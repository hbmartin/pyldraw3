"""Command-line interface for pyldraw package."""

import logging

import click
import yaml

from ldraw import generate as do_generate
from ldraw.config import Config
from ldraw.downloads import download as do_download
from ldraw.generation.exceptions import UnwritableOutputError


@click.group()
@click.option("--debug", is_flag=True)
def main(debug=False):  # noqa: FBT002
    """Provide CLI entry point for pyldraw commands."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)


@main.command(help="generate the ldraw.library modules")
@click.option(
    "--force",
    help="re-generate even if it's apparently not needed",
    required=False,
    is_flag=True,
)
def generate(force):
    """Generate the ldraw.library modules from downloaded LDraw parts."""
    rw_config = Config.load()

    try:
        do_generate(config=rw_config, force=force, warn=False)
    except UnwritableOutputError:
        print(
            f"{rw_config.generated_path} is unwritable, select another out directory",
        )


@main.command(help="show pyldraw current config")
def config():
    """Show pyldraw current configuration settings."""
    config = Config.load()
    print(yaml.dump(config.__dict__))


@main.command(help="download LDraw library files")
def download():
    """Download LDraw library files from the official repository."""
    release_id = do_download()
    logging.info(  # noqa: LOG015
        "Downloaded LDraw library files for release %s",
        release_id,
    )


if __name__ == "__main__":
    main()
