# Technical Design v0.1 - Phase A (No-Fork) Conversation Continuity Anchor

## 0. Purpose
This document defines the P0/P0.5 **Phase A minimal viable architecture**:
preserve conversation continuity after context compaction without modifying OpenClaw core logic.

---

## 1. Design Goals
1. **Continuity-first**: preserve context coherence for arbitrary follow-up questions
2. **No-fork first**: avoid OpenClaw core forks for baseline adoption
3. **Low latency**: keep additional p95 latency controlled (target <= 1s)
4. **Progressive architecture**: smooth path from local-only to hybrid mode

---

## 2. Non-Goals (Phase A)
1. Rebuilding OpenClaw compaction internals
2. Building a full long-term memory governance platform
3. Introducing enterprise-wide RBAC/SSO as part of P0
4. Multi-modal fact extraction

---

## 3. System Boundaries

### 3.1 OpenClaw Boundary (External System)
OpenClaw continues to own:
- session lifecycle
- context compaction and model execution
- tool orchestration

Phase A does not alter OpenClaw compaction algorithms.

### 3.2 Continuity Module Boundary (This Project)
This project adds a continuity coordination layer responsible for:
- generating/updating Continuity Anchors
- recovering and injecting continuity context before model calls
- acknowledging responses and incrementally updating anchors
- collecting continuity metrics and SLO checks

In short: OpenClaw remains the dialogue engine; continuity-memory provides continuity safeguards.

---

## 4. Deployment Modes

### 4.1 Local Mode
- Anchors persisted as local JSON versions (`FileAnchorStore`)
- Best for single-instance development and fast iteration

### 4.2 Hybrid Mode (Production Recommendation)
- Local file store is the primary low-latency path
- TiDB Zero acts as remote replica/fallback
- Read path: local latest -> local previous -> remote fallback
- Write path: local first; remote failure enters persisted retry queue

### 4.3 OpenClaw Plugin Mode (No-Fork Integration)
- Integrates with OpenClaw lifecycle hooks:
  - `before_agent_start`
  - `before_compaction`
  - `before_reset`
  - `agent_end`
- Calls continuity API endpoints:
  - `/anchor/update`
  - `/anchor/render-context`
  - `/anchor/ack-response`

Plugin scaffold location: `assets/openclaw-continuity-plugin/`.

---

## 5. Data Model (Phase A)

```json
{
  "conversation_id": "tenant:conversation",
  "anchor_version": 12,
  "timestamp": 1772510437.0,
  "turn_range": [120, 145],
  "summary_compact": "concise continuity summary",
  "state": {
    "goal": "...",
    "done": ["..."],
    "in_progress": ["..."],
    "blockers": ["..."],
    "next_steps": ["..."],
    "decisions": ["..."]
  },
  "facts": {
    "entities": ["..."],
    "confirmed_facts": ["..."],
    "constraints": ["..."],
    "open_questions": ["..."]
  },
  "intent": {
    "current_intent": "...",
    "topic_stack": ["..."],
    "assistant_commitments": ["..."],
    "recent_user_asks": ["..."]
  },
  "meta": {
    "confidence": 0.87,
    "source_refs": [132, 135, 141],
    "checksum": "sha256:..."
  }
}
```

---

## 6. Core Logic

### 6.1 Write Path (Anchor Update)
Current triggers:
1. periodic refresh (default every 10 turns)
2. key events (`topic`, `decision`, `commitment`, `conclusion`)
3. forced refresh before compaction/reset
4. forced refresh after response acknowledgment

Processing:
1. take latest turn window (up to 20 turns)
2. extract structured state/facts/intent
3. merge with previous anchor state
4. compute next version + checksum
5. write local store
6. in hybrid mode, attempt remote write; enqueue persisted retry on failure

### 6.2 Read Path (Pre-Response Recovery)
1. load latest anchor (local latest -> local previous -> remote)
2. build continuity context block
3. inject with current user query
4. if all reads fail, return degrade context block

### 6.3 Response Path
1. model answers with continuity context
2. response acknowledgment triggers incremental anchor update
3. service updates continuity metrics

### 6.4 Sequence - Normal Ask (Plugin + API)

```text
User -> OpenClaw Agent: ask(query)
OpenClaw Agent -> Plugin(before_agent_start)
Plugin -> Anchor API: /anchor/update (optional)
Plugin -> Anchor API: /anchor/render-context
Anchor API -> ContinuityService -> Store chain
Store chain -> ContinuityService -> Anchor API -> Plugin
Plugin -> OpenClaw Agent: prepend continuity context
OpenClaw Agent -> Model -> answer
OpenClaw Agent -> Plugin(agent_end)
Plugin -> Anchor API: /anchor/ack-response
Anchor API -> ContinuityService -> Store.put
```

### 6.5 Sequence - `/compact`

```text
User -> OpenClaw: /compact
OpenClaw -> Plugin(before_compaction)
Plugin -> Anchor API: /anchor/update (force=true)
Service -> Hybrid store write (local first, remote best effort)
OpenClaw executes compaction with fresh persisted anchor state
```

### 6.6 Sequence - `/reset`

```text
User -> OpenClaw: /reset
OpenClaw -> Plugin(before_reset)
Plugin -> Anchor API: /anchor/update (force=true)
OpenClaw clears session history
Next ask -> Plugin(before_agent_start) -> /anchor/render-context
Recovered anchor context is injected into post-reset prompt
```

### 6.7 Sequence - Degrade/Fallback

```text
/anchor/render-context
  -> local latest fails
  -> local previous fails
  -> remote fallback fails
  -> service returns degrade context block
  -> plugin keeps request fail-open
```

---

## 7. Continuity Context Block Template

```text
[Conversation Continuity Context]
Current Goal: ...
Done: ...
In Progress: ...
Blockers: ...
Next Steps: ...
Confirmed Facts: ...
Current Intent: ...
Constraints: ...
```

Injection rules:
- keep it concise and high signal
- preserve factual consistency and intent continuity
- avoid over-injecting raw historical text

---

## 8. Failure Handling and Degrade

### 8.1 Anchor Missing
- fallback to recent summary and key turns
- return actionable context-rebuild guidance

### 8.2 Anchor Corrupted
- fallback to previous valid anchor version
- trigger rebuild path

### 8.3 Hybrid Remote Write Failure
- local success does not block answer path
- failed items are persisted in retry queue
- retry worker + `flush_retry` drain queue after dependency recovery

### 8.4 Read Timeout
- `read_timeout_seconds` exists in service config
- strict timeout enforcement across all storage calls is a follow-up optimization

---

## 9. Performance Design
1. local-first read/write path for low latency
2. compact anchor payloads
3. incremental updates to avoid full recomputation per turn
4. non-blocking remote failure handling via retry queue

Validation additions in current implementation:
- regular EC2 compact/reset behavioral matrix execution
- quality dataset + stability loop + nightly gate scripts

Target:
- additional continuity overhead p95 <= 1s

---

## 10. Observability

Core metrics:
- `continuity_success_rate`
- `context_drift_rate`
- `contradiction_rate`
- `anchor_write_success_rate`
- `anchor_read_latency_p95_ms`
- `degrade_path_rate`

### 10.1 Runtime Observability Sequence

```text
ask -> before_agent_start -> /anchor/update (optional) -> /anchor/render-context
-> model answer -> /anchor/ack-response
```

At each stage:
- emit structured event and latency
- update success/degrade/retry counters

### 10.2 Stage-to-Metric Mapping
1. render stage: read latency, degrade path rate
2. update stage: write success rate, continuity availability
3. answer/ack stage: drift and contradiction rates
4. retry stage: queue depth and flush success trend

### 10.3 Offline Validation Signals
Generated by benchmark scripts under `scripts/` and written to `reports/`:
- strict delta (`delta` / `delta_strict`)
- semantic delta (`delta_semantic`)
- elapsed duration (`elapsed_sec`)
- stability pass and p95 elapsed

### 10.4 Logging Contract (Recommended)
Log these fields for each API/hook event:
- `event`
- `conversation_id`
- `anchor_version_before` / `anchor_version_after`
- `latency_ms`
- `path` (`local_latest|local_previous|remote_fallback|degrade`)
- `outcome` (`ok|retry_enqueued|degrade|error`)

---

## 11. API Contract (Internal)

### `POST /anchor/update`
Input: `conversation_id`, `latest_turns`, optional event flags
Output: `anchor_version`, `confidence`, `degraded`

### `GET /anchor/latest?conversation_id=...`
Output: latest anchor payload

### `POST /anchor/render-context`
Input: `conversation_id`, `user_query`
Output: `continuity_context_block`, `degraded`, `anchor_version`

### `POST /anchor/ack-response`
Input: `conversation_id`, `response_text`, `turn_id`
Output: updated anchor version metadata

### `GET /metrics`
Output: runtime metric snapshot (admin in secure mode)

### `GET /alerts/slo`
Output: SLO evaluation result (admin in secure mode)

---

## 12. Security and Data Boundary
- local mode keeps data on-host
- hybrid mode can upload structured anchor data only (configurable)
- `/anchor/*` enforces token auth + tenant scope + rate limiting
- `conversation_id` uses `tenant:conversation` scoping
- remote traffic uses encrypted transport and managed credentials

---

## 13. Phase Plan
### A1
- local mode complete
- end-to-end update/read/render/ack path

### A2
- replay harness
- metrics collection

### A3
- TiDB hybrid mode
- retry and fallback hardening

### A4
- canary validation + Go/No-Go

---

## 14. Acceptance Criteria
1. continuity success after compaction >= 95%
2. contradiction rate <= 2%
3. memory-loss style response rate with valid anchor = 0
4. additional p95 latency <= 1s
5. at least 3 real replay groups pass

---

## 15. Why This Is Non-Intrusive
1. no OpenClaw compaction-core changes
2. no mandatory OpenClaw fork requirement
3. continuity context injection is layered externally
4. architecture is pluggable, canaried, and switchable

Future stronger consistency can be proposed upstream via standard lifecycle hooks.
