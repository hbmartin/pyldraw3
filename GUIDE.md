# PyLDraw3 Onboarding Guide

Welcome to PyLDraw3! This guide will help you get started with creating LEGO models programmatically using Python and the LDraw standard format.

## Table of Contents

- [What is PyLDraw3?](#what-is-pyldraw3)
- [Quick Start](#quick-start)
  - [Installation and Setup](#1-installation-and-setup)
  - [Your First Model](#2-your-first-model)
  - [Understanding the Coordinate System](#3-understanding-the-coordinate-system)
  - [Working with Colors](#4-working-with-colors)
  - [Basic Minifigure](#5-basic-minifigure)
- [Intermediate Concepts](#intermediate-concepts)
  - [Working with Groups](#working-with-groups)
  - [Rotations and Transformations](#rotations-and-transformations)
  - [Advanced Minifigure Positioning](#advanced-minifigure-positioning)
- [Advanced Topics](#advanced-topics)
  - [Scene Composition with Lighting](#scene-composition-with-lighting)
  - [Building Complex Structures](#building-complex-structures)
  - [Working with Different Part Categories](#working-with-different-part-categories)
  - [Best Practices](#best-practices)
  - [Troubleshooting](#troubleshooting)
- [Next Steps](#next-steps)

## What is PyLDraw3?

PyLDraw3 is a Python package that allows you to create LDraw format files - a standard used by CAD applications for LEGO models. With PyLDraw3, you can:

- Build LEGO models using Python code
- Create minifigures with detailed positioning
- Export models to various formats (PNG, POV-Ray, SVG)
- Generate parts inventories
- Work with groups and transformations for complex scenes



## Quick Start

### 1. Installation and Setup

First, ensure you have the package installed and set up your environment:

```bash
# Activate your virtual environment
source .venv/bin/activate

# Install dependencies
uv sync

# Download the LDraw parts library (required)
uv run ldraw download --version 2018-02 --yes

# Generate the Python modules from the LDraw library
uv run ldraw generate --yes
```

### 2. Your First Model

Let's start with a simple example - creating a single LEGO brick:

```python
#!/usr/bin/env python

from ldraw.library.colours import *
from ldraw.library.parts import Brick2X2
from ldraw.pieces import Piece
from ldraw.geometry import Vector, Identity

# Create a simple 2x2 brick
brick = Piece(
    colour=Red,                    # Color of the piece
    position=Vector(0, 0, 0),      # Position (x, y, z)
    matrix=Identity(),             # Rotation matrix (no rotation)
    part=Brick2X2                  # The part to use
)

print(brick)
```

This outputs LDraw format text that can be saved to a `.ldr` file and opened in any LDraw-compatible viewer.

### 3. Understanding the Coordinate System

LDraw uses a specific coordinate system:
- **X-axis**: Left (-) to Right (+)
- **Y-axis**: Top (-) to Bottom (+) 
- **Z-axis**: Front (+) to Back (-)

Positions are measured in LDraw units (LDU), where 1 LDU ≈ 0.4mm in real life.

### 4. Working with Colors

PyLDraw3 provides access to all standard LEGO colors:

```python
from ldraw.library.colours import *

# Common colors
Red, Blue, Yellow, Green, White, Black
Chrome_Silver, Chrome_Gold
Trans_Clear, Trans_Red, Trans_Blue
Dark_Red, Dark_Blue, Light_Grey
```

### 5. Basic Minifigure

Let's create a simple minifigure:

```python
from ldraw.library.colours import *
from ldraw.figure import Person
from ldraw.library.parts.minifig.accessories import HairMale
from ldraw.library.parts.minifig.torsos import Torso

# Create a person
figure = Person()

# Build the minifigure part by part
print(figure.head(Yellow, 35))              # Head with expression
print(figure.hat(Black, HairMale))          # Hair
print(figure.torso(Red, Torso))             # Basic torso
print(figure.hips(Blue))                    # Hip piece
print(figure.left_leg(Blue, 5))             # Left leg with slight bend
print(figure.right_leg(Blue, 20))           # Right leg with more bend
print(figure.left_arm(Red, 0))              # Arms
print(figure.left_hand(Yellow, 0))
print(figure.right_arm(Red, -90))           # Right arm bent
print(figure.right_hand(Yellow, 0))
```

## Intermediate Concepts

### Working with Groups

Groups allow you to organize pieces and apply transformations to multiple pieces at once:

```python
from ldraw.pieces import Group, Piece
from ldraw.geometry import Vector, Identity, YAxis
from ldraw.library.colours import *
from ldraw.library.parts import Brick2X2, Brick1X1

# Create a group
building = Group(Vector(0, 0, 0), Identity())

# Add pieces to the group
Piece(Red, Vector(0, 0, 0), Identity(), Brick2X2, group=building)
Piece(Blue, Vector(0, -24, 0), Identity(), Brick2X2, group=building)
Piece(Yellow, Vector(20, -48, 0), Identity(), Brick1X1, group=building)

# Transform the entire group
building.position = Vector(100, 0, 0)              # Move the group
building.matrix = Identity().rotate(45, YAxis)     # Rotate the group

# Print all pieces (with transformations applied)
for piece in building.pieces:
    print(piece)
```

### Rotations and Transformations

PyLDraw3 uses 3D transformation matrices for positioning and rotating pieces:

```python
from ldraw.geometry import Identity, XAxis, YAxis, ZAxis

# Create rotation matrices
rotation = Identity()
rotation = rotation.rotate(90, YAxis)    # Rotate 90° around Y-axis
rotation = rotation.rotate(45, XAxis)    # Then 45° around X-axis

# Use in a piece
piece = Piece(Red, Vector(0, 0, 0), rotation, Brick2X2)
```

### Advanced Minifigure Positioning

Create more dynamic poses and add accessories:

```python
from ldraw.figure import Person
from ldraw.library.parts.minifig.accessories import ToolMagnifyingGlass
from ldraw.library.parts.minifig.hats import TopHat
from ldraw.library.parts.minifig.heads import HeadWithMonocle_Scar_AndMoustachePattern
from ldraw.library.parts.minifig.torsos import TorsoWithBlackSuit_RedShirt_GoldClaspsPattern

# Create a detective character
detective = Person()
detective.head(Yellow, part=HeadWithMonocle_Scar_AndMoustachePattern)
detective.hat(Black, TopHat)
detective.torso(Black, TorsoWithBlackSuit_RedShirt_GoldClaspsPattern)
detective.left_arm(Black, 70)           # Arm angles in degrees
detective.right_arm(Black, -30)
detective.left_hand(White, 0)
detective.right_hand(White, 0)

# Add a magnifying glass to the right hand
detective.right_hand_item(
    Chrome_Silver, 
    Vector(0, -58, -20),    # Relative position 
    0,                      # Rotation
    ToolMagnifyingGlass
)

detective.hips(Black)
detective.left_leg(Black, 50)           # Leg poses
detective.right_leg(Black, -40)
```

## Advanced Topics

### Scene Composition with Lighting

Add lighting to your scenes for better renders:

```python
from ldraw.pieces import Piece
from ldraw.geometry import Vector, Identity
from ldraw.library.colours import White

# Add lights to illuminate your scene
print(Piece(White, Vector(150, -100, -150), Identity(), "LIGHT"))
print(Piece(White, Vector(-150, -100, -150), Identity(), "LIGHT"))
print(Piece(White, Vector(0, -100, 150), Identity(), "LIGHT"))
```

### Building Complex Structures

Create repetitive structures using loops:

```python
from ldraw.library.parts import Brick2X3, Plate6X6
from ldraw.pieces import Group, Piece

# Build a spiral staircase
stairs = Group()

x, y, z = -120, 144, -160
steps = 5

# Base platform
Piece(Dark_Blue, Vector(x, y, z + 40), Identity(), Plate6X6, group=stairs)

# Create steps
for i in range(steps):
    for pz in range(z, z + 120, 40):
        Piece(
            Dark_Blue, 
            Vector(x + 50 + (i * 40), y - 24 - (i * 24), pz),
            Identity(), 
            Brick2X3, 
            group=stairs
        )

# Duplicate the staircase multiple times with rotation
staircases = 7
for i in range(1, staircases + 1):
    stairs.position = Vector(0, i * (8 + steps * 24), 0)
    stairs.matrix = Identity().rotate(-90 * i, YAxis)
    for piece in stairs.pieces:
        print(piece)
```

### Working with Different Part Categories

The LDraw library organizes parts into categories:

```python
# Minifigure parts
from ldraw.library.parts.minifig.accessories import *
from ldraw.library.parts.minifig.torsos import *
from ldraw.library.parts.minifig.heads import *
from ldraw.library.parts.minifig.hats import *

# Vehicle parts
from ldraw.library.parts import *
# This includes wheels, steering wheels, seats, etc.

# Architectural elements
from ldraw.library.parts import *
# Windows, doors, arches, etc.
```

### Best Practices

1. **Use Groups for Organization**: Group related pieces together for easier manipulation.

2. **Consistent Naming**: Use descriptive variable names for complex models.

3. **Modular Design**: Break complex models into functions that return groups of pieces.

4. **Comment Your Code**: Document the purpose of complex positioning or rotations.

5. **Test Your Models**: Generate LDR files frequently to verify your model looks correct.

6. **Version Control**: Save both your Python source and generated LDR files.

### Troubleshooting

**Part Not Found**: If you get import errors for parts, ensure you've run:
```bash
uv run ldraw generate --yes
```

**Wrong Colors**: Make sure you're importing from `ldraw.library.colours` and using the correct color constants.

**Positioning Issues**: Remember that LDraw Y-axis is inverted (positive Y goes down). Use small incremental changes to fine-tune positions.

**Missing Library**: If parts imports fail, you may need to download a different LDraw library version:
```bash
uv run ldraw download --version [VERSION] --yes
uv run ldraw generate --yes
```

## Next Steps

Now that you understand the basics:

1. Explore the `examples/` directory for more complex model ideas
2. Experiment with the export tools to visualize your creations
3. Try building your own custom minifigures and vehicles
4. Look into the POV-Ray export for high-quality renderings
5. Create your own library of reusable model components

Happy building with PyLDraw3!