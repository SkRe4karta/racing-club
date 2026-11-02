"""Static gate contracts: thresholds, fail-closed behavior and safe reports."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "static_gate", Path(__file__).resolve().parents[1] / "scripts/ci/static_analysis.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class StaticAnalysisTests(unittest.TestCase):
    def test_quality_thresholds(self):
        for rule, expected in [("F401", 0), ("F821", 1), ("E999", 1), (None, 1)]:
            with self.subTest(rule=rule), patch.object(gate, "run", return_value=subprocess.CompletedProcess(
                [], 1, json.dumps([{"filename": "app/example.py", "location": {"row": 1},
                                    "code": rule, "message": "do-not-publish-source"}]), "")):
                items, blockers = gate.quality(Path("unused"))
                self.assertEqual(blockers, expected)
                self.assertNotIn("message", items[0])

    def test_security_thresholds_and_incomplete_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = {"errors": [], "results": [
                {"filename": "app/a.py", "line_number": 1, "test_id": "B324",
                 "issue_severity": "HIGH", "issue_confidence": "HIGH"},
                {"filename": "app/b.py", "line_number": 2, "test_id": "B324",
                 "issue_severity": "HIGH", "issue_confidence": "MEDIUM"}]}
            (folder / "bandit.json").write_text(json.dumps(report))
            with patch.object(gate, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
                self.assertEqual(gate.security(folder)[1], 1)
                report["errors"] = [{"reason": "cannot parse"}]
                (folder / "bandit.json").write_text(json.dumps(report))
                with self.assertRaises(RuntimeError):
                    gate.security(folder)

    def test_error_is_nonzero_and_report_does_not_expose_exception(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate, "OUT", Path(tmp)), \
                patch.object(gate, "tool_version", side_effect=RuntimeError("private-credential")):
            self.assertEqual(gate.analyze("quality"), 2)
            self.assertFalse(gate.summary())
            for path in Path(tmp).rglob("*"):
                if path.is_file():
                    self.assertNotIn("private-credential", path.read_text())

    def test_missing_stale_and_pass_summary(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate, "OUT", Path(tmp)):
            self.assertFalse(gate.summary())
            for name in gate.POLICY:
                gate.write_report(name, {"name": name, "revision": "old", "status": "PASS",
                                        "findings": [], "count": 0, "blockers": 0})
            self.assertFalse(gate.summary())
            for name in gate.POLICY:
                gate.write_report(name, {"name": name, "revision": gate.tracked_revision(), "status": "PASS",
                                        "findings": [], "count": 0, "blockers": 0})
            self.assertTrue(gate.summary())

    def test_shallow_clone_is_error(self):
        with patch.object(gate, "run", return_value=subprocess.CompletedProcess([], 0, "true\n", "")):
            with self.assertRaises(RuntimeError):
                gate.secrets(Path("unused"))


if __name__ == "__main__":
    unittest.main()
