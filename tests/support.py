"""Skip helpers for optional dependencies (kickmix, the official invsqrt verifier, the native engine)."""
from __future__ import annotations

import os

import pytest


def need_kickmix():
    return pytest.importorskip("kickmix", reason="kickmix is not importable (optional dependency)")


def need_verifier():
    need_kickmix()
    from ssr.core import verifier
    if not verifier.available():
        pytest.skip("SSR_INVSQRT_VERIFIER is not set to a copy of the official invsqrt verifier",
                    allow_module_level=True)


def need_engine():
    need_verifier()
    value = os.environ.get("SSR_ENGINE_PYTHON")
    if not value:
        pytest.skip("SSR_ENGINE_PYTHON is not set to the kickmix-engine python directory",
                    allow_module_level=True)
    return value
