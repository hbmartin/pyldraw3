"""Lightweight shared CLI defaults."""

import re

from ldraw.rendering import RenderView

PACKAGE_NAME = "pyldraw3"
DEFAULT_SEARCH_LIMIT = 25
DEFAULT_RENDER_SIZE = (800, 600)
DEFAULT_RENDER_VIEWS = tuple(RenderView)
DEFAULT_PAGE_MARKER_PREFIX = "// PDF_PAGE "
_SAFE_RENDER_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
COMPLETE_VERSION = "complete"
