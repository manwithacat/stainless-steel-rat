"""Deprecated alias for ssr.core.evaluator."""
import sys
from ssr.core import evaluator as _module

sys.modules[__name__] = _module
