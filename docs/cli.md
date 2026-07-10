# CLI Reference

The `ldraw` executable downloads LDraw libraries, generates importable Python
modules, queries parts, validates model files, and exports bills of materials.

```text
usage: ldraw [-h] command ...

Download the LDraw parts library and generate the ldraw.library Python
modules.

positional arguments:
  command
    download  Download and unpack an LDraw parts library release.
    generate  Generate the ldraw.library modules from the downloaded library.
    parts     Query the parts catalog.
    validate  Validate an LDraw file (.ldr, .mpd, or .dat).
    bom       Print a bill of materials for an LDraw model file.
    stubs     Write a type-stub package for ldraw.library into your project.
    config    Print the current configuration.
    version   Print the installed pyldraw3 version.

options:
  -h, --help  show this help message and exit
```

## Commands

- `ldraw download [--version VERSION] [--yes]` downloads and unpacks an
  LDraw release. The default version is `complete`.
- `ldraw generate [--yes] [--force]` regenerates `ldraw.library.*` from the
  currently configured release. `--force` regenerates even when already up to
  date.
- `ldraw parts search TERM [--limit N]` searches the catalog by description
  or code substring. It exits with code 1 when nothing matches.
- `ldraw parts info CODE` shows a part's description, category, file path, and
  the generated-library import to use.
- `ldraw validate FILE [--strict]` lints `.ldr`, `.mpd`, and `.dat` files.
  Malformed lines, unknown parts, and unknown colour codes are errors.
  Suspect matrices, legacy dithered colours, and unknown meta-commands are
  warnings. `--strict` makes warnings fail.
- `ldraw bom FILE [--format table|csv|json] [-o OUT]` prints a bill of
  materials counted by part and colour, with submodels expanded.
- `ldraw stubs [--out PATH]` writes an `ldraw-stubs/` PEP 561 stub package for
  IDE autocompletion of generated `ldraw.library.*` imports.
- `ldraw config` prints the current configuration as YAML.
- `ldraw version` prints the installed `pyldraw3` version.

Run `ldraw <command> --help` for a command's full option list.

## Validating files

`ldraw validate FILE` lints a single `.ldr`, `.mpd`, or `.dat` file line by
line and reports every problem it finds with the file name and 1-based line
number. It parses each line, checks part references and colours against the
catalog, and inspects transformation matrices and meta-commands.

If no parts library has been downloaded and generated yet, validation still
runs but skips the checks that need the catalog (unknown parts and unknown
colour codes). It prints a note when it does so:

```text
note: no parts library found; skipping unknown-part and colour checks
```

### Severity levels

Issues come in two severities:

- **`error`** — the line is malformed or references something that does not
  exist. Errors always make `ldraw validate` exit non-zero.
- **`warning`** — the line is legal LDraw but suspicious. Warnings are
  reported but do not fail the command by default. Pass `--strict` to make
  warnings fail as well.

### What is checked

**Errors**

| Issue | Meaning |
| --- | --- |
| malformed / unparseable line | The line does not parse as valid LDraw (bad token count, non-numeric coordinates, etc.). |
| `invalid colour value` | A colour that resolves to neither a code nor an RGB value. |
| `unknown colour code N` | A colour code with no definition in the loaded catalog. |
| `unknown part CODE` | A type-1 reference to a part that is not in the catalog and is not a submodel defined inside the file. |

**Warnings**

| Issue | Meaning |
| --- | --- |
| `legacy dithered colour code N` | A colour in the legacy dithered range 256–511. |
| `singular transformation matrix (flattens geometry)` | The part's matrix collapses it to zero volume. |
| `transformation matrix is not orthonormal (scaled or sheared part)` | The matrix scales or shears rather than only rotating. |
| `unknown meta-command !NAME` | A `0 !NAME ...` bang meta-command that is not one of the recognised LDraw/editor commands. Plain `0 STEP`-style comments are not checked. |

MPD submodels are resolved from their `0 FILE` sections, so references to
sections defined inside the same file are not flagged as unknown parts.

### Example output

A file with one bad part reference and one suspect matrix:

```console
$ ldraw validate castle.ldr
castle.ldr:12: error: unknown part 9999
castle.ldr:47: warning: singular transformation matrix (flattens geometry)
castle.ldr: 1 error(s), 1 warning(s)
```

A clean file prints a single OK line and exits `0`:

```console
$ ldraw validate castle.ldr
castle.ldr: OK
```

Making warnings fail with `--strict`:

```console
$ ldraw validate castle.ldr --strict
castle.ldr:47: warning: singular transformation matrix (flattens geometry)
castle.ldr: 0 error(s), 1 warning(s)
$ echo $?
1
```

### Exit codes

- `0` — no issues, or only warnings without `--strict`.
- `1` — one or more errors, any warning when `--strict` is set, or the file
  does not exist.

### Programmatic API

The same checks are available in Python through `iter_ldr_issues`, which
yields `ValidationIssue` records (`line_number`, `message`, `severity`) so
you can build your own tooling, editor integrations, or CI gates:

```python
from pathlib import Path

from ldraw import iter_ldr_issues
from ldraw.validation import Severity
from ldraw.parts import Parts

parts = Parts.get("~/ldraw/parts.lst")  # optional; enables catalog checks
issues = list(iter_ldr_issues(Path("castle.ldr"), parts))

errors = [i for i in issues if i.severity is Severity.ERROR]
for issue in issues:
    print(f"{issue.line_number}: {issue.severity}: {issue.message}")
```

Passing `parts=None` (or omitting it) runs the parse, matrix, and
meta-command checks but skips the unknown-part and unknown-colour checks,
mirroring the CLI's behaviour when no library is available.

## Development Commands

This project uses `uv` for dependency management and packaging.

```bash
uv sync
source .venv/bin/activate
uv run ldraw download --yes
uv run ldraw generate --yes
```

Run tests and checks:

```bash
uv run pytest
uv run pytest --cov=ldraw
uv run pytest --integration
uv run ruff format .
uv run ruff check .
uv build
```

Build and preview documentation:

```bash
uv run zensical serve
uv run zensical build --clean --strict
```

GitHub Pages must use the "GitHub Actions" publishing source. If the
repository remains configured to publish from a branch such as `gh-pages`, the
live site will continue to serve that branch instead of this workflow's
Zensical artifact.
