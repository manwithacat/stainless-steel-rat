"""Guard tests for bounded KMB circuit-mouse actions."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


from ssr.qhdl import edit as EDIT
from ssr.qhdl import kmb as KMB
from ssr.mouse.actions import ActionError, apply_action


def write_kmb(path: Path, ops: list[str], num_qubits: int = 6, num_bits: int = 1,
              registers: tuple = ()) -> Path:
    records = [EDIT.parse_op(text) for text in ops]
    streams: dict[str, list[int]] = {name: [] for name in
                                     ("qqq0", "qqq1", "qqq2", "qq0", "qq1", "q0", "b0", "bc")}
    codes: list[int] = []
    angles = bytearray()
    for record in records:
        code = int(record["code"])
        codes.append(code)
        if "copy" in record:
            raise AssertionError("fixture helper accepts only explicit ops")
        cls = code & 0x30
        names = {0x30: ("qqq0", "qqq1", "qqq2"), 0x20: ("qq0", "qq1"), 0x10: ("q0",)}.get(cls, ())
        for name, q in zip(names, record.get("q", ())):
            streams[name].append(int(q))
        if code & 0x40:
            streams["b0"].append(int(record["b0"]))
        if code & 0x80:
            streams["bc"].append(int(record["bc"]))
        if (code & 0x7F) == 0x13:
            angles.extend(record["angle_literal"])
    KMB.write_kmb(
        str(path), np.asarray(codes, dtype=np.uint8),
        {name: np.asarray(values, dtype=np.uint32) for name, values in streams.items()},
        bytes(angles), registers=registers, num_qubits=num_qubits, num_bits=num_bits,
    )
    return path


def angle_bytes(path: Path) -> bytes:
    k = KMB.read(str(path))
    off, n, _ = k.offsets["angles"]
    return bytes(k.raw[off:off + 16 * n])


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.kmb"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def out(self, name: str) -> Path:
        return self.root / name

    def test_reserve_qubits_only_changes_declared_width(self) -> None:
        write_kmb(self.source, ["X q0", "CX q0 q1", "HMR q1 b0"], num_qubits=3)
        result = apply_action(self.source, {"type": "reserve_qubits", "num_qubits": 7}, self.out("reserve"))
        candidate = Path(result["candidate_path"])
        self.assertEqual(int(KMB.read(str(candidate)).num_qubits), 7)
        self.assertEqual(self.source.read_bytes()[24:], candidate.read_bytes()[24:])
        self.assertEqual(result["precondition_evidence"]["added_clean_qubits"], 4)
        with self.assertRaisesRegex(ActionError, "increase of 1..16"):
            apply_action(self.source, {"type": "reserve_qubits", "num_qubits": 3}, self.out("no-growth"))

    def test_park_factored_checks_cut_scratch_and_source_hash(self) -> None:
        write_kmb(self.source, ["X q0", "CX q0 q1", "X q2", "CX q1 q2"], num_qubits=5)
        source_sha = __import__("hashlib").sha256(self.source.read_bytes()).hexdigest()
        request = {"type": "park_factored", "expected_source_sha256": source_sha,
                   "wire": 1, "after": 1, "before": 3, "scratch": [3, 4],
                   "products": [{"left": [0], "right": [2]}], "affine": [0], "constant": True}
        result = apply_action(self.source, request, self.out("factored"))
        out = KMB.read(result["candidate_path"])
        self.assertEqual(int(out.num_bits), 2)
        self.assertEqual(result["precondition_evidence"]["products"], 1)
        self.assertEqual(result["proofscope"]["semantic_equivalence"], "cross_cut_relation_unproved_by_action")
        with self.assertRaisesRegex(ActionError, "source SHA mismatch"):
            apply_action(self.source, {**request, "expected_source_sha256": "0" * 64}, self.out("wrong-source"))
        with self.assertRaisesRegex(ActionError, "scratch wire is live"):
            apply_action(self.source, {**request, "scratch": [2, 4]}, self.out("live-scratch"))

    def test_park_one_scratch_requires_physical_left_factor(self) -> None:
        write_kmb(self.source, ["X q0", "CX q0 q1", "X q2", "CX q1 q2"], num_qubits=5)
        source_sha = __import__("hashlib").sha256(self.source.read_bytes()).hexdigest()
        request = {"type": "park_one_scratch", "expected_source_sha256": source_sha,
                   "wire": 1, "after": 1, "before": 3, "scratch": [4],
                   "products": [{"left": [0], "right": [2, 3]}], "affine": [], "constant": False}
        result = apply_action(self.source, request, self.out("one-scratch"))
        self.assertEqual(result["precondition_evidence"]["products"], 1)
        self.assertEqual(result["precondition_evidence"]["scratch"], [4])
        with self.assertRaisesRegex(ActionError, "one physical wire"):
            apply_action(self.source, {**request, "products": [{"left": [0, 2], "right": [3]}]},
                         self.out("bad-one-scratch"))

    def test_recolour_uses_pinned_registers_and_independent_check(self) -> None:
        write_kmb(
            self.source,
            ["Z_POW q0 angle128:0123456789abcdef0123456789abcdef", "X q1", "HMR q1 b0", "X q2"],
            num_qubits=7, num_bits=1, registers=(("x", [(True, 0)]),),
        )
        result = apply_action(self.source, {"type": "recolour"}, self.out("recolour"))
        candidate = Path(result["candidate_path"])
        out_k = KMB.read(str(candidate))
        self.assertEqual(out_k.num_qubits, 2)
        self.assertEqual(angle_bytes(candidate), angle_bytes(self.source))
        self.assertTrue(result["precondition_evidence"]["pinned_registers"])
        self.assertEqual(result["proofscope"]["semantic_equivalence"], "structural_lifetime_renaming_checked")
        self.assertEqual(result["precondition_evidence"]["allocator_check"]["status"], "EQUIVALENT")

    def test_advance_hmr_moves_only_across_wire_and_classical_disjoint_ops(self) -> None:
        write_kmb(self.source, [
            "X q0", "X q1", "CX q0 q1", "Z_POW q0 angle128:ffeeddccbbaa99887766554433221100",
            "HMR q2 b0", "X q3",
        ], num_qubits=4, num_bits=1)
        result = apply_action(self.source, {"type": "advance_hmr", "op": 4, "after": 1}, self.out("advance"))
        candidate = Path(result["candidate_path"])
        out = KMB.read(str(candidate))
        self.assertEqual(int(out.op_types[2]), KMB.HMR)
        self.assertEqual(int(out.stream("q0")[2]), 2)
        self.assertEqual(int(out.stream("b0")[0]), 0)
        self.assertEqual(angle_bytes(candidate), angle_bytes(self.source))
        self.assertEqual(result["proofscope"]["semantic_equivalence"], "disjoint_interference_certificate")

    def test_advance_hmr_refuses_measurement_bit_hazard_and_bad_bounds(self) -> None:
        write_kmb(self.source, ["X q0", "X q1", "BIT_STORE0 b0", "HMR q2 b0"], num_qubits=3, num_bits=1)
        with self.assertRaisesRegex(ActionError, "measurement bit"):
            apply_action(self.source, {"type": "advance_hmr", "op": 3, "after": 0}, self.out("bit-hazard"))
        write_kmb(self.source, ["X q0", "HMR q2 b0", "X q1"], num_qubits=3, num_bits=1)
        with self.assertRaisesRegex(ActionError, "0 <= after"):
            apply_action(self.source, {"type": "advance_hmr", "op": 1, "after": 0}, self.out("bounds"))

    def test_park_recompute_emits_guarded_candidate_without_expression_claim(self) -> None:
        write_kmb(self.source, ["X q0", "X q2", "CX q0 q2", "X q1"], num_qubits=4, num_bits=1)
        result = apply_action(self.source, {
            "type": "park_recompute", "wire": 1, "after": 0, "before": 3,
            "terms": [["q0"], ["q0", "q2"], ["1"]],
        }, self.out("park"))
        candidate = Path(result["candidate_path"])
        out = KMB.read(str(candidate))
        self.assertEqual(int(out.op_types[1]), KMB.HMR)
        self.assertEqual(result["proofscope"]["semantic_equivalence"], "not_established")
        self.assertEqual(result["precondition_evidence"]["fresh_measurement_bit"], 1)
        self.assertEqual(result["precondition_evidence"]["quadratic_products_emitted"], 1)

    def test_park_recompute_refuses_bad_wire_overlap_and_bad_polynomial(self) -> None:
        write_kmb(self.source, ["X q0", "X q1", "X q2"], num_qubits=3, num_bits=1)
        with self.assertRaisesRegex(ActionError, "outside"):
            apply_action(self.source, {"type": "park_recompute", "wire": 3, "after": 0,
                                      "before": 2, "terms": []}, self.out("bad-wire"))
        with self.assertRaisesRegex(ActionError, "touched inside"):
            apply_action(self.source, {"type": "park_recompute", "wire": 1, "after": 0,
                                      "before": 2, "terms": [["q0"]]}, self.out("overlap"))
        with self.assertRaisesRegex(ActionError, "may not depend"):
            apply_action(self.source, {"type": "park_recompute", "wire": 1, "after": 0,
                                      "before": 3, "terms": [["q1"]]}, self.out("self-term"))

    def test_replace_window_is_bounded_parsed_and_does_not_claim_validity(self) -> None:
        write_kmb(self.source, ["X q0", "Z_POW q1 angle128:0123456789abcdef0123456789abcdef", "X q2"],
                  num_qubits=4, num_bits=1)
        result = apply_action(self.source, {"type": "replace_window", "start": 0, "end": 1,
                                            "ops": ["CX q0 q2", "Z_POW q1 angle128:fedcba9876543210fedcba9876543210"]},
                             self.out("replace"))
        self.assertEqual(result["proofscope"]["semantic_equivalence"], "not_established")
        self.assertEqual(KMB.read(result["candidate_path"]).num_qubits, 4)
        with self.assertRaisesRegex(ActionError, "PUSH_CONDITION"):
            apply_action(self.source, {"type": "replace_window", "start": 0, "end": 1,
                                      "ops": ["PUSH_CONDITION b0"]}, self.out("stack"))
        with self.assertRaisesRegex(ActionError, "exceeds 256"):
            apply_action(self.source, {"type": "replace_window", "start": 0, "end": 0,
                                      "ops": ["X q0"] * 257}, self.out("too-many"))

    def test_outdir_must_be_fresh(self) -> None:
        write_kmb(self.source, ["X q0"], num_qubits=1)
        target = self.out("existing")
        target.mkdir()
        with self.assertRaisesRegex(ActionError, "already exists"):
            apply_action(self.source, {"type": "replace_window", "start": 0, "end": 0,
                                      "ops": ["X q0"]}, target)


if __name__ == "__main__":
    unittest.main()
