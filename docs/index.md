# pyldraw3

`pyldraw3` is a modern Python package for creating and manipulating LDraw
format files, the standard used by CAD applications for LEGO models. It is a
drop-in replacement for the unmaintained `pyldraw` library.

## Features

- Complete LDraw format support for creating `.ldr` and `.mpd` files.
- Pythonic model construction with `Piece`, `Group`, `Model`, and `Person`.
- Dynamic `ldraw.library.*` modules generated from a downloaded LDraw library.
- Catalog search, validation, bill-of-materials export, and type-stub helpers.
- Geometry queries for bounding boxes and stud positions.

## Installation

```bash
uv add pyldraw3
```

## Setup

Activate your virtual environment and set up the LDraw library:

```bash
source .venv/bin/activate
ldraw download --yes
ldraw generate --yes
```

By default, `ldraw download` fetches the `complete` LDraw release. To pin a
specific dated release for reproducible builds, pass `--version`:

```bash
ldraw download --version 2018-02 --yes
ldraw generate --yes
```

Each downloaded release is cached separately, and `ldraw generate` builds
`ldraw.library.*` from whichever release is currently configured.

## Quick Example

```python
from ldraw import Group, Identity, Piece, Vector
from ldraw.library.colours import Light_Grey
from ldraw.library.parts.bricks import Brick1X2WithClassicSpaceLogoPattern

model = Group()
Piece(
    Light_Grey,
    Vector(-10, -32, -90),
    Identity(),
    Brick1X2WithClassicSpaceLogoPattern,
    model,
)

with open("my_model.ldr", "w") as ldr_file:
    print(model, file=ldr_file)
```

For runtime part lookup by catalog description or LDraw code, use `Parts`:

```python
from pathlib import Path

from ldraw.config import Config
from ldraw.parts import Parts

config = Config.load()
parts = Parts(Path(config.ldraw_library_path) / "ldraw" / "parts.lst")
cowboy_hat = parts.get_entry_by_description("Hat Cowboy").code
brick1x1 = parts.get_entry_by_description("Brick  1 x  1").code
```

For new code, `Piece.place` offers a keyword-first constructor with sensible
defaults:

```python
from ldraw import Piece

piece = Piece.place("3005", colour=4)
```

## Core API

The top-level `ldraw` package re-exports the main construction and file I/O
types:

```python
from ldraw import Group, Identity, Model, Parts, Person, Piece, Vector, read_model
```

`Model` bridges programmatic construction and file I/O:

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
model.add_submodel(wheels, position=Vector(0, -24, 0))

model.find_pieces(colour=4)
list(model.iter_pieces())
model.bill_of_materials()
model.save("scene.ldr")
```

## Reading Model Files

`read_model` parses `.ldr` and `.mpd` files, including MPD `0 FILE` /
`0 NOFILE` sections:

```python
from ldraw import read_model

model = read_model("my_model.ldr")
print(model.description, model.author)

for piece in model.pieces:
    print(piece.part, piece.position)

model.save("my_model_out.ldr")
```

Every parsed object has a `to_ldraw()` method, so parsed content round-trips
back to LDraw text. Parse errors report the file and 1-based line number.

## Next Steps

- Read the [full guide](guide.md).
- Review the [CLI reference](cli.md).
- Explore the `examples/` directory in the repository.
- Open generated `.ldr` files in an LDraw viewer such as LDView, LeoCAD, or Stud.io.
