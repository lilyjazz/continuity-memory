from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnchorState:
    goal: str = ""
    done: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)


@dataclass
class AnchorFacts:
    entities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    confirmed_facts: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


@dataclass
class AnchorIntent:
    current_intent: str = ""
    user_ask_history: list[str] = field(default_factory=list)
    assistant_commitments: list[str] = field(default_factory=list)
    topic_stack: list[str] = field(default_factory=list)


@dataclass
class AnchorMeta:
    confidence: float = 0.0
    source_refs: list[int] = field(default_factory=list)
    checksum: str = ""


@dataclass
class ContinuityAnchor:
    conversation_id: str
    anchor_version: int
    timestamp: float
    turn_range: tuple[int, int]
    summary_compact: str
    state: AnchorState = field(default_factory=AnchorState)
    facts: AnchorFacts = field(default_factory=AnchorFacts)
    intent: AnchorIntent = field(default_factory=AnchorIntent)
    meta: AnchorMeta = field(default_factory=AnchorMeta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "anchor_version": self.anchor_version,
            "timestamp": self.timestamp,
            "turn_range": [self.turn_range[0], self.turn_range[1]],
            "summary_compact": self.summary_compact,
            "state": {
                "goal": self.state.goal,
                "done": self.state.done,
                "in_progress": self.state.in_progress,
                "blockers": self.state.blockers,
                "next_steps": self.state.next_steps,
                "decisions": self.state.decisions,
            },
            "facts": {
                "entities": self.facts.entities,
                "constraints": self.facts.constraints,
                "confirmed_facts": self.facts.confirmed_facts,
                "open_questions": self.facts.open_questions,
            },
            "intent": {
                "current_intent": self.intent.current_intent,
                "user_ask_history": self.intent.user_ask_history,
                "assistant_commitments": self.intent.assistant_commitments,
                "topic_stack": self.intent.topic_stack,
            },
            "meta": {
                "confidence": self.meta.confidence,
                "source_refs": self.meta.source_refs,
                "checksum": self.meta.checksum,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContinuityAnchor":
        turn_range = data.get("turn_range", [0, 0])
        state_data = data.get("state", {})
        facts_data = data.get("facts", {})
        intent_data = data.get("intent", {})
        meta_data = data.get("meta", {})
        return cls(
            conversation_id=data.get("conversation_id", ""),
            anchor_version=int(data.get("anchor_version", 1)),
            timestamp=float(data.get("timestamp", 0.0)),
            turn_range=(int(turn_range[0]), int(turn_range[1])),
            summary_compact=data.get("summary_compact", ""),
            state=AnchorState(
                goal=state_data.get("goal", ""),
                done=list(state_data.get("done", [])),
                in_progress=list(state_data.get("in_progress", [])),
                blockers=list(state_data.get("blockers", [])),
                next_steps=list(state_data.get("next_steps", [])),
                decisions=list(state_data.get("decisions", [])),
            ),
            facts=AnchorFacts(
                entities=list(facts_data.get("entities", [])),
                constraints=list(facts_data.get("constraints", [])),
                confirmed_facts=list(facts_data.get("confirmed_facts", [])),
                open_questions=list(facts_data.get("open_questions", [])),
            ),
            intent=AnchorIntent(
                current_intent=intent_data.get("current_intent", ""),
                user_ask_history=list(intent_data.get("user_ask_history", [])),
                assistant_commitments=list(intent_data.get("assistant_commitments", [])),
                topic_stack=list(intent_data.get("topic_stack", [])),
            ),
            meta=AnchorMeta(
                confidence=float(meta_data.get("confidence", 0.0)),
                source_refs=[int(v) for v in meta_data.get("source_refs", [])],
                checksum=meta_data.get("checksum", ""),
            ),
        )
