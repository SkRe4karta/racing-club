#!/usr/bin/env python3
"""Fail-closed analysis gates. Publish metadata only, never source or tool stderr.

Exit codes: 0 PASS, 1 policy BLOCKED, 2 infrastructure/report ERROR.
Raw scanner output lives in a temporary directory outside build artifacts.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("STATIC_ANALYSIS_DIR", ROOT / "artifacts/static-analysis")).resolve()
TARGETS = ["app", "migrations", "scripts", "tests", "run.py", "seed.py",
           "gunicorn.conf.py", "verify_acceptance.py", "verify_modernization.py"]
BLOCKERS = {"F821", "F822", "F823", "F631", "F701", "F702", "F704", "F706",
            "F707", "F722", "F901"}
VERSIONS = {"ruff": "0.14.14", "bandit": "1.9.4", "gitleaks": "8.28.0"}
POLICY = {
    "quality": "BLOCKER (project policy): invalid syntax; F821/F822/F823, F631, "
               "F701/F702/F704/F706/F707/F722/F901. Other E4/E7/E9/F findings are advisory.",
    "security": "Bandit HIGH severity AND HIGH confidence; Bandit has no CRITICAL. "
                "This conservative project threshold is not a native CRITICAL classification.",
    "secrets": "Any Gitleaks finding blocks; current source tree and feature branch commits only. "
               "Other branches are audited separately to avoid unrelated branch history blocking.",
}


def run(command: list[str]) -> subprocess.CompletedProcess:
    """Never forward raw stdout/stderr; they can contain source and credentials."""
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)


def tracked_revision() -> str:
    result = run(["git", "rev-parse", "HEAD"])
    if result.returncode:
        raise RuntimeError("Cannot identify checkout revision")
    return result.stdout.strip()


def tool_version(tool: str) -> str:
    result = run([tool, "version" if tool == "gitleaks" else "--version"])
    lines = result.stdout.splitlines()
    if result.returncode or not lines or VERSIONS[tool] not in lines[0].split():
        raise RuntimeError(f"Missing or unexpected {tool} version; run prepare-static-analysis.sh")
    return VERSIONS[tool]


def relative(filename: str) -> str:
    path = Path(filename)
    if path.is_absolute():
        try:
            path = path.relative_to(ROOT)
        except ValueError:
            return "outside-checkout"
    return path.as_posix().removeprefix("./")


def quality(tmp: Path) -> tuple[list[dict], int]:
    result = run(["ruff", "check", "--isolated", "--target-version", "py314",
                  "--select", "E4,E7,E9,F", "--output-format", "json", *TARGETS])
    if result.returncode not in (0, 1):
        raise RuntimeError("Ruff execution error")
    data = json.loads(result.stdout)
    items = [{"file": relative(x["filename"]), "line": x["location"]["row"],
              "rule": x["code"] or "invalid-syntax",
              "severity": "BLOCKER" if x["code"] is None or x["code"].startswith("E9")
              or x["code"] in BLOCKERS else "ADVISORY"} for x in data]
    return items, sum(x["severity"] == "BLOCKER" for x in items)


def security(tmp: Path) -> tuple[list[dict], int]:
    path = tmp / "bandit.json"
    result = run(["bandit", "--ignore-nosec", "-q", "-r", *TARGETS, "-f", "json", "-o", str(path)])
    if result.returncode not in (0, 1) or not path.is_file():
        raise RuntimeError("Bandit execution error")
    data = json.loads(path.read_text())
    if data.get("errors") or "internal error" in result.stderr.lower() or "exception occurred" in result.stderr.lower():
        raise RuntimeError("Bandit could not scan every target")
    items = [{"file": relative(x["filename"]), "line": x["line_number"],
              "rule": x["test_id"], "severity": x["issue_severity"],
              "confidence": x["issue_confidence"]} for x in data["results"]]
    return items, sum(x["severity"] == x["confidence"] == "HIGH" for x in items)


def secrets(tmp: Path) -> tuple[list[dict], int]:
    shallow = run(["git", "rev-parse", "--is-shallow-repository"])
    if shallow.returncode or shallow.stdout.strip() != "false":
        raise RuntimeError("Full history required for the checked-out branch")
    files = run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    if files.returncode:
        raise RuntimeError("Cannot enumerate working tree")
    snapshot = tmp / "tree"
    snapshot.mkdir()
    excluded = {".git", ".venv", "venv", ".static-tools", "__pycache__", ".ruff_cache",
                ".pytest_cache", "artifacts", "instance", "node_modules", "htmlcov"}
    for name in files.stdout.split("\0"):
        if not name or set(Path(name).parts) & excluded:
            continue
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            continue
        content = source.read_bytes()
        if b"\0" in content[:8192]:
            continue
        dest = snapshot / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    findings = []
    for mode, source, scope in (("git", ROOT, "branch-history"), ("dir", snapshot, "working-tree")):
        path = tmp / f"gitleaks-{scope}.json"
        command = ["gitleaks", mode, str(source), "--config", str(ROOT / "scripts/ci/gitleaks.toml"),
                   "--redact=100", "--no-banner", "--exit-code", "10",
                   "--report-format", "json", "--report-path", str(path)]
        if mode == "git":
            branch = run(["git", "branch", "--show-current"])
            if branch.returncode or not branch.stdout.strip():
                raise RuntimeError("Named branch checkout required for secret history scan")
            command.append(f"--log-opts=--full-history refs/heads/{branch.stdout.strip()}")
        result = run(command)
        if result.returncode not in (0, 10) or not path.is_file():
            raise RuntimeError(f"Gitleaks {scope} execution error")
        data = json.loads(path.read_text()) or []
        if bool(data) != (result.returncode == 10):
            raise RuntimeError("Inconsistent Gitleaks status/report")
        for x in data:
            filename = x["File"]
            if scope == "working-tree":
                filename = filename.removeprefix(str(snapshot) + "/")
            findings.append({"file": relative(filename), "line": x["StartLine"],
                             "rule": x["RuleID"], "severity": "BLOCKER", "scope": scope,
                             "commit": x.get("Commit", "")})
    return findings, len(findings)


def write_report(name: str, report: dict) -> None:
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    text = (f"{name}: {report['status']}; findings={report['count']}; blockers={report['blockers']}\n"
            f"Policy: {POLICY[name]}\n")
    if report.get("error"):
        text += report["error"] + "\n"
    text += "".join(f"{x['file']}:{x['line']} {x['rule']} {x['severity']}\n" for x in report["findings"])
    (folder / "summary.txt").write_text(text)
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(x.get(k, '')))}</td>"
                                  for k in ("file", "line", "rule", "severity", "confidence", "scope"))
                   + "</tr>" for x in report["findings"])
    (folder / "index.html").write_text(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Racing Club analysis</title>'
        '<style>body{font:16px sans-serif;margin:2rem}td,th{padding:.4rem;text-align:left}'
        'table{border-collapse:collapse}tr{border-bottom:1px solid #ddd}</style>'
        f"<h1>{html.escape(name)}: {report['status']}</h1><p>{html.escape(POLICY[name])}</p>"
        f"<p>Findings: {report['count']}; blockers: {report['blockers']}</p>"
        '<table><tr><th>File</th><th>Line</th><th>Rule</th><th>Severity</th><th>Confidence</th><th>Scope</th></tr>'
        + rows + '</table></html>')


def summary() -> bool:
    reports = []
    revision = tracked_revision()
    for name in POLICY:
        path = OUT / name / "report.json"
        if path.exists():
            report = json.loads(path.read_text())
            if report.get("revision") != revision:
                report = {"name": name, "status": "STALE", "count": 0, "blockers": 0}
        else:
            report = {"name": name, "status": "NOT RUN", "count": 0, "blockers": 0}
        reports.append(report)
    passed = all(x["status"] == "PASS" for x in reports)
    branch = os.environ.get("TC_BRANCH") or run(["git", "branch", "--show-current"]).stdout.strip()
    build = os.environ.get("BUILD_NUMBER", "local")
    rows = "".join(f"<tr><td><a href='{x['name']}/index.html'>{x['name']}</a></td>"
                   f"<td>{x['status']}</td><td>{x['count']}</td><td>{x['blockers']}</td></tr>" for x in reports)
    versions = "; ".join(f"{k}={v}" for k, v in VERSIONS.items())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.html").write_text(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Racing Club: статический анализ</title>'
        '<style>body{font:17px sans-serif;max-width:1000px;margin:40px auto;padding:20px}'
        'table{border-collapse:collapse;width:100%}td,th{padding:14px;border:1px solid #ccc;text-align:left}'
        'code{overflow-wrap:anywhere}</style><h1>Racing Club — статический анализ</h1>'
        f"<p>Ветка: <code>{html.escape(branch)}</code>; сборка: {html.escape(build)}</p>"
        f"<p>Revision: <code>{revision}</code></p><p>Закреплённые версии: {versions}</p>"
        '<table><tr><th>Анализатор</th><th>Статус</th><th>Замечания</th><th>Блокирующие</th></tr>'
        + rows + f"</table><h2>Итог: {'PASS' if passed else 'FAIL / INCOMPLETE'}</h2>"
        + "".join(f"<p>{html.escape(value)}</p>" for value in POLICY.values()) + "</html>")
    (OUT / "summary.json").write_text(json.dumps({"passed": passed, "revision": revision,
        "branch": branch, "build": build, "reports": reports}, ensure_ascii=False, indent=2) + "\n")
    return passed


def analyze(name: str) -> int:
    report = {"name": name, "revision": tracked_revision(), "status": "ERROR", "count": 0,
              "blockers": 0, "findings": [], "policy": POLICY[name]}
    try:
        tool = {"quality": "ruff", "security": "bandit", "secrets": "gitleaks"}[name]
        report["version"] = tool_version(tool)
        with tempfile.TemporaryDirectory(prefix="racing-static-") as tmp:
            items, blockers = {"quality": quality, "security": security, "secrets": secrets}[name](Path(tmp))
        report.update(findings=items, count=len(items), blockers=blockers,
                      status="BLOCKED" if blockers else "PASS")
        code = 1 if blockers else 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError) as exc:
        report["error"] = f"Analyzer/report error ({type(exc).__name__}); check tool installation and checkout."
        code = 2
    write_report(name, report)
    summary()
    print(f"{name}: {report['status']}; findings={report['count']}; blockers={report['blockers']}")
    for x in report["findings"]:
        if x["severity"] == "BLOCKER" or (x["severity"] == x.get("confidence") == "HIGH"):
            print(f"  {x['file']}:{x['line']} {x['rule']} {x['severity']}")
    if code == 2:
        print(report["error"], file=sys.stderr)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=[*POLICY, "all", "summary"])
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    if args.mode == "summary":
        return 0 if summary() else 1
    if args.mode == "all":
        codes = [analyze(name) for name in POLICY]
        return max(codes)
    return analyze(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
