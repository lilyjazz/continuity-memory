import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from continuity_memory.openclaw_adapter import OpenClawContinuityAdapter, RemoteOpenClawGateway  # noqa: E402
from continuity_memory.service import ContinuityService, ServiceConfig  # noqa: E402
from continuity_memory.storage import FileAnchorStore  # noqa: E402


class FakeGateway:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def ask(self, session_id: str, message: str) -> str:
        _ = session_id
        self.messages.append(message)
        lower = message.lower()
        if "constraint" in lower:
            return "Constraint is no fork OpenClaw and keep latency low."
        return "Acknowledged and continued."


class OpenClawAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        store = FileAnchorStore(root=Path(self.tempdir.name) / "anchors", keep_versions=5)
        service = ContinuityService(store=store, config=ServiceConfig(refresh_interval_turns=1))
        self.gateway = FakeGateway()
        self.adapter = OpenClawContinuityAdapter(service=service, gateway=self.gateway)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ask_without_anchor_uses_degrade_context(self) -> None:
        result = self.adapter.ask("conv-new", "What is our constraint?")
        self.assertTrue(result.degraded)
        self.assertIsNone(result.anchor_version_used)
        self.assertIn("上下文不足", result.continuity_context_block)
        self.assertEqual(result.anchor_version_after_ack, 1)

    def test_compaction_then_ask_uses_continuity_context(self) -> None:
        cid = "conv-ready"
        self.adapter.add_turn(cid, "Goal: deliver P0")
        self.adapter.add_turn(cid, "Decision: no fork OpenClaw")
        self.adapter.add_turn(cid, "Constraint: latency must stay low")
        update = self.adapter.prepare_for_compaction(cid)
        self.assertEqual(update.anchor_version, 1)

        result = self.adapter.ask(cid, "What is our constraint?")
        self.assertFalse(result.degraded)
        self.assertEqual(result.anchor_version_used, 1)
        self.assertIn("Conversation Continuity Context", result.continuity_context_block)
        self.assertIn("latency", result.answer.lower())
        self.assertEqual(result.anchor_version_after_ack, 2)

    def test_session_id_is_stable_per_conversation(self) -> None:
        first = self.adapter.session_id_for("conv-a")
        second = self.adapter.session_id_for("conv-a")
        third = self.adapter.session_id_for("conv-b")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)


if __name__ == "__main__":
    unittest.main()


class RemoteGatewayRetryTests(unittest.TestCase):
    def test_retryable_ssh_error_retries_then_succeeds(self) -> None:
        gateway = RemoteOpenClawGateway(
            ssh_host="example.com",
            ssh_user="ubuntu",
            ssh_key_path="/tmp/key.pem",
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        first = subprocess.CompletedProcess(args=["ssh"], returncode=255, stdout="", stderr="Can't assign requested address")
        second = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout='{"result":{"payloads":[{"text":"ok"}]}}',
            stderr="",
        )

        with patch("continuity_memory.openclaw_adapter.subprocess.run", side_effect=[first, second]) as mock_run:
            result = gateway.ask("sid", "hello")

        self.assertEqual(result, "ok")
        self.assertEqual(mock_run.call_count, 2)

    def test_non_retryable_error_raises_without_retries(self) -> None:
        gateway = RemoteOpenClawGateway(
            ssh_host="example.com",
            ssh_user="ubuntu",
            ssh_key_path="/tmp/key.pem",
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )
        failed = subprocess.CompletedProcess(args=["ssh"], returncode=2, stdout="", stderr="permission denied")

        with patch("continuity_memory.openclaw_adapter.subprocess.run", return_value=failed) as mock_run:
            with self.assertRaises(RuntimeError):
                gateway.ask("sid", "hello")

        self.assertEqual(mock_run.call_count, 1)
