"""Create a small MPD with renderer-neutral building instructions."""

from ldraw import (
    CameraState,
    InstructionBuilder,
    Model,
    Piece,
    RotationMode,
    Vector,
)
from ldraw.instructions import CalloutMode, InstructionScope

module = Model(name="module.ldr")
module_builder = InstructionBuilder(module)
module.add(Piece.place("3001", colour=16))
module_builder.highlight(module.pieces[0])
module_builder.note("Build the reusable module")
module_builder.step()

model = Model(name="instructions.mpd")
builder = InstructionBuilder(model)
with builder.callout(mode=CalloutMode.ASSEMBLED):
    model.add_submodel(module, colour=4, position=Vector(20, 0, 0))
builder.arrow(Vector(0, 0, 0), Vector(20, 0, 0), label="attach")
builder.step()

model.add(Piece.place("3005", colour=1, position=Vector(-20, 0, 0)))
builder.set_camera(CameraState(fov=35), scope=InstructionScope.LOCAL)
builder.rotation_step(0, 90, 0, mode=RotationMode.ADDITIVE)

print(model.to_ldraw())
