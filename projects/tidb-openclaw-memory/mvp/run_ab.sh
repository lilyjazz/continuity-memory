#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 src/run_compaction_ab.py
