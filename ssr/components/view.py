# Ported from vqcc-research ssr_tasks/view.py (R pathway, Apache-2.0).
"""Bounded-memory KMB core windows, preserving guards and every angle bit."""
from collections import Counter
import numpy as np
from .common import K, E, integer, name

MAX_OPS = 512
BLOCK = 1 << 18
KEYS = ('q3', 'q2', 'q1', 'b0', 'bc', 'ang', 'tag')


def advance(k, start, stop, counts, stack):
    for a in range(start, stop, BLOCK):
        seg = k.op_types[a:min(stop, a+BLOCK)]
        special = np.flatnonzero((seg == K.PUSH_CONDITION) | (seg == K.POP_CONDITION))
        if len(special):
            bc = np.cumsum((seg & 128) != 0)
            for i in special:
                if int(seg[i]) == K.PUSH_CONDITION:
                    stack.append(dict(push_op=a+int(i), record=int(k.stream('bc')[counts['bc']+int(bc[i])-1])))
                    if len(stack) > 256:
                        raise ValueError('condition depth exceeds the component adapter cap256')
                elif not stack:
                    raise ValueError('malformed source condition stack')
                else:
                    stack.pop()
        cls = seg & 48
        delta = (np.count_nonzero(cls == 48), np.count_nonzero(cls == 32), np.count_nonzero(cls == 16),
                 np.count_nonzero(seg & 64), np.count_nonzero(seg & 128),
                 np.count_nonzero((seg & 127) == K.Z_POW), np.count_nonzero(seg == K.INFO_TAG))
        for key, n in zip(KEYS, delta):
            counts[key] += int(n)


def window(path, start, stop, initial_conditions=()):
    k = K.read(str(path))
    n = len(k.op_types)
    integer(start, 'start', 0, n)
    integer(stop, 'stop', start+1, min(n, start+MAX_OPS))
    counts = {key:0 for key in KEYS}
    stack = list(initial_conditions)
    advance(k, 0, start, counts, stack)
    entry = list(stack)
    streams = {s:k.stream(s) for s in E.U32}
    records = []
    for i in range(start, stop):
        code = int(k.op_types[i])
        q = []
        if code != K.PUSH_CONDITION:
            cls = code & 48
            names, key = {48:(('qqq0', 'qqq1', 'qqq2'), 'q3'),
                          32:(('qq0', 'qq1'), 'q2'), 16:(('q0',), 'q1')}.get(cls, ((), None))
            q = [int(streams[s][counts[key]]) for s in names]
        record = dict(op=i, code=code, opcode=name(code), q=q,
                      b0=int(streams['b0'][counts['b0']]) if code & 64 else None,
                      bc=int(streams['bc'][counts['bc']]) if code & 128 else None,
                      angle128_le_hex=bytes(k.stream('angles')[counts['ang']]).hex() if code & 127 == K.Z_POW else None,
                      tag_hex=None, condition_depth=len(stack))
        if code == K.INFO_TAG:
            off, nt, _ = k.offsets['info_tags']
            ends = np.frombuffer(k.raw, dtype='<u8', count=nt, offset=off)
            j = counts['tag']
            a, b = (int(ends[j-1]) if j else 0), int(ends[j])
            if b-a > 4096:
                raise ValueError('INFO_TAG exceeds4096-byte component cap')
            record['tag_hex'] = bytes(k.raw[off+8*nt+a:off+8*nt+b]).hex()
        records.append(record)
        advance(k, i, i+1, counts, stack)
    touched_q = {q for r in records for q in r['q']}
    touched_b = {b for r in records for b in (r['b0'], r['bc']) if b is not None}
    relevant = []
    for nm, items in k.registers:
        if any(i in (touched_q if isq else touched_b) for isq, i, *_ in items):
            relevant.append(dict(name=nm, entries=len(items),
                                 qubits=[int(i) for isq, i, *_ in items if isq and i in touched_q],
                                 bits=[int(i) for isq, i, *_ in items if not isq and i in touched_b]))
    return dict(start=start, stop=stop, source_ops=n, source_width=int(k.num_qubits),
                registers=relevant[:32], source_registers_total=len(k.registers),
                relevant_registers_total=len(relevant), registers_truncated=len(relevant) > 32,
                register_scope='only entries touched by this source core; full source retained by hash',
                inherited_conditions=entry, exit_conditions=stack, records=records)


def text(r):
    if r['code'] == K.INFO_TAG:
        # Metadata is retained in binary; patch syntax cannot quote arbitrary
        # tag bytes safely. Export uses @source references for unchanged tags.
        return 'INFO_TAG '+repr(bytes.fromhex(r['tag_hex']).decode('utf-8', 'replace'))
    parts = [name(r['code'])]+[f'q{q}' for q in r['q']]
    if r['b0'] is not None:
        parts.append(f'b{r["b0"]}')
    if r['angle128_le_hex'] is not None:
        value = int.from_bytes(bytes.fromhex(r['angle128_le_hex']), 'little')
        parts.append(f'angle128:{value:032x}')
    if r['bc'] is not None:
        parts += ['if', f'b{r["bc"]}']
    return ' '.join(parts)


def parse(line):
    r = E.parse_op(line)
    if 'copy' in r or r.get('angle_from') is not None:
        raise ValueError('component replacement needs literal operations/angle128, not source copies')
    return dict(code=r['code'], opcode=name(r['code']), q=list(r['q']), b0=r['b0'], bc=r['bc'],
                angle128_le_hex=r['angle_literal'].hex() if r.get('angle_literal') is not None else None,
                tag_hex=r['tag'].hex() if r.get('tag') is not None else None,
                condition_depth=0, op=None)


def write_module(path, records, interface):
    streams = {key:[] for key in E.U32}
    angles, tags = [], []
    for r in records:
        code = r['code']
        names = {48:('qqq0', 'qqq1', 'qqq2'), 32:('qq0', 'qq1'), 16:('q0',)}.get(code & 48, ())
        for key, q in zip(names, r['q']):
            streams[key].append(q)
        if code & 64:
            streams['b0'].append(r['b0'])
        if code & 128:
            streams['bc'].append(r['bc'])
        if code & 127 == K.Z_POW:
            angles.append(bytes.fromhex(r['angle128_le_hex']))
        if code == K.INFO_TAG:
            tags.append(bytes.fromhex(r['tag_hex']))
    K.write_kmb(str(path), [r['code'] for r in records], streams, b''.join(angles), tags,
                [('interface', [(True, int(w)) for w in sorted(interface)])])


def costs(records):
    c = Counter(r['opcode'] for r in records)
    return dict(static_toffoli_like=sum(r['code'] in K.TOFFOLI_LIKE for r in records),
                raw_rotations=c['Z_POW'], operations=len(records),
                scope='component static counts; no full-task or synthesized-rotation cost')
