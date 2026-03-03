import json
import os
import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

compute_checksum = import_module("continuity_memory.extractor").compute_checksum
_models = import_module("continuity_memory.models")
AnchorMeta = _models.AnchorMeta
ContinuityAnchor = _models.ContinuityAnchor
_storage = import_module("continuity_memory.storage")
AnchorCorruptedError = _storage.AnchorCorruptedError
AnchorNotFoundError = _storage.AnchorNotFoundError
TiDBZeroRemoteBackend = import_module("continuity_memory.tidb_zero").TiDBZeroRemoteBackend


class _FakeCursor:
    def __init__(self, rows: dict[str, dict[str, str]]) -> None:
        self._rows = rows
        self._selected = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None):
        values = params or ()
        query = " ".join(sql.split()).lower()
        if query.startswith("create database"):
            return
        if query.startswith("use"):
            return
        if query.startswith("create table"):
            return
        if query.startswith("insert into"):
            if len(values) < 3:
                raise RuntimeError("invalid insert params")
            conversation_id = values[0]
            anchor_version = values[1]
            payload = values[2]
            self._rows[conversation_id] = {
                "anchor_version": str(anchor_version),
                "payload": payload,
            }
            return
        if query.startswith("select payload"):
            if len(values) < 1:
                raise RuntimeError("invalid select params")
            conversation_id = values[0]
            item = self._rows.get(conversation_id)
            if item is None:
                self._selected = None
            else:
                self._selected = (item["payload"],)
            return
        raise RuntimeError("unsupported SQL")

    def fetchone(self):
        return self._selected

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, rows: dict[str, dict[str, str]]) -> None:
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def close(self):
        return None


class _FakePyMySQL:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, str]] = {}
        self.kwargs_seen: dict[str, object] = {}

    def connect(self, **kwargs):
        self.kwargs_seen = kwargs
        return _FakeConnection(self.rows)


def _sample_anchor(conversation_id: str, version: int) -> ContinuityAnchor:
    anchor = ContinuityAnchor(
        conversation_id=conversation_id,
        anchor_version=version,
        timestamp=123.0,
        turn_range=(1, 2),
        summary_compact="summary",
        meta=AnchorMeta(confidence=0.9, source_refs=[1, 2], checksum=""),
    )
    anchor.meta.checksum = compute_checksum(anchor)
    return anchor


class TiDBZeroBackendTests(unittest.TestCase):
    def test_put_get_roundtrip(self) -> None:
        connector = _FakePyMySQL()
        backend = TiDBZeroRemoteBackend(
            dsn="mysql://user:pass@127.0.0.1:4000/contdb?ssl=true",
            table_name="anchors",
            connector=connector,
        )
        anchor = _sample_anchor("conv-1", 3)
        backend.put(anchor)
        latest = backend.get_latest("conv-1")

        self.assertEqual(latest.anchor_version, 3)
        self.assertEqual(latest.conversation_id, "conv-1")
        self.assertEqual(connector.kwargs_seen.get("host"), "127.0.0.1")
        self.assertIn("ssl", connector.kwargs_seen)

    def test_root_dsn_uses_default_database(self) -> None:
        connector = _FakePyMySQL()
        backend = TiDBZeroRemoteBackend(
            dsn="mysql://user:pass@127.0.0.1:4000/?ssl=true",
            table_name="anchors",
            default_database="devdb",
            connector=connector,
        )
        anchor = _sample_anchor("conv-root", 2)
        backend.put(anchor)
        loaded = backend.get_latest("conv-root")
        self.assertEqual(loaded.anchor_version, 2)

    def test_get_missing_anchor_raises(self) -> None:
        backend = TiDBZeroRemoteBackend(
            dsn="mysql://u:p@localhost:4000/db?ssl=true",
            connector=_FakePyMySQL(),
        )
        with self.assertRaises(AnchorNotFoundError):
            backend.get_latest("missing")

    def test_detect_corrupted_payload(self) -> None:
        connector = _FakePyMySQL()
        backend = TiDBZeroRemoteBackend(
            dsn="mysql://u:p@localhost:4000/db?ssl=true",
            connector=connector,
        )
        anchor = _sample_anchor("conv-x", 1)
        backend.put(anchor)

        tampered = json.loads(connector.rows["conv-x"]["payload"])
        tampered["summary_compact"] = "tampered"
        connector.rows["conv-x"]["payload"] = json.dumps(tampered, ensure_ascii=False)

        with self.assertRaises(AnchorCorruptedError):
            backend.get_latest("conv-x")

    def test_from_env_supports_host_fields(self) -> None:
        keys = [
            "TIDB_ZERO_DSN",
            "TIDB_ZERO_HOST",
            "TIDB_ZERO_USER",
            "TIDB_ZERO_PASSWORD",
            "TIDB_ZERO_DATABASE",
            "TIDB_ZERO_PORT",
            "TIDB_ZERO_TABLE",
        ]
        original = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.pop("TIDB_ZERO_DSN", None)
            os.environ["TIDB_ZERO_HOST"] = "localhost"
            os.environ["TIDB_ZERO_USER"] = "u"
            os.environ["TIDB_ZERO_PASSWORD"] = "p"
            os.environ["TIDB_ZERO_DATABASE"] = "db"
            os.environ["TIDB_ZERO_PORT"] = "4000"
            os.environ["TIDB_ZERO_TABLE"] = "my_anchors"

            backend = TiDBZeroRemoteBackend.from_env("TIDB_ZERO_")
            self.assertIn("mysql://u:p@localhost:4000/db", backend.dsn)
            self.assertEqual(backend.table_name, "my_anchors")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
