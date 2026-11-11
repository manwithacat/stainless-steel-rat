"""Small authored circuits for the mouse workbench's read-only value API."""
from __future__ import annotations

from pathlib import Path
import struct

import numpy as np
import pytest
from support import need_kickmix
km = need_kickmix()

from ssr.workbench.values import investigate


class FixtureEvaluator:
    def __init__(self, rows=(1, 2, 3, 4)):
        self._rows = np.asarray(rows, dtype=np.int64)
        self.spec = {"fixture": "two-input"}

    def export(self, path):
        target = Path(path).with_suffix(".kmx")
        if not target.exists() and Path(path) != target:
            km.Circuit.from_file(str(path), format="kmb").to_file(str(target), format="kmx")
        return target

    def rows(self, level):
        assert level in ("sampled", "full")
        return self._rows.copy()


def circuit(path, changed=False, measurement=False):
    # q0 and q1 encode x. q2 stores q0 AND q1; the neutral X on q3 forms
    # a real gap while leaving the target and its two-input relation intact.
    if measurement:
        ops = ["HMR q3 b0", "X q4 if b0", "X q5"]
    else:
        ops = ["CCX q0 q1 q2", "CX q0 q2" if changed else "X q3", "X q2"]
    lines = ["APPEND_TO_REGISTER q0 r0", "APPEND_TO_REGISTER q1 r0", "REGISTER r0 \"x\""]
    lines += ops
    kmx = path.with_suffix(".kmx")
    kmx.write_text("\n".join(lines) + "\n")
    km.Circuit.from_file(str(kmx), format="kmx").to_file(str(path), format="kmb")
    # Include declared but unreferenced qubits, as can occur in source KMBs.
    with path.open("r+b") as f:
        f.seek(20)
        f.write(struct.pack("<I", 6 if measurement else 5))
    return path


def test_fit_and_value_snapshots_are_scoped_and_emit_candidate(tmp_path):
    path = circuit(tmp_path / "fit.kmb")
    evaluator = FixtureEvaluator()
    fit = investigate(evaluator, path, {
        "type": "fit_recompute", "wire": 2, "after": 0, "before": 2,
        "basis": [0, 1], "degree": 2, "validation": "full",
    })
    assert fit["status"] == "validated"
    assert fit["terms"] == [["q0", "q1"]]
    assert fit["candidate_action"] == {
        "type": "park_recompute", "wire": 2, "after": 0, "before": 2, "terms": [["q0", "q1"]],
    }
    assert fit["all_measurement_histories"] is False
    assert "not a whole-circuit rewrite check" in fit["relation_scope"]

    values = investigate(evaluator, path, {"type": "value", "at": 1, "wires": [0, 1, 2], "level": "full"})
    assert values["rows_checked"] == 4
    assert values["scope"] == "selected wire values only; no whole-circuit validity claim"
    assert [m["model"] for m in values["models"]] == ["zero", 7, 101]
    q2 = values["models"][0]["wires"][2]
    assert q2["count_one"] == 1
    assert q2["count_zero"] == 3
    assert len(q2["signature_sha256"]) == 64
    assert len(values["models"][0]["state_sha256"]) == 64
    assert len(values["input_state_sha256"]) == 64
    assert values["models"][0]["wires"][0]["constant"] is None
    idle = investigate(evaluator, path, {"type": "value", "at": 0, "wires": [4], "level": "full"})
    assert idle["models"][0]["wires"][0]["constant"] == 0


def test_changed_gap_and_wrong_hypothesis_return_counterexample(tmp_path):
    path = circuit(tmp_path / "changed.kmb", changed=True)
    evaluator = FixtureEvaluator()
    with pytest.raises(ValueError, match="touched inside the open gap"):
        investigate(evaluator, path, {
            "type": "fit_recompute", "wire": 2, "after": 0, "before": 2,
            "basis": [0, 1], "degree": 2, "validation": "full",
        })

    clean = circuit(tmp_path / "wrong.kmb")
    check = investigate(evaluator, clean, {
        "type": "check_relation", "wire": 2, "after": 0, "before": 2,
        "basis": [0, 1], "terms": [["q0"]], "validation": "full",
    })
    assert check["status"] == "counterexample"
    assert check["counterexample"]["model"] in ("zero", 7, 101)
    assert check["counterexample"]["target"] != check["counterexample"]["proposed"]


def test_seeded_measurement_model_can_refute_zero_branch_relation(tmp_path):
    path = circuit(tmp_path / "measurement.kmb", measurement=True)
    check = investigate(FixtureEvaluator(), path, {
        "type": "check_relation", "wire": 2, "after": 2, "before": 3,
        "basis": [4], "terms": [["q4"]], "validation": "full",
    })
    assert check["status"] == "counterexample"
    assert check["counterexample"]["model"] in (7, 101)


@pytest.mark.parametrize("query", [
    {"type": "value", "at": True, "wires": [0], "level": "sampled"},
    {"type": "value", "at": 0, "wires": [0] * 17, "level": "sampled"},
    {"type": "fit_recompute", "wire": 2, "after": 0, "before": 2, "basis": [0, 1], "degree": 3, "validation": "full"},
    {"type": "fit_recompute", "wire": 2, "after": 0, "before": 2, "basis": list(range(13)), "degree": 2, "validation": "full"},
])
def test_rejects_bad_domains_bounds_and_growth(tmp_path, query):
    path = circuit(tmp_path / "reject.kmb")
    with pytest.raises(ValueError):
        investigate(FixtureEvaluator(), path, query)


def test_rejects_nopsend_boundary_and_target_in_basis(tmp_path):
    path = circuit(tmp_path / "bounds.kmb")
    evaluator = FixtureEvaluator()
    base = {"type": "fit_recompute", "wire": 2, "after": 0, "before": 3,
            "basis": [0, 1], "degree": 2, "validation": "full"}
    with pytest.raises(ValueError, match="open gap"):
        investigate(evaluator, path, base)
    bad = dict(base, before=2, basis=[0, 2])
    with pytest.raises(ValueError, match="exclude target"):
        investigate(evaluator, path, bad)


def test_disjoint_conditional_gate_inside_gap_is_allowed(tmp_path):
    path = tmp_path / "conditional.kmb"
    source = path.with_suffix(".kmx")
    source.write_text("APPEND_TO_REGISTER q0 r0\nAPPEND_TO_REGISTER q1 r0\nREGISTER r0 \"x\"\nX q4\nCX q0 q2 if b0\nX q3\n")
    km.Circuit.from_file(str(source), format="kmx").to_file(str(path), format="kmb")
    result = investigate(FixtureEvaluator(), path, {
        "type": "check_relation", "wire": 4, "after": 0, "before": 3,
        "basis": [], "terms": [["1"]], "validation": "full",
    })
    assert result["status"] == "validated"


def test_complete_condition_block_inside_gap_is_allowed(tmp_path):
    path = tmp_path / "condition_block.kmb"
    source = path.with_suffix(".kmx")
    source.write_text("APPEND_TO_REGISTER q0 r0\nAPPEND_TO_REGISTER q1 r0\nREGISTER r0 \"x\"\nX q4\nPUSH_CONDITION if b0\nX q2\nPOP_CONDITION\nX q3\n")
    km.Circuit.from_file(str(source), format="kmx").to_file(str(path), format="kmb")
    result = investigate(FixtureEvaluator(), path, {
        "type": "check_relation", "wire": 4, "after": 0, "before": 4,
        "basis": [], "terms": [["1"]], "validation": "full",
    })
    assert result["status"] == "validated"


def test_boundary_inside_condition_block_is_rejected(tmp_path):
    path = tmp_path / "boundary_block.kmb"
    source = path.with_suffix(".kmx")
    source.write_text("APPEND_TO_REGISTER q0 r0\nAPPEND_TO_REGISTER q1 r0\nREGISTER r0 \"x\"\nX q4\nPUSH_CONDITION if b0\nX q2\nPOP_CONDITION\n")
    km.Circuit.from_file(str(source), format="kmx").to_file(str(path), format="kmb")
    with pytest.raises(ValueError, match="inside a condition block"):
        investigate(FixtureEvaluator(), path, {
            "type": "check_relation", "wire": 4, "after": 0, "before": 3,
            "basis": [], "terms": [["1"]], "validation": "full",
        })

