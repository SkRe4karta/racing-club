"""Preflight accepts restored PostgreSQL CHECK syntax and rejects real drift."""
import copy
import unittest

from scripts.ci.compare_schema import differences


class SchemaComparisonTests(unittest.TestCase):
    def test_restore_rewrite_and_security_relevant_drift(self):
        source = {'revision': '0005_predictions', 'postgres': '18.6', 'structure': {
            'tables': {'users': {'checks': [{'name': 'ck_users_status', 'sqltext':
                "status::text = ANY (ARRAY['active'::character varying, 'disabled'::character varying]::text[])"}],
                'columns': [{'name': 'status', 'nullable': False}]}}}}
        restored = copy.deepcopy(source)
        check = restored['structure']['tables']['users']['checks'][0]
        check['sqltext'] = "status::text = ANY (ARRAY['active'::character varying::text, 'disabled'::character varying::text])"
        self.assertEqual(differences(source, restored), [])
        for changed in ('active', 'disabled'):
            drift = copy.deepcopy(restored)
            drift['structure']['tables']['users']['checks'][0]['sqltext'] = check['sqltext'].replace(changed, 'unexpected')
            self.assertTrue(differences(source, drift))
        drift = copy.deepcopy(restored)
        drift['structure']['tables']['users']['columns'][0]['nullable'] = True
        self.assertTrue(differences(source, drift))
        restored['revision'] = 'unreviewed_revision'
        self.assertTrue(differences(source, restored))
