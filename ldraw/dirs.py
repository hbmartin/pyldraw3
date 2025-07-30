"""data and config directories."""

import platformdirs

from ldraw.utils import ensure_exists

PYLDRAW = "pyldraw3"


def get_data_dir():
    """Get the directory where to put some data."""
    return ensure_exists(platformdirs.user_data_dir(PYLDRAW))


def get_config_dir():
    """Get the directory where the config is."""
    return ensure_exists(platformdirs.user_config_dir(PYLDRAW))


def get_cache_dir():
    """Get the directory where cached files are stored."""
    return ensure_exists(platformdirs.user_cache_dir(PYLDRAW))
