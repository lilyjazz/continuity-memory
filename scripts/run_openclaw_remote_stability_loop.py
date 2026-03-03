#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    parser.add_argument("--max-cases", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports" / "openclaw_remote_stability_loop_results.json"),
    )
    return parser.parse_args()


def _run_script(command: list[str]) -> dict:
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout.strip())


def _build_common_args(args: argparse.Namespace) -> list[str]:
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
        "--max-cases",
        str(args.max_cases),
    ]


def main() -> None:
    args = parse_args()
    py = str(Path(sys.executable))

    compact_script = str(ROOT / "scripts" / "run_openclaw_remote_behavioral_ab.py")
    reset_script = str(ROOT / "scripts" / "run_openclaw_remote_behavioral_reset_ab.py")
    round_dir = ROOT / "reports" / "stability_rounds"
    round_dir.mkdir(parents=True, exist_ok=True)

    rounds: list[dict] = []
    for idx in range(1, args.rounds + 1):
        started = time.time()
        compact_out = round_dir / f"compact_round_{idx}.json"
        reset_out = round_dir / f"reset_round_{idx}.json"

        compact = _run_script(
            [py, compact_script, *_build_common_args(args), "--out", str(compact_out)]
        )
        reset = _run_script(
            [py, reset_script, *_build_common_args(args), "--out", str(reset_out)]
        )

        elapsed = round(time.time() - started, 2)
        rounds.append(
            {
                "round": idx,
                "compact": compact,
                "reset": reset,
                "elapsed_sec": elapsed,
                "pass": compact["delta"] > 0 and reset["delta"] > 0,
            }
        )

    compact_deltas = [r["compact"]["delta"] for r in rounds]
    reset_deltas = [r["reset"]["delta"] for r in rounds]
    elapsed_values = [r["elapsed_sec"] for r in rounds]

    result = {
        "mode": "openclaw-remote-stability-loop",
        "host": args.ec2_host,
        "data": args.data,
        "max_cases": args.max_cases,
        "rounds": rounds,
        "summary": {
            "round_count": len(rounds),
            "passed_rounds": sum(1 for r in rounds if r["pass"]),
            "compact_delta_avg": statistics.mean(compact_deltas) if compact_deltas else 0.0,
            "reset_delta_avg": statistics.mean(reset_deltas) if reset_deltas else 0.0,
            "elapsed_avg_sec": statistics.mean(elapsed_values) if elapsed_values else 0.0,
            "elapsed_p95_sec": max(elapsed_values) if elapsed_values else 0.0,
        },
        "generated_at": int(time.time()),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "round_count": result["summary"]["round_count"],
                "passed_rounds": result["summary"]["passed_rounds"],
                "compact_delta_avg": result["summary"]["compact_delta_avg"],
                "reset_delta_avg": result["summary"]["reset_delta_avg"],
                "elapsed_avg_sec": result["summary"]["elapsed_avg_sec"],
                "elapsed_p95_sec": result["summary"]["elapsed_p95_sec"],
                "out": str(out_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
