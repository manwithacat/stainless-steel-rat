"""Static, bounded KMB structure inspection for mouse-workbench research.

This module reports source structure and allocator-model liveness only.  It does
not establish that an idle wire is zero, semantically redundant, or removable.
"""
from __future__ import annotations

import hashlib
import sys
from collections import Counter
from pathlib import Path
from typing import Any


import numpy as np
from ssr.qhdl import edit as EDIT
from ssr.qhdl import kmb as K
from ssr.qhdl import lifetime_allocator as A

MAX_WINDOW = 256
SUMMARY_LIMIT = 20
WIRE_LIMIT = 100


class StructureError(ValueError):
    """Invalid query or unreadable KMB source."""


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StructureError(f"{field} must be an integer")
    return value


def _source(path: str | Path) -> tuple[Path, K.Kmb]:
    p = Path(path)
    if p.suffix != ".kmb" or not p.is_file():
        raise StructureError("path must name an existing .kmb file")
    try:
        return p, K.read(str(p))
    except (OSError, K.KmbFormatError) as exc:
        raise StructureError(f"cannot read KMB: {exc}") from exc


def _base_name(code: int) -> str:
    if code == K.PUSH_CONDITION:
        return "PUSH_CONDITION"
    base = code & 0x7F if code & 0x80 else code
    return K.NAMES.get(base, f"0x{base:02x}") + ("_IF" if code & 0x80 else "")


def _records(k: K.Kmb, start: int, end: int) -> list[dict[str, Any]]:
    # Source.op is the canonical stream-index decoder, preserving angle bytes.
    src = EDIT.Source(k)
    depth = K.condition_depth(k.op_types)
    out = []
    for i in range(start, end):
        r = src.op(i)
        out.append({
            "op": i, "opcode": _base_name(r["code"]), "code": r["code"],
            "q": list(r["q"]), "b": r["b0"], "condition": r["bc"],
            "condition_depth": int(depth[i]),
            "angle128_le_hex": r["angle"].hex() if r["angle"] is not None else None,
            "tag": r["tag"].decode("utf-8", "replace") if r["tag"] is not None else None,
        })
    return out


def _layout(k: K.Kmb):
    is_reset, depth = A.reset_ops(k)
    ops, qs, order, _ = A.references(k)
    regs = A.register_qubits(k)
    iv = A.build_intervals(k, ops, qs, order, is_reset, depth, regs)
    profile = A.live_profile(iv, len(k.op_types), regs, register_gaps=False)
    return iv, profile, regs, ops, qs, is_reset, depth


def _interval_rows(iv, regs, num_ops):
    rows = []
    for j, (wire, s, e) in enumerate(zip(iv["logical"], iv["s"], iv["e"])):
        wire, s, e = int(wire), int(s), int(e)
        first, last = bool(iv["is_first"][j]), bool(iv["is_last"][j])
        if wire in regs and first:
            s = 0
        if wire in regs and last:
            e = max(0, num_ops - 1)
        rows.append({"wire": wire, "start": s, "end": e, "register": regs.get(wire),
                     "first_interval": first, "last_interval": last})
    return rows


def _runs(profile: np.ndarray, peak: int) -> list[dict[str, int]]:
    ids = np.flatnonzero(profile == peak)
    if not len(ids):
        return []
    runs = []
    start = prev = int(ids[0])
    for value in ids[1:]:
        value = int(value)
        if value != prev + 1:
            runs.append({"start": start, "end": prev})
            start = value
        prev = value
    runs.append({"start": start, "end": prev})
    return runs


def _tag_regions(k: K.Kmb) -> list[dict[str, Any]]:
    stack: list[tuple[str, int, bool]] = []
    regions = []
    indices = np.flatnonzero(k.op_types == K.INFO_TAG).tolist()
    tags = k.info_tags()
    for i, tag_bytes in zip(indices, tags):
        tag = tag_bytes
        if tag.startswith("@enter:"):
            name = tag[len("@enter:"):]
            top = not stack
            stack.append((name, i + 1, top))
        elif tag.startswith("@exit:"):
            name = tag[len("@exit:"):]
            # Match the nearest corresponding open marker. Malformed/unpaired
            # metadata is retained as no region rather than guessed.
            if stack and stack[-1][0] == name:
                opened, start, top = stack.pop()
                if top:
                    regions.append({"name": opened, "start": start, "end": i,
                                    "ops": max(0, i - start)})
    return regions


def _overview(k: K.Kmb, layout) -> dict[str, Any]:
    iv, profile, regs, *_ = layout
    n = len(k.op_types)
    counts = Counter(_base_name(int(t)) for t in k.op_types)
    runs = _runs(profile, int(profile.max()) if len(profile) else 0)
    regions = _tag_regions(k)
    return {
        "declared_qubits": int(k.num_qubits), "input_width": len(regs),
        "declared_scratch_width": max(0, int(k.num_qubits) - len(regs)), "input_registers": [
            {"name": name, "qubits": [int(q) for isq, q, _ in content if isq],
             "bits": [int(q) for isq, q, _ in content if not isq]}
            for name, content in k.registers],
        "register_qubit_count": len(regs),
        "scratch_width_at_livepeak": max(0, (int(profile.max()) if len(profile) else 0) - len(regs)),
        "livepeak": int(profile.max()) if len(profile) else 0,
        "peak_runs": runs[:SUMMARY_LIMIT], "peak_runs_total": len(runs),
        "peak_runs_truncated": len(runs) > SUMMARY_LIMIT,
        "top_level_regions": regions[:SUMMARY_LIMIT], "top_level_regions_total": len(regions),
        "top_level_regions_truncated": len(regions) > SUMMARY_LIMIT,
        "operation_counts": dict(sorted(counts.items())), "operation_count": n,
        "liveness_model": "qhdl_lifetime_allocator default: registers pinned for whole circuit; unconditional top-level R/HMR and final-touch intervals",
        "static_only": True,
    }


def _window(k: K.Kmb, query: dict[str, Any], layout) -> dict[str, Any]:
    n = len(k.op_types)
    start, end = _integer(query.get("start"), "start"), _integer(query.get("end"), "end")
    if not (0 <= start <= end <= n) or end - start > MAX_WINDOW:
        raise StructureError(f"window must satisfy 0 <= start <= end <= {n} and contain at most {MAX_WINDOW} ops")
    iv, profile, regs, ops, qs, *_ = layout
    rows = _records(k, start, end)
    selected = (ops >= start) & (ops < end)
    touched = sorted(set(int(x) for x in qs[selected]))
    bits = set()
    for field, mask in (("b", (k.op_types & 0x40) != 0), ("condition", (k.op_types & 0x80) != 0)):
        indices = np.flatnonzero(mask[start:end]) + start
        stream = k.stream("b0" if field == "b" else "bc")
        refs = np.flatnonzero(mask)
        lo, hi = np.searchsorted(refs, [start, end])
        bits.update(int(x) for x in stream[lo:hi])
    def boundary_wires(boundary):
        # A boundary is before op `boundary`; inclusive allocator intervals
        # are live at the adjacent op for 0 < boundary < n.
        at = min(max(boundary, 0), max(0, n - 1))
        return sorted({int(w) for w, s, e in zip(iv["logical"], iv["s"], iv["e"]) if int(s) <= at <= int(e)
                       and int(w) not in regs}) if n else []
    before = boundary_wires(start)
    after = boundary_wires(end)
    cross = sorted(set(before) & set(after))
    # Condition controls in force at both cuts, plus direct condition refs in window.
    depths = K.condition_depth(k.op_types)
    controls = sorted({int(x["condition"]) for x in rows if x["condition"] is not None})
    def active_conditions(boundary):
        stack = []
        decoder = K.Decoder(k)
        for op in range(boundary):
            code = int(k.op_types[op])
            if code == K.PUSH_CONDITION:
                stack.append(int(decoder.s["bc"][decoder.cc[op]]))
            elif code == K.POP_CONDITION and stack:
                stack.pop()
        return stack
    active_before, active_after = active_conditions(start), active_conditions(end)
    control_context = {"depth_before": int(depths[start]) if start < n else int(np.count_nonzero(k.op_types == K.PUSH_CONDITION) - np.count_nonzero(k.op_types == K.POP_CONDITION)),
                       "depth_after": int(depths[end]) if end < n else int(np.count_nonzero(k.op_types == K.PUSH_CONDITION) - np.count_nonzero(k.op_types == K.POP_CONDITION)),
                       "active_condition_bits_before": active_before,
                       "active_condition_bits_after": active_after,
                       "condition_bits_referenced_in_window": controls,
                       "caution": "condition bits and enclosing control context can affect behavior outside the displayed window"}
    return {"start": start, "end": end, "operations": rows, "operation_count": len(rows),
            "touched_wires": touched, "classical_bits_touched": sorted(bits),
            "boundary_cross_live_scratch": {"before": before, "after": after, "crossing": cross},
            "condition_context": control_context, "static_only": True}


def _wire(k: K.Kmb, query: dict[str, Any], layout) -> dict[str, Any]:
    wire = _integer(query.get("wire"), "wire")
    if wire < 0 or wire >= int(k.num_qubits):
        raise StructureError(f"wire must be in 0..{int(k.num_qubits)-1}")
    iv, _, regs, ops, qs, resets, depth = layout
    refs = np.flatnonzero(qs == wire)
    touches = sorted(set(int(x) for x in ops[refs]))
    events = []
    phase_codes = {0x10, 0x13, 0x20, 0x30, 0x90, 0x93, 0xA0, 0xB0}
    decoder = K.Decoder(k)
    for op in touches:
        code = int(k.op_types[op]); name = _base_name(code)
        qpos = decoder.qubits(op).index(wire)
        if code in (0x10, K.Z_POW, 0x20, 0x30, 0x90, 0x93, 0xA0, 0xB0): role = "phase"
        elif code in (K.SWAP, 0xB2): role = "read_write"
        elif name in ("CX", "CCX", "CX_IF", "CCX_IF") and qpos < len(decoder.qubits(op)) - 1: role = "read"
        else: role = "write"
        events.append({"op": op, "opcode": name, "role": role,
                       "phase": code in phase_codes,
                       "reset": bool(resets[op]), "condition_depth": int(depth[op])})
    intervals = [r for r in _interval_rows(iv, regs, len(k.op_types)) if r["wire"] == wire]
    gaps = [{"after_op": a, "before_op": b, "intervening_ops": max(0, b - a - 1)}
            for a, b in zip(touches, touches[1:])]
    phase = [e for e in events if e["phase"]]
    cap = WIRE_LIMIT
    return {"wire": wire, "register": regs.get(wire), "role": "register" if wire in regs else "scratch",
            "lifetime_intervals": intervals, "touch_count": len(touches),
            "max_gap_between_touches": max((g["intervening_ops"] for g in gaps), default=None),
            "touches": events[:cap], "touches_total": len(events), "touches_truncated": len(events) > cap,
            "phase_touches": phase[:cap], "phase_touches_total": len(phase), "phase_touches_truncated": len(phase) > cap,
            "gaps": gaps[:cap], "gaps_total": len(gaps), "gaps_truncated": len(gaps) > cap,
            "static_only": True, "idle_does_not_imply_zero": True}


def _peak(k: K.Kmb, query: dict[str, Any], layout) -> dict[str, Any]:
    iv, profile, regs, ops, qs, *_ = layout
    peak = int(profile.max()) if len(profile) else 0
    runs = _runs(profile, peak)
    if "index" in query:
        index = _integer(query["index"], "index")
        if not 0 <= index < len(profile):
            raise StructureError(f"index must be in 0..{len(profile)-1}")
        chosen = next((r for r in runs if r["start"] <= index <= r["end"]), None)
        if chosen is None:
            raise StructureError("index is not in a livepeak run")
    elif "start" in query:
        start = _integer(query["start"], "start")
        chosen = next((r for r in runs if r["start"] == start), None)
        if chosen is None:
            raise StructureError("start must identify a livepeak run")
    else:
        chosen = runs[0] if runs else None
    wires = []
    if chosen:
        at = chosen["start"]
        used_wires = set(int(w) for w in qs[(ops >= chosen["start"]) & (ops <= chosen["end"])])
        wires = []
        for row in _interval_rows(iv, regs, len(profile)):
            w, s, e = row["wire"], row["start"], row["end"]
            if s <= at <= e:
                wires.append({"wire": w, "register": row["register"], "idle_through_run": w not in used_wires})
    wire_total = len(wires)
    return {"livepeak": peak, "chosen_peak_run": chosen, "live_wires_at_run_start": wires[:WIRE_LIMIT],
            "live_wires_total": wire_total, "live_wires_truncated": wire_total > WIRE_LIMIT,
            "peak_runs": runs[:SUMMARY_LIMIT], "peak_runs_total": len(runs),
            "peak_runs_truncated": len(runs) > SUMMARY_LIMIT,
            "all_runs_metadata": {"covered": len(runs), "returned": min(len(runs), SUMMARY_LIMIT),
                                  "truncated": len(runs) > SUMMARY_LIMIT},
            "liveness_model": "qhdl_lifetime_allocator default with registers pinned throughout",
            "static_only": True, "idle_does_not_imply_zero": True}


def inspect(path: str | Path, query: dict) -> dict:
    """Inspect a KMB with one bounded query: overview, window, wire, or peak."""
    if not isinstance(query, dict):
        raise StructureError("query must be an object")
    kind = query.get("type", query.get("kind", query.get("query")))
    if kind not in {"overview", "window", "wire", "peak"}:
        raise StructureError("query kind must be overview, window, wire, or peak")
    allowed = {"overview": set(), "window": {"start", "end"}, "wire": {"wire"}, "peak": {"index", "start"}}[kind]
    if set(query) - allowed - {"type", "kind", "query"}:
        raise StructureError("unexpected structural query field")
    if sum(k in query for k in ("type", "kind", "query")) != 1:
        raise StructureError("provide exactly one query discriminator")
    if kind == "peak" and "index" in query and "start" in query:
        raise StructureError("peak selectors are mutually exclusive")
    p, k = _source(path)
    layout = _layout(k)
    if kind == "overview": result = _overview(k, layout)
    elif kind == "window": result = _window(k, query, layout)
    elif kind == "wire": result = _wire(k, query, layout)
    else: result = _peak(k, query, layout)
    result.update({"query": kind, "source": str(p), "source_sha256": _sha(p), "schema": "qhdl-mouse-structure/1"})
    return result
