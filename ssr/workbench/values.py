"""Read-only, bounded semantic queries for the circuit mouse workbench.

Snapshots are at operation boundaries: boundary ``p`` is immediately before op
``p`` (and therefore after ops ``0..p-1``).  Results describe only the selected
wires and local measurement models; they do not certify whole-circuit validity.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from ssr.qhdl import bitsim as B  # noqa: E402
from ssr.qhdl import cheap_function as CF  # noqa: E402
from ssr.qhdl import kmb as K  # noqa: E402


MODELS = ("zero", 7, 101)
MAX_VALUE_WIRES = 16
MAX_BASIS = 12
MAX_TERMS = 16
MAX_EXAMPLES = 8


def _integer(value, name, minimum=None, maximum=None):
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _selected_snapshots(ops, xq, nq, rows, boundaries, selected, outcome):
    """Run once through requested boundaries, copying selected wires only."""
    saved = {}

    def take(boundary, sim):
        saved[boundary] = {wire: sim.q[wire].copy() for wire in selected}

    sim = B.BitSim(ops, rows=rows, num_qubits=nq, x_qubits=xq, outcome=outcome)
    stop = max(boundaries)
    sim.run(stop=stop, snaps=sorted(set(boundaries)), on_snap=take)
    valid = sim.valid.copy()
    del sim
    return saved, valid


def _load(evaluator, path):
    exported = evaluator.export(path)
    ops, _header, xq = B.parse_kmx(exported)
    declared = int(K.read(path).num_qubits)
    referenced = max((max(op.q) + 1 for op in ops if op.q), default=0)
    nq = max(declared, referenced)
    return ops, xq, nq


def _rows(evaluator, level):
    if level not in ("sampled", "full"):
        raise ValueError("level/validation must be 'sampled' or 'full'")
    rows = np.asarray(evaluator.rows(level), dtype=np.int64)
    if rows.ndim != 1 or not len(rows) or np.any(rows < 1) or len(np.unique(rows)) != len(rows):
        raise ValueError("evaluator returned invalid input rows")
    return rows


def _array_hash(arr, rows):
    return _digest_bytes(np.asarray(rows, dtype="<i8").tobytes() + np.asarray(arr, dtype="<u8").tobytes())


def _value_report(wire, words, rows):
    vals = B.unpack_bits(words, len(rows))
    count = int(vals.sum())
    examples = [{"input": int(rows[i]), "value": int(vals[i])} for i in range(min(MAX_EXAMPLES, len(rows)))]
    return {
        "wire": wire,
        "count_zero": int(len(rows) - count),
        "count_one": count,
        "constant": 0 if count == 0 else (1 if count == len(rows) else None),
        "signature_sha256": _array_hash(words, rows),
        "examples": examples,
    }


def _check_query_shape(query):
    if type(query) is not dict or type(query.get("type")) is not str:
        raise ValueError("query must be an object with a string type")
    kind = query["type"]
    if kind == "value":
        if set(query) != {"type", "at", "wires", "level"}:
            raise ValueError("value query fields must be type, at, wires, level")
        return kind
    if kind in ("fit_recompute", "check_relation"):
        required = {"type", "wire", "after", "before", "basis", "validation"}
        expected = required | ({"degree"} if kind == "fit_recompute" else {"terms"})
        if set(query) != expected:
            raise ValueError(f"{kind} query fields must be {', '.join(sorted(expected))}")
        return kind
    raise ValueError("unknown query type")


def _validated_relation(query, nops):
    wire = _integer(query["wire"], "wire", 0)
    after = _integer(query["after"], "after", 0, nops)
    before = _integer(query["before"], "before", 0, nops)
    if not after < before <= nops:
        raise ValueError("require 0 <= after < before <= nops")
    basis = query["basis"]
    if type(basis) is not list or len(basis) > MAX_BASIS:
        raise ValueError("basis must be a list of at most 12 wires")
    if any(type(q) is not int or q < 0 for q in basis) or len(set(basis)) != len(basis):
        raise ValueError("basis wires must be distinct nonnegative integers")
    if wire in basis:
        raise ValueError("basis must exclude target wire")
    if "degree" in query and (type(query["degree"]) is not int or query["degree"] not in (1, 2)):
        raise ValueError("degree must be 1 or 2")
    if query["validation"] not in ("sampled", "full"):
        raise ValueError("validation must be 'sampled' or 'full'")
    return wire, after, before, sorted(basis)


def _wire_touched(op, wire):
    return wire in op.q


def _condition_depth(ops, boundary):
    """Condition-stack depth immediately before operation ``boundary``."""
    depth = 0
    for op in ops[:boundary]:
        if op.code == B.C_PUSH:
            depth += 1
        elif op.code == B.C_POP:
            depth -= 1
            if depth < 0:
                raise ValueError("condition stack pops below depth zero")
    return depth


def _term_names(term):
    if term == ["1"]:
        return ("1",)
    return tuple(f"q{q}" for q in term)


def _parse_terms(terms, basis):
    if type(terms) is not list or len(terms) > MAX_TERMS:
        raise ValueError("terms must be a list of at most 16 monomials")
    out = []
    seen = set()
    for term in terms:
        if type(term) is not list or len(term) not in (1, 2):
            raise ValueError("each term must be ['1'], [wire], or [wire, wire]")
        if term == ["1"]:
            parsed = ("1",)
        else:
            normalized = []
            for q in term:
                if type(q) is int:
                    wire = q
                elif type(q) is str and q.startswith("q") and q[1:].isdigit():
                    wire = int(q[1:])
                else:
                    raise ValueError("term wires must be basis indices or canonical qN strings")
                if wire not in basis:
                    raise ValueError("term wires must be in basis")
                normalized.append(wire)
            if len(term) == 2 and (normalized[0] == normalized[1] or normalized[0] > normalized[1]):
                raise ValueError("quadratic term wire pair must be distinct and sorted")
            parsed = tuple(f"q{q}" for q in normalized)
        if parsed in seen:
            raise ValueError("duplicate term")
        seen.add(parsed)
        out.append(parsed)
    return out


def _infer_terms(words_by_wire, target, basis, degree, nrows):
    allones = (1 << nrows) - 1
    feats = [(('1',), allones)] + [((f"q{q}",), CF.to_int(words_by_wire[q], nrows)) for q in basis]
    if degree == 2:
        for i, qa in enumerate(basis):
            for qb in basis[i + 1:]:
                feats.append(((f"q{qa}", f"q{qb}"), CF.to_int(words_by_wire[qa], nrows) & CF.to_int(words_by_wire[qb], nrows)))
    solution = CF.solve(feats, CF.to_int(target, nrows))
    return None if solution is None else [[name for name in term] if term != ("1",) else ["1"] for term in solution]


def _eval_terms(terms, words_by_wire, nrows):
    result = np.zeros((nrows + 63) // 64, dtype=np.uint64)
    for term in terms:
        if term == ("1",):
            result ^= B.ALL1
        elif len(term) == 1:
            result ^= words_by_wire[int(term[0][1:])]
        else:
            result ^= words_by_wire[int(term[0][1:])] & words_by_wire[int(term[1][1:])]
    return result


def _action_terms(terms):
    return [list(term) for term in terms]


def _row_state_sha(rows):
    return _digest_bytes(np.asarray(rows, dtype="<i8").tobytes())


def _counterexample(target, proposed, rows, valid):
    diff = (target ^ proposed) & valid
    unpacked = B.unpack_bits(diff, len(rows))
    ix = np.flatnonzero(unpacked)
    if not len(ix):
        return None
    i = int(ix[0])
    return {"input": int(rows[i]), "target": int(B.unpack_bits(target, len(rows))[i]), "proposed": int(B.unpack_bits(proposed, len(rows))[i])}


def _relation(evaluator, path, query, ops, xq, nq, inferred):
    nops = len(ops)
    wire, after, before, basis = _validated_relation(query, nops)
    if wire >= nq or any(q >= nq for q in basis):
        raise ValueError("wire index exceeds circuit width")
    # Boundary after+1 holds the value to erase; before is the recompute interface.
    if any(_wire_touched(ops[i], wire) for i in range(after + 1, before)):
        raise ValueError("target wire is touched inside the open gap")
    points = (after + 1, before)
    if any(_condition_depth(ops, point) != 0 for point in points):
        raise ValueError("erase/reconstruction boundary is inside a condition block")
    select = sorted(set([wire] + basis))
    validation = _rows(evaluator, query["validation"])
    infer_terms = None
    if inferred:
        infer_rows = _rows(evaluator, "sampled")
        infer_snaps, _ = _selected_snapshots(ops, xq, nq, infer_rows, points, select, "zero")
        # The target and basis are at different boundaries; retain only their selected words.
        infer_target_words = infer_snaps[points[0]][wire]
        infer_terms = _infer_terms(infer_snaps[points[1]], infer_target_words, basis, query["degree"], len(infer_rows))
        if infer_terms is None:
            return {"status": "no_candidate", "candidate_action": None, "checks": [], "scope": "relation only; no nonexistence proof"}
        if len(infer_terms) > MAX_TERMS:
            return {"status": "term_limit", "candidate_action": None, "checks": [], "scope": "inferred expression exceeds 16-term output limit; no nonexistence proof"}
        terms = _parse_terms(infer_terms, basis)
    else:
        terms = _parse_terms(query["terms"], basis)
    checks = []
    failed = None
    for model in MODELS:
        snaps, valid = _selected_snapshots(ops, xq, nq, validation, points, select, model)
        got = _eval_terms(terms, snaps[points[1]], len(validation))
        bad = _counterexample(snaps[points[0]][wire], got, validation, valid)
        check = {"model": model, "rows_checked": len(validation), "matches": bad is None}
        if bad is not None:
            check["counterexample"] = bad
            if failed is None:
                failed = {"model": model, **bad}
        checks.append(check)
        del snaps, valid, got
    passed = all(c["matches"] for c in checks)
    result = {
        "status": "validated" if passed else "counterexample",
        "relation_scope": "selected wire relation at two boundaries under zero/7/101 models; not a whole-circuit rewrite check",
        "validation": query["validation"],
        "rows_checked_per_model": len(validation),
        "models": ["zero", 7, 101],
        "all_measurement_histories": False,
        "terms": _action_terms(terms),
        "checks": checks,
        "counterexample": failed,
    }
    if inferred and passed:
        result["candidate_action"] = {"type": "park_recompute", "wire": wire, "after": after, "before": before, "terms": _action_terms(terms)}
        result["candidate_scope"] = "validated relation in requested models only; full means all legal inputs in three models, not all histories"
    elif inferred:
        result["candidate_action"] = None
    return result


def investigate(evaluator, path, query):
    """Answer a bounded semantic query about an exported circuit, without edits.

    Query forms are ``value``, ``fit_recompute`` and ``check_relation``.  A full
    level means every legal input x for each listed local measurement model; it
    does not cover every measurement history or whole-circuit correctness.
    """
    kind = _check_query_shape(query)
    ops, xq, nq = _load(evaluator, path)
    if kind == "value":
        at = _integer(query["at"], "at", 0, len(ops))
        wires = query["wires"]
        if type(wires) is not list or len(wires) > MAX_VALUE_WIRES:
            raise ValueError("wires must be a list of at most 16 wire indices")
        if any(type(q) is not int or q < 0 or q >= nq for q in wires) or len(set(wires)) != len(wires):
            raise ValueError("wires must be distinct in-range integers")
        level = query["level"]
        rows = _rows(evaluator, level)
        reports = []
        for model in MODELS:
            snaps_by_point, _valid = _selected_snapshots(ops, xq, nq, rows, [at], wires, model)
            snaps = snaps_by_point[at]
            states = [snaps[q] for q in wires]
            state_payload = np.asarray(rows, dtype="<i8").tobytes() + b"".join(np.asarray(snaps[q], dtype="<u8").tobytes() for q in wires)
            reports.append({"model": model, "wires": [_value_report(q, snaps[q], rows) for q in wires], "state_sha256": _digest_bytes(state_payload)})
            del snaps, states, state_payload
        source_sha = _digest_bytes(Path(path).read_bytes())
        return {"type": "value", "boundary": at, "level": level, "rows_checked": len(rows), "input_state_sha256": _row_state_sha(rows),
                "circuit_sha256": source_sha, "source_sha256": source_sha, "models": reports,
                "scope": "selected wire values only; no whole-circuit validity claim", "all_measurement_histories": False}
    result = _relation(evaluator, path, query, ops, xq, nq, inferred=(kind == "fit_recompute"))
    result["input_state_sha256"] = _row_state_sha(_rows(evaluator, query["validation"]))
    result["circuit_sha256"] = _digest_bytes(Path(path).read_bytes())
    result["source_sha256"] = result["circuit_sha256"]
    return result

