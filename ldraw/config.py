"""takes care of reading and writing a configuration in config.yml."""

import argparse
import os

import yaml

from ldraw.dirs import get_cache_dir, get_config_dir, get_data_dir
from ldraw.errors import InvalidConfigFileError

CONFIG_FILE = os.path.join(get_config_dir(), "config.yml")


def is_valid_config_file(parser, arg):  # noqa: ARG001
    """Validate that the given config file exists and is valid YAML."""
    if not os.path.exists(arg):
        raise FileNotFoundError(arg)
    with open(arg) as f:
        if yaml.load(f, Loader=yaml.SafeLoader) is None:
            raise InvalidConfigFileError(arg)
    return arg


parser = argparse.ArgumentParser()
parser.add_argument("--config", type=lambda x: is_valid_config_file(parser, x))


def get_config(config_file: str | None = None) -> str:
    """Get the path to the configuration file, either from arguments or default."""
    if config_file is None:
        args, unknown = parser.parse_known_args()
        return args.config if args.config is not None else CONFIG_FILE
    return config_file


class Config:
    """Configuration settings for pyldraw."""

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
        """Load configuration from YAML file or create default configuration."""
        config_path = get_config(config_file)

        try:
            with open(config_path) as _config_file:
                cfg = yaml.load(_config_file, Loader=yaml.SafeLoader)
                return cls(
                    # pyrefly: ignore  # missing-attribute  # noqa: ERA001
                    ldraw_library_path=cfg.get("ldraw_library_path"),
                    # pyrefly: ignore  # missing-attribute  # noqa: ERA001
                    generated_path=cfg.get("generated_path"),
                )
        except FileNotFoundError:
            return cls()

    def __str__(self):
        return f"Config({self.ldraw_library_path=}, {self.generated_path=})"

    def write(self, config_file=None):
        """Write the config to config.yml."""
        config_path = get_config(config_file=config_file)

        with open(config_path, "w") as _config_file:
            written = {}
            if self.ldraw_library_path is not None:
                written["ldraw_library_path"] = self.ldraw_library_path
            if self.generated_path is not None:
                written["generated_path"] = self.generated_path
            yaml.dump(written, _config_file)
