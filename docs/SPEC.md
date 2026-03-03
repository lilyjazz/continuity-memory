# SPEC v0.2 - OpenClaw Compaction-Safe Conversation Continuity

## 1) Problem
In long conversations, context compaction can drop critical information and cause memory loss, off-topic answers, or contradictions with prior decisions.

> The goal is not just to answer "what is the progress". The goal is: after compaction, users can ask any follow-up question and still get context-consistent answers.

---

## 2) Objective
Build a **Conversation Continuity Anchor (CCA)** mechanism that:
- Preserves high-value context before and after compaction
- Restores continuity context before answering
- Maintains stable answer quality across question types

---

## 3) Direct Evidence
Real user sessions showed a pattern:
- Conversation is coherent before compaction
- Compaction runs
- User asks a same-topic follow-up
- System answers as if previous context was forgotten

Evidence image: `./assets/context-compaction-evidence.jpg`

---

## 4) Scope
### In Scope (P0)
1. Define and version the CCA data model
2. Auto-generate/refresh CCA before compaction
3. Recover and inject CCA before answer generation
4. Prioritize continuity for arbitrary follow-up questions
5. Graceful degradation when anchor is missing/corrupted

### Out of Scope (P0)
1. Full long-term memory governance platform
2. General vector retrieval platform redesign
3. Full enterprise RBAC/SSO/audit suite
4. Multi-modal fact extraction

---

## 5) CCA Data Model
Each anchor contains:
- `conversation_id`
- `anchor_version`
- `timestamp`
- `turn_range`
- `summary_compact` (2-5 sentence compressed summary)

### Layer A - State
- `goal`
- `done[]`
- `in_progress[]`
- `blockers[]`
- `next_steps[]`
- `decisions[]`

### Layer B - Facts
- `entities[]` (people, projects, systems, terms)
- `constraints[]` (must/must-not)
- `confirmed_facts[]`
- `open_questions[]`

### Layer C - Intent / Dialogue Thread
- `current_intent`
- `user_ask_history[]`
- `assistant_commitments[]`
- `topic_stack[]`

### Reliability Meta
- `confidence`
- `source_refs[]`
- `checksum`

---

## 6) Trigger and Lifecycle
1. **Periodic**: refresh every 8-12 turns
2. **Threshold**: force refresh near compaction token threshold
3. **Event-based**: refresh on topic shift, confirmed decision, or commitment
4. **Compaction-hook**: latest CCA must be written before compaction

Retention strategy:
- Keep last N versions (recommended N=5)
- Keep latest in hot path

---

## 7) Read/Answer Flow
1. Receive user question (any type)
2. Load latest CCA (prefer local cache/store)
3. Align question intent with CCA
4. Inject continuity context block into prompt
5. Return answer and record drift/consistency outcome

Degradation:
- No CCA: fallback to recent summary + key recent turns
- Still insufficient: explicitly state context is limited and ask actionable rebuilding questions

---

## 8) Storage Modes
- `local`: local persistence (development)
- `hybrid`: local + TiDB cloud copy (production recommendation)

TiDB in P0 is a cross-instance continuity safety layer, not a full memory-platform replacement.

Current implementation notes:
- `local` uses JSON version files (`FileAnchorStore`)
- `hybrid` uses `FileAnchorStore + TiDBZeroRemoteBackend`
- Failed remote writes enter a persisted `pending_retry` queue and are recovered by worker/`flush_retry`

P0 security and operations notes:
- `/anchor/*` supports token auth, tenant-prefix scope checks, and rate limiting (configurable)
- `/metrics` and `/alerts/slo` endpoints are available for operations (admin when security enabled)
- OpenClaw plugin supports startup probe, circuit breaker, and fast bypass switch

---

## 9) Acceptance Metrics (P0)
### Continuity
1. **Continuity Success Rate** >= 95%
2. **Context Drift Rate** <= 5%
3. **Contradiction Rate** <= 2%

### Reliability
4. Pre-compaction CCA write success >= 99%
5. With valid CCA, "I don't remember"-style responses = 0

### Performance
6. Additional p95 latency from continuity recovery <= 1s
7. Timeout fallback returns a usable response within 20s

---

## 10) Test Plan (Required Coverage)
1. **Compaction Replay**: replay real incidents and verify continuity on arbitrary follow-up questions
2. **Question Diversity**: state/fact/constraint/follow-up mix
3. **Topic Shift Stress**: multiple topic switches and old-topic recall checks
4. **Contradiction Check**: inject conflicting old facts and verify consistency behavior
5. **Latency Under Load**: evaluate recovery latency under concurrent traffic

Current executable assets:
- `scripts/run_openclaw_remote_behavioral_ab.py` (real `/compact`)
- `scripts/run_openclaw_remote_behavioral_reset_ab.py` (real `/reset`)
- `scripts/run_openclaw_remote_behavioral_matrix.py` (compact + reset matrix)
- `scripts/run_openclaw_remote_stability_loop.py` (stability rounds)
- `scripts/run_openclaw_remote_nightly_gate.py` (quality gate)
- `mvp/data/ab_cases_quality.jsonl` (extended quality dataset)

Evaluation modes:
- strict: exact token matching
- semantic: semantic variant matching (numeric/unit aliases + multilingual tokens)

---

## 11) Milestones
### Week 1
- CCA schema + generator + local persistence
- basic compaction hook

### Week 2
- continuity answer path for arbitrary questions
- replay test set (including real incident samples)

### Week 3
- hybrid mode (TiDB)
- metrics collection and dashboards

### Week 4
- canary validation + Go/No-Go

---

## 12) Go/No-Go Rule
Move to P1 only if all conditions are met:
1. Continuity Success Rate >= 95%
2. Contradiction Rate <= 2%
3. Additional p95 latency <= 1s
4. At least 3 real replay groups pass

Current engineering gate additions (nightly):
- compact strict delta >= 0.20
- reset strict delta >= 0.20
- compact semantic delta >= 0.30
- reset semantic delta >= 0.30
- stability pass rate = 1.0

If any gate fails, do not expand scope; fix continuity quality first.

---

## 13) Multi-Role Self-Review (Condensed)
### CEO View
- User value is obvious (reduced "memory loss" experience)
- Story is demoable (before/after compaction comparison)
- Decision: Go, with strict P0 scope discipline

### CTO View
- Complexity: medium (hooks + schema + injection)
- Risks: extraction quality and latency
- Mitigation: versioned anchors + strict metric gates

### CPO View
- Core user benefit is clear: continuity trust
- Scope control required: avoid expanding P0 into a full memory platform

### GTM View
- External one-liner: **"Context compressed, continuity preserved."**
- Launch assets: real incident replay and before/after evidence

---

## 14) FAQ
### Q1: Is this mainly a retrieval problem?
Not primarily. The core issue is continuity context loss after compaction.

### Q2: Why not support only progress-style questions?
Because users ask arbitrary follow-ups; the target is broad continuity, not one query type.

### Q3: Is TiDB mandatory?
Not for P0. Hybrid mode is recommended in production for cross-instance recovery.

### Q4: How do we prove effectiveness?
Use continuity/contradiction/latency metrics, not subjective impressions.

### Q5: What comes after P0?
Typed memory governance, stronger conflict resolution, and lifecycle management.
