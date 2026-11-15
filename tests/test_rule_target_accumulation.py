"""Positive, interface-breaking and stale-source controls for the census."""

from __future__ import annotations

from pathlib import Path

import pytest

from support import need_kickmix

km = need_kickmix()   # skip the module before importing rules that need kickmix

from ssr.rules import target_accumulation as A  # noqa: E402


def write(path: Path, lines: list[str]) -> Path:
    km.Circuit("\n".join(lines) + "\n").to_file(str(path), format="kmb")
    return path


def test_target_only_positive_and_stale_handle(tmp_path: Path) -> None:
    lines = ["CCX q0 q1 q3", "CX q0 q2", "CCX q1 q2 q3",
             "X q2", "CCX q0 q2 q3", "CCX q1 q2 q3",
             "CCX q0 q1 q3"]
    source = write(tmp_path / "source.kmb", lines)
    result = A.census(source)
    assert result["site_count"] == 1
    site = result["sites"][0]
    assert site["ops"] == [0, 7] and site["target"] == 3
    assert A.resolve(source, site["handle"]) == site
    changed = write(tmp_path / "changed.kmb", ["X q0"] + lines)
    with pytest.raises(ValueError, match="stale"):
        A.resolve(changed, site["handle"])


@pytest.mark.parametrize("intruder", ["CX q3 q2", "Z q3", "HMR q3 b0"])
def test_target_read_phase_or_measurement_rejected(tmp_path: Path,
                                                    intruder: str) -> None:
    lines = ["CCX q0 q1 q3"] * 2 + [intruder] + ["CCX q0 q1 q3"] * 3
    result = A.census(write(tmp_path / "bad.kmb", lines))
    assert result["site_count"] == 0
