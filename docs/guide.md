# PyLDraw3 Onboarding Guide

Welcome to PyLDraw3. This guide will help you get started with creating LEGO
models programmatically using Python and the LDraw standard format.

## What is PyLDraw3?

PyLDraw3 is a Python package that allows you to create LDraw format files, a
standard used by CAD applications for LEGO models. With PyLDraw3, you can:

- Build LEGO models using Python code.
- Create minifigures with detailed positioning.
- Write standard `.ldr` files viewable in any LDraw-compatible viewer.
- Work with groups and transformations for complex scenes.

## Quick Start

### 1. Installation and Setup

First, ensure you have the package installed and set up your environment:

```bash
uv sync
source .venv/bin/activate
uv run ldraw download --version 2018-02 --yes
uv run ldraw generate --yes
```

### 2. Your First Model

Create a single LEGO brick:

```python
#!/usr/bin/env python

from ldraw.geometry import Identity, Vector
from ldraw.library.colours import Red
from ldraw.library.parts import Brick2X2
from ldraw.pieces import Piece

brick = Piece(
    colour=Red,
    position=Vector(0, 0, 0),
    matrix=Identity(),
    part=Brick2X2,
)

print(brick.to_ldraw())
```

This outputs LDraw format text that can be saved to a `.ldr` file and opened
in any LDraw-compatible viewer. `str(brick)` produces the same text; `repr`
is reserved for debugging.

### 3. Understanding the Coordinate System

LDraw uses a specific coordinate system:

- X-axis: left negative to right positive.
- Y-axis: top negative to bottom positive.
- Z-axis: front positive to back negative.

Positions are measured in LDraw units (LDU), where 1 LDU is about 0.4 mm.

### 4. Working with Colors

PyLDraw3 provides access to all standard LEGO colors:

```python
from ldraw.library.colours import (
    Black,
    Blue,
    Chrome_Gold,
    Chrome_Silver,
    Dark_Blue,
    Dark_Red,
    Green,
    Light_Grey,
    Red,
    Trans_Dark_Blue,
    Trans_Clear,
    Trans_Red,
    White,
    Yellow,
)
```

### 5. Basic Minifigure

Create a simple minifigure:

```python
from ldraw.figure import Person
from ldraw.library.colours import Black, Blue, Red, Yellow
from ldraw.library.parts.minifig.accessories import HairMale
from ldraw.library.parts.minifig.torsos import Torso

figure = Person()

print(figure.head(Yellow, 35))
print(figure.hat(Black, HairMale))
print(figure.torso(Red, Torso))
print(figure.hips(Blue))
print(figure.left_leg(Blue, 5))
print(figure.right_leg(Blue, 20))
print(figure.left_arm(Red, 0))
print(figure.left_hand(Yellow, 0))
print(figure.right_arm(Red, -90))
print(figure.right_hand(Yellow, 0))
```

## Intermediate Concepts

### Working with Groups

Groups organize pieces and apply transformations to multiple pieces at once:

```python
from ldraw.geometry import Identity, Vector, YAxis
from ldraw.library.colours import Blue, Red, Yellow
from ldraw.library.parts import Brick1X1, Brick2X2
from ldraw.pieces import Group, Piece

building = Group(Vector(0, 0, 0), Identity())

Piece(Red, Vector(0, 0, 0), Identity(), Brick2X2, group=building)
Piece(Blue, Vector(0, -24, 0), Identity(), Brick2X2, group=building)
Piece(Yellow, Vector(20, -48, 0), Identity(), Brick1X1, group=building)

building.position = Vector(100, 0, 0)
building.matrix = Identity().rotate(45, YAxis)

for piece in building.pieces:
    print(piece)
```

### Rotations and Transformations

PyLDraw3 uses 3D transformation matrices for positioning and rotating pieces:

```python
from ldraw.geometry import Identity, Vector, XAxis, YAxis
from ldraw.library.colours import Red
from ldraw.library.parts import Brick2X2
from ldraw.pieces import Piece

rotation = Identity()
rotation = rotation.rotate(90, YAxis)
rotation = rotation.rotate(45, XAxis)

piece = Piece(Red, Vector(0, 0, 0), rotation, Brick2X2)
```

### Advanced Minifigure Positioning

Create more dynamic poses and add accessories:

```python
from ldraw.figure import Person
from ldraw.geometry import Vector
from ldraw.library.colours import Black, Chrome_Silver, White, Yellow
from ldraw.library.parts.minifig.accessories import ToolMagnifyingGlass
from ldraw.library.parts.minifig.hats import TopHat
from ldraw.library.parts.minifig.heads import HeadWithMonocle_Scar_AndMoustachePattern
from ldraw.library.parts.minifig.torsos import TorsoWithBlackSuit_RedShirt_GoldClaspsPattern

detective = Person()
detective.head(Yellow, part=HeadWithMonocle_Scar_AndMoustachePattern)
detective.hat(Black, TopHat)
detective.torso(Black, TorsoWithBlackSuit_RedShirt_GoldClaspsPattern)
detective.left_arm(Black, 70)
detective.right_arm(Black, -30)
detective.left_hand(White, 0)
detective.right_hand(White, 0)

detective.right_hand_item(
    Chrome_Silver,
    Vector(0, -58, -20),
    0,
    ToolMagnifyingGlass,
)

detective.hips(Black)
detective.left_leg(Black, 50)
detective.right_leg(Black, -40)
```

### Building Models Programmatically

`Model` assembles programmatically built pieces into a saveable document.
`from_pieces` builds a model with header comments, `add` and `add_group`
append content, and `add_submodel` registers an MPD section and returns the
type-1 piece that references it:

```python
from ldraw import Group, Model, Person, Piece, Vector

model = Model.from_pieces(
    [Piece.place("3001", colour=4)],
    name="scene.ldr",
    description="A scene",
    author="you",
)

group = Group()
figure = Person(position=Vector(0, -48, 0), group=group)
figure.head(colour=14)
figure.torso(colour=4)
model.add_group(group)

wheels = Model.from_pieces([Piece.place("3005", colour=0)], name="wheels.ldr")
reference = model.add_submodel(wheels, position=Vector(0, -24, 0))

model.save("scene.ldr")
```

Query helpers work on built and parsed models alike:

```python
model.find_pieces(part="3001")
model.find_pieces(colour=4)
model.find_pieces(colour=4, recursive=True)
list(model.iter_pieces())
model.bill_of_materials()
```

`bill_of_materials` counts leaf pieces by part and colour. A submodel placed
twice contributes its pieces twice. Pass `parts=Parts.get(...)` to resolve
human-readable descriptions and colour names, and use `ldraw.bom.rows_to_csv`
or `rows_to_json` to export.

### Reading and Writing Model Files

`read_model` reads whole `.ldr` and `.mpd` files into a `Model`. MPD documents
are split on `0 FILE` / `0 NOFILE`: the first section becomes the root model
and later sections become submodels.

```python
from ldraw import parse_model, read_model

model = read_model("my_model.mpd")

print(model.description, model.header_name, model.author)
print(model.ldraw_org, model.license, model.bfc)

for piece in model.pieces:
    submodel = model.submodel_for(piece)
    print(piece.reference, submodel)

model.objects.append(
    parse_model("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat").objects[0],
)
model.save("my_model_out.mpd")
```

Every parsed object has a `to_ldraw()` method, and `str(model)` serializes the
whole document. Parse errors name the file and 1-based line number. For new
code, `Piece.place("3005", colour=4)` is a keyword-first alternative to the
positional `Piece` constructor.

### Querying and Validating from the CLI

The parts catalog and validator are available without writing Python:

```bash
ldraw parts search "cowboy"
ldraw parts info 3629
ldraw validate my_model.ldr
ldraw bom my_model.mpd
```

`ldraw validate` reports errors for malformed lines, unknown parts, and unknown
colour codes. It reports warnings for legacy dithered colours, scaled or
singular matrices, and unknown `!` meta-commands. It exits non-zero on errors;
add `--strict` to fail on warnings too. `ldraw stubs` writes an `ldraw-stubs/`
PEP 561 package to your project root so IDEs autocomplete `ldraw.library.*`
imports.

## Advanced Topics

### Scene Composition with Lighting

You can embed `LIGHT` pseudo-pieces in a scene. They have no effect in
PyLDraw3 itself, but are honored by some downstream raytracers when rendering
the exported `.ldr` file:

```python
from ldraw.geometry import Identity, Vector
from ldraw.library.colours import White
from ldraw.pieces import Piece

print(Piece(White, Vector(150, -100, -150), Identity(), "LIGHT"))
print(Piece(White, Vector(-150, -100, -150), Identity(), "LIGHT"))
print(Piece(White, Vector(0, -100, 150), Identity(), "LIGHT"))
```

### Building Complex Structures

Create repetitive structures using loops:

```python
from ldraw.geometry import Identity, Vector, YAxis
from ldraw.library.colours import Dark_Blue
from ldraw.library.parts import Brick2X3, Plate6X6
from ldraw.pieces import Group, Piece

stairs = Group()

x, y, z = -120, 144, -160
steps = 5

Piece(Dark_Blue, Vector(x, y, z + 40), Identity(), Plate6X6, group=stairs)

for i in range(steps):
    for pz in range(z, z + 120, 40):
        Piece(
            Dark_Blue,
            Vector(x + 50 + (i * 40), y - 24 - (i * 24), pz),
            Identity(),
            Brick2X3,
            group=stairs,
        )

staircases = 7
for i in range(1, staircases + 1):
    stairs.position = Vector(0, i * (8 + steps * 24), 0)
    stairs.matrix = Identity().rotate(-90 * i, YAxis)
    for piece in stairs.pieces:
        print(piece)
```

### Working with Different Part Categories

The LDraw library organizes parts into categories:

```python
from ldraw.library.parts import *
from ldraw.library.parts.minifig.accessories import *
from ldraw.library.parts.minifig.hats import *
from ldraw.library.parts.minifig.heads import *
from ldraw.library.parts.minifig.torsos import *
```

## Best Practices

1. Use groups for organization.
2. Use descriptive variable names for complex models.
3. Break complex models into functions that return groups of pieces.
4. Document the purpose of complex positioning or rotations.
5. Generate LDR files frequently to verify the model looks correct.
6. Save both Python source and generated LDR files in version control when the
   generated model is an intentional artifact.

## Troubleshooting

### Part Not Found

If generated library imports fail, ensure you have run:

```bash
uv run ldraw generate --yes
```

### Wrong Colors

Import colors from `ldraw.library.colours` and use the correct color
constants.

### Positioning Issues

Remember that the LDraw Y-axis is inverted: positive Y goes down. Use small
incremental changes to fine-tune positions.

### Missing Library

If parts imports fail after switching versions, download and regenerate:

```bash
uv run ldraw download --version 2018-02 --yes
uv run ldraw generate --yes
```

## Next Steps

1. Explore the `examples/` directory for more complex model ideas.
2. Open generated `.ldr` files in an LDraw viewer such as LDView, LeoCAD, or Stud.io.
3. Try building custom minifigures and vehicles.
4. Browse the [API reference](api/index.md) for details on the public classes
   and helper functions.
5. Create reusable model components.
