#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class GateThresholds:
    min_compact_delta_strict: float = 0.20
    min_reset_delta_strict: float = 0.20
    min_compact_delta_semantic: float = 0.30
    min_reset_delta_semantic: float = 0.30
    min_stability_pass_rate: float = 1.00
    max_stability_elapsed_p95_sec: float = 1200.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ec2-host", required=True)
    parser.add_argument("--ec2-user", default="ubuntu")
    parser.add_argument("--ec2-key", required=True)
    parser.add_argument("--openclaw-path", default="openclaw")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
    parser.add_argument("--data", default=str(ROOT / "mvp" / "data" / "ab_cases_quality.jsonl"))
    parser.add_argument("--quality-max-cases", type=int, default=0)
    parser.add_argument("--stability-max-cases", type=int, default=1)
    parser.add_argument("--stability-rounds", type=int, default=5)
    parser.add_argument("--min-compact-delta-strict", type=float, default=0.20)
    parser.add_argument("--min-reset-delta-strict", type=float, default=0.20)
    parser.add_argument("--min-compact-delta-semantic", type=float, default=0.30)
    parser.add_argument("--min-reset-delta-semantic", type=float, default=0.30)
    parser.add_argument("--min-stability-pass-rate", type=float, default=1.0)
    parser.add_argument("--max-stability-elapsed-p95-sec", type=float, default=1200.0)
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports" / "openclaw_remote_nightly_gate_results.json"),
    )
    return parser.parse_args()


def _run_json(command: list[str]) -> dict:
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    output = proc.stdout.strip().splitlines()
    if not output:
        raise RuntimeError("No output from command")
    return json.loads(output[-1])


def _common_remote_args(args: argparse.Namespace) -> list[str]:
    return [
        "--ec2-host",
        args.ec2_host,
        "--ec2-user",
        args.ec2_user,
        "--ec2-key",
        args.ec2_key,
        "--openclaw-path",
        args.openclaw_path,
        "--mode",
        args.mode,
        "--remote-backend",
        args.remote_backend,
        "--tidb-env-prefix",
        args.tidb_env_prefix,
        "--tidb-zero-file",
        args.tidb_zero_file,
        "--data",
        args.data,
    ]


def evaluate_gate(compact: dict, reset: dict, stability: dict, thresholds: GateThresholds) -> dict:
    stability_summary = stability.get("summary", {}) if isinstance(stability.get("summary", {}), dict) else {}
    round_count = float(stability_summary.get("round_count", stability.get("round_count", 0)) or 0)
    passed_rounds = float(stability_summary.get("passed_rounds", stability.get("passed_rounds", 0)) or 0)
    pass_rate = (passed_rounds / round_count) if round_count > 0 else 0.0
    elapsed_p95 = float(
        stability_summary.get("elapsed_p95_sec", stability.get("elapsed_p95_sec", 0.0)) or 0.0
    )

    checks = {
        "compact_delta_strict": {
            "ok": float(compact.get("delta", 0.0)) >= thresholds.min_compact_delta_strict,
            "actual": float(compact.get("delta", 0.0)),
            "min": thresholds.min_compact_delta_strict,
        },
        "reset_delta_strict": {
            "ok": float(reset.get("delta", 0.0)) >= thresholds.min_reset_delta_strict,
            "actual": float(reset.get("delta", 0.0)),
            "min": thresholds.min_reset_delta_strict,
        },
        "compact_delta_semantic": {
            "ok": float(compact.get("delta_semantic", 0.0)) >= thresholds.min_compact_delta_semantic,
            "actual": float(compact.get("delta_semantic", 0.0)),
            "min": thresholds.min_compact_delta_semantic,
        },
        "reset_delta_semantic": {
            "ok": float(reset.get("delta_semantic", 0.0)) >= thresholds.min_reset_delta_semantic,
            "actual": float(reset.get("delta_semantic", 0.0)),
            "min": thresholds.min_reset_delta_semantic,
        },
        "stability_pass_rate": {
            "ok": pass_rate >= thresholds.min_stability_pass_rate,
            "actual": pass_rate,
            "min": thresholds.min_stability_pass_rate,
        },
        "stability_elapsed_p95": {
            "ok": elapsed_p95 <= thresholds.max_stability_elapsed_p95_sec,
            "actual": elapsed_p95,
            "max": thresholds.max_stability_elapsed_p95_sec,
        },
    }
    overall_pass = all(item["ok"] for item in checks.values())
    return {
        "overall_pass": overall_pass,
        "checks": checks,
    }


def main() -> None:
    args = parse_args()
    py = str(Path(sys.executable))
    common = _common_remote_args(args)
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    compact_out = reports_dir / "openclaw_remote_behavioral_quality_compact_ab_results.json"
    reset_out = reports_dir / "openclaw_remote_behavioral_quality_reset_ab_results.json"
    stability_out = reports_dir / "openclaw_remote_stability_loop_results.json"

    started = time.time()
    compact = _run_json(
        [
            py,
            str(ROOT / "scripts" / "run_openclaw_remote_behavioral_ab.py"),
            *common,
            "--out",
            str(compact_out),
            "--max-cases",
            str(args.quality_max_cases),
        ]
    )
    reset = _run_json(
        [
            py,
            str(ROOT / "scripts" / "run_openclaw_remote_behavioral_reset_ab.py"),
            *common,
            "--out",
            str(reset_out),
            "--max-cases",
            str(args.quality_max_cases),
        ]
    )
    stability = _run_json(
        [
            py,
            str(ROOT / "scripts" / "run_openclaw_remote_stability_loop.py"),
            *common,
            "--out",
            str(stability_out),
            "--max-cases",
            str(args.stability_max_cases),
            "--rounds",
            str(args.stability_rounds),
        ]
    )

    thresholds = GateThresholds(
        min_compact_delta_strict=args.min_compact_delta_strict,
        min_reset_delta_strict=args.min_reset_delta_strict,
        min_compact_delta_semantic=args.min_compact_delta_semantic,
        min_reset_delta_semantic=args.min_reset_delta_semantic,
        min_stability_pass_rate=args.min_stability_pass_rate,
        max_stability_elapsed_p95_sec=args.max_stability_elapsed_p95_sec,
    )
    gate = evaluate_gate(compact=compact, reset=reset, stability=stability, thresholds=thresholds)

    result = {
        "mode": "openclaw-remote-nightly-gate",
        "host": args.ec2_host,
        "data": args.data,
        "quality_max_cases": args.quality_max_cases,
        "stability_max_cases": args.stability_max_cases,
        "stability_rounds": args.stability_rounds,
        "compact": compact,
        "reset": reset,
        "stability": stability,
        "gate": gate,
        "elapsed_sec": round(time.time() - started, 2),
        "generated_at": int(time.time()),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "overall_pass": gate["overall_pass"],
                "compact_delta": compact.get("delta"),
                "reset_delta": reset.get("delta"),
                "compact_delta_semantic": compact.get("delta_semantic"),
                "reset_delta_semantic": reset.get("delta_semantic"),
                "stability_passed_rounds": stability.get("passed_rounds"),
                "stability_round_count": stability.get("round_count"),
                "out": str(out_path),
            },
            ensure_ascii=False,
        )
    )

    if not gate["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
