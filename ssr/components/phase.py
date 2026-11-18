# Ported from vqcc-research rat_workflow/construct.py (R pathway, Apache-2.0).
"""Construct the registered phase-demand identity, then use the existing gate."""
from pathlib import Path
import sys

from . import view as V, formal as F
from .common import K

def update(mask, constant, row):
    code, qs = row['code'] & 127, row['q']
    guarded = row['bc'] is not None or row['condition_depth'] != 0
    if code in (0x11, 0x12, 0x50):
        writes = qs
    elif code in (0x21, 0x31):
        writes = qs[-1:]
    elif code in (0x22, 0x32):
        writes = qs[-2:]
    else:
        return mask, constant, None
    if not any(mask >> q & 1 for q in writes):
        return mask, constant, None
    if guarded:
        return mask, constant, 'guarded write into tracked observable'
    if code == 0x11:
        return mask, constant ^ 1, None
    if code == 0x21:
        return mask ^ (1 << qs[0]), constant, None
    if code == 0x22:
        if ((mask >> qs[0]) ^ (mask >> qs[1])) & 1:
            mask ^= (1 << qs[0]) | (1 << qs[1])
        return mask, constant, None
    if code == 0x32 and not (((mask >> qs[-2]) ^ (mask >> qs[-1])) & 1):
        return mask, constant, None
    return mask, constant, 'nonlinear write or clear into tracked observable'


def affine(mask, constant):
    return frozenset(([0] if constant else [])+[1 << i for i in range(mask.bit_length()) if mask >> i & 1])


def repayments(forms, condition):
    terms = frozenset({0})
    for form in forms:
        terms = F.mul(terms, form)
    rows = []
    for monomial in sorted(terms):
        qs = [i for i in range(monomial.bit_length()) if monomial >> i & 1]
        if not 1 <= len(qs) <= 3:
            raise ValueError('constant/global or higher-degree repayment needs another construction')
        line = {1: 'Z', 2: 'CZ', 3: 'CCZ'}[len(qs)]+' '+' '.join(f'q{q}' for q in qs)
        if condition is not None:
            line += f' if b{condition}'
        rows.append(V.parse(line))
    return rows


def build(source, nominee, out):
    start, stop = nominee['first'], nominee['hmr']+1
    cut = V.window(source, start, stop)
    if cut['inherited_conditions'] or cut['exit_conditions']:
        raise ValueError('inherited or outgoing guards need caller facts')
    rows = cut['records']
    if any(q > 65535 for row in rows for q in row['q']):
        raise ValueError('phase constructor wire-id cap65535')
    first, last = rows[0], rows[-1]
    if first['code'] != 0x31 or last['code'] != K.HMR or first['q'][-1:] != last['q']:
        raise ValueError('nomination no longer matches source endpoints')
    a, b, t = first['q']
    masks, const = [1 << a, 1 << b], [0, 0]
    child, source_outcomes, child_outcomes = [], {}, {}
    for i, row in enumerate(rows[1:], 1):
        base = row['code'] & 127
        if base == K.HMR:
            label = f'original-{i}'
            source_outcomes[str(i)] = label
            child_outcomes[str(len(child))] = label
        child.append(dict(row))
        if i == len(rows)-1:
            child += repayments([affine(m, c) for m, c in zip(masks, const)], row['b0'])
            break
        if t in row['q']:
            if base not in (0x10, 0x20):
                raise ValueError('target data read/write or unsupported target phase')
            forms = [affine(m, c) for m, c in zip(masks, const)]
            forms += [affine(1 << q, 0) for q in row['q'] if q != t]
            # Same program point and guard stack as the preserved target phase.
            child += repayments(forms, row['bc'])
        for j in range(2):
            masks[j], const[j], error = update(masks[j], const[j], row)
            if error:
                raise ValueError(error)
    if len(child) > 512:
        raise ValueError('constructed child exceeds existing 512-op measured gate')
    before, after = V.costs(rows), V.costs(child)
    conditional_cubics = sum((r['code'] & 127) == 0x30 and r['bc'] is not None for r in child)
    if after['static_toffoli_like'] > before['static_toffoli_like']:
        raise ValueError('repayment increases static charge; outside registered menu')
    if after['static_toffoli_like'] == before['static_toffoli_like'] and conditional_cubics == 0:
        raise ValueError('static tie without conditional repayment opportunity')
    out.mkdir()
    path = out/'child.kmb'
    interface = sorted({q for row in child for q in row['q']})
    V.write_module(path, child, interface)
    import json
    contract = out/'contract.json'
    contract.write_text(json.dumps(dict(zero_qubits=[], private_records=[],
        outcomes=dict(source=source_outcomes, child=child_outcomes)), indent=2)+'\n')
    return dict(start=start, stop=stop, candidate=str(path), contract=str(contract), records=child,
        before=before, after=after, conditional_cubic_repayments=conditional_cubics,
        expected_cost='unavailable until actual guards, failures and full-task draw gates are evaluated')
