"""Enforce an 80-NLOC budget without allowing existing exceptions to grow."""
# ruff: noqa: INP001

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lizard

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "function_budget.json"
BUDGET = 80


def check(*, root: Path, baseline: Path) -> list[str]:
    """Report over-budget functions and obsolete or growing exceptions."""
    exceptions: dict[str, int] = json.loads(baseline.read_text(encoding="utf-8"))
    active: set[str] = set()
    errors: list[str] = []
    for path in sorted((root / "ldraw").rglob("*.py")):
        for function in lizard.analyze_file(str(path)).function_list:
            key = f"{path.relative_to(root).as_posix()}:{function.name}"
            if function.nloc <= BUDGET:
                continue
            active.add(key)
            ceiling = exceptions.get(key, BUDGET)
            if function.nloc > ceiling:
                errors.append(f"{key}: {function.nloc} NLOC exceeds {ceiling}")
    errors.extend(
        f"{key}: remove obsolete exception"
        for key in sorted(exceptions.keys() - active)
    )
    return errors


def main() -> int:
    """Run the production-function size gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    errors = check(root=args.root, baseline=args.baseline)
    for error in errors:
        print(error)
    if not errors:
        print(
            f"Production functions meet the {BUDGET}-NLOC budget "
            "and recorded exceptions."
        )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
