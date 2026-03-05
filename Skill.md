# Continuity Memory Local Install + Smoke Skill (No Unit-Test Path)

This skill is for OpenClaw (or another coding agent) to autonomously install and run a **minimal local smoke validation**.

## Objective

Complete a local setup that proves:
1. Anchor API starts.
2. `/anchor/update` works.
3. `/anchor/render-context` works.
4. `/anchor/ack-response` works.
5. `/anchor/latest` returns the anchor.

This skill intentionally avoids unit-test execution to reduce setup blockers.

---

## Preconditions

- macOS/Linux shell
- `python3` available
- `git` available

---

## Step-by-Step Execution

Run commands from repository root.

### 1) Clone and enter repo

```bash
git clone https://github.com/lilyjazz/continuity-memory.git
cd continuity-memory
```

### 2) Prepare Python runtime (minimal dependency path)

Use venv if available. If venv is unavailable, use system Python directly.

```bash
if python3 -m venv .venv 2>/dev/null; then
  PY=./.venv/bin/python
  echo "[runtime] using venv: $PY"
else
  PY=python3
  echo "[runtime] venv unavailable, using system python: $PY"
fi
```

No extra package installation is required for local smoke mode.

### 3) Start anchor API (terminal A)

```bash
$PY scripts/run_anchor_api.py --host 127.0.0.1 --port 8080 --mode local
```

Keep terminal A running.

### 4) Run smoke flow (terminal B)

#### 4.1 `/anchor/update`

```bash
curl -sS -X POST http://127.0.0.1:8080/anchor/update \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "default:local-smoke-001",
    "latest_turns": [
      "Goal: validate local install",
      "Decision: use local mode first"
    ],
    "force": true
  }'
```

#### 4.2 `/anchor/render-context`

```bash
curl -sS -X POST http://127.0.0.1:8080/anchor/render-context \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "default:local-smoke-001",
    "user_query": "What did we decide?"
  }'
```

#### 4.3 `/anchor/ack-response`

```bash
curl -sS -X POST http://127.0.0.1:8080/anchor/ack-response \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "default:local-smoke-001",
    "response_text": "We decided to use local mode first.",
    "turn_id": 1
  }'
```

#### 4.4 `/anchor/latest`

```bash
curl -sS "http://127.0.0.1:8080/anchor/latest?conversation_id=default:local-smoke-001"
```

Expected: valid JSON responses, and `anchor_version` is present/readable.

---

## Failure Recovery

### A) `python3 -m venv .venv` fails (`ensurepip is unavailable`)

Use the no-venv path in this skill (`PY=python3`) and continue.

If you want to fix venv support anyway (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
sudo apt-get install -y python3.12-venv || true
```

### B) API does not start

Check:
1. Python command used (`$PY`)
2. Port already in use (`127.0.0.1:8080`)
3. Run from repo root

### C) Endpoint returns error

Check:
1. API process still running
2. JSON payload format
3. `conversation_id` includes tenant prefix (`default:`)

---

## Copy-Paste Prompt for OpenClaw

```text
You are executing Continuity Memory local install + smoke skill.

Goal:
1) setup local runtime with minimal dependencies,
2) start anchor API,
3) run /anchor/update -> /anchor/render-context -> /anchor/ack-response -> /anchor/latest,
4) report endpoint-level PASS/FAIL and final verdict.

Constraints:
- Do not run unit tests in this flow.
- Prefer zero extra downloads; use system python fallback if venv support is missing.
- If a step fails, fix the root cause and retry.

Acceptance:
- API is running.
- All four endpoint calls return valid JSON.
- latest anchor is readable.
```

---

## Deliverable Format (Required)

Return this block:

```text
Smoke Status
- API startup: PASS/FAIL
- /anchor/update: PASS/FAIL
- /anchor/render-context: PASS/FAIL
- /anchor/ack-response: PASS/FAIL
- /anchor/latest: PASS/FAIL
- Overall local smoke: PASS/FAIL
```

If any item is FAIL, include:
1. root cause,
2. fix applied,
3. re-test result.

After the checklist, print:

```text
Setup complete. Continuity Memory has been installed and validated locally, and continuity protection is now active.
From now on, session reset and compact operations will no longer cause context loss in normal usage.
```
