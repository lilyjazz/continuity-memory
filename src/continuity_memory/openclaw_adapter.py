from __future__ import annotations

import json
import shlex
import subprocess
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from .hooks import ContinuityHooks
from .service import ContinuityService, UpdateResult


def _extract_text(raw_output: str) -> str:
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(raw_output)
    data = json.loads(raw_output[start : end + 1])
    payloads = data.get("result", {}).get("payloads", [])
    lines = [item.get("text", "") for item in payloads if item.get("text")]
    return "\n".join(lines).strip()


class Gateway(Protocol):
    def ask(self, session_id: str, message: str) -> str:
        raise NotImplementedError


@dataclass
class OpenClawCliGateway:
    binary: str = "openclaw"

    def ask(self, session_id: str, message: str) -> str:
        command = [
            self.binary,
            "agent",
            "--session-id",
            session_id,
            "--message",
            message,
            "--json",
        ]
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return _extract_text(proc.stdout)


@dataclass
class RemoteOpenClawGateway:
    ssh_host: str
    ssh_user: str
    ssh_key_path: str
    openclaw_path: str = "openclaw"
    ssh_timeout_seconds: int = 120
    retry_attempts: int = 4
    retry_backoff_seconds: float = 1.5

    @staticmethod
    def _is_retryable_ssh_error(message: str) -> bool:
        lower = message.lower()
        markers = (
            "can't assign requested address",
            "connection reset",
            "connection timed out",
            "connection closed",
            "broken pipe",
            "resource temporarily unavailable",
            "operation timed out",
        )
        return any(marker in lower for marker in markers)

    def ask(self, session_id: str, message: str) -> str:
        remote_command = (
            f"export PATH=/home/{self.ssh_user}/.npm-global/bin:$PATH && "
            f"{self.openclaw_path} agent --session-id {shlex.quote(session_id)} "
            f"--message {shlex.quote(message)} --json"
        )
        cmd = [
            "ssh",
            "-i",
            self.ssh_key_path,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=10",
            f"{self.ssh_user}@{self.ssh_host}",
            remote_command,
        ]
        last_error: RuntimeError | None = None
        for attempt in range(1, max(1, self.retry_attempts) + 1):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.ssh_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                last_error = RuntimeError(str(exc))
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_backoff_seconds * attempt)
                    continue
                raise last_error

            if proc.returncode == 0:
                return _extract_text(proc.stdout)

            message_out = proc.stderr or proc.stdout
            error = RuntimeError(message_out)
            if attempt < self.retry_attempts and self._is_retryable_ssh_error(message_out):
                last_error = error
                time.sleep(self.retry_backoff_seconds * attempt)
                continue
            raise error

        raise last_error or RuntimeError("Remote OpenClaw gateway failed without details")


@dataclass
class MockOpenClawGateway:
    response_template: str = "Mock answer based on continuity context."

    def ask(self, session_id: str, message: str) -> str:
        _ = session_id
        lower = message.lower()
        if "constraint" in lower:
            return "The constraint is latency must stay under 1 second."
        if "goal" in lower:
            return "The goal is to ship P0 continuity module."
        if "decision" in lower:
            return "The decision is no fork OpenClaw."
        return self.response_template


@dataclass
class AdapterResponse:
    session_id: str
    answer: str
    continuity_context_block: str
    degraded: bool
    anchor_version_used: int | None
    anchor_version_after_ack: int


@dataclass
class OpenClawContinuityAdapter:
    service: ContinuityService
    gateway: Gateway
    session_prefix: str = "continuity"
    hooks: ContinuityHooks = field(init=False)
    _session_ids: dict[str, str] = field(default_factory=dict)
    _turns: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def __post_init__(self) -> None:
        self.hooks = ContinuityHooks(self.service)

    def bind_session(self, conversation_id: str, session_id: str) -> None:
        self._session_ids[conversation_id] = session_id

    def session_id_for(self, conversation_id: str) -> str:
        existing = self._session_ids.get(conversation_id)
        if existing is not None:
            return existing
        session_id = f"{self.session_prefix}-{conversation_id}-{uuid.uuid4().hex[:8]}"
        self._session_ids[conversation_id] = session_id
        return session_id

    def add_turn(self, conversation_id: str, turn: str) -> None:
        self._turns[conversation_id].append(turn)

    def prepare_for_compaction(self, conversation_id: str) -> UpdateResult:
        turns = self._turns.get(conversation_id, [])
        return self.hooks.before_compaction(conversation_id, turns)

    def ask(self, conversation_id: str, user_query: str) -> AdapterResponse:
        session_id = self.session_id_for(conversation_id)
        prepared = self.hooks.before_response(conversation_id, user_query)
        prompt = (
            f"{prepared.continuity_context_block}\n\n"
            f"[User Query]\n{user_query}\n\n"
            "Respond using continuity-first reasoning."
        )
        answer = self.gateway.ask(session_id, prompt)

        self._turns[conversation_id].append(f"user:{user_query}")
        self._turns[conversation_id].append(f"assistant:{answer}")
        ack = self.hooks.after_response(
            conversation_id=conversation_id,
            response_text=answer,
            turn_id=len(self._turns[conversation_id]),
        )

        return AdapterResponse(
            session_id=session_id,
            answer=answer,
            continuity_context_block=prepared.continuity_context_block,
            degraded=prepared.degraded,
            anchor_version_used=prepared.anchor_version,
            anchor_version_after_ack=ack.anchor_version,
        )
