from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import AnchorFacts, AnchorIntent, AnchorMeta, AnchorState, ContinuityAnchor


@dataclass
class ExtractResult:
    state: AnchorState
    facts: AnchorFacts
    intent: AnchorIntent
    summary: str
    confidence: float


_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_-]{2,}\b")
_QUESTION_RE = re.compile(r"\?$|\b(what|why|how|when|where|which|是否|怎么|什么)\b", re.IGNORECASE)


def _append_unique(target: list[str], value: str) -> None:
    text = value.strip()
    if text and text not in target:
        target.append(text)


def _merge_unique(base: list[str], new_values: list[str]) -> list[str]:
    out = list(base)
    for value in new_values:
        _append_unique(out, value)
    return out


def extract_anchor_fields(turns: list[str]) -> ExtractResult:
    state = AnchorState()
    facts = AnchorFacts()
    intent = AnchorIntent()
    summary_lines: list[str] = []

    for idx, turn in enumerate(turns):
        text = turn.strip()
        if not text:
            continue
        lower = text.lower()

        if lower.startswith("goal:"):
            state.goal = text.split(":", 1)[1].strip()
        elif lower.startswith("done:"):
            _append_unique(state.done, text.split(":", 1)[1].strip())
        elif lower.startswith("in progress:"):
            _append_unique(state.in_progress, text.split(":", 1)[1].strip())
        elif lower.startswith("blocker:") or lower.startswith("blockers:"):
            _append_unique(state.blockers, text.split(":", 1)[1].strip())
        elif lower.startswith("next:") or lower.startswith("next step:"):
            _append_unique(state.next_steps, text.split(":", 1)[1].strip())
        elif lower.startswith("decision:"):
            _append_unique(state.decisions, text.split(":", 1)[1].strip())
            _append_unique(intent.topic_stack, "decision")

        if lower.startswith("constraint:") or "must" in lower or "cannot" in lower or "不能" in lower:
            _append_unique(facts.constraints, text)

        if lower.startswith("fact:") or lower.startswith("critical rule") or lower.startswith("hard timeout"):
            _append_unique(facts.confirmed_facts, text)

        if lower.startswith("open question:"):
            _append_unique(facts.open_questions, text.split(":", 1)[1].strip())

        if _QUESTION_RE.search(text):
            _append_unique(intent.user_ask_history, text)

        if lower.startswith("commitment:") or lower.startswith("action:"):
            _append_unique(intent.assistant_commitments, text)

        for entity in _ENTITY_RE.findall(text):
            _append_unique(facts.entities, entity)

        if idx >= max(0, len(turns) - 5):
            summary_lines.append(text)

    if not intent.current_intent:
        if state.next_steps:
            intent.current_intent = f"deliver {state.next_steps[-1]}"
        elif state.goal:
            intent.current_intent = f"advance goal: {state.goal}"
        else:
            intent.current_intent = "maintain continuity"

    summary = " | ".join(summary_lines[:5])[:600]
    density = sum(
        len(v)
        for v in (
            state.done,
            state.in_progress,
            state.blockers,
            state.next_steps,
            state.decisions,
            facts.confirmed_facts,
            facts.constraints,
        )
    )
    confidence = min(1.0, 0.35 + density / 40.0)

    return ExtractResult(
        state=state,
        facts=facts,
        intent=intent,
        summary=summary,
        confidence=round(confidence, 3),
    )


def compute_checksum(anchor: ContinuityAnchor) -> str:
    payload = anchor.to_dict()
    payload["meta"] = {**payload["meta"], "checksum": ""}
    digest = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_anchor(
    conversation_id: str,
    turns: list[str],
    source_turn_refs: list[int],
    anchor_version: int,
    previous: ContinuityAnchor | None,
    timestamp: float,
) -> ContinuityAnchor:
    extraction = extract_anchor_fields(turns)

    if previous is not None:
        extraction.state.done = _merge_unique(previous.state.done, extraction.state.done)
        extraction.state.in_progress = _merge_unique(previous.state.in_progress, extraction.state.in_progress)
        extraction.state.blockers = _merge_unique(previous.state.blockers, extraction.state.blockers)
        extraction.state.next_steps = _merge_unique(previous.state.next_steps, extraction.state.next_steps)
        extraction.state.decisions = _merge_unique(previous.state.decisions, extraction.state.decisions)
        extraction.facts.entities = _merge_unique(previous.facts.entities, extraction.facts.entities)
        extraction.facts.constraints = _merge_unique(previous.facts.constraints, extraction.facts.constraints)
        extraction.facts.confirmed_facts = _merge_unique(previous.facts.confirmed_facts, extraction.facts.confirmed_facts)
        extraction.facts.open_questions = _merge_unique(previous.facts.open_questions, extraction.facts.open_questions)
        extraction.intent.user_ask_history = _merge_unique(previous.intent.user_ask_history, extraction.intent.user_ask_history)[-12:]
        extraction.intent.assistant_commitments = _merge_unique(
            previous.intent.assistant_commitments,
            extraction.intent.assistant_commitments,
        )[-12:]
        extraction.intent.topic_stack = _merge_unique(previous.intent.topic_stack, extraction.intent.topic_stack)[-10:]

        if not extraction.state.goal:
            extraction.state.goal = previous.state.goal

    turn_range = (source_turn_refs[0] if source_turn_refs else 0, source_turn_refs[-1] if source_turn_refs else 0)
    anchor = ContinuityAnchor(
        conversation_id=conversation_id,
        anchor_version=anchor_version,
        timestamp=timestamp,
        turn_range=turn_range,
        summary_compact=extraction.summary,
        state=extraction.state,
        facts=extraction.facts,
        intent=extraction.intent,
        meta=AnchorMeta(confidence=extraction.confidence, source_refs=source_turn_refs, checksum=""),
    )
    anchor.meta.checksum = compute_checksum(anchor)
    return anchor
