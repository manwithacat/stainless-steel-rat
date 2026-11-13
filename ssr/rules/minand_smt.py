#!/usr/bin/env python3
"""Bounded minimum-AND straight-line search on a reached-state truth table.

Input rows describe a target *toggle* in terms of current physical control
values. Z3 is an optional dependency. A SAT plan is checked on every supplied
row, but those rows may omit other measurement histories or unreachable
states; this tool never emits a KMB or claims circuit equivalence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def load_table(path: Path, target: str | None = None) -> tuple[list[str], list[tuple[int, int]]]:
    data = json.loads(path.read_text())
    if data.get("schema") == "vqcc-window-reached-table/1":
        if target is None or target not in data["output_wires_lsb_first"]:
            raise ValueError("name an output target in the reached table")
        names = data["input_wires_lsb_first"]
        if target not in names:
            raise ValueError("target before-bit is absent from input support")
        output_bit = data["output_wires_lsb_first"].index(target)
        input_bit = names.index(target)
        if not (data["xor_defined_mask"] >> output_bit) & 1:
            raise ValueError("target toggle is undefined")
        controls = [name for name in names if name != target]
        pairs = []
        for row in data["rows"]:
            x = row["input"]
            projected = sum(((x >> names.index(name)) & 1) << i
                            for i, name in enumerate(controls))
            y = (row["output_xor_input"] >> output_bit) & 1
            pairs.append((projected, y))
    elif "input_names" in data and "rows" in data:
        controls = data["input_names"]
        pairs = [(row["input"], row["toggle"]) for row in data["rows"]]
    else:
        raise ValueError("expected a reached toggle table")
    if not controls or len(controls) > 32 or len(set(controls)) != len(controls):
        raise ValueError("need 1..32 distinct control names")
    by_input: dict[int, int] = {}
    for x, y in pairs:
        if x < 0 or x >= 1 << len(controls) or y not in (0, 1):
            raise ValueError("invalid truth-table row")
        if x in by_input and by_input[x] != y:
            raise ValueError("target toggle conflicts on projected controls")
        by_input[x] = y
    if len(by_input) > 256:
        raise ValueError("search cap: at most 256 reached states")
    return controls, sorted(by_input.items())


def solve(controls: list[str], rows: list[tuple[int, int]],
          gates: int, timeout_seconds: int, *, cegis: bool = False) -> dict:
    try:
        import z3
    except ImportError as exc:
        raise RuntimeError("install the optional z3-solver dependency") from exc
    if not 0 <= gates <= 8 or not 1 <= timeout_seconds <= 600:
        raise ValueError("gates must be 0..8 and timeout 1..600 seconds")
    n = len(controls)
    m = len(rows)
    if m == 0:
        raise ValueError("empty truth table")
    columns = [sum(((x >> i) & 1) << r for r, (x, _) in enumerate(rows))
               for i in range(n)]
    columns.append((1 << m) - 1)  # constant one, index n
    zero = z3.BitVecVal(0, m)
    values = [z3.BitVecVal(c, m) for c in columns]
    flags: list[list[list]] = []
    gate_values = []

    def affine(prefix: str, available: list) -> tuple[list, object]:
        choices = [z3.Bool(f"{prefix}_{i}") for i in range(len(available))]
        value = zero
        for choice, col in zip(choices, available):
            value = value ^ z3.If(choice, col, zero)
        return choices, value

    solver = z3.Solver()
    solver.set(timeout=timeout_seconds * 1000)
    for i in range(gates):
        available = values + gate_values
        left, lv = affine(f"g{i}_left", available)
        right, rv = affine(f"g{i}_right", available)
        solver.add(z3.Or(*left), z3.Or(*right))
        flags.append([left, right])
        gate_values.append(lv & rv)
    output_flags, output = affine("output", values + gate_values)
    wanted = z3.BitVecVal(sum(y << r for r, (_, y) in enumerate(rows)), m)
    started = time.monotonic()
    rounds = 0
    counterexamples = 0

    def plan_and_mismatches(model):
        def selected(items: list) -> list[int]:
            return [i for i, flag in enumerate(items) if z3.is_true(model.eval(flag))]
        plans = [{"left": selected(left), "right": selected(right)}
                 for left, right in flags]
        terms = selected(output_flags)
        mismatches = []
        for r, (x, expected) in enumerate(rows):
            values_row = [(x >> i) & 1 for i in range(n)] + [1]
            for plan in plans:
                left = sum(values_row[i] for i in plan["left"]) & 1
                right = sum(values_row[i] for i in plan["right"]) & 1
                values_row.append(left & right)
            if (sum(values_row[i] for i in terms) & 1) != expected:
                mismatches.append(r)
        return plans, terms, mismatches

    if cegis:
        care = {min(m - 1, i * m // min(m, 16)) for i in range(min(m, 16))}
        status = z3.unknown
        for rounds in range(1, 65):
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                status = z3.unknown
                break
            solver.set(timeout=max(1, int(remaining * 1000)))
            mask = z3.BitVecVal(sum(1 << i for i in care), m)
            solver.add(((output ^ wanted) & mask) == zero)
            status = solver.check()
            if status != z3.sat:
                break
            plans, output_terms, mismatches = plan_and_mismatches(solver.model())
            if not mismatches:
                break
            fresh = [i for i in mismatches if i not in care][:8]
            if not fresh:
                raise AssertionError("CEGIS candidate disagrees on constrained rows")
            care.update(fresh)
            counterexamples += len(fresh)
            status = z3.unknown  # last SAT model has not passed all rows
        else:
            status = z3.unknown
    else:
        solver.add(output == wanted)
        status = solver.check()
        rounds = 1
    seconds = time.monotonic() - started
    result = {"status": str(status), "gates_requested": gates,
              "control_names": controls, "care_rows": m,
              "solver_seconds": round(seconds, 4), "timeout_seconds": timeout_seconds,
              "cegis": cegis, "solver_rounds": rounds,
              "counterexamples_added": counterexamples,
              "tier": "exact on supplied reached-state table only"}
    if status != z3.sat:
        result["solver_reason"] = (solver.reason_unknown() if status == z3.unknown
                                   else None)
        return result
    plans, output_terms, mismatches = plan_and_mismatches(solver.model())
    if mismatches:
        raise AssertionError("solver model failed independent row replay")
    result.update(gates=plans, output_terms=output_terms,
                  index_convention="0..n-1 controls, n constant one, n+1 onward prior AND outputs",
                  independent_row_replay=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--target", help="output wire for a vqcc-window-reached-table")
    parser.add_argument("--gates", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--cegis", action="store_true",
                        help="start with 16 care rows and add counterexamples")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refuse to overwrite output")
    try:
        names, rows = load_table(args.table, args.target)
        result = solve(names, rows, args.gates, args.timeout, cegis=args.cegis)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    result["source_table"] = str(args.table)
    result["source_table_sha256"] = hashlib.sha256(args.table.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "care_rows": result["care_rows"],
                      "gates": args.gates, "seconds": result["solver_seconds"],
                      "report": str(args.out)}))


if __name__ == "__main__":
    main()
