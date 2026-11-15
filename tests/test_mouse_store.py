"""Integrity and append-only behavior tests for the circuit mouse store."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ssr.core.store import StateStore


CONTEXT = {
    "task_contract": "mouse-kmb-v1",
    "evaluator_code_sha256": "e" * 64,
    "version": "1",
    "seed": 7,
    "domain": "development",
}


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "candidate.kmb"
        self.source.write_bytes(b"real-ish KMB bytes\x00\x01")
        self.state_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_duplicate_objects_are_raw_content_addressed_and_reopenable(self):
        root = self.base / "archive"
        store = StateStore(root, CONTEXT)
        first = store.add_state(self.source)
        copy = self.base / "other-name.kmb"
        copy.write_bytes(self.source.read_bytes())
        second = store.add_state(copy)
        self.assertEqual(first, second)
        self.assertEqual(first["sha256"], self.state_sha)
        self.assertEqual(first["nbytes"], len(self.source.read_bytes()))
        self.assertEqual(store.get_state(self.state_sha), self.source.read_bytes())
        self.assertEqual(StateStore(root, CONTEXT).get_state(self.state_sha), self.source.read_bytes())

    def test_context_cache_isolation_and_root_context_binding(self):
        a = StateStore(self.base / "a", CONTEXT)
        a.add_state(self.source)
        receipt = {"status": "pass", "cost": 10}
        a.record_evaluation(self.state_sha, "full", receipt)
        self.assertIsNotNone(a.get_evaluation(self.state_sha, "full"))

        other_context = dict(CONTEXT, seed=8)
        b = StateStore(self.base / "b", other_context)
        b.add_state(self.source)
        self.assertIsNone(b.get_evaluation(self.state_sha, "full"))
        with self.assertRaises(ValueError):
            StateStore(self.base / "a", other_context)

    def test_invalid_receipt_is_cached_as_evaluator_output(self):
        store = StateStore(self.base / "archive", CONTEXT)
        store.add_state(self.source)
        invalid = {"status": "fail", "reason": "counterexample", "cost": None}
        stored = store.record_evaluation(self.state_sha, "quick", invalid)
        self.assertEqual(store.get_evaluation(self.state_sha, "quick"), stored)
        self.assertEqual(stored["receipt"], invalid)

    def test_receipt_conflict_refused_but_identical_replay_is_idempotent(self):
        store = StateStore(self.base / "archive", CONTEXT)
        store.add_state(self.source)
        first = store.record_evaluation(self.state_sha, "full", {"status": "pass"})
        self.assertEqual(store.record_evaluation(self.state_sha, "full", {"status": "pass"}), first)
        with self.assertRaises(ValueError):
            store.record_evaluation(self.state_sha, "full", {"status": "fail"})

    def test_object_tampering_is_detected_before_state_or_evaluation_use(self):
        store = StateStore(self.base / "archive", CONTEXT)
        store.add_state(self.source)
        store.record_evaluation(self.state_sha, "full", {"status": "pass"})
        object_path = Path(store.add_state(self.source)["path"])
        object_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            store.get_state(self.state_sha)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            store.get_evaluation(self.state_sha, "full")

    def test_context_file_tampering_detected_on_reopen(self):
        root = self.base / "archive"
        StateStore(root, CONTEXT)
        (root / "context.json").write_text(json.dumps({"context_sha256": "wrong"}))
        with self.assertRaisesRegex(ValueError, "context file"):
            StateStore(root, CONTEXT)

    def test_events_are_append_only_context_bound_and_reopenable(self):
        root = self.base / "archive"
        store = StateStore(root, CONTEXT)
        state = store.add_state(self.source)
        event0 = store.append_event("candidate_added", {"state_sha256": state["sha256"]})
        event1 = store.append_event("evaluation_requested", {"level": "full"})
        self.assertEqual((event0["sequence"], event1["sequence"]), (0, 1))
        reopened = StateStore(root, CONTEXT)
        events = reopened.read_events()
        self.assertEqual(events, [event0, event1])
        self.assertEqual(events[0]["payload"]["state_sha256"], self.state_sha)
        self.assertEqual(events[0]["context_sha256"], reopened.context_sha256)

    def test_event_context_or_sequence_tampering_detected(self):
        store = StateStore(self.base / "archive", CONTEXT)
        store.append_event("started", {})
        path = store.events / "00000000000000000000.json"
        record = json.loads(path.read_text())
        record["context_sha256"] = "0" * 64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "event identity/context"):
            store.read_events()

    def test_symlinked_state_source_and_store_object_are_rejected(self):
        store = StateStore(self.base / "archive", CONTEXT)
        link = self.base / "candidate-link.kmb"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "symlink"):
            store.add_state(link)
        store.add_state(self.source)
        object_path = store.objects / f"{self.state_sha}.kmb"
        object_path.unlink()
        object_path.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "symlink"):
            store.get_state(self.state_sha)


if __name__ == "__main__":
    unittest.main()
