# Backups and recovery

Recovery operations are explicit and scoped. They do not run automatically in response to untrusted telemetry. Store recovery evidence privately and practise against disposable data before a real incident.

## Unpublished source candidate

The dashboard's candidate undo is limited to a recorded Charisma worktree. It verifies the base commit, branch, file list and hashes, refuses unexpected later changes and restores only prepared files. It does not change a merged PR, a production application or a database. Pause the project and wait for an active worker cycle to finish first.

## SQLite backup

Use the SQLite backup API to make a consistent snapshot, including committed WAL data:

```sh
charisma backup --database /private/events.sqlite3 \
  --out /private/backups/events-2026-10-26.sqlite3
```

The output must be a new file. Charisma runs an integrity check and writes a private manifest alongside it containing the source's absolute path, SHA-256, byte count and creation time. Keep the database and its `.json` manifest together. A backup may contain personal or security data even when the normal dashboard is restricted.

Use this for Charisma's event/security/runner SQLite databases or another authorised SQLite file. A consistent snapshot of one database does not provide an atomic snapshot of several databases or external services. Export PostgreSQL and other engines using their own supported backup processes.

For the default container paths, perform backup inside a one-off container with the same `/data` mount so the manifest records the same path that restoration will use. Example with a private persistent backup directory mounted as `/backups`:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml run --rm --no-deps \
  -v /private/charisma-backups:/backups monitor \
  charisma backup --database /data/events.sqlite3 --out /backups/events-snapshot.sqlite3
```

UID 10001 must be able to write that private directory. Copy completed backups to encrypted off-host storage through your existing process. Backups are not encrypted by this CLI.

## Offline restoration

1. Stop every process using the target database. Isolate or stop inbound application traffic during maintenance.
2. Close/checkpoint SQLite cleanly. Do not delete live `-wal` or `-shm` files to bypass the restore guard.
3. Confirm the backup and manifest match the intended source path.
4. Compute the current target SHA-256 after it is offline and record it.
5. Restore using that exact expected checksum:

```sh
charisma restore --backup /private/backups/events-2026-10-26.sqlite3 \
  --database /private/events.sqlite3 \
  --expected-current-sha256 REPLACE_WITH_CURRENT_DATABASE_HASH --offline
```

The restore checks backup provenance/content, current target hash, integrity and absence of WAL/shared-memory files. It first writes a verified `before-...` backup of the current database, then replaces the target atomically. Keep that pre-restore file and manifest until the restored application is verified. Restart the service and inspect health and representative records.

`--offline` is your assertion that all users of the database are stopped; the tool cannot prove that no other machine/process can open it. A restore replaces newer records with the selected snapshot. The preserved pre-restore backup allows a deliberate reversal using the same safeguards. Source paths must match; cross-host/path recovery needs an independently reviewed migration procedure rather than editing provenance casually.

## Static website releases

A static release store supports already-built files with an `index.html`. It rejects links, Git history, sensitive filenames, more than 10,000 files or more than 500 MB. Keep build output outside the release store.

```sh
charisma release register --source /srv/builds/site-v1 \
  --root /srv/site-releases --id v1
charisma release activate --root /srv/site-releases --id v1 --expected-current ''

charisma release register --source /srv/builds/site-v2 \
  --root /srv/site-releases --id v2
charisma release activate --root /srv/site-releases --id v2 --expected-current v1
```

Configure your static server to serve `/srv/site-releases/current`. The command does not change your web server configuration. Release IDs are immutable, and file hashes are checked again before activation. Activation atomically replaces the `current` symlink and records the transition. The expected-current value prevents a stale operator action from silently replacing another release.

Switch back explicitly:

```sh
charisma release activate --root /srv/site-releases --id v1 --expected-current v2
```

This changes served static files only. It does not reverse a database migration, a backend deployment, CDN cache state or an installed mobile app. Monitor and test those systems separately. Keep verified previous releases and enough disk space for recovery.
