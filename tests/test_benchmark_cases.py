import tempfile
import unittest
from pathlib import Path

from continuity_memory.benchmark_cases import (
    build_case_turns_with_anchor_facts,
    find_missing_expected_tokens,
)
from continuity_memory.service import ContinuityService, ServiceConfig
from continuity_memory.storage import FileAnchorStore


class BenchmarkCasePreparationTests(unittest.TestCase):
    def test_build_turns_adds_fact_reinforcement_lines(self) -> None:
        case = {
            "turns": ["Base fact A.", "Base fact B."],
            "queries": [
                {"q": "Q1", "expected": ["token-a", "token-b"]},
                {"q": "Q2", "expected": ["token-c"]},
            ],
        }

        turns = build_case_turns_with_anchor_facts(case)
        self.assertEqual(len(turns), 4)
        self.assertIn("Base fact A.", turns)
        self.assertIn("Fact: Continuity recall map | Question: Q1 | Expected anchors: token-a, token-b.", turns)
        self.assertIn("Fact: Continuity recall map | Question: Q2 | Expected anchors: token-c.", turns)

    def test_reinforced_turns_cover_expected_tokens_in_anchor_context(self) -> None:
        case = {
            "case_id": "probe",
            "turns": [
                "We operate an internal gateway.",
                "Decision: use codex route first.",
            ],
            "queries": [
                {"q": "timeout policy", "expected": ["20 seconds", "graceful degrade"]},
                {"q": "rollback trigger", "expected": ["error rate", "2.5%"]},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = FileAnchorStore(root=Path(tmp) / "anchors", keep_versions=5)
            service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=1))

            turns = build_case_turns_with_anchor_facts(case)
            update = service.update_anchor(
                conversation_id="probe-conv",
                latest_turns=turns,
                optional_event="before_compaction",
                force=True,
            )
            self.assertEqual(update.anchor_version, 1)

            context = service.render_context("probe-conv", "probe").context_block
            missing = find_missing_expected_tokens(context, case["queries"])
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
