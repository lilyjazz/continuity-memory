from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .extractor import compute_checksum
from .models import ContinuityAnchor
from .storage import AnchorCorruptedError, AnchorNotFoundError


def _safe_identifier(name: str, label: str) -> str:
    if not name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError(f"Invalid {label} identifier: {name!r}")
    return name


@dataclass
class TiDBZeroRemoteBackend:
    dsn: str
    table_name: str = "continuity_anchors"
    default_database: str = "continuity_memory_dev"
    connect_timeout_seconds: float = 5.0
    ssl_ca: str | None = None
    connector: Any | None = None

    @classmethod
    def from_env(cls, prefix: str = "TIDB_ZERO_") -> "TiDBZeroRemoteBackend":
        dsn = os.getenv(f"{prefix}DSN", "").strip()
        default_database = os.getenv(f"{prefix}DATABASE", "continuity_memory_dev").strip() or "continuity_memory_dev"
        if not dsn:
            host = os.getenv(f"{prefix}HOST", "").strip()
            user = os.getenv(f"{prefix}USER", "").strip()
            password = os.getenv(f"{prefix}PASSWORD", "").strip()
            database = os.getenv(f"{prefix}DATABASE", "").strip() or default_database
            port = os.getenv(f"{prefix}PORT", "4000").strip()
            if not all([host, user, password]):
                raise RuntimeError(
                    "Missing TiDB Zero config. Set TIDB_ZERO_DSN or host/user/password env vars."
                )
            dsn = f"mysql://{user}:{password}@{host}:{port}/{database}?ssl=true"

        table_name = os.getenv(f"{prefix}TABLE", "continuity_anchors").strip() or "continuity_anchors"
        timeout = float(os.getenv(f"{prefix}CONNECT_TIMEOUT", "5.0").strip() or "5.0")
        ssl_ca = os.getenv(f"{prefix}SSL_CA", "").strip() or None
        return cls(
            dsn=dsn,
            table_name=table_name,
            default_database=default_database,
            connect_timeout_seconds=timeout,
            ssl_ca=ssl_ca,
        )

    def _resolve_ca_path(self) -> str | None:
        if self.ssl_ca:
            return self.ssl_ca
        try:
            certifi = import_module("certifi")
            path = certifi.where()
            if path:
                return str(path)
        except ImportError:
            pass
        fallback = Path("/etc/ssl/cert.pem")
        if fallback.exists():
            return str(fallback)
        return None

    def _resolve_connector(self) -> Any:
        if self.connector is not None:
            return self.connector
        try:
            module = import_module("pymysql")
        except ImportError as exc:
            raise RuntimeError(
                "pymysql is required for TiDB Zero backend. Install with: pip install pymysql"
            ) from exc
        self.connector = module
        return module

    def _database_name(self) -> str:
        parsed = urlparse(self.dsn)
        from_path = parsed.path.lstrip("/")
        name = from_path or self.default_database
        return _safe_identifier(name, "database")

    def _connection_kwargs(self) -> dict[str, Any]:
        parsed = urlparse(self.dsn)
        if parsed.scheme not in ("mysql", "mysql+pymysql"):
            raise RuntimeError("TiDB DSN must use mysql:// or mysql+pymysql://")

        if not parsed.hostname:
            raise RuntimeError("TiDB DSN must include host")

        query = parse_qs(parsed.query)
        ssl_enabled = query.get("ssl", ["true"])[0].lower() not in ("0", "false", "no")

        kwargs: dict[str, Any] = {
            "host": parsed.hostname,
            "port": parsed.port or 4000,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "connect_timeout": self.connect_timeout_seconds,
            "charset": "utf8mb4",
            "autocommit": True,
        }
        if ssl_enabled:
            ca_path = self._resolve_ca_path()
            if ca_path:
                kwargs["ssl"] = {"ca": ca_path, "check_hostname": True}
            else:
                kwargs["ssl"] = {"check_hostname": True}
        return kwargs

    def _connect(self) -> Any:
        connector = self._resolve_connector()
        return connector.connect(**self._connection_kwargs())

    def _ensure_schema(self, conn: Any) -> None:
        database_name = self._database_name()
        table_name = _safe_identifier(self.table_name, "table")
        sql = (
            f"CREATE TABLE IF NOT EXISTS `{table_name}` ("
            "conversation_id VARCHAR(255) PRIMARY KEY,"
            "anchor_version BIGINT NOT NULL,"
            "payload JSON NOT NULL,"
            "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            ")"
        )
        cursor = conn.cursor()
        try:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}`")
            cursor.execute(f"USE `{database_name}`")
            cursor.execute(sql)
        finally:
            cursor.close()

    def put(self, anchor: ContinuityAnchor) -> None:
        table_name = _safe_identifier(self.table_name, "table")
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cursor = conn.cursor()
            try:
                payload = json.dumps(anchor.to_dict(), ensure_ascii=False)
                sql = (
                    f"INSERT INTO `{table_name}` (conversation_id, anchor_version, payload) "
                    "VALUES (%s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE "
                    "anchor_version = VALUES(anchor_version), "
                    "payload = VALUES(payload), "
                    "updated_at = CURRENT_TIMESTAMP"
                )
                cursor.execute(sql, (anchor.conversation_id, anchor.anchor_version, payload))
            finally:
                cursor.close()
        except Exception as exc:
            raise RuntimeError(f"TiDB write failed: {exc}") from exc
        finally:
            conn.close()

    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        table_name = _safe_identifier(self.table_name, "table")
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cursor = conn.cursor()
            try:
                sql = (
                    f"SELECT payload FROM `{table_name}` "
                    "WHERE conversation_id = %s LIMIT 1"
                )
                cursor.execute(sql, (conversation_id,))
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                raise AnchorNotFoundError(conversation_id)

            raw_payload = row[0]
            if isinstance(raw_payload, (bytes, bytearray)):
                payload = json.loads(raw_payload.decode("utf-8"))
            elif isinstance(raw_payload, str):
                payload = json.loads(raw_payload)
            elif isinstance(raw_payload, dict):
                payload = raw_payload
            else:
                raise RuntimeError("Unsupported payload format from TiDB")

            anchor = ContinuityAnchor.from_dict(payload)
            if anchor.meta.checksum != compute_checksum(anchor):
                raise AnchorCorruptedError(conversation_id)
            return anchor
        except AnchorNotFoundError:
            raise
        except AnchorCorruptedError:
            raise
        except Exception as exc:
            raise RuntimeError(f"TiDB read failed: {exc}") from exc
        finally:
            conn.close()
