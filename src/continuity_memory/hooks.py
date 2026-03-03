from __future__ import annotations

from dataclasses import dataclass

from .service import ContinuityService, QueryContextResult, UpdateResult


@dataclass
class PreparedPrompt:
    user_query: str
    continuity_context_block: str
    degraded: bool
    anchor_version: int | None


@dataclass
class ContinuityHooks:
    service: ContinuityService

    def before_compaction(self, conversation_id: str, latest_turns: list[str]) -> UpdateResult:
        return self.service.update_anchor(
            conversation_id=conversation_id,
            latest_turns=latest_turns,
            optional_event="before_compaction",
            force=True,
            token_near_threshold=True,
        )

    def before_response(self, conversation_id: str, user_query: str) -> PreparedPrompt:
        ctx: QueryContextResult = self.service.render_context(conversation_id, user_query)
        return PreparedPrompt(
            user_query=user_query,
            continuity_context_block=ctx.context_block,
            degraded=ctx.degraded,
            anchor_version=ctx.anchor_version,
        )

    def after_response(self, conversation_id: str, response_text: str, turn_id: int) -> UpdateResult:
        return self.service.ack_response(conversation_id, response_text, turn_id)
