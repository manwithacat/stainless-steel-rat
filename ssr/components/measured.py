# Ported from vqcc-research ssr_measured_components/measured.py (R pathway, Apache-2.0).
"""Exact sufficient instrument proof for bounded measured Rat components.

HMR outcome labels denote independent uniform bits, not mutable records.
Equality for every aligned/private outcome proves the declared instrument;
different outcome decompositions can be equivalent but fail this grammar.
"""
from pathlib import Path
import hashlib
import json
import sys

from . import formal as F
from .common import K, canonical

ZERO = frozenset()
ONE = frozenset({0})
MAX_OPS = 512
MAX_VARIABLES = 128


class NotEntered(ValueError):
    pass


def xor(a, b):
    return frozenset(F.bounded(a ^ b))


def product(*items):
    out = ONE
    for item in items:
        out = F.mul(out, item)
    return out


def normalize_outcomes(records, mapping):
    positions = {i for i, r in enumerate(records) if r['code'] & 127 == K.HMR}
    if not isinstance(mapping, dict):
        raise NotEntered('explicit outcome mapping required')
    try:
        result = {int(i): label for i, label in mapping.items()}
    except (ValueError, TypeError) as error:
        raise NotEntered('invalid HMR positions') from error
    if len(result) != len(mapping) or set(result) != positions:
        raise NotEntered('outcome mapping must cover exactly every HMR position')
    if any(not isinstance(label, str) or not label or len(label) > 64 for label in result.values()):
        raise NotEntered('outcome labels need bounded nonempty strings')
    if len(set(result.values())) != len(result):
        raise NotEntered('each HMR must have an independent outcome label')
    return result


def inputs(source, child, zeros, private, outcomes):
    if len(source) > MAX_OPS or len(child) > MAX_OPS:
        raise NotEntered('operation cap512')
    if not isinstance(outcomes, dict):
        raise NotEntered('explicit source/child outcome mappings required')
    maps = [normalize_outcomes(rows, outcomes.get(side)) for side, rows in [('source', source), ('child', child)]]
    qs = sorted({q for rows in (source, child) for r in rows for q in r['q']})
    bs = sorted({b for rows in (source, child) for r in rows for b in (r.get('b0'), r.get('bc')) if b is not None})
    if any(type(i) is not int or i < 0 for i in qs+bs+list(zeros)+list(private)):
        raise NotEntered('wire/record ids must be nonnegative integers')
    if not set(zeros) <= set(qs) or not set(private) <= set(bs):
        raise NotEntered('entry/private declarations must belong to the interface')
    roots = sorted(set(maps[0].values()) | set(maps[1].values()))
    labels = [f'q:{q}' for q in qs if q not in zeros]+[f'b:{b}' for b in bs if b not in private]+[f'm:{s}' for s in roots]
    if len(labels) > MAX_VARIABLES:
        raise NotEntered('symbolic variable cap128')
    variables = {label: frozenset({1 << i}) for i, label in enumerate(labels)}
    return qs, bs, labels, variables, maps


def execute(records, qs, bs, variables, labels, zeros, private, mapping):
    qstate = {q: ZERO if q in zeros else variables[f'q:{q}'] for q in qs}
    bstate = {b: ZERO if b in private else variables[f'b:{b}'] for b in bs}
    written_private = set()
    stack = []
    phase = {}
    for i, r in enumerate(records):
        code = r['code']
        base = code & 127
        q = r['q']
        bit, condition = r.get('b0'), r.get('bc')
        if len(q) != len(set(q)):
            raise NotEntered(f'op{i}: repeated quantum operands')
        if bool(code & 128) != (condition is not None):
            raise NotEntered(f'op{i}: malformed condition encoding')
        if condition in private and condition not in written_private:
            raise NotEntered(f'op{i}: private record read before definite write')
        if code == K.PUSH_CONDITION:
            stack.append(bstate[condition])  # Immutable snapshot, not its record id.
            continue
        if code == K.POP_CONDITION:
            if not stack:
                raise NotEntered(f'op{i}: inherited/unbalanced condition')
            stack.pop()
            continue
        guard = product(*stack, bstate[condition] if condition is not None else ONE)
        if base == K.INFO_TAG:
            continue
        arity = {0x00: 0, 0x10: 1, 0x11: 1, 0x12: 1, 0x13: 1,
                 0x20: 2, 0x21: 2, 0x22: 2, 0x30: 3, 0x31: 3, 0x32: 3,
                 0x40: 0, 0x41: 0, 0x42: 0, 0x50: 1}
        if base not in arity or len(q) != arity[base]:
            raise NotEntered(f'op{i}: unsupported opcode/arity{code}')
        if base in (0x40, 0x41, 0x42, 0x50) and bit not in bstate:
            raise NotEntered(f'op{i}: missing record output')
        if base not in (0x40, 0x41, 0x42, 0x50) and bit is not None:
            raise NotEntered(f'op{i}: unexpected record output')
        if base == 0x11:
            qstate[q[0]] = xor(qstate[q[0]], guard)
        elif base in (0x21, 0x31):
            delta = product(guard, *(qstate[w] for w in q[:-1]))
            qstate[q[-1]] = xor(qstate[q[-1]], delta)
        elif base in (0x22, 0x32):
            delta = product(guard, qstate[q[0]] if base == 0x32 else ONE,
                            xor(qstate[q[-2]], qstate[q[-1]]))
            for w in q[-2:]:
                qstate[w] = xor(qstate[w], delta)
        elif base == K.HMR:
            outcome = variables['m:'+mapping[i]]
            F.phase_add(phase, product(guard, outcome, qstate[q[0]]), F.HALF)
            qstate[q[0]] = xor(qstate[q[0]], product(guard, qstate[q[0]]))
            bstate[bit] = xor(bstate[bit], product(guard, xor(bstate[bit], outcome)))
            if bit in private and guard == ONE:
                written_private.add(bit)
        elif base == K.R:
            if product(guard, qstate[q[0]]):
                raise NotEntered(f'op{i}: dirty reset has an unmodeled random phase')
        elif base in (0x40, 0x41, 0x42):
            if bit in private and base == 0x42 and bit not in written_private:
                raise NotEntered(f'op{i}: private invert before definite write')
            delta = ONE if base == 0x42 else xor(bstate[bit], ONE if base == 0x41 else ZERO)
            bstate[bit] = xor(bstate[bit], product(guard, delta))
            if bit in private and guard == ONE and base in (0x40, 0x41):
                written_private.add(bit)
        else:
            normalized = dict(r, code=base)
            angle = F.angle(normalized)
            if angle is None:
                raise NotEntered(f'op{i}: unsupported phase')
            F.phase_add(phase, product(guard, *(qstate[w] for w in q)), angle)
    if stack:
        raise NotEntered('unbalanced outgoing condition stack')
    return dict(quantum=qstate, records={b: v for b, v in bstate.items() if b not in private}, phase=phase)


def serialize(signature):
    return dict(quantum={str(w): [hex(m) for m in sorted(p)] for w, p in signature['quantum'].items()},
                records={str(w): [hex(m) for m in sorted(p)] for w, p in signature['records'].items()},
                phase={hex(m): f'{v:032x}' for m, v in sorted(signature['phase'].items())})


def witness(left, right, labels):
    for kind in ('quantum', 'records'):
        for w in left[kind]:
            difference = left[kind][w] ^ right[kind][w]
            if difference:
                monomial = min(difference, key=lambda m: (m.bit_count(), m))
                return dict(kind=kind, wire=w, ones=[label for j, label in enumerate(labels) if monomial >> j & 1])
    difference = {m: (left['phase'].get(m, 0)-right['phase'].get(m, 0)) % F.MOD
                  for m in set(left['phase']) | set(right['phase'])}
    difference = {m: v for m, v in difference.items() if v}
    if difference:
        monomial = min(difference, key=lambda m: (m.bit_count(), m))
        return dict(kind='phase', ones=[label for j, label in enumerate(labels) if monomial >> j & 1],
                    modulus_bits=128)
    return None


def compare(source, child, *, zero_qubits=(), private_records=(), outcomes=None, inherited_conditions=()):
    if inherited_conditions or any(rows and rows[0].get('condition_depth', 0) for rows in (source, child)):
        raise NotEntered('inherited guard snapshots need a separate caller contract')
    zeros, private = set(zero_qubits), set(private_records)
    try:
        qs, bs, labels, variables, maps = inputs(source, child, zeros, private, outcomes)
        left, right = [execute(rows, qs, bs, variables, labels, zeros, private, mapping)
                       for rows, mapping in zip((source, child), maps)]
    except (F.Barrier, KeyError, TypeError) as error:
        raise NotEntered(str(error)) from error
    counterexample = witness(left, right, labels)
    signatures = [serialize(s) for s in (left, right)]
    return dict(schema='ssr-measured-component-proof-v1', tier='local prescreen',
                equivalent=counterexample is None, counterexample=counterexample,
                variables=labels, zero_qubits=sorted(zeros), private_records=sorted(private),
                outcome_mapping=outcomes, phase_modulus_bits=128,
                signature_sha256=[hashlib.sha256(canonical(s)).hexdigest() for s in signatures],
                signatures=signatures, full_task_admission='pending',
                scope='Exact sufficient aligned-outcome instrument proof, conditional on declared entry zeros and private-record interface; no caller or task admission')
