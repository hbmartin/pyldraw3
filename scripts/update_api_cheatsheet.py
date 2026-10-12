# ruff: noqa: INP001
"""Refresh only the generated API section of the curated skill cheat sheet."""

from pathlib import Path

from ldraw.api import public_symbols

START = "<!-- public-api:start -->"
END = "<!-- public-api:end -->"


def main() -> None:
    """Write names from the same registry used by inventory and reference docs."""
    path = (
        Path(__file__).resolve().parents[1]
        / "skills/lego-model-builder/references/api-cheatsheet.md"
    )
    text = path.read_text(encoding="utf-8")
    section = "\n".join(f"- `{module}.{name}`" for module, name in public_symbols())
    generated = f"{START}\n## Public API inventory\n\n{section}\n{END}"
    if START in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        text = f"{before}{generated}{after}"
    else:
        text = f"{text.rstrip()}\n\n{generated}\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
