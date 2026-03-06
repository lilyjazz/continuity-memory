#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TENANT_ID="${TENANT_ID:-default}"
API_TOKEN="${API_TOKEN:-}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8080}"

if [[ -z "$API_TOKEN" ]]; then
  API_TOKEN="continuity-$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)"
  echo "[install] API_TOKEN not provided; generated ephemeral token"
fi

OPENCLAW_HOME="${HOME}/.openclaw"
EXT_DIR="${OPENCLAW_HOME}/extensions/continuity-anchor"
CONFIG_JSON="${OPENCLAW_HOME}/openclaw.json"

echo "[install] repo root: ${REPO_ROOT}"
echo "[install] openclaw home: ${OPENCLAW_HOME}"
echo "[install] installing plugin files..."
mkdir -p "${EXT_DIR}"
cp "${REPO_ROOT}/assets/openclaw-continuity-plugin/index.ts" "${EXT_DIR}/index.ts"
cp "${REPO_ROOT}/assets/openclaw-continuity-plugin/openclaw.plugin.json" "${EXT_DIR}/openclaw.plugin.json"

mkdir -p "${OPENCLAW_HOME}"
if [[ ! -f "${CONFIG_JSON}" ]]; then
  echo '{}' > "${CONFIG_JSON}"
fi

echo "[install] patching ${CONFIG_JSON}"
python3 - <<PY
import json
from pathlib import Path

config_path = Path(${CONFIG_JSON@Q})
data = json.loads(config_path.read_text(encoding="utf-8"))

plugins = data.setdefault("plugins", {})
load = plugins.setdefault("load", {})
paths = load.setdefault("paths", [])
ext_root = str(Path(${OPENCLAW_HOME@Q}) / "extensions")
if ext_root not in paths:
    paths.append(ext_root)

entries = plugins.setdefault("entries", {})
entries["continuity-anchor"] = {
    "enabled": True,
    "config": {
        "enabled": True,
        "bypassContinuity": False,
        "tenantId": ${TENANT_ID@Q},
        "apiToken": ${API_TOKEN@Q},
        "apiBaseUrl": f"http://{${API_HOST@Q}}:{${API_PORT@Q}}",
        "requestTimeoutMs": 1500,
        "conversationPrefix": "cca-",
        "updateOnCompaction": True,
        "updateOnReset": True,
        "startupProbeAttempts": 8,
        "startupProbeDelayMs": 500,
        "healthPath": "/health",
        "circuitBreakerFailureThreshold": 5,
        "circuitBreakerCooldownMs": 30000,
        "autoStartApi": False
    }
}

slots = plugins.setdefault("slots", {})
slots["memory"] = "continuity-anchor"

config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
PY

SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SYSTEMD_USER_DIR}/continuity-anchor-api.service"
mkdir -p "${SYSTEMD_USER_DIR}"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Continuity Memory Anchor API
After=network.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
ExecStart=/usr/bin/env python3 scripts/run_anchor_api.py --host ${API_HOST} --port ${API_PORT} --mode local --retry-worker-enabled --retry-worker-interval 2.0 --api-security-enabled --api-token ${API_TOKEN}:${TENANT_ID} --api-admin-token ${API_TOKEN}
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

if command -v systemctl >/dev/null 2>&1; then
  echo "[install] enabling user service continuity-anchor-api.service"
  systemctl --user daemon-reload || true
  systemctl --user enable --now continuity-anchor-api.service || true
fi

echo "[install] validating API health"
sleep 1
if curl -fsS "http://${API_HOST}:${API_PORT}/health" >/dev/null; then
  echo "[ok] continuity anchor API healthy at http://${API_HOST}:${API_PORT}/health"
else
  echo "[warn] health check failed; start manually:"
  echo "python3 scripts/run_anchor_api.py --host ${API_HOST} --port ${API_PORT} --mode local"
fi

echo "[next] restart OpenClaw and run a cross-session compact/reset check"
echo "[info] token=${API_TOKEN} tenant=${TENANT_ID}"
