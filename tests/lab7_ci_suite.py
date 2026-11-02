"""Preserve Beta regressions while running shared Lab 7 cases only once."""
import unittest


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def load_tests(loader, tests, pattern):
    selected = {}
    for module in ('tests.lab7_integration_suite', 'tests.beta1_corrections_suite'):
        for test in flatten(loader.loadTestsFromName(module)):
            selected.setdefault(test.id(), test)
    return unittest.TestSuite(selected.values())
