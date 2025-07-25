import logging

import click
import yaml

from ldraw import generate as do_generate
from ldraw.config import Config
from ldraw.downloads import download as do_download
from ldraw.generation.exceptions import UnwritableOutput


@click.group()
@click.option("--debug", is_flag=True)
def main(debug=False):
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
@click.option(
    "--yes",
    is_flag=True,
    help="use as the ldraw.library location for subsequent uses of pyLdraw",
)
def generate(force, yes):
    rw_config = Config.load()

    try:
        do_generate(rw_config, force, False)
    except UnwritableOutput:
        print(
            f"{rw_config.generated_path} is unwritable, select another output directory",
        )


@main.command(help="show pyldraw current config")
def config():
    config = Config.load()
    print(yaml.dump(config.__dict__))


@main.command(help="download LDraw library files")
def download():
    release_id = do_download()
    logging.debug(f"Downloaded LDraw library files for release {release_id}")


if __name__ == "__main__":
    main()
