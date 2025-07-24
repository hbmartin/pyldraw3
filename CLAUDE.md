# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`pyldraw` is a Python package for creating LDraw format files - a standard used by CAD applications that create LEGO models. The package provides facilities to create LDraw scene descriptions using Python and includes tools for converting LDraw files to various formats (PNG, POV-Ray, SVG, inventory).

## Development Commands

This project uses uv for dependency management and packaging.
Before running any commands be sure sure to active the venv `source .venv/bin/activate`


### Setup and Installation
```bash
uv sync                    # Install dependencies
uv run ldraw download --version 2018-02 --yes  # Download LDraw library
uv run ldraw generate --yes   # Generate ldraw.library package
```

### Testing
```bash
uv run pytest                 # Run all tests
uv run pytest --cov=ldraw     # Run tests with coverage
uv run pytest --integration   # Run integration tests
```

### Code Quality
```bash
uv run black .               # Format code (Black is configured)
```

### Building
```bash
uv build                     # Build package
```

## Architecture

### Core Components

1. **CLI Interface (`ldraw/cli.py`)**: Main command-line interface with commands:
   - `ldraw download` - Download LDraw parts libraries
   - `ldraw use` - Select which library version to use
   - `ldraw generate` - Generate Python modules from LDraw library

2. **Dynamic Library Generation (`ldraw/generation/`)**: 
   - Generates Python modules from LDraw parts libraries
   - Creates `ldraw.library.*` namespace with parts organized by categories
   - Uses templates in `ldraw/templates/` with Mustache templating

3. **Import System (`ldraw/imports.py`)**:
   - Custom meta path hook (`LibraryImporter`) for dynamic imports
   - Enables importing LDraw parts as Python modules

4. **Writers (`ldraw/writers/`)**:
   - `povray.py` - Export to POV-Ray format
   - `png.py` - Render to PNG images  
   - `svg.py` - Export to SVG vector format
   - `common.py` - Shared writer functionality

5. **Tools (`ldraw/tools/`)**:
   - `ldr2pov` - Convert LDraw to POV-Ray
   - `ldr2png` - Convert LDraw to PNG
   - `ldr2svg` - Convert LDraw to SVG
   - `ldr2inv` - Generate bill of materials/inventory

### Key Classes

- `Parts` (`ldraw/parts.py`) - Manages parts catalog and loading
- `Piece` (`ldraw/pieces.py`) - Represents individual LEGO pieces in models
- `Figure` (`ldraw/figure.py`) - High-level minifigure construction
- Geometry classes (`ldraw/geometry.py`) - Matrix operations and 3D math

### Configuration

- Uses OS-dependent cache directories for generated libraries
- Configuration stored in YAML format
- Parts libraries cached locally after download

## Development Notes

- The project supports Python 3.11+
- Uses uv for dependency management instead of traditional pip/setuptools
- Generated `ldraw.library.*` modules are cached and should be regenerated when changing library versions
- Integration tests are marked with `@pytest.mark.integration` and require `--integration` flag
- Code style uses Black formatter and ruff linter

## Python Practices
- Always use or add type hints
- Prefer @dataclasses where applicable
- Always prefer f-string over string formatting or concatentation
- Use async generators and comprehensions when they might provide benefits
- Use underscores in large numeric literals
- Use walrus assignment := where applicable
- Prefer to use named arguments when calling a method with more than one argument
- Use "list" instead of "List" and "dict" instead of "Dict" and "|" instead of "Union" for types
- Use "Self" for applicable types
- Use Structural Pattern Matching (match...case) where applicable
