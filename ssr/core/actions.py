"""Guarded, bounded KMB actions for the circuit-mouse research strand.

These actions build candidates; they do not certify whole-circuit behavior.
Each action records the static preconditions it checked and a deliberately
limited proof scope.  The competition verifier remains the acceptance gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


from ..qhdl import edit as EDIT
from ..qhdl import kmb as KMB
from ..qhdl import lifetime_allocator as ALLOC
from ..qhdl import park_rewrite as PARK


class ActionError(ValueError):
    """An action is malformed or one of its stated preconditions failed."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionError(f"{field} must be an integer")
    return value


def _read_source(source: Path) -> KMB.Kmb:
    source = Path(source)
    if source.suffix != ".kmb" or not source.is_file():
        raise ActionError("source must be an existing .kmb file")
    try:
        return KMB.read(str(source))
    except (OSError, KMB.KmbFormatError) as exc:
        raise ActionError(f"source is not a readable KMB: {exc}") from exc


def _depth_at(k: KMB.Kmb, boundary: int) -> int:
    """Condition depth immediately before op `boundary` (or at circuit end)."""
    n = len(k.op_types)
    if not 0 <= boundary <= n:
        raise ActionError(f"boundary {boundary} is outside 0..{n}")
    if boundary == n:
        if n == 0:
            return 0
        delta = (k.op_types == KMB.PUSH_CONDITION).astype("int64")
        delta -= (k.op_types == KMB.POP_CONDITION).astype("int64")
        return int(delta.sum())
    return int(KMB.condition_depth(k.op_types)[boundary])


def _wire_touches(k: KMB.Kmb, wire: int, start: int, end: int) -> list[int]:
    ops, qs, _ = KMB.op_qubits(k)
    selected = (qs == wire) & (ops >= start) & (ops < end)
    return sorted(set(int(i) for i in ops[selected]))


def _bit_touches(k: KMB.Kmb, bit: int, start: int, end: int) -> list[dict[str, int]]:
    t = k.op_types
    import numpy as np

    indices = np.arange(start, end, dtype=np.int64)
    if not len(indices):
        return []
    found: list[dict[str, int]] = []
    b0_refs = np.flatnonzero((t & 0x40) != 0)
    b0_ids = k.stream("b0")
    lo, hi = np.searchsorted(b0_refs, [start, end])
    found.extend({"op": int(i), "role": "bit_operand"} for i in b0_refs[lo:hi][b0_ids[lo:hi] == bit])
    bc_refs = np.flatnonzero((t & 0x80) != 0)
    bc_ids = k.stream("bc")
    lo, hi = np.searchsorted(bc_refs, [start, end])
    found.extend({"op": int(i), "role": "condition"} for i in bc_refs[lo:hi][bc_ids[lo:hi] == bit])
    return sorted(found, key=lambda item: (item["op"], item["role"]))


def _edit(k: KMB.Kmb, source: Path, outdir: Path, script: str) -> tuple[Path, dict[str, Any]]:
    candidate = outdir / "candidate.kmb"
    try:
        result = EDIT.edit_file(source, script, candidate)
    except (EDIT.EditError, OSError, ValueError) as exc:
        raise ActionError(f"qhdl_edit refused the action: {exc}") from exc
    # Read back the artifact through the independent KMB parser.
    KMB.read(str(candidate))
    return candidate, result


def _result(
    action_name: str,
    source: Path,
    candidate: Path,
    preconditions: dict[str, Any],
    proofscope: dict[str, Any],
    edit_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "action": action_name,
        "source": str(source),
        "source_sha256": _sha256(source),
        "candidate": str(candidate),
        "candidate_path": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "precondition_evidence": preconditions,
        "proofscope": proofscope,
    }
    if edit_result is not None:
        record["edit"] = edit_result
    (candidate.parent / "action.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _recolour(source: Path, k: KMB.Kmb, outdir: Path) -> dict[str, Any]:
    is_reset, depth = ALLOC.reset_ops(k)
    ops, qs, order, _ = ALLOC.references(k)
    regs = ALLOC.register_qubits(k)
    intervals = ALLOC.build_intervals(k, ops, qs, order, is_reset, depth, regs)
    # Default allocator mode keeps declared register wires pinned throughout.
    colours = ALLOC.colour(intervals, len(k.op_types), regs, register_gaps=False)
    streams, recoloured = ALLOC.recolour(k, ops, qs, order, intervals, colours)
    candidate = outdir / "candidate.kmb"
    used_max = int(recoloured.max()) + 1 if len(recoloured) else 0
    register_max = max(regs, default=-1) + 1
    new_qubits = max(used_max, register_max)
    KMB.patch_qubits(k, str(candidate), streams, {q: q for q in regs}, new_qubits)
    check = ALLOC.check_equivalence(str(source), str(candidate))
    angle_preserved = _angles(k) == _angles(KMB.read(str(candidate)))
    if not angle_preserved:
        raise ActionError("lifetime allocator unexpectedly changed the exact angle stream")
    report = outdir / "allocator.json"
    profile = ALLOC.live_profile(intervals, len(k.op_types), regs, register_gaps=False)
    allocator_report = {
        "mode": "pinned-registers-default",
        "num_qubits_in": int(k.num_qubits),
        "num_qubits_out": int(KMB.read(str(candidate)).num_qubits),
        "lower_bound": int(profile.max()) if len(profile) else 0,
        "check_equivalence": check,
        "angles_byte_identical": angle_preserved,
    }
    report.write_text(json.dumps(allocator_report, indent=2) + "\n", encoding="utf-8")
    return _result(
        "recolour",
        source,
        candidate,
        {"pinned_registers": True, "allocator_check": check, "angles_byte_identical": angle_preserved},
        {
            "semantic_equivalence": "structural_lifetime_renaming_checked",
            "independent_check": "qhdl_lifetime_allocator.check_equivalence",
            "scope": "wire renaming and register preservation only; no task score or verifier claim",
        },
        {"allocator_report": str(report), **allocator_report},
    )


def _angles(k: KMB.Kmb) -> bytes:
    off, n, _ = k.offsets["angles"]
    return bytes(k.raw[off : off + 16 * n])


def _reserve_qubits(source: Path, k: KMB.Kmb, outdir: Path, action: dict[str, Any]) -> dict[str, Any]:
    """Expose clean scratch capacity without changing any operation bytes."""
    cap = _as_int(action.get("num_qubits"), "num_qubits")
    old = int(k.num_qubits)
    if not old < cap <= old + 16:
        raise ActionError("reserve_qubits requires an increase of 1..16 qubits")
    candidate = outdir / "candidate.kmb"
    KMB.patch_qubits(k, str(candidate), {}, {}, cap)
    out_k = KMB.read(str(candidate))
    if len(out_k.op_types) != len(k.op_types) or not (out_k.op_types == k.op_types).all():
        raise ActionError("reserve_qubits unexpectedly changed operations")
    if bytes(out_k.raw[24:]) != bytes(k.raw[24:]):
        raise ActionError("reserve_qubits changed bytes beyond the declared-width header")
    return _result(
        "reserve_qubits", source, candidate,
        {"num_qubits_in": old, "num_qubits_out": cap, "added_clean_qubits": cap - old,
         "operation_stream_byte_identical": True, "angles_byte_identical": True},
        {"semantic_equivalence": "header_only_width_increase",
         "scope": "original operation and register bytes unchanged; native/full verifier and score still required"},
    )


def _advance_hmr(source: Path, k: KMB.Kmb, outdir: Path, action: dict[str, Any]) -> dict[str, Any]:
    op = _as_int(action.get("op"), "op")
    after = _as_int(action.get("after"), "after")
    n = len(k.op_types)
    if not (0 <= op < n and 0 <= after < op - 1):
        raise ActionError("advance_hmr requires 0 <= after < op-1 < number of ops")
    if int(k.op_types[op]) != KMB.HMR:
        raise ActionError(f"op {op} is not an unconditional HMR")
    q_index = int(((k.op_types[:op] & 0x30) == 0x10).sum())
    move_wire = int(k.stream("q0")[q_index])
    bit_index = int((k.op_types[:op] & 0x40 != 0).sum())
    measure_bit = int(k.stream("b0")[bit_index])
    insertion = after + 1
    depths = KMB.condition_depth(k.op_types)
    if int(depths[op]) != 0 or _depth_at(k, insertion) != 0:
        raise ActionError("HMR site and insertion boundary must both have condition depth zero")
    wire_conflicts = _wire_touches(k, move_wire, insertion, op)
    bit_conflicts = _bit_touches(k, measure_bit, insertion, op)
    if wire_conflicts:
        raise ActionError(f"HMR wire q{move_wire} is touched between insertion and source: {wire_conflicts[:8]}")
    if bit_conflicts:
        raise ActionError(f"measurement bit b{measure_bit} is read or written before its original HMR: {bit_conflicts[:8]}")
    script = f"delete {op}\ninsert {insertion} => @{op}\n"
    candidate, edit_result = _edit(k, source, outdir, script)
    out_k = KMB.read(str(candidate))
    angles_preserved = _angles(k) == _angles(out_k)
    if not angles_preserved:
        raise ActionError("qhdl_edit changed an unrelated exact 128-bit angle")
    evidence = {
        "op": op,
        "after": after,
        "insertion_boundary": insertion,
        "moved_op": "unconditional HMR",
        "wire": move_wire,
        "measurement_bit": measure_bit,
        "wire_touches_in_open_interval": wire_conflicts,
        "measurement_bit_touches_in_open_interval": bit_conflicts,
        "depth_at_original_site": int(depths[op]),
        "depth_at_insertion_boundary": _depth_at(k, insertion),
        "angles_byte_identical": angles_preserved,
    }
    return _result(
        "advance_hmr", source, candidate, evidence,
        {
            "semantic_equivalence": "disjoint_interference_certificate",
            "certificate": "unconditional HMR moved across ops with no touched quantum wire or measurement-bit read/write",
            "scope": "local commutation only; no whole-circuit simulation or official verifier run",
        },
        edit_result,
    )


_TERM_RE = re.compile(r"q(\d+)$")


def _normalize_terms(value: Any) -> list[list[str]]:
    if not isinstance(value, list) or len(value) > 16:
        raise ActionError("terms must be a list containing at most 16 monomials")
    normalized: list[list[str]] = []
    for i, term in enumerate(value):
        if isinstance(term, str):
            if term == "1":
                factors = ["1"]
            elif "*" in term:
                factors = term.split("*")
            else:
                factors = [term]
        elif isinstance(term, (list, tuple)):
            factors = list(term)
        else:
            raise ActionError(f"terms[{i}] must be a string or a list of wire names")
        if factors == ["1"]:
            normalized.append(["1"])
            continue
        if not 1 <= len(factors) <= 2:
            raise ActionError(f"terms[{i}] must have degree one or two, or be the constant '1'")
        if any(not isinstance(factor, str) or not _TERM_RE.fullmatch(factor) for factor in factors):
            raise ActionError(f"terms[{i}] factors must be qN names")
        if len(set(factors)) != len(factors):
            raise ActionError(f"terms[{i}] repeats a variable")
        normalized.append(factors)
    return normalized


def _park_recompute(source: Path, k: KMB.Kmb, outdir: Path, action: dict[str, Any]) -> dict[str, Any]:
    wire = _as_int(action.get("wire"), "wire")
    after = _as_int(action.get("after"), "after")
    before = _as_int(action.get("before"), "before")
    n = len(k.op_types)
    if not 0 <= wire < int(k.num_qubits):
        raise ActionError(f"wire q{wire} is outside 0..{k.num_qubits - 1}")
    if not 0 <= after < before <= n:
        raise ActionError("park_recompute requires 0 <= after < before <= number of ops")
    terms = _normalize_terms(action.get("terms"))
    vars_used = {factor for term in terms for factor in term if factor != "1"}
    for name in vars_used:
        var = int(name[1:])
        if var >= int(k.num_qubits):
            raise ActionError(f"term variable {name} is outside the source qubit range")
        if var == wire:
            raise ActionError("recompute terms may not depend on the parked target wire")
    insertion = after + 1
    if _depth_at(k, insertion) != 0 or _depth_at(k, before) != 0:
        raise ActionError("park and recompute boundaries must both have condition depth zero")
    conflicts = _wire_touches(k, wire, insertion, before)
    if conflicts:
        raise ActionError(f"parked wire q{wire} is touched inside the open park window: {conflicts[:8]}")
    existing_bits = []
    if k.counts["b"]:
        existing_bits.extend(int(x) for x in k.stream("b0"))
    if k.counts["c"]:
        existing_bits.extend(int(x) for x in k.stream("bc"))
    fresh_bit = max(int(k.num_bits), max(existing_bits, default=-1) + 1)
    recompute_ops, quadratic_products = PARK.emit_recompute(wire, terms)
    park_line = f"insert {insertion} => HMR q{wire} b{fresh_bit}"
    recompute_line = f"insert {before} => " + "; ".join(recompute_ops + [f"Z q{wire} if b{fresh_bit}"])
    candidate, edit_result = _edit(k, source, outdir, park_line + "\n" + recompute_line + "\n")
    evidence = {
        "wire": wire,
        "after": after,
        "before": before,
        "park_boundary": insertion,
        "recompute_boundary": before,
        "target_touches_in_open_window": conflicts,
        "depth_at_park_boundary": _depth_at(k, insertion),
        "depth_at_recompute_boundary": _depth_at(k, before),
        "fresh_measurement_bit": fresh_bit,
        "terms": terms,
        "quadratic_products_emitted": int(quadratic_products),
        "inserted_ops": len(recompute_ops) + 2,
    }
    return _result(
        "park_recompute", source, candidate, evidence,
        {
            "semantic_equivalence": "not_established",
            "required_followup": "evaluate the supplied polynomial against the original wire value on the declared input domain",
            "scope": "guarded HMR and Dickson-form recomputation construction only; no expression correctness claim",
        },
        edit_result,
    )


def _park_factored(source: Path, k: KMB.Kmb, outdir: Path, action: dict[str, Any]) -> dict[str, Any]:
    """Park an idle wire and reconstruct an XOR of affine products at the next cut.

    Both one- and two-scratch modes verify syntax, cut and scratch-lifetime
    guards. The action does not
    infer or certify the supplied cross-cut value relation.
    """
    expected = action.get("expected_source_sha256")
    if expected != _sha256(source):
        raise ActionError("park_factored source SHA mismatch")
    wire = _as_int(action.get("wire"), "wire")
    after = _as_int(action.get("after"), "after")
    before = _as_int(action.get("before"), "before")
    n = len(k.op_types)
    if not 0 <= wire < int(k.num_qubits):
        raise ActionError("park_factored target outside source qubits")
    if not 0 <= after < before <= n:
        raise ActionError("park_factored requires 0 <= after < before <= number of ops")
    if _depth_at(k, after + 1) != 0 or _depth_at(k, before) != 0:
        raise ActionError("park_factored boundaries must have condition depth zero")
    conflicts = _wire_touches(k, wire, after + 1, before)
    if conflicts:
        raise ActionError(f"park_factored target touched in gap: {conflicts[:8]}")
    single_scratch = action.get("type") == "park_one_scratch"
    scratch = action.get("scratch")
    required_scratch = 1 if single_scratch else 2
    if not isinstance(scratch, list) or len(scratch) != required_scratch or any(type(v) is not int for v in scratch):
        raise ActionError(f"scratch must be {required_scratch} wire IDs")
    if len(set(scratch + [wire])) != required_scratch + 1 or any(not 0 <= v < int(k.num_qubits) for v in scratch):
        raise ActionError("scratch wires must be distinct existing non-target qubits")

    # The allocator's interval model supplies a conservative clean-at-cut
    # guard; operation insertion restores both scratch wires before the
    # original op stream resumes.
    is_reset, depth = ALLOC.reset_ops(k)
    refs, qs, order, _ = ALLOC.references(k)
    regs = ALLOC.register_qubits(k)
    iv = ALLOC.build_intervals(k, refs, qs, order, is_reset, depth, regs)
    live_intervals = (iv["s"] <= before) & (iv["e"] >= before)
    live_wires = set(map(int, iv["sq"][live_intervals[iv["interval_id"]]])) | set(regs)
    if any(v in live_wires for v in scratch):
        raise ActionError("scratch wire is live at reconstruction cut")

    def form(value, name):
        if not isinstance(value, list) or not 1 <= len(value) <= 64 or any(type(v) is not int for v in value):
            raise ActionError(f"{name} must be a nonempty list of up to 64 wire IDs")
        if len(set(value)) != len(value) or any(not 0 <= v < int(k.num_qubits) for v in value):
            raise ActionError(f"{name} contains a repeated or out-of-range wire")
        if set(value) & set(scratch + [wire]):
            raise ActionError(f"{name} uses target or scratch")
        return value

    products = action.get("products")
    if not isinstance(products, list) or len(products) > 8:
        raise ActionError("products must contain at most eight factor pairs")
    normalized = []
    for i, pair in enumerate(products):
        if not isinstance(pair, dict) or set(pair) != {"left", "right"}:
            raise ActionError(f"products[{i}] must have left and right lists")
        left, right = (form(pair["left"], f"products[{i}].left"),
                       form(pair["right"], f"products[{i}].right"))
        if single_scratch and len(left) != 1:
            raise ActionError("park_one_scratch left factor must be one physical wire")
        normalized.append((left, right))
    affine = action.get("affine", [])
    if affine:
        affine = form(affine, "affine")
    elif affine != []:
        raise ActionError("affine must be a wire-ID list")
    constant = action.get("constant", False)
    if type(constant) is not bool:
        raise ActionError("constant must be Boolean")
    existing_bits = []
    if k.counts["b"]:
        existing_bits.extend(int(x) for x in k.stream("b0"))
    if k.counts["c"]:
        existing_bits.extend(int(x) for x in k.stream("bc"))
    fresh_bit = max(int(k.num_bits), max(existing_bits, default=-1) + 1)
    op_text = [f"X q{wire}"] if constant else []
    op_text += [f"CX q{v} q{wire}" for v in affine]
    for left, right in normalized:
        if single_scratch:
            prep = [f"CX q{v} q{scratch[0]}" for v in right]
            op_text += prep + [f"CCX q{left[0]} q{scratch[0]} q{wire}"] + list(reversed(prep))
        else:
            lprep = [f"CX q{v} q{scratch[0]}" for v in left]
            rprep = [f"CX q{v} q{scratch[1]}" for v in right]
            op_text += lprep + rprep + [f"CCX q{scratch[0]} q{scratch[1]} q{wire}"]
            op_text += list(reversed(rprep)) + list(reversed(lprep))
    op_text.append(f"Z q{wire} if b{fresh_bit}")
    script = f"insert {after + 1} => HMR q{wire} b{fresh_bit}\n"
    script += f"insert {before} => " + "; ".join(op_text) + "\n"
    candidate, edit_result = _edit(k, source, outdir, script)
    return _result(
        "park_one_scratch" if single_scratch else "park_factored", source, candidate,
        {"target": wire, "after": after, "before": before, "scratch": scratch,
         "scratch_dead_at_cut": True, "target_touches_in_gap": [],
         "fresh_measurement_bit": fresh_bit, "products": len(normalized),
         "inserted_ops": len(op_text) + 1, "angles_byte_identical": _angles(k) == _angles(KMB.read(str(candidate)))},
        {"semantic_equivalence": "cross_cut_relation_unproved_by_action",
         "required_followup": "source-bound all-input value relation, all-outcome HMR phase identity, native and official verifier",
         "scope": "guarded factored quadratic construction; no task score claim"},
        edit_result,
    )


def _replace_window(source: Path, k: KMB.Kmb, outdir: Path, action: dict[str, Any]) -> dict[str, Any]:
    start = _as_int(action.get("start"), "start")
    end = _as_int(action.get("end"), "end")
    ops = action.get("ops")
    n = len(k.op_types)
    if not 0 <= start <= end <= n:
        raise ActionError("replace_window requires 0 <= start <= end <= number of ops")
    if end - start > 256:
        raise ActionError("replace_window source span exceeds 256 ops")
    if not isinstance(ops, list) or not all(isinstance(op, str) for op in ops):
        raise ActionError("replace_window ops must be a list of operation strings")
    if len(ops) > 256:
        raise ActionError("replace_window inserted op count exceeds 256")
    if _depth_at(k, start) != 0 or _depth_at(k, end) != 0:
        raise ActionError("replace_window source boundaries must both have condition depth zero")
    parsed: list[dict[str, Any]] = []
    for i, op_text in enumerate(ops):
        try:
            record = EDIT.parse_op(op_text)
        except EDIT.EditError as exc:
            raise ActionError(f"ops[{i}] is not accepted by qhdl_edit.parse_op: {exc}") from exc
        code = int(record.get("code", 0))
        if code in (KMB.PUSH_CONDITION, KMB.POP_CONDITION, KMB.INFO_TAG):
            raise ActionError("replace_window cannot insert PUSH_CONDITION, POP_CONDITION, or INFO_TAG")
        if "copy" in record:
            copied = _op_record(k, int(record["copy"]))
            if copied["code"] in (KMB.PUSH_CONDITION, KMB.POP_CONDITION, KMB.INFO_TAG):
                raise ActionError("replace_window cannot copy condition-stack or INFO_TAG operations")
            parsed.append(copied)
        else:
            parsed.append(record)
    # Replacements may use existing wires and bits only. Registers are KMB
    # metadata and are never edited by qhdl_edit.
    for i, record in enumerate(parsed):
        for q in record.get("q", ()):
            if int(q) >= int(k.num_qubits):
                raise ActionError(f"ops[{i}] refers to q{q}, beyond the source qubit cap")
        for key in ("b0", "bc"):
            bit = record.get(key)
            if bit is not None and int(bit) >= int(k.num_bits):
                raise ActionError(f"ops[{i}] refers to b{bit}, beyond the source classical-bit range")
    # qhdl_edit owns serialization and copies untouched 128-bit angles byte for byte.
    body = "; ".join(ops)
    script = f"replace {start}:{end} => {body}\n" if ops else f"delete {start}:{end}\n"
    candidate, edit_result = _edit(k, source, outdir, script)
    out_k = KMB.read(str(candidate))
    return _result(
        "replace_window",
        source,
        candidate,
        {
            "start": start,
            "end": end,
            "span": end - start,
            "inserted_ops": len(ops),
            "depth_at_start": _depth_at(k, start),
            "depth_at_end": _depth_at(k, end),
            "inserted_control_flow_or_tags": False,
            "register_metadata_edited": False,
            "num_qubits_preserved": int(out_k.num_qubits) == int(k.num_qubits),
        },
        {
            "semantic_equivalence": "not_established",
            "required_followup": "independent semantic comparison and applicable task verifier",
            "scope": "bounded syntactic splice using qhdl_edit operation parsing; no semantic or task-validity claim",
        },
        edit_result,
    )


def _op_record(k: KMB.Kmb, op: int) -> dict[str, Any]:
    if not 0 <= op < len(k.op_types):
        raise ActionError(f"copied op @{op} is outside the source circuit")
    from ..qhdl import edit as edit_module

    return edit_module.Source(k).op(op)


def apply_action(source: Path, action: dict[str, Any], outdir: Path) -> dict[str, Any]:
    """Apply one guarded circuit-mouse action to a KMB source.

    `outdir` is deliberately exclusive: it must not already exist. On
    success, a candidate KMB and an `action.json` provenance record are written.
    Failed guards can leave this new empty directory as a visible attempt record.
    """
    source, outdir = Path(source), Path(outdir)
    if outdir.exists():
        raise ActionError(f"outdir already exists; choose a fresh path: {outdir}")
    if not isinstance(action, dict):
        raise ActionError("action must be a dictionary")
    k = _read_source(source)
    outdir.mkdir(parents=True, exist_ok=False)
    kind = action.get("type", action.get("action"))
    if kind == "recolour":
        return _recolour(source, k, outdir)
    if kind == "reserve_qubits":
        return _reserve_qubits(source, k, outdir, action)
    if kind == "advance_hmr":
        return _advance_hmr(source, k, outdir, action)
    if kind == "park_recompute":
        return _park_recompute(source, k, outdir, action)
    if kind == "park_factored":
        return _park_factored(source, k, outdir, action)
    if kind == "park_one_scratch":
        return _park_factored(source, k, outdir, action)
    if kind == "replace_window":
        return _replace_window(source, k, outdir, action)
    raise ActionError(f"unsupported action type: {kind!r}")

