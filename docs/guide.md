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

Create and save a model without generating Python part modules:

```python
from pathlib import Path
from ldraw import Matrix, Model, Piece, Vector, LDrawSession
from ldraw.units import STUD_PITCH, PLATE_HEIGHT, BRICK_HEIGHT, LDU_TO_MM

model = Model(name="first.ldr")
model.add(Piece.place("3001", colour=4))
model.add(
    Piece.place(
        "3005",
        colour=14,
        position=Vector(STUD_PITCH, -BRICK_HEIGHT, 0),
        matrix=Matrix.rotation(x=0, y=90, z=0),
    )
)
model.save(Path("first.ldr"))
parts = LDrawSession().load()
print(parts.description_for("3001"))
```

`Matrix.rotation(*, x=0, y=0, z=0, units=Degrees)` returns a fresh matrix,
equivalent to the existing local X/Y/Z `Identity().rotate(...)` chain.
Use `Radians` from `ldraw.geometry` for radian angles. Each matrix is independent.
Units are LDU: stud pitch 20, plate height 8, brick height 24; multiply by
`LDU_TO_MM` (0.4) for millimetres. The historical `ldraw.model_summary.LDU_TO_MM`
import remains available.

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
from ldraw.library.parts.minifig.torsos import (
    TorsoWithBlackSuit_RedShirt_GoldClaspsPattern,
)

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

### Semantic Building Instructions

Raw LDraw objects remain the source of truth. Call
`model.instruction_document(parts=parts)` to layer typed instruction semantics
over them. The resulting document lists the root first, then reachable
non-`.dat` MPD sections in file order. Every section numbers its own steps;
submodel steps are never merged into a fabricated global sequence.

```python
from ldraw import CameraState, InstructionBuilder, Model, Piece, RotationMode
from ldraw.instructions import InstructionScope

model = Model(name="main.ldr")
builder = InstructionBuilder(model)

model.add(Piece.place("3001", colour=4))
builder.note("PDF page 1")
builder.step()

model.add(Piece.place("3005", colour=1))
builder.set_camera(CameraState(fov=35), scope=InstructionScope.LOCAL)
builder.rotation_step(0, 90, 0, mode=RotationMode.ADDITIVE)

for step in model.iter_instruction_steps():
    print(step.number, step.rotation, step.camera)
    print(step.added_bill_of_materials())
```

`InstructionStep.added_occurrences()` and `cumulative_occurrences()` expand
`.ldr` submodels explicitly while treating embedded `.dat` sections as part
dependencies. Their BOM counterparts accept `expand_submodels=` and
`respect_lpub=`. LPub `PLI`, `BOM`, and `PART BEGIN IGN` ranges affect the
appropriate inventory views but never remove snapshot geometry.

Balanced context managers make structural authoring exception-safe:

```python
from ldraw.instructions import CalloutMode, InventoryTarget

with builder.callout(mode=CalloutMode.ROTATED):
    model.add_submodel(module)

with builder.multi_step(), builder.ignore(InventoryTarget.PLI):
    model.add(Piece.place("3001"))
    builder.step()
```

Use `iter_instruction_issues(document, max_parts=...)` for structured
diagnostics. The instruction CLI adds catalog-backed inspection, combined
LDraw/instruction validation, JSON export, and paired cumulative snapshots.
It does not perform page layout or PDF/image rendering.

### Querying and Validating from the CLI

The parts catalog and validator are available without writing Python:

```bash
ldraw parts search "cowboy"
ldraw parts info 3629
ldraw validate my_model.ldr
ldraw bom my_model.mpd
ldraw instructions inspect my_model.mpd --parts
ldraw instructions validate my_model.mpd --strict
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

## Compare a model with inventory CSV

```python
from ldraw import compare_inventory, read_inventory, read_model

inventory = read_inventory("inventory.csv")
comparison = compare_inventory(
    read_model("scene.mpd"), inventory, part_aliases={"old-part": "new-part"}
)
for difference in comparison.differences:
    print(
        difference.part,
        difference.colour,
        difference.expected,
        difference.actual,
        difference.missing,
        difference.extra,
    )
assert comparison.matched
```

`InventoryComparison` and `InventoryDifference` are immutable. Repeated rows
aggregate, nested/repeated submodels expand, and inherited colours resolve.
Native BOM CSV accepts `part`, `colour_code`, and `quantity`; direct RGB BOM
rows use `colour_name` when `colour_code` is empty. Quantities must be
nonnegative integers. Missing columns, invalid quantities/colours, cycles,
and unresolved model references fail rather than produce partial matches.

Leaf references without an explicit `.dat` suffix need `parts.lst` evidence
after submodel expansion. Pass `parts=parts` to `compare_inventory` to accept
listed identifiers case-insensitively, including dotted identifiers. The
whole reference must be listed, even if its stem names a known part.
Ordinary BOMs use the same full identifiers, stripping only a terminal `.dat`
suffix. Dotted identifiers remain distinct, and a model matches its own BOM.
Parsing and piece construction preserve these dotted part identities in
`Piece.part` and leaf `ModelOccurrence.part_code`, so model summaries and BOMs
use the same dotted identities. Summaries count raw `part_code` spellings
separately; BOMs additionally aggregate case and separator variants.
Serialized reference spelling and suffix case remain unchanged.
`Piece.place("custom.v1")` uses the default reference `custom.v1.dat`, matching
the constructor. Recognized `.dat`, `.ldr`, and `.mpd` endings retain their
existing spelling; an explicit empty suffix keeps a reference suffix-free.
Earlier factory behavior kept `custom.v1` suffix-free; callers requiring that
reference should pass `suffix=""`. An explicit `suffix=".dat"` retains the
factory's existing handling of recognized endings, just like the default.
When supplying occurrences directly, their `part_code` values are authoritative,
including caller-provided replacements. BOM rows preserve the first identifier's
case and separators while aggregating equivalent spellings.
Default unresolved or deliberately unexpanded `.ldr`/`.mpd` leaf occurrences
keep their full reference, distinguishing them from same-named `.dat` parts.
Unresolved `.ldr`/`.mpd` references always fail; ambiguous references fail
before aliases are applied. Explicit `.dat` references do not require a
catalog, and resolved submodels expand normally.

For third-party CSV, `read_inventory(columns={"part": "Part ID",
"colour": "Colour ID", "quantity": "Qty"}, colour_map={"red": 4})`
explicitly maps headers and colour values. A supplied colour map must cover
every inventory colour. Colours map only on input; `compare_inventory` part
aliases canonicalize both sides, including case and `.dat` suffixes.

Validation emits `model.duplicate_placement` warnings for equality of
normalized reference, colour, and transformed position and matrix at LDraw
serialization precision within one section,
including across STEP boundaries. The later line identifies the first
occurrence. Independent MPD sections are checked separately; `--strict`
makes these warnings fail validation.

NaN and Infinity remain parsed objects so they can be inspected and repaired.
Report-oriented loading emits `model.non_finite_numeric` errors for their
coordinates or matrices, including type-2–5 vertices. If every source object
parsed, `complete` remains true while `valid` is false. Duplicate checks skip
these placements, inventory comparison refuses the invalid model, and
serialization raises a clear `ValueError` until the values are repaired.
Geometry representations remain readable for inspection, including `repr()` of
objects containing NaN or Infinity. The Python `compare_inventory` API rejects
non-finite geometry in every declared Model section, including type-2–5 objects,
and in additional sections reached through a custom resolver;
occurrence-only providers are checked for non-finite expanded transforms.
For `root.submodel_view(name)`, comparison checks the selected section and its
reachable submodels, ignoring unrelated siblings in the shared resolution table.
This includes a view of the root's own name. Views forward state reads and writes
to the selected model, including scalar subclass attributes and replacement
object lists or source mappings. They resolve references through the original
root's resolver, including when creating further views. View creation invokes
neither instance constructors, copying/state hooks, nor the selected class's
`__init_subclass__` hook or custom metaclass creation hooks. A private adapter
inherits the selected class, so `isinstance(view, SelectedClass)` and `super()`
work, while `type(view)` can differ from `type(selected)`. `view.__class__`
reports the selected class, allowing ordinary construction through
`self.__class__`, `dataclasses.replace`, and familiar representations.
Calling `type(view)(...)` also constructs an ordinary selected-class instance,
honoring its constructor and metaclass call behavior once. A private dispatcher
metaclass handles this construction; internal view allocation bypasses it.

Inherited descriptors bind to the view, including cached methods,
`singledispatchmethod`, `partialmethod`, and custom descriptors. Class factories
remain bound to the selected class. Cached properties have a separate view
cache: pre-existing values on the selected model are ignored, and assigning or
deleting a cached property affects only that view. They follow normal explicit
cache invalidation; delete a cached property when its inputs change. A view's
`__dict__` exposes this descriptor cache, while ordinary attributes and slot
state continue forwarding to the selected model. Custom non-data descriptors
that cache their value under their own attribute name through `setattr` or
`__dict__` also cache on the view. Later assignment and deletion affect that
view-owned value. Existing selected-model instance overrides remain authoritative
for custom descriptors; `cached_property` alone ignores selected cache entries.
Class-level descriptor changes are looked up live, without a persistent binding
cache. Assignment or deletion of `__class__` or `__dict__` is rejected, and an
initialized view cannot be rebound through `__setstate__`.

`copy.copy(view)` produces another live view of the same selected model and
resolution root. `copy.deepcopy(view)` copies both in one graph, preserving
their relationship and cyclic backreferences. Pickle restores the same view
bindings in the restored graph. These operations start with empty derived view
caches. Explicit deep-copy and pickle operations honor underlying objects'
normal copying and serialization hooks, including their failures; custom
classes must be pickleable under Python's normal rules. Adapter types are
cached weakly and are collectible when no live users retain them.

`dataclasses.replace(view)` carries its selected source in the optional private
keyword-only `Model._serialization_origin` field. A replacement can supersede
that specific dependency during serialization, including through further
replacements. Unrelated same-named dependencies still raise. This field is
excluded from repr, equality, and manifests. Strict manual subclass constructors
must accept or forward this keyword when used with `dataclasses.replace`;
existing positional Model parameters are unchanged.

Built-in traversal checks every composed placement, including overflow from
finite inputs into empty submodels or submodels containing geometry without
leaf parts.
Subclasses inheriting `Model.iter_occurrences` use the same validated traversal.
Custom traversal overrides keep their emitted occurrences authoritative; their
reachable submodel placements are separately audited for overflow, and their
emitted part transforms receive full numeric checks. Thus a filtered part-only
transform can overflow without failing comparison, while overflow into a
filtered empty submodel still fails. The source audit stops cyclic re-entry and
does not classify unresolved source leaves. Resolver `KeyError`s naming the
requested reference or stem are treated as mapping-style misses; unrelated
resolver errors propagate. Explicit `.dat` references can still resolve to
embedded or dynamically supplied submodels. Occurrence-only
providers can be checked only through the transforms they emit.
Unresolved emitted references fail immediately during preparation, so a later
invalid provider transform does not replace that error. Concrete model source
geometry is validated before occurrence preparation.
Reachable source discovery stops active reference-name cycles even when a
custom resolver creates fresh section objects on every call. Newly encountered
cycle-closing sections still receive numeric checks. Distinct acyclic sections
sharing a name are checked separately. Iterative source discovery first walks
by identity while checking normalized-name uniqueness, so shared acyclic and
cyclic graphs with unique names expand each source once. Distinct objects with
the same normalized name switch discovery to ancestry-sensitive traversal,
reusing cached edges and numeric checks. Later acyclic routes can still expose
descendants hidden by a cycle. Occurrence expansion, comparison audits, and
loading's structural cycle diagnostics also use explicit stacks, allowing deep
API and CLI comparisons without Python's recursive-call limit. Built-in comparison
retains its normal cycle error, while custom source audits stop cyclic re-entry
without replacing the override's occurrences.
Parsing-completeness checks additionally belong to the CLI's report-oriented
loading, since a raw Model does not retain a discarded source line's history.

Both `bill_of_materials(model)` and `model.bill_of_materials()` honor custom
occurrence traversal, including relabelling and filtering. Analysis uses the
same authoritative occurrences; summaries keep their raw identity aggregation.
BOM generation, analysis, summaries, and comparison accept overrides returning
iterables such as lists or tuples. Traversal flags are adapted independently to
override signatures, including positional-only parameters and intervening
defaults. Unsupported `include_steps` is omitted, preserving provider metadata;
unsupported default expansion is omitted too. An explicit unsupported
`expand_submodels=False` request raises `TypeError`. Exceptions from an override
are propagated without retrying its body.
BOM generation, analysis, and summaries skip built-in expansion cycles and
cycles in overrides delegating to `super()`. Other custom exceptions propagate.
The cycle policy applies only while creating or advancing that model's iterator,
resets before yielding, and does not affect ordinary public iteration.

Instruction documents include each reachable section once, including when
built from a view. Documents retain their own resolved reference targets, so
sections, step inventories, manifests, and snapshots use the objects selected
by a custom resolver even when the declared table holds a stale object with the
same name. Declared section order is retained and external targets follow in
discovery order; build a new document to discover changed resolver results.
The document owns one resolution context, shared by its steps. Copies made
with `dataclasses.replace` retain that context; replacing it binds new steps
without modifying the original document. A context belonging to a different
root or selected section raises `ValueError`.
To rebind existing sections explicitly, use
`dataclasses.replace(document, model=new_model, _resolution=None)`; to rebuild
their contents, use `new_model.instruction_document()`.

The `InstructionStep` constructor no longer accepts `_root`: its required
keyword-only `_resolution` field is the sole resolution authority. The document's
optional keyword-only `_resolution` field creates a context when omitted.
Callouts retain their actual source placements in optional keyword-only
`_pieces` metadata, excluded from representations, equality, and manifests.
Manual callouts without that metadata match cumulative source references;
another placement's alias cannot make an unresolved callout valid. Edited public
references remain authoritative: retained references keep their source identities,
added references use the cumulative source index, and removed references are
ignored by validation.

Step occurrences and BOMs in root-reachable sections keep references back to
the document root as unexpanded leaves. Orphan sections expand ordinary root
placements. Other active-path cycles emit the closing reference once,
preserving its full identity and composed transform. This lets step inspection
and `max_parts` validation finish with cycle diagnostics. Ordinary model
iteration and comparison retain their existing cycle errors.
Temporary expansion models own their dependency dictionaries: unexpanded
models have no dependencies, and expanded models register encountered canonical
instruction sections. Serialization closes their required dependencies separately
from counting's cycle cuts, including retained root references. Editing those
dictionaries does not change the root table.
Snapshot dependencies omit the section already being rendered, so self-references
do not produce duplicate `0 FILE` blocks. The private MPD writer preserves
recursive references; public paired snapshot export rejects cycles and leaves
no partially published output.

Model serialization emits the selected section once and collapses dependency
aliases referring to the same source, including a view and its raw section.
Distinct dependency objects with conflicting
normalized names raise `DuplicateSubmodelError`; raw names and reference spelling
are preserved. Instruction counts remain authoritative when custom resolvers
choose different definitions for the same name. Temporary-model serialization
and instruction exports reject those conflicts with `DuplicateSubmodelError`.
Resolver mappings requiring reference rewriting raise `ValueError` instead of
publishing a misleading file. Export failures preserve existing outputs. These
corrections keep package version and manifest schema v1 unchanged.

Connection-corpus verification hashes effective ZIP content: exact repeated
filenames use the last entry, matching extraction, while distinct names that
collide after normalization are rejected. Archive content is verified before
selection or output writes. Snapshot source paths and embedded provenance paths
use lowercase POSIX library-relative names, consistent with content identity.
Symlink aliases resolve against the library root, and archive-member names use
the same case and separator normalization. Descriptive text, identifiers, include
markers, and metadata command text are preserved. Filesystem provenance must
resolve inside the library root. Existing manifest checks precede archive reads;
the raw archive checksum is recorded only after archive content verification.
Empty archive-member strings remain empty and use the filesystem or other
origin for display. Ambiguous secondary attribution is preserved; relative
source entries containing whitespace require structured provenance for
normalization.
