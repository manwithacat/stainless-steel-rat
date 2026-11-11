"""Validate and wrap an existing full local official invsqrt report.

This module only reads recorded JSON and hashes local files. It does not run a
verifier or treat an unverified receipt as evidence of execution.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from pathlib import Path
from typing import Any


from .verifier import verifier_path

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_SHOTS = 3_133_452 * 64
_DEFAULT_CONTRACT = {
    "task": "invsqrt",
    "width": 22,
    "max_x": 3_133_452,
    "beta": "1",
    "precision_bits": 24,
    "official_shots_per_x": 64,
    "system_qubits": 6540,
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def _check_shot_override(container: dict[str, Any], where: str) -> None:
    """Check any explicit report field that declares invsqrt shots per input."""
    for key in ("invsqrt_shots_per_x", "shots_per_x"):
        if key in container:
            value = container[key]
            if isinstance(value, bool) or not isinstance(value, int) or value != 64:
                raise ValueError(f"{where}.{key} must be absent or 64")


def recorded_receipt(
    report_path: str | Path,
    state_sha: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Return a receipt for a matching, recorded full local official report.

    The frozen report is accepted only for the exact default invsqrt task
    contract. Its circuit digest must match ``state_sha`` and its recorded
    verifier, settings, shot count, and result status must satisfy the full
    local-run requirements. This function does not execute the verifier.
    """
    if not isinstance(state_sha, str) or not _SHA256_RE.fullmatch(state_sha):
        raise ValueError("state_sha must be 64 lowercase hexadecimal characters")
    exact_contract = (
        type(contract) is dict
        and set(contract) == set(_DEFAULT_CONTRACT)
        and all(type(contract[key]) is type(value) for key, value in _DEFAULT_CONTRACT.items())
        and contract == _DEFAULT_CONTRACT
    )
    if not exact_contract:
        raise ValueError("recorded report applies only to the exact default invsqrt contract")

    path = Path(report_path).absolute()
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"cannot read report file: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("report_path must be a regular non-symlink file")
    report_bytes = path.read_bytes()
    try:
        report = json.loads(report_bytes.decode("utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("report is not strict JSON") from exc
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")

    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("report settings are missing")
    if settings.get("salt") != "" or settings.get("seed") != "circuit hash derived":
        raise ValueError("report must use empty salt and circuit-hash-derived seed")
    _check_shot_override(report, "report")
    _check_shot_override(settings, "settings")

    verifier_hashes = report.get("verifier_sha256")
    if not isinstance(verifier_hashes, dict):
        raise ValueError("report verifier hashes are missing")
    recorded_verifier_sha = verifier_hashes.get("invsqrt/verify_submission_invsqrt.py")
    if (not isinstance(recorded_verifier_sha, str)
            or not _SHA256_RE.fullmatch(recorded_verifier_sha)
            or recorded_verifier_sha != _file_sha256(verifier_path())):
        raise ValueError("report invsqrt verifier hash does not match the local official verifier")

    # The optional field was added to newer report variants. Check it against
    # the currently installed native module when the report records it.
    if "kickmix_sha256" in report:
        native_sha = report["kickmix_sha256"]
        if not isinstance(native_sha, str) or not _SHA256_RE.fullmatch(native_sha):
            raise ValueError("report kickmix_sha256 is malformed")
        try:
            import kickmix
        except ImportError as exc:
            raise ValueError("cannot verify report's recorded native kickmix hash") from exc
        module_path = Path(kickmix.__file__)
        if native_sha != _file_sha256(module_path):
            raise ValueError("report native kickmix hash does not match the current module")

    results = report.get("results")
    task_result = results.get("invsqrt") if isinstance(results, dict) else None
    summary = task_result.get("summary") if isinstance(task_result, dict) else None
    if not isinstance(summary, dict):
        raise ValueError("report has no complete invsqrt summary")
    if summary.get("status") != "PASS":
        raise ValueError("recorded invsqrt summary is not PASS")
    if summary.get("circuit_sha256") != state_sha:
        raise ValueError("report circuit hash does not match the requested state bytes")
    if summary.get("verified_shots") != _FULL_SHOTS:
        raise ValueError("report is not a full-domain 64-shots-per-input run")
    loss = _finite_positive(summary.get("score"), "invsqrt score")

    return {
        "valid": True,
        "status": "PASS",
        "level": "official-recorded",
        "provenance": "recorded-not-rerun",
        "loss": loss,
        "summary": summary,
        "report_path": str(path),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "scope": (
            "recorded local official invsqrt verifier result; associated by exact "
            "KMB circuit SHA-256, current verifier hash, empty salt, hash-derived seed, "
            "and full 64-shot-per-input domain; verifier was not rerun"
        ),
    }
