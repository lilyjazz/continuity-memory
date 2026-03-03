#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--anchor-dir", default=".continuity/anchors")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
    parser.add_argument("--retry-worker-enabled", action="store_true")
    parser.add_argument("--retry-worker-interval", type=float, default=2.0)
    parser.add_argument("--api-security-enabled", action="store_true")
    parser.add_argument("--api-token", action="append", default=[])
    parser.add_argument("--api-admin-token", action="append", default=[])
    parser.add_argument("--api-rate-limit-per-minute", type=int, default=120)
    parser.add_argument("--api-require-auth-loopback", action="store_true")
    return parser.parse_args()


def parse_token_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in values:
        raw = item.strip()
        if not raw or ":" not in raw:
            raise RuntimeError(f"Invalid --api-token format: {item!r}. Expected token:tenant")
        token, tenant = raw.split(":", 1)
        token = token.strip()
        tenant = tenant.strip()
        if not token or not tenant:
            raise RuntimeError(f"Invalid --api-token format: {item!r}. Expected token:tenant")
        mapping[token] = tenant
    return mapping


def load_tidb_dsn_from_file(file_path: Path) -> str:
    if not file_path.exists():
        raise RuntimeError(
            "TiDB Zero credentials not found. Set env vars or provide --tidb-zero-file."
        )
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    dsn = payload.get("instance", {}).get("connectionString") or payload.get("connectionString")
    if not dsn:
        raise RuntimeError("Invalid TiDB Zero credential file: missing connectionString")
    return str(dsn)


def build_store(args: argparse.Namespace):
    storage_mod = import_module("continuity_memory.storage")
    tidb_mod = import_module("continuity_memory.tidb_zero")

    FileAnchorStore = storage_mod.FileAnchorStore
    HybridAnchorStore = storage_mod.HybridAnchorStore
    InMemoryRemoteBackend = storage_mod.InMemoryRemoteBackend
    TiDBZeroRemoteBackend = tidb_mod.TiDBZeroRemoteBackend

    local = FileAnchorStore(root=Path(args.anchor_dir), keep_versions=5)
    if args.mode == "local":
        return local

    if args.remote_backend == "in-memory":
        remote = InMemoryRemoteBackend()
    else:
        try:
            remote = TiDBZeroRemoteBackend.from_env(prefix=args.tidb_env_prefix)
        except RuntimeError:
            dsn = load_tidb_dsn_from_file(Path(args.tidb_zero_file))
            remote = TiDBZeroRemoteBackend(dsn=dsn)
    return HybridAnchorStore(local=local, remote=remote)


def main() -> None:
    args = parse_args()
    service_mod = import_module("continuity_memory.service")
    api_mod = import_module("continuity_memory.http_api")

    ContinuityService = service_mod.ContinuityService
    ServiceConfig = service_mod.ServiceConfig
    SLOPolicy = service_mod.SLOPolicy
    ApiSecurityConfig = api_mod.ApiSecurityConfig
    build_api_server = api_mod.build_api_server

    store = build_store(args)
    if args.retry_worker_enabled and hasattr(store, "start_retry_worker"):
        store.start_retry_worker(interval_seconds=args.retry_worker_interval)

    service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=10))
    security = ApiSecurityConfig(
        enabled=args.api_security_enabled,
        tokens=parse_token_mapping(args.api_token),
        admin_tokens=set(args.api_admin_token),
        rate_limit_per_minute=max(1, args.api_rate_limit_per_minute),
        require_auth_for_loopback=args.api_require_auth_loopback,
    )
    server = build_api_server(
        service=service,
        host=args.host,
        port=args.port,
        security=security,
        slo_policy=SLOPolicy(),
    )
    print(json.dumps({"host": args.host, "port": args.port, "mode": args.mode, "remote_backend": args.remote_backend}))
    try:
        server.serve_forever()
    finally:
        if hasattr(store, "stop_retry_worker"):
            store.stop_retry_worker(flush=True)


if __name__ == "__main__":
    main()
