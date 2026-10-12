# pyldraw3

[![PyPI](https://img.shields.io/pypi/v/pyldraw3.svg)](https://pypi.org/project/pyldraw3/)
[![Lint and Test](https://github.com/hbmartin/pyldraw3/actions/workflows/lint-test.yml/badge.svg)](https://github.com/hbmartin/pyldraw3/actions/workflows/lint-test.yml)
[![Codecov](https://codecov.io/gh/hbmartin/pyldraw3/branch/main/graph/badge.svg)](https://codecov.io/gh/hbmartin/pyldraw3)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Formatter: Ruff](https://img.shields.io/badge/formatter-ruff-46a0d9.svg)](https://github.com/astral-sh/ruff)

Create, read, validate, and inspect LEGO models in Python using the LDraw format. Python 3.12–3.14 is supported.

## Quick start

```bash
uv add pyldraw3
```

Build a model directly from LDraw part codes. Construction and file I/O do not require a downloaded parts library:

```python
from pathlib import Path
from ldraw import Matrix, Model, Piece, Vector
from ldraw.units import BRICK_HEIGHT

model = Model(name="scene.ldr")
model.add(Piece.place("3001", colour=4))
model.add(
    Piece.place(
        "3001",
        colour=14,
        position=Vector(0, -BRICK_HEIGHT, 0),
        matrix=Matrix.rotation(y=90),
    )
)
model.save(Path("scene.ldr"))
```

For catalog searches, geometry, and connections, download a library and load it through a session:

```bash
uv run ldraw download --yes
```

```python
from ldraw import LDrawSession

parts = LDrawSession().load()
brick = parts.get_entry_by_description("Brick  1 x  1")
print(brick.code)
print(parts.bounding_box(brick.code))
```

Generated `ldraw.library.*` names remain available after `uv run ldraw generate --yes`.

## Workflows

- [Guide](https://hbmartin.github.io/pyldraw3/guide/): construction, transformations, submodels, geometry, and session setup.
- [CLI reference](https://hbmartin.github.io/pyldraw3/cli/): validation, BOM and inventory comparison, inspection, previews, and instruction exports.
- [API reference](https://hbmartin.github.io/pyldraw3/api/): public types and functions.
- [Examples](https://hbmartin.github.io/pyldraw3/examples/) and [upgrade guides](https://hbmartin.github.io/pyldraw3/upgrading-1.7/).
- [pyldraw3-tui](https://github.com/hbmartin/pyldraw3-tui): interactive catalog browsing and model inspection.

## Development

```bash
uv sync --all-groups --locked
source .venv/bin/activate
uv run pytest
uv run pytest --cov=ldraw --cov-config=pyproject.toml
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_function_budget.py
uv run zensical build --clean --strict
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for integration tests, snapshot regeneration, coverage policy, and performance measurements.

## License

This project is licensed under the GNU General Public License v3.0 or later - see the [license (COPYING)](https://github.com/hbmartin/pyldraw3/blob/main/COPYING) file for details.

```
pyldraw, a Python package for creating LDraw format files.
Copyright (C) 2008 David Boddie <david@boddie.org.uk>
Some parts Copyright (C) 2021 Matthieu Berthomé <matthieu@mmea.fr>
Some parts Copyright (C) 2025 Harold Martin <harold.martin@gmail.com>
```

## Trademarks

LDraw is a trademark of the Estate of James Jessiman. LEGO is a registered trademark of the LEGO Group.

## Credits

- **Original Author**: [David Boddie](mailto:david@boddie.org.uk)
- **Previous Maintainer**: [Matthieu Berthomé](mailto:matthieu@mmea.fr)
- **Current Maintainer**: [Harold Martin](mailto:harold.martin@gmail.com)

This repository was extracted from the original Mercurial repository and modernized for current Python practices.
