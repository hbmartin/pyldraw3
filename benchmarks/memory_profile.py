"""Memory profiling script for pyldraw operations."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ldraw import config
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.geometry import Matrix, Vector


@profile
def test_parts_loading():
    """Profile memory usage during parts loading."""
    parts = Parts(config.get_ldraw_path())
    
    # Load various parts to test memory usage
    part_numbers = ["3001", "3002", "3004", "3005", "3022", "3039", "3455"]
    loaded_parts = []
    
    for part_num in part_numbers:
        try:
            part = parts.part(part_num)
            loaded_parts.append(part)
        except Exception:
            continue
    
    return loaded_parts


@profile
def test_piece_creation():
    """Profile memory usage during piece creation."""
    parts = Parts(config.get_ldraw_path())
    pieces = []
    
    try:
        part = parts.part("3001")
        
        for i in range(100):
            matrix = Matrix.translation(Vector(i, 0, 0))
            piece = Piece(4, part, matrix)  # Red color
            pieces.append(piece)
    except Exception:
        pass
    
    return pieces


@profile
def test_geometry_operations():
    """Profile memory usage during geometry operations."""
    matrices = []
    vectors = []
    
    # Create many matrices and vectors
    for i in range(1000):
        matrix = Matrix.rotation_y(i * 0.1)
        vector = Vector(i, i * 2, i * 3)
        
        # Perform operations
        transformed = matrix.transform_vector(vector)
        inverted = matrix.invert()
        
        matrices.append(inverted)
        vectors.append(transformed)
    
    return matrices, vectors


if __name__ == "__main__":
    print("Starting memory profiling...")
    
    print("\\nProfiling parts loading...")
    parts_result = test_parts_loading()
    
    print("\\nProfiling piece creation...")
    pieces_result = test_piece_creation()
    
    print("\\nProfiling geometry operations...")
    geometry_result = test_geometry_operations()
    
    print("\\nMemory profiling complete!")