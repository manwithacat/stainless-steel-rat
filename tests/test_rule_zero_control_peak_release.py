#!/usr/bin/env python3
"""Source-independent peak constructor acceptance and refusal controls."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np

from ssr.rules.zero_control_peak_release import K, constructor


def fixture(directory: Path, phase_touch: bool):
    path = directory / "tiny.kmb"
    codes = [0x21, 0x10, 0x21] if phase_touch else [0x21, 0x21]
    K.write_kmb(path, np.array(codes, np.uint8),
                {"qq0": [1, 1], "qq1": [0, 0],
                 "q0": [1] if phase_touch else []},
                registers=[("s", [(True, 0)])], num_qubits=3, num_bits=0)
    peak = directory / "peak.json"
    peak.write_text(json.dumps({
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "run_rows": [{"run": "R0", "start": 0, "end": len(codes) - 1,
                      "ops": len(codes), "path": "test"}],
        "idle_all": [{"wire": "q2", "role": "scratch", "runs": "R0..R0"}],
    }))
    return path, peak


def test_release_and_phase_touch_refusal():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        good = base / "good"
        good.mkdir()
        path, peak = fixture(good, False)
        script, report = constructor(path, peak)
        assert script == "insert 0 => R q1\ndelete 0\ndelete 1\n"
        assert len(report["admitted"]) == 1
        bad = base / "bad"
        bad.mkdir()
        path, peak = fixture(bad, True)
        script, report = constructor(path, peak)
        assert script == ""
        assert len(report["admitted"]) == 0


if __name__ == "__main__":
    test_release_and_phase_touch_refusal()
    print("zero-control peak release controls PASS")
