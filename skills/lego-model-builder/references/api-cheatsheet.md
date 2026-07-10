# pyldraw3 authoring cheat-sheet

Everything needed to write a model-building program. Read this before coding.

## The build API

```python
from ldraw import Model, Piece
from ldraw.geometry import Vector, Identity, XAxis, YAxis, ZAxis
from ldraw.library.parts import Brick2X4, Plate2X4
from ldraw.library.colours import Red, White, Light_Bluish_Grey

# Place one piece (keyword-first, sensible defaults):
#   Piece.place(part, *, colour=16, position=Vector(0,0,0), matrix=Identity(), suffix=".dat")
brick = Piece.place(Brick2X4, colour=Red, position=Vector(0, 0, 0))

# Assemble a flat model and save it:
model = Model.from_pieces(
    [brick, Piece.place(Plate2X4, colour=White, position=Vector(0, -24, 0))],
    name="example.ldr",          # becomes the file's model name
    description="An example",
    author="lego-model-builder",
)
model.save("example.ldr")         # writes the .ldr file
```

- `part` is an LDraw code string. Imported names like `Brick2X4` *are* code
  strings, so `Piece.place("3001", ...)` works identically.
- `colour` accepts a `Colour` (imported from `ldraw.library.colours`) or a bare
  int colour code. `16` is "main/inherit" (the default).
- `Model.from_pieces(pieces, *, name="", description=None, author=None)` and
  `model.save(path)` are the whole file-writing path. Keep the model **flat**
  (one list of pieces) — no submodels or steps.

## Coordinate system — read carefully

LDraw uses **LDraw Units (LDU)**. The single most common mistake is the Y axis.

- **`-Y` is UP.** Stacking a brick on top means *decreasing* Y by the brick
  height. The stud plane is at Y = 0; positive Y goes down.
- **Brick height = 24 LDU.** **Plate height = 8 LDU** (a brick is 3 plates).
- **Stud pitch = 20 LDU.** A 1×1 footprint is 20×20 LDU; an N-stud span is
  `20 * N` LDU. X and Z are the horizontal ground plane.

So a 1×1 column of 3 bricks:

```python
pieces = [Piece.place(Brick1X1, colour=Red, position=Vector(0, -24 * i, 0))
          for i in range(3)]
```

### Gotcha: Vector scalar multiply is right-only

`Vector` implements `__rmul__`, not `__mul__`. Write the scalar on the **left**:

```python
20 * Vector(1, 0, 0)      # OK
Vector(1, 0, 0) * 20      # TypeError
```

### Rotation

`Matrix.rotate(angle, axis, units=Degrees)`; axes are the marker classes
`XAxis` / `YAxis` / `ZAxis` (passed as types). Rotate about vertical Y:

```python
from ldraw.geometry import Identity, YAxis
m = Identity().rotate(90, YAxis)               # quarter turn about the up axis
Piece.place(Slope2X1, colour=Red, position=Vector(0, 0, 0), matrix=m)
```

`matrix * vector` and `matrix * matrix` are supported for composing transforms.

## Placing bricks so studs align

- Position is the part's **origin**, which for standard bricks/plates is the
  centre of its footprint at the stud plane. Adjacent 1×1 studs are 20 LDU
  apart in X/Z. To tile a wall, step X by `20 * studs_wide_of_previous_piece`.
- A 2×4 brick spans 40 LDU in one axis and 80 in the other; its origin is at
  the centre, so its edges are ±20 and ±40 from the origin. Account for the
  half-span when butting pieces edge to edge.
- Stack vertically by stepping Y by `-24` per brick or `-8` per plate.

## Finding parts not in the palette

```bash
ldraw parts search "slope 45 2 x 2"   # list candidate codes
ldraw parts info 3039                  # confirm code, category, and import line
```

`ldraw parts info` prints the exact `from ldraw.library.parts... import ...`
line to use. Confirm any non-palette code this way before using it.

## Colours

Named colours live in `ldraw.library.colours` (generated). Import by name
(spaces → underscores), e.g. `Red`, `White`, `Black`, `Yellow`, `Blue`,
`Light_Bluish_Grey`, `Dark_Bluish_Grey`, `Reddish_Brown`, `Tan`. If unsure a
name exists, list them:

```bash
python -c "from ldraw.library.colours import ColoursByName; print('\n'.join(sorted(ColoursByName)))"
```

or fall back to a bare colour code int (`Piece.place(part, colour=4)` = red).

## Two worked examples

### Parametric: a wall (loops + constants)

```python
from ldraw import Model, Piece
from ldraw.geometry import Vector
from ldraw.library.parts import Brick2X4
from ldraw.library.colours import Light_Bluish_Grey

STUDS_WIDE = 8          # in studs
COURSES = 4             # brick rows tall
BRICK = 24              # LDU per brick
BRICK_LEN = 20 * 4      # 2x4 brick is 4 studs long

pieces = []
for course in range(COURSES):
    offset = (BRICK_LEN // 2) if course % 2 else 0   # stagger alternate rows
    x = -offset
    while x < 20 * STUDS_WIDE:
        pieces.append(Piece.place(
            Brick2X4, colour=Light_Bluish_Grey,
            position=Vector(x, -BRICK * course, 0)))
        x += BRICK_LEN

Model.from_pieces(pieces, name="wall.ldr", description="A staggered wall",
                  author="lego-model-builder").save("wall.ldr")
```

### Freeform: a tiny object

```python
from ldraw import Model, Piece
from ldraw.geometry import Vector
from ldraw.library.parts import Brick1X1, Plate1X1
from ldraw.library.colours import Red, Black

pieces = [
    Piece.place(Plate1X1, colour=Black, position=Vector(0, 0, 0)),
    Piece.place(Brick1X1, colour=Red, position=Vector(0, -8, 0)),      # on the plate
    Piece.place(Brick1X1, colour=Red, position=Vector(0, -8 - 24, 0)), # stacked
]
Model.from_pieces(pieces, name="tower.ldr", author="lego-model-builder").save("tower.ldr")
```

## Reading a model back (for the geometry check / debugging)

```python
from ldraw import read_model
model = read_model("wall.ldr")
for piece in model.pieces:        # Piece objects with .part, .colour, .position
    print(piece.part, piece.position)
```
