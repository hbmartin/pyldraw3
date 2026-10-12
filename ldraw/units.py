"""Standard LEGO dimensions expressed in LDraw units (LDU)."""

from typing import Final

STUD_PITCH: Final[int] = 20
PLATE_HEIGHT: Final[int] = 8
BRICK_HEIGHT: Final[int] = 24
LDU_TO_MM: Final[float] = 0.4

__all__ = ["BRICK_HEIGHT", "LDU_TO_MM", "PLATE_HEIGHT", "STUD_PITCH"]
