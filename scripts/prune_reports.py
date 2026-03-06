#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

KEEP_FILES = {
    "README.md",
    "openclaw_remote_behavioral_matrix.json",
    "openclaw_remote_behavioral_compact_ab_results.json",
    "openclaw_remote_behavioral_reset_ab_results.json",
    "openclaw_remote_behavioral_quality_compact_ab_results.json",
    "openclaw_remote_behavioral_quality_reset_ab_results.json",
    "openclaw_remote_stability_loop_results.json",
    "openclaw_remote_nightly_gate_results.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete files not in keep set")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not REPORTS.exists():
        print("reports directory not found")
        return

    remove: list[Path] = []
    for path in REPORTS.rglob("*.json"):
        rel = path.relative_to(REPORTS)
        if rel.parts and rel.parts[0] == "stability_rounds":
            remove.append(path)
            continue
        if rel.name not in KEEP_FILES:
            remove.append(path)

    if not remove:
        print("No report files to prune")
        return

    print("Prune candidates:")
    for path in sorted(remove):
        print(f"- {path.relative_to(ROOT)}")

    if not args.apply:
        print("Dry run only. Re-run with --apply to delete.")
        return

    for path in remove:
        path.unlink(missing_ok=True)

    rounds = REPORTS / "stability_rounds"
    if rounds.exists() and not any(rounds.iterdir()):
        rounds.rmdir()

    print(f"Deleted {len(remove)} files")


if __name__ == "__main__":
    main()
