from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api_security import ApiSecurityConfig, AuthContext, RateLimiter
from .service import ContinuityService, SLOPolicy
from .storage import AnchorCorruptedError, AnchorNotFoundError


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _as_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        out.append(item)
    return out


def build_api_server(
    service: ContinuityService,
    host: str = "127.0.0.1",
    port: int = 8080,
    security: ApiSecurityConfig | None = None,
    slo_policy: SLOPolicy | None = None,
) -> ThreadingHTTPServer:
    sec = security or ApiSecurityConfig()
    limiter = RateLimiter(limit=max(1, sec.rate_limit_per_minute))
    policy = slo_policy or SLOPolicy()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > sec.max_body_bytes:
                raise ValueError("body_too_large")
            if content_length <= 0:
                return {}
            raw = self.rfile.read(content_length)
            return json.loads(raw.decode("utf-8"))

        @staticmethod
        def _conversation_scoped(conversation_id: str, tenant: str) -> bool:
            return conversation_id.startswith(f"{tenant}:")

        @staticmethod
        def _is_loopback_ip(client_ip: str) -> bool:
            return client_ip in ("127.0.0.1", "::1", "localhost")

        def _authenticate(self) -> AuthContext | None:
            if not sec.enabled:
                return AuthContext(token="", tenant="default", is_admin=True)

            client_ip = self.client_address[0] if self.client_address else ""
            auth_header = self.headers.get("Authorization", "")

            if not auth_header:
                if self._is_loopback_ip(client_ip) and not sec.require_auth_for_loopback:
                    return AuthContext(token="", tenant="default", is_admin=True)
                self._send_json(401, {"error": "authentication_required"})
                return None

            if not auth_header.startswith("Bearer "):
                self._send_json(401, {"error": "invalid_authorization_header"})
                return None

            token = auth_header.split(" ", 1)[1].strip()
            tenant_claim = sec.tokens.get(token)
            if tenant_claim is None:
                self._send_json(401, {"error": "invalid_token"})
                return None

            tenant_header = self.headers.get(sec.tenant_header_name, "").strip()
            effective_tenant = tenant_header or tenant_claim
            if tenant_claim != "*" and effective_tenant != tenant_claim:
                self._send_json(403, {"error": "tenant_mismatch"})
                return None
            if not effective_tenant:
                self._send_json(400, {"error": "tenant_required"})
                return None

            key = f"{effective_tenant}:{token}"
            if not limiter.allow(key):
                self._send_json(429, {"error": "rate_limit_exceeded"})
                return None

            return AuthContext(token=token, tenant=effective_tenant, is_admin=token in sec.admin_tokens)

        def _require_admin(self, auth: AuthContext) -> bool:
            if not sec.enabled:
                return True
            if auth.is_admin:
                return True
            self._send_json(403, {"error": "admin_required"})
            return False

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            if parsed.path == "/health":
                self._send_json(200, {"ok": True})
                return

            auth = self._authenticate()
            if auth is None:
                return

            if parsed.path == "/metrics":
                if not self._require_admin(auth):
                    return
                self._send_json(200, {"metrics": asdict(service.metrics_snapshot())})
                return

            if parsed.path == "/alerts/slo":
                if not self._require_admin(auth):
                    return
                self._send_json(200, {"alerts": service.evaluate_slo(policy)})
                return

            if parsed.path != "/anchor/latest":
                self._send_json(404, {"error": "not_found"})
                return

            params = parse_qs(parsed.query)
            conversation_id = params.get("conversation_id", [""])[0].strip()
            if not conversation_id:
                self._send_json(400, {"error": "conversation_id_required"})
                return
            if sec.enabled and not self._conversation_scoped(conversation_id, auth.tenant):
                self._send_json(403, {"error": "conversation_scope_forbidden"})
                return

            try:
                anchor = service.get_latest(conversation_id)
            except AnchorNotFoundError:
                self._send_json(404, {"error": "anchor_not_found"})
                return
            except AnchorCorruptedError:
                self._send_json(409, {"error": "anchor_corrupted"})
                return

            self._send_json(200, {"anchor": anchor.to_dict()})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            auth = self._authenticate()
            if auth is None:
                return
            try:
                body = self._read_json()
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
                return
            except ValueError as exc:
                if str(exc) == "body_too_large":
                    self._send_json(413, {"error": "body_too_large"})
                    return
                self._send_json(400, {"error": "invalid_request"})
                return

            if parsed.path == "/anchor/update":
                self._handle_update(body, auth)
                return

            if parsed.path == "/anchor/render-context":
                self._handle_render_context(body, auth)
                return

            if parsed.path == "/anchor/ack-response":
                self._handle_ack_response(body, auth)
                return

            self._send_json(404, {"error": "not_found"})

        def _handle_update(self, body: dict[str, Any], auth: AuthContext) -> None:
            conversation_id = str(body.get("conversation_id", "")).strip()
            latest_turns = _as_string_list(body.get("latest_turns"))
            if not conversation_id or latest_turns is None:
                self._send_json(400, {"error": "conversation_id_and_latest_turns_required"})
                return
            if sec.enabled and not self._conversation_scoped(conversation_id, auth.tenant):
                self._send_json(403, {"error": "conversation_scope_forbidden"})
                return

            optional_event_raw = body.get("optional_event")
            optional_event = str(optional_event_raw) if optional_event_raw is not None else None

            result = service.update_anchor(
                conversation_id=conversation_id,
                latest_turns=latest_turns,
                optional_event=optional_event,
                force=bool(body.get("force", False)),
                token_near_threshold=bool(body.get("token_near_threshold", False)),
            )
            self._send_json(
                200,
                {
                    "anchor_version": result.anchor_version,
                    "confidence": result.confidence,
                    "degraded": result.degraded,
                },
            )

        def _handle_render_context(self, body: dict[str, Any], auth: AuthContext) -> None:
            conversation_id = str(body.get("conversation_id", "")).strip()
            user_query = str(body.get("user_query", "")).strip()
            if not conversation_id or not user_query:
                self._send_json(400, {"error": "conversation_id_and_user_query_required"})
                return
            if sec.enabled and not self._conversation_scoped(conversation_id, auth.tenant):
                self._send_json(403, {"error": "conversation_scope_forbidden"})
                return

            result = service.render_context(conversation_id, user_query)
            self._send_json(
                200,
                {
                    "continuity_context_block": result.context_block,
                    "degraded": result.degraded,
                    "anchor_version": result.anchor_version,
                },
            )

        def _handle_ack_response(self, body: dict[str, Any], auth: AuthContext) -> None:
            conversation_id = str(body.get("conversation_id", "")).strip()
            response_text = str(body.get("response_text", "")).strip()
            turn_id_raw = body.get("turn_id")
            if not conversation_id or not response_text or not isinstance(turn_id_raw, int):
                self._send_json(400, {"error": "conversation_id_response_text_turn_id_required"})
                return
            if sec.enabled and not self._conversation_scoped(conversation_id, auth.tenant):
                self._send_json(403, {"error": "conversation_scope_forbidden"})
                return

            result = service.ack_response(
                conversation_id=conversation_id,
                response_text=response_text,
                turn_id=turn_id_raw,
            )
            self._send_json(
                200,
                {
                    "anchor_version": result.anchor_version,
                    "confidence": result.confidence,
                    "degraded": result.degraded,
                },
            )

        def log_message(self, format: str, *args: object) -> None:
            _ = format
            _ = args

    return ThreadingHTTPServer((host, port), Handler)
