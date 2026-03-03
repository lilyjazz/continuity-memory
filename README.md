# Continuity Memory

Compaction-safe continuity for OpenClaw sessions.

Continuity Memory preserves high-value context across `/compact` and `/reset`, so follow-up answers stay consistent instead of drifting or forgetting prior decisions.

## Why this exists

Long-running agent sessions eventually compact context. When that happens, many systems lose critical state and produce:
- "I don't remember" responses
- off-topic follow-up answers
- contradictions against previously confirmed facts

This project adds a continuity layer that writes, restores, and verifies anchor state around compaction/reset boundaries.

## What you get

- Continuity Anchor model (`state`, `facts`, `intent`, reliability metadata)
- Local + hybrid storage (file store + TiDB Zero remote fallback)
- Hardened anchor API (`/anchor/*`) with auth, tenant scope, and rate limiting
- OpenClaw plugin scaffold with startup probes, circuit breaker, and bypass switch
- Real EC2 benchmark runners for `/compact` and `/reset`
- Quality/stability/nightly gate tooling for production release checks

## Quickstart (Local)

Run tests first:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests
```

Start the anchor API service:

```bash
./.venv/bin/python scripts/run_anchor_api.py --host 127.0.0.1 --port 8080 --mode local
```

Then use OpenClaw integration (plugin or script harness) to call:
- `POST /anchor/update`
- `POST /anchor/render-context`
- `POST /anchor/ack-response`

## Proof (Current Benchmarks)

From real EC2 behavioral runs:
- Compact strict delta: `+0.6667`
- Reset strict delta: `+0.6667`
- Compact/reset semantic delta: `+0.8889`

See evidence:
- `reports/openclaw_remote_behavioral_matrix.json`
- `reports/openclaw_remote_behavioral_compact_ab_results.json`
- `reports/openclaw_remote_behavioral_reset_ab_results.json`

## Adoption Path

1. **Evaluate locally**
   - run unit tests and local API
2. **Validate on remote OpenClaw**
   - run behavioral matrix on EC2
3. **Harden operations**
   - enable API security + tenant scoping + retry worker
4. **Gate releases**
   - run quality suites + stability loop + nightly gate

Key commands:
- Matrix: `scripts/run_openclaw_remote_behavioral_matrix.py`
- Stability: `scripts/run_openclaw_remote_stability_loop.py`
- Nightly gate: `scripts/run_openclaw_remote_nightly_gate.py`

## OpenClaw Integration

Default integration scaffold:
- `assets/openclaw-continuity-plugin/index.ts`
- `assets/openclaw-continuity-plugin/openclaw.plugin.json`
- `assets/openclaw-continuity-plugin/openclaw.yaml.example`

Setup guide:
- `assets/openclaw-continuity-plugin/README.md`

## Repository Map

- `src/continuity_memory/` - core implementation
- `scripts/` - runners and gate tooling
- `reports/` - generated benchmark evidence
- `mvp/data/` - benchmark datasets
- `docs/` - spec, design, structure, SLO runbooks

Start here in docs:
- `docs/README.md`
- `docs/SPEC.md`
- `docs/TECHNICAL_DESIGN.md`
- `docs/PROJECT_STRUCTURE.md`
- `docs/SLO_ALERTING.md`

## Project Status

Status: active development, P0 hardening delivered.

Near-term focus:
- broader quality datasets
- stronger production rollout playbooks
- tighter SLO and alert automation

## Contributing

Issues and PRs are welcome.

If you want to contribute, start with:
1. `docs/SPEC.md` for acceptance goals
2. `docs/TECHNICAL_DESIGN.md` for architecture constraints
3. `docs/SLO_ALERTING.md` for operational expectations
