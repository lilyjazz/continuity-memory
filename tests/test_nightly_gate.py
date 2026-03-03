import importlib.util
import sys
import unittest
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_openclaw_remote_nightly_gate.py"
    spec = importlib.util.spec_from_file_location("run_openclaw_remote_nightly_gate", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load nightly gate script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NightlyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script_module()

    def test_gate_passes_when_metrics_meet_thresholds(self) -> None:
        compact = {"delta": 0.35, "delta_semantic": 0.55}
        reset = {"delta": 0.40, "delta_semantic": 0.60}
        stability = {
            "summary": {
                "round_count": 5,
                "passed_rounds": 5,
                "elapsed_p95_sec": 800,
            }
        }
        thresholds = self.module.GateThresholds(
            min_compact_delta_strict=0.2,
            min_reset_delta_strict=0.2,
            min_compact_delta_semantic=0.3,
            min_reset_delta_semantic=0.3,
            min_stability_pass_rate=1.0,
            max_stability_elapsed_p95_sec=1200,
        )

        result = self.module.evaluate_gate(compact, reset, stability, thresholds)
        self.assertTrue(result["overall_pass"])
        for _, check in result["checks"].items():
            self.assertTrue(check["ok"])

    def test_gate_fails_when_stability_or_delta_below_threshold(self) -> None:
        compact = {"delta": 0.1, "delta_semantic": 0.4}
        reset = {"delta": 0.3, "delta_semantic": 0.25}
        stability = {
            "summary": {
                "round_count": 5,
                "passed_rounds": 4,
                "elapsed_p95_sec": 1500,
            }
        }
        thresholds = self.module.GateThresholds(
            min_compact_delta_strict=0.2,
            min_reset_delta_strict=0.2,
            min_compact_delta_semantic=0.3,
            min_reset_delta_semantic=0.3,
            min_stability_pass_rate=1.0,
            max_stability_elapsed_p95_sec=1200,
        )

        result = self.module.evaluate_gate(compact, reset, stability, thresholds)
        self.assertFalse(result["overall_pass"])
        self.assertFalse(result["checks"]["compact_delta_strict"]["ok"])
        self.assertFalse(result["checks"]["reset_delta_semantic"]["ok"])
        self.assertFalse(result["checks"]["stability_pass_rate"]["ok"])
        self.assertFalse(result["checks"]["stability_elapsed_p95"]["ok"])

    def test_gate_accepts_stability_top_level_summary_shape(self) -> None:
        compact = {"delta": 0.5, "delta_semantic": 0.7}
        reset = {"delta": 0.5, "delta_semantic": 0.7}
        stability = {
            "round_count": 5,
            "passed_rounds": 5,
            "elapsed_p95_sec": 500,
        }
        thresholds = self.module.GateThresholds(
            min_compact_delta_strict=0.2,
            min_reset_delta_strict=0.2,
            min_compact_delta_semantic=0.3,
            min_reset_delta_semantic=0.3,
            min_stability_pass_rate=1.0,
            max_stability_elapsed_p95_sec=1200,
        )

        result = self.module.evaluate_gate(compact, reset, stability, thresholds)
        self.assertTrue(result["overall_pass"])


if __name__ == "__main__":
    unittest.main()
