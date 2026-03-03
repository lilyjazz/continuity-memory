import json
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from continuity_memory.http_api import ApiSecurityConfig, build_api_server  # noqa: E402
from continuity_memory.service import ContinuityService, SLOPolicy, ServiceConfig  # noqa: E402
from continuity_memory.storage import FileAnchorStore  # noqa: E402


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        store = FileAnchorStore(root=Path(self.tempdir.name) / "anchors", keep_versions=5)
        self.service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=1))
        self.server = build_api_server(self.service, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        addr = self.server.server_address
        host, port = str(addr[0]), int(addr[1])
        self.conn = HTTPConnection(host, port, timeout=5)

    def tearDown(self) -> None:
        self.conn.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        self.conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data

    def _post_with_headers(self, path: str, payload: dict, headers: dict[str, str]) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        merged = {"Content-Type": "application/json", **headers}
        self.conn.request("POST", path, body=body, headers=merged)
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data

    def _get(self, path: str) -> tuple[int, dict]:
        self.conn.request("GET", path)
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data

    def _get_with_headers(self, path: str, headers: dict[str, str]) -> tuple[int, dict]:
        self.conn.request("GET", path, headers=headers)
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data

    def test_health_endpoint(self) -> None:
        status, data = self._get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_anchor_update_render_ack_latest_flow(self) -> None:
        status, update = self._post(
            "/anchor/update",
            {
                "conversation_id": "conv-http",
                "latest_turns": [
                    "Goal: serve continuity over HTTP",
                    "Decision: use hybrid mode",
                    "Constraint: latency under control",
                ],
                "force": True,
                "optional_event": "decision",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(update["anchor_version"], 1)

        status, rendered = self._post(
            "/anchor/render-context",
            {
                "conversation_id": "conv-http",
                "user_query": "What is our constraint?",
            },
        )
        self.assertEqual(status, 200)
        self.assertFalse(rendered["degraded"])
        self.assertIn("Conversation Continuity Context", rendered["continuity_context_block"])

        status, ack = self._post(
            "/anchor/ack-response",
            {
                "conversation_id": "conv-http",
                "response_text": "Constraint is latency under control.",
                "turn_id": 5,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(ack["anchor_version"], 2)

        status, latest = self._get("/anchor/latest?conversation_id=conv-http")
        self.assertEqual(status, 200)
        self.assertEqual(latest["anchor"]["anchor_version"], 2)

    def test_degrade_render_when_missing_anchor(self) -> None:
        status, rendered = self._post(
            "/anchor/render-context",
            {
                "conversation_id": "unknown",
                "user_query": "hello",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(rendered["degraded"])
        self.assertIn("上下文不足", rendered["continuity_context_block"])

    def test_validation_errors(self) -> None:
        status, _ = self._post("/anchor/update", {"conversation_id": "x"})
        self.assertEqual(status, 400)

        status, _ = self._post("/anchor/ack-response", {"conversation_id": "x", "response_text": "ok"})
        self.assertEqual(status, 400)

        status, _ = self._get("/anchor/latest")
        self.assertEqual(status, 400)


class HttpApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        store = FileAnchorStore(root=Path(self.tempdir.name) / "anchors", keep_versions=5)
        self.service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=1))
        security = ApiSecurityConfig(
            enabled=True,
            tokens={"token-a": "default"},
            admin_tokens={"token-a"},
            rate_limit_per_minute=2,
            require_auth_for_loopback=True,
        )
        self.server = build_api_server(
            self.service,
            host="127.0.0.1",
            port=0,
            security=security,
            slo_policy=SLOPolicy(max_anchor_read_latency_p95_ms=999999),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        addr = self.server.server_address
        host, port = str(addr[0]), int(addr[1])
        self.conn = HTTPConnection(host, port, timeout=5)

    def tearDown(self) -> None:
        self.conn.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer token-a",
            "X-Tenant-Id": "default",
        }

    def test_requires_authentication(self) -> None:
        self.conn.request("POST", "/anchor/render-context", body=b"{}", headers={"Content-Type": "application/json"})
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 401)
        self.assertEqual(data["error"], "authentication_required")

    def test_rejects_conversation_scope_mismatch(self) -> None:
        body = {
            "conversation_id": "other:conv-1",
            "latest_turns": ["Goal: x"],
            "force": True,
        }
        merged = {"Content-Type": "application/json", **self._headers()}
        self.conn.request("POST", "/anchor/update", body=json.dumps(body).encode("utf-8"), headers=merged)
        response = self.conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 403)
        self.assertEqual(data["error"], "conversation_scope_forbidden")

    def test_rate_limit_blocks_excess_calls(self) -> None:
        headers = self._headers()
        for _ in range(2):
            self.conn.request("GET", "/anchor/latest?conversation_id=default:unknown", headers=headers)
            response = self.conn.getresponse()
            _ = response.read()
            self.assertIn(response.status, (404, 409))

        self.conn.request("GET", "/anchor/latest?conversation_id=default:unknown", headers=headers)
        limited = self.conn.getresponse()
        payload = json.loads(limited.read().decode("utf-8"))
        self.assertEqual(limited.status, 429)
        self.assertEqual(payload["error"], "rate_limit_exceeded")

    def test_metrics_and_slo_alerts_admin_endpoints(self) -> None:
        headers = self._headers()
        self.conn.request("GET", "/metrics", headers=headers)
        metrics_res = self.conn.getresponse()
        metrics = json.loads(metrics_res.read().decode("utf-8"))
        self.assertEqual(metrics_res.status, 200)
        self.assertIn("metrics", metrics)

        self.conn.request("GET", "/alerts/slo", headers=headers)
        alerts_res = self.conn.getresponse()
        alerts = json.loads(alerts_res.read().decode("utf-8"))
        self.assertEqual(alerts_res.status, 200)
        self.assertIn("alerts", alerts)


if __name__ == "__main__":
    unittest.main()
