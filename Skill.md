# Continuity Memory Local Install + Smoke Test Skill

This document is written for OpenClaw (or another coding agent) to autonomously install and run a first local validation of this project.

## Objective

Set up the project on a local machine and complete an initial smoke test that proves:

1. Unit tests pass.
2. Anchor API starts successfully.
3. `/anchor/update` -> `/anchor/render-context` -> `/anchor/ack-response` works end-to-end.

---

## Preconditions

- macOS/Linux shell
- `python3` available (3.10+ recommended)
- `git` available
- optional: `openclaw` CLI if you also want plugin-level integration smoke

---

## Step-by-Step Execution

Run these commands in order from repo root.

### 1) Clone and enter repo

```bash
git clone https://github.com/lilyjazz/continuity-memory.git
cd continuity-memory
```

### 2) Create virtual environment and install minimal dependencies

Before installing, do a local pre-check to avoid unnecessary downloads.

```bash
if [ -x ./.venv/bin/python ]; then
  echo "[precheck] existing virtualenv found"
else
  echo "[precheck] creating virtualenv"
  python3 -m venv .venv
fi

if ./.venv/bin/python -c "import pymysql" 2>/dev/null; then
  echo "[precheck] pymysql already installed"
else
  echo "[precheck] installing pymysql"
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install pymysql
fi
```

Equivalent always-safe install commands (idempotent) are below:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install pymysql
```

### 3) Run full unit tests

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass (current baseline is 38 tests).

### 4) Start anchor API (local mode)

```bash
./.venv/bin/python scripts/run_anchor_api.py --host 127.0.0.1 --port 8080 --mode local
```

Keep this process running in terminal A.

### 5) In terminal B, run API smoke test

#### 5.1 Update anchor

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

#### 5.2 Render continuity context

```bash
curl -sS -X POST http://127.0.0.1:8080/anchor/render-context \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "default:local-smoke-001",
    "user_query": "What did we decide?"
  }'
```

#### 5.3 Ack response

```bash
curl -sS -X POST http://127.0.0.1:8080/anchor/ack-response \
  -H 'Content-Type: application/json' \
  -d '{
    "conversation_id": "default:local-smoke-001",
    "response_text": "We decided to use local mode first.",
    "turn_id": 1
  }'
```

#### 5.4 Read latest anchor

```bash
curl -sS "http://127.0.0.1:8080/anchor/latest?conversation_id=default:local-smoke-001"
```

Expected: valid JSON responses, increasing `anchor_version`, and non-empty continuity context block.

---

## Optional: OpenClaw Plugin Smoke Test

If OpenClaw is installed locally, use:

- `assets/openclaw-continuity-plugin/openclaw.plugin.json`
- `assets/openclaw-continuity-plugin/openclaw.yaml.example`
- `assets/openclaw-continuity-plugin/README.md`

Then run one conversation, execute `/compact` or `/reset`, and verify follow-up answers keep earlier facts.

---

## Failure Recovery Checklist

If something fails, check in this order:

1. Python path and venv usage (`./.venv/bin/python`)
2. API process is still running on `127.0.0.1:8080`
3. JSON payload uses `conversation_id` with tenant prefix (`default:`)
4. Re-run unit tests before retrying smoke requests

---

## Copy-Paste Prompt for OpenClaw

Use the following prompt directly in OpenClaw:

```text
You are executing the Continuity Memory local install skill.

Goal:
1) set up the repo locally,
2) run unit tests,
3) start anchor API,
4) run /anchor/update -> /anchor/render-context -> /anchor/ack-response -> /anchor/latest smoke flow,
5) report exact command outputs and whether smoke test passed.

Constraints:
- Always run a dependency pre-check before install/download steps.
- Do not ask for confirmation unless blocked by missing system dependencies.
- Use the exact commands from Skill.md.
- If a command fails, fix the root cause and retry.
- At the end, return a concise checklist with pass/fail for each step.

Acceptance:
- Unit tests pass.
- API endpoints return valid JSON.
- Anchor version is created and readable from /anchor/latest.
```

---

## Deliverable Format (for agent output)

When OpenClaw finishes, it should return:

1. Environment summary (`python3 --version`, repo path)
2. Test result summary
3. API startup confirmation
4. Smoke API response summary per endpoint
5. Final PASS/FAIL verdict

Required test status block (must be included verbatim in structure):

```text
Testing Status
- Unit tests: PASS/FAIL (include command and total passed count)
- API startup: PASS/FAIL (include host:port)
- /anchor/update: PASS/FAIL
- /anchor/render-context: PASS/FAIL
- /anchor/ack-response: PASS/FAIL
- /anchor/latest: PASS/FAIL
- Overall local smoke: PASS/FAIL
```

If any line is FAIL, the agent must include:
1. root cause,
2. fix applied,
3. re-test result.

After the checklist, the agent must print this user-facing confirmation message in chat:

```text
Setup complete. Continuity Memory has been installed and validated locally, and continuity protection is now active.
From now on, session reset and compact operations will no longer cause context loss in normal usage.
```
