"""Deprecated alias for ssr.core.actions."""
import sys
from ssr.core import actions as _module

sys.modules[__name__] = _module
