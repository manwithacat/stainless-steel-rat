# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Bounded-memory source profiles and scalar KMB decoding."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import numpy as np
from ssr.qhdl import kmb as K


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def fingerprint():
    return {p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def operations(k, stop=None):
    """Stream scalar operands; no per-operation offset arrays."""
    streams = {n: k.stream(n) for n in ['qqq0','qqq1','qqq2','qq0','qq1','q0','b0','bc']}
    cursors = [0] * 5
    end = len(k.op_types) if stop is None else stop
    if type(end) is not int or not 0 <= end <= len(k.op_types):
        raise ValueError('invalid source stop')
    for raw in k.op_types[:end]:
        raw = int(raw)
        arity = raw & 0x30
        names, slot = {0x30: (['qqq0','qqq1','qqq2'],0),
                       0x20: (['qq0','qq1'],1), 0x10: (['q0'],2)}.get(arity, ([],0))
        qs = [int(streams[n][cursors[slot]]) for n in names]
        if names:
            cursors[slot] += 1
        bit = int(streams['b0'][cursors[3]]) if raw & 64 else None
        cond = int(streams['bc'][cursors[4]]) if raw & 128 else None
        cursors[3] += bool(raw & 64)
        cursors[4] += bool(raw & 128)
        base = raw if raw == K.PUSH_CONDITION else raw & 127
        if base not in K.NAMES:
            raise ValueError('unsupported opcode '+hex(raw))
        yield dict(name=K.NAMES[base], q=qs, b=bit, condition=cond)


def profile(path):
    path = Path(path)
    bound = sha(path)
    k = K.read(str(path))
    try:
        counts = Counter()
        depth = peak = 0
        for lo in range(0, len(k.op_types), 65536):
            chunk = k.op_types[lo:lo+65536]
            codes, ns = np.unique(chunk, return_counts=True)
            for code, n in zip(codes, ns):
                code = int(code)
                base = code if code == K.PUSH_CONDITION else code & 127
                counts[K.NAMES.get(base, hex(base))] += int(n)
            events = chunk[(chunk == K.PUSH_CONDITION) | (chunk == K.POP_CONDITION)]
            if len(events):
                changes = np.cumsum(np.where(events == K.PUSH_CONDITION, 1, -1))
                if depth + int(changes.min()) < 0:
                    raise ValueError('unbalanced source condition stack')
                peak = max(peak, depth + int(changes.max()))
                depth += int(changes[-1])
        if depth:
            raise ValueError('unbalanced source condition stack')
        result = dict(path=str(path.resolve()), sha256=bound, bytes=path.stat().st_size,
                      num_qubits=k.num_qubits, num_bits=k.num_bits, num_ops=len(k.op_types),
                      registers={n:[{'kind':'q' if isq else 'b','id':q} for isq,q,_ in ms]
                                 for n,ms in k.registers}, operations=dict(counts),
                      static_charged_instructions=sum(counts[n] for n in ['CCX','CCZ','CSWAP']),
                      maximum_condition_depth=peak, expected_charge=None,
                      evidence='static source structure; no task execution')
    finally:
        k.raw._mmap.close()
    if sha(path) != bound:
        raise ValueError('source changed during profile')
    return result


def word_table(path):
    path = Path(path)
    bound = sha(path)
    with np.load(path, allow_pickle=False) as z:
        if 'angle_words' not in z.files:
            raise ValueError('NPZ must provide explicit assembled angle_words')
        words = z['angle_words']
        if words.ndim != 2 or not np.issubdtype(words.dtype, np.integer):
            raise ValueError('angle_words must be a two-dimensional integer matrix')
        words = words.astype(np.int64, copy=True)
    if sha(path) != bound:
        raise ValueError('word file changed while reading')
    truth_sha = hashlib.sha256(canonical(words.tolist())).hexdigest()
    return words, dict(path=str(path.resolve()), sha256=bound, shape=list(words.shape),
                      angle_words_sha256=truth_sha)
