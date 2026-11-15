"""Deprecated alias for ssr.cursor.environment (CircuitMouse is now StateCursor)."""
import sys
from ssr.cursor import environment as _module

sys.modules[__name__] = _module
