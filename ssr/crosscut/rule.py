"""Agent-first long-gap quadratic reconstruction query for invsqrt KMBs.

Read-only discovery and proof screen. The returned action is constructed by
the guarded RAT park_factored action; it still needs native and official gates.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from ssr.qhdl import kmb as K
from ssr.qhdl import lifetime_allocator as A
from ssr.qhdl import bitsim as B
from ssr.crosscut import gap_census as G
from ssr.rules import reachable_cswap as CS


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bit_ids(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def source_ops(path: Path):
    k = K.read(str(path))
    if k.num_qubits > 260:
        raise ValueError("quadratic cross-cut screen is limited to 260 qubits")
    ops, _, xq, nq = CS._ops(path)
    if nq != k.num_qubits:
        raise ValueError("KMB decoders disagree on width")
    return k, ops, xq


def census(path: Path, top: int = 20) -> dict:
    path = Path(path)
    k = K.read(str(path))
    reset, depth = A.reset_ops(k)
    refs, qs, order, _ = A.references(k)
    regs = A.register_qubits(k)
    iv = A.build_intervals(k, refs, qs, order, reset, depth, regs)
    profile = A.live_profile(iv, len(k.op_types), regs, register_gaps=False)
    peak = int(profile.max())
    peak_ops = set(map(int, np.flatnonzero(profile == peak)))
    runs = G._runs(peak_ops)
    raw = G._gap_candidates(k, iv, regs, peak_ops, runs)
    sites = []
    source_hash = sha(path)
    for gap in raw:
        wire, after, before = (int(gap[x]) for x in ("target_wire", "after_op", "before_op"))
        cover = [i for i, run in enumerate(runs) if after < run["start"] and before > run["end"]]
        if not cover or before >= len(depth) or int(depth[after + 1]) != 0 or int(depth[before]) != 0:
            continue
        key = f"{source_hash}:{wire}:{after}:{before}"
        sites.append({"handle": hashlib.sha256(key.encode()).hexdigest(), "wire": wire,
                      "after": after, "before": before, "peak_runs_covered": len(cover),
                      "peak_ops_covered": sum(runs[i]["end"] - runs[i]["start"] + 1 for i in cover)})
    sites.sort(key=lambda s: (-s["peak_runs_covered"], -s["peak_ops_covered"], s["after"], s["wire"]))
    return {"source_sha256": source_hash, "Q": int(k.num_qubits), "peak": peak,
            "peak_run_count": len(runs), "site_count": len(sites), "sites": sites[:top],
            "truncated": len(sites) > top,
            "scope": "static idle gaps and allocator peak coverage; value relation unproved"}


def affine_basis(values):
    pivots = {}
    for wire, vector in values:
        v, mask = vector, 1 << wire
        while v:
            p = v.bit_length() - 1
            if p not in pivots:
                pivots[p] = (v, mask)
                break
            old, oldmask = pivots[p]
            v ^= old
            mask ^= oldmask
    return list(pivots.values())


def solve_quadratic(target: int, later: np.ndarray, valid: np.ndarray, excluded: int) -> dict | None:
    vals = [(i, int.from_bytes(later[i].tobytes(), "little")) for i in range(len(later)) if i != excluded]
    basis = affine_basis(vals)
    n = len(basis)
    if n > 260:
        raise ValueError("basis too large")
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    const = int.from_bytes(valid.tobytes(), "little")
    features = [(v, 1 << i) for i, (v, _) in enumerate(basis)]
    features.append((const, 1 << n))
    features.extend((basis[i][0] & basis[j][0], 1 << (n + 1 + k)) for k, (i, j) in enumerate(pairs))
    pivots = {}
    for vector, initial_mask in features:
        v, mask = vector, initial_mask
        while v:
            p = v.bit_length() - 1
            if p not in pivots:
                pivots[p] = (v, mask)
                break
            old, oldmask = pivots[p]
            v ^= old
            mask ^= oldmask
    v, mask = target, 0
    while v:
        p = v.bit_length() - 1
        if p not in pivots:
            return None
        old, oldmask = pivots[p]
        v ^= old
        mask ^= oldmask
    physical = [basis[i][1] for i in range(n)]
    linear = 0
    constant = bool(mask >> n & 1)
    adj = [0] * len(later)
    for i in range(n):
        if mask >> i & 1:
            linear ^= physical[i]
    for k, (i, j) in enumerate(pairs):
        if not mask >> (n + 1 + k) & 1:
            continue
        left, right = physical[i], physical[j]
        linear ^= left & right
        for u in bit_ids(left):
            for w in bit_ids(right):
                if u != w:
                    adj[u] ^= 1 << w
                    adj[w] ^= 1 << u
    return {"linear": linear, "constant": constant, "adj": adj,
            "affine_basis_rank": n + 1, "quadratic_feature_rank": len(pivots)}


def evaluate(poly: dict, q: np.ndarray, valid: np.ndarray) -> np.ndarray:
    value = valid.copy() if poly["constant"] else np.zeros(len(valid), np.uint64)
    for u in bit_ids(poly["linear"]):
        value ^= q[u]
    for u, row in enumerate(poly["adj"]):
        for v in bit_ids(row & ~((1 << (u + 1)) - 1)):
            value ^= q[u] & q[v]
    return value


def xor_product(poly: dict, u: int, v: int) -> None:
    for a in bit_ids(u):
        for b in bit_ids(v):
            if a == b:
                poly["linear"] ^= 1 << a
            else:
                poly["adj"][a] ^= 1 << b
                poly["adj"][b] ^= 1 << a


def factor(poly: dict) -> tuple[list[tuple[int, int]], int, bool]:
    work = {"linear": poly["linear"], "constant": poly["constant"], "adj": list(poly["adj"])}
    products = []
    while any(work["adj"]):
        i = next(i for i, row in enumerate(work["adj"]) if row)
        j = next(bit_ids(work["adj"][i]))
        u = (1 << i) | (work["adj"][j] & ~(1 << i))
        v = (1 << j) | (work["adj"][i] & ~(1 << j))
        xor_product(work, u, v)
        if work["adj"][i] or work["adj"][j]:
            raise AssertionError("quadratic elimination failed")
        products.append((u, v))
    return products, work["linear"], work["constant"]


def factor_one_scratch(poly: dict) -> tuple[list[tuple[int, int]], int, bool]:
    """Greedy physical-wire factorization: one scratch, one CCX per factor.

    This is a cost estimate for a possible one-scratch reconstruction, not
    an emitted circuit or proof of a width reduction.
    """
    work = {"linear": poly["linear"], "constant": poly["constant"], "adj": list(poly["adj"])}
    products = []
    while any(work["adj"]):
        i = max(range(len(work["adj"])), key=lambda v: (work["adj"][v].bit_count(), -v))
        right = work["adj"][i]
        xor_product(work, 1 << i, right)
        if work["adj"][i]:
            raise AssertionError("single-wire quadratic elimination failed")
        products.append((1 << i, right))
    return products, work["linear"], work["constant"]


def one_scratch_factor_count(poly: dict) -> int:
    return len(factor_one_scratch(poly)[0])


def _cut_values(ops, rows, nq, xq, wire, after, before, branch):
    sim = B.BitSim(ops, rows=rows, num_qubits=nq, x_qubits=xq, outcome=branch)
    sim.run(stop=after + 1)
    target = sim.q[wire].copy()
    sim.run(stop=before)
    return target, sim.q, sim.valid


def _full_check(ops, nq, xq, site, poly, branch):
    rows = B.legal_rows()
    target, q, valid = _cut_values(ops, rows, nq, xq, site["wire"], site["after"], site["before"], branch)
    difference = target ^ evaluate(poly, q, valid)
    mask = np.unpackbits(difference.view(np.uint8), bitorder="little")[:len(rows)]
    return rows[np.flatnonzero(mask)]


def _scratch(k, before, support):
    reset, depth = A.reset_ops(k)
    refs, qs, order, _ = A.references(k)
    regs = A.register_qubits(k)
    iv = A.build_intervals(k, refs, qs, order, reset, depth, regs)
    live_intervals = (iv["s"] <= before) & (iv["e"] >= before)
    live = set(map(int, iv["sq"][live_intervals[iv["interval_id"]]])) | set(regs)
    available = sorted(set(range(int(k.num_qubits))) - live - set(bit_ids(support)), reverse=True)
    return available[:2]


def fit(path: Path, site: dict, sample_size: int = 8192, max_products: int = 8) -> dict:
    path = Path(path)
    source_hash = sha(path)
    expected_handle = hashlib.sha256(f"{source_hash}:{site['wire']}:{site['after']}:{site['before']}".encode()).hexdigest()
    if site.get("handle") != expected_handle:
        raise ValueError("stale or forged site handle")
    k, ops, xq = source_ops(path)
    if int(k.num_qubits) != site.get("Q", int(k.num_qubits)):
        raise ValueError("site width mismatch")
    rng = np.random.default_rng(20261108)
    rows = np.sort(rng.choice(B.legal_rows(), size=sample_size, replace=False))
    rounds = []
    for iteration in range(3):
        target, q, valid = _cut_values(ops, rows, int(k.num_qubits), xq, site["wire"], site["after"], site["before"], "zero")
        polynomial = solve_quadratic(int.from_bytes(target.tobytes(), "little"), q, valid, site["wire"])
        if polynomial is None:
            return {"status": "no_quadratic_fit", "source_sha256": source_hash,
                    "site": site, "rounds": rounds, "sample_rows": len(rows)}
        sample_error = int(np.bitwise_count(target ^ evaluate(polynomial, q, valid)).sum())
        if sample_error:
            raise AssertionError("quadratic solver did not reproduce its fit sample")
        mismatch = _full_check(ops, int(k.num_qubits), xq, site, polynomial, "zero")
        rounds.append({"iteration": iteration, "sample_rows": len(rows),
                       "quadratic_feature_rank": polynomial["quadratic_feature_rank"],
                       "full_zero_mismatches": len(mismatch)})
        if not len(mismatch):
            break
        if iteration == 2 or len(mismatch) > 4096 or len(rows) + len(mismatch) > 16384:
            return {"status": "counterexample_budget", "source_sha256": source_hash,
                    "site": site, "rounds": rounds}
        rows = np.unique(np.r_[rows, mismatch])
    other = {str(branch): len(_full_check(ops, int(k.num_qubits), xq, site, polynomial, branch)) for branch in (7, 101)}
    if any(other.values()):
        return {"status": "outcome_model_mismatch", "source_sha256": source_hash,
                "site": site, "rounds": rounds, "other_mismatches": other}
    products, linear, constant = factor(polynomial)
    support = linear
    for u, v in products:
        support |= u | v
    scratch = _scratch(k, site["before"], support | (1 << site["wire"]))
    if len(scratch) == 1:
        products, linear, constant = factor_one_scratch(polynomial)
        kind = "park_one_scratch"
    else:
        kind = "park_factored"
    if len(products) > max_products or len(scratch) not in (1, 2):
        return {"status": "resource_limit", "source_sha256": source_hash,
                "site": site, "rounds": rounds, "products": len(products), "scratch": scratch,
                "one_scratch_ccx_estimate": one_scratch_factor_count(polynomial)}
    action = {"type": kind, "expected_source_sha256": source_hash,
              "wire": site["wire"], "after": site["after"], "before": site["before"],
              "scratch": scratch,
              "products": [{"left": list(bit_ids(u)), "right": list(bit_ids(v))} for u, v in products],
              "affine": list(bit_ids(linear)), "constant": constant}
    return {"status": "three_branch_exact", "source_sha256": source_hash,
            "site": site, "rounds": rounds, "other_mismatches": other,
            "quadratic_rank": 2 * len(products), "products": len(products),
            "scratch": scratch, "action": action,
            "scope": "all legal x in deterministic zero/7/101; all outcome histories and official verifier still required"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--top", type=int, default=20, help="number of ranked idle-gap sites to report")
    p.add_argument("--fit-index", type=int, help="zero-based rank of one site to fit")
    p.add_argument("--fit-first", action="store_true", help="alias for --fit-index 0")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    fit_index = 0 if a.fit_first else a.fit_index
    if a.top < 1 or fit_index is not None and fit_index < 0:
        p.error("--top must be positive and --fit-index nonnegative")
    result = census(a.source, top=max(a.top, fit_index + 1 if fit_index is not None else 0))
    if fit_index is not None:
        if fit_index >= len(result["sites"]):
            p.error("--fit-index exceeds the number of sites")
        result["fit_index"] = fit_index
        result["fit_result"] = fit(a.source, result["sites"][fit_index])
        if a.fit_first:
            result["fit_first"] = result["fit_result"]
    payload = json.dumps(result, indent=2) + "\n"
    if a.out:
        a.out.write_text(payload)
    else:
        print(payload, end="")
