from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from .context import render_continuity_context, render_degrade_context
from .extractor import build_anchor
from .models import ContinuityAnchor
from .storage import AnchorCorruptedError, AnchorNotFoundError, AnchorStore


@dataclass
class ServiceConfig:
    refresh_interval_turns: int = 10
    keep_versions: int = 5
    read_timeout_seconds: float = 20.0


@dataclass
class UpdateResult:
    anchor_version: int
    confidence: float
    degraded: bool


@dataclass
class QueryContextResult:
    context_block: str
    degraded: bool
    anchor_version: int | None


@dataclass
class ServiceMetrics:
    continuity_success_rate: float = 0.0
    context_drift_rate: float = 0.0
    contradiction_rate: float = 0.0
    anchor_write_success_rate: float = 0.0
    anchor_read_latency_p95_ms: float = 0.0
    degrade_path_rate: float = 0.0


@dataclass
class SLOPolicy:
    min_continuity_success_rate: float = 0.95
    max_context_drift_rate: float = 0.05
    max_contradiction_rate: float = 0.02
    min_anchor_write_success_rate: float = 0.99
    max_anchor_read_latency_p95_ms: float = 1000.0
    max_degrade_path_rate: float = 0.05


@dataclass
class ContinuityService:
    store: AnchorStore
    config: ServiceConfig = field(default_factory=ServiceConfig)
    _read_latencies_ms: list[float] = field(default_factory=list)
    _write_attempts: int = 0
    _write_success: int = 0
    _read_degrade_count: int = 0
    _read_total: int = 0
    _answer_stats: dict[str, list[bool]] = field(default_factory=lambda: defaultdict(list))
    _last_turn_index: dict[str, int] = field(default_factory=dict)
    _recent_turns: dict[str, list[str]] = field(default_factory=dict)

    def _safe_previous(self, conversation_id: str) -> ContinuityAnchor | None:
        getter = getattr(self.store, "get_previous", None)
        if getter is None:
            return None
        previous = getter(conversation_id)
        if previous is None:
            return None
        return previous

    def _next_version(self, conversation_id: str) -> tuple[int, ContinuityAnchor | None]:
        try:
            latest = self.store.get_latest(conversation_id)
            return latest.anchor_version + 1, latest
        except AnchorCorruptedError:
            previous = self._safe_previous(conversation_id)
            if previous is not None:
                return previous.anchor_version + 1, previous
            return 1, None
        except AnchorNotFoundError:
            return 1, None

    def update_anchor(
        self,
        conversation_id: str,
        latest_turns: list[str],
        optional_event: str | None = None,
        force: bool = False,
        token_near_threshold: bool = False,
    ) -> UpdateResult:
        self._write_attempts += 1
        turns = [t for t in latest_turns if t.strip()]
        self._recent_turns[conversation_id] = turns[-20:]

        should_refresh = force or token_near_threshold
        if optional_event:
            event = optional_event.lower()
            if any(k in event for k in ("topic", "decision", "commitment", "conclusion")):
                should_refresh = True

        prev_index = self._last_turn_index.get(conversation_id, 0)
        current_index = prev_index + len(turns)
        if current_index - prev_index >= self.config.refresh_interval_turns:
            should_refresh = True

        if not should_refresh:
            latest, prev = self._next_version(conversation_id)
            version = (prev.anchor_version if prev is not None else latest)
            confidence = (prev.meta.confidence if prev is not None else 0.0)
            return UpdateResult(anchor_version=version, confidence=confidence, degraded=False)

        next_version, previous = self._next_version(conversation_id)
        source_refs = list(range(max(1, current_index - len(turns) + 1), current_index + 1))
        anchor = build_anchor(
            conversation_id=conversation_id,
            turns=turns,
            source_turn_refs=source_refs,
            anchor_version=next_version,
            previous=previous,
            timestamp=time.time(),
        )
        self.store.put(anchor)
        self._write_success += 1
        self._last_turn_index[conversation_id] = current_index
        return UpdateResult(anchor_version=anchor.anchor_version, confidence=anchor.meta.confidence, degraded=False)

    def get_latest(self, conversation_id: str) -> ContinuityAnchor:
        return self.store.get_latest(conversation_id)

    def render_context(self, conversation_id: str, user_query: str) -> QueryContextResult:
        _ = user_query
        t0 = time.time()
        self._read_total += 1
        try:
            anchor = self.store.get_latest(conversation_id)
            context = render_continuity_context(anchor)
            latency = (time.time() - t0) * 1000.0
            self._read_latencies_ms.append(latency)
            return QueryContextResult(context_block=context, degraded=False, anchor_version=anchor.anchor_version)
        except (AnchorNotFoundError, AnchorCorruptedError):
            previous = self._safe_previous(conversation_id)
            if previous is not None:
                latency = (time.time() - t0) * 1000.0
                self._read_latencies_ms.append(latency)
                return QueryContextResult(
                    context_block=render_continuity_context(previous),
                    degraded=False,
                    anchor_version=previous.anchor_version,
                )
            self._read_degrade_count += 1
            latency = (time.time() - t0) * 1000.0
            self._read_latencies_ms.append(latency)
            recent = self._recent_turns.get(conversation_id, [])
            return QueryContextResult(
                context_block=render_degrade_context(recent),
                degraded=True,
                anchor_version=None,
            )

    def ack_response(self, conversation_id: str, response_text: str, turn_id: int) -> UpdateResult:
        turns = self._recent_turns.get(conversation_id, [])
        merged = turns + [f"assistant-response:{response_text}"]
        self._last_turn_index[conversation_id] = max(self._last_turn_index.get(conversation_id, 0), turn_id)
        return self.update_anchor(
            conversation_id=conversation_id,
            latest_turns=merged[-20:],
            optional_event="commitment",
            force=True,
        )

    def record_answer_outcome(
        self,
        conversation_id: str,
        success: bool,
        drifted: bool,
        contradicted: bool,
    ) -> None:
        stats = self._answer_stats[conversation_id]
        stats.extend([success, not drifted, not contradicted])

    def metrics_snapshot(self) -> ServiceMetrics:
        successes: list[bool] = []
        not_drift: list[bool] = []
        not_contra: list[bool] = []
        for values in self._answer_stats.values():
            for idx, value in enumerate(values):
                if idx % 3 == 0:
                    successes.append(value)
                elif idx % 3 == 1:
                    not_drift.append(value)
                else:
                    not_contra.append(value)

        continuity_success_rate = (sum(successes) / len(successes)) if successes else 0.0
        context_drift_rate = (1.0 - (sum(not_drift) / len(not_drift))) if not_drift else 0.0
        contradiction_rate = (1.0 - (sum(not_contra) / len(not_contra))) if not_contra else 0.0

        anchor_write_success_rate = (
            (self._write_success / self._write_attempts) if self._write_attempts else 0.0
        )

        sorted_latencies = sorted(self._read_latencies_ms)
        if sorted_latencies:
            idx = min(len(sorted_latencies) - 1, int(round((len(sorted_latencies) - 1) * 0.95)))
            p95 = sorted_latencies[idx]
        else:
            p95 = 0.0

        degrade_path_rate = (
            (self._read_degrade_count / self._read_total) if self._read_total else 0.0
        )

        return ServiceMetrics(
            continuity_success_rate=continuity_success_rate,
            context_drift_rate=context_drift_rate,
            contradiction_rate=contradiction_rate,
            anchor_write_success_rate=anchor_write_success_rate,
            anchor_read_latency_p95_ms=p95,
            degrade_path_rate=degrade_path_rate,
        )

    def evaluate_slo(self, policy: SLOPolicy | None = None) -> dict[str, object]:
        active = policy or SLOPolicy()
        metrics = self.metrics_snapshot()
        checks = {
            "continuity_success_rate": {
                "ok": metrics.continuity_success_rate >= active.min_continuity_success_rate,
                "actual": metrics.continuity_success_rate,
                "min": active.min_continuity_success_rate,
            },
            "context_drift_rate": {
                "ok": metrics.context_drift_rate <= active.max_context_drift_rate,
                "actual": metrics.context_drift_rate,
                "max": active.max_context_drift_rate,
            },
            "contradiction_rate": {
                "ok": metrics.contradiction_rate <= active.max_contradiction_rate,
                "actual": metrics.contradiction_rate,
                "max": active.max_contradiction_rate,
            },
            "anchor_write_success_rate": {
                "ok": metrics.anchor_write_success_rate >= active.min_anchor_write_success_rate,
                "actual": metrics.anchor_write_success_rate,
                "min": active.min_anchor_write_success_rate,
            },
            "anchor_read_latency_p95_ms": {
                "ok": metrics.anchor_read_latency_p95_ms <= active.max_anchor_read_latency_p95_ms,
                "actual": metrics.anchor_read_latency_p95_ms,
                "max": active.max_anchor_read_latency_p95_ms,
            },
            "degrade_path_rate": {
                "ok": metrics.degrade_path_rate <= active.max_degrade_path_rate,
                "actual": metrics.degrade_path_rate,
                "max": active.max_degrade_path_rate,
            },
        }
        overall_ok = all(item["ok"] for item in checks.values())
        return {
            "overall_ok": overall_ok,
            "checks": checks,
        }
