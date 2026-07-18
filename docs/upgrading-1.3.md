# Upgrading pyldraw3 from 1.2.0 to 1.3.0

Unlike 1.2.0's purely additive release, 1.3.0 is a **correctness release**:
it fixes long-standing behavioral bugs, which means some results change —
deliberately, because the old results were wrong. The headline fixes are a
**Y-axis rotation** that turned the wrong way, **bills of materials** that
never resolved the main colour (16) through submodels, an **import hook**
that relied on a deprecated CPython code path, and a parts loader that a
single malformed line could silently truncate. Alongside the fixes, whole
subsystems became fail-fast (colour parsing, config loading) or
fail-soft-with-warnings (parts.lst loading, categorization) instead of
failing silently or catastrophically.

This guide covers every behavior change in the release: what changed, why
the new behavior is correct, and what (if anything) you need to do.

## At a glance

**Results that change (the old ones were wrong)**

| Change | Old behavior | New behavior |
| --- | --- | --- |
| `Matrix.rotate(angle, YAxis)` | Rotated opposite to X/Z (transposed matrix) | Cyclic convention: 90° about Y maps +Z→+X |
| `Matrix.scale(...)` | Pre-multiplied (world frame), unlike `rotate` | Post-multiplies (local frame), matching `rotate` |
| `bill_of_materials()` / `ldraw bom` | Colour 16 inside submodels counted as 16 | Resolved to the colour the submodel was placed with |
| `Model.add_submodel(same_object)` | Raised `DuplicateSubmodelError` | Accepted; appends another placement piece |
| `StudReference.is_top_stud` / `Parts.stud_positions` | Counted sideways and inverted studs | Orientation-aware via the new `StudReference.up` vector |
| Validator colour checks | Warned on real colours in 256–511; missed decimal/uppercase direct colours | Catalog membership checked first; all direct-colour spellings accepted |
| `Person` limb defaults | `3815b`/`3816b`/`3817b` (absent pre-2019), hair as the default "hat" | Plain `3815`/`3816`/`3817`, plain head `3626b`, hat `3624` |

**Silent failures that now raise**

| Input | Old behavior | New behavior |
| --- | --- | --- |
| Unparseable colour token (`1 blue 0 0 0 …`) | Parsed; crashed later in `to_ldraw()` with a bare `ValueError` | `InvalidColourValueError` at parse time, with file/line context |
| `Comment("NOFILE")` / `Comment("FILE x")` serialized | Silent data loss on the next parse | `StructuralCommentError` from `to_ldraw()` / `save()` |
| `0 NOFILE` before any `0 FILE` | Rest of the document silently discarded | `MisplacedNofileError` |
| Empty part file `.description` | Bare `StopIteration` | `EmptyPartFileError` |
| Malformed/corrupt `config.yml` | `AttributeError` / raw `yaml.YAMLError` | `ConfigLoadError` naming the path and problem |

**Silent breakage that now warns and continues**

| Input | Old behavior | New behavior |
| --- | --- | --- |
| Malformed `parts.lst` line | Everything after it silently dropped | Warning; loading continues |
| Part file missing or unparseable during categorization | Whole catalog build aborted | Warning; that part is skipped |
| Descriptions containing `.dat` | Truncated the catalog | Parsed correctly (split at the first `.dat` only) |

**Removals affecting your code**

| Removed | Replacement |
| --- | --- |
| `LibraryImporter.load_module` / `find_module` / `get_code` | The modern `find_spec` protocol (see below) |
| `Vector.norm()` (in-place, returned `None`) | `Vector.normalized()` (non-mutating copy) |
| `Vector.__rsub__` / `__cmp__`, `Vector2D.__rsub__` / `__cmp__` | Dead in Python 3; nothing to migrate |
| `ldraw.utils.flatten`, `ldraw.schemas` | Unused; nothing to migrate |
| `NoLibrarySelectedError` | Was never raised; `UnwritableOutputError` is now actually raised |

## Upgrade checklist

1. Upgrade the package: `uv add "pyldraw3>=1.3.0"` (or `pip install -U pyldraw3`).
2. Do nothing for caches: both the generated `ldraw.library` package and
   the `catalog.sqlite` index self-heal. 1.3.0 bumps the generation schema
   (v3) and the catalog schema (v4), so the first run after upgrading
   regenerates both automatically.
3. If you construct rotations about the **Y axis**, or chain
   `.rotate(...).scale(...)`, re-check the results — the fixed math is
   almost certainly what you meant, but serialized output changes (see
   below).
4. If you postprocess **BOM output** for models that recolour submodels,
   expect rows split by the placed colour instead of one `colour_code=16`
   row.
5. If you catch parse errors, note that context-wrapped errors now keep
   their concrete class (`InvalidNumericValueError`,
   `InvalidColourValueError`, …) — `except PartError` still catches all of
   them.

## Geometry: the Y-rotation fix and local-frame scaling

The Y-axis rotation matrix was the transpose of the convention used for X
and Z, so composing "the same" 90° turns about different axes produced
mirrored results:

```python
from ldraw.geometry import Identity, Vector, XAxis, YAxis, ZAxis

# 1.3.0 — all three axes are cyclic:
Identity().rotate(90, XAxis) * Vector(0, 1, 0)   # → (0, 0, 1): ŷ→ẑ
Identity().rotate(90, YAxis) * Vector(0, 0, 1)   # → (1, 0, 0): ẑ→x̂  (was (-1, 0, 0))
Identity().rotate(90, ZAxis) * Vector(1, 0, 0)   # → (0, 1, 0): x̂→ŷ
```

Serialized matrices for Y rotations change sign on the two sine terms; a
model built with `rotate(angle, YAxis)` now turns the direction the other
axes always did. If you compensated for the old behavior by negating Y
angles, remove the compensation.

`Matrix.scale` previously pre-multiplied (applying the scale in the world
frame) while `rotate` post-multiplied (local frame), so chained calls
silently mixed frames. Both now compose in the **local frame**:

```python
m = Identity().rotate(90, ZAxis).scale(2, 1, 1)
m * Vector(1, 0, 0)   # → (0, 2, 0): the *local* X axis was scaled
# Equivalent identity that now holds:
m == Identity().rotate(90, ZAxis) * Identity().scale(2, 1, 1)
```

Other geometry API changes:

- `vector * scalar` now works (previously only `scalar * vector`).
- `matrix * unsupported` raises `TypeError` (was a misleading
  `MatrixError("Invalid axis specified.")`), and reflected operators of
  other types now get their chance.
- Mutable `Matrix` / `Vector` / `Vector2D` are **unhashable**, like
  `list`: their value-based hashes silently corrupted sets and dict keys
  when mutated. Use `.copy()` + a tuple key if you need one.
- `Vector.norm()` (which normalized **in place**, returned `None`, and
  crashed with `ZeroDivisionError` on the zero vector) is replaced by
  `Vector.normalized()`, which returns a unit-length copy and raises
  `ValueError` for zero-length input.
- `CoordinateSystem` fields are non-optional with unit-vector defaults;
  `project` no longer has an unreachable `MatrixError` branch.

## BOM: colour 16 resolves through submodels

`bill_of_materials()` (and `ldraw bom`) iterated raw pieces, so a
colour-16 brick inside a submodel was counted as "Main_Colour" no matter
what colour the submodel was placed with. It now traverses resolved
occurrences (`Model.iter_occurrences`), so the placed colour wins:

```python
root = Model(name="main.ldr")
arm = Model(name="arm.ldr", objects=[Piece.place("3001", colour=16)])
root.add_submodel(arm, colour=4)

root.bill_of_materials()
# 1.2.0: [BomRow(part="3001", colour_code=16, quantity=1)]
# 1.3.0: [BomRow(part="3001", colour_code=4,  quantity=1)]
```

Root-level colour-16 pieces still report code 16 (there is nothing to
inherit from). Placing the same submodel in two colours now yields two
rows, one per placed colour.

## Models: repeated submodels, structural safety, identity semantics

**`add_submodel` accepts the same object again.** Placing a subassembly
twice — and diamond-sharing a nested submodel between two parents — is the
most common LEGO modeling pattern, and it used to raise
`DuplicateSubmodelError`:

```python
root.add_submodel(wheel)
root.add_submodel(wheel, position=Vector(0, -24, 0))   # now: second placement
```

A **different** `Model` object under an already-registered name still
raises — that remains a genuine conflict.

**Round-trip integrity is now guarded on both sides.** Serializing a
comment whose text would re-parse as MPD structure (`Comment("NOFILE")`,
`Comment("FILE x")`) raises `StructuralCommentError` instead of silently
producing a document that loses content when re-read. Symmetrically,
parsing a document with `0 NOFILE` before any `0 FILE` raises
`MisplacedNofileError` instead of silently discarding everything after it.

**`Model` and `ModelOccurrence` compare and hash by identity.** Field-wise
`Model` equality was already meaningless (pieces compare by identity, and
the internal source-line map made two parses of identical text unequal);
now it is honest, and both types are hashable again. Compare content with
`m1.to_ldraw() == m2.to_ldraw()`.

Smaller model fixes:

- `Model.source_line_for(piece)` answers only for the exact parsed piece
  object; the old id-keyed map could return another piece's line after
  object churn.
- `Model.steps` drops **all** trailing empty step groups, as its docstring
  always claimed.
- `Model.description` returns `None` when the first line is a managed
  header (`Name:`, `Author:`, `BFC`), consistent with `set_header`.
- `Piece.place("car.ldr", suffix=".ldr")` no longer produces
  `car.ldr.ldr`.

## Colour parsing: fail-fast, and all direct-colour spellings

`colour_from_str` silently returned `None` for unparseable tokens,
producing a `Colour` with neither code nor rgb that exploded much later —
in `to_ldraw()`, with a bare `ValueError` and no hint where the bad token
came from. Colour fields now fail at parse time with
`InvalidColourValueError` (both a `PartError` and a `ValueError`) carrying
file and line context.

Direct colours are also parsed in every spelling other tools accept:

```python
colour_from_str("0x2FF0000")   # canonical
colour_from_str("0X2FF0000")   # uppercase prefix — was UnknownCommandError
colour_from_str("50266112")    # the same value in decimal — was a plain code
# all three → Colour(rgb="#FF0000", alpha=255)
```

Non-canonical spellings re-serialize canonically as `0x2RRGGBB`, so
byte-level round-trips change for these (rare) inputs. The 3-digit
`0x2RGB` shorthand is now rejected in **files** — CSS-style shorthand
expansion remains available in `Colour(rgb="#f00")` for user-constructed
colours, where it is a convenience rather than a spec violation.

Part files are read as `utf-8-sig`, so a UTF-8 BOM no longer breaks part
parsing (models already tolerated it).

## Validator: fewer false positives

- Colour codes are checked against the catalog **before** the
  legacy-dithered range warning, so real LDConfig colours in 256–511
  (Dark_Blue 272, Dark_Green 288, Sand_Blue 379, Dark_Orange 484, …) no
  longer warn.
- `!LDCAD` and `!STUDIO` are recognized meta-commands — files authored in
  LDCad or BrickLink Studio no longer produce per-line warning spam.
- Decimal and uppercase-prefix direct colours validate clean; garbage
  colour tokens report `Invalid colour value '<token>'` (previously
  `invalid colour value` with no token).
- `ldraw validate` and `ldraw bom` report non-UTF-8 input as an error and
  exit 1 instead of crashing with a `UnicodeDecodeError` traceback.

## Stud geometry is orientation-aware

`StudReference` gains an `up` vector — the image of the stud's local up
direction under the placing transforms. `is_top_stud` (and therefore
`Parts.stud_positions`) uses it to exclude sideways and inverted studs:

```python
parts.stud_positions("4070")   # Headlight Brick
# 1.2.0: included the sideways front stud — a brick cannot sit on it
# 1.3.0: only the genuine top stud
```

## The import hook uses the modern loader protocol

`LibraryImporter.find_spec` previously returned a spec whose loader
implemented none of the modern protocol, so every `ldraw.library` import
went through CPython's **deprecated** `load_module()` fallback — emitting
`ImportWarning` on current Pythons, breaking outright under
`-W error::ImportWarning` (or a `filterwarnings = error` test suite), and
scheduled for removal from CPython. It now returns a standard file-backed
spec, and CPython performs the load itself.

Behavior changes you might notice:

- Imports are silent under `-W error::ImportWarning`.
- When **no** generated library exists, `find_spec` returns `None`:
  `importlib.util.find_spec("ldraw.library")` is now a truthful
  availability probe, and the import raises a standard
  `ModuleNotFoundError`. A missing submodule of an *existing* generated
  library still raises `CouldNotFindModuleError` naming both candidate
  paths.
- The legacy `load_module`, `find_module`, and `get_code` members are
  gone. If you called `load_module` directly, use a normal `import` or
  `ldraw.imports.load_lib(generated_path, fullname)`.
- `set_config` / `clean` are thread-safe. Reconfiguration now waits for
  in-flight generated-module imports to finish before evicting them, rather
  than deleting their `sys.modules` entries during execution. A spec resolved
  before reconfiguration but not yet executing is rejected with
  `StaleModuleSpecError`; retry that import against the new configuration.

## Parts loading: resilient instead of brittle

One bad line in `parts.lst` used to silently **truncate the whole
catalog** (loading stopped at the first line that did not split cleanly),
and one missing `.dat` file aborted the entire categorization pass with
`PartNotFoundError`, taking `ldraw generate`, `parts`, and `bom` down with
it. Both now warn and continue: the bad line is skipped, the unloadable
part gets no catalog entry (it stays visible in `by_code`/`by_name`), and
everything else loads. Descriptions containing `.dat` — which used to
trigger the truncation — parse correctly.

Also in this area:

- Lazy categorization is **thread-safe**; concurrent first accesses no
  longer duplicate category entries in a shared instance.
- `Parts.get` expands `~` in paths, so
  `Parts.get("~/ldraw/parts.lst")` works as documented.
- `PartsCatalog.add` on an existing code now replaces the entry in every
  index (previously stale entries lingered in the category lists).
- Cross-prefix description collisions (e.g. `Minifig Torso Plain` vs
  `Torso Plain` in one module) no longer silently drop a part — both
  survive to symbol generation, where collisions get part-code suffixes.

## Freshness: `.dat` edits now invalidate caches

The catalog index and the generated library were keyed only to the MD5 of
`parts.lst` (plus LDConfig), so editing a part file's `!CATEGORY` or
`!KEYWORDS` header in place left both serving stale data forever. Both
fingerprints now hash every file's relative path, size, and nanosecond mtime
under the `parts/` and `p/` trees. Unlike the earlier aggregate
count/total-size/newest-mtime scheme, renames and offsetting metadata changes
cannot collide. Schema versions remain catalog v4 and generation v3; an older
aggregate fingerprint mismatches automatically, so the first run after
upgrading rebuilds both.

Generated modules are also **compile-checked before the generation is
marked fresh**, and code values are emitted with `repr()` — a part code
containing a backslash can no longer be corrupted by octal-escape
interpretation, and a pathological description can no longer produce an
unimportable module (invalid identifiers are skipped with a warning;
digit-leading ones get a `P` prefix). Generated `Colour` objects now carry
the LDConfig name (`ColoursByName["Two-tone"].name == "Two-tone"`), not
the sanitized identifier. Distinct colour names that sanitize to the same
Python symbol now receive colour-code suffixes, so their `ColoursByCode` and
`ColoursByName` entries cannot silently reference the last assignment.

`ldraw stubs` clears the previous `ldraw-stubs` output before writing, so
stale `.pyi` files no longer advertise symbols that are gone.

## CLI and configuration hardening

- **Errors and diagnostics go to stderr.** Piping `ldraw bom` or
  `ldraw parts` output no longer mixes error text into the data stream.
- `ldraw parts search` normalizes whitespace, so `"arch 1 x 6"` matches
  the column-aligned catalog description `Arch  1 x  6`.
- `ldraw generate` before `ldraw download` prints
  ``run `ldraw download` first`` instead of a `FileNotFoundError`
  traceback, and an unwritable output directory actually produces the
  friendly `UnwritableOutputError` message (the handler existed; the
  exception was never raised).
- A malformed `config.yml` (bad YAML, a list instead of a mapping, a falsey
  scalar, a non-string value, or a directory at the path) raises
  `ConfigLoadError` with the path and reason — previously every CLI command
  crashed with a raw traceback or silently treated falsey non-mappings as an
  empty config. `Config.write` uses a unique sibling temporary file and atomic
  rename, so concurrent writers do not share `config.yml.tmp`; failed writes
  clean up their temporary files.
- If a download succeeds but persisting its selected library path fails, the
  CLI now prints `Could not update configuration: ...` and exits 1 instead of
  showing a traceback.
- Importing `ldraw` no longer creates config/cache directories on disk;
  directories are created when first needed, so the import works in
  read-only environments.
- Network requests carry a 30-second timeout; a stalled server no longer
  hangs `ldraw download` or `ensure_library` forever. Interrupted
  downloads clean up their `.part` file.
- Dashed release ids (`2024-01`) are preserved in full when recording the
  downloaded complete-library release (previously truncated to `01`), and the
  parser now requires the ID to be its own dashed segment instead of accepting
  a malformed suffix such as `zipfoo2024-01`.
- A cached `complete.zip` (only ever left behind by a failed unpack) is
  discarded instead of reused — the complete release is a moving target.
  Versioned archives still cache (their tags are immutable).
- Archive-wrapper entries are checked for case-insensitive collisions before
  anything is hoisted. An archive containing both `LDRAW` and `ldraw` now fails
  without deleting either tree.
- `ensure_library` wraps *all* download failures (including
  `CouldNotDetermineLatestVersionError` and `OSError`) in the documented
  `RuntimeError`.

`LDrawSession.rebuild_index()` uses the same unique-temporary-file rule for
`catalog.sqlite`, preventing concurrent rebuilds from replacing or unlinking
one another's work.

## Minifigure defaults that exist everywhere

`Person`'s default hips and legs were `3815b` / `3816b` / `3817b` —
variants that only exist in libraries from 2019 onwards. The defaults are
now the plain codes `3815` / `3816` / `3817`, which resolve in every
library vintage (modern libraries keep them as moved-to aliases). The
default head is a plain `3626b` instead of a Star Wars-patterned head
(`HeadWithSwSmirkAndBrownEyebrowsPattern` remains available as an explicit
constant), and the default hat is an actual hat (`3624`, police hat)
instead of hair — `3901` is `Minifig Hair Male`.

Two figure bug fixes: `hat()` no longer shares its position `Vector` with
the head (mutating one no longer moves the other), and the
`dependent_piece` machinery no longer swallows `KeyError`s raised *inside*
a limb method — a missing anchor still returns `None`, but a genuine bug
in your subclass propagates.

## Errors: context without class-erasure

Wrapping a parse error with file/line context used to re-raise it as the
base `PartError`, so `except InvalidNumericValueError:` never matched
errors that came through `Part.objects` or `parse_model`. The concrete
class is now preserved — the message is identical, and `PartError` gains
`source` and `line_number` attributes carrying the context in structured
form:

```python
try:
    read_model("broken.ldr")
except InvalidNumericValueError as exc:   # now catchable by concrete class
    print(exc.source, exc.line_number)
```

New exception types you can catch: `InvalidColourValueError`,
`EmptyPartFileError`, `StructuralCommentError`, `MisplacedNofileError`
(all `PartError` subclasses), `ConfigLoadError`, and
`GeneratedModuleSyntaxError`.
