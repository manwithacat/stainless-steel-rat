"""Deprecated alias for ssr.cursor.cli."""
import sys
from ssr.cursor import cli as _module

sys.modules[__name__] = _module
