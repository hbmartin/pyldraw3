# Upgrading pyldraw3 from 1.3.0 to 1.4.0

Version 1.4.0 adds renderer-neutral building-instruction semantics. It is
backward compatible: raw `Model.objects`, `Comment`, `MetaCommand`,
serialization, and the legacy `Model.steps` grouping retain their 1.3
behavior.

## New semantic document API

Call `model.instruction_document(parts=...)` to obtain an
`InstructionDocument`. Its `sections` are root-first and follow reachable MPD
file order; each root/submodel section retains an independent step sequence.
Embedded `.dat` sections are dependencies rather than instruction sections.
`model.iter_instruction_steps()` is a shortcut for the root sequence.

Plain `STEP` and typed `ROTSTEP` commands terminate the current step. Adjacent
boundaries intentionally preserve geometry-stable rotation steps, while only
the phantom group after a final delimiter is dropped. Expansion remains an
explicit occurrence or inventory operation and never creates one artificial
global build order.

The primary types are available from `ldraw`:

```python
from ldraw import (
    CameraState,
    InstructionBuilder,
    InstructionDocument,
    InstructionIssue,
    InstructionSection,
    InstructionStep,
    RotationMode,
    RotationStep,
    iter_instruction_issues,
)
```

Advanced directive, callout, inventory, scope, and camera-context enums live
in `ldraw.instructions`.

## Directives and authoring

The interpreter recognizes standard `STEP`; MLCad `ROTSTEP ... REL|ADD|ABS`
and `ROTSTEP END`; modern `0 !LPUB` and legacy `0 LPUB` forms for callouts,
multi-step groups, suppression, inventory-ignore ranges, inserted pages, and
assembly camera values; plus namespaced `!PYLDRAW` notes, highlights, and 3D
arrows. Unsupported LPub commands remain raw and lossless.

Use `InstructionBuilder` for canonical serialization and balanced structural
ranges. Its context managers close in `finally`, including when user code
raises. Existing handwritten metadata does not need migration.

## Inventory and validation

Instruction steps provide added and cumulative occurrence/BOM methods with
explicit `expand_submodels` and `respect_lpub` controls. `.ldr` models expand;
embedded `.dat` sections remain countable part dependencies. LPub `PLI`, `BOM`,
and `PART` ignore ranges affect only the corresponding inventory views, never
geometry.

`iter_instruction_issues()` reports stable codes with section, source line,
severity, and message. The CLI combines these checks with `iter_ldr_issues`:

```bash
ldraw instructions validate model.mpd --strict --max-parts 25
```

## Manifests and snapshots

The new CLI surface is:

```text
ldraw instructions inspect FILE [--section NAME] [--parts]
ldraw instructions validate FILE [--strict] [--max-parts N]
ldraw instructions export FILE [-o MANIFEST] [--force]
ldraw instructions snapshots FILE --out DIR [--section NAME] [--force]
```

Manifest schema v1 is deterministic JSON with source provenance, section and
step structure, placements/occurrences, BOMs, transformed bounds, rotation,
camera, directives, and artifact paths. Snapshot bundles contain a cumulative
self-contained MPD and flattened LDR per reachable step. Embedded `.dat`
dependencies become relative sidecars. Regeneration is staged and `--force`
may replace only files owned by a previous pyldraw3 manifest.

All instruction CLI commands now require a configured parts catalog. Run
`ldraw download --yes` if the standard installation hint appears.

## Deliberate limits

1.4.0 does not render PDF, image, or HTML instructions and does not implement
page typography/layout, `.io`, `.lxf`, the complete LPub grammar, build
modifications, `BUFEXCHG`, or automatic camera selection. The manifest and
snapshots are intended as stable inputs to those downstream concerns.
