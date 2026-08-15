# Upgrading pyldraw3 from 1.5.0 to 1.6.0

Version 1.6 adds a typed connection subsystem. Parts now expose connection
features — studs, stud receptacles, bars, clips, pins, pin holes, axles, axle
holes, hinges, rim seats, tyre beads, and generic interfaces — assembled from
conservative heuristics, connector primitives, inline `!LDCAD` records, LDCad
shadow libraries, Studio connectivity exports, and explicit overrides. Model
inspection matches those features into typed contacts, connection multigraphs,
and ranked snap suggestions, and the CLI serializes all of it.

Everything released in 1.5.0 keeps working. The observable changes for code
that never opts into connections are collected under
[Behavior notes](#behavior-notes); the one semantic rewrite is
[`stud_contacts()`](#stud_contacts-is-now-strict).

## The typed connection vocabulary

`ConnectionFeature` is the central type: a `kind` (`ConnectionKind`), a mating
`role` (`ConnectionRole.MALE`/`FEMALE`/`NEUTRAL`), a local `position` and
orthonormal `frame` whose **+Y column is the feature axis** (X/Z retain
cross-section roll, which is significant for axles and clips), a shape
`profile`, a stable `feature_id`, allowed `freedoms` (rotate, slide, discrete
rotate, free rotate), an evidence `source` (`ConnectionSource`), a
`confidence` in `[0, 1]`, occupancy (`occupied`/`occupied_by`), and structured
`connection_provenance` (source, path, archive member, line number, command,
include chain).

Profiles are a tagged union:

- `CylindricalProfile` — one or more `CylindricalSection`s (round, axle, or
  square; optionally flexible), plus `centered`, `friction`, and `caps`;
- `FingerProfile` — hinge finger sequence, radius, first finger role, and
  detents;
- `AnnularProfile` — radius, width, and offset for rim seats and tyre beads;
- `GenericProfile` — named interface with optional `GenericBounds` (point,
  box, cylinder, sphere), a `match` mode, and an `aligned`/`free` placement.

Module-level helpers are exported at the top level: `connections_compatible()`
answers whether two features can mate (fixed pairs stud↔stud-receptacle,
bar↔clip, pin↔pin-hole, axle↔axle-hole, rim-seat↔tyre-bead, plus
hinge↔hinge and generic↔generic, gated on role, group, occupancy, and
radius tolerance); `connection_residual()` measures centerline distance,
axial gap, and angular/roll alignment; `angular_alignment_within()` converts
a dot-product alignment to a degree tolerance; `snap_transform()` computes
the placement that mates one feature to another.

All connection enums are `StrEnum`s, so serialized values are the lowercase
member strings (`"stud"`, `"ldcad_shadow"`, `"confirmed"`, …).

## Query connection features from the catalog

`Parts.connections(code)` and `Parts.connection_metadata(code)` are new.
`connections()` returns the `features` projection of the richer report:

```python
from ldraw import prepare_catalog

prepared = prepare_catalog()
parts = prepared.parts

for feature in parts.connections("3001"):
    print(feature.kind, feature.role, feature.position, feature.source)

report = parts.connection_metadata("3001")
print(report.coverage, report.source_count, report.diagnostics)
```

`ConnectionMetadataReport` carries the part code, a coverage grade, the
features, and per-source counts: `source_count`, `recognized_record_count`,
`unsupported_record_count`, `invalid_record_count`, and `diagnostics`.

`ConnectionMetadataCoverage.COMPLETE` means clean authoritative metadata was
processed, including an explicit clear-to-empty document. `PARTIAL` means the
result relies on primitive/heuristic evidence or recovered around unsupported
or invalid records. `NONE` means neither metadata nor connector primitives
were found.

Wheel and tyre pairings derived from official shortcut descriptions are also
new: `parts.tyre_rim_compatibility` returns `PartCompatibility` rows, and
`parts.compatible_tyres(rim_code)` / `parts.compatible_rims(tyre_code)`
answer the common lookups. When a shortcut assembles a rim with its tyre, the
matching rim-seat and tyre-bead features are marked `occupied` by the
assembly.

## Configure authoritative metadata

Register sources when preparing the catalog:

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

The same keywords exist on `LDrawSession.prepare_catalog()`,
`catalog.load_parts()`, `Parts.get()`, and `Parts.fresh()`. An existing
`Parts` instance can be adjusted directly: `add_connection_shadow(source)`,
`clear_connection_shadows()`, `add_studio_metadata(source)`,
`clear_studio_metadata()`, and per-part overrides with
`set_connection_overrides(code, features, replace_existing=False)` /
`clear_connection_overrides(code=None)`. Overrides augment by default;
`replace_existing=True` discards every lower-priority feature for that part.

Sources are folded deterministically in this order:

1. connector primitives collected during geometry traversal;
2. conservative description/bounds heuristics and official wheel/tyre
   shortcuts;
3. inline `!LDCAD SNAP_*` records in the part file itself;
4. registered LDCad shadow sources, in registration order;
5. registered Studio sources, in registration order;
6. `Parts.set_connection_overrides()`.

Two distinct rules govern the fold. Between metadata sources, stable feature
IDs — not colocated geometry — control replacement: a later feature with the
same (case-insensitive) ID replaces the earlier one and emits a
`connection.feature_conflict` warning; distinct IDs may intentionally coexist
at the same location. Separately, once authoritative metadata (inline LDCad,
shadow, Studio, or override) survives the fold, any heuristic-, primitive-,
or shortcut-sourced feature describing the *same interface* (same kind,
colocated position, parallel axis) is dropped, so authoritative data
supersedes inference without needing matching IDs.

`SNAP_CLEAR [id=...]` targets the raw `metadata_id`; an unqualified
`SNAP_CLEAR` applies at its exact stream position, wiping features
accumulated so far (including pending targeted clears).

## LDCad shadow sources

`LDCadShadowLibrary` accepts a shadow directory, a ZIP file, or an LDCad
`.csl` archive (a CSL is a ZIP). All three use the same case-insensitive
logical resolver over `parts/`, `parts/s/`, `p/`, `p/8/`, and `p/48/`; a
bare code tries `parts/<code>.dat` then `p/<code>.dat`. A missing source
raises `FileNotFoundError` at registration; a file that is not a ZIP raises
`zipfile.BadZipFile`. On duplicate logical names inside an archive, the first
member wins.

Supported records and options:

| Record       | Options                                                                    |
| ------------ | -------------------------------------------------------------------------- |
| `SNAP_CLEAR` | `id`                                                                       |
| `SNAP_INCL`  | `id`, `ref` (required), `pos`, `ori`, `scale`, `grid`, `slide`             |
| `SNAP_CYL`   | `id`, `group`, `pos`, `ori`, `scale`, `mirror`, `gender`, `secs` (required), `caps`, `grid`, `center`, `slide` |
| `SNAP_CLP`   | `id`, `group`, `pos`, `ori`, `radius`, `length`, `center`, `slide`, `scale`, `mirror`, `gender` |
| `SNAP_FGR`   | `id`, `group`, `pos`, `ori`, `genderofs`, `gender`, `seq` (required), `radius`, `center`, `scale`, `mirror` |
| `SNAP_GEN`   | `id`, `group`, `pos`, `ori`, `gender`, `bounding`, `scale`, `mirror`, `match`, `placement` |

`SNAP_CYL` maps to axle, stud, bar, or pin kinds based on its sections,
label, and gender; `SNAP_CLP` is always a female clip; `SNAP_FGR` produces a
hinge with a finger profile; `SNAP_GEN` produces a generic feature. `ori`
must be orthonormal with positive determinant — mirroring goes through the
`mirror` option, not the orientation. A `grid` replicates the feature once
per cell. Parsing is tolerant: an unknown `SNAP_*` record or option key is
reported as a warning diagnostic and skipped, never aborting geometry.

`SNAP_INCL` resolves its `ref` across the entire registered shadow registry
(so an include in one archive can reach a document in another), transforms
the included features without placement inheritance, re-owns them to the
including part, and records the nesting path in the provenance
`include_chain`. Unresolvable references and include cycles are diagnosed.

For direct use, `ldraw.connection_metadata` exports `parse_ldcad_text()`,
`parse_ldcad_commands()`, `metadata_report()`, and the
`ShadowConnectionResult` accumulator; `LDCadShadowLibrary.connections_for()`
returns the same shape.

## Studio connectivity sources

`StudioConnectionLibrary` reads Studio connectivity exports with the JSON
shape `{"parts": [{"part_id": ..., "connections": [...]}]}`. Each connection
row accepts `id`, `type`, `position`, `axis`, `gender`, `group`, `radius`,
`length`, and `width`; recognized types are `stud`, `pin`/`technic_pin`,
`axle`, `bar`, `clip`, `hinge`, `tyre_rim`, `ball`/`ball_joint`, and
`turntable`. Unknown fields are excluded with a warning; unknown types make
the row invalid. Studio-sourced features carry `source="studio"` and
confidence 0.95.

Studio limitations worth knowing: the format carries no cross-section roll
(the frame is derived from the axis alone), profiles are single-section,
and there is no grid, include, clear, scale-, or mirror-inheritance support.
A part row with an empty `connections` list contributes no authoritative
evidence — primitive and heuristic features survive and coverage is
unchanged. Clear-to-empty is an LDCad `SNAP_CLEAR` or
`set_connection_overrides(..., replace_existing=True)` concern.

## Diagnostics

All connection metadata problems are reported as `Severity.WARNING`
diagnostics with stable codes; parsing recovers and geometry is never
aborted. The new `DiagnosticCode` members and their serialized values:

| Member                               | Value                                | Meaning                                                        |
| ------------------------------------ | ------------------------------------ | -------------------------------------------------------------- |
| `CONNECTION_UNSUPPORTED_RECORD`      | `connection.unsupported_record`      | `SNAP_*` record type not implemented                           |
| `CONNECTION_UNSUPPORTED_OPTION`      | `connection.unsupported_option`      | Option key not allowed for the record; excluded Studio field   |
| `CONNECTION_INVALID_OPTION_VALUE`    | `connection.invalid_option_value`    | Malformed option syntax or value; unreadable/invalid document  |
| `CONNECTION_MISSING_REQUIRED_OPTION` | `connection.missing_required_option` | `SNAP_INCL` without `ref`, `SNAP_CYL` without `secs`, `SNAP_FGR` without `seq` |
| `CONNECTION_INCLUDE_NOT_FOUND`       | `connection.include_not_found`       | `SNAP_INCL` reference unresolvable                             |
| `CONNECTION_INCLUDE_CYCLE`           | `connection.include_cycle`           | `SNAP_INCL` recursion                                          |
| `CONNECTION_FEATURE_CONFLICT`        | `connection.feature_conflict`        | Later source replaced a same-ID feature with different content |
| `CONNECTION_INVALID_TRANSFORM`       | `connection.invalid_transform`       | Non-orthonormal/singular/mirroring orientation or bad scale    |
| `CONNECTION_INVALID_GRID`            | `connection.invalid_grid`            | Malformed `[grid=...]` specification                           |

Relative to the released 1.5.0, every `connection.*` code is new — nothing
was renamed. `DiagnosticCode.CONNECTION_METADATA_INVALID` exists only as an
attribute alias of `CONNECTION_INVALID_OPTION_VALUE`: the two names are the
same member, its `.name` reports the canonical spelling, it does not appear
when iterating `DiagnosticCode`, and
`DiagnosticCode("connection.metadata_invalid")` raises `ValueError`. If you
tracked unreleased development snapshots in which that member serialized as
`connection.metadata_invalid`, update string matches to
`connection.invalid_option_value`.

## Source caching and invalidation

`Parts.get` memoizes instances keyed by cheap source metadata, and the key
now also folds in every registered connection source: file sources by size
and modification time, directory sources by their root modification time,
size, device, and inode. Descendants are deliberately not walked on lookup.
Replacing a shadow directory wholesale or touching a file source is picked
up automatically; a nested edit that leaves the root directory's metadata
unchanged is not detected. After any nested edit, call `Parts.fresh(...)` or
`Parts.clear_cache()` to rebuild from current disk contents.

Mutating an instance's sources — `add_connection_shadow()`,
`add_studio_metadata()`, `set_connection_overrides()`, or any of the
`clear_*` methods — invalidates that instance's derived geometry caches and
drops all memoized `Parts` instances process-wide, so later `Parts.get`
calls rebuild from current state.

## Inspect typed contacts and multigraphs

`inspect_model()` now attaches world-space connection features to every
resolved occurrence (`OccurrenceGeometry.connections`), and
`ModelInspection` gains three methods.

`connection_contacts(*, tolerance=0.25, angular_tolerance=2.0)` matches
compatible feature pairs through a deterministic spatial index and returns
`ConnectionContact` values: the two occurrences, the two features, a
`ConnectionResidual` (centerline `distance`, `axial_gap`, angular
`alignment`, `roll_alignment`, and — for stud matches — `entry_face_gap` and
`penetration`), and a `ConnectionStatus`. A contact involving a
heuristic-sourced feature is `POTENTIAL`; every other source yields
`CONFIRMED`.

Studs use strict profile semantics: a male stud is confirmed only when the
candidate part has stud-receptacle evidence, the axes are anti-parallel
within the angular tolerance, the stud's base lies on the candidate's
oriented entry face, and it penetrates inward. Consequently two overlapping
surfaces no longer count as a stud connection.

```python
from ldraw import inspect_model

inspection = inspect_model(model, parts)
graphs = inspection.connection_graphs()

for edge in graphs.confirmed.edges:
    print(edge.first, edge.second, edge.first_feature_id, edge.second_feature_id)
```

`connection_graphs()` returns a `ConnectionGraphs` pair of
`ConnectionMultigraph`s. Both graphs share one zero-based occurrence node
tuple covering *every* occurrence, including unresolved ones (which appear as
isolated nodes). Parallel feature contacts remain parallel edges; edges carry
feature-ID strings (empty string when a feature has no ID) plus status and
residual. `confirmed` is the subset of `optimistic` whose edges are
`CONFIRMED`; the optimistic graph adds only heuristic-feature contacts — it
does not add generic AABB surface edges or component analysis.

`snap_candidates(moving, *, fixed=None, limit=None)` is new: given a moving
occurrence (object or index) and optionally a fixed one, it ranks compatible
feature pairings by residual and returns `SnapCandidate` values whose
`transform` is the world-space `SnapTransform` (position and matrix) that
would mate the moving part:

```python
best = inspection.snap_candidates(moving=2, limit=3)
for candidate in best:
    print(candidate.fixed_occurrence.index, candidate.transform.position)
```

## `stud_contacts()` is now strict

`stud_contacts(*, tolerance=0.1, probe_distance=0.1)` keeps its signature but
is reimplemented as a projection of the strict typed stud matches above, and
its results change for existing models:

- A candidate occurrence must expose stud-receptacle evidence. A stud pressed
  against a plain tile, or two merely overlapping AABBs, no longer produces a
  contact, so counts can drop relative to 1.5.
- Sideways or averted studs are rejected by the oriented entry-face and
  inward-penetration checks; axes must be anti-parallel within 2 degrees.
- At most one contact is reported per stud feature and candidate occurrence
  (the best receptacle wins), where 1.5 could report several.
- `tolerance` is now the residual cap (centerline distance, axial gap,
  entry-face gap, lateral slack) rather than AABB padding, and
  `probe_distance` is now a minimum penetration depth rather than a probe
  offset. Both remain "bigger is stricter/looser" in the same direction, but
  values are not comparable across versions.
- `StudContact.position` is the matched connection feature's position, and
  `StudContact.stud` is the nearest qualifying `StudReference` retained as
  evidence. Three optional fields were added: `stud_feature`,
  `receptacle_feature`, and `residual`.
- Results are sorted by occurrence indices and feature IDs instead of
  iteration order.

`stud_contacts()` remains the convenient stud-only view;
`connection_contacts()` is the full typed surface.

## CLI and JSON

Repeat `--ldcad-shadow PATH` and `--studio-metadata PATH` on `parts geometry`
or `inspect` to register sources; a missing path, a shadow source that is not
a directory or ZIP/CSL archive, or a Studio source that is not a readable
JSON file is reported on stderr and exits 1 before the catalog loads.

`parts geometry --format json` adds `connection_count`, `connections` (each
feature with kind, role, position, axis, frame, profile as a tagged union,
freedoms, source, confidence, occupancy, compatible parts, and structured
provenance), and `connection_metadata` (coverage, counts, diagnostics). The
table format prints a `connections:` line.

`inspect --format json` adds top-level `connection_contacts` and
`connection_graphs` (confirmed/optimistic edge lists plus the node list),
per-occurrence `connection_count`/`connections`/`connection_metadata`, and
extends each `stud_contacts` entry with `stud_feature`, `receptacle_feature`,
and `residual`. Residual objects serialize `alignment`, `axial_gap`,
`distance`, `entry_face_gap`, `penetration`, and `roll_alignment`. The table
format prints a `connection contacts:` line. Exit codes are unchanged: only
error-severity diagnostics fail `inspect`.

The optional pinned corpus check is:

```bash
uv run python scripts/check_ldcad_shadow_corpus.py
```

It checks commit `15aa1e718b6a8da37d24fc7af5e52e262c041bfb` of the official
LDCad shadow library (pass `--source PATH` to use an existing checkout) and
exits nonzero when the corpus contains command or option forms pyldraw3 does
not yet recognize.

## Behavior notes

- `PartGeometry` gained `connections` (inserted between `studs` and
  `diagnostics`) and a trailing `connection_metadata` field. Construct it
  with keyword arguments; positional construction with five or more
  arguments now binds differently than in 1.5.
- Inline `!LDCAD` scanning always runs, so a part whose file contains an
  unsupported or invalid `SNAP_*` record now carries warning diagnostics and
  reports `PartGeometry.complete == False`; `ModelInspection.complete` and
  the `inspect` JSON `complete` field inherit this. CLI exit codes are
  unaffected because they key on error severity only.
- The first geometry query per part reads the part file a second time to
  collect inline metadata — a small first-call cost on large libraries, and
  a file that becomes unreadable between the two reads raises instead of
  degrading to a diagnostic.
- `StudContact` equality, `repr`, and tuple forms changed with the three new
  optional fields, and `stud_contacts()` results changed as described above.
- `Matrix.inverse()` is new and raises `numpy.linalg.LinAlgError` for a
  singular matrix.
- `from ldraw import *` now brings in roughly forty additional connection
  names (`ConnectionFeature`, `ConnectionKind`, `SnapTransform`, …); check
  for shadowing if you star-import. `ldraw.part_geometry` additionally
  exports `part_connections()` and `clear_part_geometry_cache()`.
- `prepare_catalog()`, `load_parts()`, `Parts.get()`, and `Parts.fresh()`
  accept `connection_shadows=` and `studio_metadata=` keywords; defaults are
  empty, so existing calls behave identically, but the `Parts.get`
  memoization key now includes those sources.

## 1.6.1: stud receptacles move to the mating grid

1.6.0 placed inferred `stud_receptacle` features on the tube centreline — a
cell centre. Studs mate at the surrounding grid corners, so strict stud
matching (a centreline-residual test) could not confirm an ordinary stacked
brick. 1.6.1 derives **mating sockets** from tube primitives during part
resolution:

- an open tube (`stud4` family) contributes its four diagonal grid corners
  plus a socket on its own centreline (half-offset "jumper" mounts);
- a solid tube (`stud3` family) contributes its axial neighbours and loses
  its centreline feature — nothing can enter a solid tube;
- candidate sockets are validated against the part's own top-stud grid
  phases; a studless underside (tiles) falls back to the part bounds, and a
  stud-group primitive or subpart with no stud evidence defers derivation to
  the enclosing part;
- bounds filtering can reject every offset candidate: a solid tube then
  contributes no inferred receptacle, while an open tube keeps only its named
  centre socket. When the rejected tube belongs to a catalog part referenced
  by another catalog part, its raw evidence remains available internally so
  the enclosing assembly can reconsider it against the larger grid and bounds;
- sockets sit at the far end of the transformed tube primitive, not at the
  part's bounding-box face, so unrelated underside protrusions do not move
  them and `snap_transform()` mates a stud flush with the part.

Derived offset sockets are named `Stud Socket`, keep the tube's kind, role,
axis, profile, and source, and append `derived:stud-socket` to `provenance`.
The center socket retained for an open tube is the exception: it keeps the
primitive's complete header description (for example, `Stud Tube Open` for
`stud4`) to distinguish the tube's own opening from the surrounding derived
sockets. Authoritative metadata (inline LDCad, shadows, Studio, overrides)
still supersedes them as inferred interfaces.

Observable changes: `stud_receptacle` counts and positions change for any
part with tubes; `connection_contacts()` and `stud_contacts()` now confirm
plain stacks (two stacked 2 x 4 bricks report exactly eight confirmed stud
contacts with zero residual), while half-offset or wall-touching studs remain
rejected.
