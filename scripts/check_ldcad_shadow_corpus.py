"""Opt-in compatibility check against the pinned official shadow corpus."""  # noqa: INP001

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from ldraw.connection_metadata import LDCadShadowLibrary

REPOSITORY = "https://github.com/RolandMelkert/LDCadShadowLibrary.git"
PINNED_COMMIT = "15aa1e718b6a8da37d24fc7af5e52e262c041bfb"
_COMMAND = re.compile(r"^\s*0\s+!LDCAD\s+(SNAP_\w+)\b(.*)$", re.IGNORECASE)
_OPTION = re.compile(r"\[([A-Za-z][A-Za-z0-9_]*)=")
_KNOWN_OPTIONS = {
    "SNAP_CLEAR": frozenset({"id"}),
    "SNAP_CLP": frozenset(
        {
            "center",
            "gender",
            "group",
            "length",
            "mirror",
            "ori",
            "pos",
            "radius",
            "scale",
            "slide",
        },
    ),
    "SNAP_CYL": frozenset(
        {
            "caps",
            "center",
            "gender",
            "grid",
            "group",
            "id",
            "mirror",
            "ori",
            "pos",
            "scale",
            "secs",
            "slide",
        },
    ),
    "SNAP_FGR": frozenset(
        {
            "center",
            "gender",
            "genderofs",
            "group",
            "id",
            "mirror",
            "ori",
            "pos",
            "radius",
            "scale",
            "seq",
        },
    ),
    "SNAP_GEN": frozenset(
        {
            "bounding",
            "gender",
            "group",
            "id",
            "match",
            "mirror",
            "ori",
            "placement",
            "pos",
            "scale",
        },
    ),
    "SNAP_INCL": frozenset({"grid", "id", "ori", "pos", "ref", "scale", "slide"}),
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="Use an existing checkout instead of fetching the pinned commit.",
    )
    return parser.parse_args()


def _checkout(destination: Path) -> None:
    if (git := shutil.which("git")) is None:
        message = "git is required to fetch the LDCad shadow corpus"
        raise RuntimeError(message)
    subprocess.run(  # noqa: S603
        (git, "clone", "--quiet", REPOSITORY, str(destination)),
        check=True,
    )
    subprocess.run(  # noqa: S603
        (git, "-C", str(destination), "checkout", "--quiet", PINNED_COMMIT),
        check=True,
    )


def _check(root: Path) -> int:
    library = LDCadShadowLibrary(root)
    command_counts: Counter[str] = Counter()
    options: defaultdict[str, set[str]] = defaultdict(set)
    diagnostics: Counter[str] = Counter()
    file_count = 0
    feature_count = 0
    for path in sorted(root.rglob("*.dat")):
        file_count += 1
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if (match := _COMMAND.match(line)) is None:
                continue
            command = match.group(1).upper()
            command_counts[command] += 1
            options[command].update(
                option.casefold() for option in _OPTION.findall(match.group(2))
            )
        result = library.connections_for(path.relative_to(root).as_posix())
        feature_count += len(result.features)
        diagnostics.update(item.code.value for item in result.diagnostics)
    new_commands = sorted(set(command_counts) - set(_KNOWN_OPTIONS))
    new_options = {
        command: sorted(values - _KNOWN_OPTIONS.get(command, frozenset()))
        for command, values in options.items()
        if values - _KNOWN_OPTIONS.get(command, frozenset())
    }
    print(f"commit: {PINNED_COMMIT}")
    print(f"documents: {file_count}")
    print(f"normalized features: {feature_count}")
    print(f"commands: {dict(sorted(command_counts.items()))}")
    print(f"diagnostics: {dict(sorted(diagnostics.items()))}")
    print(f"new commands: {new_commands}")
    print(f"new options: {new_options}")
    return int(bool(new_commands or new_options))


def main() -> int:
    """Run the pinned corpus check and return nonzero for newly observed forms."""
    args = _arguments()
    if args.source is not None:
        return _check(args.source.expanduser().resolve())
    with TemporaryDirectory(prefix="pyldraw3-shadow-") as temporary:
        root = Path(temporary) / "LDCadShadowLibrary"
        _checkout(root)
        return _check(root)


if __name__ == "__main__":
    raise SystemExit(main())
