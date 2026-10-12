"""The production size gate rejects new functions, growth, and stale exceptions."""

import json
from pathlib import Path

import lizard

from scripts.check_function_budget import check


def test_budget_rejects_new_long_function(tmp_path: Path) -> None:
    (tmp_path / "ldraw").mkdir()
    source = tmp_path / "ldraw" / "example.py"
    source.write_text(
        "def production():\n" + "    value = 0\n" * 100 + "    return value\n"
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    assert "exceeds 80" in check(root=tmp_path, baseline=baseline)[0]


def test_existing_budget_cannot_grow_and_must_be_removed(tmp_path: Path) -> None:
    (tmp_path / "ldraw").mkdir()
    source = tmp_path / "ldraw" / "example.py"
    text = "def production():\n" + "    value = 0\n" * 100 + "    return value\n"
    source.write_text(text)
    measured = lizard.analyze_file(str(source)).function_list[0].nloc
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"ldraw/example.py:production": measured}))
    assert check(root=tmp_path, baseline=baseline) == []
    source.write_text(
        text.replace("    return value", "    value += 1\n    return value")
    )
    assert f"exceeds {measured}" in check(root=tmp_path, baseline=baseline)[0]
    source.write_text("def production():\n    return 1\n")
    assert check(root=tmp_path, baseline=baseline) == [
        "ldraw/example.py:production: remove obsolete exception"
    ]
