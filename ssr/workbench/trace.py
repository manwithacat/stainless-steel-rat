"""Read-only, row-domain-aware state traces for local QHDL diagnosis.

Boundaries use operation indices: boundary ``p`` is immediately before op p,
after operations ``0..p-1``.  ``active_condition`` is retained as a compatibility
alias for the condition-stack mask; ``stack_active`` names it explicitly, and
``next_operation_active`` also includes the next op's own `if bN` predicate.
This is diagnostic evidence under the evaluator's fixed row/outcome model, not
a validity or score check.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


from ssr.qhdl import bitsim as B  # noqa: E402
from ssr.qhdl import kmb as K  # noqa: E402

MAX_POINTS = 16
MAX_WIRES = 16
MAX_BITS = 16
OUTCOMES = {"zero": "zero", "7": 7, "101": 101}


class TraceError(ValueError):
    """Malformed trace query, source, or unsupported local simulation."""


def _integer(value: Any, name: str) -> int:
    if type(value) is not int:
        raise TraceError(f"{name} must be an integer")
    return value


def _indices(value: Any, name: str, maximum: int) -> list[int]:
    if type(value) is not list or len(value) > maximum:
        raise TraceError(f"{name} must be a list of at most {maximum} integers")
    result = [_integer(item, f"{name} entry") for item in value]
    if len(set(result)) != len(result):
        raise TraceError(f"{name} entries must be distinct")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_bit(words: np.ndarray, row_index: int) -> int:
    return int((int(words[row_index // 64]) >> (row_index % 64)) & 1)


def _query_shape(query: Any) -> tuple[int, list[int], list[int], list[int], str, str]:
    if type(query) is not dict:
        raise TraceError("query must be an object")
    required = {"type", "x", "at", "wires", "level", "outcome"}
    allowed = required | {"bits"}
    if not required <= set(query) or not set(query) <= allowed:
        raise TraceError("trace query fields must be type, x, at, wires, level, outcome, and optional bits")
    if query["type"] != "trace":
        raise TraceError("query type must be 'trace'")
    x = _integer(query["x"], "x")
    at = _indices(query["at"], "at", MAX_POINTS)
    if not at:
        raise TraceError("at must contain at least one operation boundary")
    wires = _indices(query["wires"], "wires", MAX_WIRES)
    bits = _indices(query.get("bits", []), "bits", MAX_BITS)
    level = query["level"]
    if type(level) is not str or level not in ("sampled", "full"):
        raise TraceError("level must be 'sampled' or 'full'")
    outcome = query["outcome"]
    if type(outcome) is not str or outcome not in OUTCOMES:
        raise TraceError("outcome must be 'zero', '7', or '101'")
    return x, at, wires, bits, level, outcome


def investigate_trace(evaluator: Any, path: str | Path, query: dict[str, Any]) -> dict[str, Any]:
    """Trace one requested x while replaying the evaluator's complete row set.

    Seeded HMR outcomes are generated per packed row word.  Therefore the
    selected input is deliberately located in the full ``evaluator.rows``
    domain; running only that x would change both packed-word placement and
    the pseudo-random stream's correspondence to rows.
    """
    x, points, wires, bits, level, outcome_name = _query_shape(query)
    source = Path(path)
    if source.suffix != ".kmb" or not source.is_file():
        raise TraceError("path must name an existing .kmb candidate")
    try:
        k = K.read(str(source))
    except (OSError, K.KmbFormatError) as exc:
        raise TraceError(f"cannot read KMB candidate: {exc}") from exc
    nops = len(k.op_types)
    for boundary in points:
        if not 0 <= boundary <= nops:
            raise TraceError(f"operation boundary must be in 0..{nops}")
    for wire in wires:
        if not 0 <= wire < int(k.num_qubits):
            raise TraceError(f"wire index must be in 0..{int(k.num_qubits)-1}")
    for bit in bits:
        if not 0 <= bit < int(k.num_bits):
            raise TraceError(f"bit index must be in 0..{int(k.num_bits)-1}")

    try:
        rows = np.asarray(evaluator.rows(level), dtype=np.int64)
    except (ValueError, TypeError, AttributeError) as exc:
        raise TraceError(f"cannot obtain evaluator {level} row domain: {exc}") from exc
    if rows.ndim != 1 or not len(rows) or np.any(rows < 1) or len(np.unique(rows)) != len(rows):
        raise TraceError("evaluator returned an invalid row domain")
    selected = np.flatnonzero(rows == x)
    if not len(selected):
        raise TraceError(f"x={x} is not present in evaluator {level} rows; use level='full' if needed")
    row_index = int(selected[0])

    try:
        try:
            exported = evaluator.export(source)
        except ValueError as exc:
            # kickmix's text exporter requires the declared width to end at a
            # used wire.  Some valid KMB files declare spare wires, which the
            # trace contract must still expose.  Make an ephemeral header-only
            # compact copy for conversion; retain the original declared width
            # when allocating BitSim below and never rewrite the candidate.
            if "num_qubits from header wasn't one more than maximum used qubit id" not in str(exc):
                raise
            used = K.op_qubits(k)[1]
            highest = max((int(q) for q in used), default=-1)
            register_highest = max(
                (int(q) for _name, content in k.registers for is_q, q, _pos in content if is_q),
                default=-1,
            )
            highest = max(highest, register_highest)
            compact_width = highest + 1
            if compact_width >= int(k.num_qubits):
                raise exc
            with tempfile.TemporaryDirectory(prefix="qhdl-trace-") as td:
                compact = Path(td) / "trace.kmb"
                K.patch_qubits(k, str(compact), {}, {}, compact_width)
                exported = evaluator.export(compact)
        # `load()` infers width using max() over operation references and
        # raises on a valid zero-op source.  parse_kmx preserves the text
        # header/x-register map without making that unused-width inference.
        ops, _header, x_qubits = B.parse_kmx(exported)
    except (OSError, ValueError, AssertionError, IndexError, K.KmbFormatError) as exc:
        raise TraceError(f"cannot load local simulator operations: {exc}") from exc
    if any(q < 0 or q >= int(k.num_qubits) for q in x_qubits):
        raise TraceError("candidate input-register wire exceeds declared width")
    try:
        sim = B.BitSim(ops, rows=rows, num_qubits=int(k.num_qubits), x_qubits=x_qubits,
                       outcome=OUTCOMES[outcome_name])
        snapshots: dict[int, dict[str, Any]] = {}

        def capture(boundary: int, state: B.BitSim) -> None:
            phase = (int(state.rot[row_index]) + (_row_bit(state.sign, row_index) << 63)) & ((1 << 64) - 1)
            stack_active = True if state.act is None else bool(_row_bit(state.act, row_index))
            op = ops[boundary] if boundary < len(ops) else None
            next_active = stack_active
            # PUSH_CONDITION reads its bit to create the next stack frame;
            # it is itself unconditional. Other conditioned operations add
            # their local predicate to the enclosing stack mask.
            if op is not None and op.code != B.C_PUSH and op.cond >= 0:
                next_active = next_active and bool(_row_bit(state._bit(op.cond), row_index))
            snapshots[boundary] = {
                "boundary": boundary,
                "wires": {str(wire): _row_bit(state.q[wire], row_index) for wire in wires},
                "bits": {str(bit): _row_bit(state._bit(bit), row_index) for bit in bits},
                "phase_units_mod_2_64": phase,
                "active_condition": stack_active,
                "stack_active": stack_active,
                "next_operation_active": None if op is None else next_active,
                "condition_stack_depth": len(state.stack),
                "op_at_boundary": _op_record(ops, boundary),
            }

        ordered = sorted(set(points))
        sim.run(stop=max(ordered), snaps=ordered, on_snap=capture)
    except (ValueError, IndexError, KeyError, AssertionError, OverflowError) as exc:
        raise TraceError(f"local trace simulation failed: {type(exc).__name__}: {exc}") from exc

    return {
        "status": "diagnostic",
        "scope": "selected input state under the evaluator's fixed local row domain and measurement model; no full validation claim",
        "source_sha256": _sha256(source),
        "level": level,
        "row_count": len(rows),
        "outcome": outcome_name,
        "x": x,
        "row_index": row_index,
        "operation_count": nops,
        "checkpoints": [snapshots[point] for point in points],
    }


def _op_record(ops: list[B.Op], boundary: int) -> dict[str, Any] | None:
    if boundary == len(ops):
        return None
    op = ops[boundary]
    return {
        "index": boundary,
        "opcode": B.KINDS[op.code],
        "wires": list(op.q),
        "bit": None if op.bit < 0 else op.bit,
        "condition": None if op.cond < 0 else op.cond,
        "text": op.text,
    }
