# KoLmafia settings backup, restore, and rollback (host-side)

The `don_kolfix` host companion archives **original settings bytes** from a KoLmafia home. It does not replace the actual `GLOBAL_aliases.txt` with any refined alias template. The GCLI status reader is read-only and does not execute Python, Docker, preference writes, or game actions.

## Protected scope

`settings/GLOBAL_aliases.txt`, `GLOBAL_prefs.txt`, `GLOBAL_prefs.bak`, `GLOBAL_moods.txt`, and all discovered `<player>_prefs.txt`, `<player>_moods.txt`, `<player>_prefs.bak`. Missing optional files are listed. The original alias file remains tab-separated and is never normalized.

These files can contain sensitive information. Archives are private, unencrypted ZIPs (mode 0600) stored outside Git. Do **not** commit archives, settings contents, or status files to GitHub.

## Host commands

Use your existing setup:

```bash
KOLFIX="$HOME/repos/donCannoli-burns/don_kolfix/tools/kolfix-settings"
SOURCE="$HOME/.kolmafia"
XPRA="$HOME/repos/es-3581100/kolmafia-xpra/data"
CONTAINER=kolmafia-xpra-kolmafia-1

# 1. Archive originals, verify hashes and stage into XPRA without replacing settings.
"$KOLFIX" backup --source "$SOURCE" --target "$XPRA"
# Copy the printed ARCHIVE path into ARCHIVE variable:
ARCHIVE="$HOME/.local/share/don_kolfix/backups/kolfix-settings-EXACT-TIMESTAMP.zip"

# 2. Verify an existing archive (read-only).
"$KOLFIX" verify "$ARCHIVE"

# 3. Inspect the last recorded host action for XPRA (read-only).
"$KOLFIX" status --root "$XPRA"

# 4. Explicitly replace settings, only after stopping KoLmafia.
(
  set -e
  docker stop "$CONTAINER"
  trap 'docker start "$CONTAINER" >/dev/null' EXIT
  "$KOLFIX" verify "$ARCHIVE"
  "$KOLFIX" deliver "$ARCHIVE" --target "$XPRA" --apply --stopped --container "$CONTAINER"
)

# 5. Preview a rollback, using the timestamp printed in its rollback directory.
SNAPSHOT=20261030T220202789948Z  # replace with your actual snapshot ID
"$KOLFIX" rollback --target "$XPRA" --snapshot "$SNAPSHOT"

# 6. Undo the previous restore (stop container again before applying).
(
  set -e
  docker stop "$CONTAINER"
  trap 'docker start "$CONTAINER" >/dev/null' EXIT
  "$KOLFIX" rollback --target "$XPRA" --snapshot "$SNAPSHOT" --apply --stopped --container "$CONTAINER"
)
```

### Existing v1.1 snapshots

The first rollback from 2026-10-30 was made by v1.1 and has no rollback manifest. Use `--legacy` for such folders after reviewing the snapshot. This restores **only saved previous files** and does **not** remove files that did not exist before the old restore. A redo snapshot is created first.

```bash
"$KOLFIX" rollback --target "$XPRA" --snapshot "$SNAPSHOT" --legacy
# ... for application while container is stopped:
"$KOLFIX" rollback --target "$XPRA" --snapshot "$SNAPSHOT" --legacy --apply --stopped --container "$CONTAINER"
```

### Data safety and limitations

- `backup` never changes `settings/`; `backup --target` stages under `kolfix-imports/staged-*` only.
- `deliver --apply` and `rollback --apply` require `--stopped`; when session markers exist, also require `--container NAME` with Docker-verified stopped state and matching bind mount.
- Existing destination files are backed up under `kolfix-imports/rollback/TIMESTAMP/settings` before mutation. New v2 snapshot manifests additionally record whether each destination existed and the expected applied hash. Rollback refuses to clobber changed files.
- Restore and rollback are **not whole-directory transactions**; each destination file is written atomically. A failure partway through requires examination and manual recovery from the preserved snapshots.
- The Docker guard confirms the named container is stopped and that no other **running Docker container** has an overlapping bind mount. It cannot prove a separate non-Docker KoLmafia process is stopped. Close any native KoLmafia instance sharing that directory.
- A v1.1 legacy snapshot cannot reconstruct files newly introduced by the old restore. It can restore the previously existing files only.
- The host utility only publishes a small non-sensitive `data/kolfix-backup-status.txt` file: the action type, UTC timestamp, file count, optional archive digest and rollback snapshot ID. This is a **last-successful-operation report**, not live Docker state or archive health.

## KoLmafia GCLI (read-only)

Install `scripts/kolfix_backup_status.ash` into the active KoLmafia `scripts/` directory. Then either:

```text
call kolfix_backup_status.ash
kolfix backupStatus
```

The second form requires the rebuilt `don_kolfix` entrypoint with the `backupStatus` flag. To add the short direct command, enter once in gCLI:

```text
alias backup-status => call kolfix_backup_status.ash;
```

Afterward, just enter `backup-status`. This command **does not create backups or restore anything**; it reads the last status snapshot written by the Linux host utility into the selected KoLmafia home's `data/` directory. If no status has yet been published to that installation, it says so without attempting recovery or fabrication.

## Developer checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tools/kolfix_settings.py
yarn build
```

Smoke in your **test** KoLmafia with `call kolfix_backup_status.ash` and `kolfix backupStatus`; verify only read-only status text appears. Do not perform a live restore just to test the GCLI reader.
