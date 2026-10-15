"""14 SQLite scenarios for the Beta 1 manual-review correction round."""
CASES = (
    'tests.test_beta1.LargeDemoTests',
    'tests.test_beta1.SeedSafetyTests',
    'tests.test_beta1.CompetitionNavigationTests',
    'tests.test_auth.AuthenticationTests.test_csrf_all_mutating_methods_and_session_rotation',
    'tests.test_alpha3.Alpha3Tests.test_access_matrix_all_panels_and_post_methods',
    'tests.test_alpha3.Alpha3Tests.test_pending_is_not_starter_then_admission_provenance_and_idempotence',
    'tests.test_alpha4.Alpha4Tests.test_ties_dnf_dsq_and_indeterminate',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(CASES)
