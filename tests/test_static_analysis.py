"""Static gate contracts: thresholds, fail-closed behavior and safe reports."""
import importlib.util
import json
import contextlib
import io
from pathlib import Path
import shutil
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


class InstalledAnalyzerTests(unittest.TestCase):
    """Run explicitly after bootstrap: isolated repos, real tools, no ambient DB."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lab6 path with spaces ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ("app", "migrations", "scripts/ci", "tests"):
            (self.root / directory).mkdir(parents=True)
        for name in ("run.py", "seed.py", "gunicorn.conf.py", "verify_acceptance.py", "verify_modernization.py"):
            (self.root / name).touch()
        shutil.copy(gate.ROOT / "scripts/ci/gitleaks.toml", self.root / "scripts/ci/gitleaks.toml")
        self.command("init", "-q")
        (self.root / "README.md").write_text("isolated fixture\n")
        self.commit()
        self.patcher = patch.multiple(gate, ROOT=self.root, CONFIG=gate.ROOT / "scripts/ci",
                                      OUT=self.root / "artifacts/static-analysis")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def command(self, *args):
        return subprocess.run(["git", "-c", "user.name=CI fixture", "-c", "user.email=fixture@example.test", *args],
                              cwd=self.root, check=True, capture_output=True, text=True)

    def commit(self):
        self.command("add", ".")
        self.command("commit", "-qm", "isolated fixture")

    def test_real_ruff_and_bandit_gates(self):
        (self.root / "app/probe.py").write_text("def probe():\n    return undefined_probe\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.analyze("quality"), 1)
        quality = json.loads((gate.OUT / "quality/report.json").read_text())
        self.assertEqual(quality["blockers"], 1)
        self.assertEqual(quality["findings"][0]["rule"], "F821")
        (self.root / "app/probe.py").write_text("import subprocess\nsubprocess.run('ls', shell=True)\n")
        # B602 constant shell command is LOW, not the HIGH/HIGH policy.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.analyze("security"), 0)
        (self.root / "app/probe.py").write_text("import subprocess\ndef probe(command):\n    subprocess.run(command, shell=True)\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.analyze("security"), 1)

    def test_real_gitleaks_current_and_deleted_history_are_redacted(self):
        # Deliberately synthetic, never a credential; assembled to avoid adding
        # a secret-looking literal to the actual repository history.
        marker = "NotReal" + "9x7Y6v5W4u3T2s1R" + "8q6P5m4K3j2H1g0F"
        probe = self.root / "app/probe.py"
        probe.write_text("pass" + "word = " + repr(marker) + "\n")
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(gate.analyze("secrets"), 1)
        self.assertNotIn(marker, captured.getvalue())
        self.commit()
        probe.unlink()
        self.commit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.analyze("secrets"), 1)
        text = (gate.OUT / "secrets/report.json").read_text()
        self.assertIn("reachable-history", text)
        self.assertNotIn(marker, text)
        self.assertNotIn(marker, (gate.OUT / "secrets/index.html").read_text())


if __name__ == "__main__":
    unittest.main()
