"""Portable component utilities; optional competition tooling is not imported."""
from pathlib import Path
import hashlib
import json
from ssr.qhdl import kmb as K, edit as E

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write_json(path, value):
    with Path(path).open('xb') as f:
        f.write(canonical(value))


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def name(code):
    base = code if code == K.PUSH_CONDITION else code & 127
    return K.NAMES.get(base, hex(base))
