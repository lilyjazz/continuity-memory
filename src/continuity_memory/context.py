from __future__ import annotations

from .models import ContinuityAnchor


def render_continuity_context(anchor: ContinuityAnchor) -> str:
    done = "; ".join(anchor.state.done[-3:]) or "N/A"
    in_progress = "; ".join(anchor.state.in_progress[-3:]) or "N/A"
    blockers = "; ".join(anchor.state.blockers[-3:]) or "N/A"
    next_steps = "; ".join(anchor.state.next_steps[-3:]) or "N/A"
    confirmed = "; ".join(anchor.facts.confirmed_facts[-4:]) or "N/A"
    constraints = "; ".join(anchor.facts.constraints[-4:]) or "N/A"
    intent = anchor.intent.current_intent or "maintain continuity"

    return "\n".join(
        [
            "[Conversation Continuity Context]",
            f"Current Goal: {anchor.state.goal or 'N/A'}",
            f"Done: {done}",
            f"In Progress: {in_progress}",
            f"Blockers: {blockers}",
            f"Next Steps: {next_steps}",
            f"Confirmed Facts: {confirmed}",
            f"Current Intent: {intent}",
            f"Constraints: {constraints}",
            f"Anchor Version: {anchor.anchor_version}",
        ]
    )


def render_degrade_context(recent_turns: list[str]) -> str:
    if not recent_turns:
        return "上下文不足，正在重建。请确认当前目标、约束和最近决策。"

    tail = " | ".join([t.strip() for t in recent_turns[-3:] if t.strip()])
    return (
        "上下文不足，正在重建。"
        "请先确认以下信息是否正确："
        f" {tail}"
    )
