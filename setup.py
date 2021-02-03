#! /usr/bin/env python
# coding=utf-8
import codecs
from distutils.core import setup

from setuptools import find_packages


def get_readme():
    return codecs.open("README.rst", encoding="utf-8").read()


setup(
    name="pyldraw",
    description="A package for working with LDraw format files.",
    long_description=get_readme(),
    author=" David Boddie <david@boddie.org.uk>",
    maintainer="Matthieu Berthomé <rienafairefr@gmail.com>",
    author_email="rienairefr@gmail.com, david@boddie.org.uk",
    version="0.0.0",
    python_requires=">=3.5",
    packages=find_packages(),
    package_data={"ldraw": ["templates/*.mustache"]},
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    entry_points={
        "console_scripts": [
            "ldr2inv = ldraw.tools.ldr2inv:main",
            "ldr2png = ldraw.tools.ldr2png:main",
            "ldr2pov = ldraw.tools.ldr2pov:main",
            "ldr2svg = ldraw.tools.ldr2svg:main",
            "ldraw = ldraw.cli:main"
        ],
    },
    install_requires=[
        "appdirs",
        "numpy",
        "pymklist",
        "pystache",
        "attrdict",
        "progress",
        "PyYaml",
        "Pillow",
    ],
)
