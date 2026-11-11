from __future__ import annotations

import hashlib
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
import sys

import numpy as np

from support import need_kickmix
km = need_kickmix()
from ssr.workbench.structure import StructureError, inspect
from ssr.qhdl import kmb as K


def native_kickmix_fixture(path: Path) -> None:
    builder = km.CircuitBuilder()
    with builder.mark("top-region"):
        builder.cx(km.q(0), km.q(2))
        builder.z_pow(km.q(2), Fraction(1, 4))
        builder.cx(km.q(1), km.q(2))
    builder.finish_circuit().to_file(path, format="kmb")


def structured_fixture(path: Path) -> None:
    # Includes a pinned input, scratch reuse after unconditional reset, a
    # phase operation in a wire's touch stream, and a classical condition.
    types = np.array([0x11, 0x13, 0x12, 0x81, 0xA1, 0x01, 0x11], dtype=np.uint8)
    streams = {
        "q0": np.array([0, 2, 1, 2], dtype=np.uint32),
        "qq0": np.array([0], dtype=np.uint32), "qq1": np.array([1], dtype=np.uint32),
        "bc": np.array([0, 0], dtype=np.uint32),
    }
    # The angle stream is one exact little-endian full-turn value: 1/4.
    angle = (1 << 126).to_bytes(16, "little")
    regs = [("input", [(True, 0), (False, 0)])]
    K.write_kmb(path, types, streams, angles=angle, registers=regs, num_qubits=5, num_bits=1)


class StructureTests(unittest.TestCase):
    def test_native_kickmix_overview_window_angle_and_region(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "native.kmb"
            native_kickmix_fixture(p)
            overview = inspect(p, {"kind": "overview"})
            self.assertEqual(overview["operation_count"], 5)  # enter/tag/gates/exit
            self.assertEqual(overview["top_level_regions"][0]["name"], "top-region")
            self.assertEqual(overview["top_level_regions"][0]["start"], 1)
            self.assertEqual(overview["source_sha256"], hashlib.sha256(p.read_bytes()).hexdigest())
            window = inspect(p, {"kind": "window", "start": 1, "end": 4})
            self.assertEqual([r["opcode"] for r in window["operations"]], ["CX", "Z_POW", "CX"])
            self.assertEqual(window["operations"][1]["angle128_le_hex"], (1 << 125).to_bytes(16, "little").hex())
            self.assertEqual(window["operations"][1]["q"], [2])

    def test_wire_reports_phase_gap_reset_and_pinned_register(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.kmb"
            structured_fixture(p)
            self.assertEqual(inspect(p, {"kind": "overview"})["declared_qubits"], 5)
            w2 = inspect(p, {"kind": "wire", "wire": 2})
            self.assertEqual(w2["role"], "scratch")
            self.assertEqual(w2["touch_count"], 2)
            self.assertEqual(w2["phase_touches_total"], 1)
            self.assertEqual(w2["max_gap_between_touches"], 4)
            w1 = inspect(p, {"kind": "wire", "wire": 1})
            self.assertEqual(w1["phase_touches_total"], 0)
            self.assertTrue(any(x["reset"] for x in w1["touches"]))
            w0 = inspect(p, {"kind": "wire", "wire": 0})
            self.assertEqual(w0["register"], "input")
            self.assertEqual(w0["role"], "register")
            self.assertEqual(w0["lifetime_intervals"][0]["start"], 0)
            self.assertEqual(w0["lifetime_intervals"][0]["end"], 6)
            self.assertTrue(w0["idle_does_not_imply_zero"])

    def test_condition_context_bits_and_peak_idle_flag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.kmb"
            structured_fixture(p)
            win = inspect(p, {"kind": "window", "start": 4, "end": 5})
            self.assertEqual(win["operations"][0]["condition"], 0)
            self.assertEqual(win["operations"][0]["condition_depth"], 1)
            self.assertEqual(win["condition_context"]["depth_before"], 1)
            self.assertEqual(win["condition_context"]["active_condition_bits_before"], [0])
            peak = inspect(p, {"kind": "peak"})
            self.assertTrue(peak["idle_does_not_imply_zero"])
            self.assertGreaterEqual(peak["all_runs_metadata"]["covered"], 1)

    def test_rejects_bool_and_oversized_or_invalid_windows(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.kmb"
            structured_fixture(p)
            for query in ({"kind": "wire", "wire": True},
                          {"kind": "window", "start": False, "end": 2},
                          {"kind": "window", "start": 0, "end": 999},
                          {"kind": "peak", "index": True}):
                with self.subTest(query=query), self.assertRaises(StructureError):
                    inspect(p, query)


if __name__ == "__main__":
    unittest.main()
