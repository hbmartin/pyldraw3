"""Tests for Person minifigure limb transforms."""

import ldraw.figure as figure_mod
from ldraw.figure import Person
from ldraw.geometry import Identity, Vector, XAxis, ZAxis


def test_canonical_pose_limb_transforms() -> None:
    person = Person()
    head = person.head(14)
    torso = person.torso(4)
    hips = person.hips(1)
    left_arm = person.left_arm(4, 20)
    left_hand = person.left_hand(14)
    right_arm = person.right_arm(4, -20)
    right_hand = person.right_hand(14)
    left_leg = person.left_leg(1, 10)
    right_leg = person.right_leg(1)

    assert head.position == Vector(0, -24, 0)
    assert head.matrix == Identity()  # angle 0: no Y rotation
    assert head.part == figure_mod.Head
    assert torso.position == Vector(0, 0, 0)
    assert torso.part == figure_mod.Torso
    assert hips.position == Vector(0, 32, 0)
    assert hips.part == figure_mod.Hips

    assert left_arm.position == Vector(15, 8, 0)
    assert left_arm.matrix == Identity().rotate(-10, ZAxis) * Identity().rotate(
        20,
        XAxis,
    )
    assert left_hand is not None
    assert left_hand.position == left_arm.position + left_arm.matrix * Vector(4, 17, -9)
    assert left_hand.matrix == left_arm.matrix * Identity().rotate(40, XAxis)
    assert right_arm.position == Vector(-15, 8, 0)
    assert right_arm.matrix == Identity().rotate(10, ZAxis) * Identity().rotate(
        -20,
        XAxis,
    )
    assert right_hand is not None
    assert right_hand.position == right_arm.position + right_arm.matrix * Vector(
        -4,
        17,
        -9,
    )

    assert left_leg.position == Vector(0, 44, 0)
    assert left_leg.matrix == Identity().rotate(10, XAxis)
    assert left_leg.part == figure_mod.LegLeft
    assert right_leg.matrix == Identity()
    assert right_leg.part == figure_mod.LegRight


def test_dependent_pieces_require_their_anchor() -> None:
    person = Person()

    assert person.hat(0) is None
    assert person.left_hand(14) is None
    assert person.right_hand(14) is None
    assert person.left_shoe(0, part="2599") is None
    assert person.right_shoe(0, part="2599") is None


def test_posed_person_offsets_through_its_matrix() -> None:
    person = Person(Vector(10, 0, -5), Identity().rotate(30, ZAxis))

    head = person.head(14)

    assert head.position == Vector(10, 0, -5) + person.matrix * Vector(0, -24, 0)
