#!/usr/bin/env python
"""Check pyldraw3 round-trip fidelity against a corpus of real LDraw files.

For every ``.ldr``/``.mpd`` file in a corpus directory (see
``scripts/fetch_omr_corpus.py``) this verifies, in order:

- L0 parse: the file parses at all.
- L1 idempotence (hard): ``parse(serialize(model))`` serializes to the
  same text.
- L2 semantics (hard): reparsing preserves submodel structure, object
  counts, piece tuples, and header values.
- L3 text (informational): after canonicalizing both sides line-by-line,
  residual differences are classified into known-lossy buckets
  (``0 NOFILE`` normalization, inter-section junk, blank lines, preamble
  relocation). Anything unexplained fails the file — that is the real
  fidelity signal.

Exit codes: 0 all files pass, 1 any failure, 2 corpus missing/empty.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections import Counter
from pathlib import Path

from ldraw.errors import PartError
from ldraw.model import Model, parse_model, read_model
from ldraw.part import parse_ldraw_line
from ldraw.utils import ldraw_file_name

KNOWN_LOSSY_NOTE = "known-lossy"


def is_nofile(line: str) -> bool:
    """Return whether the line is a ``0 NOFILE`` command."""
    match line.split(maxsplit=2):
        case ["0", keyword, *_] if keyword.upper() == "NOFILE":
            return True
        case _:
            return False


def canonical_line(line: str) -> str | None:
    """Reformat one line the way the serializer would, or None to drop it."""
    if not line.strip():
        return None
    try:
        parsed = parse_ldraw_line(line)
    except (PartError, ValueError):
        return line.strip()
    if parsed is None:
        return None
    return parsed.to_ldraw()


def _segment_original(text: str, buckets: Counter[str]) -> list[str]:
    """Drop inter-section junk and relocate preamble the way the parser does."""
    kept: list[str] = []
    preamble: list[str] = []
    seen_file = False
    dropping_junk = False
    for raw in text.splitlines():
        if ldraw_file_name(raw) is not None:
            dropping_junk = False
            kept.append(raw)
            if not seen_file:
                seen_file = True
                buckets["preamble-moved"] += len([p for p in preamble if p.strip()])
                kept.extend(preamble)
                preamble.clear()
            continue
        if is_nofile(raw):
            buckets["nofile-normalization"] += 1
            dropping_junk = True
            continue
        if dropping_junk:
            if raw.strip():
                buckets["inter-section-junk"] += 1
            continue
        (kept if seen_file else preamble).append(raw)
    return [*preamble, *kept] if not seen_file else kept


def _canonical_lines(
    lines: list[str],
    buckets: Counter[str],
    *,
    count_blanks: bool,
) -> list[str]:
    """Reformat lines the way the serializer would, tallying dropped ones."""
    result: list[str] = []
    for raw in lines:
        if is_nofile(raw):
            buckets["nofile-normalization"] += 1
            continue
        canonical = canonical_line(raw)
        if canonical is None:
            if count_blanks and not raw.strip():
                buckets["blank-lines"] += 1
            continue
        result.append(canonical)
    return result


def model_summary(model: Model) -> tuple:
    """Summarize one model section for semantic comparison."""
    return (
        Counter(type(obj).__name__ for obj in model.objects),
        [
            (piece.colour.code, piece.colour.rgb, piece.reference)
            for piece in model.pieces
        ],
        (
            model.description,
            model.header_name,
            model.author,
            model.ldraw_org,
            model.license,
            model.bfc,
        ),
    )


def document_summary(model: Model) -> tuple:
    """Summarize a whole document (root plus submodels)."""
    return (
        model_summary(model),
        {key: model_summary(sub) for key, sub in model.submodels.items()},
    )


def _text_fidelity(path: Path, serialized: str, *, verbose: bool) -> tuple[bool, str]:
    """L3: diff canonicalized original vs serialized text."""
    buckets: Counter[str] = Counter()
    original_lines = _canonical_lines(
        _segment_original(path.read_text(encoding="utf-8-sig"), buckets),
        buckets,
        count_blanks=True,
    )
    serialized_lines = _canonical_lines(
        serialized.splitlines(),
        buckets,
        count_blanks=False,
    )
    diff = list(
        difflib.unified_diff(original_lines, serialized_lines, lineterm="", n=0),
    )
    if diff:
        report = f"FAIL {path.name}: L3 {len(diff)} unexplained diff line(s)"
        if verbose:
            report += "\n" + "\n".join(f"    {line}" for line in diff[:40])
        return False, report
    if nonzero := {key: count for key, count in buckets.items() if count}:
        detail = ", ".join(f"{key} x{count}" for key, count in sorted(nonzero.items()))
        return True, f"PASS {path.name} ({KNOWN_LOSSY_NOTE}: {detail})"
    return True, f"PASS {path.name}"


def check_file(path: Path, *, verbose: bool) -> tuple[bool, str]:
    """Run all four fidelity levels on one file; return (passed, report)."""
    try:
        model = read_model(path)
    except (PartError, ValueError) as exc:
        return False, f"FAIL {path.name}: L0 parse error: {exc}"

    serialized = model.to_ldraw()
    try:
        reparsed = parse_model(serialized, name=model.name)
    except (PartError, ValueError) as exc:
        return False, f"FAIL {path.name}: L1 reparse error: {exc}"
    if reparsed.to_ldraw() != serialized:
        return False, f"FAIL {path.name}: L1 serialization is not idempotent"

    if document_summary(reparsed) != document_summary(model):
        return False, f"FAIL {path.name}: L2 semantic mismatch after round-trip"

    return _text_fidelity(path, serialized, verbose=verbose)


def validation_report(path: Path, parts: object) -> str:
    """Return an error/warning count line for one file."""
    from ldraw.validation import Severity, iter_ldr_issues  # noqa: PLC0415

    issues = list(iter_ldr_issues(path, parts))  # type: ignore[arg-type]
    errors = sum(1 for issue in issues if issue.severity is Severity.ERROR)
    warnings = len(issues) - errors
    return f"    validate: {errors} error(s), {warnings} warning(s)"


def _load_parts_for_validation() -> object:
    from ldraw.catalog import load_parts  # noqa: PLC0415
    from ldraw.config import Config  # noqa: PLC0415

    config = Config.load()
    parts_lst = Path(config.ldraw_library_path) / "ldraw" / "parts.lst"
    if not parts_lst.exists():
        print("note: no parts library configured; validation is syntax-only")
        return None
    return load_parts(parts_lst, config.generated_path)


def main(argv: list[str] | None = None) -> int:
    """Check every corpus file and print a summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="Directory of .ldr/.mpd files.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print unexplained diff hunks.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Also run the ldraw validator against the local parts library.",
    )
    args = parser.parse_args(argv)

    files = sorted(
        path for pattern in ("*.ldr", "*.mpd") for path in args.corpus.glob(pattern)
    )
    if not files:
        print(f"no .ldr/.mpd files found in {args.corpus}")
        return 2

    parts = _load_parts_for_validation() if args.validate else None
    passed = 0
    for path in files:
        ok, report = check_file(path, verbose=args.verbose)
        print(report)
        if args.validate:
            print(validation_report(path, parts))
        passed += ok

    print(f"{passed}/{len(files)} files round-trip cleanly")
    return 0 if passed == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
