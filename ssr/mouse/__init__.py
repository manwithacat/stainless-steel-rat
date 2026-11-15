"""Deprecated alias (0.x series): `ssr.mouse` was renamed.

The shared modules moved to `ssr.core` (store, evaluator, verifier, official, actions, fixtures) and the local
interaction loop to `ssr.cursor` (`CircuitMouse` is now `StateCursor`; `python -m ssr.cursor`). Importing
`ssr.mouse.<module>` still works and returns the new module.
"""
import warnings

warnings.warn("ssr.mouse is deprecated: use ssr.core (shared modules) and ssr.cursor (the state cursor)",
              DeprecationWarning, stacklevel=2)
