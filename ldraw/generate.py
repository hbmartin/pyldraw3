"""LDraw library parts.lst generation functionality."""

import re
from pathlib import Path

FORMAT_STRING = "{filename:<30} {description}"
alphanum = re.compile(r"[\W_]+", re.UNICODE)
num = re.compile(r"\D", re.UNICODE)


def _line_format(**kwargs):
    return FORMAT_STRING.format(**kwargs)


def _do_sort(li, mode):
    def cmpkey1(row):
        return alphanum.sub("", row[mode]).lower()

    def cmpkey2(row):
        return _line_format(**row)

    li.sort(key=cmpkey2)
    li.sort(key=cmpkey1)


def get_parts_lst(parts_dir: Path, mode: str) -> list[dict]:
    """Generate a list of parts from the parts directory with metadata."""
    parts = parts_dir.glob("*.dat")

    parts_dict = {"_": [], "~": []}
    parts_lst = []

    for part in parts:
        try:
            with open(part, encoding="utf-8") as part_file:
                header = part_file.readline()
                header_description = header[2:]
                if "~Moved" in header:
                    continue
                row = {
                    "filename": part.name,
                    "number": part.stem,
                    "description": header_description,
                }

                if "_" in header_description:
                    parts_dict["_"].append(row)
                elif "~" in header_description:
                    parts_dict["~"].append(row)
                else:
                    parts_lst.append(row)
        except UnicodeDecodeError:
            # ignore non-utf-8 files
            continue

    _do_sort(parts_lst, mode)
    _do_sort(parts_dict["_"], mode)
    _do_sort(parts_dict["~"], mode)

    parts_lst.extend(parts_dict["_"])
    parts_lst.extend(parts_dict["~"])

    return parts_lst


def generate_parts_lst(mode: str, version_dir: Path):
    """Generate a parts.lst file from the parts directory in an LDraw version."""
    parts_lst_path = version_dir / "ldraw" / "parts.lst"
    parts_folder_path = version_dir / "ldraw" / "parts"
    if parts_lst_path.exists():
        parts_lst_path.rename(parts_lst_path.with_suffix(".old"))

    parts_lst = get_parts_lst(parts_folder_path, mode)

    lines = [_line_format(**row) for row in parts_lst]
    parts_lst_path.write_text("\r\n".join(lines))
