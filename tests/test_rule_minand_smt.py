"""Solver calibration and aliased-target rejection for reached-state plans."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from ssr.rules.minand_smt import load_table, solve


class MinAndSmtTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("z3"), "optional z3-solver absent")
    def test_two_product_calibration(self) -> None:
        rows = [(x, ((x >> 0 & 1) & (x >> 1 & 1)) ^
                 ((x >> 2 & 1) & (x >> 3 & 1))) for x in range(16)]
        names = ["a", "b", "c", "d"]
        self.assertEqual(solve(names, rows, 1, 10)["status"], "unsat")
        answer = solve(names, rows, 2, 10)
        self.assertEqual(answer["status"], "sat")
        self.assertTrue(answer["independent_row_replay"])
        cegis = solve(names, rows, 2, 10, cegis=True)
        self.assertEqual(cegis["status"], "sat")
        self.assertTrue(cegis["independent_row_replay"])

    def test_colliding_target_projection_rejected(self) -> None:
        table = {"schema": "vqcc-window-reached-table/1",
                 "input_wires_lsb_first": ["control", "target"],
                 "output_wires_lsb_first": ["target"],
                 "xor_defined_mask": 1,
                 "rows": [{"input": 0, "output_xor_input": 0},
                          {"input": 2, "output_xor_input": 1}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.json"
            path.write_text(json.dumps(table))
            with self.assertRaisesRegex(ValueError, "conflicts"):
                load_table(path, "target")


if __name__ == "__main__":
    unittest.main()
