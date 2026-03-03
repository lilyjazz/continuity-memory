# Scripts Layout

`scripts/` is organized by execution purpose.

- `run_anchor_api.py` — start continuity HTTP API service
- `run_openclaw_continuity.py` — local OpenClaw continuity harness
- `run_openclaw_remote_behavioral_ab.py` — remote `/compact` benchmark
- `run_openclaw_remote_behavioral_reset_ab.py` — remote `/reset` benchmark
- `run_openclaw_remote_behavioral_matrix.py` — compact+reset matrix runner
- `run_openclaw_remote_stability_loop.py` — repeated stability runs
- `run_openclaw_remote_nightly_gate.py` — quality gate orchestration
- `run_openclaw_remote_mvp_ab.py` — MVP baseline benchmark

All scripts keep backward-compatible paths for CI and docs commands.
