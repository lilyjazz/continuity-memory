from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .extractor import compute_checksum
from .models import ContinuityAnchor


class AnchorNotFoundError(RuntimeError):
    pass


class AnchorCorruptedError(RuntimeError):
    pass


class AnchorStore(Protocol):
    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        raise NotImplementedError

    def put(self, anchor: ContinuityAnchor) -> None:
        raise NotImplementedError

    def get_previous(self, conversation_id: str) -> ContinuityAnchor | None:
        raise NotImplementedError


@dataclass
class FileAnchorStore:
    root: Path
    keep_versions: int = 5

    def _path(self, conversation_id: str) -> Path:
        return self.root / f"{conversation_id}.json"

    def _load_versions(self, conversation_id: str) -> list[ContinuityAnchor]:
        path = self._path(conversation_id)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [ContinuityAnchor.from_dict(item) for item in payload.get("versions", [])]

    def _save_versions(self, conversation_id: str, versions: list[ContinuityAnchor]) -> None:
        path = self._path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"versions": [item.to_dict() for item in versions[-self.keep_versions :]]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        versions = self._load_versions(conversation_id)
        if not versions:
            raise AnchorNotFoundError(conversation_id)
        latest = versions[-1]
        checksum = compute_checksum(latest)
        if latest.meta.checksum != checksum:
            raise AnchorCorruptedError(conversation_id)
        return latest

    def get_previous(self, conversation_id: str) -> ContinuityAnchor | None:
        versions = self._load_versions(conversation_id)
        if len(versions) < 2:
            return None
        prev = versions[-2]
        if prev.meta.checksum != compute_checksum(prev):
            return None
        return prev

    def put(self, anchor: ContinuityAnchor) -> None:
        versions = self._load_versions(anchor.conversation_id)
        versions.append(anchor)
        self._save_versions(anchor.conversation_id, versions)


class RemoteBackend(Protocol):
    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        raise NotImplementedError

    def put(self, anchor: ContinuityAnchor) -> None:
        raise NotImplementedError


@dataclass
class InMemoryRemoteBackend:
    fail_writes: bool = False
    values: dict[str, ContinuityAnchor] = field(default_factory=dict)

    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        if conversation_id not in self.values:
            raise AnchorNotFoundError(conversation_id)
        return self.values[conversation_id]

    def put(self, anchor: ContinuityAnchor) -> None:
        if self.fail_writes:
            raise RuntimeError("remote write failed")
        self.values[anchor.conversation_id] = anchor


@dataclass
class HybridAnchorStore:
    local: FileAnchorStore
    remote: RemoteBackend
    retry_queue_path: Path | None = None
    pending_retry: list[ContinuityAnchor] = field(default_factory=list)
    retry_interval_seconds: float = 2.0
    _retry_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _retry_worker: threading.Thread | None = field(default=None, init=False, repr=False)
    _retry_stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.retry_queue_path is None:
            self.retry_queue_path = self.local.root / "pending_retry.json"
        self._load_retry_queue()

    def _load_retry_queue(self) -> None:
        path = self.retry_queue_path
        if path is None or not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload.get("anchors", [])
        with self._retry_lock:
            self.pending_retry = [ContinuityAnchor.from_dict(item) for item in values]

    def _persist_retry_queue(self) -> None:
        path = self.retry_queue_path
        if path is None:
            return
        with self._retry_lock:
            payload = {
                "anchors": [item.to_dict() for item in self.pending_retry],
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def start_retry_worker(self, interval_seconds: float | None = None) -> None:
        if interval_seconds is not None:
            self.retry_interval_seconds = max(0.1, interval_seconds)
        if self._retry_worker is not None and self._retry_worker.is_alive():
            return
        self._retry_stop.clear()

        def _run() -> None:
            while not self._retry_stop.wait(self.retry_interval_seconds):
                self.flush_retry()

        self._retry_worker = threading.Thread(target=_run, daemon=True, name="continuity-retry-worker")
        self._retry_worker.start()

    def stop_retry_worker(self, flush: bool = True) -> None:
        self._retry_stop.set()
        worker = self._retry_worker
        if worker is not None:
            worker.join(timeout=max(1.0, self.retry_interval_seconds * 2.0))
        self._retry_worker = None
        if flush:
            self.flush_retry()

    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        try:
            return self.local.get_latest(conversation_id)
        except AnchorCorruptedError:
            prev = self.local.get_previous(conversation_id)
            if prev is not None:
                return prev
            return self.remote.get_latest(conversation_id)
        except AnchorNotFoundError:
            return self.remote.get_latest(conversation_id)

    def get_previous(self, conversation_id: str) -> ContinuityAnchor | None:
        return self.local.get_previous(conversation_id)

    def flush_retry(self) -> None:
        with self._retry_lock:
            queued = list(self.pending_retry)
        remain: list[ContinuityAnchor] = []
        for anchor in queued:
            try:
                self.remote.put(anchor)
            except RuntimeError:
                remain.append(anchor)
        with self._retry_lock:
            self.pending_retry = remain
        self._persist_retry_queue()

    def put(self, anchor: ContinuityAnchor) -> None:
        self.local.put(anchor)
        try:
            self.remote.put(anchor)
        except RuntimeError:
            with self._retry_lock:
                self.pending_retry.append(anchor)
            self._persist_retry_queue()
