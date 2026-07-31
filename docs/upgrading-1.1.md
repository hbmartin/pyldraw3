# Upgrading pyldraw3 from 1.0.0 to 1.1.0

pyldraw3 1.1.0 adds part geometry queries, a building-step API, submodel
views, colour finish detection, and convenience lookups — and it changes a
few behaviors you may have code pinned against, most notably **part
reference case preservation** and **`Parts.part()` raising instead of
returning `None`**.

This guide covers every API change in the release: what changed, why, how
to migrate, and what the new APIs are good for.

## At a glance

**New APIs**

| API | What it does |
| --- | --- |
| `Parts.bounding_box(code)` | Axis-aligned bounding box of a part, in LDU |
| `Parts.studs(code)` / `Parts.stud_positions(code)` | Stud primitives a part places / positions of its top studs |
| `BoundingBox`, `StudReference` | Value objects for the geometry queries, exported at top level |
| `Model.add_step()` / `Model.steps` | Write and read `0 STEP` building-step markers |
| `Model.set_header(ldraw_org=..., license=...)` | Write `0 !LDRAW_ORG` / `0 !LICENSE` header metas |
| `Model.submodel_view(name)` | A submodel view that resolves nested references against the root |
| `Parts.find_part(...)` | `None`-returning variant of `part()` |
| `Parts.description_for(code)` | Cheap, case-tolerant code → description lookup |
| `Colour.is_solid` | Whether a colour is plain opaque paint (no alpha, no finish) |
| `symbol_description(description)` | The description generated symbol names derive from |

**Behavioral changes**

| Change | Impact |
| --- | --- |
| Piece part/suffix case is preserved | `Piece.place("3001").reference` is now `"3001.dat"`, not `"3001.DAT"` |
| `Parts.part()` always raises on a miss | Code that checked `part(...) is None` must use `find_part()` |
| `Colour.rgb` canonicalized to `#RRGGBB` | String comparisons against other forms (`"4B0082"`, lowercase) break |
| Minifig descriptions kept as written | Catalog, BOM, and `ldraw parts` output show `Minifig Torso`, not `Torso` |
| `PartCategory` synced with LDraw.org (27 new members) | Parts leave `OTHER`; new `ldraw.library.parts.*` modules appear |
| Colour finish detection expanded | `GLITTER`, `SPECKLE`, `LUMINANCE` now appear in `colour_attributes` |

**Removals**

| Removed | Replacement |
| --- | --- |
| `ldraw.config.is_valid_config_file`, module-level `parser` | None needed — pass a path to `get_config()` / `Config.load()` |
| `ldraw.errors.InvalidConfigFileError` | No longer raised anywhere |

## Upgrade checklist

1. Upgrade the package: `uv add pyldraw3>=1.1.0` (or `pip install -U pyldraw3`).
2. Do nothing for caches: the parts catalog (`catalog.sqlite`) and the
   generated `ldraw.library` package both detect they are stale and rebuild
   themselves on first use. To rebuild eagerly instead, run
   `ldraw generate --force` followed by `ldraw stubs`.
3. Search your code for the migration patterns below:

| Search for | Why |
| --- | --- |
| comparisons of `.part` / `.reference` / `.suffix` to uppercase literals | case is now preserved; compare with `casefold()` |
| `".DAT"` | `DEFAULT_SUFFIX` is now `".dat"` |
| `parts.part(...)` followed by an `is None` check | `part()` now raises; switch to `find_part()` |
| comparisons of `Colour.rgb` to non-`#RRGGBB` strings | `rgb` is canonicalized on construction |
| code stripping or expecting a stripped `"Minifig "` prefix | descriptions are now kept as written |
| `InvalidConfigFileError`, `is_valid_config_file` | removed |
| golden `.ldr`/`.mpd` output files | newly built pieces serialize with lowercase `.dat` |

## Behavioral changes in detail

### Part reference case is now preserved

This is the change most likely to touch your code. In 1.0.0, `Piece`
uppercased the part name and suffix on construction, so every reference
serialized as `3001.DAT` regardless of input. In 1.1.0, case is preserved
end to end, and every comparison casefolds instead:

```python
from ldraw.pieces import Piece

piece = Piece.place("3001")
piece.reference
# 1.0.0: "3001.DAT"
# 1.1.0: "3001.dat"

parsed = Piece.place("Sub-Assembly.LDR")
parsed.reference
# 1.0.0: "SUB-ASSEMBLY.LDR"
# 1.1.0: "Sub-Assembly.LDR"  (exactly as written)
```

What this buys you:

- Files **round-trip byte-identically**: reading a model and writing it
  back no longer rewrites every reference line to uppercase.
- MPD submodel references match their `0 FILE` sections exactly, so other
  LDraw tools that compare references literally stay happy.
- New output uses the library's canonical lowercase filenames
  (`3001.dat`), matching what LDraw.org actually ships.

The related constants and helpers changed to match:

- `ldraw.pieces.DEFAULT_SUFFIX` is `".dat"` (was `".DAT"`).
- `ldraw.utils.split_reference` no longer uppercases the stem or
  extension.

Lookups and comparisons are case-insensitive, so behavior-level code keeps
working without changes:

- `Model.find_pieces(part="3001")` matches `3001`, `3001.DAT`, and
  `3001.dat` pieces alike.
- `Model.bill_of_materials()` counts part codes case-insensitively and
  displays each code as it was first written in the model.
- `Parts.description_for(code)` (new, see below) tolerates any casing.

**Migration:** anywhere you compared `piece.part`, `piece.suffix`, or
`piece.reference` against an uppercase literal, casefold both sides:

```python
# 1.0.0 (relied on forced uppercase)
if piece.part == "3001":  # worked because .part was uppercased anyway
    ...
if piece.reference == "3001.DAT":
    ...

# 1.1.0
if piece.part.casefold() == "3001":
    ...
if piece.reference.casefold() == "3001.dat":
    ...
```

If you keep golden `.ldr` output files in tests, regenerate them once:
pieces built in code now serialize with lowercase `.dat`.

### `Parts.part()` raises; `Parts.find_part()` returns `None`

In 1.0.0, `Parts.part()` had a split personality: it returned `None` for
an unknown description, an unresolvable subdirectory code, or missing
arguments, but raised a generic `PartError` for a missing part file. In
1.1.0 the contract is unified:

- `part(description=...)` or `part(code=...)` **raises
  `PartNotFoundError`** on every miss — unknown description, unknown code,
  bad subdirectory reference, or missing file.
- Calling `part()` with **neither argument raises `ValueError`** (it used
  to silently return `None`).
- The new **`find_part()`** is the lookup that returns `None` instead of
  raising, with the same signature.

```python
from ldraw import Parts
from ldraw.errors import PartNotFoundError

parts = Parts.get("path/to/parts.lst")

# 1.0.0
part = parts.part(code="3001")
if part is None:
    handle_missing()

# 1.1.0 — either let the precise error propagate...
try:
    part = parts.part(code="3001")
except PartNotFoundError:
    handle_missing()

# ...or keep the None-flavored flow with find_part()
if (part := parts.find_part(code="3001")) is None:
    handle_missing()
```

`PartNotFoundError` carries `.code` and `.path` attributes, so error
messages can say exactly which library missed which code.

### `Colour.rgb` is canonicalized to `#RRGGBB`

`Colour.__post_init__` now rewrites `rgb` to canonical form — a leading
`#` followed by six uppercase hex digits — for **all** colours, whatever
form the value was given in. Malformed values raise `ValueError` at
construction time rather than surfacing at write-out.

```python
from ldraw.colour import Colour

Colour(rgb="4b0082").rgb  # "#4B0082"
Colour(rgb="#4b0082").rgb  # "#4B0082"
Colour(rgb="nonsense")  # ValueError, immediately
```

In 1.0.0, `rgb` kept whatever string you passed, and only code-less
(direct) colours were validated. Equality between direct colours is
unaffected — it already normalized internally — but code comparing `rgb`
strings directly must expect the canonical form.

Related hardening: `Parts` now **skips a malformed `VALUE` token in
`LDConfig.ldr` with a warning** instead of crashing the whole colour load,
and the values stored in the legacy `Parts.colours` dict are canonical.

### Minifig descriptions are kept as written

In 1.0.0, the catalog stripped the `Minifig ` prefix from part
descriptions at load time, so a BOM or `ldraw parts` search showed `Torso`
where the library says `Minifig Torso`. In 1.1.0:

- The catalog, BOM descriptions, and `ldraw parts` search/info output show
  descriptions **exactly as written in `parts.lst`** (`Minifig Torso`).
- Generated symbol names are **unchanged** — the stripping moved into the
  new `ldraw.parts.symbol_description()` helper, applied only at code
  generation time, so `ldraw.library.parts.minifig.torsos.Torso` still
  generates byte-identically.
- `CATALOG_SCHEMA_VERSION` was bumped to 3, so an existing
  `catalog.sqlite` rebuilds itself automatically on first use.

**Migration:** only needed if you matched catalog or BOM descriptions
against pre-stripped text. Match the real library descriptions, or apply
`symbol_description()` yourself when you want the symbol-name form.

### `PartCategory` synced with the official LDraw.org list

`PartCategory` gained 27 members: `BRACKET`, `CLIKITS`, `COCKPIT`,
`CONSTRACTION_ACCESSORY`, `CONVEYOR`, `DUPLO`, `EXHAUST`, `FLAG`,
`FORKLIFT`, `GARAGE`, `GLASS`, `GRAB`, `LADDER`, `LEVER`, `MONORAIL`,
`PANEL`, `PLATFORM`, `RACK`, `ROCK`, `SCALA`, `STRING`, `TAIL`, `TIPPER`,
`TRACTOR`, `TRAILER`, `WEDGE`, and `ZNAP`.

Effects you will notice:

- Parts that previously landed in `PartCategory.OTHER` are now properly
  categorized — against the 2018-02 library, `OTHER` shrank from roughly
  700 parts to 27, and every unknown-category warning disappeared.
- The generated library gains corresponding modules:
  `from ldraw.library.parts.panels import Panel1X2X1` now works (panels
  alone gained 187 importable symbols), likewise `duplo`, `wedges`,
  `flags`, and so on.
- Code that special-cased `PartCategory.OTHER` (for example, treating it
  as "everything uncategorized") will see far fewer parts there.

The library regenerates automatically (see the fingerprint section below),
after which run `ldraw stubs` to refresh IDE autocomplete for the new
modules.

### Colour finish detection expanded

`Parts.ColourAttributes` now recognizes `GLITTER`, `SPECKLE`, and
`LUMINANCE` in addition to `CHROME`, `PEARLESCENT`, `RUBBER`,
`MATTE_METALLIC`, and `METAL`. Colours parsed from `LDConfig.ldr` that
carry these finishes now report them in `colour_attributes` — for
example, colour 114 (Glitter Trans Dark Pink) now loads with
`alpha=128` and `["GLITTER"]` where 1.0.0 reported it as plain.

`MATERIAL` was deliberately left out: it always co-occurs with `GLITTER`
or `SPECKLE` and would only add noise.

**Migration:** code that assumed `colour_attributes` could only contain
the original five tokens should handle the three new ones. Pair this with
the new `Colour.is_solid` property (below) if what you actually wanted was
"is this a plain paint colour?".

### Config loading no longer sniffs `sys.argv`

In 1.0.0, importing `ldraw.config` installed a module-level
`argparse` parser and `get_config(None)` would parse the **host
process's** command line looking for `--config` — meaning a `--config`
flag in an application embedding pyldraw could `SystemExit` the app. In
1.1.0:

- `get_config(None)` simply returns the default `CONFIG_FILE` path.
  `Config.load()` never inspects `sys.argv`.
- `ldraw.config.is_valid_config_file` and the module-level `parser` are
  **removed**.
- `ldraw.errors.InvalidConfigFileError` is **removed**.

**Migration:** if you relied on `--config` reaching pyldraw through the
command line, pass the path explicitly instead:

```python
from ldraw.config import Config

config = Config.load(config_file="/path/to/config.yml")
```

(No CLI feature was lost: `ldraw --config ...` never actually worked — the
CLI's own parser rejected the flag as unrecognized.)

### Generated library self-heals across upgrades

The generated `ldraw.library` package's staleness check is now a
fingerprint of three inputs instead of just the `parts.lst` MD5:

1. `GENERATION_SCHEMA_VERSION` (new module constant, bumped whenever
   generator output changes),
2. the `parts.lst` MD5,
3. the `ldconfig.ldr` MD5.

A change to **any** of the three — including upgrading pyldraw itself —
triggers regeneration automatically. Practically: the first
`ldraw generate` (or generation-triggering import) after upgrading to
1.1.0 rebuilds the library so it picks up the new categories, colour
attributes, and symbol deduplication without you passing `--force`.

Two smaller generation improvements ship alongside:

- **Colliding symbol names are deduplicated.** Distinct descriptions that
  sanitize to the same Python identifier (e.g. the three
  `Tile 1 x 1 with Silver "." / "-" / "@" Pattern` variants, which all
  became `Tile1X1WithSilver_Pattern` and silently shadowed each other in
  1.0.0) now each get a part-code suffix, with a warning logged. All
  variants are importable. The impossible case — still colliding after
  suffixing — raises the new
  `ldraw.generation.exceptions.DuplicateSymbolError`.
- `ldraw generate` ends by reminding you to run `ldraw stubs` to refresh
  the `ldraw-stubs` package for IDE autocomplete and type checking.

## New APIs and what to build with them

### Part geometry queries: bounding boxes and studs

The headline feature of 1.1.0. Three new methods on `Parts` answer the two
questions a placement tool needs — *how big is this part* and *where are
its studs* — without you reading `.dat` files by hand:

```python
from ldraw import Parts

parts = Parts.get("path/to/parts.lst")

box = parts.bounding_box("3001")  # 2 x 4 brick
box.min, box.max  # Vector(-40, -4, -20), Vector(40, 24, 20)
box.size  # Vector(80, 28, 40) — LDU; multiply by 0.4 for mm

studs = parts.studs("3001")  # every stud primitive, incl. underside tubes
tops = parts.stud_positions("3001")  # 8 top-stud positions for a 2 x 4 brick
```

The supporting types are exported at the top level:

- **`BoundingBox`** — frozen dataclass with `min` and `max` corner
  `Vector`s, a `size` property, and a `corners()` method returning all
  eight corner points. Remember LDraw's Y axis points *down*: `min.y` is
  the highest point of the part (stud tops), `max.y` the lowest.
- **`StudReference`** — frozen dataclass with `name` (casefolded primitive
  stem, e.g. `stud` or `stud4`), `description` (the primitive's header
  description, e.g. `Stud Tube Open`), `position` (a `Vector` in the
  part's own coordinates), and an `is_top_stud` property that reports
  whether a brick above could sit on it. `Parts.studs()` returns every
  stud primitive including underside tubes; `Parts.stud_positions()`
  pre-filters to top studs for you.

Error handling: an unknown code raises `PartNotFoundError`; a part that
draws no geometry at all raises the new `ldraw.errors.NoGeometryError`.
Unresolvable subfiles inside a part are skipped with a logged warning
rather than failing the whole query.

How it works, so you can trust the numbers: the part's subfile tree is
resolved recursively with memoized per-file geometry, so repeated queries
are cheap. Boxes are composed by transforming the eight corners of each
child box — exact under the axis-aligned rotations that dominate the
library, slightly conservative (never too small) under oblique ones. Stud
classification is judged from each primitive's own description
(`tube`/`underside`/`placeholder` → not a top stud), not a pinned name
list, so hollow studs and underside tubes classify correctly.

Things these enable:

- **Programmatic building.** Query a brick's top studs, then place the
  next piece exactly one plate (8 LDU) or brick (24 LDU) above a stud
  position — no hardcoded offset tables.
- **Collision and fit checks.** Intersect bounding boxes to detect
  overlapping pieces in a generated model before writing it out.
- **Scene framing.** Fold the boxes of every piece (transformed by
  `piece.matrix` / `piece.position`) to get whole-model bounds for camera
  placement or centering.
- **Real-world dimensions.** `box.size` times 0.4 gives millimetres, for
  documentation or 3D-print scaling.

If you need the machinery underneath, `ldraw.part_geometry` exposes the
functional forms `part_bounding_box(parts, code)` and
`part_studs(parts, code)`.

### Building steps: `Model.add_step()` and `Model.steps`

Models can now express LDraw's `0 STEP` building-instruction markers:

```python
from ldraw import Model

model = Model(name="tower.ldr")
model.add(base_plate)
model.add_step()  # end of step 1
model.add(first_brick, second_brick)
model.add_step()  # end of step 2
model.add(roof)

for number, step in enumerate(model.steps, start=1):
    print(f"Step {number}: {len(step)} piece(s)")
```

`Model.steps` groups the model's own pieces by `0 STEP` markers and works
on parsed files too, so you can read any published model and walk its
instruction steps. The edge cases are handled the way you'd hope: a model
without any `0 STEP` lines is a single step, and a trailing marker does
not produce a phantom empty step. Note that submodel references are not
expanded — steps are per file, as in the format itself.

Uses: generating step-by-step building instructions, rendering
progressive snapshots (steps 1..n) of a model, or analyzing the pacing of
existing instruction files.

### OMR-compliant headers: `set_header(ldraw_org=..., license=...)`

`Model.set_header()` gained two keyword arguments that write the
`0 !LDRAW_ORG` and `0 !LICENSE` meta commands, placed after any
`Name:`/`Author:` comments in canonical header order:

```python
model.set_header(
    description="My Model",
    name="my-model.ldr",
    author="Jane Builder",
    ldraw_org="Model",
    license="Licensed under CC BY 4.0 : see CAreadme.txt",
)
```

Calling it again replaces the existing meta lines rather than duplicating
them. If you publish models to the LDraw Official Model Repository (OMR)
or want files that pass strict header checks, this saves you from
splicing meta lines into `Model.objects` manually.

### `Model.submodel_view(name)`: correct iteration over one submodel

This fixes a subtle trap with multi-file (`.mpd`) models. A model taken
straight from the `Model.submodels` dict has an **empty submodel table**,
so iterating it treats references to sibling submodels as leaf pieces —
your BOM quietly counts a submodel reference as if it were a part.

`submodel_view()` returns the same submodel as a **live view sharing the
root's submodel table**, so nested references expand correctly:

```python
from ldraw import read_model

root = read_model("castle.mpd")

# The trap (still works, still wrong for nested references):
wing = root.submodels["wing.ldr"]
rows = wing.bill_of_materials()  # sibling submodel refs counted as parts!

# The fix:
wing = root.submodel_view("wing.ldr")
rows = wing.bill_of_materials()  # nested references expanded correctly
list(wing.iter_pieces())  # likewise
wing.find_pieces(part="3001", recursive=True)
```

Details worth knowing:

- The name is matched case-insensitively; asking for the root's own name
  returns the root itself.
- An unknown name raises the new `ldraw.errors.UnknownSubmodelError`
  instead of returning something silently wrong.
- It is a *view*, not a copy — its objects and submodel table are shared
  with the root, so mutations through the view affect the original model.

Uses: per-submodel bills of materials, counting how many of each part a
single assembly needs, or analyzing one section of a large MPD without
flattening the whole file.

### `Parts.description_for(code)`: cheap description lookup

A convenience for the common "what is part `3001` called?" question:

```python
parts.description_for("3001")  # "Brick  2 x  4" (as written in parts.lst)
parts.description_for("30071B")  # found even though parts.lst says "30071b"
parts.description_for("nonsense")  # None
```

Two properties make it preferable to poking `parts.by_code` yourself:

- **Case-tolerant.** `Piece.part` preserves whatever casing the source
  file used (see the case-preservation change above), while `parts.lst`
  codes are typically lowercase. The lookup tries the code as given, then
  lowercased, then uppercased.
- **Cheap.** It reads the inexpensive `by_code` dict and never triggers
  the expensive full categorization pass, so it is safe to call in a hot
  loop over `model.iter_pieces()`.

Uses: labeling pieces in UIs or reports, enriching custom BOM-like
outputs, log messages. (The built-in `bill_of_materials` now uses it
internally for its description column.)

### `Colour.is_solid`: filtering for plain paint

A new property that reports whether a colour is plain opaque paint — full
alpha (or none given) and no finish attributes:

```python
solid_palette = [colour for colour in parts.colours_by_code.values() if colour.is_solid]
```

This composes with the expanded finish detection: transparent, chrome,
pearlescent, rubber, metallic, glitter, speckle, and luminous colours all
report `is_solid == False` when loaded from a parts catalog.

One caveat from the docstring worth repeating: the judgment is made from
the data *on the instance*. A bare `Colour(code=4)` placeholder carries
neither alpha nor attributes and so reads as solid — when you need to
judge the real palette entry, look the code up in
`parts.colours_by_code` first.

Uses: restricting random or generated colour choices to plain colours,
separating "special finish" parts in a BOM, palette pickers.

### `symbol_description(description)`: description → symbol-name form

A small helper in `ldraw.parts` exposing the transformation code
generation applies to minifig descriptions: `Minifig Torso` →
`Torso`, everything else passes through unchanged. Use it when you want
to derive the generated class name for a catalog entry the same way
`ldraw generate` does — for example, when building your own import
suggestions or documentation from `CatalogEntry` descriptions.

