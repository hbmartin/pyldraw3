# Upgrading pyldraw3 from 1.5.0 to 1.6.0

Version 1.6 makes pyldraw3's connection subsystem the typed adapter for LDCad
and Studio metadata. Existing `Parts.connections(code)` calls remain valid;
they now return the `features` projection of a richer metadata report.

## Configure authoritative metadata

LDCad shadow directories, ZIP files, and CSL archives use the same
case-insensitive logical `parts/`, `parts/s/`, `p/`, `p/8/`, and `p/48/`
resolver. Studio connectivity exports use the JSON shape
`{"parts": [{"part_id": ..., "connections": [...]}]}`.

```python
from ldraw import prepare_catalog

prepared = prepare_catalog(
    connection_shadows=("LDCadShadowLibrary.csl",),
    studio_metadata=("studio-connectivity.json",),
)
parts = prepared.parts
report = parts.connection_metadata("32000")
print(report.coverage, report.source_count, report.diagnostics)
```

Sources are folded deterministically in this order:

1. conservative description/bounds heuristics;
2. connector primitives and official wheel/tyre shortcuts;
3. inline `!LDCAD SNAP_*` records;
4. registered LDCad shadow sources, in registration order;
5. registered Studio sources, in registration order;
6. `Parts.set_connection_overrides()`.

Stable feature IDs, not colocated geometry, control replacement. Distinct IDs
may intentionally coexist. `SNAP_CLEAR [id=...]` targets the raw
`metadata_id`; an unqualified clear applies at its exact stream position.

`ConnectionMetadataCoverage.COMPLETE` means clean authoritative metadata was
processed, including an explicit clear-to-empty document. `PARTIAL` means the
result relies on primitive/heuristic evidence or recovered around unsupported
or invalid records. `NONE` means neither metadata nor connector primitives
were found. Diagnostics have stable codes for unsupported records/options,
invalid values/transforms/grids, missing values/includes, include cycles, and
feature overrides.

### Source caching and invalidation

`Parts.get` memoizes instances keyed by cheap source metadata: file sources
by size and modification time, directory sources by their root stat identity
(device and inode) only — descendants are deliberately not walked on lookup.
Replacing a shadow directory wholesale or touching a file source is picked up
automatically; editing a file nested inside a registered shadow directory is
not. After such in-place edits, call `Parts.fresh(...)` or
`Parts.clear_cache()` to rebuild from current disk contents.

### Diagnostic code compatibility

`DiagnosticCode.CONNECTION_METADATA_INVALID` is retained as an attribute
alias, but its serialized value changed from `connection.metadata_invalid`
(1.5) to `connection.invalid_option_value` (1.6). Consumers that match the
serialized `to_dict()["code"]` string, or that construct
`DiagnosticCode("connection.metadata_invalid")`, must update to the new
value.

## Inspect typed contacts and multigraphs

`connection_contacts()` uses profile semantics and a spatial index. Studs are
confirmed only when a male stud has receptacle evidence, its base lies on the
candidate's oriented entry face, and it penetrates inward. Consequently two
overlapping surfaces no longer count as a stud connection.

```python
from ldraw import inspect_model

inspection = inspect_model(model, parts)
graphs = inspection.connection_graphs()

for edge in graphs.confirmed.edges:
    print(edge.first, edge.second, edge.first_feature_id, edge.second_feature_id)
```

Both graphs contain zero-based occurrence nodes, including unresolved
occurrences. Parallel feature contacts remain parallel edges. The optimistic
graph adds contacts involving heuristic features; it does not add generic AABB
surface edges or component analysis. `stud_contacts()` remains available as a
projection of strict typed stud matches and now includes feature evidence and
the residual entry-face gap/penetration.

## CLI and JSON

Repeat `--ldcad-shadow PATH` and `--studio-metadata PATH` on `parts geometry`
or `inspect`. JSON now includes world-space connection features, structured
provenance, metadata coverage/counts/diagnostics, contact status and residuals,
stud evidence, and confirmed/optimistic graph edges.

The optional pinned corpus check is:

```bash
uv run python scripts/check_ldcad_shadow_corpus.py
```

It checks commit `15aa1e718b6a8da37d24fc7af5e52e262c041bfb` of the official
LDCad shadow library and reports newly observed command or option forms.
