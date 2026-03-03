#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ec2-host", required=True)
    parser.add_argument("--ec2-user", default="ubuntu")
    parser.add_argument("--ec2-key", required=True)
    parser.add_argument("--openclaw-path", default="openclaw")
    parser.add_argument("--data", default=str(ROOT / "mvp" / "data" / "ab_cases.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "openclaw_remote_mvp_ab_results.json"))
    parser.add_argument("--case-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--anchor-dir", default=".continuity/anchors")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
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


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def hit(answer: str, expected: list[str]) -> bool:
    lower = answer.lower()
    return all(token.lower() in lower for token in expected)


def run_case(case: dict, gateway, service):
    adapter_mod = import_module("continuity_memory.openclaw_adapter")
    OpenClawContinuityAdapter = adapter_mod.OpenClawContinuityAdapter

    control_sid = f"ab-control-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    experiment_sid = f"ab-exp-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    conversation_id = f"remote-mvp-{case['case_id']}-{uuid.uuid4().hex[:6]}"

    adapter = OpenClawContinuityAdapter(service=service, gateway=gateway, session_prefix="remote-mvp")
    adapter.bind_session(conversation_id, experiment_sid)

    isolation_instruction = (
        "Benchmark rule: Use ONLY facts from this session conversation turns. "
        "Ignore MEMORY.md, workspace files, prior chats, and external memory. "
        "Do not cite file sources."
    )

    gateway.ask(control_sid, isolation_instruction)
    gateway.ask(experiment_sid, isolation_instruction)

    for turn in case["turns"]:
        gateway.ask(control_sid, turn)
        gateway.ask(experiment_sid, turn)
        adapter.add_turn(conversation_id, turn)

    pre_compaction_update = adapter.prepare_for_compaction(conversation_id)
    compact_control_reply = gateway.ask(control_sid, "/compact")
    compact_experiment_reply = gateway.ask(experiment_sid, "/compact")

    rows = []
    for query in case["queries"]:
        control_answer = gateway.ask(control_sid, query["q"])
        experiment_result = adapter.ask(conversation_id, query["q"])
        rows.append(
            {
                "query": query["q"],
                "expected": query["expected"],
                "control_answer": control_answer,
                "experiment_answer": experiment_result.answer,
                "control_hit": hit(control_answer, query["expected"]),
                "experiment_hit": hit(experiment_result.answer, query["expected"]),
                "anchor_version_used": experiment_result.anchor_version_used,
                "anchor_version_after_ack": experiment_result.anchor_version_after_ack,
            }
        )

    return {
        "case_id": case["case_id"],
        "domain": case["domain"],
        "conversation_id": conversation_id,
        "control_session_id": control_sid,
        "experiment_session_id": experiment_sid,
        "pre_compaction_anchor_version": pre_compaction_update.anchor_version,
        "compact_control_reply": compact_control_reply,
        "compact_experiment_reply": compact_experiment_reply,
        "rows": rows,
    }


def main() -> None:
    args = parse_args()
    service_mod = import_module("continuity_memory.service")
    adapter_mod = import_module("continuity_memory.openclaw_adapter")

    ContinuityService = service_mod.ContinuityService
    ServiceConfig = service_mod.ServiceConfig
    RemoteOpenClawGateway = adapter_mod.RemoteOpenClawGateway

    cases = load_cases(Path(args.data))
    if args.case_id:
        cases = [case for case in cases if case.get("case_id") == args.case_id]
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        raise RuntimeError("No cases selected")

    gateway = RemoteOpenClawGateway(
        ssh_host=args.ec2_host,
        ssh_user=args.ec2_user,
        ssh_key_path=str(Path(args.ec2_key).expanduser()),
        openclaw_path=args.openclaw_path,
        ssh_timeout_seconds=180,
    )
    store = build_store(args)
    service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=10))

    started = time.time()
    case_reports = []
    total_queries = 0
    control_hits = 0
    experiment_hits = 0

    for case in cases:
        report = run_case(case, gateway, service)
        case_reports.append(report)
        for row in report["rows"]:
            total_queries += 1
            control_hits += int(row["control_hit"])
            experiment_hits += int(row["experiment_hit"])

    result = {
        "mode": "openclaw-remote-real-compact-mvp-style",
        "host": args.ec2_host,
        "cases": len(case_reports),
        "total_queries": total_queries,
        "control_recall": control_hits / total_queries,
        "experiment_recall": experiment_hits / total_queries,
        "delta": (experiment_hits - control_hits) / total_queries,
        "elapsed_sec": round(time.time() - started, 2),
        "case_reports": case_reports,
        "disclosure": "MVP-like A/B flow with real /compact on remote OpenClaw and continuity context injection from P0 service.",
        "generated_at": int(time.time()),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "cases": result["cases"],
        "total_queries": result["total_queries"],
        "control_recall": result["control_recall"],
        "experiment_recall": result["experiment_recall"],
        "delta": result["delta"],
        "elapsed_sec": result["elapsed_sec"],
        "out": str(out_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
