"""Small append-only content-addressed store for KMB mouse runs.

The store authenticates raw KMB bytes and binds all evaluations and events to
one canonical run context.  It intentionally makes no claim that a receipt is
truthful: evaluator receipts are opaque JSON records, including failed or
invalid outcomes, and are never produced by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORMAT = "qhdl-circuit-mouse-store-v1"


def _canonical(value: Any) -> bytes:
    """Encode JSON data deterministically, rejecting NaN and infinity."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain only finite JSON data") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    _require_regular_nonsymlink(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON record: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON record must be an object: {path.name}")
    return value


def _require_regular_nonsymlink(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f"missing store file: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"expected a regular, non-symlink file: {path}")


def _reject_symlink_components(path: Path) -> None:
    """Reject a symlink at the caller-selected path itself.

    Ancestor symlinks are resolved by the host OS (macOS commonly aliases
    ``/var``); all store-controlled subdirectories and files are separately
    checked with lstat before access.
    """
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise ValueError(f"symlink path is not allowed: {path}")


class StateStore:
    """Append-only content-addressed storage for candidate states and evidence."""

    def __init__(self, root: str | os.PathLike[str], context: dict[str, Any]):
        if not isinstance(context, dict):
            raise TypeError("context must be a dictionary")
        context_bytes = _canonical(context)
        self.context = json.loads(context_bytes.decode("utf-8"))
        self.context_sha256 = _sha256(context_bytes)
        self.root = Path(root).absolute()
        _reject_symlink_components(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_directory(self.root)
        self.objects = self.root / "objects"
        self.evaluations = self.root / "evaluations"
        self.events = self.root / "events"
        for directory in (self.objects, self.evaluations, self.events):
            directory.mkdir(exist_ok=True)
            self._ensure_directory(directory)
        self._bind_context()

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ValueError(f"missing store directory: {path}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError(f"expected a real directory: {path}")

    def _bind_context(self) -> None:
        path = self.root / "context.json"
        record = {
            "format": _FORMAT,
            "context": self.context,
            "context_sha256": self.context_sha256,
        }
        expected = _canonical(record)
        try:
            with path.open("xb") as stream:
                stream.write(expected)
        except FileExistsError:
            existing = _read_json(path)
            if existing != record or _canonical(existing) != expected:
                raise ValueError("store context file is tampered or belongs to another context")

    @staticmethod
    def _validate_sha(state_sha: str) -> str:
        if not isinstance(state_sha, str) or not _SHA256_RE.fullmatch(state_sha):
            raise ValueError("state SHA-256 must be 64 lowercase hexadecimal characters")
        return state_sha

    def add_state(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        """Store raw file bytes under their SHA-256; existing objects are verified."""
        source = Path(path).absolute()
        _reject_symlink_components(source)
        _require_regular_nonsymlink(source)
        data = source.read_bytes()
        digest = _sha256(data)
        target = self.objects / f"{digest}.kmb"
        try:
            with target.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            _require_regular_nonsymlink(target)
            existing = target.read_bytes()
            if _sha256(existing) != digest or existing != data:
                raise ValueError("content-addressed object is tampered")
        return {"sha256": digest, "path": str(target), "nbytes": len(data)}

    def get_state(self, state_sha: str) -> bytes:
        """Return authenticated object bytes, rejecting missing or modified objects."""
        digest = self._validate_sha(state_sha)
        path = self.objects / f"{digest}.kmb"
        _require_regular_nonsymlink(path)
        data = path.read_bytes()
        if _sha256(data) != digest:
            raise ValueError("content-addressed object failed SHA-256 verification")
        return data

    @staticmethod
    def _level(level: str) -> str:
        if not isinstance(level, str) or not level or "\x00" in level:
            raise ValueError("level must be a non-empty string")
        return level

    def _evaluation_path(self, state_sha: str, level: str) -> Path:
        digest = self._validate_sha(state_sha)
        encoded_level = _sha256(level.encode("utf-8"))
        return self.evaluations / f"{digest}.{self.context_sha256}.{encoded_level}.json"

    def record_evaluation(self, state_sha: str, level: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Persist one opaque evaluator output; identical replays are idempotent."""
        digest = self._validate_sha(state_sha)
        level = self._level(level)
        # Require the state to exist and authenticate it before recording evidence.
        self.get_state(digest)
        if not isinstance(receipt, dict):
            raise TypeError("receipt must be a JSON object")
        receipt = json.loads(_canonical(receipt).decode("utf-8"))
        envelope = {
            "format": "qhdl-circuit-mouse-evaluation-v1",
            "state_sha256": digest,
            "context_sha256": self.context_sha256,
            "level": level,
            "receipt": receipt,
        }
        expected = _canonical(envelope)
        path = self._evaluation_path(digest, level)
        try:
            with path.open("xb") as stream:
                stream.write(expected)
        except FileExistsError:
            existing = _read_json(path)
            if existing != envelope or _canonical(existing) != expected:
                raise ValueError("evaluation receipt conflict or tampering")
            return existing
        return envelope

    def get_evaluation(self, state_sha: str, level: str) -> dict[str, Any] | None:
        level = self._level(level)
        # Validate a present object before exposing its cached evaluator output.
        self.get_state(state_sha)
        path = self._evaluation_path(state_sha, level)
        if not path.exists():
            return None
        existing = _read_json(path)
        if (existing.get("format") != "qhdl-circuit-mouse-evaluation-v1"
                or existing.get("state_sha256") != state_sha
                or existing.get("context_sha256") != self.context_sha256
                or existing.get("level") != level
                or not isinstance(existing.get("receipt"), dict)):
            raise ValueError("evaluation record failed identity/context validation")
        return existing

    def append_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a new context-bound event with a monotonically increasing sequence."""
        if not isinstance(kind, str) or not kind or "\x00" in kind:
            raise ValueError("kind must be a non-empty string")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a JSON object")
        payload = json.loads(_canonical(payload).decode("utf-8"))
        # Derive the next sequence from filenames, then create exclusively. A
        # collision increments and retries, so an event is never overwritten.
        sequence = 0
        while True:
            path = self.events / f"{sequence:020d}.json"
            event = {
                "format": "qhdl-circuit-mouse-event-v1",
                "sequence": sequence,
                "context_sha256": self.context_sha256,
                "kind": kind,
                "payload": payload,
            }
            encoded = _canonical(event)
            try:
                with path.open("xb") as stream:
                    stream.write(encoded)
                return event
            except FileExistsError:
                sequence += 1

    def read_events(self) -> list[dict[str, Any]]:
        """Read and validate the contiguous event log for this context."""
        paths = sorted(self.events.glob("*.json"))
        events: list[dict[str, Any]] = []
        for expected_sequence, path in enumerate(paths):
            if path.name != f"{expected_sequence:020d}.json":
                raise ValueError("event sequence has a gap or unexpected filename")
            event = _read_json(path)
            if (event.get("format") != "qhdl-circuit-mouse-event-v1"
                    or event.get("sequence") != expected_sequence
                    or event.get("context_sha256") != self.context_sha256
                    or not isinstance(event.get("kind"), str)
                    or not isinstance(event.get("payload"), dict)):
                raise ValueError(f"event identity/context validation failed: {path.name}")
            events.append(event)
        return events
