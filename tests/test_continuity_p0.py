import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from continuity_memory.hooks import ContinuityHooks  # noqa: E402
from continuity_memory.service import ContinuityService, ServiceConfig  # noqa: E402
from continuity_memory.storage import (  # noqa: E402
    AnchorCorruptedError,
    FileAnchorStore,
    HybridAnchorStore,
    InMemoryRemoteBackend,
)


class ContinuityP0Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.local_store = FileAnchorStore(root=root / "anchors", keep_versions=5)
        self.service = ContinuityService(store=self.local_store, config=ServiceConfig(refresh_interval_turns=2))
        self.hooks = ContinuityHooks(service=self.service)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_update_read_render_ack_flow(self) -> None:
        conversation_id = "conv-alpha"
        turns = [
            "Goal: ship P0 continuity module",
            "Decision: no fork OpenClaw",
            "Constraint: latency must remain low",
            "Done: drafted API contract",
        ]

        update = self.hooks.before_compaction(conversation_id, turns)
        self.assertEqual(update.anchor_version, 1)
        self.assertGreater(update.confidence, 0.0)

        prepared = self.hooks.before_response(conversation_id, "What is our current constraint?")
        self.assertFalse(prepared.degraded)
        self.assertIsNotNone(prepared.anchor_version)
        self.assertIn("Conversation Continuity Context", prepared.continuity_context_block)
        self.assertIn("latency", prepared.continuity_context_block.lower())

        ack = self.hooks.after_response(conversation_id, "We keep latency low.", turn_id=5)
        self.assertEqual(ack.anchor_version, 2)

        latest = self.service.get_latest(conversation_id)
        self.assertEqual(latest.anchor_version, 2)
        self.assertIn("no fork OpenClaw", " ".join(latest.state.decisions))

    def test_degrade_when_anchor_missing(self) -> None:
        prepared = self.hooks.before_response("unknown-conv", "What did we decide?")
        self.assertTrue(prepared.degraded)
        self.assertIsNone(prepared.anchor_version)
        self.assertIn("上下文不足", prepared.continuity_context_block)

    def test_corrupted_latest_falls_back_to_previous(self) -> None:
        cid = "conv-corrupt"
        turns_v1 = ["Goal: stabilize continuity", "Decision: keep latest cache"]
        turns_v2 = turns_v1 + ["Done: write second version"]

        self.hooks.before_compaction(cid, turns_v1)
        self.hooks.before_compaction(cid, turns_v2)

        data_path = Path(self.tempdir.name) / "anchors" / f"{cid}.json"
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        payload["versions"][-1]["summary_compact"] = "tampered"
        data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.hooks.before_response(cid, "What is our goal?")
        self.assertFalse(result.degraded)
        self.assertEqual(result.anchor_version, 1)

    def test_detect_corruption_on_store_direct_read(self) -> None:
        cid = "conv-direct"
        self.hooks.before_compaction(cid, ["Goal: integrity"]) 
        data_path = Path(self.tempdir.name) / "anchors" / f"{cid}.json"
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        payload["versions"][-1]["summary_compact"] = "changed"
        data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with self.assertRaises(AnchorCorruptedError):
            self.local_store.get_latest(cid)

    def test_hybrid_store_local_write_and_remote_retry(self) -> None:
        remote = InMemoryRemoteBackend(fail_writes=True)
        local = FileAnchorStore(root=Path(self.tempdir.name) / "hybrid", keep_versions=5)
        hybrid = HybridAnchorStore(local=local, remote=remote)
        service = ContinuityService(store=hybrid, config=ServiceConfig(refresh_interval_turns=1))
        hooks = ContinuityHooks(service=service)

        cid = "conv-hybrid"
        hooks.before_compaction(cid, ["Goal: hybrid mode", "Constraint: no data loss"])
        latest = service.get_latest(cid)
        self.assertEqual(latest.anchor_version, 1)
        self.assertEqual(len(hybrid.pending_retry), 1)

        remote.fail_writes = False
        hybrid.flush_retry()
        self.assertEqual(len(hybrid.pending_retry), 0)
        self.assertEqual(remote.get_latest(cid).anchor_version, 1)

    def test_hybrid_retry_queue_persists_across_restart(self) -> None:
        remote = InMemoryRemoteBackend(fail_writes=True)
        local = FileAnchorStore(root=Path(self.tempdir.name) / "hybrid-persist", keep_versions=5)
        queue_path = Path(self.tempdir.name) / "hybrid-persist" / "retry.json"
        hybrid = HybridAnchorStore(local=local, remote=remote, retry_queue_path=queue_path)
        service = ContinuityService(store=hybrid, config=ServiceConfig(refresh_interval_turns=1))
        hooks = ContinuityHooks(service=service)

        cid = "default:conv-persist"
        hooks.before_compaction(cid, ["Goal: persist retries", "Decision: keep durable queue"])
        self.assertEqual(len(hybrid.pending_retry), 1)
        self.assertTrue(queue_path.exists())

        reloaded = HybridAnchorStore(local=local, remote=remote, retry_queue_path=queue_path)
        self.assertEqual(len(reloaded.pending_retry), 1)

    def test_hybrid_retry_worker_flushes_when_remote_recovers(self) -> None:
        remote = InMemoryRemoteBackend(fail_writes=True)
        local = FileAnchorStore(root=Path(self.tempdir.name) / "hybrid-worker", keep_versions=5)
        hybrid = HybridAnchorStore(local=local, remote=remote)
        service = ContinuityService(store=hybrid, config=ServiceConfig(refresh_interval_turns=1))
        hooks = ContinuityHooks(service=service)

        cid = "default:conv-worker"
        hooks.before_compaction(cid, ["Goal: background flush"])
        self.assertEqual(len(hybrid.pending_retry), 1)

        hybrid.start_retry_worker(interval_seconds=0.1)
        try:
            remote.fail_writes = False
            for _ in range(20):
                if len(hybrid.pending_retry) == 0:
                    break
                time.sleep(0.05)
            self.assertEqual(len(hybrid.pending_retry), 0)
        finally:
            hybrid.stop_retry_worker(flush=True)

    def test_metrics_snapshot(self) -> None:
        cid = "conv-metrics"
        self.hooks.before_compaction(cid, ["Goal: metrics", "Done: define KPIs"])
        self.service.record_answer_outcome(cid, success=True, drifted=False, contradicted=False)
        self.service.record_answer_outcome(cid, success=False, drifted=True, contradicted=False)
        _ = self.hooks.before_response(cid, "what next?")

        metrics = self.service.metrics_snapshot()
        self.assertGreaterEqual(metrics.continuity_success_rate, 0.0)
        self.assertLessEqual(metrics.continuity_success_rate, 1.0)
        self.assertGreaterEqual(metrics.anchor_write_success_rate, 1.0)
        self.assertGreaterEqual(metrics.anchor_read_latency_p95_ms, 0.0)

        alert_eval = self.service.evaluate_slo()
        self.assertIn("overall_ok", alert_eval)
        self.assertIn("checks", alert_eval)


if __name__ == "__main__":
    unittest.main()
