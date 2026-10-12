"""Lightweight shared CLI defaults."""

import re

from ldraw._constants import (
    COMPLETE_VERSION as COMPLETE_VERSION,  # noqa: PLC0414 - public re-export
)
from ldraw._constants import (
    DEFAULT_PAGE_MARKER_PREFIX as DEFAULT_PAGE_MARKER_PREFIX,  # noqa: PLC0414 - public re-export
)
from ldraw.rendering import RenderView

PACKAGE_NAME = "pyldraw3"
DEFAULT_SEARCH_LIMIT = 25
DEFAULT_RENDER_SIZE = (800, 600)
DEFAULT_RENDER_VIEWS = tuple(RenderView)
_SAFE_RENDER_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
