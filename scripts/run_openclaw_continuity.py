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
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--anchor-dir", default=".continuity/anchors")
    parser.add_argument("--openclaw-bin", default="openclaw")
    parser.add_argument("--turn", action="append", default=[])
    parser.add_argument("--before-compaction", action="store_true")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
    parser.add_argument("--openclaw-mode", choices=["local", "remote", "mock"], default="local")
    parser.add_argument("--ec2-host", default="")
    parser.add_argument("--ec2-user", default="ubuntu")
    parser.add_argument("--ec2-key", default="~/.ssh/id_rsa")
    return parser.parse_args()


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
    adapter_mod = import_module("continuity_memory.openclaw_adapter")

    ContinuityService = service_mod.ContinuityService
    ServiceConfig = service_mod.ServiceConfig
    OpenClawCliGateway = adapter_mod.OpenClawCliGateway
    RemoteOpenClawGateway = adapter_mod.RemoteOpenClawGateway
    MockOpenClawGateway = adapter_mod.MockOpenClawGateway
    OpenClawContinuityAdapter = adapter_mod.OpenClawContinuityAdapter

    store = build_store(args)
    service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=10))

    if args.openclaw_mode == "mock":
        gateway = MockOpenClawGateway()
    elif args.openclaw_mode == "remote":
        gateway = RemoteOpenClawGateway(
            ssh_host=args.ec2_host,
            ssh_user=args.ec2_user,
            ssh_key_path=str(Path(args.ec2_key).expanduser()),
        )
    else:
        gateway = OpenClawCliGateway(binary=args.openclaw_bin)

    adapter = OpenClawContinuityAdapter(service=service, gateway=gateway)

    for turn in args.turn:
        adapter.add_turn(args.conversation_id, turn)

    compaction_update = None
    if args.before_compaction:
        compaction_update = adapter.prepare_for_compaction(args.conversation_id)

    result = adapter.ask(args.conversation_id, args.query)
    output = {
        "conversation_id": args.conversation_id,
        "session_id": result.session_id,
        "degraded": result.degraded,
        "anchor_version_used": result.anchor_version_used,
        "anchor_version_after_ack": result.anchor_version_after_ack,
        "answer": result.answer,
        "context_block": result.continuity_context_block,
        "before_compaction_anchor_version": (
            compaction_update.anchor_version if compaction_update is not None else None
        ),
        "mode": args.mode,
        "remote_backend": args.remote_backend,
        "openclaw_mode": args.openclaw_mode,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
