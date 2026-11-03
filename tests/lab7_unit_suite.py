"""Small deterministic unit checks for pure validation and permission rules."""
import unittest
from types import SimpleNamespace

from app.permissions import can
from app.services import parse_time_input


class ResultTimeParsingTests(unittest.TestCase):
    def test_seconds_and_minute_formats_normalize_to_hundredths(self):
        self.assertEqual(parse_time_input(' 124,567 '), 124.57)
        self.assertEqual(parse_time_input('02:04.5'), 124.5)
        self.assertEqual(parse_time_input('1:45'), 105.0)

    def test_invalid_nonpositive_nonfinite_and_out_of_range_times_are_rejected(self):
        for value in ('', '0', '-1', 'nan', 'inf', '1:60', '1:2:3', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time_input(value)


class PermissionPolicyTests(unittest.TestCase):
    @staticmethod
    def user(role, active=True):
        return SimpleNamespace(is_authenticated=True, is_active=active, role=role)

    def test_permission_matrix_allows_only_declared_roles(self):
        self.assertTrue(can('create_application', user=self.user('OWNER')))
        self.assertFalse(can('create_application', user=self.user('VIEWER')))
        self.assertTrue(can('manage_system', user=self.user('ROOT')))
        self.assertFalse(can('manage_system', user=self.user('ADMIN')))

    def test_inactive_and_unknown_permission_default_to_denied(self):
        self.assertFalse(can('account', user=self.user('OWNER', active=False)))
        self.assertFalse(can('invented_permission', user=self.user('ROOT')))


if __name__ == '__main__':
    unittest.main()
