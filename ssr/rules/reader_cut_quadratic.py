#!/usr/bin/env python3
"""Fit a target accumulation as a quadratic of wires at its first reader.

This finds a more useful interface than the first CCX: non-target address
wires may evolve before the target is read. The fit is a finite-panel proposal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from ssr.crosscut import rule as C
from ssr.qhdl import bitsim as B
from ssr.rules import quadratic_rank as Q
from ssr.rules import target_accumulation as A


def _reader(ops, target: int, end: int) -> int:
    for i in range(end, len(ops)):
        o = ops[i]
        if target not in o.q:
            continue
        if o.code == B.C_X or (o.code in (B.C_CX, B.C_CCX) and o.q[-1] == target):
            continue
        return i
    raise ValueError("target has no later reader")


def _pack_entry(sim: B.BitSim, target: int, nq: int) -> np.ndarray:
    if nq >= 63:
        raise ValueError("reader fit currently supports fewer than 63 qubits")
    values = np.zeros(sim.n, np.uint64)
    for wire in range(nq):
        if wire != target:
            values |= B.unpack_bits(sim.q[wire], sim.n).astype(np.uint64) << np.uint64(wire)
    return values


def analyze(source: Path, handle: str, *, sample_rows: int = 8192,
            outcomes: tuple[str, ...] = ("zero", "7", "101"),
            trials: int = 1) -> dict:
    source = Path(source)
    site = A.resolve(source, handle)
    if not 128 <= sample_rows <= B.MAX_X or not 1 <= len(outcomes) <= 4 or not 1 <= trials <= 128:
        raise ValueError("invalid sample size or outcome count")
    header, _, ops, nq = Q.load(source)
    xq = [int(line.split()[1][1:]) for line in header if line.startswith("APPEND_TO_REGISTER ")]
    start, end = site["ops"]
    target = site["target"]
    reader = _reader(ops, target, end)
    positions = [i for i in range(start, end)
                 if ops[i].code == B.C_CCX and ops[i].q[-1] == target]
    rows = np.sort(np.random.default_rng(20261113).choice(B.legal_rows(),
                                                          size=sample_rows, replace=False))
    pairs = set()
    for outcome in outcomes:
        sim = B.BitSim(ops, rows=rows, num_qubits=nq, x_qubits=xq, outcome=outcome)
        products = np.zeros(sim.W, np.uint64)
        def capture(i, state):
            a, b, _ = ops[i].q
            products[:] ^= state.q[a] & state.q[b]
        sim.run(stop=reader, snaps=positions, on_snap=capture)
        values = _pack_entry(sim, target, nq)
        toggles = B.unpack_bits(products, sim.n)
        pairs.update((int(x), int(y)) for x, y in zip(values, toggles))
    by_entry = {}
    for entry, toggle in pairs:
        by_entry.setdefault(entry, set()).add(toggle)
    conflicts = sum(len(values) > 1 for values in by_entry.values())
    result = {"schema": "ssr-reader-cut-quadratic/1",
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "site_handle": handle, "ops": [start, end], "reader_op": reader,
              "target": target, "outcomes": list(outcomes),
              "sample_random_seed": 20261113, "sample_rows_per_outcome": sample_rows,
              "unique_reader_states": len(by_entry), "conflicting_toggle_states": conflicts,
              "tier": "fixed-outcome finite legal-input proposal",
              "limits": "fit excludes phase, other measurement histories and KMB construction"}
    if conflicts:
        result["status"] = "toggle_not_determined_by_reader_wires"
        return result
    states = sorted(by_entry)
    count = len(states)
    packed = np.zeros((nq, (count + 63) // 64), dtype=np.uint64)
    for wire in range(nq):
        packed[wire] = B.pack_bits(np.array([bool((value >> wire) & 1) for value in states]))
    wanted = B.pack_bits(np.array([bool(next(iter(by_entry[value]))) for value in states]))
    valid = B.pack_bits(np.ones(count, bool))
    best = None
    fit_trials = 0
    generator = np.random.default_rng(20261114)
    for trial in range(trials):
        permutation = list(range(nq)) if trial == 0 else list(map(int, generator.permutation(nq)))
        proposed = C.solve_quadratic(int.from_bytes(wanted.tobytes(), "little"),
                                     packed[permutation], valid, permutation.index(target))
        fit_trials += 1
        if proposed is None:
            continue
        poly = _unpermute(proposed, permutation)
        if not np.array_equal(C.evaluate(poly, packed, valid), wanted):
            raise AssertionError("quadratic fit failed independent table replay")
        factors, linear, constant = C.factor(poly)
        candidate = (len(factors), trial, proposed, poly, factors, linear, constant)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
        if len(factors) <= 4:
            break
    result.update(fit_trials=fit_trials, trial_seed=20261114)
    if best is None:
        result["status"] = "no_quadratic_fit"
        return result
    _, selected_trial, proposed, poly, factors, linear, constant = best
    result.update(status="quadratic_fit", selected_trial=selected_trial,
                  affine_basis_rank=proposed["affine_basis_rank"],
                  quadratic_feature_rank=proposed["quadratic_feature_rank"],
                  factor_count=len(factors), quadratic_rank=2 * len(factors),
                  products=[[a, b] for a, b in factors], linear=linear, constant=constant,
                  independent_table_replay=True)
    return result


def _unpermute(poly: dict, permutation: list[int]) -> dict:
    nq = len(permutation)
    linear = sum(1 << permutation[i] for i in range(nq) if (poly["linear"] >> i) & 1)
    adjacency = [0] * nq
    for i, row in enumerate(poly["adj"]):
        for j in range(nq):
            if (row >> j) & 1:
                adjacency[permutation[i]] ^= 1 << permutation[j]
    return {"linear": linear, "constant": poly["constant"], "adj": adjacency}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--handle", required=True)
    parser.add_argument("--rows", type=int, default=8192)
    parser.add_argument("--outcomes", default="zero,7,101")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refuse to overwrite output")
    try:
        result = analyze(args.source, args.handle, sample_rows=args.rows,
                         outcomes=tuple(args.outcomes.split(",")), trials=args.trials)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "reader": result["reader_op"],
                      "states": result["unique_reader_states"],
                      "factors": result.get("factor_count"), "out": str(args.out)}))


if __name__ == "__main__":
    main()
