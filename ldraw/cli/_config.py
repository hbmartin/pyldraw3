"""Runtime services for the config commands."""

from __future__ import annotations

import yaml

from ldraw.config import Config


def config_command() -> int:
    """Print the current pyldraw configuration as YAML."""
    print(yaml.dump(Config.load().to_dict()))
    return 0
