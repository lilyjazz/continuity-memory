#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--data", default=str(ROOT / "mvp" / "data" / "ab_cases.jsonl"))
    parser.add_argument("--case-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--anchor-dir", default=".continuity/anchors")
    parser.add_argument("--mode", choices=["local", "hybrid"], default="hybrid")
    parser.add_argument("--remote-backend", choices=["tidb-zero", "in-memory"], default="tidb-zero")
    parser.add_argument("--tidb-env-prefix", default="TIDB_ZERO_")
    parser.add_argument("--tidb-zero-file", default="tidb-cloud-zero.json")
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports" / "openclaw_remote_behavioral_matrix.json"),
    )
    return parser.parse_args()


def _run(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout.strip())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    started = time.time()

    compact_out = ROOT / "reports" / "openclaw_remote_behavioral_compact_ab_results.json"
    reset_out = ROOT / "reports" / "openclaw_remote_behavioral_reset_ab_results.json"

    common = [
        "--ec2-host",
        args.ec2_host,
        "--ec2-user",
        args.ec2_user,
        "--ec2-key",
        str(Path(args.ec2_key).expanduser()),
        "--openclaw-path",
        args.openclaw_path,
        "--data",
        args.data,
        "--anchor-dir",
        args.anchor_dir,
        "--mode",
        args.mode,
        "--remote-backend",
        args.remote_backend,
        "--tidb-env-prefix",
        args.tidb_env_prefix,
        "--tidb-zero-file",
        args.tidb_zero_file,
    ]

    if args.case_id:
        common += ["--case-id", args.case_id]
    if args.max_cases > 0:
        common += ["--max-cases", str(args.max_cases)]

    compact_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_openclaw_remote_behavioral_ab.py"),
        "--out",
        str(compact_out),
        *common,
    ]
    reset_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_openclaw_remote_behavioral_reset_ab.py"),
        "--out",
        str(reset_out),
        *common,
    ]

    compact_summary = _run(compact_cmd)
    reset_summary = _run(reset_cmd)
    compact_report = _read_json(compact_out)
    reset_report = _read_json(reset_out)

    matrix = {
        "mode": "behavioral-matrix-compact-reset",
        "host": args.ec2_host,
        "compact": {
            "summary": compact_summary,
            "metrics": {
                "control_recall_strict": compact_report["control_recall_strict"],
                "experiment_recall_strict": compact_report["experiment_recall_strict"],
                "delta_strict": compact_report["delta_strict"],
                "control_recall_semantic": compact_report["control_recall_semantic"],
                "experiment_recall_semantic": compact_report["experiment_recall_semantic"],
                "delta_semantic": compact_report["delta_semantic"],
            },
            "report": str(compact_out),
        },
        "reset": {
            "summary": reset_summary,
            "metrics": {
                "control_recall_strict": reset_report["control_recall_strict"],
                "experiment_recall_strict": reset_report["experiment_recall_strict"],
                "delta_strict": reset_report["delta_strict"],
                "control_recall_semantic": reset_report["control_recall_semantic"],
                "experiment_recall_semantic": reset_report["experiment_recall_semantic"],
                "delta_semantic": reset_report["delta_semantic"],
            },
            "report": str(reset_out),
        },
        "elapsed_sec": round(time.time() - started, 2),
        "generated_at": int(time.time()),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "out": str(out_path),
                "compact_strict_delta": matrix["compact"]["metrics"]["delta_strict"],
                "compact_semantic_delta": matrix["compact"]["metrics"]["delta_semantic"],
                "reset_strict_delta": matrix["reset"]["metrics"]["delta_strict"],
                "reset_semantic_delta": matrix["reset"]["metrics"]["delta_semantic"],
                "elapsed_sec": matrix["elapsed_sec"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
