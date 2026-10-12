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
    name="example.ldr",  # becomes the file's model name
    description="An example",
    author="lego-model-builder",
)
model.save("example.ldr")  # writes the .ldr file
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
pieces = [
    Piece.place(Brick1X1, colour=Red, position=Vector(0, -24 * i, 0)) for i in range(3)
]
```

### Vector scalar multiply works on either side

`Vector` implements both `__mul__` and `__rmul__` for `int | float` scalars:

```python
20 * Vector(1, 0, 0)  # Vector(20, 0, 0)
Vector(1, 0, 0) * 20  # Vector(20, 0, 0)
```

### Rotation

`Matrix.rotate(angle, axis, units=Degrees)`; axes are the marker classes
`XAxis` / `YAxis` / `ZAxis` (passed as types). Rotate about vertical Y:

```python
from ldraw.geometry import Identity, YAxis

m = Identity().rotate(90, YAxis)  # quarter turn about the up axis
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
"$PYTHON_BIN" -m ldraw.cli parts search "slope brick 45 2 x 2"  # candidate codes
"$PYTHON_BIN" -m ldraw.cli parts info 3039     # confirm code, category, import line
```

`ldraw parts info` prints the exact `from ldraw.library.parts... import ...`
line to use. Confirm any non-palette code this way before using it.

## Colours

Named colours live in `ldraw.library.colours` (generated). Import by name
(spaces → underscores), e.g. `Red`, `White`, `Black`, `Yellow`, `Blue`,
`Light_Bluish_Grey`, `Dark_Bluish_Grey`, `Reddish_Brown`, `Tan`. If unsure a
name exists, list them:

```bash
"$PYTHON_BIN" -c "from ldraw.library.colours import ColoursByName; print('\n'.join(sorted(ColoursByName)))"
```

or fall back to a bare colour code int (`Piece.place(part, colour=4)` = red).

## Two worked examples

### Parametric: a wall (loops + constants)

```python
from ldraw import Model, Piece
from ldraw.geometry import Vector
from ldraw.library.parts import Brick2X4
from ldraw.library.colours import Light_Bluish_Grey

STUDS_WIDE = 8  # in studs
COURSES = 4  # brick rows tall
BRICK = 24  # LDU per brick
BRICK_LEN = 20 * 4  # 2x4 brick is 4 studs long

pieces = []
for course in range(COURSES):
    offset = (BRICK_LEN // 2) if course % 2 else 0  # stagger alternate rows
    x = -offset
    while x < 20 * STUDS_WIDE:
        pieces.append(
            Piece.place(
                Brick2X4,
                colour=Light_Bluish_Grey,
                position=Vector(x, -BRICK * course, 0),
            )
        )
        x += BRICK_LEN

Model.from_pieces(
    pieces, name="wall.ldr", description="A staggered wall", author="lego-model-builder"
).save("wall.ldr")
```

### Freeform: a tiny object

```python
from ldraw import Model, Piece
from ldraw.geometry import Vector
from ldraw.library.parts import Brick1X1, Plate1X1
from ldraw.library.colours import Red, Black

pieces = [
    Piece.place(Plate1X1, colour=Black, position=Vector(0, 0, 0)),
    Piece.place(Brick1X1, colour=Red, position=Vector(0, -8, 0)),  # on the plate
    Piece.place(Brick1X1, colour=Red, position=Vector(0, -8 - 24, 0)),  # stacked
]
Model.from_pieces(pieces, name="tower.ldr", author="lego-model-builder").save(
    "tower.ldr"
)
```

## Reading a model back (for the geometry check / debugging)

```python
from ldraw import read_model

model = read_model("wall.ldr")
for piece in model.pieces:  # Piece objects with .part, .colour, .position
    print(piece.part, piece.position)
```

<!-- public-api:start -->
## Public API inventory

- `ldraw.ALL_CATALOG_SEARCH_FIELDS`
- `ldraw.AnnularProfile`
- `ldraw.ApiEntry`
- `ldraw.ApiInventory`
- `ldraw.BfcCertification`
- `ldraw.BomReport`
- `ldraw.BomRow`
- `ldraw.BoundingBox`
- `ldraw.BoundsGap`
- `ldraw.CameraState`
- `ldraw.CancellationToken`
- `ldraw.CatalogBuildOutcome`
- `ldraw.CatalogBuildReport`
- `ldraw.CatalogEntry`
- `ldraw.CatalogPreparationResult`
- `ldraw.CatalogSearchField`
- `ldraw.CatalogSearchResult`
- `ldraw.Colour`
- `ldraw.ConnectionContact`
- `ldraw.ConnectionFeature`
- `ldraw.ConnectionFreedom`
- `ldraw.ConnectionGraphEdge`
- `ldraw.ConnectionGraphs`
- `ldraw.ConnectionKind`
- `ldraw.ConnectionMetadataCoverage`
- `ldraw.ConnectionMetadataReport`
- `ldraw.ConnectionMultigraph`
- `ldraw.ConnectionProvenance`
- `ldraw.ConnectionResidual`
- `ldraw.ConnectionRole`
- `ldraw.ConnectionSource`
- `ldraw.ConnectionStatus`
- `ldraw.ContactReport`
- `ldraw.Coverage`
- `ldraw.CylindricalCaps`
- `ldraw.CylindricalProfile`
- `ldraw.CylindricalSection`
- `ldraw.Diagnostic`
- `ldraw.DiagnosticCode`
- `ldraw.DoctorReport`
- `ldraw.DownloadPlan`
- `ldraw.ExtractionAttribution`
- `ldraw.ExtractionResult`
- `ldraw.FingerProfile`
- `ldraw.GenericBounds`
- `ldraw.GenericBoundsKind`
- `ldraw.GenericMatch`
- `ldraw.GenericPlacement`
- `ldraw.GenericProfile`
- `ldraw.Group`
- `ldraw.Identity`
- `ldraw.InstructionBuilder`
- `ldraw.InstructionDocument`
- `ldraw.InstructionIssue`
- `ldraw.InstructionSection`
- `ldraw.InstructionStep`
- `ldraw.InventoryComparison`
- `ldraw.InventoryDifference`
- `ldraw.LDCadShadowLibrary`
- `ldraw.LDrawCapability`
- `ldraw.LDrawPaths`
- `ldraw.LDrawSession`
- `ldraw.LDrawState`
- `ldraw.LDrawStateReason`
- `ldraw.LibraryComponent`
- `ldraw.LibraryInspection`
- `ldraw.LibraryOrigin`
- `ldraw.Matrix`
- `ldraw.MinifigSection`
- `ldraw.Model`
- `ldraw.ModelAnalysis`
- `ldraw.ModelInspection`
- `ldraw.ModelLoadResult`
- `ldraw.ModelOccurrence`
- `ldraw.ModelSummary`
- `ldraw.OccurrenceAttribution`
- `ldraw.OccurrenceContact`
- `ldraw.OccurrenceGeometry`
- `ldraw.OccurrencePathItem`
- `ldraw.OperationCancelled`
- `ldraw.PartCategory`
- `ldraw.PartCompatibility`
- `ldraw.PartFileKind`
- `ldraw.PartGeometry`
- `ldraw.PartHistoryEntry`
- `ldraw.PartInspection`
- `ldraw.PartMeasurements`
- `ldraw.PartMetadata`
- `ldraw.PartReference`
- `ldraw.PartReferenceKind`
- `ldraw.PartStatus`
- `ldraw.Parts`
- `ldraw.PartsCatalog`
- `ldraw.Person`
- `ldraw.Piece`
- `ldraw.PreviewTransform`
- `ldraw.ProgressEvent`
- `ldraw.ProgressStage`
- `ldraw.ProgressUnit`
- `ldraw.RawGeometry`
- `ldraw.RenderBackend`
- `ldraw.RenderCapability`
- `ldraw.RenderResult`
- `ldraw.RenderView`
- `ldraw.RotationMode`
- `ldraw.RotationStep`
- `ldraw.SectionShape`
- `ldraw.Severity`
- `ldraw.SkippedGeometry`
- `ldraw.SkippedOccurrenceGeometry`
- `ldraw.SnapCandidate`
- `ldraw.SnapReport`
- `ldraw.SnapTransform`
- `ldraw.StudContact`
- `ldraw.StudReference`
- `ldraw.StudioConnectionLibrary`
- `ldraw.ValidationIssue`
- `ldraw.Vector`
- `ldraw.XAxis`
- `ldraw.YAxis`
- `ldraw.ZAxis`
- `ldraw.analyze_model`
- `ldraw.angular_alignment_within`
- `ldraw.api_inventory`
- `ldraw.bill_of_materials`
- `ldraw.bom_report`
- `ldraw.bounds_gap`
- `ldraw.compare_inventory`
- `ldraw.connection_residual`
- `ldraw.connections_compatible`
- `ldraw.discover_libraries`
- `ldraw.doctor`
- `ldraw.download`
- `ldraw.ensure_library`
- `ldraw.generate`
- `ldraw.inspect_library`
- `ldraw.inspect_model`
- `ldraw.iter_instruction_issues`
- `ldraw.iter_ldr_issues`
- `ldraw.load_model`
- `ldraw.model_bounds`
- `ldraw.parse_model`
- `ldraw.parse_model_result`
- `ldraw.part_measurements`
- `ldraw.plan_download`
- `ldraw.prepare_catalog`
- `ldraw.read_inventory`
- `ldraw.read_model`
- `ldraw.render_capabilities`
- `ldraw.render_preview`
- `ldraw.snap_transform`
- `ldraw.bom.comparison_to_csv`
- `ldraw.units.STUD_PITCH`
- `ldraw.units.PLATE_HEIGHT`
- `ldraw.units.BRICK_HEIGHT`
- `ldraw.units.LDU_TO_MM`
- `ldraw.bom.rows_to_csv`
- `ldraw.bom.rows_to_json`
- `ldraw.config.Config`
- `ldraw.errors.NoGeometryError`
- `ldraw.errors.PartNotFoundError`
- `ldraw.errors.UnknownSubmodelError`
- `ldraw.part_geometry.part_bounding_box`
- `ldraw.part_geometry.part_studs`
- `ldraw.parts.symbol_description`
- `ldraw.snippets.module_path`
- `ldraw.snippets.suggested_import`
- `ldraw.snippets.symbol_name`
- `ldraw.snippets.symbol_name_for_description`
<!-- public-api:end -->
