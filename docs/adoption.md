# Discover and use pyldraw

`ldraw api` and `api_inventory()` require no downloaded library. Queries match
public names and documentation; `--limit` and `--offset` select a page while
`total` describes every matching item. The generated [API reference](api/index.md)
uses the same symbol registry.

```python
from ldraw import api_inventory

page = api_inventory("Model.save", limit=10)
print(page.items[0].signature)
```

```sh
ldraw api Model.save --format json --limit 10 --offset 0 --output api.json
ldraw doctor --format json
```

Catalog lookup and resolved geometry need an installed LDraw library. You can
select its installation root or its data directory. This loads geometry from
that installation and prepares derived indexes in pyldraw's cache. It works
with read-only sources. Indexing never downloads a library or changes saved
configuration. `LDRAW_DIR` and `LDRAWDIR` are also supported. An explicit library
or Config takes precedence; otherwise environment, saved configuration, existing
default cache, and discovery are tried in order. Ambiguous discovery requires
an explicit selection. `doctor()` diagnoses availability without repair.

If you need a library, explicitly run `ldraw download --yes`. Generation of
`ldraw.library.*` Python modules is optional for these workflows; use
`ldraw generate --yes` when you want generated imports.

The executable Python walkthrough is `examples/adoption.py:workflows`. Its
search, inspection, BOM, and validation operations have these CLI counterparts:

```sh
ldraw parts search 3001 --library /path/to/ldraw --format json --limit 5
ldraw inspect scene.ldr --library /path/to/ldraw --format json
ldraw bom scene.ldr --library /path/to/ldraw --format json --output scene.json
ldraw validate scene.ldr --library /path/to/ldraw
ldraw render scene.ldr --library /path/to/ldraw
```

Rendering also requires LDView or LeoCAD on PATH. `ldraw doctor` reports those
optional executables. The default previews remain front, isometric, and top.
Search falls back to the previous ranked matcher when FTS5 or persistent caching
is unavailable, and carries a diagnostic describing that fallback. Exact codes
and code prefixes rank before text matches. Queries are literal text, so SQL or
FTS operators in a query do not become executable search syntax.

```python
from pathlib import Path
from ldraw import Parts, doctor

parts = Parts.from_directory(Path("/path/to/ldraw"))
page = parts.search("brick", category="brick", physical_only=True, limit=10)
entry = parts.resolve_symbol("Brick2X4")
print(page.total, page.diagnostics)
print(doctor(library=parts.library_root).to_dict())
```

## Documents and qualified analysis

Run `examples.adoption_reports.document_workflows(parts, Path("scene.mpd"))`
to build a document with a shortcut containing two embedded physical parts.
The shortcut expands into two inventory occurrences; each physical part's
geometry stays inside that part boundary. The example saves an attributed,
independent extraction and returns full and bounded BOM reports.

```python
from ldraw import bom_report, inspect_model, read_model

model = read_model("scene.mpd")
report = bom_report(model, parts=parts)
print(report.rows, report.coverage, report.unresolved_contents)
inspection = inspect_model(model, parts, occurrence_budget=100)
print(inspection.geometry_coverage, inspection.connection_coverage)
reuse = model.extract("local.dat", namespace="reuse-")
reuse.model.save("reuse-local.mpd", mpd=True)
print(reuse.manifest)
```

```sh
ldraw bom scene.mpd --library /path/to/ldraw --format json --detail full
ldraw inspect scene.mpd --library /path/to/ldraw --occurrence-budget 100 --format json
ldraw validate scene.mpd --library /path/to/ldraw --profile assembly --matrix-tolerance 0.000001
ldraw extract scene.mpd local.dat --namespace reuse- --output reuse-local.mpd --manifest attribution.json
ldraw render scene.mpd --section local.dat --library /path/to/ldraw --views rear left right bottom
```

Extraction and raw document parsing require no installed library. Physical BOM
expansion, resolved bounds, reference checks, and connections require definitions
for the requested references. Unknown physical contents retain known counts with
diagnostics. Unclassified `.dat` definitions produce provisional part rows.

`occurrence_budget` and `feature_pair_budget` are optional. Exhaustion returns
completed work and diagnostics; totals that require unvisited work stay unknown.
The CLI's `--strict` fails when the coverage required by the operation is
incomplete. `ldraw inspect --geometry-only --strict` only requires geometry
coverage. General format validation and `--profile assembly` share format
checks; contextual assembly findings are warnings and include checks that could
not run. `--connectivity` enables the optional topology check.

## Connections and measurements

Run `examples.adoption_reports.connection_workflows(parts, Path("stack.ldr"))`
for a two-brick stack. Results include topology, a bounded snap search, and
conservative measurements. Neither a snap report nor a connection graph
certifies collision clearance, rigidity, strength, or physical support.

```python
model = read_model("stack.ldr")
inspection = inspect_model(model, parts)
snap = inspection.snap_report(moving=1, fixed=0, feature_pair_budget=100)
print(snap.candidates, snap.examined_pairs, snap.total_pairs, snap.coverage)
graphs = inspection.connection_graphs()
print(graphs.confirmed.components(), graphs.optimistic.components())
measurement = parts.measurements("3001")
print(measurement.to_dict())
```

```sh
ldraw snap stack.ldr --library /path/to/ldraw --moving 1 --fixed 0 --feature-pair-budget 100 --format json
ldraw inspect stack.ldr --library /path/to/ldraw --feature-pair-budget 100 --format json
ldraw parts measurements 3001 --library /path/to/ldraw --format json --output measurements.json
```

Snap suggestions return transforms without editing the model. A candidate's
`contact_supported` flag records whether applying its transform establishes
contact through the same detector used by inspection. Truncated reports rank
only the examined pairs. Reports explicitly list unsupported checks.

Measurements contain optional `body_bounds`, `stack_height`, and
`footprint_studs`, with provenance and diagnostics. Footprint values are
supported top-stud X/Z positions divided by `ldraw.units.STUD_PITCH`, retaining
the part origin. Recognized top-stud geometry is excluded from body bounds;
underside geometry remains. Stacking height needs a unique supported direction
and seating planes. Unsupported values are `None`.
