"""Deprecated alias for ssr.core.verifier."""
import sys
from ssr.core import verifier as _module

sys.modules[__name__] = _module
