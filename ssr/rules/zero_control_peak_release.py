#!/usr/bin/env python3
"""Emit exact zero-control CX peak releases from an arbitrary KMB and peak cache.

Only one-idle-scratch peak runs are considered. A released wire must be
provably zero at run entry and have no in-run touch except CX control uses
already certified as no-ops by the reset/last-write sieve. The emitted R
is on |0>, and every deleted CX is identity; there is no phase or record
change. A child still needs whole-circuit verification and peak analysis.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from ssr.rules.zero_control_cx import K, scan


def class_counts(t):
    q = t & 0x30
    return [int(np.count_nonzero(q == code)) for code in (0x30, 0x20, 0x10)]


def constructor(path: Path, peak_path: Path):
    peak = json.loads(peak_path.read_text())
    k = K.read(str(path))
    t = k.op_types
    idle = defaultdict(set)
    for gap in peak["idle_all"]:
        if gap["role"] != "scratch":
            continue
        lo, hi = (int(x[1:]) for x in gap["runs"].split(".."))
        for run in range(lo, hi + 1):
            idle[run].add(int(gap["wire"][1:]))
    selected = [(i, row) for i, row in enumerate(peak["run_rows"])
                if len(idle[i]) == 1]
    starts = [row["start"] for _, row in selected]
    if not starts:
        raise ValueError("no one-idle scratch peak runs")
    sieve = scan(path, len(t), (min(starts), max(row["end"] for _, row in selected) + 1),
                 max_events=len(t), cuts=starts)
    if sieve["source_sha256"] != peak["input_sha256"] or sieve["events_truncated"]:
        raise ValueError("source/peak mismatch or truncated zero-control events")
    zero_cx = {e["op"] for e in sieve["events"] if e["kind"] == "CX"}
    input_wires = {qid for _, contents in k.registers
                   for is_qubit, qid, _ in contents if is_qubit}
    scratch = set(range(k.num_qubits)) - input_wires
    streams = {name: k.stream(name) for name in
               ("qqq0", "qqq1", "qqq2", "qq0", "qq1", "q0")}
    cursor, offsets = 0, [0, 0, 0]
    admitted, rejected = [], []
    for run, row in selected:
        a, b = row["start"], row["end"] + 1
        offsets = [x + y for x, y in zip(offsets, class_counts(t[cursor:a]))]
        block = t[a:b]
        class_ops = [np.flatnonzero((block & 0x30) == code) + a
                     for code in (0x30, 0x20, 0x10)]
        lengths = [len(x) for x in class_ops]
        if sieve["depth_at_cuts"][str(a)] != 0:
            rejected.append({"run": run, "start": a, "path": row["path"],
                             "reason": "entry inside condition scope"})
            offsets = [x + y for x, y in zip(offsets, lengths)]
            cursor = b
            continue
        candidates = (set(sieve["zero_at_cuts"][str(a)]) & scratch) - idle[run]
        touches = defaultdict(list)
        for group, names in enumerate((("qqq0", "qqq1", "qqq2"),
                                       ("qq0", "qq1"), ("q0",))):
            lo, hi = offsets[group], offsets[group] + lengths[group]
            for role, name in enumerate(names):
                vals = streams[name][lo:hi]
                for j in np.flatnonzero(np.isin(vals, list(candidates))):
                    op = int(class_ops[group][j])
                    touches[int(vals[j])].append((op, group, role))
        eligible = []
        for wire in candidates:
            events = touches.get(wire, [])
            if events and all(group == 1 and role == 0 and op in zero_cx
                              for op, group, role in events):
                eligible.append((len(events), wire, sorted(op for op, _, _ in events)))
        if eligible:
            _, wire, ops = min(eligible)
            admitted.append({"run": run, "start": a, "end": b,
                             "wire": wire, "deleted_cx": ops,
                             "other_idle": sorted(idle[run])})
        else:
            rejected.append({"run": run, "start": a, "path": row["path"],
                             "zero_at_start": len(candidates)})
        offsets = [x + y for x, y in zip(offsets, lengths)]
        cursor = b
    script = "".join(f"insert {r['start']} => R q{r['wire']}\n" for r in admitted)
    script += "".join(f"delete {op}\n" for r in admitted for op in r["deleted_cx"])
    report = {"source_sha256": sieve["source_sha256"],
              "peak_report": str(peak_path), "one_idle_runs": len(selected),
              "admitted": admitted, "rejected": rejected,
              "sieve_counts": sieve["counts"],
              "tier": "sound reset/last-write zero; only zero-control CX touches; edit unverified"}
    return script, report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("circuit", type=Path)
    ap.add_argument("peak_json", type=Path)
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    script, report = constructor(args.circuit, args.peak_json)
    args.script.write_text(script)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"source_sha256": report["source_sha256"],
                      "one_idle_runs": report["one_idle_runs"],
                      "admitted": len(report["admitted"]),
                      "removed_cx": sum(len(r["deleted_cx"]) for r in report["admitted"])}))


if __name__ == "__main__":
    main()
