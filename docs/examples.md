# Examples

The [`examples/`](https://github.com/hbmartin/pyldraw3/tree/main/examples)
directory in the repository contains runnable scripts that build LDraw models
with pyldraw3. Each one writes LDraw text to standard output, so you run an
example and redirect it into a `.ldr` file that you can open in an LDraw
viewer such as LDView, LeoCAD, or Stud.io:

```bash
python examples/figures.py > figures.ldr
```

All of the examples assume you have already downloaded and generated a
library (`ldraw download --yes && ldraw generate --yes`) so that the
`ldraw.library.*` imports resolve. See the [Guide](guide.md) for setup.

## What each script demonstrates

| Script | Demonstrates |
| --- | --- |
| [`figure.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/figure.py) | The simplest minifigure. Builds a single `Person`, calling `head`, `hat`, `torso`, `hips`, arms, hands, and legs, then adds a few `"LIGHT"` sources. The best starting point for understanding the figure API. |
| [`diver.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/diver.py) | Minifigure accessories. A scuba diver assembled from `DiverMask`, `HairMale`, `Airtanks`, `Flipper` shoes, and a movie camera held in one hand — with the whole `Person` tilted using a rotated orientation matrix. |
| [`brothers.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/brothers.py) | Grouping and group transforms. A minifig (cap, revolver) is built inside a `Group`, then the group's `position` and `matrix` are changed and every piece is re-emitted at the new placement — the core pattern for moving an assembled sub-scene as a unit. |
| [`figures.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/figures.py) | Multiple figures in one scene. Two spacemen posed differently (including the `hips_and_legs` convenience), placed on a `Baseplate16X16` with a crystal rock prop. |
| [`spaceman.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/spaceman.py) | Procedural generation. A grid of spacemen, each given randomized head/limb rotations from a seeded `random`, showing how to drive figure construction from a loop. |
| [`stairs.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/stairs.py) | Reusing a group to duplicate geometry. A staircase is built once inside a `Group`, then repositioned and rotated in a loop to emit a spiralling tower of staircases — plus a top-hatted figure holding a magnifying glass. |
| [`buggy.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/buggy.py) | Materials and a full vehicle. A space buggy/rover built from wheels, tyres, slopes, and a steering wheel using chrome, rubber, and metallic colours, driven by a seated minifig, on tiled baseplates. |
| [`moon_landing.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/moon_landing.py) | A complete diorama with group duplication. An astronaut and a rover on a `Baseplate32X32WithCraters`; the rover `Group` is emitted once, then re-placed with a new position and orientation to appear twice, with a second seated figure added. |
| [`mandelbrot.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/mandelbrot.py) | Algorithmic brick artwork. Renders the Mandelbrot set as a grid of `Brick1X1` pieces, mapping each cell's escape-iteration count to a colour — an example of computing a model rather than hand-placing it. |
| [`instructions.py`](https://github.com/hbmartin/pyldraw3/blob/main/examples/instructions.py) | Semantic building instructions. Authors section-local steps, a callout, ROTSTEP, camera state, a note, a highlight, and an arrow, then emits a self-contained MPD. |

## Two construction styles

The examples use the classic figure/`Group` API, where each `print(...)` emits
one object's LDraw text as it is built. Newer code can instead assemble a
[`Model`](api/index.md) and save it in one step (`Model.from_pieces(...)`,
`model.add_group(...)`, `model.save(...)`); see the
[Guide](guide.md) and the top-level `README` for that style. Both produce the
same LDraw output — pick whichever fits your program.
