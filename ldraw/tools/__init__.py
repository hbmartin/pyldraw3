"""Some tools to convert ldr to other formats."""

import argparse
import os
import sys

from ldraw import LibraryImporter
from ldraw.config import Config
from ldraw.geometry import CoordinateSystem, Vector
from ldraw.parts import Part, PartError, Parts


def widthxheight(input_str):
    """Parse widthxheight image size."""
    image_dimensions = input_str.split("x")
    if len(image_dimensions) != 2:
        raise argparse.ArgumentTypeError("Expecting widthxheight")
    return list(map(int, image_dimensions))


def vector_position(input_str):
    """Parse comma separated vector."""
    position = input_str.split(",")
    if len(position) != 3:
        raise argparse.ArgumentTypeError(
            "Expecting comma-separated elements for the position",
        )
    return Vector(*map(float, position))


def get_model(config, ldraw_model_file):
    """ " get model from ldraw path."""
    ldraw_library_path = config.ldraw_library_path
    parts_lst = os.path.join(ldraw_library_path, "ldraw", "parts.lst")
    parts = Parts(parts_lst)
    try:
        model = Part(file=ldraw_model_file)
    except PartError:
        sys.stderr.write("Failed to read LDraw file: %s\n" % ldraw_model_file)
        sys.exit(1)
    return model, parts


UP_DIRECTION = Vector(0, -1.0, 0)


def get_coordinate_system(camera_position, look_at_position):
    """ " get coordinate system of the view."""
    system = CoordinateSystem()
    system.z = camera_position - look_at_position
    system.z.norm()
    system.x = UP_DIRECTION.cross(system.z)
    if abs(system.x) == 0.0:
        system.x = system.z.cross(Vector(1.0, 0, 0))
    system.x.norm()
    system.y = system.z.cross(system.x)
    return system


def verify_camera_look_at(camera_position, look_at_position):
    """Verify that the camera and look_at positions are valid."""
    if camera_position == look_at_position:
        sys.stderr.write("Camera and look-at positions are the same.\n")
        sys.exit(1)
