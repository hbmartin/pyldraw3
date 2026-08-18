"""Physical connection inference, metadata, compatibility, and snapping."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ldraw.connection_metadata import (
    ConnectionMetadataCoverage,
    LDCadShadowLibrary,
    parse_ldcad_commands,
)
from ldraw.connection_studio import StudioConnectionLibrary
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    ConnectionStatus,
    CylindricalProfile,
    CylindricalSection,
    FingerProfile,
    GenericProfile,
    SectionShape,
    connection_residual,
    connections_compatible,
    snap_transform,
)
from ldraw.diagnostics import DiagnosticCode
from ldraw.geometry import Identity, Matrix, Vector, YAxis
from ldraw.inspection import bounds_gap, inspect_model
from ldraw.model import parse_model
from ldraw.part_geometry import part_connections, part_geometry
from ldraw.parts import Parts

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.part import Part

_IDENTITY = "1 0 0 0 1 0 0 0 1"
_ROTATE_X_180 = "1 0 0 0 -1 0 0 0 -1"
# The Y scale stretches a four-LDU tube through a twenty-LDU brick body; the
# matching Z negation keeps the transform a rotation plus scale, not a mirror.
_ROTATE_X_180_SCALE_Y_5 = "1 0 0 0 -5 0 0 0 -1"
_SCALE_XZ_2 = "2 0 0 0 1 0 0 0 2"
_SINGULAR_XZ = "0 0 0 0 1 0 0 0 0"
_SINGULAR_COLLINEAR_XZ = "1 0 1 0 1 0 0 0 0"
# Determinant 1e-8 stays under Matrix.is_singular's 1e-6 tolerance, so the
# placement keeps full confidence and a raw, uniformly shrunken X/Z basis.
_SHRUNKEN_XZ = "0.00000001 0 0 0 1 0 0 0 0.00000001"
# Only the Y column collapses, leaving a usable X/Z pair but a zero axis.
_SINGULAR_Y = "1 0 0 0 0 0 0 0 1"
# A reflection is orthonormal and non-singular, so it survives every rank
# check; only the inheritance rules reject it.
_MIRROR_X = "-1 0 0 0 1 0 0 0 1"
# One stud per grid direction, so both the axial and the lateral sockets of a
# solid tube at x=40 find a matching phase.
_GRID_STUD_PAIR = (
    f"1 16 10 0 0 {_IDENTITY} stud.dat\n1 16 0 0 10 {_IDENTITY} stud.dat\n"
)


@dataclass(eq=False)
class _PartLibraryAdapter:
    _backing: Parts

    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part:
        return self._backing.part(description=description, code=code)


class _RimOnlyCompatibilityLibrary(_PartLibraryAdapter):
    def compatible_tyres(self, rim_code: str) -> tuple[str, ...]:
        return ("tyre",) if rim_code == "rim" else ()


class _TyreOnlyCompatibilityLibrary(_PartLibraryAdapter):
    def compatible_rims(self, tyre_code: str) -> tuple[str, ...]:
        return ("rim",) if tyre_code == "tyre" else ()


def _connections_with_kind(
    *,
    parts: Parts,
    code: str,
    kind: ConnectionKind,
) -> tuple[ConnectionFeature, ...]:
    return tuple(feature for feature in parts.connections(code) if feature.kind is kind)


def _connection_positions(
    features: Iterable[ConnectionFeature],
) -> set[tuple[float, float, float]]:
    return {
        (feature.position.x, feature.position.y, feature.position.z)
        for feature in features
    }


def _connection_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    scout_receptacles = "".join(
        f"1 16 {x} 0 {z} {_ROTATE_X_180} stud4.dat\n"
        for x in (-4, 4)
        for z in (-30, -10, 10, 30)
    )
    files = {
        "p/clip5.dat": ("0 Clip Primitive\n2 24 -8 -4 -8 8 4 8\n"),
        "p/peghole.dat": ("0 Technic Pin Hole End\n2 24 -8 0 -8 8 2 8\n"),
        "p/connect2.dat": ("0 Technic Pin\n2 24 -6 -20 -6 6 0 6\n"),
        "p/axlehol8.dat": ("0 Technic Axle Hole End\n2 24 -6 0 -6 6 2 6\n"),
        "p/npeghol.dat": ("0 Technic Pin Hole Negative End\n2 24 -8 0 -8 8 2 8\n"),
        "p/clh4.dat": ("0 Click Lock Hinge Half Dual Finger\n2 24 -6 -8 -6 6 8 6\n"),
        "p/clh1.dat": (
            "0 Click Lock Hinge Single Finger for Bricks\n2 24 -6 -8 -6 6 8 6\n"
        ),
        "p/stud.dat": "0 Stud\n2 24 -6 -4 -6 6 0 6\n",
        "p/stud3.dat": "0 Stud Tube Solid\n2 24 -4 0 -4 4 4 4\n",
        "p/stud4.dat": "0 Stud Tube Open\n2 24 -6 0 -6 6 4 6\n",
        "p/studplaceholder.dat": (
            "0 Stud Tube Solid Placeholder\n2 24 -4 0 -4 4 4 4\n"
        ),
        "p/studundersideplaceholder.dat": (
            "0 Stud Underside Placeholder\n2 24 -4 0 -4 4 4 4\n"
        ),
        "p/stud4f4s.dat": (
            "0 Stud Tube Open with 4 Fillets Standard\n2 24 -6 0 -6 6 4 6\n"
        ),
        "parts/bar1.dat": ("0 Bar 3L\n0 Name: bar1.dat\n2 24 -4 0 -4 4 60 4\n"),
        "parts/blank.dat": ("0 Blank Tile\n2 24 -10 0 -10 10 4 10\n"),
        "parts/clipper.dat": (f"0 Minifig Clip\n1 16 0 0 0 {_IDENTITY} clip5.dat\n"),
        "parts/inline.dat": (
            "0 Bar with Inline Metadata\n"
            "0 !LDCAD SNAP_CLEAR\n"
            "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 20] "
            "[center=true] [slide=true] [id=inline-bar]\n"
            "2 24 -4 -10 -4 4 10 4\n"
        ),
        "parts/emptyclear.dat": (
            "0 Explicitly Connector-Free Part\n"
            "0 !LDCAD SNAP_CLEAR\n"
            "2 24 -10 0 -10 10 4 10\n"
        ),
        "parts/wrappedinline.dat": (
            "0 Inline Metadata Referenced Twice\n"
            f"1 16 -10 0 0 {_IDENTITY} inline.dat\n"
            f"1 16 10 0 0 {_IDENTITY} inline.dat\n"
        ),
        "parts/scaledinline.dat": (
            "0 Inline Metadata Under Invalid Inheritance Scale\n"
            "1 16 0 0 0 1 0 0 0 2 0 0 0 1 inline.dat\n"
        ),
        "parts/beam.dat": (
            "0 Technic Brick with Pin Hole\n"
            f"1 16 0 0 0 {_IDENTITY} peghole.dat\n"
            f"1 16 0 20 0 {_ROTATE_X_180} peghole.dat\n"
        ),
        "parts/nbeam.dat": (
            "0 Technic Brick with Negative Pin Hole\n"
            f"1 16 0 0 0 {_IDENTITY} npeghol.dat\n"
            f"1 16 0 20 0 {_ROTATE_X_180} npeghol.dat\n"
        ),
        "parts/pin.dat": (f"0 Technic Pin\n1 16 0 20 0 {_IDENTITY} connect2.dat\n"),
        "parts/axle.dat": (f"0 Technic Axle 2\n1 16 0 0 0 {_IDENTITY} axlehol8.dat\n"),
        "parts/axlehole.dat": (
            "0 Technic Brick with Axle Hole\n"
            f"1 16 0 0 0 {_IDENTITY} axlehol8.dat\n"
            f"1 16 0 20 0 {_ROTATE_X_180} axlehol8.dat\n"
        ),
        "parts/hinge1.dat": (
            f"0 Hinge Click Finger\n1 16 0 0 0 {_IDENTITY} clh4.dat\n"
        ),
        "parts/hinge2.dat": (
            f"0 Hinge Click Finger Mate\n1 16 0 0 0 {_IDENTITY} clh1.dat\n"
        ),
        "parts/hingepair.dat": (
            "0 Hinge Click Dual Finger Pair\n"
            f"1 16 -5.75 0 0 {_IDENTITY} clh4.dat\n"
            f"1 16 5.75 0 0 {_IDENTITY} clh4.dat\n"
        ),
        "parts/rim.dat": ("0 Wheel Rim 20 x 30\n2 24 -15 -5 -15 15 5 15\n"),
        "parts/tyre.dat": ("0 Tyre 20 x 30\n2 24 -18 -6 -18 18 6 18\n"),
        "parts/wheelc01.dat": (
            "0 Wheel Rim 20 x 30 with Tyre 20 x 30\n"
            f"1 16 0 0 0 {_IDENTITY} rim.dat\n"
            f"1 16 0 0 0 {_IDENTITY} tyre.dat\n"
        ),
        "parts/3035.dat": (
            "0 Synthetic Scout Upper Plate\n"
            "2 24 -80 0 -6 80 4 6\n"
            + "".join(
                f"1 16 {x} 0 {z} {_IDENTITY} stud.dat\n"
                for x in (-70, -50, -30, -10, 10, 30, 50, 70)
                for z in (-4, 4)
            )
        ),
        "parts/3958.dat": (
            "0 Synthetic Scout Receptacle Plate\n"
            f"2 24 -6 0 -40 6 4 40\n{scout_receptacles}"
        ),
        "parts/studmeta.dat": (
            "0 Plate with One Stud and Inline Metadata\n"
            "2 24 -10 0 -10 10 4 10\n"
            f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
            "0 !LDCAD SNAP_CYL [gender=M] [caps=one] [secs=R 6 4] "
            "[pos=0 0 0] [id=meta-stud]\n"
        ),
        "parts/precedence.dat": (
            "0 Precedence Test Cylinder\n"
            "0 !LDCAD SNAP_CYL [gender=M] [center=true] [slide=true] "
            "[secs=R 4 20] [pos=0 -5 0] [id=Cross-Bar]\n"
            "2 24 -4 -10 -4 4 10 4\n"
        ),
        "parts/deckplate.dat": ("0 Studio Precedence Plate\n2 24 -10 0 -10 10 4 10\n"),
        "parts/dualrecept.dat": (
            "0 Dual Receptacle Strip\n"
            "2 24 -6 0 -40 6 4 40\n"
            f"1 16 0 0 -20 {_ROTATE_X_180} stud4.dat\n"
            f"1 16 0 0 20 {_ROTATE_X_180} stud4.dat\n"
        ),
        "parts/coincidentopen.dat": (
            "0 Coincident Open Tube Fixture\n"
            "2 24 -6 0 10 6 4 30\n"
            f"1 16 0 0 20 {_ROTATE_X_180} stud4.dat\n"
            f"1 16 0 0 20 {_ROTATE_X_180} stud4.dat\n"
        ),
        "parts/coincidentsolid.dat": (
            "0 Coincident Solid Tube Fixture\n"
            "2 24 -20 0 -10 20 8 10\n"
            f"1 16 -10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
        ),
        "parts/longopen.dat": (
            "0 Long Open Tube Name Fixture\n"
            "2 24 -10 0 -10 10 8 10\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud4f4s.dat\n"
        ),
        "parts/narrowsolid.dat": (
            "0 Bounds-Rejected Solid Tube Fixture\n"
            "2 24 -5 0 -5 5 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
        ),
        "parts/nestedsolid.dat": (
            "0 Assembly Expanding a Narrow Solid Tube\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        "parts/narrowsolidmeta.dat": (
            "0 Bounds-Rejected Solid Tube with Metadata\n"
            "2 24 -5 0 -5 5 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
            "0 !LDCAD SNAP_CYL [id=explicit-socket] [gender=F] "
            "[secs=R 6 4] [pos=0 8 0]\n"
        ),
        "parts/nestedsolidmeta.dat": (
            "0 Assembly Containing a Metadata-Resolved Solid Tube\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} narrowsolidmeta.dat\n"
        ),
        "parts/narrowsolidlateralmeta.dat": (
            "0 Bounds-Rejected Solid Tube with Lateral Metadata\n"
            "2 24 -5 0 -5 5 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
            "0 !LDCAD SNAP_CYL [id=explicit-lateral] [gender=F] "
            "[secs=R 6 4] [pos=10 8 0]\n"
        ),
        "parts/nestedsolidlateralmeta.dat": (
            "0 Assembly Containing a Laterally Resolved Solid Tube\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} narrowsolidlateralmeta.dat\n"
        ),
        "parts/partialsolid.dat": (
            "0 Partially Bounds-Matched Solid Tube\n"
            "2 24 -15 0 -5 15 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
        ),
        "parts/scaledpartialsolid.dat": (
            "0 Scaled Assembly Containing Partial Solid Tube Evidence\n"
            "2 24 -40 0 -40 40 8 40\n"
            f"1 16 0 0 0 {_SCALE_XZ_2} partialsolid.dat\n"
        ),
        "parts/partialsolidlateralmeta.dat": (
            "0 Partially Bounds-Matched Solid Tube with Lateral Metadata\n"
            "2 24 -15 0 -5 15 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
            "0 !LDCAD SNAP_CYL [id=explicit-partial-lateral] [gender=F] "
            "[secs=R 6 4] [pos=10 8 0]\n"
        ),
        "parts/nestedpartialsolidlateralmeta.dat": (
            "0 Assembly Containing a Partially Resolved Solid Tube\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} partialsolidlateralmeta.dat\n"
        ),
        "parts/parentlateralmeta.dat": (
            "0 Parent Metadata Isolated from Child Tube Evidence\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} partialsolid.dat\n"
            "0 !LDCAD SNAP_CYL [id=parent-lateral] [gender=F] "
            "[secs=R 6 4] [pos=0 8 10]\n"
        ),
        # The valid child sits far enough away that none of its sockets land
        # on the singular child's collapse point, so a phantom socket there
        # cannot hide behind a real one during deduplication.
        "parts/singularevidence.dat": (
            "0 Assembly with Singular and Valid Deferred Tube Evidence\n"
            "2 24 -20 0 -20 60 8 20\n"
            f"1 16 0 0 0 {_SINGULAR_XZ} narrowsolid.dat\n"
            f"1 16 40 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        # Every grid fixture below shares one layout: an on-grid stud pair
        # whose phases admit the four sockets of a valid sibling at x=40, plus
        # a degenerately placed child at the origin. The sibling is the
        # positive control — a regression that silences socket derivation
        # outright fails these tests instead of passing them.
        "parts/singulargridevidence.dat": (
            "0 Assembly with a Stud Grid and a Singular Child\n"
            "2 24 -20 0 -20 60 8 20\n"
            f"{_GRID_STUD_PAIR}"
            f"1 16 0 0 0 {_SINGULAR_XZ} narrowplaceholder.dat\n"
            f"1 16 40 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        "parts/collineargridevidence.dat": (
            "0 Assembly with a Stud Grid and Collinear Child Axes\n"
            "2 24 -20 0 -20 60 8 20\n"
            f"{_GRID_STUD_PAIR}"
            f"1 16 0 0 0 {_SINGULAR_COLLINEAR_XZ} narrowplaceholder.dat\n"
            f"1 16 40 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        "parts/shrunkengridevidence.dat": (
            "0 Assembly with a Stud Grid and a Uniformly Shrunken Child\n"
            "2 24 -20 0 -20 60 8 20\n"
            f"{_GRID_STUD_PAIR}"
            f"1 16 0 0 0 {_SHRUNKEN_XZ} narrowplaceholder.dat\n"
            f"1 16 40 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        "parts/mirroredchild.dat": (
            "0 Assembly Mirroring a Solid Tube Child\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_MIRROR_X} narrowsolid.dat\n"
        ),
        "parts/collapsedaxistube.dat": (
            "0 Solid Tube whose Placement Collapses its Axis\n"
            "2 24 -30 -30 -30 30 30 30\n"
            f"1 16 0 8 0 {_SINGULAR_Y} stud3.dat\n"
        ),
        "parts/collapsedopentube.dat": (
            "0 Open Tube whose Placement Collapses its Grid\n"
            "2 24 -30 -30 -30 30 30 30\n"
            f"1 16 0 8 0 {_SINGULAR_XZ} stud4.dat\n"
        ),
        "parts/placeholderseed.dat": (
            "0 Solid Tube Sharing a Cell with a Placeholder Receptacle\n"
            "2 24 -15 0 -15 15 8 15\n"
            # Matching axes are required to exercise socket suppression;
            # opposing socket axes are intentionally treated as distinct.
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
            f"1 16 10 8 0 {_ROTATE_X_180} studundersideplaceholder.dat\n"
        ),
        "parts/narrowplaceholder.dat": (
            "0 Bounds-Rejected Placeholder Solid Tube Fixture\n"
            "2 24 -5 0 -5 5 8 5\n"
            f"1 16 0 4 0 {_ROTATE_X_180} studplaceholder.dat\n"
        ),
        "parts/nestedplaceholder.dat": (
            "0 Assembly Expanding Placeholder Tube Evidence\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} narrowplaceholder.dat\n"
        ),
        "parts/s/middlesolid.dat": (
            "0 Non-Catalog Intermediate with Deferred Solid Tube\n"
            f"1 16 0 0 0 {_IDENTITY} narrowsolid.dat\n"
        ),
        "parts/nestedmiddlesolid.dat": (
            "0 Assembly Containing a Non-Catalog Tube Intermediate\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} s/middlesolid.dat\n"
        ),
        "parts/partialphase.dat": (
            "0 Partially Grid-Matched Solid Tube\n"
            "2 24 -15 0 -15 15 8 15\n"
            f"1 16 -10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud3.dat\n"
        ),
        "parts/parentphase.dat": (
            "0 Assembly Completing a Child Stud Grid\n"
            "2 24 -20 0 -20 20 8 20\n"
            f"1 16 0 0 0 {_IDENTITY} partialphase.dat\n"
            f"1 16 0 0 -10 {_IDENTITY} stud.dat\n"
            f"1 16 0 0 10 {_IDENTITY} stud.dat\n"
        ),
        "parts/openorderab.dat": (
            "0 Open Tubes Ordered Corner then Centre\n"
            "2 24 -30 0 -30 30 8 30\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud4.dat\n"
            f"1 16 10 4 10 {_ROTATE_X_180} stud4.dat\n"
        ),
        "parts/openorderba.dat": (
            "0 Open Tubes Ordered Centre then Corner\n"
            "2 24 -30 0 -30 30 8 30\n"
            f"1 16 10 4 10 {_ROTATE_X_180} stud4.dat\n"
            f"1 16 0 4 0 {_ROTATE_X_180} stud4.dat\n"
        ),
        "parts/protrudingplate.dat": (
            "0 Plate with Unrelated Underside Protrusion\n"
            "2 24 -20 0 -10 20 24 10\n"
            "2 24 15 24 0 15 60 0\n"
            f"1 16 -10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 10 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 0 4 0 {_ROTATE_X_180_SCALE_Y_5} stud3.dat\n"
        ),
        "parts/onestud.dat": (
            "0 Single Stud Plate\n"
            "2 24 -10 0 -10 10 4 10\n"
            f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
        ),
        "parts/gridbrick.dat": (
            "0 Synthetic Brick 2 x 4\n"
            "2 24 -40 0 -20 40 24 20\n"
            + "".join(
                f"1 16 {x} 0 {z} {_IDENTITY} stud.dat\n"
                for x in (-30, -10, 10, 30)
                for z in (-10, 10)
            )
            + "".join(
                f"1 16 {x} 4 0 {_ROTATE_X_180_SCALE_Y_5} stud4.dat\n"
                for x in (-20, 0, 20)
            )
        ),
        "parts/gridstrip.dat": (
            "0 Synthetic Plate 1 x 4\n"
            "2 24 -40 0 -10 40 8 10\n"
            + "".join(
                f"1 16 {x} 0 0 {_IDENTITY} stud.dat\n" for x in (-30, -10, 10, 30)
            )
            + "".join(f"1 16 {x} 4 0 {_ROTATE_X_180} stud3.dat\n" for x in (-20, 0, 20))
        ),
        "parts/twostrips.dat": (
            "0 Two Coincident Synthetic Plates\n"
            f"1 16 0 0 0 {_IDENTITY} gridstrip.dat\n"
            f"1 16 0 0 0 {_IDENTITY} gridstrip.dat\n"
        ),
    }
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / "parts.lst").write_text(
        "bar1.dat Bar 3L\n"
        "blank.dat Blank Tile\n"
        "clipper.dat Minifig Clip\n"
        "inline.dat Bar with Inline Metadata\n"
        "emptyclear.dat Explicitly Connector-Free Part\n"
        "wrappedinline.dat Inline Metadata Referenced Twice\n"
        "scaledinline.dat Inline Metadata Under Invalid Inheritance Scale\n"
        "beam.dat Technic Brick with Pin Hole\n"
        "nbeam.dat Technic Brick with Negative Pin Hole\n"
        "pin.dat Technic Pin\n"
        "axle.dat Technic Axle 2\n"
        "axlehole.dat Technic Brick with Axle Hole\n"
        "hinge1.dat Hinge Click Finger\n"
        "hinge2.dat Hinge Click Finger Mate\n"
        "hingepair.dat Hinge Click Dual Finger Pair\n"
        "rim.dat Wheel Rim 20 x 30\n"
        "tyre.dat Tyre 20 x 30\n"
        "wheelc01.dat Wheel Rim 20 x 30 with Tyre 20 x 30\n"
        "3035.dat Synthetic Scout Upper Plate\n"
        "3958.dat Synthetic Scout Receptacle Plate\n"
        "studmeta.dat Plate with One Stud and Inline Metadata\n"
        "precedence.dat Precedence Test Cylinder\n"
        "deckplate.dat Studio Precedence Plate\n"
        "dualrecept.dat Dual Receptacle Strip\n"
        "coincidentopen.dat Coincident Open Tube Fixture\n"
        "coincidentsolid.dat Coincident Solid Tube Fixture\n"
        "longopen.dat Long Open Tube Name Fixture\n"
        "narrowsolid.dat Bounds-Rejected Solid Tube Fixture\n"
        "nestedsolid.dat Assembly Expanding a Narrow Solid Tube\n"
        "narrowsolidmeta.dat Bounds-Rejected Solid Tube with Metadata\n"
        "nestedsolidmeta.dat Assembly Containing a Metadata-Resolved Solid Tube\n"
        "narrowsolidlateralmeta.dat Bounds-Rejected Solid Tube with Lateral Metadata\n"
        "nestedsolidlateralmeta.dat "
        "Assembly Containing a Laterally Resolved Solid Tube\n"
        "partialsolid.dat Partially Bounds-Matched Solid Tube\n"
        "scaledpartialsolid.dat "
        "Scaled Assembly Containing Partial Solid Tube Evidence\n"
        "partialsolidlateralmeta.dat "
        "Partially Bounds-Matched Solid Tube with Lateral Metadata\n"
        "nestedpartialsolidlateralmeta.dat "
        "Assembly Containing a Partially Resolved Solid Tube\n"
        "parentlateralmeta.dat Parent Metadata Isolated from Child Tube Evidence\n"
        "singularevidence.dat Assembly with Singular and Valid Deferred Tube Evidence\n"
        "singulargridevidence.dat Assembly with a Stud Grid and a Singular Child\n"
        "collineargridevidence.dat Assembly with a Stud Grid and Collinear Child Axes\n"
        "shrunkengridevidence.dat "
        "Assembly with a Stud Grid and a Uniformly Shrunken Child\n"
        "mirroredchild.dat Assembly Mirroring a Solid Tube Child\n"
        "collapsedaxistube.dat Solid Tube whose Placement Collapses its Axis\n"
        "collapsedopentube.dat Open Tube whose Placement Collapses its Grid\n"
        "placeholderseed.dat Solid Tube Sharing a Cell with a Placeholder Receptacle\n"
        "narrowplaceholder.dat Bounds-Rejected Placeholder Solid Tube Fixture\n"
        "nestedplaceholder.dat Assembly Expanding Placeholder Tube Evidence\n"
        "nestedmiddlesolid.dat Assembly Containing a Non-Catalog Tube Intermediate\n"
        "partialphase.dat Partially Grid-Matched Solid Tube\n"
        "parentphase.dat Assembly Completing a Child Stud Grid\n"
        "openorderab.dat Open Tubes Ordered Corner then Centre\n"
        "openorderba.dat Open Tubes Ordered Centre then Corner\n"
        "protrudingplate.dat Plate with Unrelated Underside Protrusion\n"
        "onestud.dat Single Stud Plate\n"
        "gridbrick.dat Synthetic Brick 2 x 4\n"
        "gridstrip.dat Synthetic Plate 1 x 4\n"
        "twostrips.dat Two Coincident Synthetic Plates\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text(
        "clip5.dat Clip Primitive\n"
        "npeghol.dat Technic Pin Hole Negative End\n"
        "peghole.dat Technic Pin Hole End\n"
        "connect2.dat Technic Pin\n"
        "axlehol8.dat Technic Axle Hole End\n"
        "clh4.dat Click Lock Hinge Half Dual Finger\n"
        "clh1.dat Click Lock Hinge Single Finger for Bricks\n"
        "stud.dat Stud\n"
        "stud3.dat Stud Tube Solid\n"
        "stud4.dat Stud Tube Open\n"
        "studplaceholder.dat Stud Tube Solid Placeholder\n"
        "studundersideplaceholder.dat Stud Underside Placeholder\n"
        "stud4f4s.dat Stud Tube Open with 4 Fillets Standard\n",
        encoding="utf-8",
    )
    return Parts(root / "parts.lst")


def _one(parts: Parts, code: str, kind: ConnectionKind) -> ConnectionFeature:
    return next(feature for feature in parts.connections(code) if feature.kind is kind)


def test_infers_bar_clip_pin_hole_axle_and_hinge_semantics(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)

    bar = _one(parts, "bar1", ConnectionKind.BAR)
    clip = _one(parts, "clipper", ConnectionKind.CLIP)
    assert connections_compatible(bar, clip)
    assert bar.source is ConnectionSource.HEURISTIC
    assert clip.source is ConnectionSource.PRIMITIVE
    assert bar.connection_provenance is not None
    assert clip.connection_provenance is not None
    assert clip.freedoms == {
        ConnectionFreedom.ROTATE,
        ConnectionFreedom.SLIDE,
    }

    hole = _one(parts, "beam", ConnectionKind.PIN_HOLE)
    pin = _one(parts, "pin", ConnectionKind.PIN)
    assert hole.feature_id == "peghole@R0/peghole:through"
    assert hole.position == Vector(0, 10, 0)
    assert hole.length == pytest.approx(20)
    assert connections_compatible(pin, hole)

    axle = _one(parts, "axle", ConnectionKind.AXLE)
    axle_hole = _one(parts, "axlehole", ConnectionKind.AXLE_HOLE)
    assert isinstance(axle.profile, CylindricalProfile)
    assert isinstance(axle_hole.profile, CylindricalProfile)
    assert axle.profile.primary_shape is SectionShape.AXLE
    assert axle_hole.profile.primary_shape is SectionShape.AXLE
    assert axle.freedoms == {ConnectionFreedom.SLIDE}
    assert connections_compatible(axle, axle_hole)

    quarter_turned = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Identity().rotate(90, YAxis),
    )
    diagonally_turned = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Identity().rotate(45, YAxis),
    )
    assert connection_residual(
        quarter_turned, axle_hole
    ).roll_alignment == pytest.approx(1)
    assert connection_residual(
        diagonally_turned, axle_hole
    ).roll_alignment == pytest.approx(2**-0.5)
    assert snap_transform(quarter_turned, axle_hole).matrix.flatten() == pytest.approx(
        Identity().flatten(),
        abs=1e-12,
    )
    degenerate = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Matrix([[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
    )
    assert degenerate.confidence == 0
    assert degenerate.radial == Vector(0, 0, 0)
    assert not connections_compatible(degenerate, axle_hole)
    with pytest.raises(ValueError, match="radius tolerance"):
        connections_compatible(axle, axle_hole, radius_tolerance=-1)

    first_hinge = _one(parts, "hinge1", ConnectionKind.HINGE)
    second_hinge = _one(parts, "hinge2", ConnectionKind.HINGE)
    assert isinstance(first_hinge.profile, FingerProfile)
    assert first_hinge.profile.detents == tuple(index * 22.5 for index in range(9))
    assert first_hinge.freedoms == {ConnectionFreedom.DISCRETE_ROTATE}
    assert connections_compatible(first_hinge, second_hinge)
    assert not connections_compatible(first_hinge, first_hinge)
    hinge_pair = tuple(
        feature
        for feature in parts.connections("hingepair")
        if feature.kind is ConnectionKind.HINGE
    )
    assert len(hinge_pair) == 1
    assert hinge_pair[0].feature_id == "clh4@R0/clh4:complete"


def test_derives_tyre_rim_pairs_and_marks_complete_shortcut_occupied(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    assert parts.compatible_tyres("rim") == ("tyre",)
    assert parts.compatible_rims("tyre") == ("rim",)
    relation = parts.tyre_rim_compatibility[0]
    assert (relation.first, relation.second, relation.evidence) == (
        "rim",
        "tyre",
        "wheelc01",
    )

    rim = _one(parts, "rim", ConnectionKind.RIM_SEAT)
    tyre = _one(parts, "tyre", ConnectionKind.TYRE_BEAD)
    assert rim.compatible_parts == ("tyre",)
    assert tyre.compatible_parts == ("rim",)
    assert connections_compatible(rim, tyre)

    assembly = parts.connections("wheelc01")
    fitted = tuple(
        feature
        for feature in assembly
        if feature.kind in {ConnectionKind.RIM_SEAT, ConnectionKind.TYRE_BEAD}
    )
    assert len(fitted) == 2
    assert all(feature.occupied for feature in fitted)
    assert {feature.occupied_by for feature in fitted} == {"wheelc01"}
    assert not connections_compatible(fitted[0], fitted[1])


def test_shadow_metadata_can_clear_include_grid_and_supersede_inference(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    shadow = tmp_path / "shadow"
    (shadow / "parts").mkdir(parents=True)
    (shadow / "p").mkdir()
    (shadow / "parts" / "bar1.dat").write_text(
        "0 !LDCAD SNAP_CLEAR\n"
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 60] "
        "[center=true] [slide=true] [id=main]\n",
        encoding="utf-8",
    )
    (shadow / "p" / "common.dat").write_text(
        "0 !LDCAD SNAP_GEN [gender=F] [group=test] [id=socket]\n",
        encoding="utf-8",
    )
    (shadow / "parts" / "clipper.dat").write_text(
        "0 !LDCAD SNAP_CLEAR\n"
        "0 !LDCAD SNAP_INCL [ref=common.dat] [grid=C 2 C 1 20 0]\n",
        encoding="utf-8",
    )

    assert _one(parts, "bar1", ConnectionKind.BAR).source is ConnectionSource.HEURISTIC
    parts.add_connection_shadow(shadow)

    bar_connections = parts.connections("bar1")
    assert len(bar_connections) == 1
    assert bar_connections[0].feature_id == "main"
    assert bar_connections[0].source is ConnectionSource.LDCAD_SHADOW
    included = parts.connections("clipper")
    assert len(included) == 2
    assert {feature.position.x for feature in included} == {-10, 10}
    assert all(feature.owner_code == "clipper" for feature in included)

    direct = LDCadShadowLibrary(shadow).connections_for("bar1")
    assert direct.clear_all is True
    assert direct.diagnostics == ()


def test_inline_ldcad_metadata_is_consumed_without_a_shadow_library(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    connections = parts.connections("inline")

    assert len(connections) == 1
    assert connections[0].feature_id == "inline-bar"
    assert connections[0].kind is ConnectionKind.BAR
    assert connections[0].source is ConnectionSource.LDCAD_INLINE
    assert connections[0].position == Vector(0, 0, 0)

    assert parts.connection_metadata("inline").coverage is (
        ConnectionMetadataCoverage.COMPLETE
    )
    assert parts.connection_metadata("bar1").coverage is (
        ConnectionMetadataCoverage.PARTIAL
    )
    assert (
        parts.connection_metadata("blank").coverage is ConnectionMetadataCoverage.NONE
    )
    cleared = parts.connection_metadata("emptyclear")
    assert cleared.coverage is ConnectionMetadataCoverage.COMPLETE
    assert cleared.features == ()


def test_metadata_part_code_follows_each_requested_spelling(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)
    # Prime the shared local-geometry cache under a different spelling.
    parts.bounding_box("INLINE")

    first = parts.connection_metadata("inline")
    second = parts.connection_metadata("INLINE")
    geometry = parts.geometry("Inline")

    assert first.part_code == "inline"
    assert second.part_code == "INLINE"
    assert geometry.connection_metadata is not None
    assert geometry.connection_metadata.part_code == geometry.code


def test_inline_metadata_supersedes_colocated_primitive_without_snap_clear(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    connections = parts.connections("studmeta")

    assert len(connections) == 1
    assert connections[0].kind is ConnectionKind.STUD
    assert connections[0].feature_id == "meta-stud"
    assert connections[0].source is ConnectionSource.LDCAD_INLINE
    assert connections[0].position == Vector(0, 0, 0)
    assert not any(
        diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
        for diagnostic in parts.connection_metadata("studmeta").diagnostics
    )


def test_shadow_replaces_inline_feature_by_case_insensitive_id(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    shadow = tmp_path / "shadow"
    (shadow / "parts").mkdir(parents=True)
    (shadow / "parts" / "precedence.dat").write_text(
        "0 !LDCAD SNAP_CYL [gender=M] [center=true] [slide=true] "
        "[secs=R 4 20] [pos=0 5 0] [id=cross-bar]\n",
        encoding="utf-8",
    )
    before = parts.connections("precedence")
    assert [
        (feature.feature_id, feature.source, feature.position) for feature in before
    ] == [("Cross-Bar", ConnectionSource.LDCAD_INLINE, Vector(0, -5, 0))]

    parts.add_connection_shadow(shadow)

    after = parts.connections("precedence")
    assert [
        (feature.feature_id, feature.source, feature.position) for feature in after
    ] == [("cross-bar", ConnectionSource.LDCAD_SHADOW, Vector(0, 5, 0))]
    conflict = next(
        diagnostic
        for diagnostic in parts.connection_metadata("precedence").diagnostics
        if diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
    )
    assert "'cross-bar'" in conflict.message


def test_studio_metadata_replaces_shadow_feature_with_same_id(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    shadow = tmp_path / "shadow"
    (shadow / "parts").mkdir(parents=True)
    (shadow / "parts" / "deckplate.dat").write_text(
        "0 !LDCAD SNAP_CYL [gender=M] [center=true] [slide=true] "
        "[secs=R 4 20] [pos=0 -6 0] [id=deck]\n",
        encoding="utf-8",
    )
    studio_path = tmp_path / "studio.json"
    studio_path.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": "deckplate.dat",
                        "connections": [
                            {
                                "id": "deck",
                                "type": "bar",
                                "gender": "male",
                                "position": [0, 6, 0],
                                "axis": [0, 1, 0],
                                "radius": 4,
                                "length": 20,
                            },
                        ],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    parts.add_connection_shadow(shadow)
    shadowed = parts.connections("deckplate")
    assert [
        (feature.feature_id, feature.source, feature.position) for feature in shadowed
    ] == [("deck", ConnectionSource.LDCAD_SHADOW, Vector(0, -6, 0))]

    parts.add_studio_metadata(studio_path)

    final = parts.connections("deckplate")
    assert [
        (feature.feature_id, feature.source, feature.position) for feature in final
    ] == [("deck", ConnectionSource.STUDIO, Vector(0, 6, 0))]
    conflict = next(
        diagnostic
        for diagnostic in parts.connection_metadata("deckplate").diagnostics
        if diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
    )
    assert str(studio_path) in conflict.message


def test_inherited_metadata_counts_each_document_once_and_rejects_bad_scale(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    inherited = parts.connection_metadata("wrappedinline")
    assert inherited.coverage is ConnectionMetadataCoverage.COMPLETE
    assert inherited.source_count == 1
    assert inherited.recognized_record_count == 2
    assert len(inherited.features) == 2

    scaled = parts.connection_metadata("scaledinline")
    assert scaled.coverage is ConnectionMetadataCoverage.PARTIAL
    assert scaled.source_count == 1
    assert scaled.recognized_record_count == 2
    assert scaled.invalid_record_count == 1
    assert not scaled.features
    assert scaled.diagnostics[-1].code is DiagnosticCode.CONNECTION_INVALID_TRANSFORM


def test_tokenizer_recovers_with_stable_counts_and_repeated_ids() -> None:
    result = parse_ldcad_commands(
        "synthetic",
        (
            "SNAP_CYL [id=repeat] [gender=M] [secs=R 4 8]",
            "SNAP_CYL [id=repeat] [gender=M] [secs=R 4 8]",
            "SNAP_CYL [gender=M] [secs=R 4 8] [grid=C 2 C 2 20 20]",
            "SNAP_CYL [gender=M] [secs=R nan 8]",
            "SNAP_CYL [gender=M] [secs=R 4 8] [grid=0 1 20 0]",
            "SNAP_CYL [gender=M] [secs=R 4 8] [mystery=true]",
            "SNAP_CYL [gender=M] [gender=F] [secs=R 4 8]",
            "SNAP_SPH [gender=M]",
        ),
    )

    repeated = tuple(
        feature for feature in result.features if feature.metadata_id == "repeat"
    )
    assert [feature.feature_id for feature in repeated] == [
        "repeat@L1:I0",
        "repeat@L2:I0",
    ]
    assert len(result.features) == 7
    assert result.recognized_record_count == 4
    assert result.unsupported_record_count == 2
    assert result.invalid_record_count == 3
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        DiagnosticCode.CONNECTION_INVALID_GRID,
        DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
        DiagnosticCode.CONNECTION_UNSUPPORTED_RECORD,
    }


def test_studio_metadata_has_documented_precedence_and_excludes_physics(
    tmp_path: Path,
) -> None:
    studio_path = tmp_path / "studio.json"
    studio_path.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": "inline.dat",
                        "connections": [
                            {
                                "id": "inline-bar",
                                "type": "bar",
                                "gender": "male",
                                "position": [1, 2, 3],
                                "axis": [0, 1, 0],
                                "radius": 4,
                                "length": 20,
                            },
                        ],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    parts = _connection_parts(tmp_path)
    parts.add_studio_metadata(studio_path)

    report = parts.connection_metadata("inline")
    assert report.coverage is ConnectionMetadataCoverage.COMPLETE
    assert report.source_count == 2
    assert report.features[0].source is ConnectionSource.STUDIO
    assert report.features[0].position == Vector(1, 2, 3)
    assert report.features[0].metadata_id == "inline-bar"
    assert report.features[0].connection_provenance is not None
    conflict = next(
        diagnostic
        for diagnostic in report.diagnostics
        if diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
    )
    assert str(studio_path) in conflict.message
    assert "inline.dat" in conflict.message

    excluded_path = tmp_path / "studio-physical.json"
    excluded_path.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": "bar1",
                        "mass_g": 2.5,
                        "connections": [
                            {
                                "id": "studio-bar",
                                "type": "bar",
                                "gender": "male",
                                "position": [0, 0, 0],
                                "axis": [0, 1, 0],
                                "capacity": 2,
                            },
                        ],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    library_result = StudioConnectionLibrary(excluded_path).connections_for("bar1")
    assert len(library_result.features) == 1
    assert library_result.unsupported_record_count == 2
    assert all(
        diagnostic.code is DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION
        for diagnostic in library_result.diagnostics
    )


def test_overrides_are_authoritative_and_invalidate_cached_geometry(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    override = ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=ConnectionRole.FEMALE,
        position=Vector(1, 2, 3),
        frame=Identity(),
        profile=GenericProfile("custom"),
        group="custom",
    )

    assert _one(parts, "bar1", ConnectionKind.BAR)
    parts.set_connection_overrides("bar1", (override,), replace_existing=True)

    connections = parts.connections("bar1")
    assert len(connections) == 1
    assert connections[0].source is ConnectionSource.OVERRIDE
    assert connections[0].owner_code == "bar1"
    assert connections[0].position == Vector(1, 2, 3)
    assert connections[0].connection_provenance is not None
    assert connections[0].connection_provenance.source is ConnectionSource.OVERRIDE
    assert parts.connection_metadata("bar1").coverage is (
        ConnectionMetadataCoverage.COMPLETE
    )

    parts.clear_connection_overrides("bar1")
    assert _one(parts, "bar1", ConnectionKind.BAR).source is ConnectionSource.HEURISTIC


def test_world_contacts_and_ranked_snap_candidates(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)
    aligned = parse_model(
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n1 16 0 30 0 {_IDENTITY} clipper.dat\n",
    )
    aligned_inspection = inspect_model(aligned, parts)

    contacts = aligned_inspection.connection_contacts()
    assert len(contacts) == 1
    assert {contacts[0].first.kind, contacts[0].second.kind} == {
        ConnectionKind.BAR,
        ConnectionKind.CLIP,
    }
    assert contacts[0].residual.distance == pytest.approx(0)
    assert contacts[0].status is ConnectionStatus.POTENTIAL
    graphs = aligned_inspection.connection_graphs()
    assert graphs.confirmed.edges == ()
    assert len(graphs.optimistic.edges) == 1

    separated = parse_model(
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n1 16 20 30 0 {_IDENTITY} clipper.dat\n",
    )
    inspection = inspect_model(separated, parts)
    assert inspection.connection_contacts() == ()

    candidates = inspection.snap_candidates(1, fixed=0)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.residual.distance == pytest.approx(20)
    assert candidate.transform.position == Vector(0, 30, 0)
    assert candidate.transform.matrix == Identity()

    by_object = inspection.snap_candidates(
        inspection.occurrences[1],
        fixed=inspection.occurrences[0],
    )
    assert len(by_object) == 1
    assert by_object[0].moving_occurrence.index == 1

    with pytest.raises(IndexError, match="no occurrence"):
        inspection.snap_candidates(99)
    with pytest.raises(ValueError, match="limit"):
        inspection.snap_candidates(1, limit=-1)
    with pytest.raises(ValueError, match="does not belong"):
        inspection.snap_candidates(aligned_inspection.occurrences[1])
    with pytest.raises(TypeError, match="OccurrenceGeometry or integer"):
        inspection.snap_candidates(cast("int", "1"))
    with pytest.raises(ValueError, match="tolerance"):
        inspection.connection_contacts(tolerance=-1)
    with pytest.raises(ValueError, match="angular_tolerance"):
        inspection.connection_contacts(angular_tolerance=-1)


def test_connection_contacts_skip_blank_and_far_apart_occurrences(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    model = parse_model(
        f"1 16 0 0 0 {_IDENTITY} blank.dat\n"
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n"
        f"1 16 2000 0 0 {_IDENTITY} clipper.dat\n",
    )

    inspection = inspect_model(model, parts)

    assert inspection.occurrences[0].connections == ()
    assert inspection.connection_contacts() == ()


def test_snap_transform_never_reflects_mirrored_feature_frames(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    mirror = Matrix([[-1, 0, 0], [0, 1, 0], [0, 0, 1]])

    axle = _one(parts, "axle", ConnectionKind.AXLE)
    axle_hole = _one(parts, "axlehole", ConnectionKind.AXLE_HOLE)
    mirrored_axle = axle.transformed(position=Vector(0, 0, 0), matrix=mirror)
    assert mirrored_axle.frame.det() == pytest.approx(-1)
    assert mirrored_axle.confidence == axle.confidence
    transform = snap_transform(mirrored_axle, axle_hole)
    assert transform.matrix.det() == pytest.approx(1)
    snapped = mirrored_axle.transformed(
        position=transform.position,
        matrix=transform.matrix,
    )
    assert snapped.position == axle_hole.position
    assert abs(snapped.axis.dot(axle_hole.axis)) == pytest.approx(1)

    bar = _one(parts, "bar1", ConnectionKind.BAR)
    clip = _one(parts, "clipper", ConnectionKind.CLIP)
    mirrored_bar = bar.transformed(position=Vector(0, 0, 0), matrix=mirror)
    assert snap_transform(mirrored_bar, clip).matrix.det() == pytest.approx(1)


def test_snap_transform_rejects_non_orthonormal_feature_frames() -> None:
    feature = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=R 4 8]"],
    ).features[0]
    invalid_frames = (
        Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]),
        Matrix([[1, 0.5, 0], [0, 1, 0], [0, 0, 1]]),
        Matrix([[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
    )

    for frame in invalid_frames:
        with pytest.raises(
            ValueError, match="moving feature frame must be orthonormal"
        ):
            snap_transform(replace(feature, frame=frame), feature)
        with pytest.raises(
            ValueError, match="target feature frame must be orthonormal"
        ):
            snap_transform(feature, replace(feature, frame=frame))


def test_negative_peghole_endpoints_merge_into_through_hole(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    hole = _one(parts, "nbeam", ConnectionKind.PIN_HOLE)

    assert hole.feature_id == "npeghol@R0/npeghol:through"
    assert hole.position == Vector(0, 10, 0)
    assert hole.length == pytest.approx(20)


def test_leading_flexible_section_is_reported_as_invalid() -> None:
    result = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=_L 4 8 A 6 20]"],
    )

    assert result.features == ()
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.code is DiagnosticCode.CONNECTION_METADATA_INVALID
    assert "adjacent rigid section" in diagnostic.message


def test_flexible_section_with_flexible_neighbour_is_reported_as_invalid() -> None:
    result = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=R 4 8 L_ 4 8 _L 4 8 R 4 8]"],
    )

    assert result.features == ()
    assert len(result.diagnostics) == 1
    assert "adjacent rigid section" in result.diagnostics[0].message


def test_inline_include_without_shadow_library_reports_diagnostic() -> None:
    result = parse_ldcad_commands("bar1", ["SNAP_INCL [ref=common.dat]"])

    assert result.features == ()
    assert len(result.diagnostics) == 1
    assert "SNAP_INCL" in result.diagnostics[0].message


def test_zip_shadow_library_resolves_nested_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "shadow.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "shadow/parts/bar1.dat",
            "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 60] [center=true] [id=main]\n",
        )

    library = LDCadShadowLibrary(archive_path)

    result = library.connections_for("bar1")
    assert [feature.feature_id for feature in result.features] == ["main"]
    assert result.features[0].source is ConnectionSource.LDCAD_SHADOW
    assert library.connections_for("missing").features == ()


def test_one_sided_tyre_rim_compatibility_adapters_are_preserved(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    rim = next(
        feature
        for feature in part_connections(_RimOnlyCompatibilityLibrary(parts), "rim")
        if feature.kind is ConnectionKind.RIM_SEAT
    )
    tyre = next(
        feature
        for feature in part_connections(_TyreOnlyCompatibilityLibrary(parts), "tyre")
        if feature.kind is ConnectionKind.TYRE_BEAD
    )

    assert rim.compatible_parts == ("tyre",)
    assert tyre.compatible_parts == ("rim",)
    assert rim.source is ConnectionSource.SHORTCUT
    assert tyre.source is ConnectionSource.SHORTCUT


def test_generic_features_mate_only_within_a_shared_group() -> None:
    left = ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=ConnectionRole.MALE,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=GenericProfile("towball"),
        group="towball",
    )
    right = replace(left, role=ConnectionRole.FEMALE)

    assert connections_compatible(left, right)
    assert not connections_compatible(left, replace(right, group="pantograph"))
    assert not connections_compatible(left, replace(right, group=None))


def test_scout_fixture_requires_ry90_and_receptacle_evidence(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    models = Path(__file__).parent / "models"

    broken = inspect_model(
        parse_model((models / "scout-connectivity-broken.ldr").read_text()),
        parts,
    )
    assert broken.connection_contacts() == ()
    assert broken.stud_contacts() == ()

    corrected = inspect_model(
        parse_model((models / "scout-connectivity-corrected.ldr").read_text()),
        parts,
    )
    contacts = corrected.connection_contacts()
    assert len(contacts) == 16
    assert {
        occurrence.index: sum(
            occurrence.index
            in {contact.first_occurrence.index, contact.second_occurrence.index}
            for contact in contacts
        )
        for occurrence in corrected.occurrences[1:]
    } == {1: 8, 2: 8}
    assert len(corrected.stud_contacts()) == 16
    graphs = corrected.connection_graphs()
    assert graphs.confirmed.nodes == (0, 1, 2)
    assert len(graphs.confirmed.edges) == 16
    assert graphs.optimistic.edges == graphs.confirmed.edges

    tiles = inspect_model(
        parse_model((models / "scout-overlapping-tiles.ldr").read_text()),
        parts,
    )
    assert len(tiles.occurrences) == 2
    for occurrence in tiles.occurrences:
        assert len(occurrence.connections) == 16
        assert {feature.kind for feature in occurrence.connections} == {
            ConnectionKind.STUD,
        }
    assert bounds_gap(
        tiles.occurrences[0].bounds,
        tiles.occurrences[1].bounds,
    ).intersects
    assert tiles.connection_contacts() == ()
    assert tiles.stud_contacts() == ()


@pytest.mark.parametrize(
    ("fixture_name", "receptacle_axis"),
    [
        ("scout-studs-sideways.ldr", Vector(-1, 0, 0)),
        ("scout-studs-averted.ldr", Vector(0, 1, 0)),
    ],
)
def test_strict_stud_contacts_require_entry_orientation_and_penetration(
    tmp_path: Path,
    fixture_name: str,
    receptacle_axis: Vector,
) -> None:
    parts = _connection_parts(tmp_path)
    models = Path(__file__).parent / "models"

    inspection = inspect_model(
        parse_model((models / fixture_name).read_text()),
        parts,
    )

    plate, receptacle = inspection.occurrences
    assert len(plate.connections) == 16
    assert {feature.kind for feature in plate.connections} == {ConnectionKind.STUD}
    # 8 open-tube centre sockets plus the 6 in-bounds derived corner sockets.
    assert len(receptacle.connections) == 14
    assert {feature.kind for feature in receptacle.connections} == {
        ConnectionKind.STUD_RECEPTACLE,
    }
    assert all(feature.axis == receptacle_axis for feature in receptacle.connections)
    assert bounds_gap(plate.bounds, receptacle.bounds).intersects
    assert inspection.connection_contacts() == ()
    assert inspection.stud_contacts() == ()


def test_stud_contacts_deduplicate_coincident_open_tubes(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    model = parse_model(
        f"1 16 0 0 20 {_IDENTITY} onestud.dat\n"
        f"1 16 0 -4 0 {_IDENTITY} coincidentopen.dat\n",
    )

    inspection = inspect_model(model, parts)

    receptacles = tuple(
        feature
        for feature in inspection.occurrences[1].connections
        if feature.kind is ConnectionKind.STUD_RECEPTACLE
    )
    assert len(receptacles) == 1
    assert {feature.feature_id for feature in receptacles} == {"stud4@R0/stud4"}
    assert {
        (feature.position.x, feature.position.y, feature.position.z)
        for feature in receptacles
    } == {(0, 0, 20)}
    assert all("derived:stud-socket" in feature.provenance for feature in receptacles)

    contacts = inspection.connection_contacts()
    assert len(contacts) == 1
    assert contacts[0].first.feature_id == "stud@R0/stud"
    assert contacts[0].second.feature_id == "stud4@R0/stud4"
    assert contacts[0].second.position == Vector(0, 0, 20)
    stud_contacts = inspection.stud_contacts()
    assert len(stud_contacts) == 1
    assert stud_contacts[0].receptacle_feature is not None
    assert stud_contacts[0].receptacle_feature.feature_id == "stud4@R0/stud4"


def test_stud_contacts_choose_lowest_ranked_valid_receptacle(
    tmp_path: Path,
) -> None:
    from ldraw.inspection import _best_strict_candidate

    parts = _connection_parts(tmp_path)
    stud = _one(parts, "onestud", ConnectionKind.STUD)
    socket = _one(parts, "longopen", ConnectionKind.STUD_RECEPTACLE)
    farther = replace(
        socket,
        position=Vector(0.4, 0, 0),
        feature_id="farther",
    )
    nearer = replace(
        socket,
        position=Vector(0.1, 0, 0),
        feature_id="nearer",
    )

    best = _best_strict_candidate(
        stud=stud,
        receptacles=(farther, nearer),
        tolerance=0.5,
        angular_tolerance=1.0,
    )

    assert best is not None
    receptacle, residual = best
    assert receptacle is nearer
    assert residual.distance == pytest.approx(0.1)


@pytest.mark.parametrize("code", ["openorderab", "openorderba"])
def test_derive_stud_sockets_prefer_named_open_tube_centres(
    tmp_path: Path,
    code: str,
) -> None:
    parts = _connection_parts(tmp_path)

    overlap = tuple(
        feature
        for feature in _connections_with_kind(
            parts=parts,
            code=code,
            kind=ConnectionKind.STUD_RECEPTACLE,
        )
        if feature.position == Vector(10, 8, 10)
    )

    assert len(overlap) == 1
    assert overlap[0].name == "Stud Tube Open"
    assert overlap[0].feature_id is not None
    assert ":socket:" not in overlap[0].feature_id


def test_derive_stud_sockets_expand_tubes_onto_the_mating_grid(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    brick = _connections_with_kind(
        parts=parts,
        code="gridbrick",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    assert len(brick) == 11
    assert all(feature.feature_id is not None for feature in brick)
    corners = tuple(
        feature for feature in brick if ":socket:" in (feature.feature_id or "")
    )
    centres = tuple(
        feature for feature in brick if ":socket:" not in (feature.feature_id or "")
    )
    assert len(corners) == 8
    assert _connection_positions(corners) == {
        (float(x), 24.0, float(z)) for x in (-30, -10, 10, 30) for z in (-10, 10)
    }
    assert len(centres) == 3
    assert _connection_positions(centres) == {
        (-20.0, 24.0, 0.0),
        (0.0, 24.0, 0.0),
        (20.0, 24.0, 0.0),
    }

    strip = _connections_with_kind(
        parts=parts,
        code="gridstrip",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    assert len(strip) == 4
    assert all(feature.name == "Stud Socket" for feature in strip)
    assert _connection_positions(strip) == {
        (-30.0, 8.0, 0.0),
        (-10.0, 8.0, 0.0),
        (10.0, 8.0, 0.0),
        (30.0, 8.0, 0.0),
    }


def test_derived_stud_socket_snap_transform_preserves_facing_axes(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    stud = _one(parts, "onestud", ConnectionKind.STUD)
    socket = next(
        feature
        for feature in _connections_with_kind(
            parts=parts,
            code="gridstrip",
            kind=ConnectionKind.STUD_RECEPTACLE,
        )
        if feature.position == Vector(30, 8, 0)
    )

    transform = snap_transform(socket, stud)

    assert socket.centered
    assert transform.matrix.flatten() == pytest.approx(Identity().flatten())
    assert transform.position == Vector(-30, -8, 0)
    assert connection_residual(stud, socket).axial_gap == pytest.approx(4)


def test_derive_stud_sockets_use_tube_span_and_preserve_header_name(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    protruding = _connections_with_kind(
        parts=parts,
        code="protrudingplate",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    assert len(protruding) == 2
    assert _connection_positions(protruding) == {
        (-10.0, 24.0, 0.0),
        (10.0, 24.0, 0.0),
    }
    assert all(feature.centered for feature in protruding)

    long_name = _connections_with_kind(
        parts=parts,
        code="longopen",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    assert len(long_name) == 1
    assert long_name[0].name == "Stud Tube Open with 4 Fillets Standard"
    assert long_name[0].position == Vector(0.0, 8.0, 0.0)
    assert long_name[0].centered
    assert "derived:stud-socket" in long_name[0].provenance


def test_derive_stud_sockets_drop_bounds_rejected_solid_tube_centre(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    assert not _connections_with_kind(
        parts=parts,
        code="narrowsolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )


def test_derive_stud_sockets_defer_rejected_catalog_tubes_through_metadata(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    nested = _connections_with_kind(
        parts=parts,
        code="nestedsolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(nested) == 4
    assert all(feature.name == "Stud Socket" for feature in nested)
    assert _connection_positions(nested) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }

    parts.set_connection_overrides(
        code="narrowsolid",
        features=(),
        replace_existing=True,
    )
    assert not _connections_with_kind(
        parts=parts,
        code="nestedsolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )


def test_derived_stud_sockets_preserve_child_metadata_when_nested(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    standalone = _connections_with_kind(
        parts=parts,
        code="narrowsolidmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    nested = _connections_with_kind(
        parts=parts,
        code="nestedsolidmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(standalone) == len(nested) == 1
    assert standalone[0].source is ConnectionSource.LDCAD_INLINE
    assert nested[0].source is ConnectionSource.LDCAD_INLINE
    assert standalone[0].position == nested[0].position == Vector(0, 8, 0)


def test_lateral_child_metadata_suppresses_all_deferred_tube_candidates(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    standalone = _connections_with_kind(
        parts=parts,
        code="narrowsolidlateralmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    nested = _connections_with_kind(
        parts=parts,
        code="nestedsolidlateralmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(standalone) == len(nested) == 1
    assert standalone[0].source is ConnectionSource.LDCAD_INLINE
    assert nested[0].source is ConnectionSource.LDCAD_INLINE
    assert standalone[0].position == nested[0].position == Vector(10, 8, 0)


def test_lateral_child_metadata_suppresses_visible_and_deferred_candidates(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    standalone = _connections_with_kind(
        parts=parts,
        code="partialsolidlateralmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    nested = _connections_with_kind(
        parts=parts,
        code="nestedpartialsolidlateralmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(standalone) == len(nested) == 1
    assert standalone[0].source is ConnectionSource.LDCAD_INLINE
    assert nested[0].source is ConnectionSource.LDCAD_INLINE
    assert standalone[0].position == nested[0].position == Vector(10, 8, 0)


def test_parent_metadata_does_not_resolve_child_owned_socket_evidence(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="parentlateralmeta",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 4
    assert _connection_positions(receptacles) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }
    assert (
        sum(feature.source is ConnectionSource.LDCAD_INLINE for feature in receptacles)
        == 1
    )


def test_degenerate_transform_cannot_poison_deferred_socket_evidence(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="singularevidence",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 4
    assert all(feature.confidence > 0 for feature in receptacles)
    # The singular child collapses its four candidates onto (0, 8, 0); no
    # socket may be emitted there, and every surviving one must trace back to
    # the validly placed sibling.
    assert _connection_positions(receptacles) == {
        (30.0, 8.0, 0.0),
        (40.0, 8.0, -10.0),
        (40.0, 8.0, 10.0),
        (50.0, 8.0, 0.0),
    }
    assert all(
        feature.feature_id is not None
        and feature.feature_id.startswith("narrowsolid@R1/")
        for feature in receptacles
    )


def test_override_features_are_rejected_under_a_degenerate_placement(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    parts.set_connection_overrides(
        code="narrowsolid",
        features=(
            ConnectionFeature(
                kind=ConnectionKind.STUD_RECEPTACLE,
                role=ConnectionRole.FEMALE,
                position=Vector(0, 8, 0),
                frame=Identity(),
                profile=CylindricalProfile(
                    sections=(CylindricalSection(SectionShape.ROUND, 6.0, 4.0),),
                ),
            ),
        ),
        replace_existing=True,
    )

    report = parts.connection_metadata("singularevidence")
    receptacles = tuple(
        feature
        for feature in report.features
        if feature.kind is ConnectionKind.STUD_RECEPTACLE
    )

    # Only the validly placed sibling keeps its override; the collapsed one is
    # reported rather than kept at a fabricated position.
    assert _connection_positions(receptacles) == {(40.0, 8.0, 0.0)}
    assert all(feature.source is ConnectionSource.OVERRIDE for feature in receptacles)
    assert any(
        diagnostic.code is DiagnosticCode.CONNECTION_INVALID_TRANSFORM
        for diagnostic in report.diagnostics
    )


def _sibling_socket_positions(offset: float) -> set[tuple[float, float, float]]:
    """Return the sockets a validly placed ``narrowsolid`` sibling derives."""
    return {
        (offset - 10.0, 8.0, 0.0),
        (offset, 8.0, -10.0),
        (offset, 8.0, 10.0),
        (offset + 10.0, 8.0, 0.0),
    }


def test_singular_child_cannot_pass_a_collapsed_stud_grid_phase(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="singulargridevidence",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # A collapsed placement leaves every grid phase at the origin, which would
    # match the equally collapsed stud phase and promote all four candidates.
    # Only the validly placed sibling's sockets may survive.
    assert _connection_positions(receptacles) == _sibling_socket_positions(40.0)


def test_collinear_child_cannot_pass_a_stud_grid_phase(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="collineargridevidence",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # Nonzero but collinear X/Z directions alias the two-dimensional grid onto
    # one line; matching phases on that line must not promote the candidates.
    # The validly placed sibling keeps its sockets, so this cannot pass by
    # silencing socket derivation altogether.
    assert _connection_positions(receptacles) == _sibling_socket_positions(40.0)


def test_uniformly_shrunken_child_cannot_pass_a_stud_grid_phase(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="shrunkengridevidence",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # The shrunken basis is nonzero and not collinear, so a magnitude-only
    # guard admits it; every dot product then rounds to zero and aliases the
    # candidate phases onto the stud phases exactly as a collapsed basis does.
    assert _connection_positions(receptacles) == _sibling_socket_positions(40.0)


def test_placement_collapsing_a_tube_axis_derives_no_socket(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="collapsedaxistube",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # The X and Z directions survive this placement, so only the axis reveals
    # the collapse. Sockets derived from it would carry a zero axis, which no
    # bounds check or deduplication pass can reason about.
    assert receptacles == ()


def test_placement_collapsing_an_open_tube_grid_drops_its_centre_socket(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="collapsedopentube",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # An open tube keeps its own centre socket through a bounds rejection, but
    # a rank-deficient frame leaves that socket no trustworthy roll either.
    assert receptacles == ()


def test_override_features_are_rejected_under_a_mirrored_placement(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    parts.set_connection_overrides(
        code="narrowsolid",
        features=(
            ConnectionFeature(
                kind=ConnectionKind.STUD_RECEPTACLE,
                role=ConnectionRole.FEMALE,
                position=Vector(10, 8, 0),
                frame=Identity(),
                profile=CylindricalProfile(
                    sections=(CylindricalSection(SectionShape.ROUND, 6.0, 4.0),),
                ),
                mirror_inheritance="none",
            ),
        ),
        replace_existing=True,
    )

    receptacles = _connections_with_kind(
        parts=parts,
        code="mirroredchild",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # A reflection is orthonormal and non-singular, so nothing about the
    # placement's rank rejects it; the override declines to inherit the mirror,
    # which must reject it exactly as it rejects an LDCad or Studio feature.
    assert receptacles == ()


def test_degraded_socket_evidence_reports_why_it_was_dropped(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    geometry = part_geometry(parts, "singularevidence")
    dropped = tuple(
        diagnostic
        for diagnostic in geometry.diagnostics
        if diagnostic.code is DiagnosticCode.CONNECTION_INVALID_TRANSFORM
    )

    # The singular child's four candidates are inferred, not authored, so the
    # authored-metadata rejection never covers them. Dropping them silently
    # would leave the missing sockets unexplainable from the report.
    assert len(dropped) == 4
    assert all(
        diagnostic.offending_value is not None
        and diagnostic.offending_value.startswith("stud3")
        for diagnostic in dropped
    )


def test_zero_confidence_receptacle_does_not_suppress_a_derived_socket(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="placeholderseed",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    # Asserting over every receptacle, not just the derived ones, is what
    # makes the placeholder's disappearance observable: it shares a cell and
    # an axis with the socket at (10, 8, 0), and nothing downstream removes a
    # colocated pair.
    assert _connection_positions(receptacles) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }
    assert all(feature.name == "Stud Socket" for feature in receptacles)
    assert all(feature.confidence > 0 for feature in receptacles)


def test_deferred_socket_evidence_preserves_born_zero_confidence(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="nestedplaceholder",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 4
    assert all(feature.confidence == 0 for feature in receptacles)
    assert _connection_positions(receptacles) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }


def test_deferred_socket_candidates_preserve_child_placement_scale(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="scaledpartialsolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 4
    assert _connection_positions(receptacles) == {
        (-20.0, 8.0, 0.0),
        (0.0, 8.0, -20.0),
        (0.0, 8.0, 20.0),
        (20.0, 8.0, 0.0),
    }


def test_non_catalog_intermediate_keeps_solid_tube_candidates_private(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    intermediate = _connections_with_kind(
        parts=parts,
        code="s/middlesolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    nested = _connections_with_kind(
        parts=parts,
        code="nestedmiddlesolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert intermediate == ()
    assert len(nested) == 4
    assert _connection_positions(nested) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }


def test_parent_grid_reconsiders_child_phase_rejections(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)

    child = _connections_with_kind(
        parts=parts,
        code="partialphase",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )
    parent = _connections_with_kind(
        parts=parts,
        code="parentphase",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(child) == 2
    assert _connection_positions(child) == {
        (-10.0, 8.0, 0.0),
        (10.0, 8.0, 0.0),
    }
    assert len(parent) == 4
    assert _connection_positions(parent) == {
        (-10.0, 8.0, 0.0),
        (0.0, 8.0, -10.0),
        (0.0, 8.0, 10.0),
        (10.0, 8.0, 0.0),
    }


def test_derive_stud_sockets_deduplicate_nested_derived_sockets(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="twostrips",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 4
    assert len(_connection_positions(receptacles)) == 4


def test_derive_stud_sockets_drop_deduplicated_solid_tube_centres(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    receptacles = _connections_with_kind(
        parts=parts,
        code="coincidentsolid",
        kind=ConnectionKind.STUD_RECEPTACLE,
    )

    assert len(receptacles) == 2
    assert all(feature.name == "Stud Socket" for feature in receptacles)
    assert _connection_positions(receptacles) == {
        (-10.0, 8.0, 0.0),
        (10.0, 8.0, 0.0),
    }


def test_strict_stud_contacts_confirm_a_plain_stack(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)
    model = parse_model(
        f"1 16 0 0 0 {_IDENTITY} gridbrick.dat\n"
        f"1 16 0 -24 0 {_IDENTITY} gridbrick.dat\n",
    )

    inspection = inspect_model(model, parts)

    contacts = inspection.connection_contacts()
    assert len(contacts) == 8
    assert {contact.status for contact in contacts} == {ConnectionStatus.CONFIRMED}
    assert all(contact.residual.distance == 0.0 for contact in contacts)
    assert len({id(contact.first) for contact in contacts}) == 8
    assert len(inspection.stud_contacts()) == 8


def test_spatial_hash_matches_exhaustive_contact_oracle(tmp_path: Path) -> None:
    from ldraw.inspection import _paired_contacts

    parts = _connection_parts(tmp_path)
    model_path = Path(__file__).parent / "models" / "scout-connectivity-corrected.ldr"
    inspection = inspect_model(parse_model(model_path.read_text()), parts)

    exhaustive = tuple(
        contact
        for first_index, first in enumerate(inspection.occurrences)
        for second in inspection.occurrences[first_index + 1 :]
        for contact in _paired_contacts(
            first,
            second,
            tolerance=0.25,
            angular_tolerance=2.0,
        )
    )
    indexed = inspection.connection_contacts()
    signature = lambda contact: (  # noqa: E731 - compact test projection
        contact.first_occurrence.index,
        contact.second_occurrence.index,
        contact.first.feature_id,
        contact.second.feature_id,
        contact.status,
        contact.residual,
    )

    assert tuple(map(signature, indexed)) == tuple(
        sorted(map(signature, exhaustive), key=lambda value: value[:4]),
    )
