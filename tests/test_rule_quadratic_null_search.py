"""Reached-state rank-collapse positive and stale-source controls."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from support import need_kickmix

need_kickmix()   # skip the module before importing rules that need kickmix

from ssr.rules import quadratic_null_search as N  # noqa: E402
from ssr.rules import reader_cut_quadratic as R  # noqa: E402
from ssr.rules import target_accumulation as A
from ssr.crosscut import rule as C
from ssr.qhdl import bitsim as B

km = need_kickmix()


def _source(path: Path, duplicate: bool = True) -> Path:
    inputs = [0, 1, 2, 5, 6, 7, 8, 9, 10]
    lines = [f"APPEND_TO_REGISTER q{q} r0" for q in inputs]
    lines += (["CX q0 q4"] if duplicate else ["CX q1 q4"])
    lines += ["CCX q0 q1 q11", "CCX q4 q2 q11",
              "CCX q5 q6 q11", "CCX q7 q8 q11", "CCX q9 q10 q11"]
    lines += ["CX q11 q12"]
    km.Circuit("\n".join(lines) + "\n").to_file(str(path), format="kmb")
    return path


def test_live_product_relation_lowers_exact_polynomial_rank(tmp_path: Path) -> None:
    source = _source(tmp_path / "source.kmb")
    site = A.census(source)["sites"][0]
    report = N.search(source, site["handle"], rows=8192, outcomes=("zero",))
    assert report["original_rank"] == 10
    assert report["hit_count"] > 0
    assert report["hits"][0]["new_symbolic_rank"] <= 8
    assert all(hit["panel_relation_replayed"] for hit in report["hits"])
    reader = R.analyze(source, site["handle"], sample_rows=8192,
                       outcomes=("zero",), trials=16)
    assert reader["status"] == "quadratic_fit"
    assert reader["reader_op"] == site["ops"][1]
    assert reader["factor_count"] <= 4
    changed = _source(tmp_path / "changed.kmb", duplicate=False)
    with pytest.raises(ValueError, match="stale"):
        N.search(changed, site["handle"], rows=8192, outcomes=("zero",))


def test_reader_null_refinement_on_reachable_alias() -> None:
    states = np.arange(512, dtype=np.uint64)
    nq, target = 12, 11
    packed = np.zeros((nq, 8), dtype=np.uint64)
    input_wires = [0, 1, 2, 5, 6, 7, 8, 9, 10]
    for bit, wire in enumerate(input_wires):
        packed[wire] = B.pack_bits(((states >> np.uint64(bit)) & 1).astype(bool))
    packed[4] = packed[0].copy()
    valid = B.pack_bits(np.ones(len(states), bool))
    adjacency = [0] * nq
    for a, b in [(0, 1), (4, 2), (5, 6), (7, 8), (9, 10)]:
        adjacency[a] ^= 1 << b
        adjacency[b] ^= 1 << a
    poly = {"linear": 0, "constant": False, "adj": adjacency}
    assert len(C.factor(poly)[0]) == 5
    wanted = C.evaluate(poly, packed, valid)
    result = R._refine(poly, packed, valid, wanted, target, support=11)
    assert result["status"] == "rank_reduced_on_panel"
    assert result["factor_count"] <= 4
    assert result["independent_panel_replay"]
