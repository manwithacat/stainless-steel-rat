#!/usr/bin/env python3
"""Sound reset/last-write screen for zero-operand CX, CCX, CCZ and CSWAP.

Starts at the KMB's initialized state. A wire is marked zero only after an
unconditional reset, at circuit start if it is not an input register, or
through a value operation that preserves that fact. Every uncertain write
forgets the fact. This deliberately misses algebraic cancellations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from ssr.qhdl import kmb as K  # noqa: E402
from ssr.components.common import sha


def scan(path: Path, stop: int, focus: tuple[int, int], max_events: int,
         cuts=(), event_kinds=None):
    k = K.read(str(path))
    if not 0 <= focus[0] <= focus[1] <= stop <= len(k.op_types):
        raise ValueError("invalid stop/focus")
    input_wires = {qid for _, contents in k.registers
                   for is_qubit, qid, _ in contents if is_qubit}
    scratch = [q for q in range(k.num_qubits) if q not in input_wires]
    zero = [q not in input_wires for q in range(k.num_qubits)]
    origin = ["initial" if z else None for z in zero]
    t = k.op_types
    s = {name: k.stream(name) for name in ("qqq0", "qqq1", "qqq2", "qq0", "qq1", "q0")}
    n3 = n2 = n1 = 0
    depth = 0
    counts = Counter()
    focus_counts = Counter()
    events = []
    cut_set = set(cuts)
    zero_at_cuts = {}
    depth_at_cuts = {}
    for op in range(stop):
        if op in cut_set:
            zero_at_cuts[str(op)] = [q for q in scratch if zero[q]]
            depth_at_cuts[str(op)] = depth
        code = int(t[op])
        if code == K.PUSH_CONDITION:
            depth += 1
            continue
        if code == K.POP_CONDITION:
            depth -= 1
            if depth < 0:
                raise ValueError(f"negative condition depth at {op}")
            continue
        base = code & 0x7F
        guarded = bool(code & 0x80 or depth)
        qclass = code & 0x30
        if qclass == 0x30:
            a, b, c = (int(s[name][n3]) for name in ("qqq0", "qqq1", "qqq2"))
            n3 += 1
            if base == 0x30:  # CCZ, diagonal
                known = [wire for wire in (a, b, c) if zero[wire]]
                if known:
                    counts["CCZ"] += 1
                    if focus[0] <= op < focus[1]:
                        focus_counts["CCZ"] += 1
                        if len(events) < max_events and (event_kinds is None or "CCZ" in event_kinds):
                            events.append({"op": op, "kind": "CCZ", "qubits": [a, b, c],
                                           "zero_operand": known[0], "origin": origin[known[0]]})
                continue
            if base == 0x31:  # CCX
                control = a if zero[a] else b if zero[b] else None
                if control is not None:
                    counts["CCX"] += 1
                    if focus[0] <= op < focus[1]:
                        focus_counts["CCX"] += 1
                        if len(events) < max_events and (event_kinds is None or "CCX" in event_kinds):
                            events.append({"op": op, "kind": "CCX", "qubits": [a, b, c],
                                           "zero_control": control, "origin": origin[control]})
                else:
                    zero[c], origin[c] = False, None
            elif base == 0x32:  # CSWAP
                known = a if zero[a] else b if zero[b] and zero[c] else None
                if known is not None:
                    counts["CSWAP"] += 1
                    if focus[0] <= op < focus[1]:
                        focus_counts["CSWAP"] += 1
                        if len(events) < max_events and (event_kinds is None or "CSWAP" in event_kinds):
                            events.append({"op": op, "kind": "CSWAP", "qubits": [a, b, c],
                                           "zero_operand": known, "origin": origin[known]})
                else:
                    zero[b] = zero[c] = False
                    origin[b] = origin[c] = None
            else:
                for wire in (a, b, c):
                    zero[wire], origin[wire] = False, None
                    counts["unsupported_3q"] += 1
        elif qclass == 0x20:
            a, b = int(s["qq0"][n2]), int(s["qq1"][n2])
            n2 += 1
            if base == 0x20:  # CZ, diagonal
                continue
            if base == 0x21:  # CX
                if zero[a]:
                    counts["CX"] += 1
                    if focus[0] <= op < focus[1]:
                        focus_counts["CX"] += 1
                        if len(events) < max_events and (event_kinds is None or "CX" in event_kinds):
                            events.append({"op": op, "kind": "CX", "qubits": [a, b],
                                           "zero_control": a, "origin": origin[a]})
                else:
                    zero[b], origin[b] = False, None
            elif base == 0x22:  # SWAP
                if guarded:
                    if not (zero[a] and zero[b]):
                        zero[a] = zero[b] = False
                        origin[a] = origin[b] = None
                else:
                    zero[a], zero[b] = zero[b], zero[a]
                    origin[a], origin[b] = origin[b], origin[a]
            else:
                zero[a] = zero[b] = False
                origin[a] = origin[b] = None
                counts["unsupported_2q"] += 1
        elif qclass == 0x10:
            a = int(s["q0"][n1])
            n1 += 1
            if base in (0x10, 0x13):  # Z, Z_POW: diagonal
                continue
            if base == 0x11:  # X
                zero[a], origin[a] = False, None
            elif base in (0x12, 0x50):  # R, HMR
                if not guarded:
                    zero[a], origin[a] = True, f"{K.NAMES[base]}@{op}"
                elif zero[a]:
                    pass  # conditional reset preserves an already-proved zero
                else:
                    zero[a], origin[a] = False, None
            else:
                zero[a], origin[a] = False, None
                counts["unsupported_1q"] += 1
    if stop in cut_set:
        zero_at_cuts[str(stop)] = [q for q in scratch if zero[q]]
        depth_at_cuts[str(stop)] = depth
    return {"source_sha256": sha(path),
            "num_ops_scanned": stop, "focus": list(focus),
            "counts": dict(counts), "focus_counts": dict(focus_counts),
            "events": events, "events_truncated": sum(v for n,v in focus_counts.items() if event_kinds is None or n in event_kinds) > len(events),
            "zero_at_cuts": zero_at_cuts,
            "depth_at_cuts": depth_at_cuts,
            "zero_wires_at_stop": sum(zero), "condition_depth_at_stop": depth,
            "tier": "sound reset/last-write zero certificates; unsupported value ops forget zero"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("circuit", type=Path)
    ap.add_argument("--stop", type=int)
    ap.add_argument("--focus", nargs=2, type=int, metavar=("START", "END"))
    ap.add_argument("--max-events", type=int, default=100)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    k = K.read(str(args.circuit))
    stop = len(k.op_types) if args.stop is None else args.stop
    focus = (0, stop) if args.focus is None else tuple(args.focus)
    report = scan(args.circuit, stop, focus, args.max_events)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ("source_sha256", "num_ops_scanned", "focus_counts",
                       "counts", "events_truncated")}))


if __name__ == "__main__":
    main()
