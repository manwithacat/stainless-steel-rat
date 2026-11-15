"""Deprecated alias for ssr.core.store."""
import sys
from ssr.core import store as _module

sys.modules[__name__] = _module
