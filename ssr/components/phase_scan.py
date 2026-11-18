# Ported from vqcc-research rat_workflow/phase_scan.py (R pathway, Apache-2.0).
"""Bounded streaming nomination of phase-only CCX/HMR target lifetimes.

Not a proof. All quantum accesses participate, including guards. The exact
constructor subsequently checks control transport, record/guard and cost debt.
"""
from collections import Counter
from pathlib import Path
import sys
import numpy as np

from .common import K, sha

def nominate(events, after, stats):
    """Per-wire access sequence: (source_op, full_code, operand_role)."""
    if not len(events):
        return [], []
    e = np.asarray(events, dtype=np.int64)
    base = e[:, 1] & 127
    phase = np.isin(base, [0x10, 0x20])
    last_nonphase = np.maximum.accumulate(np.where(phase, -1, np.arange(len(e))))
    found = []
    for h in np.flatnonzero((base == K.HMR) & (e[:, 0] >= after)):
        stats['HMR_target_accesses'] += 1
        j = last_nonphase[h-1] if h else -1
        if j < 0 or j == h-1:
            stats['HMR_without_preceding_phase'] += 1
            continue
        stats['phase_ended_lifetimes'] += 1
        if e[j, 1] != 0x31 or e[j, 2] != 2:
            stats['phase_predecessor_not_unguarded_CCX_target'] += 1
        elif e[h, 1] != K.HMR:
            stats['guarded_HMR'] += 1
        elif h-j-1 > 8:
            stats['more_than_8_target_phases'] += 1
        elif e[h, 0]-e[j, 0]+1 > 512:
            stats['source_span_above_512'] += 1
        else:
            found.append(dict(first=int(e[j, 0]), hmr=int(e[h, 0]),
                              phase_ops=[int(x) for x in e[j+1:h, 0]]))
            stats['grammar_eligible'] += 1
    # Preserve a possible producer followed by arbitrarily many phase accesses.
    # Nine tail events suffice: >8 phases is outside this registered grammar.
    return found, [tuple(map(int, row)) for row in e[-10:]]


def scan(path, block=262144, limit=8):
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError('nomination limit must be 1..256')
    before = sha(path)
    k = K.read(str(path))
    n = len(k.op_types)
    if n == 0:
        raise ValueError('zero operation coverage')
    counts = dict(q1=0, q2=0, q3=0)
    tails = {}
    stats = Counter()
    samples = []
    for lo in range(0, n, block):
        hi = min(n, lo+block)
        types = np.asarray(k.op_types[lo:hi])
        wires, indices, codes, roles = [], [], [], []
        for kind, names, key in [(16, ('q0',), 'q1'), (32, ('qq0', 'qq1'), 'q2'),
                                 (48, ('qqq0', 'qqq1', 'qqq2'), 'q3')]:
            pos = np.flatnonzero((types & 48) == kind)
            for role, name in enumerate(names):
                wires.append(np.asarray(k.stream(name)[counts[key]:counts[key]+len(pos)]))
                indices.append(pos+lo)
                codes.append(types[pos])
                roles.append(np.full(len(pos), role, dtype=np.uint8))
            counts[key] += len(pos)
        w, ix, c, r = map(np.concatenate, (wires, indices, codes, roles))
        stats['quantum_operand_accesses'] += len(w)
        if len(w):
            order = np.lexsort((ix, w))
            w, ix, c, r = (a[order] for a in (w, ix, c, r))
            cuts = np.r_[0, np.flatnonzero(w[1:] != w[:-1])+1, len(w)]
            for a, z in zip(cuts[:-1], cuts[1:]):
                q = int(w[a])
                events = tails.get(q, [])+list(zip(ix[a:z], c[a:z], r[a:z]))
                found, tails[q] = nominate(events, lo, stats)
                samples += [dict(row, target=q) for row in found]
        stats['operations_covered'] += hi-lo
    samples.sort(key=lambda row: (row['first'], row['hmr']))
    if sha(path) != before:
        raise ValueError('source drift during scan')
    return dict(schema='ssr-phase-demand-nominations-v1', source=str(path), source_sha256=before,
        declared_qubits=int(k.num_qubits), source_ops=n, coverage=dict(stats),
        nominees=samples[:limit], nominees_truncated=len(samples) > limit,
        status='nominated' if samples else 'no_eligible_lifetime_in_registered_grammar',
        scope='Complete source-access scan; sufficient <=512-op/8-phase grammar only. No proof, cost or optimum claim.')
