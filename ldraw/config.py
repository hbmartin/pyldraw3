"""takes care of reading and writing a configuration in config.yml"""

import argparse
import os

import yaml

from ldraw import download
from ldraw.dirs import get_cache_dir, get_config_dir, get_data_dir

CONFIG_FILE = os.path.join(get_config_dir(), "config.yml")


def is_valid_config_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist!" % arg)
    else:
        try:
            with open(arg) as f:
                result = yaml.load(f, Loader=yaml.SafeLoader)
                assert result is not None
            return arg
        except:
            parser.error("%s Doesn't look like a YAML file" % arg)


parser = argparse.ArgumentParser()
parser.add_argument("--config", type=lambda x: is_valid_config_file(parser, x))


def get_config(config_file: str | None = None) -> str:
    if config_file is None:
        args, unknown = parser.parse_known_args()
        return args.config if args.config is not None else CONFIG_FILE
    return config_file


class Config:
    ldraw_library_path: str
    generated_path: str

    def __init__(
        self,
        ldraw_library_path: str | None = None,
        generated_path: str | None = None,
    ):
        self.ldraw_library_path = (
            ldraw_library_path
            if ldraw_library_path is not None
            else os.path.join(get_cache_dir(), "complete")
        )
        self.generated_path = (
            generated_path
            if generated_path is not None
            else os.path.join(get_data_dir(), "generated")
        )

    @classmethod
    def load(cls, config_file=None):
        config_path = get_config(config_file)

        try:
            with open(config_path) as config_file:
                cfg = yaml.load(config_file, Loader=yaml.SafeLoader)
                return cls(
                    ldraw_library_path=cfg.get("ldraw_library_path"),
                    generated_path=cfg.get("generated_path"),
                )
        except FileNotFoundError:
            return cls()

    def __str__(self):
        return f"Config({self.ldraw_library_path=}, {self.generated_path=})"

    def write(self, config_file=None):
        """Write the config to config.yml"""
        config_path = get_config(config_file=config_file)

        with open(config_path, "w") as config_file:
            written = {}
            if self.ldraw_library_path is not None:
                written["ldraw_library_path"] = self.ldraw_library_path
            if self.generated_path is not None:
                written["generated_path"] = self.generated_path
            yaml.dump(written, config_file)


def use(version, config=None):
    cache_ldraw = get_cache_dir()
    ldraw_library_path = os.path.join(cache_ldraw, version)
    if not os.path.exists(ldraw_library_path):
        print("downloading that version to use...")
        download(version)
    if config is None:
        config = Config.load()
    config.ldraw_library_path = ldraw_library_path
    return config
