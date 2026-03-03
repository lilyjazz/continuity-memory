# SLO and Alerting Policy (P0)

This document defines production-facing SLO checks and alert conditions for continuity-memory.

## Runtime Endpoints

- `GET /metrics` (admin only when API security is enabled)
- `GET /alerts/slo` (admin only when API security is enabled)

Both endpoints are served by `src/continuity_memory/http_api.py` and use `ContinuityService.metrics_snapshot()` and `ContinuityService.evaluate_slo()`.

## P0 SLO Thresholds

- `continuity_success_rate >= 0.95`
- `context_drift_rate <= 0.05`
- `contradiction_rate <= 0.02`
- `anchor_write_success_rate >= 0.99`
- `anchor_read_latency_p95_ms <= 1000`
- `degrade_path_rate <= 0.05`

## Alert Rules

Trigger warning/critical alerts when any SLO check returns `ok=false` from `/alerts/slo`.

Recommended initial routing:

- Warning: one failed check for more than 5 minutes
- Critical: two or more failed checks for more than 5 minutes

## Failure Handling Flows (Top 5)

### 1) Authentication failures spike (`401`)

Trigger:
- `authentication_required` or `invalid_token` increases sharply

Flow:
1. Verify `run_anchor_api.py` token mapping (`--api-token token:tenant`) matches plugin `apiToken`.
2. Check if loopback auth policy changed (`--api-require-auth-loopback`).
3. Confirm request headers contain `Authorization: Bearer <token>`.
4. Rotate token if leakage is suspected, then update plugin config.

Exit criteria:
- `401` rate returns to baseline and `/metrics` read succeeds.

### 2) Tenant scope rejects (`403`)

Trigger:
- `tenant_mismatch` or `conversation_scope_forbidden` appears

Flow:
1. Verify plugin `tenantId` and API `X-Tenant-Id` alignment.
2. Ensure `conversation_id` format is `tenant:conversation`.
3. Confirm token claim tenant matches header tenant.
4. Re-run one compact/reset smoke case with corrected tenant scope.

Exit criteria:
- No new tenant mismatch errors for 10+ minutes.

### 3) Remote write failures increase

Trigger:
- `anchor_write_success_rate` drops

Flow:
1. Check TiDB connectivity/credential health.
2. Inspect `pending_retry` queue growth in hybrid store state.
3. Keep service online (local write is primary path).
4. Recover remote dependency and run `flush_retry` (or wait worker cycle).

Exit criteria:
- Retry queue starts draining and write success recovers.

### 4) Retry queue backlog keeps growing

Trigger:
- queue depth and oldest item age increase together

Flow:
1. Verify retry worker is enabled (`--retry-worker-enabled`).
2. Check worker interval and process liveness.
3. Validate remote error type (transient vs permanent config failure).
4. If permanent failure, fix config first then trigger drain.

Exit criteria:
- backlog trend turns downward and oldest age stabilizes.

### 5) Degrade path rate rises

Trigger:
- `degrade_path_rate` exceeds SLO threshold

Flow:
1. Inspect anchor read path failures (local latest, previous, remote fallback).
2. Check corruption frequency and checksum mismatches.
3. Validate tenant scope and auth are not blocking valid reads.
4. Run quality benchmark suites and compare strict/semantic deltas.

Exit criteria:
- `degrade_path_rate` returns below threshold and benchmark deltas remain positive.

## Operational Guidance

1. If `anchor_write_success_rate` drops:
   - Inspect hybrid retry queue depth (`pending_retry`) and remote backend status.
2. If `degrade_path_rate` rises:
   - Inspect anchor read failures and conversation scope/auth rejects.
3. If `anchor_read_latency_p95_ms` rises:
   - Check local disk health and TiDB fallback path latency.
4. If `context_drift_rate` or `contradiction_rate` rises:
   - Run quality benchmark suites and compare strict/semantic deltas.

## Benchmark Gate Alignment

Use offline gate scripts as release safety checks:

- `scripts/run_openclaw_remote_behavioral_matrix.py`
- `scripts/run_openclaw_remote_stability_loop.py`
- `scripts/run_openclaw_remote_nightly_gate.py`

Online SLOs and offline benchmark gates must both pass before production rollout.
