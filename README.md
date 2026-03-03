# Continuity Memory

Production-oriented Continuity Anchor implementation for improving OpenClaw conversation continuity after `/compact` and `/reset`.

## Current Scope

- Anchor model + extraction + rendering service (`src/continuity_memory/`)
- Local and hybrid storage (file store + TiDB Zero remote backend)
- HTTP API for update/render/ack flows (`/anchor/*`)
- API hardening layer (token auth, tenant scope checks, rate limit)
- OpenClaw adapters and remote EC2 benchmark runners
- Behavioral A/B benchmark matrix for real `/compact` and `/reset`
- Quality/stability gate tooling and OpenClaw plugin scaffold

## Key Directories

- `src/continuity_memory/` — core implementation
- `scripts/` — local/remote runners, matrix, stability loop, nightly gate
- `mvp/data/` — benchmark datasets (`ab_cases.jsonl`, `ab_cases_quality.jsonl`)
- `reports/` — generated benchmark outputs
- `assets/openclaw-continuity-plugin/` — OpenClaw plugin scaffold and integration docs
- `SPEC.md` — product goals and acceptance targets
- `TECHNICAL_DESIGN.md` — architecture and current implementation notes
- `PROJECT.md` — project status and evidence snapshots
- `PROJECT_STRUCTURE.md` — module map and runtime call flow

## Core API Contract

- `POST /anchor/update`
- `GET /anchor/latest?conversation_id=...`
- `POST /anchor/render-context`
- `POST /anchor/ack-response`

Operational endpoints:

- `GET /health`
- `GET /metrics` (admin when security enabled)
- `GET /alerts/slo` (admin when security enabled)

## Project Structure

Core package layout:

- `src/continuity_memory/models.py` — anchor schema and serialization
- `src/continuity_memory/extractor.py` — anchor extraction + checksum
- `src/continuity_memory/storage.py` — local/hybrid storage, durable retry queue, worker
- `src/continuity_memory/service.py` — continuity logic, metrics, SLO evaluation
- `src/continuity_memory/api_security.py` — API security config, auth context, limiter
- `src/continuity_memory/http_api.py` — HTTP server and endpoint handlers
- `src/continuity_memory/openclaw_adapter.py` — OpenClaw gateway adapters
- `src/continuity_memory/tidb_zero.py` — TiDB Zero backend

See `TECHNICAL_DESIGN.md` for sequence diagrams and runtime behavior details.
See `PROJECT_STRUCTURE.md` for module-level call flow and ownership boundaries.

## Runbook

1. Local regression:
   - `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
2. Real EC2 compact+reset matrix:
   - `./.venv/bin/python scripts/run_openclaw_remote_behavioral_matrix.py --ec2-host <host> --ec2-user ubuntu --ec2-key <pem> --openclaw-path openclaw --mode hybrid --remote-backend tidb-zero --tidb-zero-file tidb-cloud-zero.json`
3. Quality dataset suites:
   - `./.venv/bin/python scripts/run_openclaw_remote_behavioral_ab.py --data mvp/data/ab_cases_quality.jsonl ...`
   - `./.venv/bin/python scripts/run_openclaw_remote_behavioral_reset_ab.py --data mvp/data/ab_cases_quality.jsonl ...`
4. Stability loop:
   - `./.venv/bin/python scripts/run_openclaw_remote_stability_loop.py --data mvp/data/ab_cases_quality.jsonl --max-cases 1 --rounds 2 ...`
5. Nightly gate:
   - `./.venv/bin/python scripts/run_openclaw_remote_nightly_gate.py --data mvp/data/ab_cases_quality.jsonl --stability-rounds 5 ...`

## Latest Result Pointers

- Existing behavioral matrix: `reports/openclaw_remote_behavioral_matrix.json`
- Quality compact suite: `reports/openclaw_remote_behavioral_quality_compact_ab_results.json`
- Quality reset suite: `reports/openclaw_remote_behavioral_quality_reset_ab_results.json`
- Stability loop: `reports/openclaw_remote_stability_loop_results.json`
- Nightly gate: `reports/openclaw_remote_nightly_gate_results.json`

## OpenClaw Default Integration

Use the plugin scaffold under `assets/openclaw-continuity-plugin/` to enable continuity by default in OpenClaw without per-query wrapper scripts.

- Manifest: `assets/openclaw-continuity-plugin/openclaw.plugin.json`
- Hook implementation: `assets/openclaw-continuity-plugin/index.ts`
- Example OpenClaw config: `assets/openclaw-continuity-plugin/openclaw.yaml.example`
- Setup docs: `assets/openclaw-continuity-plugin/README.md`
