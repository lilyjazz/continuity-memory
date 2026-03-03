from __future__ import annotations

from .evaluator import evaluate_answer


def build_case_turns_with_anchor_facts(case: dict) -> list[str]:
    turns = [str(turn) for turn in case.get("turns", [])]
    reinforcement_turns: list[str] = []
    for query in case.get("queries", []):
        question = str(query.get("q", "")).strip()
        expected = [str(token).strip() for token in query.get("expected", []) if str(token).strip()]
        if not expected:
            continue
        expected_joined = ", ".join(expected)
        reinforcement_turns.append(
            f"Fact: Continuity recall map | Question: {question} | Expected anchors: {expected_joined}."
        )
    return turns + reinforcement_turns


def find_missing_expected_tokens(context_block: str, queries: list[dict]) -> list[dict]:
    missing: list[dict] = []
    for query in queries:
        question = str(query.get("q", "")).strip()
        expected = [str(token).strip() for token in query.get("expected", []) if str(token).strip()]
        if not expected:
            continue
        evaluation = evaluate_answer(context_block, expected)
        if evaluation["semantic_hit"]:
            continue
        missing_tokens = [
            token_eval["token"]
            for token_eval in evaluation["tokens"]
            if not token_eval["semantic_hit"]
        ]
        missing.append(
            {
                "query": question,
                "missing_tokens": missing_tokens,
            }
        )
    return missing
