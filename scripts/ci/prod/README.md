# PROD Release — activation requires owner action

The new code is preparation, not authorization to migrate/deploy PROD.
`runner --mode check` fetches actual DEV/STAGE metadata and digest from TeamCity,
checks the exact snapshot dependency, then returns an explicit read-only receipt.
It does not open SSH, acquire an identity, stop web or access the production DB.
`--mode release` additionally requires the isolated PROD key in the TeamCity SSH
Agent and console-verified known_hosts on RACING-CI. The root-owned wrapper on
PROD validates the owner approval and all target settings; the CI build cannot
read or replace those root-owned files.

The owner approval binds SHA256 of the complete request (SHA, digest, DEV/STAGE
IDs, source fingerprint/revision, nonce, expected target structure hash), owner,
UTC maintenance window and recovery plan. No default release approval exists.
Runtime parameters cannot supply an approval. Only authorized release operators
may run/edit the dedicated TeamCity project. No VCS or finish-build trigger.

Separate SSH identity name: `racing_prod_cd`, never `racing_stage_cd`.
The key is not created/copied by this task. Owner must provision a distinct key,
install only its public key for zelyonka via the VM console, and verify the PROD
host fingerprint independently via console. Put the key in the dedicated TC
PROD project, add its SSH Agent feature, set its public fingerprint as the
non-secret `PROD_SSH_KEY_FINGERPRINT` parameter, and install a fixed known_hosts
file at `/data/teamcity_agent/conf/racing-prod-known-hosts` on RACING-CI.
No private key or password belongs in Git/artifacts/build scripts/parameters.

Install reviewed source, helper files and compose.prod-release.yaml under
/opt/racing-club-prod-release, root-owned and unwritable by the SSH user.
/usr/local/sbin/racing-prod-release must be a root-owned wrapper invoking
`python3 -m scripts.ci.prod.transaction` there, with fixed clean PYTHONPATH.
A narrowly scoped sudoers rule may allow zelyonka to invoke ONLY that fixed
wrapper, without arbitrary arguments or another command. Do not grant docker
or general passwordless sudo just for this pipeline. Provisioning requires the
owner; this task does not install anything on PROD.

The complete owner approval must be installed root-owned mode 600 on PROD at
`/etc/racing-club/prod-release-approval.json`, not supplied by build parameters.

Private PROD settings /etc/racing-club/prod-release.json:
state_dir:<protected backup/state directory>, db_container:racing-club-prod-db-1,
web_container:racing-club-prod-web-1, network:<confirmed existing PROD network>,
database_url:<existing private PROD URL>,secret_key:<persistent secure session key>,
web_bind:<confirmed existing binding>,web_port:<confirmed existing port>,secure_cookie:<explicit boolean>.
Use actual inspected values; do not infer the network, port or session key.
The wrapper verifies host, container, network alias, published port, PG18,
actual database name, approved schema fingerprint/history and monotonic build ID.
It never recreates PostgreSQL or removes any Docker volume.

Transaction: lock -> read-only preflight -> quiesce web -> all-table hashes ->
free-space check -> fresh custom pg_dump600 -> SHA256 -> isolated PG18 restore ->
schema/hash equality -> candidate migration + model check on copy -> target/hash
checks -> recheck approval/window/source -> live migration -> target/hash checks ->
web-only compose deployment/health -> immutable image check -> success receipt.
Any backup/restore/rehearsal failure blocks live DDL. Before DDL failures restart
old web. After DDL failure: stop and use the verified backup/recovery plan; no
automatic destructive downgrade/restore. Private dumps and DB logs remain private.
