"""The ten selected alpha.1 review checks; the full regression suite is retained."""
import unittest


CASES = (
    'tests.test_auth.AuthenticationTests.test_register_owner_creates_new_profile',
    'tests.test_auth.AuthenticationTests.test_register_jockey_sets_trusted_initial_rating',
    'tests.test_auth.AuthenticationTests.test_register_viewer_has_no_profile',
    'tests.test_auth.AuthenticationTests.test_login_updates_timestamp_and_protects_account',
    'tests.test_auth.AuthenticationTests.test_owner_cannot_assign_horse_to_other_owner',
    'tests.test_auth.AuthenticationTests.test_admin_creates_empty_competition_but_cannot_manage_profiles',
    'tests.test_auth.AuthenticationTests.test_csrf_all_mutating_methods_and_session_rotation',
    'tests.test_concurrency.SharedThrottleTests.test_atomic_limit_across_independent_applications',
    'tests.test_migrations.MigrationTests.test_adopt_upgrade_preserves_all_legacy_rows_and_constraints',
    'verify_modernization.ModernizationTests.test_cyrillic_search_filters_sort_and_pagination',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(CASES)
