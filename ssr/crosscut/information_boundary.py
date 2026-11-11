"""Locate when an idle wire stops being determined by the other quantum wires.

Exact over every legal invsqrt input in one fixed deterministic HMR outcome
model. This is a read-only information test, not an optimization action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np


from ssr.crosscut import rule


def _state_keys(q: np.ndarray, n: int, excluded: set[int]) -> np.ndarray:
    """Pack all non-target wire values into one or more uint64 keys per row."""
    blocks = (len(q) + 63) // 64
    keys = np.zeros((n, blocks), dtype=np.uint64)
    for wire in range(len(q)):
        if wire in excluded:
            continue
        keys[:, wire // 64] |= rule.B.unpack_bits(q[wire], n).astype(np.uint64) << np.uint64(wire % 64)
    return keys


def information_test(q: np.ndarray, rows: np.ndarray, wire: int,
                     extra_exclude: tuple[int, ...] = ()) -> dict:
    """Return exact collision count and one conflicting legal-input pair."""
    n = len(rows)
    keys = _state_keys(q, n, set(extra_exclude) | {wire})
    if keys.shape[1] == 1:
        order = np.argsort(keys[:, 0], kind="stable")
        sorted_keys = keys[order, 0]
        same = sorted_keys[1:] == sorted_keys[:-1]
    else:
        packed = np.ascontiguousarray(keys).view(np.dtype(f"V{keys.shape[1] * 8}")).reshape(-1)
        order = np.argsort(packed, kind="stable")
        sorted_keys = packed[order]
        same = sorted_keys[1:] == sorted_keys[:-1]
    target = rule.B.unpack_bits(q[wire], n)[order]
    bad = np.flatnonzero(same & (target[1:] != target[:-1]))
    if not len(bad):
        return {"determined": True, "conflicting_keys": 0, "witness": None}
    witness = int(bad[0])
    # Count unique keys with both target values, rather than adjacent flips.
    conflict_keys = int(np.unique(sorted_keys[bad + 1]).size)
    return {"determined": False, "conflicting_keys": conflict_keys,
            "witness": {"x0": int(rows[order[witness]]), "x1": int(rows[order[witness + 1]]),
                        "wire_value_x0": int(target[witness]),
                        "wire_value_x1": int(target[witness + 1]),
                        "other_wire_state_equal": True}}


def locate(source: Path, wire: int, start: int, stop: int) -> dict:
    source = Path(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    k, ops, xq = rule.source_ops(source)
    if len(xq) != 22:
        raise ValueError("this exact-domain query currently requires invsqrt's 22 input wires")
    if not 0 <= wire < k.num_qubits or not 0 <= start < stop <= len(ops):
        raise ValueError("wire or operation boundaries outside source")
    if any(wire in op.q for op in ops[start:stop]):
        raise ValueError("target wire is touched inside the proposed idle gap")
    rows = rule.B.legal_rows()
    checks = []
    begin = time.monotonic()

    def check(cut: int) -> dict:
        sim = rule.B.BitSim(ops, rows=rows, num_qubits=k.num_qubits, x_qubits=xq, outcome="zero")
        sim.run(stop=cut)
        result = {"cut": cut, **information_test(sim.q, rows, wire)}
        checks.append(result)
        return result

    first = check(start)
    last = check(stop)
    out = {"source_sha256": source_hash, "wire": wire, "idle_cuts": [start, stop],
           "legal_inputs": len(rows), "outcome_model": "zero", "checks": checks,
           "status": None, "scope": "all legal invsqrt x, deterministic zero HMR outcomes; other quantum wires only"}
    if not first["determined"]:
        out["status"] = "already_information_bearing"
    elif last["determined"]:
        out["status"] = "determined_through_gap"
    else:
        lo, hi = start, stop
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            result = check(mid)
            if result["determined"]:
                lo = mid
            else:
                hi = mid
        before = first if lo == start else next(r for r in checks if r["cut"] == lo)
        after = last if hi == stop else next(r for r in checks if r["cut"] == hi)
        out.update({"status": "first_information_loss", "last_determined_cut": lo,
                    "first_undetermined_cut": hi, "loss_operation": hi - 1,
                    "loss_operation_syntax": ops[hi - 1].text,
                    "before": before, "after": after})
        operation = ops[hi - 1]
        if operation.code in (rule.B.C_HMR, rule.B.C_R) and len(operation.q) == 1:
            removed_wire = operation.q[0]
            pre = rule.B.BitSim(ops, rows=rows, num_qubits=k.num_qubits, x_qubits=xq, outcome="zero")
            pre.run(stop=lo)
            without = information_test(pre.q, rows, wire, extra_exclude=(removed_wire,))
            out["boundary_carrier_test"] = {"removed_wire": removed_wire,
                                             "status": "carrier_required" if not without["determined"] else "carrier_not_required_alone",
                                             **without,
                                             "scope": "counterfactual exclusion of measured/reset wire from the pre-operation state"}
    out["wall_seconds"] = round(time.monotonic() - begin, 3)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--wire", type=int, required=True)
    p.add_argument("--start", type=int, required=True, help="cut immediately after the last target touch")
    p.add_argument("--stop", type=int, required=True, help="cut immediately before the next target touch")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    payload = json.dumps(locate(a.source, a.wire, a.start, a.stop), indent=2) + "\n"
    if a.out:
        a.out.write_text(payload)
    else:
        print(payload, end="")
