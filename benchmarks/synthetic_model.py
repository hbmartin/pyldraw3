"""Reproducible 360-piece workload shared by CI and local profiling."""

from ldraw.geometry import Matrix, Vector
from ldraw.model import Model
from ldraw.pieces import Piece

PART_CODES = (
    "3001",
    "3002",
    "3003",
    "3004",
    "3005",
    "3020",
    "3021",
    "3022",
    "3023",
    "3024",
    "3062b",
    "3070b",
)


def synthetic_model() -> Model:
    """Build six rotated modules, each placed three times (360 leaf pieces)."""
    model = Model(name="benchmark.mpd")
    for variant in range(6):
        child = Model(name=f"module-{variant}.ldr")
        for index in range(20):
            child.add(
                Piece.place(
                    PART_CODES[(index + variant) % len(PART_CODES)],
                    colour=16,
                    position=Vector((index % 5) * 60, -(index // 5) * 32, variant * 4),
                    matrix=Matrix.rotation(y=(index % 4) * 90),
                )
            )
        for repeat in range(3):
            model.add_submodel(
                child,
                colour=(1, 4, 14)[repeat],
                position=Vector(variant * 400, 0, repeat * 400),
                matrix=Matrix.rotation(y=repeat * 90),
            )
    return model
