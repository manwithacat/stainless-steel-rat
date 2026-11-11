"""Tests for report-only authentication of recorded official receipts."""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ssr.mouse import official
from ssr.mouse.official import recorded_receipt

# Authored stand-ins: a synthetic recorded report and a fake verifier file. The
# original test read a real local official report; these exercise the same checks.
FAKE_VERIFIER = b"# stand-in verifier bytes for report-hash tests\n"
FAKE_CIRCUIT_SHA = "ab" * 32


def synthetic_report(verifier_sha):
    return {
        "settings": {"salt": "", "seed": "circuit hash derived"},
        "verifier_sha256": {"invsqrt/verify_submission_invsqrt.py": verifier_sha},
        "results": {"invsqrt": {"summary": {
            "status": "PASS", "circuit_sha256": FAKE_CIRCUIT_SHA,
            "verified_shots": 3_133_452 * 64, "score": 12345.5}}},
    }
CONTRACT = {
    "task": "invsqrt",
    "width": 22,
    "max_x": 3_133_452,
    "beta": "1",
    "precision_bits": 24,
    "official_shots_per_x": 64,
    "system_qubits": 6540,
}


class RecordedOfficialReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "report.json"
        verifier = Path(self.temp.name) / "verify_submission_invsqrt.py"
        verifier.write_bytes(FAKE_VERIFIER)
        patcher = mock.patch.object(official, "verifier_path", lambda: verifier)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.verifier_sha = official._file_sha256(verifier)
        self.report = synthetic_report(self.verifier_sha)
        # The optional native-module check is covered separately with a
        # controlled current-module fingerprint in the test below.
        self.report.pop("kickmix_sha256", None)
        self._write()
        self.state_sha = self.report["results"]["invsqrt"]["summary"]["circuit_sha256"]

    def _write(self):
        self.path.write_text(json.dumps(self.report), encoding="utf-8")

    def test_accepts_matching_full_pass_and_marks_receipt_as_recorded(self):
        receipt = recorded_receipt(self.path, self.state_sha, CONTRACT)
        self.assertTrue(receipt["valid"])
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["level"], "official-recorded")
        self.assertEqual(receipt["provenance"], "recorded-not-rerun")
        self.assertEqual(receipt["loss"], self.report["results"]["invsqrt"]["summary"]["score"])
        self.assertEqual(receipt["summary"], self.report["results"]["invsqrt"]["summary"])
        self.assertEqual(len(receipt["report_sha256"]), 64)

    def test_rejects_bad_state_hash_or_circuit_mismatch(self):
        with self.assertRaisesRegex(ValueError, "state_sha"):
            recorded_receipt(self.path, "not-a-sha", CONTRACT)
        with self.assertRaisesRegex(ValueError, "circuit hash"):
            recorded_receipt(self.path, "0" * 64, CONTRACT)

    def test_rejects_report_for_other_task_contract(self):
        other = dict(CONTRACT, max_x=3_133_451)
        with self.assertRaisesRegex(ValueError, "exact default invsqrt contract"):
            recorded_receipt(self.path, self.state_sha, other)
        typed_other = dict(CONTRACT, precision_bits=24.0)
        with self.assertRaisesRegex(ValueError, "exact default invsqrt contract"):
            recorded_receipt(self.path, self.state_sha, typed_other)

    def test_rejects_partial_shot_count_and_explicit_nondefault_override(self):
        summary = self.report["results"]["invsqrt"]["summary"]
        summary["verified_shots"] -= 64
        self._write()
        with self.assertRaisesRegex(ValueError, "full-domain"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

        summary["verified_shots"] += 64
        self.report["settings"]["invsqrt_shots_per_x"] = 32
        self._write()
        with self.assertRaisesRegex(ValueError, "must be absent or 64"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

    def test_rejects_wrong_salt_or_non_hash_derived_seed(self):
        self.report["settings"]["salt"] = "changed"
        self._write()
        with self.assertRaisesRegex(ValueError, "empty salt"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

        self.report["settings"]["salt"] = ""
        self.report["settings"]["seed"] = "fixed"
        self._write()
        with self.assertRaisesRegex(ValueError, "hash-derived seed"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

    def test_rejects_changed_verifier_hash_and_fail_status(self):
        key = "invsqrt/verify_submission_invsqrt.py"
        self.report["verifier_sha256"][key] = "0" * 64
        self._write()
        with self.assertRaisesRegex(ValueError, "verifier hash"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

        self.report = synthetic_report(self.verifier_sha)
        self.report.pop("kickmix_sha256", None)
        self.report["results"]["invsqrt"]["summary"]["status"] = "FAIL"
        self._write()
        with self.assertRaisesRegex(ValueError, "not PASS"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

    def test_rejects_nonpositive_score(self):
        self.report["results"]["invsqrt"]["summary"]["score"] = 0
        self._write()
        with self.assertRaisesRegex(ValueError, "finite positive"):
            recorded_receipt(self.path, self.state_sha, CONTRACT)

    def test_rejects_optional_kickmix_hash_mismatch(self):
        native = Path(self.temp.name) / "native.so"
        native.write_bytes(b"current native build")
        self.report["kickmix_sha256"] = "0" * 64
        self._write()
        module = types.SimpleNamespace(__file__=str(native))
        with mock.patch.dict(sys.modules, {"kickmix": module}):
            with self.assertRaisesRegex(ValueError, "kickmix hash"):
                recorded_receipt(self.path, self.state_sha, CONTRACT)


if __name__ == "__main__":
    unittest.main()
