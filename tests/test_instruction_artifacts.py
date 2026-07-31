"""Tests for instruction manifests and cumulative snapshot bundles."""

import json
import stat
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.errors import SubmodelCycleError
from ldraw.instruction_artifacts import (
    MANIFEST_NAME,
    instruction_manifest,
    manifest_json,
    write_instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.instructions import RotationMode
from ldraw.model import Model, parse_model, read_model
from ldraw.parts import Parts

TESTS_DIR = Path(__file__).resolve().parent
PARTS = Parts(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")


def _file_contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _piece(
    reference: str = "3001.dat",
    *,
    colour: int = 4,
    x: int = 0,
) -> str:
    return f"1 {colour} {x} 0 0 1 0 0 0 1 0 0 0 1 {reference}"


def _artifact_model() -> Model:
    return parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                '0 !PYLDRAW NOTE "PDF page 1"',
                _piece("sub.ldr", colour=2, x=10),
                "0 STEP",
                "0 !LPUB NOSTEP",
                _piece(x=50),
                "0 ROTSTEP 0 90 0 ADD",
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(colour=16, x=5),
                _piece("custom.dat", colour=16, x=25),
                "0 STEP",
                "2 16 0 0 0 10 0 0",
                "0 NOFILE",
                "0 FILE custom.dat",
                _piece("s/helper.dat", colour=16),
                "2 16 0 0 0 0 10 0",
                "0 NOFILE",
                "0 FILE s/helper.dat",
                "2 16 0 0 0 10 0 0",
                "0 NOFILE",
            )
        ),
        source="source.mpd",
    )


def test_manifest_v1_is_deterministic_and_avoids_cumulative_occurrence_lists() -> None:
    model = _artifact_model()
    document = model.instruction_document(parts=PARTS)

    manifest = instruction_manifest(document, parts=PARTS, source="source.mpd")
    encoded = manifest_json(manifest)
    reparsed = json.loads(encoded)

    repeated = instruction_manifest(
        _artifact_model().instruction_document(parts=PARTS),
        parts=PARTS,
        source="source.mpd",
    )
    assert manifest_json(repeated) == encoded
    assert reparsed["schema_version"] == 1
    assert reparsed["generator"]["name"] == "pyldraw3"
    assert reparsed["source"] == "source.mpd"
    assert reparsed["root_section"] == "main.ldr"
    assert [section["name"] for section in reparsed["sections"]] == [
        "main.ldr",
        "sub.ldr",
    ]
    first, second = reparsed["sections"][0]["steps"]
    assert first["source_lines"] == [2, 4]
    assert first["direct_placements"][0]["source_section"] == "main.ldr"
    assert first["direct_placements"][0]["source_line"] == 3
    assert first["direct_placements"][0]["description"] is None
    assert len(first["added_occurrences"]) == 2
    assert first["added_occurrences"][0]["source_section"] == "sub.ldr"
    assert first["added_occurrences"][1]["part"] == "custom"
    assert first["cumulative_occurrence_count"] == 2
    assert "cumulative_occurrences" not in first
    assert first["bounds"] is not None
    assert first["geometry_warnings"][0]["part"] == "custom"
    assert second["suppressed"] is True
    assert second["rotation"]["mode"] == RotationMode.ADDITIVE.value
    assert second["cumulative_occurrence_count"] == 3


def test_write_standalone_manifest_is_atomic_and_collision_safe(
    tmp_path: Path,
) -> None:
    model = _artifact_model()
    document = model.instruction_document(parts=PARTS)
    output = tmp_path / "nested" / "manifest.json"
    ordinary = tmp_path / "ordinary.json"
    ordinary.write_text("{}\n", encoding="utf-8")

    write_instruction_manifest(
        document,
        parts=PARTS,
        output=output,
        source="source.mpd",
    )
    first = output.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        write_instruction_manifest(document, parts=PARTS, output=output)
    write_instruction_manifest(
        document,
        parts=PARTS,
        output=output,
        force=True,
    )
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1
    assert first.endswith("\n")
    assert list(output.parent.glob(".manifest.json.*")) == []
    assert stat.S_IMODE(output.stat().st_mode) == stat.S_IMODE(ordinary.stat().st_mode)


def test_snapshots_write_dual_parseable_formats_and_embedded_dat_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _artifact_model()
    document = model.instruction_document(parts=PARTS)
    output = tmp_path / "bundle"
    dat_writes: list[Path] = []
    original_write_text = Path.write_text

    def track_dat_writes(path: Path, text: str, **kwargs: object) -> int:
        if path.suffix.casefold() == ".dat":
            dat_writes.append(path)
        return original_write_text(path, text, **kwargs)

    monkeypatch.setattr(Path, "write_text", track_dat_writes)

    manifest_path = write_instruction_snapshots(
        document,
        parts=PARTS,
        output=output,
        source="source.mpd",
    )

    assert manifest_path == output / MANIFEST_NAME
    expected = {
        "001-main/step-0001.mpd",
        "001-main/step-0001.ldr",
        "001-main/step-0002.mpd",
        "001-main/step-0002.ldr",
        "001-main/custom.dat",
        "001-main/s/helper.dat",
        "002-sub/step-0001.mpd",
        "002-sub/step-0001.ldr",
        "002-sub/step-0002.mpd",
        "002-sub/step-0002.ldr",
        "002-sub/custom.dat",
        "002-sub/s/helper.dat",
        MANIFEST_NAME,
    }
    files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert files == expected

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["generated_files"]) == expected
    assert manifest["sections"][0]["steps"][0]["artifacts"] == {
        "mpd": "001-main/step-0001.mpd",
        "ldr": "001-main/step-0001.ldr",
    }
    assert manifest["sections"][0]["steps"][1]["suppressed"] is True

    for section_index, section in enumerate(document.sections, start=1):
        slug = "main" if section.is_root else "sub"
        for step in section.steps:
            base = output / f"{section_index:03d}-{slug}" / f"step-{step.number:04d}"
            mpd = read_model(base.with_suffix(".mpd"))
            ldr = read_model(base.with_suffix(".ldr"))
            expected_count = len(step.cumulative_occurrences())
            mpd_step = mpd.instruction_document().root.steps[-1]
            ldr_step = ldr.instruction_document().root.steps[-1]
            assert len(mpd_step.cumulative_occurrences()) == expected_count
            assert len(ldr_step.cumulative_occurrences()) == expected_count

    mpd_text = (output / "001-main/step-0001.mpd").read_text(encoding="utf-8")
    ldr_text = (output / "001-main/step-0001.ldr").read_text(encoding="utf-8")
    assert "0 FILE sub.ldr" in mpd_text
    assert "0 FILE custom.dat" in mpd_text
    assert "0 FILE s/helper.dat" in mpd_text
    assert "sub.ldr" not in ldr_text
    assert "custom.dat" in ldr_text
    assert "!LPUB" not in mpd_text
    assert "!PYLDRAW" not in mpd_text
    assert ldr_text.startswith("1 2 15 0 0")
    assert len(dat_writes) == len(set(dat_writes))


def test_section_selection_uses_one_numbered_directory(tmp_path: Path) -> None:
    model = _artifact_model()
    document = model.instruction_document(parts=PARTS)
    output = tmp_path / "selected"

    write_instruction_snapshots(
        document,
        parts=PARTS,
        output=output,
        section_name="SUB.LDR",
    )

    assert (output / "001-sub/step-0001.mpd").is_file()
    assert not (output / "002-sub").exists()
    manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["sections"][0]["steps"][0]["artifacts"] == {}
    assert manifest["sections"][1]["steps"][0]["artifacts"]["ldr"].startswith(
        "001-sub/"
    )


def test_force_removes_only_stale_owned_files_and_preserves_unrelated_files(
    tmp_path: Path,
) -> None:
    model = _artifact_model()
    output = tmp_path / "bundle"
    write_instruction_snapshots(
        model.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
    )
    unrelated = output / "notes.txt"
    unrelated.write_text("mine", encoding="utf-8")

    shorter = parse_model(_piece())
    write_instruction_snapshots(
        shorter.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
        force=True,
    )

    assert unrelated.read_text(encoding="utf-8") == "mine"
    assert not (output / "002-sub").exists()
    assert not (output / "001-main/step-0002.mpd").exists()
    assert (output / "001-section/step-0001.ldr").is_file()


def test_force_rolls_back_the_complete_bundle_when_the_final_swap_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _artifact_model()
    output = tmp_path / "bundle"
    write_instruction_snapshots(
        model.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
    )
    original_files = _file_contents(output)
    original_replace = Path.replace

    def fail_stage_swap(path: Path, target: Path) -> Path:
        if path.name.startswith(".bundle-") and target == output:
            raise OSError
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_stage_swap)

    with pytest.raises(OSError):
        write_instruction_snapshots(
            parse_model(_piece()).instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
            force=True,
        )

    assert _file_contents(output) == original_files
    assert not list(tmp_path.glob(".bundle-backup-*"))
    assert not list(tmp_path.glob(".bundle-*"))


def test_snapshot_collisions_require_owned_manifest(tmp_path: Path) -> None:
    model = _artifact_model()
    document = model.instruction_document(parts=PARTS)
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "mine.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        write_instruction_snapshots(document, parts=PARTS, output=output)
    with pytest.raises(ValueError, match=r"valid instructions\.json"):
        write_instruction_snapshots(
            document,
            parts=PARTS,
            output=output,
            force=True,
        )
    assert (output / "mine.txt").read_text(encoding="utf-8") == "mine"


def test_force_refuses_new_collision_with_an_unowned_path(tmp_path: Path) -> None:
    model = _artifact_model()
    output = tmp_path / "bundle"
    write_instruction_snapshots(
        model.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
        section_name="sub.ldr",
    )
    collision = output / "002-sub" / "step-0001.mpd"
    collision.parent.mkdir(parents=True)
    collision.write_text("mine", encoding="utf-8")

    with pytest.raises(FileExistsError, match="unrelated file"):
        write_instruction_snapshots(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
            force=True,
        )
    assert collision.read_text(encoding="utf-8") == "mine"


def test_unsafe_embedded_part_paths_fail_without_partial_output(tmp_path: Path) -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("../unsafe.dat"),
                "0 NOFILE",
                "0 FILE ../unsafe.dat",
                "2 16 0 0 0 1 1 1",
                "0 NOFILE",
            )
        )
    )
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="Unsafe embedded part path"):
        write_instruction_snapshots(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".bundle-*"))


def test_duplicate_sanitized_section_names_stay_distinct(tmp_path: Path) -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("A B.ldr"),
                _piece("a-b.ldr"),
                "0 NOFILE",
                "0 FILE A B.ldr",
                _piece(),
                "0 NOFILE",
                "0 FILE a-b.ldr",
                _piece(),
                "0 NOFILE",
            )
        )
    )
    output = tmp_path / "bundle"

    write_instruction_snapshots(
        model.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
    )

    assert (output / "002-a-b/step-0001.ldr").is_file()
    assert (output / "003-a-b/step-0001.ldr").is_file()


def test_flattened_ldr_transforms_all_direct_geometry_types_and_deduplicates_mpd(
    tmp_path: Path,
) -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("geometry.ldr", x=10),
                _piece("geometry.ldr", x=30),
                "0 NOFILE",
                "0 FILE geometry.ldr",
                "2 16 0 0 0 1 0 0",
                "3 16 0 0 0 1 0 0 0 1 0",
                "4 16 0 0 0 1 0 0 1 1 0 0 1 0",
                "5 16 0 0 0 1 0 0 0 1 0 1 1 0",
                "0 NOFILE",
            )
        )
    )
    output = tmp_path / "bundle"
    output.mkdir()

    write_instruction_snapshots(
        model.instruction_document(parts=PARTS),
        parts=PARTS,
        output=output,
    )

    ldr = (output / "001-main/step-0001.ldr").read_text(encoding="utf-8")
    assert ldr.count("\n2 ") + ldr.startswith("2 ") == 2
    assert ldr.count("\n3 ") + ldr.startswith("3 ") == 2
    assert ldr.count("\n4 ") + ldr.startswith("4 ") == 2
    assert ldr.count("\n5 ") + ldr.startswith("5 ") == 2
    assert "2 4 10 0 0 11 0 0" in ldr
    mpd = (output / "001-main/step-0001.mpd").read_text(encoding="utf-8")
    assert mpd.count("0 FILE geometry.ldr") == 1


def test_snapshot_cycle_failure_is_atomic(tmp_path: Path) -> None:
    model = parse_model(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("sub.ldr"),
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece("main.ldr"),
                "0 NOFILE",
            )
        )
    )
    output = tmp_path / "bundle"

    with pytest.raises(SubmodelCycleError):
        write_instruction_snapshots(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
        )
    assert not output.exists()


def test_force_validates_generator_ownership_and_file_list(tmp_path: Path) -> None:
    model = parse_model(_piece())
    output = tmp_path / "bundle"
    output.mkdir()
    manifest = output / MANIFEST_NAME
    manifest.write_text(
        json.dumps({"generator": {"name": "someone-else"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not owned"):
        write_instruction_snapshots(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
            force=True,
        )

    manifest.write_text(
        json.dumps(
            {
                "generator": {"name": "pyldraw3"},
                "generated_files": "not-a-list",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid generated_files"):
        write_instruction_snapshots(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
            output=output,
            force=True,
        )


def test_manifest_has_a_fallback_version_when_package_metadata_is_missing() -> None:
    model = parse_model(_piece())

    with patch(
        "ldraw.instruction_artifacts.version",
        side_effect=PackageNotFoundError,
    ):
        manifest = instruction_manifest(
            model.instruction_document(parts=PARTS),
            parts=PARTS,
        )

    assert manifest["generator"] == {"name": "pyldraw3", "version": "unknown"}
