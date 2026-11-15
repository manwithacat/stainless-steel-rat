"""Deprecated alias for ssr.core.fixtures."""
import sys
from ssr.core import fixtures as _module

if __name__ == "__main__":   # python -m ssr.mouse.fixtures
    _module.main()
else:
    sys.modules[__name__] = _module
