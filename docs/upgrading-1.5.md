# Upgrading pyldraw3 from 1.4.0 to 1.5.0

Version 1.5 adds report-oriented APIs for interactive applications. Existing
strict parsing, catalog loading, geometry helpers, validation issue fields,
and generated imports remain available.

## Prepare the catalog once

`prepare_catalog()` replaces separate readiness and loading passes. It checks
only requested capabilities, computes one reusable filesystem fingerprint,
loads or rebuilds the SQLite index, and returns before/after state plus a
`CatalogBuildReport` and diagnostics. Progress events now carry explicit
`ProgressUnit` values; pass a `CancellationToken` to cancel safely.

```python
from ldraw import CancellationToken, LDrawCapability, prepare_catalog

token = CancellationToken()
result = prepare_catalog(
    capabilities=(LDrawCapability.CATALOG,),
    on_progress=lambda event: print(
        event.stage, event.current, event.total, event.unit
    ),
    cancellation=token,
)
parts = result.parts
```

Generated Python modules are no longer checked unless
`LDrawCapability.GENERATED_MODULES` is requested.

## Load, validate, and analyze once

`load_model()` returns `ModelLoadResult(model, diagnostics, complete)`. The
default tolerant parser skips malformed lines, retains surrounding valid
objects, and reports stable codes, path, MPD section, source line, severity,
offending value, suggestions, and underlying cause. Duplicate MPD sections,
misplaced/content-after `NOFILE`, unresolved submodels, and cycles are
diagnosed as structure errors.

```python
from ldraw import load_model

loaded = load_model("model.mpd", parts=parts)
if loaded.model is not None:
    analysis = loaded.analyze(parts)
    print(analysis.summary, analysis.bom, analysis.instruction_steps)
```

`iter_ldr_issues(loaded)` reuses the report and never rereads the source.
`read_model()` and `parse_model()` retain their strict, exception-based
behavior for callers that prefer it.

`ModelAnalysis` materializes leaf occurrences once and reuses them for the
summary and BOM. `ModelSummary.from_occurrences()` and
`bill_of_materials(occurrences=...)` are available for custom pipelines.

## Search, metadata, and inspection

`PartsCatalog.search()` owns normalized whitespace, casefolding, AND-token
matching, scoped searches, code/description/category/keyword fields, limits,
and deterministic relevance ranking. The CLI uses the same implementation.

Each catalog entry can retain a `PartMetadata` value parsed from official and
unofficial headers: file kind, origin, alias/moved/obsolete status,
replacement, author, license, BFC certification, history, category, keywords,
and preview transform. Catalog schema v5 persists this data; older indexes are
rebuilt automatically.

`Parts.library_root` exposes the resolved data directory and
`parts.inspect_part()` returns metadata, references, exact geometry, and
explicit diagnostics rather than treating failures as empty results.

## Exact geometry and occurrence provenance

`parts.geometry(code)` expands the real descendant points used to calculate
bounds and returns unresolved-reference/cycle diagnostics alongside studs and
receptacles. `inspect_model()` transforms that exact geometry for every leaf
occurrence and retains skipped occurrences. It also provides broad-phase AABB
gaps and stud contacts.

Every `ModelOccurrence.path` now contains each root-to-leaf placement with its
source model, reference, source line, local step, and inherited/effective step.
World transforms continue to include every outer submodel placement.

## First-run setup and optional previews

`discover_libraries()` and `inspect_library()` identify complete and partial
installations. `plan_download()` reports the exact remote size when available,
current release, cached bytes, resume support, archive integrity, destination,
and diagnostics without mutating local state. `download(..., resume=True,
cancellation=token)` enables resumable, cancellable transfer and cancellable
unpacking.

Preview rendering is an optional boundary. `render_capabilities()` detects
LDView/LeoCAD and `render_preview()` renders one named view through a
content-addressed cache with progress and cancellation. No renderer is a
warning result, not an import-time dependency or exception.
