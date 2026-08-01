# CLI Reference

The `ldraw` executable downloads LDraw libraries, generates importable Python
modules, queries parts, validates and inspects model files, renders standard
preview views, exports bills of materials, and produces renderer-neutral
instruction data.

```text
usage: ldraw [-h] command ...

Manage LDraw libraries and create, inspect, validate, and render LDraw models.

positional arguments:
  command
    download  Download and unpack an LDraw parts library release.
    generate  Generate the ldraw.library modules from the downloaded library.
    parts     Query the parts catalog.
    validate  Validate an LDraw file (.ldr, .mpd, or .dat).
    bom       Print a bill of materials for an LDraw model file.
    inspect   Inspect exact world bounds, provenance, contacts, and gaps.
    render    Render a deterministic set of standard preview views.
    stubs     Write a type-stub package for ldraw.library into your project.
    instructions
              Inspect, validate, and export renderer-neutral instructions.
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
- `ldraw parts search TERM [--limit N]` searches the catalog across part
  codes, descriptions, categories, and keywords. Every whitespace-separated
  token in `TERM` must match (case-insensitive), and results are ranked by
  relevance. It exits with code 1 when nothing matches.
- `ldraw parts info CODE` shows a part's description, category, file path, and
  the generated-library import to use.
- `ldraw parts geometry CODE [--format table|json]` expands the part's
  drawable subfile tree and reports exact local bounds, points, connectors,
  completeness, and structured diagnostics.
- `ldraw validate FILE [--strict]` lints `.ldr`, `.mpd`, and `.dat` files.
  Malformed lines, unknown parts, and unknown colour codes are errors.
  Suspect matrices, legacy dithered colours, and unknown meta-commands are
  warnings. `--strict` makes warnings fail.
- `ldraw bom FILE [--format table|csv|json] [-o OUT]` prints a bill of
  materials counted by part and colour, with submodels expanded.
- `ldraw inspect FILE [--format table|json] [--gap-threshold LDU]
  [--chronological] [--page-marker-prefix TEXT] [-o OUT]` reports exact
  transformed occurrence geometry, provenance, stud contacts, nearest AABB
  gaps, skipped geometry, and structured diagnostics.
- `ldraw render FILE [--view front|isometric|top] [--size WIDTHxHEIGHT]
  [--backend auto|ldview|leocad] [--output-dir DIR] [--prefix NAME]
  [--refresh] [--overwrite]` renders a safely staged standard-view set.
- `ldraw stubs [--out PATH]` writes an `ldraw-stubs/` PEP 561 stub package for
  IDE autocompletion of generated `ldraw.library.*` imports.
- `ldraw instructions inspect FILE [--section NAME] [--parts]` prints one row
  per section-local step. `--parts` adds each step's parts tray.
- `ldraw instructions validate FILE [--strict] [--max-parts N]` runs both the
  ordinary LDraw linter and semantic instruction validation.
- `ldraw instructions export FILE [-o MANIFEST] [--force]` writes manifest
  schema v1 to stdout or a file.
- `ldraw instructions snapshots FILE --out DIR [--section NAME] [--force]`
  writes cumulative MPD and flattened LDR files plus `instructions.json`.
- `ldraw config` prints the current configuration as YAML.
- `ldraw version` prints the installed `pyldraw3` version.

Run `ldraw <command> --help` for a command's full option list.

## Geometry and model inspection

`parts geometry` returns useful partial geometry when a part references a
missing or unreadable child. Table output labels the result incomplete; JSON
adds `complete` and serialized diagnostics alongside the original bounds,
point, and stud fields. An unavailable library or unknown root part exits 1,
while reportable incomplete geometry exits 0.

`inspect` loads models tolerantly and preserves valid occurrences around
malformed lines. Its table and JSON reports include root-to-leaf model,
reference, source-line, step, and attributed-page paths; exact world bounds;
skipped geometry; stud contacts; and nearest AABB gaps. The default page
marker is `0 // PDF_PAGE NNN`, controlled by `--page-marker-prefix`.

```console
$ ldraw parts geometry 3001 --format json
$ ldraw inspect model.mpd --chronological --gap-threshold 5 -o inspection.txt
```

When a partial inspection contains error diagnostics the report is still
written, but the command exits 1. Warnings alone exit 0. Missing or undecodable
files that cannot produce a model are diagnosed on stderr and also exit 1.

## Rendering previews

`render` uses the same optional, cached preview boundary as `render_preview()`.
With no `--view`, it renders `front`, `isometric`, and `top` at `800x600`.
Repeat `--view` to choose an ordered subset. `--backend auto` prefers the first
available current backend; an explicit `ldview` or `leocad` fails if that
backend is unavailable. `--refresh` bypasses cache reads.

Outputs are named `PREFIX.VIEW.png`, using the model stem as the default
prefix. Every requested view is first completed in destination-local temporary
storage. Final files are promoted only after all views succeed, and existing
files are restored if promotion fails. Existing outputs are rejected before
rendering unless `--overwrite` is supplied.

```console
$ ldraw render model.mpd --view front --view top --output-dir renders
RENDERED: /work/renders/model.front.png
RENDERED: /work/renders/model.top.png
```

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

## Instruction commands

All four `ldraw instructions` commands require the configured parts catalog,
because counts, descriptions, colours, and geometry bounds must be
deterministic. If it is unavailable they print the existing `ldraw download`
installation hint and exit 1.

`inspect` reports direct placements, expanded additions, cumulative leaf
counts, ROTSTEP, camera, callout/multi-step, page-break, and suppression state.
Section selection is case-insensitive:

```console
$ ldraw instructions inspect model.mpd --section module.ldr --parts
section  step  direct  expanded  cumulative  rotation  camera  callouts  group  page  suppressed
module.ldr     1       2         2           2  -             -              0      -     -  -
      qty  part         colour               description
        2  3001         Red                  Brick  2 x  4
```

`validate` emits instruction diagnostics with section and source-line context.
Errors always fail. Warnings (including missing explicit boundaries, orphan
sections, and `--max-parts` overflow) fail only with `--strict`.

Manifest schema v1 is snake_case and contains root-first reachable sections,
source provenance, direct and expanded additions, cumulative count/BOM/bounds,
ROTSTEP and LPub camera state, directives, callouts/groups, and suppression or
page-break flags. Cumulative occurrences are deliberately represented only by
aggregates so manifests do not grow quadratically.

`snapshots` writes this layout by default:

```text
output/
  instructions.json
  001-main/
    step-0001.mpd
    step-0001.ldr
  002-module/
    step-0001.mpd
    step-0001.ldr
```

MPDs preserve submodel references and include the transitive dependency
closure. LDRs flatten `.ldr` submodels into section-local coordinates, retain
`.dat` references, and write embedded `.dat` definitions as safe relative
sidecars. Instruction directives live in the manifest rather than snapshot
geometry. Suppressed steps still receive artifacts; page breaks do not create
steps.

Without `--force`, any collision fails. Forced regeneration trusts only paths
listed in an existing pyldraw3-owned manifest, removes stale owned paths, and
never deletes or overwrites unrelated files. Output is staged beside the
destination before commit. These commands create data for renderers; they do
not generate PDF, image, HTML, typography, or page layout.

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
uv sync --group docs
uv run zensical serve
uv run zensical build --clean --strict
```

GitHub Pages must use the "GitHub Actions" publishing source. If the
repository remains configured to publish from a branch such as `gh-pages`, the
live site will continue to serve that branch instead of this workflow's
Zensical artifact.
