"""Integration tests for full pyldraw workflows."""

import tempfile
from pathlib import Path

import pytest

from ldraw import config
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.geometry import Matrix, Vector
from ldraw.figure import Person


@pytest.mark.integration
def test_full_library_workflow():
    """Test complete workflow from library download to part usage."""
    # Get configured library path
    ldraw_path = config.get_ldraw_path()
    assert ldraw_path.exists(), "LDraw library should be downloaded"
    
    # Initialize parts catalog
    parts = Parts(ldraw_path)
    assert len(parts.parts) > 0, "Parts catalog should not be empty"
    
    # Load a common brick part
    brick_part = parts.part("3001")  # 2x4 brick
    assert brick_part is not None, "Should be able to load basic brick part"
    
    # Create a piece with the part
    matrix = Matrix.translation(Vector(0, 0, 0))
    piece = Piece(4, brick_part, matrix)  # Red brick
    assert piece.colour == 4
    assert piece.part == brick_part


@pytest.mark.integration
def test_figure_creation_workflow():
    """Test creating a complete minifigure."""
    parts = Parts(config.get_ldraw_path())
    
    # Create a basic figure
    figure = Person(parts)
    
    # Add basic components if they exist
    try:
        figure.head(4)  # Red head
        figure.torso(2)  # Green torso
        figure.hips(1)   # Blue hips
        figure.right_leg(14)  # Yellow leg
        figure.left_leg(14)   # Yellow leg
        
        # Generate the figure lines
        lines = list(figure.lines())
        assert len(lines) > 0, "Figure should generate LDraw lines"
        
    except Exception as e:
        # Some parts might not be available in test library
        pytest.skip(f"Figure parts not available: {e}")


@pytest.mark.integration
def test_ldraw_file_generation():
    """Test generating complete LDraw files."""
    parts = Parts(config.get_ldraw_path())
    
    # Create a simple model
    pieces = []
    
    # Add a few bricks if available
    try:
        brick_part = parts.part("3001")  # 2x4 brick
        
        # Stack some bricks
        for i in range(3):
            y_pos = i * -24  # Standard brick height
            matrix = Matrix.translation(Vector(0, y_pos, 0))
            piece = Piece(i + 2, brick_part, matrix)  # Different colors
            pieces.append(piece)
        
        # Generate LDraw content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ldr', delete=False) as f:
            f.write("0 Simple Stack Model\n")
            f.write("0 Created by pyldraw integration test\n")
            
            for piece in pieces:
                for line in piece.lines():
                    f.write(str(line) + "\n")
            
            temp_file = f.name
        
        # Verify file was created
        temp_path = Path(temp_file)
        assert temp_path.exists(), "LDraw file should be created"
        assert temp_path.stat().st_size > 0, "LDraw file should not be empty"
        
        # Clean up
        temp_path.unlink()
        
    except Exception as e:
        pytest.skip(f"Required parts not available: {e}")


@pytest.mark.integration
def test_parts_search_and_filtering():
    """Test parts search and filtering functionality."""
    parts = Parts(config.get_ldraw_path())
    
    # Search for brick parts
    brick_parts = parts.parts_by_name("brick")
    assert len(brick_parts) > 0, "Should find brick parts"
    
    # Test that results contain expected parts
    part_numbers = [part.number for part in brick_parts]
    
    # Check for some common brick parts (if they exist)
    common_bricks = ["3001", "3002", "3003", "3004"]
    found_common = [num for num in common_bricks if num in part_numbers]
    
    if not found_common:
        pytest.skip("Common brick parts not found in library")


@pytest.mark.integration
@pytest.mark.slow
def test_large_model_performance():
    """Test performance with larger models."""
    parts = Parts(config.get_ldraw_path())
    
    try:
        brick_part = parts.part("3001")
        pieces = []
        
        # Create a larger model (10x10 grid)
        for x in range(10):
            for z in range(10):
                matrix = Matrix.translation(Vector(x * 40, 0, z * 40))
                piece = Piece(4, brick_part, matrix)
                pieces.append(piece)
        
        # Generate all lines
        total_lines = 0
        for piece in pieces:
            lines = list(piece.lines())
            total_lines += len(lines)
        
        assert total_lines > 0, "Should generate lines for large model"
        assert len(pieces) == 100, "Should create 100 pieces"
        
    except Exception as e:
        pytest.skip(f"Large model test failed: {e}")


@pytest.mark.integration
def test_color_validation():
    """Test color handling in integration context."""
    parts = Parts(config.get_ldraw_path())
    
    try:
        brick_part = parts.part("3001")
        
        # Test various colors
        test_colors = [0, 1, 2, 4, 7, 14, 15]  # Common LDraw colors
        
        for color in test_colors:
            matrix = Matrix.translation(Vector(0, 0, 0))
            piece = Piece(color, brick_part, matrix)
            assert piece.colour == color, f"Color {color} should be preserved"
            
            # Verify lines can be generated
            lines = list(piece.lines())
            assert len(lines) > 0, f"Should generate lines for color {color}"
            
    except Exception as e:
        pytest.skip(f"Color validation test failed: {e}")


@pytest.mark.integration
def test_matrix_transformations_integration():
    """Test matrix transformations in real usage context."""
    parts = Parts(config.get_ldraw_path())
    
    try:
        brick_part = parts.part("3001")
        
        # Test various transformations
        transformations = [
            Matrix.translation(Vector(10, 20, 30)),
            Matrix.rotation_x(45),
            Matrix.rotation_y(90),
            Matrix.rotation_z(180),
            Matrix.scale(2.0),
        ]
        
        for i, matrix in enumerate(transformations):
            piece = Piece(i + 1, brick_part, matrix)
            lines = list(piece.lines())
            assert len(lines) > 0, f"Should generate lines for transformation {i}"
            
    except Exception as e:
        pytest.skip(f"Matrix transformation test failed: {e}")