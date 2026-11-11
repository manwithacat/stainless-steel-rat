"""Parity tests for grouped reference reuse against the frozen stream probe."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from support import need_engine

ENGINE = need_engine()
import kickmix as km  # noqa: E402

from ssr.qhdl import kmb as K  # noqa: E402
from ssr.mouse.fixtures import write_fixture  # noqa: E402
from ssr.stream import stream as _old  # noqa: E402  (v1 streaming probe)
from ssr.rat import stream as _new  # noqa: E402  (grouped-reference probe)


def _identity_kmb(path: Path, width: int, max_x: int) -> dict:
    streams = {name: np.zeros(0, np.uint32) for name in
               ("qqq0", "qqq1", "qqq2", "qq0", "qq1", "q0", "b0", "bc")}
    K.write_kmb(
        str(path), np.zeros(0, np.uint8), streams,
        registers=(("x", [(True, q) for q in range(width)]),),
        num_qubits=width, num_bits=0,
    )
    return {
        "source": str(path),
        "contract": {"task": "invsqrt", "width": width, "max_x": max_x, "beta": "1",
                     "precision_bits": 24, "official_shots_per_x": 64,
                     "system_qubits": max(12, width)},
    }


def _mutate_fixture(source: Path, dest: Path, op: str) -> Path:
    text = source.with_suffix(".kmx").read_text(encoding="utf-8") + op + "\n"
    kmx = dest.with_suffix(".kmx")
    kmx.write_text(text, encoding="utf-8")
    km.Circuit.from_file(str(kmx), format="kmx").to_file(str(dest), format="kmb")
    return dest


def _model_projection(receipt: dict) -> tuple:
    """Compare all seedwise evidence except top-level timing/identity fields."""
    return receipt["models"], receipt["loss_estimate"], receipt["valid_on_native_models"]


def test_grouped_reference_reuse_matches_frozen_native_fixture(tmp_path):
    fixture = write_fixture(tmp_path / "native")
    old = _old.StreamingProbe(ENGINE, fixture["contract"])
    new = _new.StreamingProbe(ENGINE, fixture["contract"])

    legacy = old.evaluate(fixture["source"], threads=1, group_chunks=1)
    grouped = new.evaluate(fixture["source"], threads=4, group_chunks=16)
    assert _model_projection(grouped) == _model_projection(legacy)
    assert grouped["backend_sha256"][str(Path(_new.__file__))]
    assert grouped["reference_calls"] == 1
    assert grouped["reference_rows"] == 16_384

    for name, op in (("dirty", "X q3"), ("phase", "Z q0")):
        bad = _mutate_fixture(Path(fixture["source"]), tmp_path / f"{name}.kmb", op)
        old_receipt = old.evaluate(bad, threads=1, group_chunks=1)
        new_receipt = new.evaluate(bad, threads=2, group_chunks=1)
        assert _model_projection(new_receipt) == _model_projection(old_receipt)
        assert not new_receipt["valid_on_native_models"]
        assert new_receipt["loss_estimate"] is None


def test_multigroup_padding_reference_call_count_and_thread_invariance(tmp_path):
    # 16,385 inputs require two fixed 16,384-row chunks.  The last legal x is
    # repeated through the padded tail, exactly as in the frozen stream.
    fixture = _identity_kmb(tmp_path / "identity.kmb", width=15, max_x=16_385)
    old = _old.StreamingProbe(ENGINE, fixture["contract"])
    new = _new.StreamingProbe(ENGINE, fixture["contract"])

    frozen = old.evaluate(fixture["source"], threads=1, group_chunks=1)
    single_group = new.evaluate(fixture["source"], threads=1, group_chunks=2)
    split_groups = new.evaluate(fixture["source"], threads=4, group_chunks=1)
    assert _model_projection(single_group) == _model_projection(frozen)
    assert _model_projection(split_groups) == _model_projection(frozen)
    assert not single_group["valid_on_native_models"]
    assert single_group["loss_estimate"] is None
    assert all(model["covered_legal_rows"] == 16_385 for model in split_groups["models"])
    assert all(model["executed_rows"] == 32_768 for model in split_groups["models"])
    assert single_group["reference_calls"] == 1
    assert split_groups["reference_calls"] == 2
    assert split_groups["reference_rows"] == 32_768


def test_bounds_and_seed_rejection(tmp_path):
    fixture = write_fixture(tmp_path / "native")
    probe = _new.StreamingProbe(ENGINE, fixture["contract"])
    with pytest.raises(ValueError, match="group_chunks"):
        probe.evaluate(fixture["source"], group_chunks=0)
    with pytest.raises(ValueError, match="invalid seeds"):
        probe.evaluate(fixture["source"], seeds=())

