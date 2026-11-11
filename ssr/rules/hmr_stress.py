#!/usr/bin/env python3
"""Many-history, small-input BitSim preflight before native/official verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from ssr.rules import clifford_splice as rule

SEEDS = ["zero", 7, 101] + list(range(1000, 1064))
ROWS = np.arange(1, 64, dtype=np.int64)


def reference(rows):
    roots = [math.isqrt((1 << 130) // int(x)) for x in rows]
    target = np.array([((r + 1) >> 1) & ((1 << 64) - 1) for r in roots], np.uint64)
    tol = np.array([min(r >> 25, 1 << 63) for r in roots], np.uint64)
    return target, tol


def contract(sim, target, tol):
    error = (sim.phase_units() - target).view(np.int64)
    used = np.abs(error).view(np.uint64)
    bad = np.flatnonzero(used > tol)
    return {"x_restored": sim.x_restored(), "scratch_clean": sim.scratch_clean(),
            "dirty": sim.dirty, "phase_failures": len(bad),
            "first_bad_x": int(sim.rows[bad[0]]) if len(bad) else None,
            "worst_ratio": float((used / tol).max()),
            "mean_toffoli": sim.toffoli_rows / sim.n}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--host", type=Path, required=True)
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--host-sha", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error(f"refuse overwrite: {a.out}")
    if rule.sha(a.candidate) != a.candidate_sha or rule.sha(a.host) != a.host_sha:
        p.error("source SHA drift")
    co, ch, cx, cn = rule.CS._ops(a.candidate)
    ho, hh, hx, hn = rule.CS._ops(a.host)
    if (ch, cx, cn) != (hh, hx, hn):
        p.error("register interface mismatch")
    target, tol = reference(ROWS)
    receipt = {"schema": "rat-hmr-stress/1", "candidate_sha256": a.candidate_sha,
               "host_sha256": a.host_sha, "rows": ROWS.tolist(),
               "rows_sha256": hashlib.sha256(ROWS.tobytes()).hexdigest(),
               "seeds": SEEDS, "result": [], "first_divergence": None,
               "first_candidate_contract_failure": None}
    # A synthetic phase-flip control independent of the source circuit.
    synthetic = rule.B.BitSim(ho + [rule.B.parse_line("Z q0")], rows=ROWS,
                              num_qubits=hn, x_qubits=hx, outcome="zero").run()
    assert contract(synthetic, target, tol)["phase_failures"] > 0
    receipt["synthetic_phase_flip_control"] = "pass"
    for seed in SEEDS:
        candidate = rule.B.BitSim(co, rows=ROWS, num_qubits=cn, x_qubits=cx,
                                  outcome=seed, count_toffoli=True).run()
        host = rule.B.BitSim(ho, rows=ROWS, num_qubits=hn, x_qubits=hx,
                             outcome=seed, count_toffoli=True).run()
        c = contract(candidate, target, tol)
        h = contract(host, target, tol)
        same_q = np.array_equal(candidate.q, host.q)
        same_phase = np.array_equal(candidate.phase_units(), host.phase_units())
        entry = {"seed": seed, "candidate": c, "host": h,
                 "same_final_quantum": bool(same_q), "same_final_phase": bool(same_phase)}
        receipt["result"].append(entry)
        if receipt["first_divergence"] is None and (not same_q or not same_phase):
            qdiff = np.bitwise_or.reduce(candidate.q ^ host.q, axis=0)
            pdiff = candidate.phase_units() != host.phase_units()
            nz = np.flatnonzero(rule.B.unpack_bits(qdiff, len(ROWS)) | pdiff)
            receipt["first_divergence"] = {"seed": seed, "x": int(ROWS[nz[0]]) if len(nz) else None,
                                           "quantum": not same_q, "phase": not same_phase}
        if receipt["first_candidate_contract_failure"] is None and (not c["x_restored"] or
                not c["scratch_clean"] or c["dirty"] or c["phase_failures"]):
            receipt["first_candidate_contract_failure"] = {"seed": seed, **c}
    receipt["all_reference_pass"] = receipt["first_candidate_contract_failure"] is None
    receipt["all_pointwise_equal"] = receipt["first_divergence"] is None
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("result", "rows", "seeds")}, indent=2))


if __name__ == "__main__":
    main()
