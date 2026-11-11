"""Optimistic peak-cover lower bound for a frozen cross-cut fit census.

This ignores overlap, scratch conflicts and semantic changes after edits. A
feasible cover is a research target, never an executable or verified plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp  # optional extra: pip install .[scipy]


from ssr.crosscut import rule


def peak_runs(source: Path):
    k = rule.K.read(str(source))
    reset, depth = rule.A.reset_ops(k)
    refs, qs, order, _ = rule.A.references(k)
    regs = rule.A.register_qubits(k)
    iv = rule.A.build_intervals(k, refs, qs, order, reset, depth, regs)
    profile = rule.A.live_profile(iv, len(k.op_types), regs, register_gaps=False)
    return int(profile.max()), rule.G._runs(set(map(int, np.flatnonzero(profile == profile.max()))))


def solve(source: Path, scan: Path) -> dict:
    rows = json.loads(Path(scan).read_text())
    source_hash = rule.sha(source)
    if any(r["result"]["source_sha256"] != source_hash for r in rows):
        raise ValueError("scan and circuit SHA mismatch")
    q, runs = peak_runs(source)
    out = {"source_sha256": source_hash, "Q": q, "scanned": len(rows),
           "peak_runs": len(runs), "models": {}}
    for model, allowed in (("guarded_two_or_one_scratch", {"three_branch_exact"}),
                           ("optimistic_scratch_available", {"three_branch_exact", "resource_limit"})):
        candidates = [r for r in rows if r["result"]["status"] in allowed]
        n = len(candidates)
        matrix = np.zeros((len(runs), n), dtype=np.float64)
        for j, r in enumerate(candidates):
            site = r["site"]
            for i, peak in enumerate(runs):
                if site["after"] < peak["start"] and site["before"] > peak["end"]:
                    matrix[i, j] = 1
        uncovered = np.flatnonzero(~matrix.any(axis=1)).tolist()
        report = {"candidate_count": n, "uncovered_run_indices": uncovered}
        if not uncovered and n:
            cost = np.array([r["result"]["products"] + 0.001 for r in candidates], dtype=float)
            answer = milp(cost, integrality=np.ones(n), bounds=Bounds(0, 1),
                          constraints=LinearConstraint(matrix, 1, np.inf),
                          options={"time_limit": 60, "mip_rel_gap": 0.0})
            report["solver_status"] = int(answer.status)
            report["solver_message"] = answer.message
            if answer.x is not None:
                selected = [j for j, value in enumerate(answer.x) if value > 0.5]
                report["optimistic_ccx_count"] = int(sum(candidates[j]["result"]["products"] for j in selected))
                report["selected"] = [{"rank": candidates[j]["rank"], "wire": candidates[j]["site"]["wire"],
                                       "after": candidates[j]["site"]["after"],
                                       "before": candidates[j]["site"]["before"],
                                       "products": candidates[j]["result"]["products"]} for j in selected]
        out["models"][model] = report
    out["scope"] = "Static set cover and product lower bound only; candidate interactions, scratch availability and verifier unproved"
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("scan", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    result = json.dumps(solve(a.source, a.scan), indent=2) + "\n"
    if a.out:
        a.out.write_text(result)
    else:
        print(result, end="")
