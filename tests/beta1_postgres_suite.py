"""Five distinct PostgreSQL migration, constraints and transaction scenarios."""
CASES = (
    'tests.test_migrations.MigrationTests.test_fresh_install_schema_matches_models_and_auth_works',
    'tests.test_migrations.MigrationTests.test_adopt_upgrade_preserves_all_legacy_rows_and_constraints',
    'tests.test_beta1.PostgresDemoTests.test_import_constraints_and_preservation',
    'tests.test_alpha4.Alpha4DatabaseTests.test_concurrent_create_one_prediction',
    'tests.test_alpha4.Alpha4MigrationTests.test_populated_alpha3_upgrade',
)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromNames(CASES)
