"""Tests for raster registration and visual-comparison reporting."""

import argparse
import builtins
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import numpy as np
import pytest
from PIL import Image, ImageDraw

from ldraw import visual_compare
from ldraw.visual_compare import (
    AlignmentConfig,
    Camera,
    Region,
    apply_alignment,
    build_report,
    camera_grid,
    compare,
    compare_paths,
    difference_heatmap,
    estimate_background,
    foreground_mask,
    image_metrics,
    load_image,
    main,
    mask_box,
    overlay_image,
    parse_number_list,
    rank_candidates,
    register_silhouettes,
    render_leocad_grid,
    write_comparison_artifacts,
    write_contact_sheet,
)

if TYPE_CHECKING:
    from collections.abc import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Since Python 3.14 argparse derives the ``python -m package.module`` prog for
# module execution; older interpreters fall back to the module file's basename.
_MODULE_USAGE = (
    f"usage: {Path(sys.executable).name} -m ldraw.visual_compare"
    if sys.version_info >= (3, 14)
    else "usage: visual_compare.py"
)


def _load_visual_compare_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "visual_compare_script",
        PROJECT_ROOT / "scripts" / "visual_compare.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_image(
    *,
    size: tuple[int, int] = (96, 80),
    background: str = "white",
    offset: tuple[int, int] = (0, 0),
    scale: float = 1.0,
    colour: str = "#c91a09",
) -> Image.Image:
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    left, top = offset
    body = tuple(
        round(value * scale) for value in (left + 20, top + 26, left + 59, top + 59)
    )
    cab = tuple(
        round(value * scale) for value in (left + 30, top + 14, left + 49, top + 25)
    )
    draw.rectangle(body, fill=colour)
    draw.rectangle(cab, fill=colour)
    return image


def _save_model(path: Path, **kwargs) -> Path:
    _model_image(**kwargs).save(path)
    return path


def test_visual_comparison_dependency_and_command_are_optional() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert all(
        not dependency.casefold().startswith("pillow")
        for dependency in project["project"]["dependencies"]
    )
    extra = project["project"]["optional-dependencies"]["visual-compare"]
    assert len(extra) == 1
    assert extra[0].casefold().startswith("pillow")
    assert "ldraw-compare" not in project["project"]["scripts"]
    assert any(
        dependency.casefold().startswith("pillow")
        for dependency in project["dependency-groups"]["dev"]
    )


@pytest.mark.parametrize("missing_name", ["PIL", "PIL.Image"])
def test_repository_script_explains_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_name: str,
) -> None:
    script = _load_visual_compare_script()
    real_import = builtins.__import__

    def missing_pillow(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        if name == "ldraw.visual_compare":
            message = f"No module named {missing_name!r}"
            raise ModuleNotFoundError(message, name=missing_name)
        importer = real_import
        return importer(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_pillow)

    assert cast("Callable[[list[str]], int]", script.main)([]) == 1
    assert "pyldraw3[visual-compare]" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "usage"),
    [
        (
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "visual_compare.py"),
                "--help",
            ],
            "usage: visual_compare.py",
        ),
        (
            [sys.executable, "-m", "ldraw.visual_compare", "--help"],
            _MODULE_USAGE,
        ),
    ],
)
def test_help_uses_the_actual_invocation_name(command: list[str], usage: str) -> None:
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0
    assert process.stdout.startswith(usage)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_scale": 0}, "min_scale"),
        ({"min_scale": 2, "max_scale": 1}, "max_scale"),
        ({"scale_steps": 0}, "scale_steps"),
        ({"min_scale": 1.0, "max_scale": 1.2, "scale_steps": 1}, "requires min_scale"),
        ({"background_tolerance": -1}, "background_tolerance"),
        ({"alpha_threshold": 300}, "alpha_threshold"),
    ],
)
def test_alignment_config_rejects_invalid_settings(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        AlignmentConfig(**kwargs)


def test_region_resolves_normalized_and_pixel_boxes() -> None:
    assert Region("cab", (0.25, 0.25, 0.5, 0.5)).resolve((100, 80)) == (
        25,
        20,
        75,
        60,
    )
    assert Region("cab", (-4, 5, 30, 20), relative=False).resolve((20, 20)) == (
        0,
        5,
        20,
        20,
    )
    with pytest.raises(ValueError, match="empty crop"):
        Region("outside", (2, 2, 1, 1)).resolve((100, 100))


def test_camera_grid_has_stable_keys_and_parseable_angles() -> None:
    cameras = camera_grid([15, 30], [-45, 0])
    assert cameras == [
        Camera(15, -45),
        Camera(15, 0),
        Camera(30, -45),
        Camera(30, 0),
    ]
    assert cameras[0].key == "lat_p015d00_lon_m045d00"
    assert parse_number_list(" 15, 30.5 ") == [15.0, 30.5]
    with pytest.raises(Exception, match="comma-separated numbers"):
        parse_number_list("fifteen")
    with pytest.raises(Exception, match="finite numbers"):
        parse_number_list("nan")


def test_image_loading_background_and_opaque_foreground(tmp_path: Path) -> None:
    path = _save_model(tmp_path / "model.png", background="#f4f5f6")
    image = load_image(path)
    mask = foreground_mask(image, background_tolerance=12)

    assert image.mode == "RGBA"
    assert estimate_background(image) == (244, 245, 246)
    assert mask[30, 30]
    assert not mask[0, 0]
    assert mask_box(mask) == (20, 14, 60, 60)


def test_transparent_image_uses_alpha_for_foreground() -> None:
    image = Image.new("RGBA", (8, 8), (200, 0, 0, 0))
    image.putpixel((3, 4), (255, 255, 255, 128))
    mask = foreground_mask(image, alpha_threshold=16)
    assert mask.sum() == 1
    assert mask[4, 3]


def test_one_pixel_image_estimates_background() -> None:
    image = Image.new("RGB", (1, 1), (10, 20, 30))
    assert estimate_background(image) == (10, 20, 30)


def test_mask_box_rejects_empty_mask() -> None:
    with pytest.raises(ValueError, match="no detectable foreground"):
        mask_box(np.zeros((4, 4), dtype=np.bool_))


def test_registration_recovers_scale_and_translation() -> None:
    reference = _model_image()
    candidate = _model_image(size=(70, 70), scale=0.5)
    reference_mask = foreground_mask(reference)
    candidate_mask = foreground_mask(candidate)
    config = AlignmentConfig(min_scale=2.0, max_scale=2.0, scale_steps=1)

    alignment = register_silhouettes(reference_mask, candidate_mask, config=config)
    aligned, aligned_mask = apply_alignment(
        candidate,
        candidate_mask,
        alignment,
        reference.size,
    )

    assert alignment.scale == 2.0
    assert alignment.offset_x == 20
    assert alignment.offset_y == 12
    assert alignment.silhouette_iou > 0.9
    assert aligned.size == reference.size
    assert (
        image_metrics(reference, aligned, reference_mask, aligned_mask)[
            "silhouette_iou"
        ]
        > 0.9
    )


def test_registration_sweep_matches_or_beats_single_scale() -> None:
    reference = _model_image()
    candidate = _model_image(size=(70, 70), scale=0.5)
    reference_mask = foreground_mask(reference)
    candidate_mask = foreground_mask(candidate)
    fixed = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=AlignmentConfig(min_scale=2.0, max_scale=2.0, scale_steps=1),
    )

    swept = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=AlignmentConfig(min_scale=1.0, max_scale=2.5, scale_steps=16),
    )

    assert swept.silhouette_iou >= fixed.silhouette_iou
    assert 1.5 <= swept.scale <= 2.5


def test_tied_registration_does_not_depend_on_losing_scales() -> None:
    reference = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    reference.putpixel((1, 0), (255, 0, 0, 255))
    reference.putpixel((2, 2), (0, 0, 255, 255))
    candidate = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    candidate.putpixel((0, 0), (255, 0, 0, 255))

    fixed = compare(
        reference,
        candidate,
        config=AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1),
    )
    swept = compare(
        reference,
        candidate,
        config=AlignmentConfig(min_scale=1, max_scale=4, scale_steps=2),
    )

    assert fixed.alignment == swept.alignment
    assert fixed.metrics == swept.metrics
    assert swept.alignment.offset_x == 1
    assert swept.alignment.offset_y == 0
    assert swept.metrics["rgb_mae"] == 0.0


def test_coarse_registration_matches_the_exhaustive_full_resolution_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _model_image()
    candidate = _model_image(size=(70, 70), scale=0.5)
    reference_mask = foreground_mask(reference)
    candidate_mask = foreground_mask(candidate)
    config = AlignmentConfig(min_scale=1.0, max_scale=2.5, scale_steps=16)
    exhaustive = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=config,
    )
    monkeypatch.setattr(visual_compare, "_COARSE_MAX_DIMENSION", 32)

    alignment = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=config,
    )

    assert alignment == exhaustive


def test_coarse_tie_pruning_keeps_the_tied_optimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sizes 13-17 all collapse to the same 3x3 coarse mask and tie at coarse
    # IoU 1.0; the true optimum (size 17, index 7) sits past the window the
    # old top-3-indices-plus-radius selection kept, so it used to be pruned.
    reference_mask = np.zeros((40, 40), dtype=np.bool_)
    reference_mask[5:22, 5:22] = True
    candidate_mask = np.ones((10, 10), dtype=np.bool_)
    config = AlignmentConfig(min_scale=1.0, max_scale=2.0, scale_steps=11)
    exhaustive = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=config,
    )
    monkeypatch.setattr(visual_compare, "_COARSE_MAX_DIMENSION", 8)

    pruned = register_silhouettes(
        reference_mask,
        candidate_mask,
        config=config,
    )

    assert exhaustive.scale == pytest.approx(1.7)
    assert exhaustive.silhouette_iou == 1.0
    assert pruned == exhaustive


def test_registration_rejects_empty_or_oversized_candidates() -> None:
    reference = np.ones((20, 20), dtype=np.bool_)
    with pytest.raises(ValueError, match="no detectable foreground"):
        register_silhouettes(reference, np.zeros((10, 10), dtype=np.bool_))
    candidate = np.ones((30, 30), dtype=np.bool_)
    with pytest.raises(ValueError, match="no configured scale fits"):
        register_silhouettes(
            reference,
            candidate,
            config=AlignmentConfig(min_scale=2, max_scale=2, scale_steps=1),
        )
    with pytest.raises(ValueError, match="reference image"):
        register_silhouettes(
            np.zeros((20, 20), dtype=np.bool_),
            np.ones((10, 10), dtype=np.bool_),
        )
    with pytest.raises(ValueError, match="does not fit"):
        visual_compare._best_placement(  # noqa: SLF001
            np.ones((10, 10), dtype=np.bool_),
            np.ones((20, 20), dtype=np.bool_),
        )
    with pytest.raises(ValueError, match="supplied together"):
        visual_compare._best_placement(  # noqa: SLF001
            np.ones((10, 10), dtype=np.bool_),
            np.ones((5, 5), dtype=np.bool_),
            transform_shape=(14, 14),
        )


def test_comparison_metrics_and_visuals() -> None:
    reference = _model_image()
    candidate = _model_image(colour="#0055bf")
    result = compare(
        reference,
        candidate,
        config=AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1),
        regions=[Region("cab", (0.2, 0.1, 0.5, 0.5))],
    )

    assert result.metrics["silhouette_iou"] == 1.0
    assert result.metrics["rgb_mae"] > 0
    assert result.regions["cab"]["silhouette_recall"] == 1.0
    assert overlay_image(result).size == reference.size
    assert difference_heatmap(result).getbbox() is not None


def test_colliding_or_duplicate_region_names_are_rejected() -> None:
    reference = _model_image()
    candidate = _model_image()
    config = AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1)

    colliding = [
        Region("cab!", (0.2, 0.1, 0.5, 0.5)),
        Region("cab?", (0.1, 0.1, 0.5, 0.5)),
    ]
    with pytest.raises(ValueError, match="both map to"):
        compare(reference, candidate, config=config, regions=colliding)

    duplicated = [
        Region("cab", (0.2, 0.1, 0.5, 0.5)),
        Region("cab", (0.1, 0.1, 0.5, 0.5)),
    ]
    with pytest.raises(ValueError, match="duplicate region name"):
        compare(reference, candidate, config=config, regions=duplicated)


def test_safe_names_reject_case_and_unicode_equivalent_paths() -> None:
    case_owners: dict[str, str] = {}
    assert visual_compare._claim_safe_name("Front", case_owners, "view") == "Front"  # noqa: SLF001
    with pytest.raises(ValueError, match="filesystem-equivalent"):
        visual_compare._claim_safe_name("front", case_owners, "view")  # noqa: SLF001

    unicode_owners: dict[str, str] = {}
    assert (
        visual_compare._claim_safe_name(  # noqa: SLF001
            "Caf\N{LATIN SMALL LETTER E WITH ACUTE}",
            unicode_owners,
            "candidate",
        )
        == "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"
    )
    with pytest.raises(ValueError, match="both map to"):
        visual_compare._claim_safe_name(  # noqa: SLF001
            "Cafe\N{COMBINING ACUTE ACCENT}",
            unicode_owners,
            "candidate",
        )


def test_artifact_regions_must_match_the_comparison(tmp_path: Path) -> None:
    reference = _model_image()
    candidate = _model_image()
    config = AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1)
    result = compare(
        reference,
        candidate,
        config=config,
        regions=[Region("cab", (0.2, 0.1, 0.5, 0.5))],
    )
    output = tmp_path / "mismatch"

    with pytest.raises(ValueError, match="regions must match"):
        write_comparison_artifacts(result, output)

    assert not output.exists()


def test_artifact_region_boxes_must_match_the_comparison(tmp_path: Path) -> None:
    reference = _model_image()
    candidate = _model_image()
    result = compare(
        reference,
        candidate,
        config=AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1),
        regions=[Region("cab", (0.2, 0.1, 0.5, 0.5))],
    )
    output = tmp_path / "box-mismatch"

    with pytest.raises(ValueError, match="box does not match the comparison"):
        write_comparison_artifacts(
            result,
            output,
            regions=[Region("cab", (0.1, 0.1, 0.5, 0.5))],
        )

    assert not output.exists()


def test_image_metrics_handles_empty_and_disjoint_masks() -> None:
    image = Image.new("RGB", (4, 4), "white")
    empty = np.zeros((4, 4), dtype=np.bool_)
    full = np.ones((4, 4), dtype=np.bool_)
    both_empty = image_metrics(image, image, empty, empty)
    disjoint = image_metrics(image, image, full, empty)

    assert both_empty["silhouette_iou"] == 1.0
    assert both_empty["silhouette_dice"] == 1.0
    assert disjoint["silhouette_iou"] == 0.0
    assert disjoint["rgb_mae"] == 1.0


def test_compare_paths_writes_artifacts_and_region_crops(tmp_path: Path) -> None:
    reference = _save_model(tmp_path / "reference.png")
    candidate = _save_model(tmp_path / "candidate.png")
    output_dir = tmp_path / "comparison"
    regions = [Region("upper cab", (0.2, 0.1, 0.5, 0.5))]

    payload = compare_paths(
        reference,
        candidate,
        output_dir,
        config=AlignmentConfig(min_scale=1, max_scale=1, scale_steps=1),
        regions=regions,
    )

    assert payload["metrics"]["silhouette_iou"] == 1.0
    assert (output_dir / "aligned.png").is_file()
    assert (output_dir / "overlay.png").is_file()
    assert (output_dir / "difference.png").is_file()
    assert (output_dir / "regions/upper-cab.reference.png").is_file()
    saved = json.loads((output_dir / "comparison.json").read_text())
    assert saved["alignment"]["scale"] == 1.0


def test_ranking_prefers_matching_silhouette_and_writes_sheet(tmp_path: Path) -> None:
    reference = _save_model(tmp_path / "reference.png")
    good = _save_model(tmp_path / "good.png", offset=(5, 3))
    bad_image = Image.new("RGB", (96, 80), "white")
    ImageDraw.Draw(bad_image).ellipse((20, 15, 60, 60), fill="red")
    bad = tmp_path / "bad.png"
    bad_image.save(bad)

    ranking = rank_candidates(reference, [bad, good])

    assert Path(ranking[0]["candidate"]).name == "good.png"
    assert [row["rank"] for row in ranking] == [1, 2]
    sheet = tmp_path / "ranking.png"
    write_contact_sheet(ranking, sheet, columns=2)
    assert sheet.is_file()
    with pytest.raises(ValueError, match="columns"):
        write_contact_sheet(ranking, sheet, columns=0)


def test_render_leocad_grid_builds_commands(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 test\n")
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = Path(command[command.index("--image") + 1])
        _model_image().save(output)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(visual_compare.shutil, "which", lambda _value: "/bin/leocad")
    monkeypatch.setattr(visual_compare.subprocess, "run", fake_run)
    renders = render_leocad_grid(
        model,
        tmp_path / "grid",
        [Camera(20, -45), Camera(30, 45)],
        size=(640, 480),
    )

    assert len(renders) == 2
    assert calls[0][-3:] == ["--camera-angles", "20", "-45"]
    assert calls[0][calls[0].index("--width") + 1] == "640"

    calls.clear()
    render_leocad_grid(
        model,
        tmp_path / "grid",
        [Camera(20, -45)],
        skip_existing=True,
    )
    assert calls == []


def test_render_leocad_grid_reports_preflight_and_renderer_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with pytest.raises(FileNotFoundError, match="model not found"):
        render_leocad_grid(tmp_path / "missing.ldr", tmp_path, [])

    model = tmp_path / "model.ldr"
    model.write_text("0 test\n")
    with pytest.raises(ValueError, match="timeout must be positive"):
        render_leocad_grid(model, tmp_path, [], timeout_seconds=0)
    with pytest.raises(ValueError, match="share the file key"):
        render_leocad_grid(
            model,
            tmp_path,
            [Camera(15.001, 0), Camera(15.004, 0)],
        )
    camera = Camera(15.001, 0)
    with pytest.raises(ValueError, match="share the file key"):
        render_leocad_grid(model, tmp_path, [camera, camera])
    monkeypatch.setattr(visual_compare.shutil, "which", lambda _value: None)
    with pytest.raises(FileNotFoundError, match="executable not found"):
        render_leocad_grid(model, tmp_path, [])

    monkeypatch.setattr(visual_compare.shutil, "which", lambda _value: "/bin/leocad")
    with pytest.raises(ValueError, match="render size"):
        render_leocad_grid(model, tmp_path, [], size=(0, 100))

    monkeypatch.setattr(
        visual_compare.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "broken"),
    )
    with pytest.raises(RuntimeError, match="broken"):
        render_leocad_grid(model, tmp_path, [Camera(0, 0)])

    def raise_timeout(*_args, **_kwargs) -> None:
        raise subprocess.TimeoutExpired("leocad", 5)

    monkeypatch.setattr(visual_compare.subprocess, "run", raise_timeout)
    with pytest.raises(RuntimeError, match="timed out after 5s"):
        render_leocad_grid(
            model,
            tmp_path,
            [Camera(0, 0)],
            timeout_seconds=5,
        )


@pytest.mark.parametrize(
    "value",
    [None, "not a list", ["not an object"], [{"name": "bad", "box": [1]}]],
)
def test_region_json_parser_rejects_bad_shapes(value) -> None:
    if value is None:
        assert visual_compare._regions_from_json(value) == []  # noqa: SLF001
        return
    with pytest.raises((TypeError, ValueError)):
        visual_compare._regions_from_json(value)  # noqa: SLF001


def test_manifest_value_parsers_cover_validation() -> None:
    assert visual_compare._parse_size("640x480") == (640, 480)  # noqa: SLF001
    for value in ("640", "0x480"):
        with pytest.raises(argparse.ArgumentTypeError):
            visual_compare._parse_size(value)  # noqa: SLF001

    with pytest.raises(TypeError, match="region relative"):
        visual_compare._regions_from_json(  # noqa: SLF001
            [{"name": "cab", "box": [0, 0, 1, 1], "relative": "yes"}],
        )
    with pytest.raises(TypeError, match="alignment"):
        visual_compare._config_from_mapping([])  # noqa: SLF001
    with pytest.raises(TypeError, match="setting names"):
        visual_compare._config_from_mapping({1: 2})  # type: ignore[dict-item]  # noqa: SLF001
    with pytest.raises(ValueError, match="unknown alignment"):
        visual_compare._config_from_mapping({"unknown": 1})  # noqa: SLF001
    with pytest.raises(TypeError, match="must be a number"):
        visual_compare._config_from_mapping({"min_scale": "wide"})  # noqa: SLF001
    with pytest.raises(TypeError, match="must be an integer"):
        visual_compare._config_from_mapping({"scale_steps": 2.5})  # noqa: SLF001
    with pytest.raises(TypeError, match="string label"):
        visual_compare._candidate_specs([{"label": 1, "path": "a.png"}])  # noqa: SLF001
    with pytest.raises(TypeError, match="candidate must"):
        visual_compare._candidate_specs([1])  # noqa: SLF001


def test_manifest_report_covers_multiple_views_and_candidates(tmp_path: Path) -> None:
    _save_model(tmp_path / "front-reference.png")
    _save_model(tmp_path / "front-good.png", offset=(5, 3))
    _save_model(tmp_path / "front-blue.png", colour="#0055bf")
    _save_model(tmp_path / "side-reference.png", colour="#0055bf")
    _save_model(tmp_path / "side.png", colour="#0055bf", scale=0.8)
    manifest = {
        "alignment": {"min_scale": 0.8, "max_scale": 1.25, "scale_steps": 10},
        "views": [
            {
                "name": "front",
                "reference": "front-reference.png",
                "candidates": [
                    {"label": "geometry", "path": "front-good.png"},
                    "front-blue.png",
                ],
                "regions": [
                    {"name": "cab", "box": [0.2, 0.1, 0.5, 0.5]},
                ],
            },
            {
                "name": "side",
                "reference": "side-reference.png",
                "candidate": "side.png",
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    report = build_report(manifest_path, tmp_path / "report")

    assert len(report["views"]) == 2
    assert report["aggregate"]["mean_silhouette_iou"] > 0.9
    assert (tmp_path / "report/report.json").is_file()
    html_text = (tmp_path / "report/report.html").read_text()
    assert "LDraw visual comparison" in html_text
    assert "views/front/geometry/overlay.png" in html_text


def test_manifest_report_rejects_colliding_view_and_candidate_names(
    tmp_path: Path,
) -> None:
    _save_model(tmp_path / "reference.png")
    _save_model(tmp_path / "candidate.png")
    alignment = {"min_scale": 1, "max_scale": 1, "scale_steps": 1}
    manifest_path = tmp_path / "manifest.json"

    manifest_path.write_text(
        json.dumps(
            {
                "alignment": alignment,
                "views": [
                    {
                        "name": "front",
                        "reference": "reference.png",
                        "candidate": "candidate.png",
                    },
                    {
                        "name": "front!",
                        "reference": "reference.png",
                        "candidate": "candidate.png",
                    },
                ],
            },
        ),
    )
    with pytest.raises(ValueError, match="both map to"):
        build_report(manifest_path, tmp_path / "views-report")

    manifest_path.write_text(
        json.dumps(
            {
                "alignment": alignment,
                "views": [
                    {
                        "name": "solo",
                        "reference": "reference.png",
                        "candidates": ["candidate.png", "candidate.png"],
                    },
                ],
            },
        ),
    )
    with pytest.raises(ValueError, match="duplicate candidate name"):
        build_report(manifest_path, tmp_path / "labels-report")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"views": ["bad"]},
        {"views": [{}]},
        {"views": [{"name": "front", "reference": "ref.png"}]},
    ],
)
def test_manifest_report_rejects_invalid_structure(tmp_path: Path, payload) -> None:
    manifest = tmp_path / "bad.json"
    manifest.write_text(json.dumps(payload))
    with pytest.raises((TypeError, ValueError)):
        build_report(manifest, tmp_path / "out")


def test_cli_compare_rank_and_report(tmp_path: Path, capsys) -> None:
    reference = _save_model(tmp_path / "reference.png")
    candidate = _save_model(tmp_path / "candidate.png")
    regions_path = tmp_path / "regions.json"
    regions_path.write_text(json.dumps([{"name": "cab", "box": [0, 0, 1, 1]}]))
    assert (
        main(
            [
                "compare",
                str(reference),
                str(candidate),
                "--output-dir",
                str(tmp_path / "compare"),
                "--regions",
                str(regions_path),
                "--min-scale",
                "1",
                "--max-scale",
                "1",
            ],
        )
        == 0
    )
    assert "silhouette_iou" in capsys.readouterr().out

    assert (
        main(
            [
                "rank",
                str(reference),
                str(candidate),
                "--output-dir",
                str(tmp_path / "rank"),
            ],
        )
        == 0
    )
    assert (tmp_path / "rank/ranking.json").is_file()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "views": [
                    {
                        "name": "front",
                        "reference": reference.name,
                        "candidate": candidate.name,
                    },
                ],
            },
        ),
    )
    assert (
        main(
            [
                "report",
                str(manifest),
                "--output-dir",
                str(tmp_path / "cli-report"),
            ],
        )
        == 0
    )


def _fake_render_rows(output_dir: Path, cameras) -> list[dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for camera in cameras:
        path = output_dir / f"{camera.key}.png"
        _model_image().save(path)
        rows.append(
            {
                "camera": {
                    "latitude": camera.latitude,
                    "longitude": camera.longitude,
                },
                "key": camera.key,
                "path": str(path.resolve()),
                "command": [],
            },
        )
    return rows


def test_cli_camera_grid_and_error_path(tmp_path: Path, monkeypatch, capsys) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 model\n")
    reference = _save_model(tmp_path / "reference.png")
    captured_kwargs: dict[str, object] = {}

    def fake_render(_model, output_dir, cameras, **kwargs) -> list[dict[str, object]]:
        captured_kwargs.update(kwargs)
        return _fake_render_rows(output_dir, cameras)

    monkeypatch.setattr(visual_compare, "render_leocad_grid", fake_render)
    assert (
        main(
            [
                "camera-grid",
                str(model),
                "--output-dir",
                str(tmp_path / "grid"),
                "--reference",
                str(reference),
                "--latitudes",
                "20",
                "--longitudes=-45,45",
                "--timeout",
                "9",
            ],
        )
        == 0
    )
    assert captured_kwargs["timeout_seconds"] == 9
    assert (tmp_path / "grid/camera-grid.json").is_file()
    assert (tmp_path / "grid/camera-grid.png").is_file()

    assert (
        main(["report", str(tmp_path / "missing.json"), "--output-dir", str(tmp_path)])
        == 1
    )
    assert "error:" in capsys.readouterr().err


def test_cli_camera_grid_keeps_renders_json_when_ranking_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 model\n")
    blank = tmp_path / "blank.png"
    Image.new("RGB", (96, 80), "white").save(blank)
    monkeypatch.setattr(
        visual_compare,
        "render_leocad_grid",
        lambda _model, output_dir, cameras, **_kwargs: _fake_render_rows(
            output_dir,
            cameras,
        ),
    )

    assert (
        main(
            [
                "camera-grid",
                str(model),
                "--output-dir",
                str(tmp_path / "grid"),
                "--reference",
                str(blank),
                "--latitudes",
                "20",
                "--longitudes",
                "30",
            ],
        )
        == 1
    )

    assert "error:" in capsys.readouterr().err
    saved = json.loads((tmp_path / "grid/camera-grid.json").read_text())
    assert saved["renders"]
    assert "ranking" not in saved
