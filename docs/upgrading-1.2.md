# Upgrading pyldraw3 from 1.1.0 to 1.2.0

pyldraw3 1.2.0 is a **purely additive** release. Unlike 1.1.0, it changes
no existing behavior and removes no public API — every code path that
worked against 1.1.0 keeps working unchanged. The headline is a new
**session and setup API** (`LDrawSession` / `ensure_library`) for
embedding pyldraw in applications, backed by structured **progress
events**. Alongside it ship whole-model geometry summaries, per-piece
**model occurrences** with transform and source context, part-file
reference introspection, and a handful of colour and catalog convenience
accessors.

This guide covers every new API in the release: what it does, why it
exists, and what to build with it.

## At a glance

**New APIs**

| API | What it does |
| --- | --- |
| `ensure_library(...)` | One call that downloads, generates, and indexes everything a configured library needs |
| `LDrawSession` | Manage one configured catalog + generated library; `state()`, `load()`, `rebuild_index()`, `open_model()` |
| `LDrawState` / `LDrawStateReason` | Classify what (if anything) is stale or missing before doing work |
| `LDrawPaths` | Resolved filesystem paths for one configuration |
| `ProgressEvent` / `ProgressStage` | Structured progress updates from long-running setup operations |
| `Model.iter_occurrences()` | Yield placed leaf parts with world transform, colour, step, and source context |
| `ModelOccurrence` | Value object for one placed part occurrence |
| `Model.source_line_for(piece)` | The source line a parsed piece came from |
| `ModelSummary` / `model_bounds()` | Whole-model bounds, part counts, colour usage, skipped-geometry report |
| `SkippedGeometry` | A part whose geometry could not be folded into the model bounds |
| `Parts.references_for(code)` | Type-1 subfile references a part places, optionally recursive |
| `PartReference` / `PartReferenceKind` | Value object + classification (part / subpart / primitive / unknown) for those references |
| `Parts.resolve_colour(colour)` | Enrich a bare colour code with catalog metadata |
| `CatalogEntry.symbol_name` / `.module_path` / `.import_statement()` | Generated-library symbol, module, and import line for a catalog entry |
| `ldraw.snippets` | `symbol_name`, `module_path`, `suggested_import`, `symbol_name_for_description` helpers |
| `Colour.display_label` / `swatch_rgb` / `swatch_alpha` / `is_transparent` | UI-facing colour accessors |

**Other changes**

| Change | Impact |
| --- | --- |
| `download()` / `generate()` gained an `on_progress=` keyword | Additive; the default CLI path is unchanged |
| Python 3.14 added to the supported/tested matrix | Nothing to do |
| Coverage moved from Coveralls to Codecov; `coveralls` dev dep dropped | Contributors only |

**Removals affecting your code:** none.

## Upgrade checklist

1. Upgrade the package: `uv add pyldraw3>=1.2.0` (or `pip install -U pyldraw3`).
2. Do nothing for caches. The generated `ldraw.library` package and the
   `catalog.sqlite` index both self-heal (unchanged from 1.1.0). The new
   `LDrawSession`/`ensure_library` machinery uses the same fingerprints, so
   it agrees with `ldraw generate` about when a rebuild is needed.
3. There is no migration step. Optionally, adopt the new APIs below where
   they replace hand-rolled setup, geometry, or introspection code.

## New APIs and what to build with them

### Session and setup: `ensure_library()` and `LDrawSession`

The centerpiece of 1.2.0. Setting pyldraw up in an application previously
meant orchestrating `download`, `generate`, catalog indexing, and
`LibraryImporter.set_config` yourself, and knowing which of those were
already done. The new `ldraw.session` module packages that.

`ensure_library()` is the one-call "make everything ready" entry point. It
inspects the current state and does only the work that is actually
missing — download the library if absent, (re)generate `ldraw.library` if
stale, rebuild the catalog index if stale — then wires up the importer:

```python
from ldraw import ensure_library

session = ensure_library()          # download + generate + index as needed
parts = session.load()              # ready to use
model = session.open_model("castle.mpd")
```

Its keyword arguments mirror the choices the CLI makes:

- `config` / `config_file` — supply an explicit `Config` or a config path
  instead of the default.
- `version=` — which LDraw release to download if one is missing (defaults
  to the complete release).
- `force_generate=True` — regenerate `ldraw.library` even if it looks
  fresh.
- `write_config=True` — persist the resolved configuration to disk.
- `on_progress=` — a callback receiving `ProgressEvent`s (see below).

Setup failures are normalized to `RuntimeError` with a readable message
(wrapping the underlying `requests`/zip/`UnwritableOutputError` cause).

`LDrawSession` is the lower-level handle when you want to inspect or
control the steps individually:

```python
from ldraw import LDrawSession

session = LDrawSession()            # uses Config.load() by default
state = session.state()

if state.ready:
    parts = session.load()
else:
    if state.needs_generation:
        ...                          # call ensure_library() to fix, or regenerate
    if state.needs_index_rebuild:
        parts = session.rebuild_index()
```

- `session.state()` returns an `LDrawState` classifying the library,
  catalog index, and generated package. Its booleans — `ready`,
  `library_available`, `needs_index_rebuild`, `needs_generation` — let you
  branch without catching exceptions or stat-ing files yourself. The exact
  cause is in `state.reasons` as `LDrawStateReason` members
  (`LIBRARY_MISSING`, `INDEX_STALE`, `GENERATED_LIBRARY_MISSING`, …).
- `session.paths` returns `LDrawPaths` — the resolved `parts.lst`,
  generated-library, catalog-db, and other paths for the configuration, so
  you don't reconstruct them from `Config` by hand.
- `session.load()` loads `Parts`, building and persisting the catalog index
  when needed.
- `session.rebuild_index(force=..., on_progress=...)` rebuilds the
  persistent index (unlinking a stale DB first) and returns the loaded
  parts.
- `session.open_model(path)` is a thin wrapper over `read_model`.

Uses: application/library bootstrap on first launch, a "check status
before doing expensive work" gate, health checks, or a settings screen
that reports whether the library is installed and current.

### Progress events for embeddable setup

`ldraw.progress` defines the structured events the setup flows emit.
Pass an `on_progress` callback to `ensure_library`, `download`, or
`generate` and you receive a typed `ProgressEvent` at each stage:

```python
from ldraw import ProgressEvent, ProgressStage, ensure_library

def report(event: ProgressEvent) -> None:
    if event.total:
        print(f"[{event.stage}] {event.message}: {event.current}/{event.total}")
    else:
        print(f"[{event.stage}] {event.message}")

ensure_library(on_progress=report)
```

- `ProgressStage` is a `StrEnum`: `DOWNLOAD`, `UNPACK`, `PARTS_LIST`,
  `LIBRARY_GENERATION`, `INDEX_REBUILD`, `DONE`.
- `ProgressEvent` carries `stage`, `message`, optional `current`/`total`
  byte counts (for the download stage), and an optional `path`.

Download progress is **throttled**: at most one event per megabyte, with
the first (`current=0`) and final byte counts always forced through, so an
~80 MB download produces ~80 events rather than tens of thousands. When no
callback is supplied, no events are built at all — the default CLI path
pays nothing.

Uses: driving a GUI/TUI progress bar or spinner during first-run setup,
logging setup steps, or surfacing "downloading… generating…" status in an
embedding application.

### Model occurrences: `Model.iter_occurrences()`

`iter_occurrences()` walks a model and yields one `ModelOccurrence` per
placed **leaf** part, with everything a geometry or analysis tool needs
already computed:

```python
from ldraw import read_model

model = read_model("castle.mpd")

for occ in model.iter_occurrences():
    print(occ.part_code, occ.colour.code, occ.position, occ.step)
```

Each `ModelOccurrence` (a frozen dataclass) carries:

- `piece`, `part_code`, `reference` — the source piece and its code.
- `colour` — the **effective** colour, with the main-colour code (16)
  resolved to the inherited colour from the enclosing submodel reference.
- `position` / `matrix` — the **world** transform, composed down through
  every submodel reference (not the piece-local transform).
- `source_model` / `source_line` — which submodel the piece lives in and
  the line it was parsed from (`None` for pieces built in code).
- `step` / `source_step` — the building step this occurrence belongs to.

Two keyword flags control traversal:

- `expand_submodels=False` — treat submodel references as leaves (yield the
  reference itself) instead of recursing into them.
- `include_steps=False` — skip `0 STEP` accounting (`step`/`source_step`
  become `None`).

Submodel cycles raise `SubmodelCycleError`, as elsewhere in `Model`.

The related `Model.source_line_for(piece)` returns the parsed source line
for a given piece (source-line tracking is now threaded through parsing and
preserved by `submodel_view`).

Uses: exporting to renderers or other formats where you need world-space
placements, per-step snapshots, mapping a piece back to its file/line for
diagnostics, or any analysis that wants flattened placements with
inherited colour already resolved.

### Whole-model geometry: `ModelSummary` and `model_bounds()`

Built on top of occurrences, `ModelSummary` folds a model's real geometry
into a reusable summary:

```python
from ldraw import ModelSummary, model_bounds, read_model

model = read_model("castle.mpd")
summary = ModelSummary.from_model(model, parts)

summary.bounds          # transformed axis-aligned bounds (BoundingBox | None)
summary.size_ldu        # overall size as a Vector, in LDU
summary.size_mm         # same, in millimetres (× 0.4)
summary.part_counts     # {part_code: count}
summary.colour_usage    # {colour_code_or_rgb: count}
summary.occurrence_count
summary.skipped_geometry  # parts whose geometry couldn't be resolved
```

- `bounds` is the true transformed extent — each part's bounding-box
  corners are transformed by the occurrence's world matrix before folding,
  so rotated parts are accounted for. `origin_bounds` is the cheaper
  bounds of just the placement origins.
- Parts whose geometry can't be resolved (a missing part, a part with no
  geometry) don't abort the summary — they're collected as
  `SkippedGeometry` records (`part`, `source_model`, `source_line`,
  `reason`) so you can report exactly what was left out.

`model_bounds(model, parts)` is the shorthand when all you want is the
`BoundingBox`.

Uses: camera framing / auto-centering, real-world dimension readouts,
sanity-checking a generated model's size, or a BOM-plus-dimensions report.
This supersedes hand-folding per-piece `bounding_box()` calls.

### Part-file reference introspection: `Parts.references_for()`

`references_for()` exposes the type-1 subfile references *inside* a part
file — what a part is built out of:

```python
for ref in parts.references_for("3001"):
    print(ref.kind, ref.code, ref.description)

# Recurse through subparts and primitives:
tree = parts.references_for("3001", recursive=True)
```

Each `PartReference` carries `parent_code`, `code`, `reference`, `kind`,
`description`, the resolved `colour`, the `position`/`matrix` transform,
and a `depth`. `PartReferenceKind` classifies each reference as `PART`,
`SUBPART`, `PRIMITIVE`, or `UNKNOWN` (using the catalog, the primitive
index, and the `8/48/p` primitive path conventions). Recursion follows
everything except `UNKNOWN` references and guards against cycles.

The supporting `Parts.resolve_colour(colour)` takes a `Colour` or a bare
integer code and returns the catalog's full metadata for that colour when
known, or the input unchanged otherwise.

Uses: exploded-view or part-composition analysis, dependency graphs
between parts and primitives, or auditing which primitives a part relies
on.

### Catalog entry symbol/import helpers and `ldraw.snippets`

`CatalogEntry` now knows how to name and import itself in the generated
library:

```python
entry.symbol_name          # e.g. "Brick2X4"
entry.module_path          # "ldraw.library.parts.bricks" (or None if uncategorized)
entry.import_statement()   # "from ldraw.library.parts.bricks import Brick2X4"
```

The new `ldraw.snippets` module offers the same as free functions —
`symbol_name(entry)`, `module_path(entry)`, `suggested_import(entry)`, and
`symbol_name_for_description(description)` — which is the exact
transformation code generation applies (and now shares), so your derived
symbol names always match what `ldraw generate` emits. The `ldraw parts`
CLI now routes through `suggested_import` for its import suggestions.

Uses: building "add this to your imports" hints in a UI, generating docs
from the catalog, or resolving a catalog entry to its importable class.

### Colour UI accessors

`Colour` gained four presentation-oriented properties for building palette
pickers and inspectors:

```python
colour.display_label   # "Bright Red" (name, spaces for underscores) / "Colour 4" / rgb / "Unknown colour"
colour.swatch_rgb      # rgb hex for a swatch, or None
colour.swatch_alpha    # alpha 0–255, defaulting to fully opaque when unset
colour.is_transparent  # True when swatch_alpha is below opaque
```

These complement `Colour.is_solid` from 1.1.0: `is_solid` answers "is this
plain opaque paint (no alpha, no finish)?" for filtering, while these four
answer "how do I show this colour to a user?".

Uses: colour swatches and labels in TUIs/GUIs, palette pickers, and BOM or
inspector displays.

## Platform and tooling notes

- **Python 3.14** is now part of the supported and CI-tested matrix
  (3.12+ remains the floor).
- Coverage reporting moved from Coveralls to **Codecov**; the `coveralls`
  dev dependency was dropped and `memory-profiler`/`psutil` added for
  benchmarking. These affect contributors only, not consumers of the
  package.
