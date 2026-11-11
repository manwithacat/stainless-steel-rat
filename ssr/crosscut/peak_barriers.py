"""Map information-loss operations for idle wires across one allocator peak run."""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path

import numpy as np

from ssr.crosscut.information_boundary import locate, rule


def idle_sites(source: Path, run_index: int) -> dict:
    source = Path(source)
    k, ops, xq = rule.source_ops(source)
    reset, depth = rule.A.reset_ops(k)
    refs, qs, order, _ = rule.A.references(k)
    regs = rule.A.register_qubits(k)
    iv = rule.A.build_intervals(k, refs, qs, order, reset, depth, regs)
    profile = rule.A.live_profile(iv, len(ops), regs, register_gaps=False)
    peak = int(profile.max())
    runs = rule.G._runs(set(map(int, np.flatnonzero(profile == peak))))
    if not 0 <= run_index < len(runs):
        raise ValueError("peak run index outside source")
    run = runs[run_index]
    touches = [[] for _ in range(k.num_qubits)]
    for i, op in enumerate(ops):
        for wire in op.q:
            touches[wire].append(i)
    sites = []
    for wire, wire_touches in enumerate(touches):
        live = wire in regs or any(int(q) == wire and int(s) <= run["start"] and int(e) >= run["end"]
                                   for q, s, e in zip(iv["logical"], iv["s"], iv["e"]))
        if not live:
            continue
        pos = bisect.bisect_left(wire_touches, run["start"])
        if pos < len(wire_touches) and wire_touches[pos] <= run["end"]:
            continue
        if pos == 0 or pos == len(wire_touches):
            continue
        start, stop = wire_touches[pos - 1] + 1, wire_touches[pos]
        sites.append({"wire": wire, "start": start, "stop": stop,
                      "role": "register" if wire in regs else "scratch"})
    return {"source_sha256": rule.sha(source), "Q": int(k.num_qubits), "peak_width": peak,
            "peak_run_index": run_index, "peak_run": run, "idle_sites": sites,
            "scope": "static allocator peak and target idleness only"}


def map_barriers(source: Path, run_index: int, out: Path) -> dict:
    out = Path(out)
    if out.exists():
        raise ValueError("output exists; choose a fresh path")
    result = idle_sites(source, run_index)
    result["barriers"] = []
    for site in result["idle_sites"]:
        found = locate(source, site["wire"], site["start"], site["stop"])
        decisive = found.get("after") or found["checks"][0]
        result["barriers"].append({"site": site, "status": found["status"],
                                   "first_loss_op": found.get("loss_operation"),
                                   "loss_syntax": found.get("loss_operation_syntax"),
                                   "witness": decisive["witness"],
                                   "conflicting_keys_at_decisive_cut": decisive["conflicting_keys"],
                                   "detail": found})
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(site["wire"], found["status"], found.get("loss_operation"), flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--run", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    map_barriers(a.source, a.run, a.out)
