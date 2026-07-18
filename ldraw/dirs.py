"""data and config directories."""

import platformdirs

PYLDRAW = "pyldraw3"


def get_data_dir() -> str:
    """Get the directory where to put some data."""
    return platformdirs.user_data_dir(PYLDRAW)


def get_config_dir() -> str:
    """Get the directory where the config is."""
    return platformdirs.user_config_dir(PYLDRAW)


def get_cache_dir() -> str:
    """Get the directory where cached files are stored."""
    return platformdirs.user_cache_dir(PYLDRAW)
