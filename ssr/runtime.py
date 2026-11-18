"""Dependency discovery that does not import optional native libraries."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path


def engine_python():
    value = os.environ.get('SSR_ENGINE_PYTHON')
    return Path(value).expanduser() if value else None


def doctor(engine=None):
    import numpy as np
    from ssr import __version__
    kickmix = importlib.util.find_spec('kickmix') is not None
    verifier = os.environ.get('SSR_INVSQRT_VERIFIER')
    verifier_ready = bool(verifier and Path(verifier).expanduser().is_file())
    engine = Path(engine) if engine else engine_python()
    engine_ready = bool(engine and (engine/'kickmix_engine/__init__.py').is_file()
                        and any((engine/'kickmix_engine').glob('_engine*.so')))
    core_ready = int(np.__version__.split('.')[0]) >= 2
    return {'version': __version__, 'numpy': np.__version__,
            'component_tools': 'ready' if core_ready else 'requires numpy>=2',
            'invsqrt_native': 'configured' if kickmix and verifier_ready and engine_ready else 'dependencies_missing',
            'dependencies': {'kickmix': kickmix, 'official_invsqrt_verifier': verifier_ready,
                             'kickmix_engine': engine_ready},
            'next': 'ssr-components capabilities',
            'setup': {'kickmix': 'Install the kickmix package from Qualtran into this interpreter.',
                      'official_invsqrt_verifier': 'Set SSR_INVSQRT_VERIFIER to your own competition verifier file.',
                      'kickmix_engine': 'Set SSR_ENGINE_PYTHON to the directory containing kickmix_engine.'},
            'scope': 'Configuration check only; no native binary was loaded and no circuit was executed.'}
