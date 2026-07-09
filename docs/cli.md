# CLI Reference

The `ldraw` executable downloads LDraw libraries, generates importable Python
modules, queries parts, validates model files, and exports bills of materials.

```text
usage: ldraw [-h] command ...

Download the LDraw parts library and generate the ldraw.library Python
modules.

positional arguments:
  command
    download  Download and unpack an LDraw parts library release.
    generate  Generate the ldraw.library modules from the downloaded library.
    parts     Query the parts catalog.
    validate  Validate an LDraw file (.ldr, .mpd, or .dat).
    bom       Print a bill of materials for an LDraw model file.
    stubs     Write a type-stub package for ldraw.library into your project.
    config    Print the current configuration.
    version   Print the installed pyldraw3 version.

options:
  -h, --help  show this help message and exit
```

## Commands

- `ldraw download [--version VERSION] [--yes]` downloads and unpacks an
  LDraw release. The default version is `complete`.
- `ldraw generate [--yes] [--force]` regenerates `ldraw.library.*` from the
  currently configured release. `--force` regenerates even when already up to
  date.
- `ldraw parts search TERM [--limit N]` searches the catalog by description
  or code substring. It exits with code 1 when nothing matches.
- `ldraw parts info CODE` shows a part's description, category, file path, and
  the generated-library import to use.
- `ldraw validate FILE [--strict]` lints `.ldr`, `.mpd`, and `.dat` files.
  Malformed lines, unknown parts, and unknown colour codes are errors.
  Suspect matrices, legacy dithered colours, and unknown meta-commands are
  warnings. `--strict` makes warnings fail.
- `ldraw bom FILE [--format table|csv|json] [-o OUT]` prints a bill of
  materials counted by part and colour, with submodels expanded.
- `ldraw stubs [--out PATH]` writes an `ldraw-stubs/` PEP 561 stub package for
  IDE autocompletion of generated `ldraw.library.*` imports.
- `ldraw config` prints the current configuration as YAML.
- `ldraw version` prints the installed `pyldraw3` version.

Run `ldraw <command> --help` for a command's full option list.

## Development Commands

This project uses `uv` for dependency management and packaging.

```bash
uv sync
source .venv/bin/activate
uv run ldraw download --yes
uv run ldraw generate --yes
```

Run tests and checks:

```bash
uv run pytest
uv run pytest --cov=ldraw
uv run pytest --integration
uv run ruff format .
uv run ruff check .
uv build
```

Build and preview documentation:

```bash
uv run zensical serve
uv run zensical build --clean --strict
```

GitHub Pages must use the "GitHub Actions" publishing source. If the
repository remains configured to publish from a branch such as `gh-pages`, the
live site will continue to serve that branch instead of this workflow's
Zensical artifact.
