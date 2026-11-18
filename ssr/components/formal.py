# Ported from vqcc-research ssr_tasks/formal.py (R pathway, Apache-2.0).
"""Exact arbitrary-entry value and phase semantics for bounded reversible cores."""
from copy import deepcopy
from .common import K

MOD = 1 << 128
HALF = 1 << 127
TERM_CAP = 512


class Barrier(ValueError):
    pass


def bounded(terms):
    if len(terms) > TERM_CAP:
        raise Barrier(f'symbolic term cap{TERM_CAP} exceeded')
    return terms


def mul(a, b):
    out = set()
    for x in a:
        for y in b:
            m = x | y
            if m in out:
                out.remove(m)
            else:
                out.add(m)
        bounded(out)
    return frozenset(out)


def phase_add(total, predicate, angle):
    angle %= MOD
    if not angle:
        return
    if angle == HALF:
        poly = {m:1 for m in predicate}
    else:
        # XOR of Boolean monomials as an integer multilinear polynomial:
        # f XOR m = f + m - 2*f*m. Products use x*x=x.
        poly = {}
        for monomial in sorted(predicate):
            old = dict(poly)
            poly[monomial] = (poly.get(monomial, 0)+1) % MOD
            for m, coefficient in old.items():
                q = m | monomial
                poly[q] = (poly.get(q, 0)-2*coefficient) % MOD
            poly = {m:c for m, c in poly.items() if c}
            bounded(poly)
    for m, coefficient in poly.items():
        total[m] = (total.get(m, 0)+angle*coefficient) % MOD
        if not total[m]:
            del total[m]
    bounded(total)


def angle(r):
    code = r['code']
    if code in (0x00, 0x10, 0x20, 0x30):
        return HALF
    if code == K.Z_POW:
        raw = bytes.fromhex(r['angle128_le_hex'])
        if len(raw) != 16:
            raise Barrier('Z_POW must retain exactly128angle bits')
        return int.from_bytes(raw, 'little')
    return None


def signature(records, interface, *, trace=False):
    if len(records) > 512 or len(interface) > 128 or len(set(interface)) != len(interface):
        raise Barrier('reversible cap:512 ops,128 unique wires')
    if any(type(w) is not int or not 0 <= w <= 65535 for w in interface):
        raise Barrier('wire ids must be integers in0..65535')
    state = {w:frozenset({1 << w}) for w in interface}
    phase = {}
    predicates = {}
    for i, r in enumerate(records):
        code, q = r['code'], r['q']
        if r.get('bc') is not None or r.get('condition_depth', 0):
            raise Barrier(f'op{i}: conditioned interface needs an outcome-aware gate')
        if len(q) != len(set(q)) or any(w not in state for w in q):
            raise Barrier(f'op{i}: repeated or out-of-interface wire')
        if code == K.INFO_TAG:
            continue
        if code in (K.R, K.HMR, K.PUSH_CONDITION, K.POP_CONDITION, 0x40, 0x41, 0x42):
            raise Barrier(f'op{i} {r["opcode"]}: measurement/reset/record barrier; inspect a smaller reversible core')
        if code == 0x11:
            state[q[0]] = bounded(state[q[0]] ^ {0})
        elif code == 0x21:
            state[q[1]] = bounded(state[q[1]] ^ state[q[0]])
        elif code == 0x31:
            state[q[2]] = bounded(state[q[2]] ^ mul(state[q[0]], state[q[1]]))
        elif code == K.SWAP:
            state[q[0]], state[q[1]] = state[q[1]], state[q[0]]
        elif code == 0x32:
            delta = mul(state[q[0]], state[q[1]] ^ state[q[2]])
            state[q[1]] = bounded(state[q[1]] ^ delta)
            state[q[2]] = bounded(state[q[2]] ^ delta)
        elif angle(r) is not None:
            predicate = frozenset({0})
            for w in q:
                predicate = mul(predicate, state[w])
            predicates[i] = (predicate, angle(r))
            phase_add(phase, predicate, angle(r))
        else:
            raise Barrier(f'op{i}: unsupported opcode{code}')
    result = dict(values={str(w):[hex(m) for m in sorted(v)] for w, v in sorted(state.items())},
                  phase={hex(m):f'{c:032x}' for m, c in sorted(phase.items())},
                  phase_modulus_bits=128, arbitrary_dirty_entry=True, global_phase_preserved=True)
    return (result, predicates) if trace else result


def fold_phase(records, interface):
    _, predicates = signature(records, interface, trace=True)
    groups = {}
    for i, (p, a) in predicates.items():
        groups.setdefault(p, []).append((i, a))
    child = deepcopy(records)
    drop = set()
    for rows in groups.values():
        if len(rows) < 2:
            continue
        total = sum(a for _, a in rows) % MOD
        if total == 0:
            drop.update(i for i, _ in rows)
        elif all(records[i]['code'] == K.Z_POW for i, _ in rows):
            child[rows[0][0]]['angle128_le_hex'] = total.to_bytes(16, 'little').hex()
            drop.update(i for i, _ in rows[1:])
    return [r for i, r in enumerate(child) if i not in drop]


def conjugate(records, interface):
    signature(records, interface)
    from .view import parse, costs
    for i, first in enumerate(records):
        if first['code'] != 0x31:
            continue
        a, b, t = first['q']
        added = {}
        for j in range(i+1, len(records)):
            r = records[j]
            code, q = r['code'], r['q']
            if code == 0x31 and q[-1] == t and set(q[:2]) == {a, b}:
                child = []
                for k, old in enumerate(records):
                    if k not in (i, j):
                        child.append(old)
                    child += added.get(k, [])
                if costs(child)['static_toffoli_like'] < costs(records)['static_toffoli_like']:
                    return child
                break
            written = set(q) if code == K.SWAP else set(q[1:]) if code == 0x32 else {q[-1]} if code in (0x11, 0x21, 0x31) else set()
            if written & {a, b}:
                break
            if t not in q:
                continue
            if code == 0x10:
                added[j] = [parse(f'CZ q{a} q{b}')]
            elif code == 0x20:
                c = q[1] if q[0] == t else q[0]
                added[j] = [parse(f'CZ q{a} q{b}' if c in (a, b) else f'CCZ q{a} q{b} q{c}')]
            else:
                break
    return deepcopy(records)


def cancel_pairs(records, interface):
    signature(records, interface)
    out = deepcopy(records)
    inverse = {0x00, 0x10, 0x11, 0x20, 0x21, 0x22, 0x30, 0x31, 0x32}
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(out):
            if a['code'] not in inverse:
                continue
            for j in range(i+1, len(out)):
                b = out[j]
                if a['code'] == b['code'] and a['q'] == b['q']:
                    out = [r for k, r in enumerate(out) if k not in (i, j)]
                    changed = True
                    break
                if set(a['q']) & set(b['q']):
                    break
            if changed:
                break
    return out
