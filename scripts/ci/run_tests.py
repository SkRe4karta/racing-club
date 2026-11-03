#!/usr/bin/env python3
"""Run a named unittest suite and emit a JUnit XML report without extra packages."""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import xml.etree.ElementTree as ET


class JUnitResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.started = {}
        self.outcomes = {}

    def startTest(self, test):
        self.started[test] = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        self.cases.append((test, time.monotonic() - self.started.pop(test), self.outcomes.pop(test, None)))
        super().stopTest(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test] = ('failure', self.failures[-1][1])

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test] = ('error', self.errors[-1][1])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test] = ('skipped', reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = 'failure' if issubclass(err[0], test.failureException) else 'error'
            self.outcomes[test] = (kind, self._exc_info_to_string(err, subtest))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.outcomes[test] = ('skipped', 'Expected failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes[test] = ('failure', 'Unexpected success')



def main(name):
    modules = {'unit': 'tests.lab7_unit_suite', 'integration': 'tests.lab7_integration_suite',
               'postgres': 'tests.beta1_postgres_suite', 'ci-integration': 'tests.lab7_ci_suite',
               'lab8-sqlite': 'tests.test_lab8', 'lab8-postgres': 'tests.test_lab8'}
    if name not in modules:
        raise SystemExit('Usage: python scripts/ci/run_tests.py {unit|integration|ci-integration|postgres}')
    output = Path(os.environ.get('LAB7_REPORT_DIR', 'artifacts/tests')) / f'{name}.xml'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    if name == 'postgres' and not os.environ.get('RACING_TEST_POSTGRES_URL'):
        raise SystemExit('postgres suite requires an isolated RACING_TEST_POSTGRES_URL')
    sha = os.environ.get('LAB7_GIT_SHA') or subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True
    ).strip()
    suite = unittest.defaultTestLoader.loadTestsFromName(modules[name])
    if name == 'unit':
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName('tests.test_schema_comparison'))
    stream = sys.stderr if not sys.stdout.isatty() else sys.stdout
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=JUnitResult)
    try:
        result = runner.run(suite)
    except KeyboardInterrupt:
        root = ET.Element('testsuite', name=name, tests='1', errors='1', failures='0')
        props = ET.SubElement(root, 'properties')
        ET.SubElement(props, 'property', name='git.sha', value=sha)
        case = ET.SubElement(root, 'testcase', classname='runner', name='interrupted')
        ET.SubElement(case, 'error').text = 'Test process interrupted; no successful result.'
        ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
        return 130
    root = ET.Element('testsuite', name=name, tests=str(result.testsRun),
        failures=str(sum(bool(row[2] and row[2][0] == 'failure') for row in result.cases)),
        errors=str(sum(bool(row[2] and row[2][0] == 'error') for row in result.cases)),
        skipped=str(sum(bool(row[2] and row[2][0] == 'skipped') for row in result.cases)), time=f'{sum(row[1] for row in result.cases):.3f}')
    properties = ET.SubElement(root, 'properties')
    ET.SubElement(properties, 'property', name='git.sha', value=sha)
    ET.SubElement(properties, 'property', name='database', value='none' if name == 'unit' else ('PostgreSQL' if os.environ.get('RACING_TEST_POSTGRES_URL') else 'SQLite'))
    for test, duration, outcome in result.cases:
        case = ET.SubElement(root, 'testcase', classname=test.__class__.__module__ + '.' + test.__class__.__name__,
                             name=test._testMethodName, time=f'{duration:.3f}')
        if outcome:
            kind, message = outcome
            if kind == 'skipped':
                ET.SubElement(case, kind, message=message)
            else:
                node = ET.SubElement(case, kind, message=message.splitlines()[-1][:500])
                node.text = message
    temporary = output.with_suffix('.xml.tmp')
    ET.ElementTree(root).write(temporary, encoding='utf-8', xml_declaration=True)
    temporary.replace(output)
    print(f'JUnit report: {output}; Git SHA: {sha}')
    if not os.environ.get('LAB7_REPORT_DIR'):
        print(f'##teamcity[importData type="junit" path="{output}"]')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ''))
