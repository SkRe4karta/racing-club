"""14 selected SQLite scenarios for Beta 1; all existing tests remain available."""
CASES = (
    'tests.test_beta1.LargeDemoTests',
    'tests.test_beta1.SeedSafetyTests',
    'tests.test_auth.AuthenticationTests.test_csrf_all_mutating_methods_and_session_rotation',
    'tests.test_auth.AuthenticationTests.test_disabled_user_loses_existing_session_and_permissions',
    'tests.test_auth.AuthenticationTests.test_owner_cannot_assign_horse_to_other_owner',
    'tests.test_alpha3.Alpha3Tests.test_access_matrix_all_panels_and_post_methods',
    'tests.test_alpha3.Alpha3Tests.test_pending_is_not_starter_then_admission_provenance_and_idempotence',
    'tests.test_alpha4.Alpha4Tests.test_ties_dnf_dsq_and_indeterminate',
    'tests.test_alpha4_ui.UICorrectionTests.test_password_change_revokes_all_sessions_and_old_password',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(CASES)
