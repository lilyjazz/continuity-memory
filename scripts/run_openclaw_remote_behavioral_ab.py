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
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports" / "openclaw_remote_behavioral_ab_results.json"),
    )
    parser.add_argument("--case-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--anchor-dir", default=".continuity/anchors")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
    parser.add_argument(
        "--followup-prefix",
        default="It is the next day and we are continuing yesterday's project context.",
    )
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


def run_case(case: dict, gateway, service, followup_prefix: str):
    adapter_mod = import_module("continuity_memory.openclaw_adapter")
    benchmark_mod = import_module("continuity_memory.benchmark_cases")
    OpenClawContinuityAdapter = adapter_mod.OpenClawContinuityAdapter
    evaluate_answer = import_module("continuity_memory.evaluator").evaluate_answer
    build_case_turns_with_anchor_facts = benchmark_mod.build_case_turns_with_anchor_facts
    find_missing_expected_tokens = benchmark_mod.find_missing_expected_tokens

    control_day1_sid = f"ab-control-day1-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    control_day2_sid = f"ab-control-day2-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    experiment_day1_sid = f"ab-exp-day1-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    experiment_day2_sid = f"ab-exp-day2-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    conversation_id = f"default:behavior-{case['case_id']}-{uuid.uuid4().hex[:6]}"

    adapter = OpenClawContinuityAdapter(service=service, gateway=gateway, session_prefix="behavior")
    adapter.bind_session(conversation_id, experiment_day1_sid)

    isolation_instruction = (
        "Benchmark rule: Use ONLY facts from this session conversation turns. "
        "Ignore MEMORY.md, workspace files, prior chats, and external memory. "
        "Do not cite file sources."
    )
    gateway.ask(control_day1_sid, isolation_instruction)
    gateway.ask(experiment_day1_sid, isolation_instruction)

    case_turns = build_case_turns_with_anchor_facts(case)
    for turn in case_turns:
        gateway.ask(control_day1_sid, turn)
        gateway.ask(experiment_day1_sid, turn)
        adapter.add_turn(conversation_id, turn)

    pre_compaction_update = adapter.prepare_for_compaction(conversation_id)
    context_probe = service.render_context(conversation_id, "anchor coverage probe").context_block
    missing_tokens = find_missing_expected_tokens(context_probe, case["queries"])
    if missing_tokens:
        raise RuntimeError(
            f"Case {case['case_id']} has expected tokens not present in anchor context: {missing_tokens}"
        )

    compact_control_reply = gateway.ask(control_day1_sid, "/compact")
    compact_experiment_reply = gateway.ask(experiment_day1_sid, "/compact")

    day_switch_note = (
        "This is a new session on the next day. Continue naturally from prior work if possible."
    )
    gateway.ask(control_day2_sid, day_switch_note)
    gateway.ask(experiment_day2_sid, day_switch_note)
    adapter.bind_session(conversation_id, experiment_day2_sid)

    rows = []
    for query in case["queries"]:
        followup_query = (
            f"{followup_prefix}\n"
            f"Yesterday context should still apply.\n"
            f"Question: {query['q']}\n"
            "Answer in one short sentence."
        )
        control_answer = gateway.ask(control_day2_sid, followup_query)
        experiment_result = adapter.ask(conversation_id, followup_query)
        control_eval = evaluate_answer(control_answer, query["expected"])
        experiment_eval = evaluate_answer(experiment_result.answer, query["expected"])
        rows.append(
            {
                "query": query["q"],
                "followup_query": followup_query,
                "expected": query["expected"],
                "control_answer": control_answer,
                "experiment_answer": experiment_result.answer,
                "control_hit": control_eval["strict_hit"],
                "experiment_hit": experiment_eval["strict_hit"],
                "control_hit_strict": control_eval["strict_hit"],
                "experiment_hit_strict": experiment_eval["strict_hit"],
                "control_hit_semantic": control_eval["semantic_hit"],
                "experiment_hit_semantic": experiment_eval["semantic_hit"],
                "control_coverage_strict": control_eval["strict_coverage"],
                "experiment_coverage_strict": experiment_eval["strict_coverage"],
                "control_coverage_semantic": control_eval["semantic_coverage"],
                "experiment_coverage_semantic": experiment_eval["semantic_coverage"],
                "control_token_eval": control_eval["tokens"],
                "experiment_token_eval": experiment_eval["tokens"],
                "anchor_version_used": experiment_result.anchor_version_used,
                "anchor_version_after_ack": experiment_result.anchor_version_after_ack,
            }
        )

    return {
        "case_id": case["case_id"],
        "domain": case["domain"],
        "conversation_id": conversation_id,
        "control_day1_session_id": control_day1_sid,
        "control_day2_session_id": control_day2_sid,
        "experiment_day1_session_id": experiment_day1_sid,
        "experiment_day2_session_id": experiment_day2_sid,
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
        ssh_timeout_seconds=300,
    )
    store = build_store(args)
    service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=10))

    started = time.time()
    case_reports = []
    total_queries = 0
    control_hits = 0
    experiment_hits = 0
    control_hits_semantic = 0
    experiment_hits_semantic = 0

    for case in cases:
        report = run_case(case, gateway, service, args.followup_prefix)
        case_reports.append(report)
        for row in report["rows"]:
            total_queries += 1
            control_hits += int(row["control_hit"])
            experiment_hits += int(row["experiment_hit"])
            control_hits_semantic += int(row["control_hit_semantic"])
            experiment_hits_semantic += int(row["experiment_hit_semantic"])

    result = {
        "mode": "openclaw-remote-real-compact-behavioral-day-switch",
        "host": args.ec2_host,
        "cases": len(case_reports),
        "total_queries": total_queries,
        "control_recall": control_hits / total_queries,
        "experiment_recall": experiment_hits / total_queries,
        "delta": (experiment_hits - control_hits) / total_queries,
        "control_recall_strict": control_hits / total_queries,
        "experiment_recall_strict": experiment_hits / total_queries,
        "delta_strict": (experiment_hits - control_hits) / total_queries,
        "control_recall_semantic": control_hits_semantic / total_queries,
        "experiment_recall_semantic": experiment_hits_semantic / total_queries,
        "delta_semantic": (experiment_hits_semantic - control_hits_semantic) / total_queries,
        "elapsed_sec": round(time.time() - started, 2),
        "case_reports": case_reports,
        "disclosure": "Behavioral simulation with real /compact and explicit next-day session switch. Dual-track strict+semantic evaluation enabled.",
        "generated_at": int(time.time()),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "cases": result["cases"],
                "total_queries": result["total_queries"],
                "control_recall": result["control_recall"],
                "experiment_recall": result["experiment_recall"],
                "delta": result["delta"],
                "control_recall_semantic": result["control_recall_semantic"],
                "experiment_recall_semantic": result["experiment_recall_semantic"],
                "delta_semantic": result["delta_semantic"],
                "elapsed_sec": result["elapsed_sec"],
                "out": str(out_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
