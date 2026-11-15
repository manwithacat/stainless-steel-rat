"""Lazy access to the task's official invsqrt verifier module, which is not shipped here.

The Rat's task adapter reuses the official verifier's problem specification and reference
functions (`ProblemSpecInvSqrt`, `reference_values`, `z_pow_class`, `rotation_t_count`,
`T_PER_TOFFOLI`, `validate_registers`, `from_bits`). That file belongs to the competition data,
under its own terms, so this repository does not include it. Point the environment variable
`SSR_INVSQRT_VERIFIER` at your own copy of `verify_submission_invsqrt.py`. It is imported once,
unmodified, and its SHA-256 enters every run context fingerprint.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ENV = "SSR_INVSQRT_VERIFIER"
_MODULE_NAME = "ssr_official_invsqrt_verifier"


class VerifierUnavailable(RuntimeError):
    """The official invsqrt verifier was not configured."""


def verifier_path() -> Path:
    value = os.environ.get(ENV)
    if not value:
        raise VerifierUnavailable(
            f"set {ENV} to your copy of the official verify_submission_invsqrt.py; it is not shipped with this package")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise VerifierUnavailable(f"{ENV} does not name a file: {path}")
    return path


def available() -> bool:
    try:
        verifier_path()
    except VerifierUnavailable:
        return False
    return True


def load():
    module = sys.modules.get(_MODULE_NAME)
    if module is not None:
        return module
    path = verifier_path()
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_MODULE_NAME, None)
        raise
    return module


class _LazyVerifier:
    """Module proxy: attribute access loads the configured verifier on first use."""

    def __getattr__(self, name):
        return getattr(load(), name)


V = _LazyVerifier()


class _LazyPath(os.PathLike):
    """Path-like handle to the configured verifier, resolved when used."""

    def __fspath__(self):
        return str(verifier_path())

    def __str__(self):
        return str(verifier_path())

    def read_bytes(self):
        return verifier_path().read_bytes()

    def resolve(self):
        return verifier_path()


VERIFIER = _LazyPath()
