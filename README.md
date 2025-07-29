# pyldraw

[![Python package](https://github.com/rienafairefr/python-ldraw/workflows/Python%20package/badge.svg)](https://github.com/rienafairefr/python-ldraw/actions?query=workflow%3A%22Python+package%22)
[![Coverage Status](https://coveralls.io/repos/github/rienafairefr/python-ldraw/badge.svg?branch=master)](https://coveralls.io/github/rienafairefr/python-ldraw?branch=master)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pyldraw.svg)](https://pypi.python.org/pypi/pyldraw)

A modern Python package for creating and manipulating LDraw format files - the standard for CAD applications that create LEGO models.

## Features

- 🧱 **Complete LDraw Support**: Full compatibility with the LDraw standard format
- 🐍 **Pythonic API**: Import LEGO parts directly as Python modules
- 🎨 **Multiple Export Formats**: Convert to PNG, SVG, POV-Ray, and generate inventories
- 📦 **Dynamic Library Generation**: Automatically generate Python modules from LDraw libraries
- 🛠️ **Command Line Tools**: Rich CLI for downloading, managing, and converting models

## Quick Start

### Installation

```bash
pip install pyldraw3
```

### Setup

Activate your virtual environment and set up the LDraw library:

```bash
source .venv/bin/activate
ldraw download --version 2018-02 --yes
ldraw generate --yes
```

### Basic Usage

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
- Modern dependency management with `uv`

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
uv run ldraw download --version 2018-02 --yes
uv run ldraw generate --yes
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

## Command Line Tools

### Core Commands

- `ldraw download` - Download LDraw parts libraries
- `ldraw use` - Select which library version to use  
- `ldraw generate` - Generate Python modules from LDraw library

### Conversion Tools

- `ldr2png` - Convert LDraw files to PNG images
- `ldr2svg` - Convert LDraw files to SVG vector graphics
- `ldr2pov` - Convert LDraw files to POV-Ray scenes
- `ldr2inv` - Generate bill of materials/inventory

### Example Usage

```bash
# Convert a model to different formats
python examples/figures.py > temp.ldr
ldr2pov temp.ldr temp.pov 160.0,80.0,-240.0
ldr2png temp.ldr output.png
ldr2svg temp.ldr output.svg
ldr2inv temp.ldr inventory.txt
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

## Examples

Check the `examples/` directory for sample scripts demonstrating various features:

```bash
# Run an example
python examples/figures.py > my_model.ldr
```

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

This project is licensed under the GNU General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.

```
pyldraw, a Python package for creating LDraw format files.
Copyright (C) 2008 David Boddie <david@boddie.org.uk>
Some parts Copyright (C) 2021 Matthieu Berthomé <matthieu@mmea.fr>
Some parts Copyright (C) 2024 Harold Martin <harold.martin@gmail.com>
```

## Trademarks

LDraw is a trademark of the Estate of James Jessiman. LEGO is a registered trademark of the LEGO Group.

## Credits

- **Original Author**: [David Boddie](mailto:david@boddie.org.uk)
- **Maintainer**: [Matthieu Berthomé](mailto:matthieu@mmea.fr)
- **Contributor**: [Harold Martin](mailto:harold.martin@gmail.com)

This repository was extracted from the original Mercurial repository and modernized for current Python practices.