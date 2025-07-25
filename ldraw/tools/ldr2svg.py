#!/usr/bin/env python

"""ldr2svg.py - An LDraw to SVG convertor tool.

Copyright (C) 2010 David Boddie <david@boddie.org.uk>

This file is part of the ldraw Python package.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import argparse

from ldraw.config import Config
from ldraw.tools import (
    get_coordinate_system,
    get_model,
    vector_position,
    verify_camera_look_at,
    widthxheight,
)


def main():
    """ldr2svg main function."""
    description = """Converts the LDraw file to a SVG file.
    
The viewport size is specified as a pair of floating point numbers representing
lengths in LDraw scene coordinates separated by an \"x\" character.

The camera and look-at positions are x,y,z argument in LDraw scene coordinates
where each coordinate should be specified as a floating point number.

The optional sky background colour is an SVG colour, either specified as
#rrggbb or as a named colour.

"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("ldraw_file", type=argparse.FileType(mode="r"))
    parser.add_argument("svg_file", type=argparse.FileType(mode="w"))
    parser.add_argument("viewport_size", type=widthxheight)
    parser.add_argument("camera_position", type=vector_position)
    parser.add_argument(
        "--look_at_position",
        type=vector_position,
        required=False,
        default=vector_position("0,0,0"),
    )
    parser.add_argument("--sky")

    args = parser.parse_args()
    from ldraw.writers.svg import SVGArgs

    svg_args = SVGArgs(
        args.viewport_size[0],
        args.viewport_size[1],
        background_colour=args.background_colour,
    )

    config = Config.load()

    ldr2svg(
        config,
        args.ldraw_file,
        args.svg_file,
        args.camera_position,
        args.look_at_position,
        svg_args,
    )


def ldr2svg(
    config,
    ldraw_model_file,
    svg_path,
    camera_position,
    look_at_position,
    svg_args,
):  # pylint: disable=too-many-arguments
    """ldr2svg actual implementation."""
    verify_camera_look_at(camera_position, look_at_position)

    model, parts = get_model(config, ldraw_model_file)

    system = get_coordinate_system(camera_position, look_at_position)

    with open(svg_path, "w") as svg_file:
        from ldraw.writers.svg import SVGWriter

        writer = SVGWriter(camera_position, system, parts)
        writer.write(model, svg_file, svg_args)


if __name__ == "__main__":
    main()
