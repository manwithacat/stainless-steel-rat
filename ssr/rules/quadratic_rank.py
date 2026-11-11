#!/usr/bin/env python3
"""Deterministic all-entry quadratic-rank rewrite for one-target CCX windows.

Only X/CX/SWAP and unconditional CCX are admitted. The target cannot be a
control or swapped. Other wires evolve affinely, so the target's quadratic
toggle has an exact alternating matrix. Hyperbolic elimination gives a
rank/2-product implementation; all other terms are free affine gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import kickmix as km  # noqa: E402
from ssr.qhdl import bitsim as B  # noqa: E402
from ssr.qhdl import window as W  # noqa: E402


def _hash(b):
    return hashlib.sha256(b).hexdigest()


def load(source):
    lines = str(km.Circuit.from_file(str(source))).splitlines()
    header, op_lines, ops = [], [], []
    nq = int(km.Circuit.from_file(str(source)).num_qubits)
    for line in lines:
        if line.startswith(("REGISTER ", "APPEND_TO_REGISTER ")):
            header.append(line)
        else:
            op_lines.append(line)
            ops.append(B.parse_line(line))
    return header, op_lines, ops, nq


def rank(rows):
    basis = {}
    for v in rows:
        while v:
            p = v.bit_length() - 1
            if p not in basis:
                basis[p] = v
                break
            v ^= basis[p]
    return len(basis)


def quadratic(ops, lo, hi, target, nq, depth, min_ccx=2, phase_transparent=False):
    if len(depth) and depth[lo] != 0:
        return None, "inherited_condition"
    forms = [1 << i for i in range(nq)]
    const = [0] * nq
    H = [0] * nq
    linear = 0
    scalar = 0
    charged = 0
    for i in range(lo, hi):
        o = ops[i]
        diagonal = o.code in (B.C_Z, B.C_CZ, B.C_CCZ, B.C_ZPOW, B.C_NEG)
        bit_only = o.code in (B.C_BINV, B.C_BST0, B.C_BST1)
        if o.cond >= 0 and not (phase_transparent and (diagonal or bit_only)):
            return None, "conditional_gate"
        if o.code == B.C_INFO:
            continue
        if o.code == B.C_X:
            q = o.q[0]
            if q == target:
                scalar ^= 1
            else:
                const[q] ^= 1
        elif o.code == B.C_CX:
            a, b = o.q
            if a == target:
                return None, "target_as_control"
            if b == target:
                linear ^= forms[a]
                scalar ^= const[a]
            else:
                forms[b] ^= forms[a]
                const[b] ^= const[a]
        elif o.code == B.C_SWAP:
            a, b = o.q
            if target in (a, b):
                return None, "target_swapped"
            forms[a], forms[b] = forms[b], forms[a]
            const[a], const[b] = const[b], const[a]
        elif o.code == B.C_CCX:
            a, b, t = o.q
            if t != target or target in (a, b):
                return None, "other_ccx_target_or_control"
            f, g = forms[a], forms[b]
            cf, cg = const[a], const[b]
            charged += 1
            linear ^= (f & g) ^ (g if cf else 0) ^ (f if cg else 0)
            scalar ^= cf & cg
            for bit in range(nq):
                if f >> bit & 1:
                    H[bit] ^= g
                if g >> bit & 1:
                    H[bit] ^= f
        elif phase_transparent and o.code in (B.C_R, B.C_HMR):
            q = o.q[0]
            if q == target:
                return None, "target_measured_or_reset"
            forms[q], const[q] = 0, 0
        elif phase_transparent and diagonal:
            if target in o.q:
                return None, "target_phase_operand"
        elif phase_transparent and bit_only:
            pass
        else:
            return None, "phase_or_unsupported_gate"
    if charged < min_ccx:
        return None, "fewer_than_two_ccx"
    assert all(not (H[i] >> i & 1) for i in range(nq))
    if not phase_transparent:
        assert rank([forms[q] for q in range(nq) if q != target]) == nq - 1
    r = rank(H)
    assert r % 2 == 0
    return {"H": H, "linear": linear, "scalar": scalar, "ccx": charged,
            "rank": r, "floor": r // 2, "saving": charged - r // 2}, None


def decompose(H):
    """H = sum_i f_i g_i^T + g_i f_i^T; pairs have exclusive pivots."""
    rows = list(H)
    n = len(rows)
    pairs = []
    while True:
        i = next((i for i, row in enumerate(rows) if row), None)
        if i is None:
            break
        j = (rows[i] & -rows[i]).bit_length() - 1
        f = sum(((rows[k] >> j) & 1) << k for k in range(n))
        g = sum(((rows[k] >> i) & 1) << k for k in range(n))
        assert (f >> i & 1, g >> i & 1, f >> j & 1, g >> j & 1) == (1, 0, 0, 1)
        pairs.append((i, j, f, g))
        for k in range(n):
            if f >> k & 1:
                rows[k] ^= g
            if g >> k & 1:
                rows[k] ^= f
    assert all(v == 0 for v in rows)
    assert len(pairs) == rank(H) // 2
    return pairs


def recipe(ops, lo, hi, target, nq, depth, phase_transparent=False):
    poly, reason = quadratic(ops, lo, hi, target, nq, depth, phase_transparent=phase_transparent)
    if reason:
        return None, reason
    if poly["saving"] <= 0:
        return None, "no_formal_saving"
    pairs = decompose(poly["H"])
    kept = [o.text for o in ops[lo:hi] if o.code != B.C_CCX]
    baseline, reason = quadratic([B.parse_line(s) for s in kept], 0, len(kept), target, nq,
                                 [0] * len(kept), min_ccx=0, phase_transparent=phase_transparent)
    assert reason is None and not any(baseline["H"])
    correction = poly["linear"] ^ baseline["linear"]
    scalar_correction = poly["scalar"] ^ baseline["scalar"]
    added = []
    for i, j, f, g in pairs:
        assert i != target and j != target
        pre = [f"CX q{k} q{i}" for k in range(nq) if k != i and (f >> k & 1)]
        pre += [f"CX q{k} q{j}" for k in range(nq) if k != j and (g >> k & 1)]
        added += pre + [f"CCX q{i} q{j} q{target}"] + pre[::-1]
        correction ^= f & g
    added += [f"CX q{k} q{target}" for k in range(nq) if correction >> k & 1]
    if scalar_correction:
        added.append(f"X q{target}")
    candidate = added + kept
    # Exact symbolic all-entry equivalence, including the affine map on every other wire.
    new_ops = [B.parse_line(s) for s in candidate]
    fresh, reason = quadratic(new_ops, 0, len(new_ops), target, nq, [0] * len(new_ops),
                              min_ccx=0, phase_transparent=phase_transparent)
    assert reason is None
    assert fresh["H"] == poly["H"] and fresh["linear"] == poly["linear"] and fresh["scalar"] == poly["scalar"]
    assert fresh["ccx"] == poly["floor"]
    return {"ops": candidate, "source_ccx": poly["ccx"], "new_ccx": poly["floor"],
            "saving": poly["saving"], "rank": poly["rank"], "pairs": [list(p) for p in pairs],
            "affine_correction": correction, "constant_correction": scalar_correction,
            "proof": ("formal GF(2) target polynomial equality on arbitrary interval-entry bits; "
                      "all non-target state/phase/record operations retained in source order and target never read by them"
                      if phase_transparent else
                      "formal GF(2) polynomial equality on arbitrary interval-entry bits; same other-wire affine map; no phase or records in interval")}, None


def census(source, *, size=10, span=512, phase_transparent=False):
    source = Path(source)
    sha = _hash(source.read_bytes())
    header, lines, ops, nq = load(source)
    if len(ops) > 200_000 or nq > 256:
        raise ValueError("rule cap: <=200000 ops and <=256 qubits")
    depth = W.Liveness(ops).depth
    hits = []
    tested = 0
    admitted = 0
    skipped = Counter()
    for lo, ends in W.candidate_windows(ops, size=size, span=span).items():
        if phase_transparent and ops[lo].code != B.C_CCX:
            continue
        target = ops[lo].q[-1]
        for hi in ends[1:]:
            tested += 1
            poly, reason = quadratic(ops, lo, hi, target, nq, depth,
                                     phase_transparent=phase_transparent)
            if reason:
                skipped[reason] += 1
                continue
            admitted += 1
            if poly["saving"] <= 0:
                continue
            handle = _hash(json.dumps({"source": sha, "ops": [lo, hi], "text": lines[lo:hi],
                                       "phase_transparent": phase_transparent}, sort_keys=True).encode())
            hits.append({"handle": handle, "ops": [lo, hi], "target": target,
                         "ccx": poly["ccx"], "floor": poly["floor"], "saving": poly["saving"]})
    return {"source_sha256": sha, "nq": nq, "op_count": len(ops), "size": size, "span": span,
            "phase_transparent": phase_transparent,
            "windows_tested": tested, "admissible_windows": admitted,
            "skip_reasons": dict(skipped), "hits": hits,
            "scope": "static exact formal affine-factor rule; whole-circuit verifier required for emitted candidates"}


def emit(source, out, handle, *, size=10, span=512, phase_transparent=False):
    source, out = Path(source), Path(out)
    if out.exists():
        raise ValueError("refuse to overwrite output")
    catalog = census(source, size=size, span=span, phase_transparent=phase_transparent)
    hit = next((h for h in catalog["hits"] if h["handle"] == handle), None)
    if hit is None:
        raise ValueError("unknown or stale source-bound handle")
    header, lines, ops, nq = load(source)
    lo, hi = hit["ops"]
    result, reason = recipe(ops, lo, hi, hit["target"], nq, W.Liveness(ops).depth,
                            phase_transparent=phase_transparent)
    if reason:
        raise ValueError(reason)
    edited = lines[:lo] + result["ops"] + lines[hi:]
    out.parent.mkdir(parents=True, exist_ok=True)
    km.Circuit("\n".join(header + edited) + "\n").to_file(str(out), format="kmb")
    receipt = {"source_sha256": catalog["source_sha256"], "candidate_sha256": _hash(out.read_bytes()),
               "handle": handle, "site": hit, "phase_transparent": phase_transparent,
               "recipe": {k: v for k, v in result.items() if k != "ops"},
               "validation_needed": "native all-input, HMR history and unchanged official-local verifier"}
    out.with_suffix(out.suffix + ".rule.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--handle")
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--span", type=int, default=512)
    p.add_argument("--phase-transparent", action="store_true",
                   help="admit non-target reset/HMR/phase/record gates; keep their stream in place")
    a = p.parse_args()
    if a.handle:
        print(json.dumps(emit(a.source, a.out, a.handle, size=a.size, span=a.span,
                              phase_transparent=a.phase_transparent), indent=2))
    else:
        if a.out.exists():
            p.error("refuse to overwrite output")
        result = census(a.source, size=a.size, span=a.span,
                        phase_transparent=a.phase_transparent)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: result[k] for k in ("source_sha256", "windows_tested", "hits")}, indent=2))


if __name__ == "__main__":
    main()
