"""Bounded static KMB gap census and guarded HMR affordances.

This module reads a supplied KMB only. It never edits or evaluates the circuit.
Gap cards describe open intervals between consecutive allocator-lifetime
touches; they are coverage candidates, not reconstruction or width claims.
"""
from __future__ import annotations

import hashlib
import json
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ssr.qhdl import kmb as K  # noqa: E402
from ssr.qhdl import lifetime_allocator as A  # noqa: E402

MAX_CARDS = 20
MAX_HMR_ACTIONS = 6


class CensusError(ValueError):
    """Bad source, stale SHA, or invalid census request."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_gap(source_sha: str, gap: dict[str, int]) -> str:
    payload = json.dumps(gap, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((source_sha + payload).encode("ascii")).hexdigest()


def _runs(values: set[int]) -> list[dict[str, int]]:
    if not values:
        return []
    ordered = sorted(values)
    out, start, prev = [], ordered[0], ordered[0]
    for x in ordered[1:]:
        if x != prev + 1:
            out.append({"start": start, "end": prev})
            start = x
        prev = x
    out.append({"start": start, "end": prev})
    return out


def _touches_by_lifetime(iv: dict[str, Any]) -> dict[int, list[int]]:
    touches: dict[int, set[int]] = defaultdict(set)
    for life, op in zip(iv["interval_id"], iv["so"]):
        touches[int(life)].add(int(op))
    return {life: sorted(ops) for life, ops in touches.items()}


def _last_touch(k: K.Kmb, wire: int, left: int,
                class_ops: dict[int, np.ndarray]) -> dict[str, Any]:
    """Return the last local operand and a conservative controlled-X role."""
    typ = int(k.op_types[left])
    code = typ & 0x7F
    cls = typ & 0x30
    if cls == 0x30:
        pos = int(np.searchsorted(class_ops[0x30], left, side="right")) - 1
        operands = [int(k.stream(name)[pos]) for name in ("qqq0", "qqq1", "qqq2")]
    elif cls == 0x20:
        pos = int(np.searchsorted(class_ops[0x20], left, side="right")) - 1
        operands = [int(k.stream(name)[pos]) for name in ("qq0", "qq1")]
    elif cls == 0x10:
        pos = int(np.searchsorted(class_ops[0x10], left, side="right")) - 1
        operands = [int(k.stream("q0")[pos])]
    else:
        return {"op": None, "role": "no_prior_touch"}
    # The final operand is a destination only for these common reversible
    # controlled-X forms. Other opcodes are deliberately called touches.
    role = "target" if code in (0x21, 0x31) and operands and operands[-1] == wire else "touch"
    return {"op": left, "role": role, "opcode": K.NAMES.get(code, f"0x{code:02x}")}


def _condition_depths(types: np.ndarray) -> np.ndarray:
    return K.condition_depth(types)


def _gap_candidates(k: K.Kmb, iv: dict[str, Any], registers: dict[int, Any],
                    peak_ops: set[int], peak_runs: list[dict[str, int]]) -> list[dict[str, Any]]:
    depths = _condition_depths(k.op_types)
    class_ops = {cls: np.flatnonzero((k.op_types & 0x30) == cls)
                 for cls in (0x10, 0x20, 0x30)}
    peak_sorted = np.asarray(sorted(peak_ops), dtype=np.int64)
    run_starts = [r["start"] for r in peak_runs]
    run_ends = [r["end"] for r in peak_runs]
    result: list[dict[str, Any]] = []
    for life, touches in _touches_by_lifetime(iv).items():
        wire = int(iv["logical"][life])
        if wire in registers:
            continue
        for left, right in zip(touches, touches[1:]):
            if right - left <= 1:
                continue
            # A cut is boundary left+1 (erase) and right (reconstruct).
            if int(depths[left + 1]) != 0 or int(depths[right]) != 0:
                continue
            p0 = int(np.searchsorted(peak_sorted, left, side="right"))
            p1 = int(np.searchsorted(peak_sorted, right, side="left"))
            covered_count = p1 - p0
            if not covered_count:
                continue
            first_run = bisect_right(run_ends, left)
            end_run = bisect_left(run_starts, right)
            run_ids = list(range(first_run, end_run))
            last_touch = _last_touch(k, wire, left, class_ops)
            producer = ({"op": last_touch["op"], "status": "controlled_x_target"}
                        if last_touch.get("role") == "target" else
                        {"op": None, "status": "unknown_from_static_touch"})
            row = {"target_wire": wire, "allocator_lifetime_id": life,
                   "after_op": left, "before_op": right,
                   "open_gap_ops": right - left - 1,
                   "peak_ops_covered": covered_count, "peak_run_ids": run_ids,
                   "peak_runs_covered": len(run_ids),
                   "last_touch": last_touch,
                   "actual_last_producer": producer,
                   "small_region_suggestion": {
                       "left_window": {"start": max(0, left - 4),
                                       "end": min(len(k.op_types), left + 5)},
                       "right_window": {"start": max(0, right - 4),
                                        "end": min(len(k.op_types), right + 5)}},
                   "suggestion_reason": "inspect local reversible dependencies around the two actual wire touches; no value or reconstruction inference"}
            canonical = {"target_wire": wire, "allocator_lifetime_id": life,
                         "after_op": left, "before_op": right}
            result.append({"handle": _canonical_gap("", canonical), **row,
                           "_canonical": canonical})
    result.sort(key=lambda r: (-r["peak_ops_covered"], r["open_gap_ops"],
                               r["target_wire"], r["after_op"], r["before_op"]))
    return result


def _hmr_affordances(k: K.Kmb, source_sha: str, limit: int = MAX_HMR_ACTIONS) -> list[dict[str, Any]]:
    """List only earlier moves accepted by CircuitMouse's disjoint-touch guard."""
    if type(limit) is not int or not 0 <= limit <= MAX_HMR_ACTIONS:
        raise CensusError(f"HMR action limit must be 0..{MAX_HMR_ACTIONS}")
    depths = _condition_depths(k.op_types)
    q3i = q2i = q1i = b0i = bci = 0
    lastq: dict[int, int] = {}
    lastb: dict[int, int] = {}
    candidates = []
    for i, typ in enumerate(k.op_types):
        code = int(typ)
        qclass = code & 0x30
        if qclass == 0x30:
            qrefs = [int(k.stream(name)[q3i]) for name in ("qqq0", "qqq1", "qqq2")]
            q3i += 1
        elif qclass == 0x20:
            qrefs = [int(k.stream(name)[q2i]) for name in ("qq0", "qq1")]
            q2i += 1
        elif qclass == 0x10:
            qrefs = [int(k.stream("q0")[q1i])]
            q1i += 1
        else:
            qrefs = []
        bit0 = int(k.stream("b0")[b0i]) if code & 0x40 else None
        if bit0 is not None:
            b0i += 1
        cond = int(k.stream("bc")[bci]) if code & 0x80 else None
        if cond is not None:
            bci += 1
        if code == K.HMR and int(depths[i]) == 0:
            bit = bit0
            if qrefs and bit is not None:
                after = max(lastq.get(qrefs[0], -1), lastb.get(bit, -1))
                if after >= 0 and after < i - 1 and int(depths[after + 1]) == 0:
                    # `after` is the latest touch of either dependency, so
                    # both intervals are empty by construction.
                    candidates.append((i - after, i, after, qrefs[0], bit))
        for q in qrefs:
            lastq[q] = i
        for b in (bit0, cond):
            if b is not None:
                lastb[b] = i
    candidates.sort(key=lambda row: (-row[0], row[1]))
    actions = []
    for distance, op, after, wire, bit in candidates[:limit]:
        identity = hashlib.sha256(f"{source_sha}:advance_hmr:{op}:{after}".encode()).hexdigest()
        actions.append({"candidate_id": identity,
                        "action": {"type": "advance_hmr", "op": op, "after": after},
                        "expected_source_sha256": source_sha,
                        "predicted_op_gap": {"before_move": distance,
                                             "open_interval": {"start": after + 1, "end": op - 1}},
                        "quantum_wire": wire, "measurement_bit": bit,
                        "guard_status": "static_guard_conforms",
                        "guard_checks": {"unconditional_hmr": True, "condition_depth_zero": True,
                                          "wire_disjoint": True, "measurement_bit_disjoint": True,
                                          "disjointness_basis": "latest prior wire/bit touch determines insertion boundary"},
                        "semantic_status": "local_disjoint_commutation_only; whole-circuit semantics not evaluated"})
    return actions


def census(source: str | Path, expected_sha256: str, *, limit: int = MAX_CARDS,
           hmr_limit: int = MAX_HMR_ACTIONS, offset: int = 0, stride: int = 1, full_artifact: str | Path | None = None) -> dict[str, Any]:
    """Return bounded cards for the exact expected source bytes."""
    path = Path(source)
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise CensusError("expected_sha256 is mandatory and must be a 64-character SHA-256")
    if type(limit) is not int or not 0 <= limit <= MAX_CARDS:
        raise CensusError(f"card limit must be 0..{MAX_CARDS}")
    if type(offset) is not int or offset < 0:
        raise CensusError("offset must be a nonnegative integer")
    if type(stride) is not int or not 1 <= stride <= 256:
        raise CensusError("stride must be an integer in 1..256")
    got = sha256(path)
    if got != expected_sha256.lower():
        raise CensusError(f"stale source SHA: expected {expected_sha256}, got {got}")
    try:
        k = K.read(str(path))
    except (OSError, K.KmbFormatError) as exc:
        raise CensusError(f"cannot read KMB: {exc}") from exc
    reset, depth = A.reset_ops(k)
    ops, qs, order, _ = A.references(k)
    registers = A.register_qubits(k)
    iv = A.build_intervals(k, ops, qs, order, reset, depth, registers)
    profile = A.live_profile(iv, len(k.op_types), registers, register_gaps=False)
    peak = int(profile.max()) if len(profile) else 0
    peak_ops = set(map(int, np.flatnonzero(profile == peak)))
    peak_runs = _runs(peak_ops)
    all_gaps = _gap_candidates(k, iv, registers, peak_ops, peak_runs)
    cards = []
    ranks = list(range(offset, len(all_gaps), stride))[:limit]
    for rank in ranks:
        row = all_gaps[rank]
        clean = dict(row)
        clean["rank"] = rank + 1
        canonical = clean.pop("_canonical")
        clean["handle"] = _canonical_gap(got, canonical)
        clean["candidate_identity"] = canonical
        clean["predicted_op_gap"] = {"after_op": row["after_op"], "before_op": row["before_op"],
                                     "open_operation_count": row["open_gap_ops"]}
        clean["guard_status"] = "allocator_touch_and_unconditional_cut_guards_pass"
        clean["semantic_status"] = "static_liveness_candidate_only; no reconstruction or width claim"
        cards.append(clean)
    output: dict[str, Any] = {
        "schema": "qhdl_ssr_loop_census_v2", "source_sha256": got,
        "source_path": str(path), "read_only_static": True,
        "operation_count": len(k.op_types), "declared_qubits": int(k.num_qubits),
        "allocator_live_peak": peak, "peak_operation_count": len(peak_ops),
        "peak_runs": peak_runs, "peak_run_count": len(peak_runs),
        "candidate_total": len(all_gaps), "returned_cards": len(cards),
        "offset": offset, "stride": stride,
        "next_offset": (ranks[-1] + stride if ranks and ranks[-1] + stride < len(all_gaps) else None),
        "omitted_candidates": len(all_gaps) - len(cards), "cards": cards,
        "hmr_actions": _hmr_affordances(k, got, hmr_limit),
        "ranking": "number of actual peak operation indices covered descending; then shorter open gap; then wire and endpoints",
        "claim_boundary": "candidate census only; does not evaluate, edit, infer values, or claim reconstruction/width reduction",
    }
    if full_artifact is not None:
        artifact = Path(full_artifact)
        if artifact.exists():
            raise CensusError(f"refusing to overwrite full artifact: {artifact}")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        full_rows = []
        for row in all_gaps:
            clean = dict(row)
            canonical = clean.pop("_canonical")
            clean["handle"] = _canonical_gap(got, canonical)
            full_rows.append(clean)
        artifact.write_text(json.dumps({"source_sha256": got, "cards": full_rows}, separators=(",", ":")) + "\n")
        output["full_artifact"] = str(artifact)
    return output


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("--expected-sha256", required=True)
    p.add_argument("--limit", type=int, default=MAX_CARDS)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    result = census(args.source, args.expected_sha256, limit=args.limit, offset=args.offset, stride=args.stride)
    rendered = json.dumps(result, separators=(",", ":"))
    if args.out:
        if args.out.exists():
            p.error(f"refusing to overwrite output: {args.out}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
