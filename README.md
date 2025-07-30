# pyldraw3

[![PyPI](https://img.shields.io/pypi/v/pyldraw3.svg)](https://pypi.org/project/pyldraw3/)
[![Lint and Test](https://github.com/hbmartin/pyldraw3/actions/workflows/lint-test.yml/badge.svg)](https://github.com/hbmartin/pyldraw3/actions/workflows/lint-test.yml)
[![Coverage Status](https://coveralls.io/repos/github/hbmartin/pyldraw3/badge.svg?branch=main)](https://coveralls.io/github/hbmartin/pyldraw3?branch=main)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/🐧️-black-000000.svg)](https://github.com/psf/black)

A modern Python package for creating and manipulating LDraw format files - the standard for CAD applications that create LEGO models. It is a drop-in replacement for the unmaintained `pyldraw` library.

## Features

- 🧱 **Complete LDraw Support**: Full compatibility with the LDraw standard format
- 🐍 **Pythonic API**: Import LEGO parts directly as Python modules
- 📦 **Dynamic Library Generation**: Automatically generate Python modules from LDraw libraries
- 📜 **Comprehensive Guide**: Jump into example or the quick start below, or read a [detailed usage guide](GUIDE.md)

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
  - [Installation](#installation)
  - [Setup](#setup)
  - [Examples](#examples)
  - [Basic Usage](#basic-usage)


## Quick Start

### Installation

```bash
uv add pyldraw3
```

### Setup

Activate your virtual environment and set up the LDraw library - this will download the LDraw library and create the parts classes:

```bash
source .venv/bin/activate
ldraw
```

### Examples

Check the `examples/` directory for sample scripts demonstrating various features:

```bash
# Run an example
python examples/figures.py > my_model.ldr
```

### Basic Usage

This package allows users to create LDraw scene descriptions using `Piece`s which are `Part`s that have a specific position and orientation.

```python
from ldraw.library.colours import Light_Grey
from ldraw.library.parts.minifig.accessories import Seat2X2
from ldraw.library.parts.bricks import Brick1X2WithClassicSpaceLogoPattern
from ldraw.pieces import Piece
from ldraw.geometry import Vector, Identity

# Create a simple model
rover = group()
Piece(Light_Grey, Vector(-10, -32, -90), Identity(), "3957a", rover)
```

You can also reference parts by their LDraw codes:

```python
from ldraw.parts import Parts

parts = Parts("parts.lst")
cowboy_hat = parts.minifig.hats["Hat Cowboy"]
head = parts.minifig.heads["Head with Solid Stud"]
brick1x1 = parts.others["Brick  1 x  1"]
```

## Requirements

- Python 3.12+

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and packaging.

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/rienafairefr/python-ldraw.git
cd python-ldraw

# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate

# Download and set up LDraw library
uv run ldraw
```

### Development Commands

```bash
# Run tests
uv run pytest                 # All tests
uv run pytest --cov=ldraw     # With coverage
uv run pytest --integration   # Integration tests only

# Code formatting and linting
uv run black .               # Format code
uv run ruff check            # Lint code
uv run ruff check --fix      # Fix linting issues

# Build package
uv build
```

## Architecture

### Core Components

- **CLI Interface** (`ldraw/cli.py`): Command-line interface for library management
- **Dynamic Library Generation** (`ldraw/generation/`): Converts LDraw libraries to Python modules
- **Import System** (`ldraw/imports.py`): Custom meta path hook for dynamic imports
- **Writers** (`ldraw/writers/`): Export to various formats (PNG, SVG, POV-Ray)
- **Tools** (`ldraw/tools/`): Command-line conversion utilities

### Key Classes

- `Parts` - Manages parts catalog and loading
- `Piece` - Represents individual LEGO pieces in models  
- `Figure` - High-level minifigure construction
- Geometry classes - Matrix operations and 3D mathematics

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and ensure they pass (`uv run pytest`)
5. Format your code (`uv run black .`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 or later - see the [license (COPYING)](COPYING) file for details.

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