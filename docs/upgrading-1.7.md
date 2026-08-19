# Upgrading pyldraw3 from 1.6.0 to 1.7.0

Version 1.7 is a correctness release for the connection subsystem that 1.6
introduced. Nothing is removed, no signature gains a required argument, and
the runtime dependencies are unchanged — but inferred `stud_receptacle`
features move to different positions and are emitted in different numbers, so
`Parts.connections()`, `stud_contacts()`, the connection graphs, snap
suggestions, and the `inspect` JSON payload all report different values for
parts with tubes.

No cached artifact encodes connection features, so upgrading needs no
`ldraw download`, `ldraw generate`, or catalog rebuild. Clear only the
in-process geometry cache if you hold one across the upgrade
(`clear_part_geometry_cache()`).

## The problem 1.7 fixes

1.6 placed an inferred `stud_receptacle` on the tube primitive's own
centreline. A tube centreline is a *cell centre* of the stud grid, and an
ordinary stud does not mate there — it mates at the four grid corners around
the tube. Because strict stud matching keys on a centreline residual, the
most basic assembly in the format could not be confirmed:

```python
from ldraw import inspect_model, load_model, prepare_catalog

parts = prepare_catalog().parts
model = load_model("stack.ldr").model   # two Brick 2 x 4 stacked squarely
report = inspect_model(model, parts=parts)

len(report.stud_contacts())                  # 1.6.0: 0    1.7.0: 8
len(report.connection_graphs().confirmed.edges)  # 1.6.0: 0    1.7.0: 8
```

In 1.7 every one of those eight contacts reports a residual `distance` of
`0.0`.

## Stud receptacles move onto the mating grid

During part resolution each tube receptacle is now expanded into the sockets
a stud can actually enter, and the tube's own centreline feature is replaced:

- an **open tube** (the `stud4` family, description contains `open`)
  contributes its four diagonal grid corners at ±10 LDU, **plus** a socket on
  its own centreline for half-offset "jumper" mounts;
- a **solid tube** (the `stud3` family) contributes its four axial neighbours
  at ±20 LDU and **loses** its centreline feature entirely — nothing can enter
  a solid tube;
- sockets sit at the **far end of the transformed tube primitive**, not on its
  centre and not on the part's bounding-box face, so unrelated underside
  protrusions do not move them.

Concretely, for Brick 2 x 4 (`3001`) the three tube features at `y = 4` become
three openings plus eight deduplicated corner sockets, all at `y = 24` — the
brick's underside face:

| Part | 1.6.0 receptacles | 1.7.0 receptacles |
| --- | --- | --- |
| `3001` Brick 2 x 4 | 3 × `Stud Tube Open` at `y = 4` | 3 × `Stud Tube Open` + 8 × `Stud Socket` at `y = 24` |
| `3020` Plate 2 x 4 | 3 × `Stud Tube Open` | 3 × `Stud Tube Open` + 8 × `Stud Socket` |
| `3022` Plate 2 x 2 | 1 × `Stud Tube Open` | 1 × `Stud Tube Open` + 4 × `Stud Socket` |
| `3710` Plate 1 x 4 | 3 × `Stud Tube Solid` | 4 × `Stud Socket` (no solid centres) |
| `3623` Plate 1 x 3 | 2 × `Stud Tube Solid` | 3 × `Stud Socket` |
| `3068b` Tile 2 x 2 | 1 × `Stud Tube Open` | 1 × `Stud Tube Open` + 4 × `Stud Socket` |

Because the socket now sits at the tube's opening rather than 20 LDU up its
centreline, `snap_transform()` mates a stud **flush** with the part instead of
sinking the mating piece into it.

## How to recognize a derived socket

A derived offset socket is `replace()`d from the tube it came from, so it
keeps the tube's `kind`, `role`, `axis`, `profile`, `source`, `confidence`,
and `owner_code`, and changes three fields:

- `name` becomes the literal `"Stud Socket"`;
- `feature_id` gains a `:socket:<±x><±z>` suffix, for example
  `s/3001s01@R0/stud4@R0/stud4:socket:+1-1`;
- `provenance` gains a trailing `"derived:stud-socket"` entry.

The centre socket an open tube keeps is the exception: it retains the
primitive's own header description (`Stud Tube Open` for `stud4`) and its
original `feature_id`, so the tube's own opening stays distinguishable from
the derived sockets around it. It also gains the `"derived:stud-socket"`
provenance entry. A solid tube's centre feature, when one is emitted at all,
takes the `feature_id` suffix `:opening`.

If your code matched receptacles by `feature_id == "stud4"`, by the
description `"Stud Tube Solid"`, or assumed one receptacle per tube, update it
to test `"derived:stud-socket" in feature.provenance` instead.

## Grid validation, and deferral through nested geometry

A candidate socket is accepted only when its position lands on a phase of the
part's **own top-stud grid** (positions reduced modulo the 20 LDU pitch, using
studs whose axis opposes the socket's). This is what keeps sockets off the
outside of a part's walls.

Stud-group primitives and subparts see only a slice of a part, so their grid
is often incomplete. Rather than guessing:

- a candidate rejected by an incomplete grid stays **deferred** — private to
  that resolution level, absent from `connections()`, and carried up through
  the enclosing geometry, transformed by the child's complete placement
  (including scale), for the parent's grid to reconsider;
- only a **catalog part** may fall back to lateral bounds filtering (with a
  4 LDU margin), because a studless underside such as a tile has no grid to
  validate against;
- when bounds filtering rejects every offset candidate, a solid tube
  contributes no inferred receptacle at all, while an open tube still keeps
  its centre socket.

Where two sockets contest the same cell (within 0.5 LDU and aligned to 0.999),
the higher-confidence one wins; ties fall back to a tube's own opening over a
derived neighbour, then to emission order. An existing non-derived receptacle
with positive confidence holds its cell outright; a zero-confidence one (a
placeholder primitive) competes as a candidate and loses to a socket that can
actually mate.

## Authored metadata still wins

Inline `!LDCAD` records, LDCad shadow libraries, Studio exports, and explicit
overrides continue to supersede inferred interfaces, and now do so for a whole
tube's socket set at once: authoritative metadata matching **any** interface of
a tube — the opening or any candidate corner — resolves the entire set, so an
excluded inferred socket cannot reappear at an enclosing assembly. Metadata
that clears all features, and an override that replaces existing features,
discard the deferred candidates outright.

## Placements that invalidate a feature

Two related tightenings:

- **Overrides are now placement-checked.** `ConnectionSource.OVERRIDE` joins
  `LDCAD_INLINE`, `LDCAD_SHADOW`, and `STUDIO` in the set of authored sources
  whose features are rejected — not merely downgraded — under a mirrored,
  sheared, or otherwise disallowed placement. A rejected override is dropped
  and reported as a `connection.invalid_transform` warning, exactly as a
  shadow-library feature already was.
- **Degenerate placements yield no sockets.** A placement that leaves a tube's
  frame non-orthonormal (singular, collapsed, or scaled off the grid unit)
  carries no trustworthy position, roll, or axis, so that tube contributes
  nothing — not even the centre socket a bounds rejection would otherwise
  leave. Such candidates are dropped rather than deferred, since no enclosing
  placement can restore a basis a singular one destroyed.

Socket evidence that a placement degrades from positive to zero confidence is
dropped with its own `connection.invalid_transform` warning
(`socket evidence '…' … dropped under invalid scale or reflection`), so an
inferred socket never disappears from a part without an entry in the report
explaining where it went.

## New public name

`ldraw.connection_types.METADATA_SOURCES` is a new
`frozenset[ConnectionSource]` naming the four authored sources
(`LDCAD_INLINE`, `LDCAD_SHADOW`, `STUDIO`, `OVERRIDE`). It is exported from
`ldraw.connection_types.__all__` but deliberately **not** re-exported from the
top-level `ldraw` package, so `from ldraw import *` is unaffected:

```python
from ldraw.connection_types import METADATA_SOURCES

authored = [f for f in features if f.source in METADATA_SOURCES]
```

## Behavior notes

- `Parts.connections()`, `Parts.connection_metadata()`,
  `PartGeometry.connections`, and `part_connections()` return more
  `stud_receptacle` features for parts with tubes, at different positions
  (the tube opening, not the tube centre). Counts and positions are the
  observable change; every other field on a derived socket is inherited from
  its tube.
- `stud_contacts()` and `connection_contacts()` now confirm plain stacks.
  Half-offset and wall-touching studs remain rejected — the strictness
  introduced in 1.6 is unchanged, it simply now has correctly placed
  receptacles to match against.
- `connection_graphs()` gains confirmed edges for assemblies that previously
  reported none, and `inspect --format json` reflects this in
  `stud_contacts`, `connection_contacts`, and `connection_graphs`. The
  `inspect --format table` `connection contacts:` line changes accordingly.
  Exit codes are unchanged.
- Snap suggestions for stud/receptacle pairs change position, because the
  target socket moved to the tube opening.
- `bom`, `validate`, `parts`, model parsing, and serialization are untouched.
- `ldraw/connection_inference.py` gained `StudSocketEvidence`,
  `StudSocketDerivation`, and `derive_stud_socket_evidence()`. They are
  module-internal plumbing between inference and part resolution and are not
  listed in `__all__`; treat them as private.
