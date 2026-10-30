# Persistent customer records

The app supports `CREDIT_DESK_DATA_DIR`, an absolute path on a persistent disk.
Accounts, recovery-code hashes, the database (profiles, photos, loans, payment reports and support chats),
audit fallback, documents, uploaded extracts and registered models default to that directory.
Individual CREDIT_DESK_* path overrides still take precedence.
The bundled analysis CSV stays in the source folder and is not customer state.

## Activate online

1. Connect a persistent disk/volume in the hosting service. A source-code deployment alone is insufficient.
2. Stop writes to the old instance. Download an encrypted backup using Administration > Backup and restore.
3. Set CREDIT_DESK_DATA_DIR to a writable absolute directory on the mounted disk, then restart.
4. Restore the encrypted backup as administrator on the new instance before allowing customer use.
   Alternatively migrate the complete private state directory while the app is stopped.
   Keep all path overrides on the same persistent volume. Do not put accounts, photos, databases or backups in Git.
5. Keep encrypted backups outside the hosting service too. Use one app instance for this SQLite/file storage setup.

Local default remains the existing data directory. Changing the environment setting does not copy existing records.
A newly empty directory starts a new account database; preserve and restore your backup.
The hosted disk is not provisioned or enabled by these source changes.
Support chats still follow the requested 24-hour expiry policy.

## Payment destination

Set CREDIT_DESK_PAYMENT_INSTRUCTIONS in the hosting environment to the verified instructions supplied by the team.
Until configured, customers are directed to contact support; no bank destination is invented.
Reported payments do not affect balances until an employee verifies them in Customer requests > Verify customer payments.

## Account recovery

New registrants receive a random single-use recovery code. Only its SHA-256 hash is saved.
Existing users generate a code in My account after confirming their password.
Forgot password requires the username and recovery code, consumes the code, invalidates older sessions,
and keeps any MFA requirement. No email recovery is configured.
