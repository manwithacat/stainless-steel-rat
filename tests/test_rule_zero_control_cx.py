#!/usr/bin/env python3
"""Positive and negative controls for the reset/last-write sieve."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from ssr.rules.zero_control_cx import K, scan


def test_reset_zero_and_guarded_write():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "control.kmb"
        K.write_kmb(
            path,
            np.array([0x21, 0x11, 0x21, 0x12, 0x31,
                      0x22, 0x50, 0x21, 0x91, 0x21], np.uint8),
            {
                "qqq0": [1], "qqq1": [0], "qqq2": [2],
                "qq0": [1, 1, 1, 1, 1],
                "qq1": [0, 0, 2, 0, 0],
                "q0": [1, 1, 1, 1],
                "b0": [0], "bc": [0],
            },
            registers=[("s", [(True, 0)])], num_qubits=3, num_bits=1,
        )
        report = scan(path, 10, (0, 10), 100, cuts=(0, 3, 4, 8, 9))
        assert report["counts"] == {"CX": 2, "CCX": 1}
        assert [e["op"] for e in report["events"]] == [0, 4, 7]
        assert report["events"][0]["origin"] == "initial"
        assert report["events"][-1]["origin"] == "HMR@6"
        assert 1 in report["zero_at_cuts"]["0"]
        assert 1 not in report["zero_at_cuts"]["3"]
        assert 1 in report["zero_at_cuts"]["4"]
        assert 1 in report["zero_at_cuts"]["8"]
        assert 1 not in report["zero_at_cuts"]["9"]


def test_charged_zero_operands_and_mutation():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "charged.kmb"
        K.write_kmb(
            path,
            np.array([0x12, 0x30, 0x32, 0x11, 0x11, 0x30, 0x32], np.uint8),
            {"qqq0": [1, 1, 1, 1], "qqq1": [0, 0, 0, 0],
             "qqq2": [2, 2, 2, 2], "q0": [1, 1, 2]},
            registers=[("s", [(True, 0)])], num_qubits=3, num_bits=0,
        )
        report = scan(path, 7, (0, 7), 100)
        assert report["counts"] == {"CCZ": 1, "CSWAP": 1}
        assert [e["op"] for e in report["events"]] == [1, 2]
        assert [e["origin"] for e in report["events"]] == ["R@0", "R@0"]


if __name__ == "__main__":
    test_reset_zero_and_guarded_write()
    test_charged_zero_operands_and_mutation()
    print("zero-control sieve controls PASS")
