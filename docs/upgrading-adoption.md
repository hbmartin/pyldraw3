# Adoption milestone upgrade notes

These three implementation milestones are staged in roadmap order. They are
unreleased changes; this page does not assign or publish package versions.
Existing `ldraw.units` constants and the generated API reference remain the
upstream unit vocabulary and documentation.

## Milestone 1: discovery and portable libraries

`api_inventory()` and `ldraw api` enumerate public exports, public methods,
signatures, documentation, and unit constants without a parts installation.
The reference and generated API portion of the skill cheat sheet use the same
registry. Curated workflows remain separate from generated inventories.

`Parts.search()` returns items, the full matching total, pagination, and
diagnostics. Exact codes and prefixes precede BM25 text matches; part codes
break ties. Literal queries cannot inject FTS operators. When SQLite FTS5 or a
persistent cache is unavailable, the previous ranked matcher provides results
with a fallback diagnostic. Derived indexes rebuild after schema changes.
`Parts.resolve_symbol()` shares generation's naming and collision rules and
does not import generated modules.

`Parts.from_directory()` and `LDrawSession(library=...)` accept an installation
root or its data directory. Missing indexes are created in pyldraw's cache;
geometry is read from the original installation. A failed persistent cache
uses a temporary index and reports its limitation. No ordinary operation
downloads, changes saved configuration, or writes into the installation.

Selection order is explicit library, explicitly supplied `Config`, `LDRAW_DIR`,
`LDRAWDIR`, usable saved configuration, an existing default cache, then unique
discovery. An invalid explicit or environment selection fails with a path and
remedy. Multiple discovered libraries require `--library`. `doctor()` and
`ldraw doctor` only inspect selection, capabilities, cache state, FTS5, and
renderer availability.

## Milestone 2: document and analysis contracts

Embedded definitions take precedence within a `Parts.with_embedded(model)`
overlay and report library-name shadowing. BOM, inspection, analysis, and
instruction inventories share physical boundary classification. Declared
parts stop expansion. Shortcuts and aliases expand into known physical leaves,
with multiplicity and inherited colours. Primitive and subpart geometry does
not create physical inventory rows. Unclassified `.dat` boundaries and missing
definitions remain provisional; cycles and unresolved contents are diagnosed.
These rules can correct previous row quantities and part identities.

`bill_of_materials()` and `Model.bill_of_materials()` retain their list return
types. `bom_report()` adds diagnostics, unresolved contents, provisional rows,
coverage, and processed versus total counts. The ordinary CLI displays
incomplete-count diagnostics. Existing `ldraw bom --format json` retains its
rows-only schema; `--detail full` selects the qualified report.

Direct lines, triangles, quads, and conditional-line endpoints participate in
world bounds through nested transforms. Conditional-line control points do not
enlarge bounds. Raw geometry has source attribution and creates no inferred
physical parts or connectors. Occurrence path items have a zero-based
`piece_index`, stable while the document is unchanged.

Use `geometry_coverage` and `connection_coverage`, each `complete`, `partial`,
or `unavailable`. Geometry completeness is independent of connection warnings.
Geometry and inspection `.complete` properties emit `DeprecationWarning` and
retain their previous meaning throughout 1.x; removal is planned for 2.0.
The legacy inspection JSON `complete` field remains alongside the explicit
fields. Parser completeness is a separate contract.

Occurrence and feature-pair budgets are opt-in. Exhaustion returns completed
work with diagnostics and unknown totals where appropriate. `snap_report()`
qualifies the search prefix; `snap_candidates()` retains its tuple return for
unbounded callers. Strict CLI modes require the requested coverage; partial
ordinary reports succeed. Geometry-only strict inspection does not require
connection metadata.

`Model.save()` defaults to LF and atomic replacement, with keyword-only
`newline`, `mpd`, and `atomic` controls. Automatic output selection is retained.
Explicit MPD supports one named section. Failed replacement preserves the
existing destination. Reference names retain internal spaces. Whitespace and
numbers may be canonicalized; this is semantic serialization.

`Model.extract(section, namespace=...)` copies a dependency closure and returns
an attribution/rename manifest. Authorship and licence records survive;
internal names are rewritten deterministically. Cycles, missing internal
sections, and inconsistent names are rejected. `ldraw extract` exposes the
same workflow.

`--profile assembly` adds contextual warnings for placements, colours, aliases,
shadowing, polygons, BFC ordering, headers, and reachability. Missing evidence
is reported as checks that could not run. Matrix tolerance is explicit;
reflections remain orthonormal and receive a separate mirrored-placement
warning. Optional disconnected-component warnings do not establish support.

Rendering accepts section selection and exports embedded parts and local
sidecars into an isolated workspace. Resolved bounds frame the scene. Cache
identity includes dependencies and the selected library. Rear, left, right,
and bottom views supplement the existing front/isometric/top defaults.

## Milestone 3: connection foundations

A feature's local +Y axis is its outward mating normal. Stud and socket normals
oppose at mating. Cylindrical `profile.direction` records the direction of
physical sections along that axis, preserving section locations and caps when
metadata frames are normalized. Direction-symmetric interfaces retain their
equivalent orientations. Snap deltas are proper rotations.

Authored and inferred sockets now use consistent mating frames. Circular
primitive evidence resolves wide-rim axes; extent-based fallbacks stay
heuristic. Supported square underside cavities can receive studs. Mixed
axle/pin metadata produces distinct addressable regions at their physical
locations. Axles can form bearing contacts in round holes; pins remain
incompatible with cross holes. Confirmed cylindrical contact requires positive
compatible engagement and supported end access. Entrance touching alone is
insufficient. Equivalent duplicate features are removed without combining
separate ports.

Editor `slide` flags are preserved as `editor_slide`. They no longer imply
physical friction. `profile.friction` is unknown (`None`) unless explicit
evidence or an override supplies it. Snap reports indicate post-application
contact support and list unverified candidates. Seating and joint rules that
lack evidence are explicitly unsupported.

`ConnectionMultigraph.components()` is deterministic, includes isolated nodes,
and handles parallel edges. Confirmed and optimistic graphs expose coverage.
They report topology, without rigidity or physical-support conclusions.

`PartMeasurements` provides optional body bounds, supported footprint positions
in stud units, and stacking height, with provenance and diagnostics. Geometry
and connection dependencies invalidate its cache. Unsupported measurements
remain absent.

Measurement caching follows the geometry cache of its `Parts` session. After
explicitly editing library files, reload `Parts` or call
`clear_part_geometry_cache(parts)` to refresh geometry and its measurements.

The unchanged 200-part 2018-02 corpus selection and content fingerprint were
verified before updating snapshots. Intentional differences affect 143 parts:
profile directions and unknown friction, top-stud centering, normalized socket
frames, and duplicate-port removal in ten parts. This snapshot update does not
change the pinned library or its selected codes.

Construction recipes, placement verbs, automatic snap application, collision
certification, declarative plans, ancestor cloning, and rigidity or strength
solvers remain downstream.
