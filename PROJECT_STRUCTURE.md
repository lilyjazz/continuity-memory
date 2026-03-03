# Project Structure

This document is the code-centric map of continuity-memory.

## Top Level

- `src/continuity_memory/` — product code
- `tests/` — unit and integration tests
- `scripts/` — local/remote runners and gate tools
- `mvp/data/` — benchmark datasets
- `reports/` — generated run outputs
- `assets/openclaw-continuity-plugin/` — OpenClaw plugin scaffold

## Core Package (`src/continuity_memory`)

- `models.py`
  - Dataclasses for continuity anchor (`state`, `facts`, `intent`, `meta`)
  - Dict serialization/deserialization
- `extractor.py`
  - Turn extraction and anchor merge logic
  - checksum generation
- `context.py`
  - continuity/degrade context rendering
- `service.py`
  - business orchestration (`update_anchor`, `render_context`, `ack_response`)
  - runtime metrics snapshot and SLO evaluation
- `api_security.py`
  - API security configuration
  - auth context and rate limiter primitives
- `http_api.py`
  - REST endpoint routing and validation
  - security enforcement and admin observability endpoints
- `storage.py`
  - file anchor store
  - hybrid store with durable retry queue and background flush worker
- `tidb_zero.py`
  - TiDB Zero remote backend implementation
- `openclaw_adapter.py`
  - local/remote/mock OpenClaw gateway adapters
- `benchmark_cases.py`
  - benchmark case reinforcement and preflight coverage checks
- `evaluator.py`
  - strict + semantic scoring

## Runtime Call Flow

### 1) Request Path (normal ask)

```text
OpenClaw Plugin (before_agent_start)
  -> HTTP API (/anchor/update, /anchor/render-context)
    -> ContinuityService
      -> AnchorStore (Hybrid or Local)
        -> Local file store (primary)
        -> Remote backend fallback (TiDB Zero)
  -> OpenClaw model invocation with continuity block
  -> HTTP API (/anchor/ack-response)
    -> ContinuityService
      -> AnchorStore.put()
```

### 2) Storage Path (hybrid write)

```text
ContinuityService.update_anchor()
  -> HybridAnchorStore.put(anchor)
    -> local.put(anchor)                # must succeed first
    -> remote.put(anchor)               # best effort
      -> success: done
      -> failure: enqueue pending_retry + persist queue file
```

### 3) Recovery Path (retry worker)

```text
retry worker loop (interval)
  -> HybridAnchorStore.flush_retry()
    -> iterate pending_retry
      -> remote.put(anchor)
        -> success: remove from queue
        -> failure: keep in queue
    -> persist queue snapshot
```

### 4) Security and Tenant Scope

```text
HTTP request
  -> ApiSecurityConfig gate
    -> Bearer token validation
    -> tenant resolution (header/token)
    -> rate limiter check
    -> conversation scope check (tenant:conversation)
  -> route handler
```

### 5) Observability Path

```text
ContinuityService internal counters/latencies
  -> /metrics (runtime snapshot)
  -> /alerts/slo (SLO policy evaluation)
  -> benchmark reports (offline strict/semantic deltas)
```

## Failure Handling Call Flows

### A) Auth failure (`401`)

```text
Plugin/API caller
  -> HTTP API auth gate
    -> token missing/invalid
      -> 401
      -> check token mapping and Authorization header
      -> retry with corrected token
```

### B) Tenant scope failure (`403`)

```text
Plugin/API caller
  -> HTTP API tenant gate
    -> tenant header/token mismatch OR conversation outside tenant scope
      -> 403
      -> align tenantId + conversation_id prefix (tenant:...)
```

### C) Hybrid remote write failure

```text
HybridAnchorStore.put(anchor)
  -> local.put(anchor) success
  -> remote.put(anchor) failure
    -> enqueue pending_retry
    -> persist retry queue
  -> request still succeeds on local durability
```

### D) Retry backlog recovery

```text
retry worker tick
  -> flush_retry()
    -> remote.put(anchor)
      -> success: dequeue
      -> failure: keep queued
  -> persist queue snapshot
```

### E) Degrade path activation

```text
render_context()
  -> local latest read fails
  -> local previous read fails
  -> remote fallback read fails
  -> return degrade context block
  -> monitor degrade_path_rate and trigger runbook
```

## Script Roles (`scripts`)

- `run_anchor_api.py` — start anchor HTTP API (local/hybrid, security, retry worker)
- `run_openclaw_remote_behavioral_ab.py` — `/compact` benchmark
- `run_openclaw_remote_behavioral_reset_ab.py` — `/reset` benchmark
- `run_openclaw_remote_behavioral_matrix.py` — compact + reset combined run
- `run_openclaw_remote_stability_loop.py` — repeated rounds for stability
- `run_openclaw_remote_nightly_gate.py` — threshold gate over quality/stability runs

## Plugin Scaffold (`assets/openclaw-continuity-plugin`)

- `index.ts` — hook integration and operability controls
- `openclaw.plugin.json` — plugin schema and UI hints
- `openclaw.yaml.example` — production-style config example
- `README.md` — install and integration guide
