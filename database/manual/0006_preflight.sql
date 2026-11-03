-- Run in an explicit read-only transaction against the confirmed STAGE database.
SELECT current_database(), current_setting('server_version');
SELECT version_num FROM alembic_version;
SELECT count(*) AS competitions_before FROM public.competitions;
-- Expected version: 0005_predictions; upgrade is performed via Alembic, not this file.
