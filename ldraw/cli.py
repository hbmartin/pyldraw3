"""Command-line interface for pyldraw package.

Priamrily responsible for downloading LDraw library files and
generating the ldraw.library modules from them.
"""

import logging

import yaml

from ldraw import generate as do_generate
from ldraw.config import Config
from ldraw.downloads import download as do_download
from ldraw.generation.exceptions import UnwritableOutputError


def generate():
    """Generate the ldraw.library modules from downloaded LDraw parts."""
    rw_config = Config.load()

    try:
        do_generate(config=rw_config)
    except UnwritableOutputError:
        print(
            f"{rw_config.generated_path} is unwritable, select another out directory",
        )


def config():
    """Show pyldraw current configuration settings."""
    config = Config.load()
    print(yaml.dump(config.__dict__))


def download():
    """Download LDraw library files from the official repository."""
    release_id = do_download()
    logging.info(  # noqa: LOG015
        "Downloaded LDraw library files for release %s",
        release_id,
    )


def main():
    """Entry point for the CLI."""
    download()
    generate()


if __name__ == "__main__":
    main()
