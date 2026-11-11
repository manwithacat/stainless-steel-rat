"""Tests for exact row-domain replay and bounded candidate traces."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


from ssr.qhdl import bitsim as B
from ssr.qhdl import edit as EDIT
from ssr.qhdl import kmb as K
from support import need_verifier
need_verifier()
from ssr.mouse.evaluator import InvSqrtEvaluator
from ssr.workbench.trace import TraceError, investigate_trace


def _fixture(path: Path) -> Path:
    """Authored KMB trajectory with an input, seeded HMR and conditional phase."""
    text = [
        "CX q0 q3",
        "HMR q3 b0",
        "PUSH_CONDITION b0",
        "X q4",
        "X q5 if b1",
        "Z_POW q4 angle128:40000000000000000000000000000000",  # 1/4 turn
        "POP_CONDITION",
    ]
    records = [EDIT.parse_op(op) for op in text]
    names = ("qqq0", "qqq1", "qqq2", "qq0", "qq1", "q0", "b0", "bc")
    streams: dict[str, list[int]] = {name: [] for name in names}
    codes: list[int] = []
    angles = bytearray()
    for record in records:
        code = int(record["code"])
        codes.append(code)
        arity = {0x10: ("q0",), 0x20: ("qq0", "qq1"), 0x30: ("qqq0", "qqq1", "qqq2")}.get(code & 0x30, ())
        for name, wire in zip(arity, record.get("q", ())):
            streams[name].append(int(wire))
        if code & 0x40:
            streams["b0"].append(int(record["b0"]))
        if code & 0x80:
            streams["bc"].append(int(record["bc"]))
        if (code & 0x7F) == 0x13:
            angles.extend(record["angle_literal"])
    K.write_kmb(
        str(path), np.asarray(codes, dtype=np.uint8),
        {name: np.asarray(values, dtype=np.uint32) for name, values in streams.items()},
        bytes(angles), registers=(("x", [(True, 0), (True, 1), (True, 2)]),),
        num_qubits=7, num_bits=2,
    )
    return path


class TraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = _fixture(self.root / "trace.kmb")
        self.evaluator = InvSqrtEvaluator(
            {"task": "invsqrt", "width": 3, "max_x": 7, "beta": "1",
             "precision_bits": 24, "official_shots_per_x": 64, "system_qubits": 12},
            self.root / "work", sample_rows=7,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def query(self, **updates):
        result = {"type": "trace", "x": 4, "at": [0, 1, 2, 3, 4, 6, 7],
                  "wires": [0, 3, 4, 5, 6], "bits": [0, 1], "level": "sampled", "outcome": "7"}
        result.update(updates)
        return result

    def independent_export(self) -> Path:
        """The independent simulator uses a temporary header compacted for kickmix export."""
        k = K.read(str(self.source))
        used = K.op_qubits(k)[1]
        highest = max((int(q) for q in used), default=-1)
        highest = max(highest, max((int(q) for _name, content in k.registers
                                    for is_q, q, _pos in content if is_q), default=-1))
        with tempfile.TemporaryDirectory(prefix="qhdl-trace-test-") as td:
            compact = Path(td) / "compact.kmb"
            K.patch_qubits(k, str(compact), {}, {}, highest + 1)
            return self.evaluator.export(compact)

    def test_seeded_trace_replays_full_sampled_row_domain_through_endpoint(self):
        rows = np.asarray(self.evaluator.rows("sampled"), dtype=np.int64)
        result = investigate_trace(self.evaluator, self.source, self.query())
        self.assertEqual(result["status"], "diagnostic")
        self.assertEqual(result["row_count"], len(rows))
        self.assertEqual(result["row_index"], int(np.flatnonzero(rows == 4)[0]))
        self.assertEqual(result["source_sha256"], __import__("hashlib").sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(result["scope"].split(";")[0], "selected input state under the evaluator's fixed local row domain and measurement model")
        points = {row["boundary"]: row for row in result["checkpoints"]}
        self.assertEqual(points[3]["condition_stack_depth"], 1)
        self.assertTrue(points[3]["active_condition"])
        self.assertTrue(points[3]["stack_active"])
        self.assertTrue(points[3]["next_operation_active"])
        self.assertTrue(points[4]["stack_active"])
        self.assertFalse(points[4]["next_operation_active"])  # op's own `if b1` is false
        self.assertEqual(points[7]["condition_stack_depth"], 0)
        self.assertIsNone(points[7]["op_at_boundary"])
        self.assertEqual(points[6]["op_at_boundary"]["opcode"], "POP_CONDITION")

        # The independent end-state oracle sees the same entire fixed row set.
        exported = self.independent_export()
        ops, _header, xq, _used_width = B.load(exported)
        sim = B.BitSim(ops, rows=rows, num_qubits=7, x_qubits=xq, outcome=7).run()
        idx = int(np.flatnonzero(rows == 4)[0])
        self.assertEqual(points[7]["wires"], {str(q): int(sim.q[q, idx // 64] >> np.uint64(idx % 64) & np.uint64(1)) for q in (0, 3, 4, 5, 6)})
        self.assertEqual(points[7]["bits"]["0"], int(sim.bits[0][idx // 64] >> np.uint64(idx % 64) & np.uint64(1)))
        self.assertEqual(points[7]["phase_units_mod_2_64"], int(sim.phase_units()[idx]))
        self.assertEqual(points[7]["active_condition"], sim.act is None or bool((int(sim.act[idx // 64]) >> (idx % 64)) & 1))
        self.assertEqual(len(xq), 3)

        # Replaying x=6 alone changes the seeded HMR row assignment. This is
        # the explicit counterexample that motivates retaining the old row domain.
        # For x=6, bit 5 of seed 7's first packed outcome word differs from
        # bit 0 used by the single-row run.
        seeded = investigate_trace(self.evaluator, self.source, self.query(x=6))
        seeded_end = seeded["checkpoints"][-1]
        one = B.BitSim(ops, rows=np.asarray([6], dtype=np.int64), num_qubits=7,
                       x_qubits=xq, outcome=7).run()
        one_bit = int(one.bits[0][0] & np.uint64(1))
        self.assertNotEqual(seeded_end["bits"]["0"], one_bit)
        self.assertNotEqual(seeded_end["phase_units_mod_2_64"], int(one.phase_units()[0]))

    def test_zero_model_scalar_trajectory_and_declared_unused_wire(self):
        result = investigate_trace(self.evaluator, self.source, self.query(
            x=3, outcome="zero", at=[0, 1, 2, 3, 4, 5, 6, 7], wires=[3, 4, 6], bits=[0]))
        rows = np.asarray(self.evaluator.rows("sampled"), dtype=np.int64)
        idx = int(np.flatnonzero(rows == 3)[0])
        exported = self.independent_export()
        ops, _header, xq, _used_width = B.load(exported)
        sim = B.BitSim(ops, rows=rows, num_qubits=7, x_qubits=xq, outcome="zero").run()
        endpoint = result["checkpoints"][-1]
        self.assertEqual(endpoint["wires"]["6"], 0)  # declared, unused wire is addressable
        self.assertEqual(endpoint["wires"]["3"], int((int(sim.q[3, idx // 64]) >> (idx % 64)) & 1))
        self.assertEqual(endpoint["wires"]["4"], int((int(sim.q[4, idx // 64]) >> (idx % 64)) & 1))
        self.assertEqual(endpoint["phase_units_mod_2_64"], int(sim.phase_units()[idx]))
        self.assertTrue(endpoint["active_condition"])
        self.assertEqual(endpoint["condition_stack_depth"], 0)
        self.assertIsNone(endpoint["next_operation_active"])

    def test_query_limits_types_and_sample_membership(self):
        for query in (self.query(x=True), self.query(at=[True]), self.query(wires=[7]),
                      self.query(bits=[2]), self.query(at=list(range(17))),
                      self.query(outcome="11")):
            with self.subTest(query=query), self.assertRaises(TraceError):
                investigate_trace(self.evaluator, self.source, query)
        self.evaluator.sample_rows = 2
        with self.assertRaisesRegex(TraceError, "use level='full'"):
            investigate_trace(self.evaluator, self.source, self.query(x=4, level="sampled"))

    def test_full_level_and_invalid_source_are_diagnostic_not_validation(self):
        result = investigate_trace(self.evaluator, self.source, self.query(level="full", x=4))
        self.assertEqual(result["level"], "full")
        self.assertEqual(result["row_count"], 7)
        self.assertIn("no full validation claim", result["scope"])
        with self.assertRaisesRegex(TraceError, "existing .kmb"):
            investigate_trace(self.evaluator, self.root / "missing.kmb", self.query())


if __name__ == "__main__":
    unittest.main()
