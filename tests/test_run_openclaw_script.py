import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_openclaw_continuity.py"
    spec = importlib.util.spec_from_file_location("run_openclaw_continuity", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load script module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunOpenClawScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script_module()

    def test_load_tidb_dsn_from_instance_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tidb.json"
            path.write_text(
                json.dumps(
                    {
                        "instance": {
                            "connectionString": "mysql://u:p@h:4000/",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            dsn = self.module.load_tidb_dsn_from_file(path)
            self.assertEqual(dsn, "mysql://u:p@h:4000/")

    def test_load_tidb_dsn_from_top_level_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tidb.json"
            path.write_text(
                json.dumps({"connectionString": "mysql://u:p@h:4000/"}, ensure_ascii=False),
                encoding="utf-8",
            )
            dsn = self.module.load_tidb_dsn_from_file(path)
            self.assertEqual(dsn, "mysql://u:p@h:4000/")

    def test_load_tidb_dsn_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.json"
            with self.assertRaises(RuntimeError):
                self.module.load_tidb_dsn_from_file(path)


if __name__ == "__main__":
    unittest.main()
