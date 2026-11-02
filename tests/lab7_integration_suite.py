"""Selected existing end-to-end scenarios, each with an isolated migrated DB."""
CASES = (
    'tests.test_auth.AuthenticationTests.test_register_owner_creates_new_profile',
    'tests.test_auth.AuthenticationTests.test_login_wrong_password_unknown_and_disabled_same_message',
    'tests.test_auth.AuthenticationTests.test_csrf_all_mutating_methods_and_session_rotation',
    'tests.test_auth.AuthenticationTests.test_owner_cannot_assign_horse_to_other_owner',
    'tests.test_alpha2.Alpha2Tests.test_owner_submission_initial_consent_notification_and_no_result',
    'tests.test_lab7_integration.PredictionRevisionRegression.test_stale_edit_does_not_replace_current_prediction',
    'tests.test_alpha2.Alpha2Tests.test_notification_failure_rolls_back_entire_submission_and_decision',
    'tests.test_alpha2.Alpha2Tests.test_owner_profile_edit_and_foreign_profile_denied',
    'tests.test_alpha3.Alpha3Tests.test_pending_is_not_starter_then_admission_provenance_and_idempotence',
    'tests.test_alpha3.Alpha3Tests.test_protocol_full_validation_no_early_or_unapproved_results',
    'tests.test_alpha3.Alpha3Tests.test_user_block_restore_revokes_sessions_unique_messages',
    'tests.test_alpha3.Alpha3Tests.test_audit_visibility_append_only_and_no_credential_fields',
    'tests.test_alpha4.Alpha4Tests.test_public_analytics_and_period',
    'tests.test_alpha4.Alpha4Tests.test_assessment_and_gets_do_not_write',
    'tests.test_alpha4.Alpha4Tests.test_deadline_exact_and_completed_immutable',
    'tests.test_migrations.MigrationTests.test_fresh_install_schema_matches_models_and_auth_works',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(CASES)
