"""Bounded-memory native diagnostics with reference-table reuse per chunk group.

This is a new performance experiment; the frozen ``ssr_stream`` receipt format
and evaluator remain unchanged.  It retains that stream's native seed schedule,
padding, model aggregates and diagnostic-only evidence scope.
"""
from pathlib import Path
import sys
import time
import hashlib
import math

import numpy as np

HERE = Path(__file__).resolve().parent
from ssr.native.adapter import NativeProbe, V, sha  # noqa: E402


class StreamingProbe(NativeProbe):
    def __init__(self, engine_python, contract):
        super().__init__(engine_python, contract)
        # Bind the implementation into the backend identity checked at entry
        # and exit, matching the original native probe's drift protection.
        self.identity[str(Path(__file__))] = sha(__file__)

    def evaluate(self, path, threads=1, group_chunks=16, seeds=(7, 101)):
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError("threads must be 1..4")
        if type(group_chunks) is not int or not 1 <= group_chunks <= 32:
            raise ValueError("group_chunks must be 1..32")
        if not seeds or len(seeds) > 3 or any(type(s) is not int or not 0 <= s < 2**256 for s in seeds):
            raise ValueError("invalid seeds")

        self._guard()
        start = time.perf_counter()
        state = sha(path)
        prog = self.ke.compile_kmb(path)
        regs = prog.registers
        if (len(regs) != 1 or regs[0][0] != "x" or
                len(regs[0][1]) != self.contract["width"] or
                not all(is_qubit for is_qubit, _wire in regs[0][1])):
            raise ValueError("invalid x register")
        xids = [int(wire) for _is_qubit, wire in regs[0][1]]
        if len(set(xids)) != len(xids):
            raise ValueError("duplicate x wire")
        compile_seconds = time.perf_counter() - start

        maxx = self.contract["max_x"]
        chunk_rows = 16384
        nchunks = (maxx + chunk_rows - 1) // chunk_rows
        # Keep only O(seeds) scalar/hasher state between groups.  Rows,
        # references and engine output arrays are released before advancing.
        states = []
        for seed in seeds:
            states.append({
                "seed": seed,
                "phase_hash": hashlib.sha256(),
                "minimum_margin_units": 2**64,
                "worst_error_over_tolerance": 0.0,
                "worst_x": 1,
                "first_failure": None,
                "toffolis": 0,
                "t_count": 0,
                "rotations": 0,
                "executed_rows": 0,
                "covered_legal_rows": 0,
            })

        reference_seconds = 0.0
        reference_calls = 0
        reference_rows = 0
        for lo in range(0, nchunks, group_chunks):
            hi = min(nchunks, lo + group_chunks)
            # A group is bounded by 32 * 16,384 rows.  Its fixed-size tail is
            # padded exactly as in ssr.stream.stream.
            raw = np.arange(lo * chunk_rows + 1, hi * chunk_rows + 1, dtype=np.uint64)
            rows = np.minimum(raw, maxx)
            xs = rows.reshape(hi - lo, 64, 256)
            t_ref = time.perf_counter()
            target, tol = V.reference_values(self.spec, rows)
            reference_seconds += time.perf_counter() - t_ref
            reference_calls += 1
            reference_rows += len(rows)
            valid_rows = min(len(rows), maxx - lo * chunk_rows)

            # Seed remains the outer semantic model; each group gets the same
            # independently derived chunk seeds and each chunk keeps one
            # simulator stream across its 64 batches.
            for record in states:
                seed = record["seed"]
                derived = [
                    int.from_bytes(
                        hashlib.sha256(seed.to_bytes(32, "little") + i.to_bytes(8, "little")).digest(),
                        "little",
                    )
                    for i in range(lo, hi)
                ]
                out = self.ke.run(prog, derived, xs, xids, threads=threads, counting=True)
                phase = out["phase_units"].reshape(-1)
                err = (phase - target).view(np.int64)
                used = np.abs(err).view(np.uint64)
                x_out = out["x_out"].reshape(-1)
                scratch_dirty = out["scratch_dirty"].reshape(-1).astype(bool)
                good = (x_out == rows) & ~scratch_dirty & (used <= tol)

                record["phase_hash"].update(phase[:valid_rows].astype("<u8").tobytes())
                record["covered_legal_rows"] += valid_rows
                record["executed_rows"] += len(rows)
                if not good.all() and record["first_failure"] is None:
                    j = int(np.flatnonzero(~good)[0])
                    record["first_failure"] = {
                        "x": int(rows[j]),
                        "x_restored": bool(x_out[j] == rows[j]),
                        "scratch_clean": not bool(scratch_dirty[j]),
                        "phase_ok": bool(used[j] <= tol[j]),
                    }
                if good.all():
                    record["minimum_margin_units"] = min(
                        record["minimum_margin_units"], int((tol - used).min())
                    )
                ratio = used / tol
                j = int(ratio.argmax())
                # Strict comparison intentionally preserves the original
                # first-seen x on equal worst ratios across groups.
                if ratio[j] > record["worst_error_over_tolerance"]:
                    record["worst_error_over_tolerance"] = float(ratio[j])
                    record["worst_x"] = int(rows[j])
                record["toffolis"] += int(out["toffoli_count"].sum())
                record["t_count"] += int(out["z_levels"][:, 3].sum())
                record["rotations"] += int(out["z_levels"][:, 4:].sum())

                # Do not retain per-group/per-seed state arrays across groups.
                del out, phase, err, used, x_out, scratch_dirty, good, ratio
            del raw, rows, xs, target, tol

        models = []
        for record in states:
            models.append({
                "seed": record["seed"],
                "covered_legal_rows": record["covered_legal_rows"],
                "executed_rows": record["executed_rows"],
                "valid": record["first_failure"] is None,
                "first_failure": record["first_failure"],
                "phase_sha256": record["phase_hash"].hexdigest(),
                "minimum_margin_units": (record["minimum_margin_units"]
                                         if record["first_failure"] is None else None),
                "worst_error_over_tolerance": record["worst_error_over_tolerance"],
                "worst_x": record["worst_x"],
                "toffolis": record["toffolis"],
                "t_count": record["t_count"],
                "rotations": record["rotations"],
            })

        valid = all(model["valid"] for model in models)
        loss = None
        if valid:
            margin = min(model["minimum_margin_units"] for model in models)
            mt = np.mean([model["toffolis"] / model["executed_rows"] for model in models])
            nt = np.mean([model["t_count"] / model["executed_rows"] for model in models])
            nr = np.mean([model["rotations"] / model["executed_rows"] for model in models])
            eps = math.pi * margin / 2**64 / nr if nr else None
            if nr and eps <= 0:
                valid = False
            else:
                loss = float(prog.num_qubits * (mt + (nt + nr * V.rotation_t_count(eps) if nr else nt) /
                                                 V.T_PER_TOFFOLI))

        self._guard()
        if sha(path) != state:
            raise ValueError("circuit changed during evaluation")
        return {
            "schema": "ssr-native-stream-v2/1",
            "state_sha256": state,
            "contract": self.contract,
            "backend_sha256": self.identity,
            "kernel": self.ke.kernel_info(),
            "valid_on_native_models": valid,
            "models": models,
            "declared_qubits": prog.num_qubits,
            "loss_estimate": loss,
            "loss_scope": "native fixed-seed formula estimate; counts include repeated final input padding; not official expected cost",
            "coverage": "all legal x per native seed, not all measurement histories",
            "schedule": {
                "chunk_rows": chunk_rows,
                "chunk_seed": "SHA256(seed_le32||chunk_index_le8)",
                "group_chunks": group_chunks,
                "threads": threads,
                "padding": "repeat final legal input to fixed16384-row chunk",
            },
            "dirty_reset_check": "unavailable; final scratch only",
            "transition_acceptance": False,
            "compile_seconds": compile_seconds,
            "reference_seconds": reference_seconds,
            "reference_calls": reference_calls,
            "reference_rows": reference_rows,
            "seconds": time.perf_counter() - start,
        }
