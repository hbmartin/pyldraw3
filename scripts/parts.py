#!/usr/bin/env python
"""Example script for part lookup operations."""

from ldraw.parts import Parts

parts = Parts()
part = parts.part(code="93055")
print(part.category)
print(part.description)
part = parts.part(code="u9156c02")
print(part.category)
print(part.description)
