# Ported from vqcc-research ssr_measured_framing/frame.py (R pathway, Apache-2.0).
"""Sufficient commutation frame for nominated CCX-to-HMR retiming.

The body is copied unchanged and cannot access the measured qubit or its
outcome record. Only the tiny endpoint instrument is expanded symbolically.
"""
from pathlib import Path
import sys

import numpy as np

from . import measured as M, view as V
from .common import K

BLOCK = 65536
KNOWN = {0, 1, 6, 0x10, 0x11, 0x12, 0x13, 0x20, 0x21, 0x22,
         0x30, 0x31, 0x32, 0x40, 0x41, 0x42, 0x50}


def certify(path, first, last):
    k = K.read(str(path))
    if not 0 <= first < last < len(k.op_types):
        raise M.NotEntered('ordered endpoint indices required')
    left = V.window(path, first, first+1)
    right = V.window(path, last, last+1)
    if left['inherited_conditions'] or right['inherited_conditions']:
        raise M.NotEntered('endpoints need empty inherited guard stacks')
    a, z = left['records'][0], right['records'][0]
    if a['code'] != 0x31 or z['code'] != K.HMR or len(set(a['q'])) != 3 or z['q'] != a['q'][-1:]:
        raise M.NotEntered('need unconditional CCX and matching HMR endpoints')
    target, record = a['q'][-1], z['b0']
    counts = dict.fromkeys(V.KEYS, 0)
    stack = []
    V.advance(k, 0, first+1, counts, stack)
    if stack:
        raise M.NotEntered('nonempty body entry guard stack')
    streams = {key: k.stream(key) for key in V.E.U32}
    totals = dict(quantum_operands_checked=0, record_fields_checked=0, push_events=0, pop_events=0)
    for lo in range(first+1, last, BLOCK):
        hi = min(lo+BLOCK, last)
        types = np.asarray(k.op_types[lo:hi])
        base = types & 127
        bad = np.flatnonzero(~np.isin(base, list(KNOWN)))
        if len(bad):
            raise M.NotEntered(f'unsupported body opcode at{lo+int(bad[0])}')
        for kind, names, key in [(48, ('qqq0', 'qqq1', 'qqq2'), 'q3'),
                                 (32, ('qq0', 'qq1'), 'q2'), (16, ('q0',), 'q1')]:
            positions = np.flatnonzero((types & 48) == kind)
            for name in names:
                values = streams[name][counts[key]:counts[key]+len(positions)]
                totals['quantum_operands_checked'] += len(values)
                hit = np.flatnonzero(values == target)
                if len(hit):
                    raise M.NotEntered(f'body accesses measured q{target} at{lo+int(positions[int(hit[0])])}')
        for mask, name in [(64, 'b0'), (128, 'bc')]:
            positions = np.flatnonzero((types & mask) != 0)
            values = streams[name][counts[name]:counts[name]+len(positions)]
            totals['record_fields_checked'] += len(values)
            hit = np.flatnonzero(values == record)
            if len(hit):
                raise M.NotEntered(f'body accesses outcome b{record} at{lo+int(positions[int(hit[0])])}')
        totals['push_events'] += int(np.count_nonzero(types == K.PUSH_CONDITION))
        totals['pop_events'] += int(np.count_nonzero(types == K.POP_CONDITION))
        V.advance(k, lo, hi, counts, stack)
    if stack:
        raise M.NotEntered('nonempty body exit guard stack')
    source = [dict(a, op=0, condition_depth=0), dict(z, op=1, condition_depth=0)]
    child = [dict(z, op=0, condition_depth=0), V.parse(f'CZ q{a["q"][0]} q{a["q"][1]} if b{record}')]
    endpoint = M.compare(source, child, outcomes=dict(source={'1': 'retired'}, child={'0': 'retired'}))
    if not endpoint['equivalent']:
        raise M.NotEntered('endpoint instrument mismatch')
    script = '\n'.join([f'insert {first} => HMR q{target} b{record}',
                        f'replace {first} => CZ q{a["q"][0]} q{a["q"][1]} if b{record}',
                        f'delete {last}'])+'\n'
    return dict(schema='ssr-measured-frame-proof-v1', tier='local prescreen',
                source_range=[first, last+1], body_range=[first+1, last],
                body_ops=last-first-1, measured_qubit=target, outcome_record=record,
                frame=dict(body_unchanged=True, target_and_record_never_accessed=True,
                           empty_endpoint_guards=True, closed_internal_guards=True, **totals),
                endpoint=endpoint, endpoint_source=source, endpoint_child=child,
                edit_script=script, static_toffoli_delta=-1, qubit_delta=0,
                whole_task_admission='pending',
                proof='HMR(target,record) commutes with the unchanged disjoint body; exact endpoint instrument then gives retiming and phase repayment',
                limits='Nominated site only. Outcome labels may be reordered; no same-seed or complete-task admission claim.')
