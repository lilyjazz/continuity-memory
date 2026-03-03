import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from continuity_memory.evaluator import evaluate_answer  # noqa: E402


class EvaluatorTests(unittest.TestCase):
    def test_strict_and_semantic_exact_match(self) -> None:
        result = evaluate_answer(
            "Hard timeout is 20 seconds with graceful degrade response.",
            ["20 seconds", "graceful degrade"],
        )
        self.assertTrue(result["strict_hit"])
        self.assertTrue(result["semantic_hit"])

    def test_semantic_handles_variant_phrasing(self) -> None:
        result = evaluate_answer(
            "Timeout is 20s and we degrade gracefully when exceeded.",
            ["20 seconds", "graceful degrade"],
        )
        self.assertFalse(result["strict_hit"])
        self.assertTrue(result["semantic_hit"])

    def test_numeric_comparator_variants(self) -> None:
        result = evaluate_answer(
            "No instant payout for merchants with tenure under 60 days.",
            ["no instant payout", "< 60 days"],
        )
        self.assertFalse(result["strict_hit"])
        self.assertTrue(result["semantic_hit"])

    def test_semantic_supports_cjk_tokens(self) -> None:
        result = evaluate_answer(
            "Constraint: 不能上传任何可识别个人信息到第三方分析平台。",
            ["不能上传", "可识别个人信息"],
        )
        self.assertTrue(result["strict_hit"])
        self.assertTrue(result["semantic_hit"])


if __name__ == "__main__":
    unittest.main()
