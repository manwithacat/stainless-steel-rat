# Ported from vqcc-research ssr_quadratic_components/quadratic.py (R pathway, Apache-2.0).
"""Compact exact zero-phase quadratic value certificate, separate from Rat admission.

One packed GF(2) coefficient vector per output: constant, linear variables,
then lexicographic i<j cross terms. No sparse-monomial expansion is needed.
"""
from __future__ import annotations
import hashlib
import json


class Unsupported(ValueError):
    pass


def rank(vectors):
    basis = {}
    for v in vectors:
        while v:
            p = v.bit_length()-1
            if p not in basis:
                basis[p] = v
                break
            v ^= basis[p]
    return len(basis)


def multiply(a, b, n):
    if a == 0 or b == 0:
        return 0
    if a == 1:
        return b
    if b == 1 or a == b:
        return a
    if a ^ b == 1:
        return 0
    if (a | b) >> (n+1):
        raise Unsupported('non-affine product controls require a higher-degree backend')
    mask = (1 << n)-1
    x, y = (a >> 1) & mask, (b >> 1) & mask
    ca, cb = a & 1, b & 1
    linear = (x & y) ^ (y if ca else 0) ^ (x if cb else 0)
    cross = 0
    for i in range(n):
        offset = i*(2*n-i-1)//2
        if x >> i & 1:
            cross ^= (y >> (i+1)) << offset
        if y >> i & 1:
            cross ^= (x >> (i+1)) << offset
    return (ca & cb) ^ (linear << 1) ^ (cross << (n+1))


def signature(records, interface):
    wires = sorted(interface)
    if len(wires) != len(set(wires)) or not 1 <= len(wires) <= 256:
        raise Unsupported('quadratic backend needs1..256unique interface wires')
    n = len(wires)
    state = {w:1 << (i+1) for i, w in enumerate(wires)}
    factors = []
    for i, r in enumerate(records):
        c, q = r['code'], r['q']
        if r.get('bc') is not None or r.get('condition_depth', 0):
            raise Unsupported(f'op{i}: conditional/record interface is not certified')
        if len(q) != len(set(q)) or any(w not in state for w in q):
            raise Unsupported(f'op{i}: invalid wire interface')
        if c == 0x06:
            continue
        if c == 0x11:
            state[q[0]] ^= 1
        elif c == 0x21:
            state[q[1]] ^= state[q[0]]
        elif c == 0x22:
            state[q[0]], state[q[1]] = state[q[1]], state[q[0]]
        elif c in (0x31, 0x32):
            a = state[q[0]]
            b = state[q[1]] if c == 0x31 else state[q[1]] ^ state[q[2]]
            try:
                product = multiply(a, b, n)
            except Unsupported as error:
                raise Unsupported(f'op{i}: {error}') from error
            factors.append(dict(local_op=i, opcode=r['opcode'], controls=q[:2],
                                first_form=hex(a), second_form=hex(b),
                                first_terms=a.bit_count(), second_terms=b.bit_count()))
            if c == 0x31:
                state[q[2]] ^= product
            else:
                state[q[1]] ^= product
                state[q[2]] ^= product
        else:
            raise Unsupported(f'op{i} {r["opcode"]}: zero-phase reversible value cores only; no phase/reset/HMR/records')
    sig = dict(schema='ssr-quadratic-value-v1', interface=wires,
               coefficient_order='constant; linear in interface order; pairs i<j lexicographic',
               outputs={str(w):hex(state[w]) for w in wires},
               phase='identically zero for this supported grammar', arbitrary_dirty_entry=True)
    info = dict(wires=n, products=len(factors), factors=factors,
                nonlinear_output_rank=rank(p >> (n+1) for p in state.values()),
                maximum_output_monomials=max(p.bit_count() for p in state.values()),
                signature_sha256=hashlib.sha256(json.dumps(sig, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                scope='exact fixed-interface zero-phase quadratic value map; not a Rat admission or task verifier')
    return sig, info


def evaluate(sig, values):
    """Evaluate packed coefficients, for independent scalar control comparisons."""
    n = len(sig['interface'])
    features = 1
    bits = [int(values[w]) for w in sig['interface']]
    for i, b in enumerate(bits):
        features |= b << (i+1)
    k = n+1
    for i in range(n):
        for j in range(i+1, n):
            features |= (bits[i] & bits[j]) << k
            k += 1
    return {int(w):(int(p, 16) & features).bit_count() % 2 for w, p in sig['outputs'].items()}
