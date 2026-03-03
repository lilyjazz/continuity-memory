from __future__ import annotations

import re
from dataclasses import dataclass


_SPACE_RE = re.compile(r"\s+")
_STRIP_RE = re.compile(r"[^\w%<>.=\-\s]", re.UNICODE)
_NUM_UNIT_RE = re.compile(
    r"(?P<cmp><=|>=|<|>)?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|s|days?|d|weeks?|w|hours?|hrs?|h|%|percent|pct)?",
    re.IGNORECASE,
)


_PHRASE_VARIANTS = {
    "graceful degrade": ["graceful degradation", "degrade gracefully", "graceful-degrade"],
    "error rate": ["error-rate", "failure rate", "error percentage"],
    "legal sign-off": ["legal signoff", "legal approval", "legal review sign off"],
    "no cloud phi export": [
        "no phi export to cloud",
        "cloud phi export is not allowed",
        "do not export phi to cloud",
    ],
    "unresolved": ["not resolved", "pending resolution", "still pending"],
    "weekly": ["per week", "each week", "every week"],
}


@dataclass
class TokenEval:
    token: str
    strict_hit: bool
    semantic_hit: bool


def _normalize(text: str) -> str:
    lowered = text.lower().replace("–", "-").replace("—", "-")
    cleaned = _STRIP_RE.sub(" ", lowered)
    compacted = _SPACE_RE.sub(" ", cleaned).strip()
    return compacted


def _unit_aliases(unit: str) -> list[str]:
    u = unit.lower()
    if u in ("s", "sec", "secs", "second", "seconds"):
        return ["s", "sec", "second", "seconds"]
    if u in ("d", "day", "days"):
        return ["d", "day", "days"]
    if u in ("w", "week", "weeks"):
        return ["w", "week", "weeks"]
    if u in ("h", "hr", "hrs", "hour", "hours"):
        return ["h", "hr", "hour", "hours"]
    if u in ("%", "percent", "pct"):
        return ["%", "percent", "pct"]
    return [u]


def _phrase_variants(token_norm: str) -> list[str]:
    variants = {token_norm, token_norm.replace("-", " "), token_norm.replace(" ", "-")}

    for key, values in _PHRASE_VARIANTS.items():
        if key in token_norm:
            for value in values:
                variants.add(_normalize(value))

    if "%" in token_norm:
        variants.add(token_norm.replace("%", " percent"))
        variants.add(token_norm.replace("%", " pct"))

    m = _NUM_UNIT_RE.fullmatch(token_norm)
    if m:
        cmp_sign = m.group("cmp") or ""
        num = m.group("num")
        unit = m.group("unit") or ""
        unit_variants = _unit_aliases(unit) if unit else [""]
        for unit_variant in unit_variants:
            unit_tail = f" {unit_variant}" if unit_variant else ""
            variants.add(_normalize(f"{cmp_sign}{num}{unit_tail}"))
            variants.add(_normalize(f"{cmp_sign} {num}{unit_tail}"))
            if cmp_sign == "<":
                variants.add(_normalize(f"under {num}{unit_tail}"))
                variants.add(_normalize(f"less than {num}{unit_tail}"))
                variants.add(_normalize(f"below {num}{unit_tail}"))
            if cmp_sign == ">":
                variants.add(_normalize(f"over {num}{unit_tail}"))
                variants.add(_normalize(f"more than {num}{unit_tail}"))
                variants.add(_normalize(f"above {num}{unit_tail}"))
            if cmp_sign in (">=",):
                variants.add(_normalize(f"at least {num}{unit_tail}"))
            if cmp_sign in ("<=",):
                variants.add(_normalize(f"at most {num}{unit_tail}"))

    m_in = re.search(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|days?|weeks?|hours?|%)", token_norm)
    if m_in:
        num = m_in.group("num")
        unit = m_in.group("unit")
        for unit_variant in _unit_aliases(unit):
            variants.add(_normalize(f"{num}{unit_variant}"))
            variants.add(_normalize(f"{num} {unit_variant}"))

    return sorted(variants)


def _strict_token_hit(answer: str, token: str) -> bool:
    return token.lower() in answer.lower()


def _semantic_token_hit(answer_norm: str, token: str) -> bool:
    token_norm = _normalize(token)
    if not token_norm:
        return False

    if token_norm in answer_norm:
        return True

    for variant in _phrase_variants(token_norm):
        if variant and variant in answer_norm:
            return True

    words = [w for w in token_norm.split(" ") if w]
    if len(words) >= 2:
        covered = sum(1 for w in words if w in answer_norm)
        if covered / len(words) >= 0.8:
            return True

    return False


def evaluate_answer(answer: str, expected_tokens: list[str]) -> dict:
    answer_norm = _normalize(answer)
    token_evals: list[TokenEval] = []
    strict_hits = 0
    semantic_hits = 0

    for token in expected_tokens:
        strict = _strict_token_hit(answer, token)
        semantic = _semantic_token_hit(answer_norm, token)
        if strict:
            strict_hits += 1
        if semantic:
            semantic_hits += 1
        token_evals.append(TokenEval(token=token, strict_hit=strict, semantic_hit=semantic))

    total = max(1, len(expected_tokens))
    return {
        "strict_hit": strict_hits == len(expected_tokens),
        "semantic_hit": semantic_hits == len(expected_tokens),
        "strict_coverage": strict_hits / total,
        "semantic_coverage": semantic_hits / total,
        "tokens": [
            {
                "token": item.token,
                "strict_hit": item.strict_hit,
                "semantic_hit": item.semantic_hit,
            }
            for item in token_evals
        ],
    }
