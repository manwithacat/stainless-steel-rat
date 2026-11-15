"""Deprecated alias for ssr.core.official."""
import sys
from ssr.core import official as _module

sys.modules[__name__] = _module
