# How `ldraw.library.*` imports work

One of pyldraw3's most surprising features is that this works:

```python
from ldraw.library.parts.bricks import Brick2X4
from ldraw.library.colours import Light_Grey
```

…even though there is **no `bricks.py` in the `ldraw` package**, and nothing
named `Brick2X4` was written by hand anywhere in the source tree. If you clone
the repository and go looking for `ldraw/library/parts/bricks.py`, you will not
find it. Yet the import succeeds, your IDE can be made to autocomplete it, and
`Brick2X4` is a real string you can pass to `Piece`.

This page explains the machinery that makes that work: a custom **meta path
import hook** (`LibraryImporter`) that resolves the `ldraw.library` namespace
to files that `ldraw generate` writes into a per-user cache directory.

## Why it is generated instead of shipped

The LDraw parts library is huge — the `complete` release is tens of thousands
of parts — and it is versioned and updated independently of pyldraw3. Shipping
a hand-written Python module for every part would be enormous, would go stale
the moment LDraw published a new release, and would force everyone to carry
parts they never use.

Instead, pyldraw3 ships **no** parts modules. You download an LDraw release
(`ldraw download`) and then **generate** Python modules from *your* copy of it
(`ldraw generate`). The generator turns each part's catalog description into a
Python identifier — `"Brick  2 x  4"` becomes `Brick2X4` — and writes out a
tree of modules. Because the modules are derived from whichever release you
configured, two users on different LDraw releases get different (but
correctly matching) `ldraw.library.*` contents.

That generated tree does not live inside the installed `ldraw` package. It
lives in an OS-appropriate cache directory (`generated_path`, see
[Configuration](index.md)). Something has to bridge the gap between the import
statement `from ldraw.library.parts.bricks import Brick2X4` and a file sitting
in a cache folder somewhere else on disk. That something is `LibraryImporter`.

## What gets generated, and where

`ldraw generate` writes a package rooted at `<generated_path>/library/`:

```text
<generated_path>/
└── library/
    ├── __init__.py          # ldraw.library
    ├── py.typed
    ├── colours.py           # ldraw.library.colours   (Light_Grey, Red, …)
    └── parts/
        ├── __init__.py      # ldraw.library.parts
        ├── bricks.py        # ldraw.library.parts.bricks   (Brick2X4, …)
        ├── …
        └── minifig/
            ├── __init__.py  # ldraw.library.parts.minifig
            ├── accessories.py
            ├── torsos.py
            └── …
```

Each leaf module is a flat list of `Name = "code"` assignments — for example
`Brick2X4 = "3001"` — grouped into modules by the part's catalog category, with
nested subpackages (`minifig/…`) for subcategories. That is the entire trick on
the *content* side: the names you import are plain string constants holding
LDraw part codes.

The bridge from the dotted module name to these files is the import hook.

## The import hook

CPython lets you extend the import system by adding **finders** to
`sys.meta_path`. When you write `import ldraw.library.parts.bricks`, the
interpreter asks each finder on `sys.meta_path`, in order, "can you handle this
module?" — and the first one that says yes provides a **loader** that produces
the module object. This is the mechanism described in Python's import
reference; `LibraryImporter` (in [`ldraw/imports.py`](https://github.com/hbmartin/pyldraw3/blob/main/ldraw/imports.py))
is one such finder, acting as its own loader.

### Registration

The hook is installed the moment you `import ldraw`. At the bottom of
`ldraw/__init__.py`:

```python
library_importer_instance = LibraryImporter()
if not any(isinstance(hook, LibraryImporter) for hook in sys.meta_path):
    sys.meta_path.insert(0, library_importer_instance)
```

It is inserted at position `0` so it is consulted *before* the standard
finders, and the `isinstance` guard makes registration idempotent — importing
`ldraw` more than once will not stack duplicate hooks. From then on, any
import of `ldraw.library` or a submodule is routed through this instance.

### Claiming only the right names

The hook is careful to claim **only** the `ldraw.library` namespace and
nothing else, so it never interferes with ordinary imports:

```python
VIRTUAL_MODULE = "ldraw.library"

@staticmethod
def valid_module(fullname: str) -> bool:
    if fullname.startswith(VIRTUAL_MODULE):
        rest = fullname[len(VIRTUAL_MODULE):]
        return not rest or rest.startswith(".")
    return False
```

So `ldraw.library`, `ldraw.library.colours`, and
`ldraw.library.parts.minifig.accessories` are all claimed, but
`ldraw.librarything` (which merely *starts with* the string) is not — the
`rest` after the prefix has to be empty or begin with a `.`. For any name it
does not recognise, the finder returns `None` and the interpreter moves on to
the next finder, exactly as if `LibraryImporter` were not there.

### Finding and loading

For a claimed name, `find_spec` hands back a spec whose loader is the hook
itself:

```python
def find_spec(self, fullname, path, target=None):
    if self.valid_module(fullname):
        return importlib.util.spec_from_loader(fullname, self)
    return None
```

(`find_module` is also implemented for older callers; both funnel through
`valid_module`.)

Loading then maps the dotted name to a file on disk in `load_lib`. The `ldraw`
prefix is stripped, the remaining components become a path under
`<generated_path>`, and the last component is resolved to either a package
(`…/name/__init__.py`) or a plain module (`…/name.py`):

```python
def load_lib(library_path, fullname):
    dot_split = fullname.split(".")
    dot_split.pop(0)                       # drop "ldraw"
    lib_name = dot_split[-1]
    library_root = Path(library_path)
    lib_dir = library_root.joinpath(*dot_split[:-1]) if len(dot_split) > 1 else library_root

    init_path = lib_dir / lib_name / "__init__.py"
    py_path = lib_dir / f"{lib_name}.py"
    module_path = init_path if init_path.exists() else py_path
    # …spec_from_file_location + exec_module…
```

The module is registered in `sys.modules` before execution and popped back out
again if execution raises, so a failed import never leaves a half-initialised
module cached.

### Worked example

Resolving `from ldraw.library.parts.bricks import Brick2X4`:

1. The interpreter walks `sys.meta_path`; `LibraryImporter` is first.
2. `valid_module("ldraw.library.parts.bricks")` → `True`, so `find_spec`
   returns a spec pointing at the hook as loader.
3. `load_module` resolves the configuration (see below) to find
   `generated_path`, then calls `load_lib`.
4. `load_lib` strips `ldraw`, leaving `["library", "parts", "bricks"]`. It looks
   for `<generated_path>/library/parts/bricks/__init__.py` (a package) and, not
   finding it, falls back to `<generated_path>/library/parts/bricks.py` (a
   module) — which exists.
5. That file is loaded as the module `ldraw.library.parts.bricks`; it contains
   `Brick2X4 = "3001"`, so the name binds to the string `"3001"`.

Along the way the parent packages `ldraw.library` and `ldraw.library.parts`
are imported the same way, each resolving to its generated `__init__.py`.

## Where the configuration comes from

`load_module` has to know *which* `generated_path` to read from. It resolves
the configuration in priority order:

```python
config = self.config or self._default_config or Config.load()
```

- **`self.config`** — a `Config` passed to a specific `LibraryImporter`
  instance (rarely needed).
- **`self._default_config`** — a process-wide default set via
  `LibraryImporter.set_config(config)`. The [`LDrawSession` / `ensure_library`
  setup API](upgrading-1.2.md) uses this to point the importer at the library
  it just prepared.
- **`Config.load()`** — the persisted YAML configuration written by
  `ldraw download` / `ldraw generate`, used when nothing else set a default.

That is why, in the common case, you never touch the importer at all: the CLI
wrote a config file, and the hook reads it on the first `ldraw.library.*`
import.

## Reconfiguring at runtime: `set_config` and `clean`

Switching to a different generated library within a running process needs more
than a new config — Python caches imported modules in `sys.modules`, so the
old `ldraw.library.*` modules would keep being returned. `set_config` handles
both halves:

```python
@classmethod
def set_config(cls, config):
    cls._default_config = config
    cls.clean()
```

`clean` evicts every cached `ldraw.library*` module from `sys.modules` (and
drops the `library` attribute off the `ldraw` module object), so the next
import re-resolves against the new `generated_path`. This is what lets an
application point pyldraw3 at a freshly generated library — after switching
LDraw releases, say — without restarting.

## Why your IDE can't see it (and the fix)

Because the modules only exist after generation, in a cache directory outside
your project, static analysers (Pylance, pyright, mypy) have nothing to index —
the import hook runs at *runtime*, but type checkers work *statically* and do
not execute it. So editors show `ldraw.library.parts.bricks` as an unresolved
import even though it runs fine.

The fix is `ldraw stubs`, which writes a PEP 561 `ldraw-stubs/` package of
`.pyi` files mirroring the generated modules into your project, where your
checker can find them:

```bash
ldraw stubs
```

Regenerate the stubs whenever you change LDraw releases. See the `README`'s
"IDE Autocompletion and Type Checking" section for details.

## Summary

- pyldraw3 ships no parts modules; `ldraw generate` writes them into a
  per-user cache (`<generated_path>/library/…`) from your downloaded release.
- `LibraryImporter`, inserted at the front of `sys.meta_path` when you
  `import ldraw`, claims only the `ldraw.library` namespace and loads those
  cache files on demand.
- It resolves which library to use from an explicit config, a process default
  (`set_config`), or the persisted CLI configuration.
- `set_config` / `clean` allow switching libraries at runtime by evicting the
  cached modules.
- Static tools can't see the generated modules, so `ldraw stubs` emits stub
  files for IDE autocompletion and type checking.
