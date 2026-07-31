"""Tests for renderer-neutral, sectioned instruction semantics."""

from pathlib import Path

import pytest

from ldraw.geometry import Identity, Matrix, Vector
from ldraw.instructions import (
    CalloutMode,
    CameraContext,
    CameraState,
    DirectiveKind,
    InstructionBuilder,
    InstructionScope,
    InventoryTarget,
    RotationMode,
    iter_instruction_issues,
    parse_instruction_directive,
)
from ldraw.lines import Comment, MetaCommand
from ldraw.model import Model, parse_model
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.validation import Severity

TESTS_DIR = Path(__file__).resolve().parent
PARTS = Parts(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")


def _piece(
    reference: str = "3001.dat",
    *,
    colour: int = 4,
    x: int = 0,
) -> str:
    return f"1 {colour} {x} 0 0 1 0 0 0 1 0 0 0 1 {reference}"


def _matrix_values(matrix: Matrix) -> list[float]:
    return [value for row in matrix.rows for value in row]


def test_source_tracking_covers_every_object_without_changing_legacy_steps() -> None:
    model = parse_model(f"0 A note\n{_piece()}\n0 ROTSTEP 0 90 0\n0 STEP\n")
    semantic_step = model.instruction_document().root.steps[0]

    assert [model.source_line_for(obj) for obj in model.objects] == [1, 2, 3, 4]
    assert [len(step) for step in model.steps] == [1]
    assert model.source_line_for(Comment("A note")) is None
    assert semantic_step.cumulative_objects == tuple(model.objects[:3])
    assert semantic_step.source_line_for(semantic_step.added_pieces[0]) == 2


def test_document_is_root_first_then_reachable_mpd_order_with_orphans() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("b.ldr"),
                _piece("a.ldr", x=20),
                _piece("embedded.dat", x=40),
                "0 NOFILE",
                "0 FILE a.ldr",
                _piece(),
                "0 NOFILE",
                "0 FILE orphan.ldr",
                _piece(),
                "0 NOFILE",
                "0 FILE b.ldr",
                _piece(),
                "0 NOFILE",
                "0 FILE embedded.dat",
                "2 16 0 0 0 10 0 0",
                "0 NOFILE",
            )
        )
    )

    document = model.instruction_document(parts=PARTS)

    assert [section.name for section in document.sections] == [
        "main.ldr",
        "a.ldr",
        "b.ldr",
    ]
    assert document.root.is_root is True
    assert document.section("A.LDR").name == "a.ldr"
    assert [section.name for section in document.orphan_sections] == ["orphan.ldr"]
    with pytest.raises(KeyError, match="No reachable"):
        document.section("orphan.ldr")


def test_submodel_steps_are_independent_and_expansion_is_explicit() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("sub.ldr", colour=2, x=10),
                "0 STEP",
                _piece("sub.ldr", colour=3, x=30),
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(colour=16, x=5),
                "0 STEP",
                _piece(colour=1, x=15),
                "0 NOFILE",
            )
        ),
        source="nested.mpd",
    )
    document = model.instruction_document()
    root_steps = document.root.steps
    sub_steps = document.section("sub.ldr").steps

    assert [step.number for step in root_steps] == [1, 2]
    assert [step.number for step in sub_steps] == [1, 2]
    assert len(root_steps[0].added_occurrences(expand_submodels=False)) == 1
    expanded = root_steps[0].added_occurrences()
    assert len(expanded) == 2
    assert [item.position.x for item in expanded] == [15, 25]
    assert expanded[0].colour.code == 2
    assert expanded[0].source_model.name == "sub.ldr"
    assert expanded[0].source_line == 7
    assert len(root_steps[1].cumulative_occurrences()) == 4
    assert len(sub_steps[1].cumulative_occurrences()) == 2


def test_step_boundaries_include_geometry_stable_rotation_steps() -> None:
    model = parse_model(
        "\n".join(
            (
                _piece(),
                "0 STEP",
                "0 ROTSTEP 0 90 0",
                _piece(x=20),
                "0 ROTSTEP 90 0 0 ADD",
                "0 ROTSTEP 0 0 45 ABS",
                "0 ROTSTEP END",
            )
        )
    )
    steps = model.instruction_document().root.steps

    assert len(steps) == 5
    assert [len(step.added_pieces) for step in steps] == [1, 0, 1, 0, 0]
    assert [step.rotation.mode if step.rotation else None for step in steps] == [
        None,
        RotationMode.RELATIVE,
        RotationMode.ADDITIVE,
        RotationMode.ABSOLUTE,
        RotationMode.END,
    ]
    relative, additive, absolute, end = (
        step.rotation for step in steps[1:] if step.rotation is not None
    )
    assert _matrix_values(relative.effective_matrix) == pytest.approx(
        _matrix_values(relative.command_matrix)
    )
    assert _matrix_values(additive.effective_matrix) == pytest.approx(
        _matrix_values(relative.command_matrix * additive.command_matrix)
    )
    assert _matrix_values(absolute.effective_matrix) == pytest.approx(
        _matrix_values(absolute.command_matrix)
    )
    assert _matrix_values(end.effective_matrix) == pytest.approx(
        _matrix_values(Identity())
    )


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (Comment("step"), DirectiveKind.STEP),
        (Comment("rotstep 1 2 3 rel"), DirectiveKind.ROTATION_STEP),
        (Comment("LPUB CALLOUT BEGIN WHOLE"), DirectiveKind.CALLOUT_BEGIN),
        (MetaCommand("LPUB", "CALLOUT END"), DirectiveKind.CALLOUT_END),
        (MetaCommand("lpub", "MULTI_STEP BEGIN"), DirectiveKind.MULTI_STEP_BEGIN),
        (MetaCommand("LPUB", "PLI BEGIN IGN"), DirectiveKind.INVENTORY_IGNORE_BEGIN),
        (MetaCommand("LPUB", "BOM END"), DirectiveKind.INVENTORY_IGNORE_END),
        (MetaCommand("LPUB", "NOSTEP"), DirectiveKind.NO_STEP),
        (MetaCommand("LPUB", "PARSE_NOSTEP TRUE"), DirectiveKind.PARSE_NO_STEP),
        (MetaCommand("LPUB", "INSERT PAGE OFFSET 1 2"), DirectiveKind.PAGE_BREAK),
        (MetaCommand("LPUB", "ASSEM CAMERA_FOV 35"), DirectiveKind.CAMERA),
        (MetaCommand("LPUB", "SOME FUTURE META 1"), DirectiveKind.UNSUPPORTED_LPUB),
        (MetaCommand("PYLDRAW", 'NOTE "page:17"'), DirectiveKind.NOTE),
        (MetaCommand("PYLDRAW", "HIGHLIGHT NEXT"), DirectiveKind.HIGHLIGHT),
        (MetaCommand("PYLDRAW", "ARROW 0 0 0 1 2 3"), DirectiveKind.ARROW),
    ],
)
def test_directive_parser_recognizes_canonical_and_legacy_forms(
    raw: Comment | MetaCommand,
    kind: DirectiveKind,
) -> None:
    directive = parse_instruction_directive(raw, source_line=7)

    assert directive is not None
    assert directive.kind is kind
    assert directive.raw is raw
    assert directive.source_line == 7
    assert directive.to_dict()["raw"] == raw.to_ldraw()


@pytest.mark.parametrize(
    "text",
    [
        "ROTSTEP",
        "ROTSTEP x 0 0",
        "ROTSTEP 361 0 0",
        "ROTSTEP 0 0 0 BAD",
        "ROTSTEP 0 0 0 END",
    ],
)
def test_malformed_rotation_directives_are_preserved(text: str) -> None:
    raw = Comment(text)
    directive = parse_instruction_directive(raw)

    assert directive is not None
    assert directive.kind is DirectiveKind.MALFORMED
    assert directive.raw is raw


@pytest.mark.parametrize(
    "text",
    [
        "CALLOUT BEGIN BAD",
        "PARSE_NOSTEP maybe",
        "INSERT PAGE OFFSET x 2",
        "ASSEM CAMERA_FOV LOCAL nope",
        "ASSEM CAMERA_ORTHOGRAPHIC maybe",
        'ASSEM CAMERA_NAME "unterminated',
    ],
)
def test_malformed_lpub_directives_are_typed(text: str) -> None:
    directive = parse_instruction_directive(MetaCommand("LPUB", text))

    assert directive is not None
    assert directive.kind is DirectiveKind.MALFORMED


def test_non_directives_and_additional_malformed_grammar_branches() -> None:
    assert parse_instruction_directive(Comment("ordinary note")) is None
    geometry = parse_model("2 16 0 0 0 1 1 1").objects[0]
    assert parse_instruction_directive(geometry) is None
    assert parse_instruction_directive(MetaCommand("LEOCAD", "MODEL AUTHOR")) is None

    malformed = (
        "CALLOUT BEGIN WHOLE EXTRA",
        "INSERT PAGE OFFSET 1",
        "ASSEM CAMERA_POSITION 1 2",
        "ASSEM CAMERA_DISTANCE 1 2",
        "ASSEM CAMERA_NAME one two",
        "ASSEM CAMERA_ANGLES 1 2 3 4",
        "ASSEM CAMERA_UNKNOWN 1",
    )
    for text in malformed:
        directive = parse_instruction_directive(MetaCommand("LPUB", text))
        assert directive is not None
        assert directive.kind is DirectiveKind.MALFORMED

    unsupported = parse_instruction_directive(MetaCommand("LPUB", "ASSEM NOT_CAMERA 1"))
    assert unsupported is not None
    assert unsupported.kind is DirectiveKind.UNSUPPORTED_LPUB


def test_camera_presets_lat_lon_and_pyldraw_error_branches() -> None:
    preset = parse_instruction_directive(
        MetaCommand("LPUB", "ASSEM CAMERA_ANGLES FRONT")
    )
    lat_lon = parse_instruction_directive(
        MetaCommand("LPUB", "ASSEM CAMERA_ANGLES LAT_LON 10 20")
    )
    assert preset is not None
    assert preset.value("value") == "FRONT"
    assert lat_lon is not None
    assert lat_lon.value("value") == (10.0, 20.0)

    malformed_annotations = (
        'NOTE "unterminated',
        "NOTE one two",
        "HIGHLIGHT PREVIOUS",
        "ARROW 0 0",
        "ARROW x 0 0 1 2 3",
        "ARROW 0 0 0 1 2 3 WRONG label",
    )
    for text in malformed_annotations:
        directive = parse_instruction_directive(MetaCommand("PYLDRAW", text))
        assert directive is not None
        assert directive.kind is DirectiveKind.MALFORMED
    future = parse_instruction_directive(MetaCommand("PYLDRAW", "FUTURE data"))
    assert future is not None
    assert future.kind is DirectiveKind.UNSUPPORTED_PYLDRAW


def test_camera_global_local_and_context_inheritance() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                "0 !LPUB ASSEM CAMERA_FOV GLOBAL 45",
                _piece(),
                "0 STEP",
                "0 !LPUB ASSEM CAMERA_DISTANCE LOCAL 100",
                _piece(x=20),
                "0 STEP",
                "0 !LPUB CALLOUT BEGIN ROTATED",
                "0 !LPUB CALLOUT ASSEM CAMERA_FOV LOCAL 30",
                _piece("sub.ldr", x=40),
                "0 !LPUB CALLOUT END",
                "0 STEP",
                _piece(x=60),
                "0 STEP",
                "0 !LPUB MULTI_STEP BEGIN",
                "0 !LPUB MULTI_STEP ASSEM CAMERA_DISTANCE GLOBAL 200",
                _piece(x=80),
                "0 STEP",
                "0 !LPUB MULTI_STEP END",
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(),
                "0 NOFILE",
            )
        )
    )
    document = model.instruction_document()
    steps = document.root.steps

    assert document.root.name == "main.ldr"
    assert document.section("sub.ldr").name == "sub.ldr"
    assert steps[0].camera == CameraState(fov=45)
    assert steps[1].camera == CameraState(distance=100, fov=45)
    assert steps[2].camera.fov == 30
    assert steps[2].callouts[0].mode is CalloutMode.ROTATED
    assert steps[2].callouts[0].references == ("sub.ldr",)
    assert steps[3].camera == CameraState(fov=45)
    assert steps[4].camera == CameraState(distance=200, fov=45)
    assert steps[4].multi_step_group == 1


def test_all_camera_values_parse_and_builder_serializes_them() -> None:
    model = Model(name="camera.ldr")
    builder = InstructionBuilder(model)
    camera = CameraState(
        angles=(10, 20),
        position=(1, 2, 3),
        target=(4, 5, 6),
        up_vector=(0, 1, 0),
        distance=100,
        fov=35,
        name='Hero "view"',
        orthographic=True,
        z_near=1,
        z_far=1_000,
    )

    builder.set_camera(
        camera,
        scope=InstructionScope.GLOBAL,
        context=CameraContext.MULTI_STEP,
    )
    model.add(Piece.place("3001"))
    builder.step()
    step = model.instruction_document().root.steps[0]

    assert step.camera == CameraState()
    camera_directives = [
        item for item in step.directives if item.kind is DirectiveKind.CAMERA
    ]
    assert len(camera_directives) == 10
    assert all(
        item.raw.to_ldraw().startswith("0 !LPUB MULTI_STEP ASSEM CAMERA_")
        for item in camera_directives
    )

    preset_model = Model(objects=[Piece.place("3001")])
    preset_builder = InstructionBuilder(preset_model)
    preset_builder.set_camera(CameraState(angle_preset="HOME"))
    preset_builder.step()
    preset_step = preset_model.instruction_document().root.steps[0]
    assert preset_step.camera.angle_preset == "HOME"


def test_builder_annotations_highlight_and_balanced_ranges() -> None:
    first = Piece.place("3001", colour=1)
    second = Piece.place("3001", colour=2)
    model = Model(name="builder.ldr", objects=[first, second])
    builder = InstructionBuilder(model)

    builder.highlight(second)
    builder.note('PDF page "17"')
    builder.arrow(Vector(0, 1, 2), Vector(3, 4, 5), label="attach")
    builder.page_break(offset=(1.5, -2))
    builder.suppress_step()
    builder.rotation_step(0, 90, 0, mode=RotationMode.ABSOLUTE)
    builder.end_rotation()
    with (
        pytest.raises(RuntimeError, match="stop"),
        builder.callout(mode=CalloutMode.WHOLE),
        builder.ignore(InventoryTarget.PLI),
    ):
        raise RuntimeError("stop")

    assert model.objects[1] == MetaCommand("PYLDRAW", "HIGHLIGHT NEXT")
    text = model.to_ldraw()
    assert '0 !PYLDRAW NOTE "PDF page \\"17\\""' in text
    assert '0 !PYLDRAW ARROW 0 1 2 3 4 5 LABEL "attach"' in text
    assert "0 !LPUB INSERT PAGE OFFSET 1.5 -2" in text
    assert "0 ROTSTEP 0 90 0 ABS" in text
    assert text.endswith("0 !LPUB CALLOUT END")
    assert text.count("PLI BEGIN IGN") == text.count("PLI END") == 1


def test_builder_rejects_invalid_targets_and_same_range_nesting_before_mutation() -> (
    None
):
    model = Model()
    builder = InstructionBuilder(model)

    with pytest.raises(ValueError, match="not in this model"):
        builder.highlight(Piece.place("3001"))
    assert model.objects == []

    with builder.multi_step():
        count_before = len(model.objects)
        with (
            pytest.raises(ValueError, match="Cannot nest MULTI_STEP"),
            builder.multi_step(),
        ):
            pass
        assert len(model.objects) == count_before
    assert [obj.text for obj in model.objects if isinstance(obj, MetaCommand)] == [
        "MULTI_STEP BEGIN",
        "MULTI_STEP END",
    ]

    with pytest.raises(ValueError, match="end_rotation_steps"):
        model.add_rotation_step(0, 0, 0, mode=RotationMode.END)


def test_lpub_inventory_ignore_scopes_do_not_remove_geometry() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                "0 !LPUB PLI BEGIN IGN",
                _piece("sub.ldr"),
                "0 !LPUB PLI END",
                "0 STEP",
                "0 !LPUB BOM BEGIN IGN",
                _piece(x=20),
                "0 !LPUB BOM END",
                "0 STEP",
                "0 !LPUB PART BEGIN IGN",
                _piece(x=40),
                "0 !LPUB PART END",
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(colour=1),
                _piece(colour=2, x=10),
                "0 NOFILE",
            )
        )
    )
    steps = model.instruction_document().root.steps

    assert [len(step.added_occurrences()) for step in steps] == [2, 1, 1]
    assert steps[0].added_bill_of_materials() == []
    assert (
        sum(
            row.quantity for row in steps[0].added_bill_of_materials(respect_lpub=False)
        )
        == 2
    )
    assert sum(row.quantity for row in steps[1].added_bill_of_materials()) == 1
    assert steps[2].added_bill_of_materials() == []
    assert sum(row.quantity for row in steps[2].cumulative_bill_of_materials()) == 2
    assert (
        sum(
            row.quantity
            for row in steps[2].cumulative_bill_of_materials(respect_lpub=False)
        )
        == 4
    )


def test_instruction_validation_reports_structural_and_semantic_codes() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                "0 !LPUB CALLOUT BEGIN",
                "0 !LPUB MULTI_STEP BEGIN",
                "0 !LPUB CALLOUT END",
                "0 !LPUB MULTI_STEP END",
                "0 !LPUB CALLOUT BEGIN",
                _piece(),
                "0 !LPUB CALLOUT END",
                "0 !LPUB ASSEM CAMERA_FOV 200",
                "0 !LPUB ASSEM CAMERA_ZNEAR -1",
                "0 !LPUB ASSEM CAMERA_ZFAR -2",
                "0 !LPUB ASSEM CAMERA_UPVECTOR 0 0 0",
                "0 !PYLDRAW HIGHLIGHT NEXT",
                "0 STEP",
                "0 STEP",
                _piece("missing.ldr"),
                "0 ROTSTEP nope 0 0",
                "0 NOFILE",
                "0 FILE orphan.ldr",
                _piece(),
                "0 NOFILE",
            )
        ),
        source="issues.mpd",
    )
    issues = list(iter_instruction_issues(model.instruction_document(), max_parts=0))
    codes = {issue.code for issue in issues}

    assert {
        "orphan-section",
        "crossed-range",
        "empty-callout",
        "invalid-camera-fov",
        "invalid-camera-near",
        "invalid-camera-far",
        "invalid-camera-up",
        "missing-highlight-target",
        "empty-step",
        "unknown-submodel",
        "malformed-directive",
        "step-too-large",
    } <= codes
    malformed = next(issue for issue in issues if issue.code == "malformed-directive")
    assert malformed.section == "main.ldr"
    assert malformed.line_number == 17
    orphan = next(issue for issue in issues if issue.code == "orphan-section")
    assert orphan.severity is Severity.WARNING


def test_validation_reports_missing_boundaries_unclosed_ranges_and_cycles() -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                "0 !LPUB PLI BEGIN IGN",
                _piece("sub.ldr"),
                _piece(x=20),
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece("main.ldr"),
                "0 NOFILE",
            )
        )
    )

    issues = list(iter_instruction_issues(model.instruction_document()))
    codes = [issue.code for issue in issues]

    assert "cyclic-submodel" in codes
    assert "unclosed-range" in codes
    assert "no-step-boundaries" in codes


def test_validation_reports_illegal_nesting_unbalanced_ends_and_final_highlight() -> (
    None
):
    model = parse_model(
        f"0 !LPUB CALLOUT BEGIN\n"
        f"0 !LPUB CALLOUT BEGIN\n"
        f"0 !LPUB CALLOUT END\n"
        f"0 !LPUB CALLOUT END\n"
        f"0 !LPUB MULTI_STEP END\n"
        f"{_piece()}\n"
        f"0 !PYLDRAW HIGHLIGHT NEXT"
    )

    codes = {
        issue.code for issue in iter_instruction_issues(model.instruction_document())
    }

    assert "illegal-nesting" in codes
    assert "unbalanced-range" in codes
    assert "missing-highlight-target" in codes


def test_final_delimiter_drops_only_the_phantom_group() -> None:
    model = parse_model(f"{_piece()}\n0 STEP\n")

    steps = list(model.iter_instruction_steps())

    assert len(steps) == 1
    assert steps[0].source_start_line == 1
    assert steps[0].source_end_line == 2
