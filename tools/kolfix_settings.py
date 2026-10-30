#!/usr/bin/env python3
"""don_kolfix host-side, byte-preserving settings backup and delivery.

No KoLmafia/JVM filesystem access is attempted. The archive contains exact
copies of selected settings files plus a SHA-256 manifest. Does not upload data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Optional
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

VERSION = 1
STATUS_SCHEMA = "1"
STATUS_FILENAME = "kolfix-backup-status.txt"
ROLLBACK_FORMAT = "don-kolfix-rollback-v2"
SNAPSHOT_RE = re.compile(r"^\d{8}T\d{12}Z$")
MAX_FILE_SIZE = 32 * 1024 * 1024
MAX_FILES = 200
GLOBAL_FILES = (
    "GLOBAL_aliases.txt", "GLOBAL_prefs.txt", "GLOBAL_prefs.bak", "GLOBAL_moods.txt",
)
PLAYER_SUFFIXES = ("_prefs.txt", "_moods.txt", "_prefs.bak")
PLAYER_RE = re.compile(r"^[A-Za-z0-9_ -]{1,80}$")

class KolfixError(Exception):
    pass


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> bool:
    if name in GLOBAL_FILES:
        return True
    return any(name.endswith(s) and PLAYER_RE.fullmatch(name[:-len(s)]) for s in PLAYER_SUFFIXES)


def files_to_backup(settings: Path, players: list[str] | None) -> list[str]:
    if players:
        selected = {p.lower() for p in players}
        for p in selected:
            if not PLAYER_RE.fullmatch(p) or p.lower() == "global":
                raise KolfixError(f"Invalid character name: {p!r}")
    else:
        selected = set()
        for p in settings.iterdir():
            for suffix in PLAYER_SUFFIXES:
                if p.name.endswith(suffix) and p.name not in GLOBAL_FILES:
                    candidate = p.name[:-len(suffix)]
                    if PLAYER_RE.fullmatch(candidate):
                        selected.add(candidate)
    if len(selected) > 60:
        raise KolfixError("Too many characters discovered (>60); provide --player")
    result = list(GLOBAL_FILES)
    for p in sorted(selected):
        result.extend(p + x for x in PLAYER_SUFFIXES)
    return result


def read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise KolfixError(f"Not a regular file or is a symlink: {path}")
    before = path.stat()
    if before.st_size > MAX_FILE_SIZE:
        raise KolfixError(f"Refusing oversized settings file: {path}")
    data = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise KolfixError(f"Settings file changed during backup: {path}; try again when KoLmafia is closed")
    if len(data) != before.st_size:
        raise KolfixError(f"Incomplete read: {path}")
    return data


def ensure_dir(path: Path) -> None:
    # Reject symlinked destinations in the protected scope.
    if path.is_symlink():
        raise KolfixError(f"Symlinked destination is not allowed: {path}")
    if path.exists() and not path.is_dir():
        raise KolfixError(f"Destination is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def backup(source: Path, output_dir: Path, players: list[str] | None) -> Path:
    settings = source / "settings"
    if not settings.is_dir() or settings.is_symlink():
        raise KolfixError(f"Expected a real KoLmafia settings directory at {settings}")
    names = files_to_backup(settings, players)
    if len(names) > MAX_FILES:
        raise KolfixError("Too many settings files")
    found: dict[str, bytes] = {}
    missing: list[str] = []
    for name in names:
        path = settings / name
        if path.is_symlink():
            raise KolfixError(f"Symlinked settings file: {path}")
        if path.exists():
            found[name] = read_regular(path)
        else:
            missing.append(name)
    if not found:
        raise KolfixError("No matching files found; refusing empty archive")
    ensure_dir(output_dir)
    archive = output_dir / f"kolfix-settings-{stamp()}.zip"
    manifest = {
        "format": "don-kolfix-settings-v1", "version": VERSION,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": [{"path": f"settings/{n}", "bytes": len(data), "sha256": digest(data)}
                  for n, data in sorted(found.items())],
        "missing": sorted(missing),
    }
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            with zipfile.ZipFile(f, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
                for name, data in sorted(found.items()):
                    z.writestr("settings/" + name, data)
                z.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        verify(archive)
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    publish_status(source, "backup", len(found), manifest["created_utc"],
                   archive_sha256=digest(archive.read_bytes()))
    print(f"ARCHIVE: {archive}")
    print(f"FILES: {len(found)} copied byte-for-byte; {len(missing)} optional/missing")
    for item in missing:
        print("MISSING:", item)
    return archive


def verify(archive: Path) -> tuple[dict, dict[str, bytes]]:
    if archive.is_symlink() or not archive.is_file():
        raise KolfixError(f"Archive missing or is a symlink: {archive}")
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or len(names) > MAX_FILES + 1:
            raise KolfixError("Duplicate or excessive ZIP members")
        if names.count("manifest.json") != 1:
            raise KolfixError("Manifest missing")
        manifest_entry = z.getinfo("manifest.json")
        if manifest_entry.file_size > 128000:
            raise KolfixError("Oversized manifest")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != "don-kolfix-settings-v1" or manifest.get("version") != VERSION:
            raise KolfixError("Unsupported manifest")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise KolfixError("Manifest has no files")
        expected = {"manifest.json"}
        checked: dict[str, bytes] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise KolfixError("Bad manifest file entry")
            filename = entry.get("path")
            if not isinstance(filename, str) or not filename.startswith("settings/") or not safe_name(filename.removeprefix("settings/")):
                raise KolfixError(f"Unexpected archive path: {filename!r}")
            if filename in expected:
                raise KolfixError("Duplicate file in manifest")
            expected.add(filename)
            info = z.getinfo(filename)
            if info.is_dir() or info.file_size > MAX_FILE_SIZE:
                raise KolfixError(f"Invalid archive member size/type: {filename}")
            data = z.read(filename)
            if len(data) != entry.get("bytes") or digest(data) != entry.get("sha256"):
                raise KolfixError(f"Hash mismatch: {filename}")
            checked[filename] = data
        if set(names) != expected:
            raise KolfixError("Unexpected ZIP members")
        missing = manifest.get("missing", [])
        if not isinstance(missing, list) or any(not isinstance(n, str) or not safe_name(n) for n in missing):
            raise KolfixError("Invalid missing-file manifest entries")
    return manifest, checked


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise KolfixError(f"Refusing nonregular target: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".kolfix-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



def publish_status(root: Path, action: str, files: int, archive_created: str = "",
                   rollback_snapshot: str = "", archive_sha256: str = "") -> None:
    """Publish only a small public-metadata snapshot for KoLmafia's read-only gCLI.

    Never include preference values, character names, absolute filesystem paths,
    secrets, archive member names or output from Docker.
    """
    allowed = {"backup", "verified", "staged", "restored", "rolled-back"}
    if action not in allowed or files < 0 or files > MAX_FILES:
        raise KolfixError("Invalid public status payload")
    if rollback_snapshot and not SNAPSHOT_RE.fullmatch(rollback_snapshot):
        raise KolfixError("Invalid rollback snapshot reference")
    # Preserve the meaning of a successful settings operation even if status
    # publishing is unavailable. Never turn a successful restore into an error.
    try:
        if root.is_symlink() or not root.is_dir():
            raise KolfixError("Invalid KoLmafia root for status")
        folder = root / "data"
        ensure_dir(folder)
        rows = {
            "schema": STATUS_SCHEMA,
            "action": action,
            "result": "success",
            "updated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files": str(files),
            "archive_created_utc": archive_created,
            "archive_sha256": archive_sha256,
            "rollback": "available" if rollback_snapshot else "none",
            "rollback_snapshot": rollback_snapshot,
        }
        atomic_write(folder / STATUS_FILENAME,
                     "".join(f"{k}\t{v}\n" for k, v in rows.items()).encode("utf-8"))
    except (OSError, KolfixError) as exc:
        print(f"WARNING: could not publish read-only backup status: {exc}", file=sys.stderr)


def build_rollback_snapshot(target: Path, replacements: dict[str, bytes | None],
                            previous_sha256: str = "") -> str:
    """Preflight + snapshot all existing destination bytes before any mutation."""
    snapshot = stamp()
    imports = target / "kolfix-imports"
    rollback_root = imports / "rollback"
    if imports.is_symlink() or rollback_root.is_symlink():
        raise KolfixError("Symlinked rollback parent")
    folder = rollback_root / snapshot
    ensure_dir(folder / "settings")
    entries = []
    for relative, data in sorted(replacements.items()):
        destination = target / relative
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise KolfixError(f"Unsafe destination: {destination}")
        existing = read_regular(destination) if destination.exists() else None
        if existing is not None:
            atomic_write(folder / relative, existing)
        entries.append({"path": relative, "existed": existing is not None,
                        "previous_sha256": digest(existing) if existing is not None else "",
                        "applied_sha256": digest(data) if data is not None else "__ABSENT__"})
    manifest = {"format": ROLLBACK_FORMAT, "version": 2,
                "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "archive_sha256": previous_sha256, "files": entries}
    atomic_write(folder / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return snapshot


def rollback_snapshot(target: Path, snapshot: str, apply: bool, stopped: bool,
                      container: Optional[str], legacy: bool = False) -> None:
    """Undo a previous restore with the same guards used by deliver().

    Legacy v1.1 rollback folders lack delete/change metadata: only known
    originals can be restored, with explicit --legacy acknowledgement.
    """
    if not SNAPSHOT_RE.fullmatch(snapshot):
        raise KolfixError("Invalid snapshot identifier")
    if target.is_symlink() or not target.is_dir():
        raise KolfixError("Target root is missing or symlinked")
    if (target / "settings").is_symlink():
        raise KolfixError("Target settings directory is symlinked")
    imports = target / "kolfix-imports"
    rollback_root = imports / "rollback"
    if imports.is_symlink() or rollback_root.is_symlink():
        raise KolfixError("Symlinked rollback parent")
    folder = rollback_root / snapshot
    if folder.is_symlink() or not folder.is_dir():
        raise KolfixError("Rollback snapshot directory is missing or symlinked")
    if (folder / "settings").is_symlink():
        raise KolfixError("Rollback settings directory is symlinked")
    meta_path = folder / "manifest.json"
    replacements: dict[str, bytes | None] = {}
    expected_post: dict[str, str] = {}
    if meta_path.exists():
        meta = json.loads(read_regular(meta_path))
        if meta.get("format") != ROLLBACK_FORMAT or meta.get("version") != 2:
            raise KolfixError("Unrecognized rollback manifest")
        entries = meta.get("files")
        if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
            raise KolfixError("Empty/invalid rollback manifest")
        for entry in entries:
            rel = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(rel, str) or not rel.startswith("settings/") or not safe_name(rel[9:]) or rel in replacements:
                raise KolfixError("Unsafe or duplicate rollback file")
            original = folder / rel
            if entry.get("existed") is True:
                data = read_regular(original)
                if digest(data) != entry.get("previous_sha256"):
                    raise KolfixError("Rollback original hash mismatch")
                replacements[rel] = data
            elif entry.get("existed") is False and not original.exists() and not original.is_symlink():
                replacements[rel] = None
            else:
                raise KolfixError("Invalid previous-file state")
            expected_post[rel] = entry.get("applied_sha256", "")
            if expected_post[rel] != "__ABSENT__" and not re.fullmatch(r"[0-9a-f]{64}", expected_post[rel]):
                raise KolfixError("Invalid applied hash in rollback manifest")
    else:
        if not legacy:
            raise KolfixError("Legacy snapshot lacks a manifest; pass --legacy to restore known previous files only")
        snapshots = folder / "settings"
        if not snapshots.is_dir():
            raise KolfixError("Missing legacy rollback settings")
        for entry in snapshots.iterdir():
            if not safe_name(entry.name):
                raise KolfixError("Unsafe legacy rollback filename")
            replacements["settings/" + entry.name] = read_regular(entry)
        if not replacements:
            raise KolfixError("Empty legacy rollback")

    if not apply:
        print(f"ROLLBACK PREVIEW: {len(replacements)} settings entries in snapshot {snapshot}")
        print("No settings changed. To restore: --apply --stopped --container NAME")
        return
    if not stopped:
        raise KolfixError("Rollback requires --stopped acknowledgement")
    if container:
        verify_stopped_container(target, container)
    elif list((target / "sessions").glob("active_session.*")):
        raise KolfixError("Session markers found; use --container NAME after Docker stops")
    for rel, data in replacements.items():
        dest = target / rel
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise KolfixError("Unsafe rollback target")
        if rel in expected_post:
            expected = expected_post[rel]
            matching = (not dest.exists()) if expected == "__ABSENT__" else (dest.exists() and digest(read_regular(dest)) == expected)
            if not matching:
                raise KolfixError(f"Target diverged since restore: {rel}; refusing rollback")
        if data is None and not dest.exists():
            raise KolfixError("Expected newly-created restore file no longer exists")
    # Guarantee a redo path (another snapshot) before making any change.
    redo = build_rollback_snapshot(target, replacements) if replacements else ""
    if container:
        verify_stopped_container(target, container)
    for rel, original in replacements.items():
        dest = target / rel
        if original is None:
            dest.unlink()
        else:
            atomic_write(dest, original)
    print(f"ROLLED BACK: {len(replacements)} settings entries from {snapshot}")
    if redo:
        print(f"PRE-ROLLBACK SETTINGS PRESERVED: {target / 'kolfix-imports' / 'rollback' / redo}")
    publish_status(target, "rolled-back", len(replacements), rollback_snapshot=redo)
    print("NOTE: restart KoLmafia to reload the restored preferences")


def _docker_json(args: list[str]) -> object:
    """Query Docker directly; never trust a user-set boolean for container state."""
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KolfixError(f"Cannot verify Docker runtime: {exc}") from exc
    if result.returncode:
        raise KolfixError(
            f"Docker verification failed ({' '.join(args[:2])}): "
            + (result.stderr.strip() or "unknown error")
        )
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise KolfixError("Docker returned an invalid inspection response") from exc


def _docker_ps_ids() -> list[str]:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KolfixError(f"Cannot inspect running Docker containers: {exc}") from exc
    if result.returncode:
        raise KolfixError("Cannot inspect running Docker containers: " + result.stderr.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _mount_overlaps_target(mount: dict, target: Path) -> bool:
    """An active container with this directory or a parent/child bind mount is unsafe."""
    if mount.get("Type") != "bind" or not mount.get("Source"):
        return False
    source = Path(mount["Source"]).resolve()
    return source == target or source in target.parents or target in source.parents


def verify_stopped_container(target: Path, container: str) -> None:
    """Require a stopped container owning the mounted KoLmafia data directory.

    A leftover sessions/active_session.* is *not* a process-liveness test.
    This Docker confirmation permits restoration without deleting those markers.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise KolfixError("Invalid Docker container name")
    inspection = _docker_json(["inspect", container])
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise KolfixError("Expected exactly one inspected Docker container")
    c = inspection[0]
    state = c.get("State") or {}
    if state.get("Running") is not False or state.get("Status") not in ("exited", "created"):
        raise KolfixError(f"Docker container is not stopped: {container}")
    mounts = c.get("Mounts") or []
    actual = target.resolve(strict=True)
    if not any(
        m.get("Type") == "bind"
        and m.get("Destination") == "/home/kolmafia/.kolmafia"
        and Path(m.get("Source", "")).resolve() == actual
        for m in mounts
    ):
        raise KolfixError(
            "Container does not bind-mount the specified --target at "
            "/home/kolmafia/.kolmafia; refusing restore"
        )
    running = _docker_ps_ids()
    if running:
        other = _docker_json(["inspect", *running])
        if not isinstance(other, list):
            raise KolfixError("Cannot verify other running container mounts")
        for c in other:
            if any(_mount_overlaps_target(m, actual) for m in (c.get("Mounts") or [])):
                raise KolfixError(
                    "Another running Docker container has an overlapping bind mount "
                    "on the target; refusing restore"
                )


def deliver(
    archive: Path, target: Path, apply: bool, stopped: bool,
    container: Optional[str] = None,
) -> None:
    _, data = verify(archive)
    if target.is_symlink() or not target.is_dir():
        raise KolfixError(f"Target KoLmafia root does not exist or is a symlink: {target}")
    settings = target / "settings"
    if settings.is_symlink():
        raise KolfixError("Target settings is symlinked")
    if apply and not stopped:
        raise KolfixError("For an active settings replacement, close KoLmafia first and pass --stopped")
    markers = sorted((target / "sessions").glob("active_session.*")) if apply else []
    if apply and container:
        # Verifiable stop + bind mount identity, rather than stale marker existence.
        verify_stopped_container(target, container)
        if markers:
            print(
                f"NOTICE: {len(markers)} session marker(s) retained; Docker confirms "
                "the selected container is stopped and owns the target."
            )
    elif markers:
        raise KolfixError(
            "Session marker(s) found; to distinguish stale markers from an "
            "active session, re-run with --container NAME after docker stop"
        )
    date_tag = stamp()
    if apply:
        # Preflight before touching any file.
        if settings.exists() and not settings.is_dir():
            raise KolfixError("Target settings is not a directory")
        for relative in data:
            destination = target / relative
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise KolfixError(f"Unsafe target file: {destination}")
        snapshot = build_rollback_snapshot(target, data, digest(archive.read_bytes()))
        rollback = target / "kolfix-imports" / "rollback" / snapshot
        ensure_dir(settings)
        if container:
            verify_stopped_container(target, container)
        for relative, content in data.items():
            atomic_write(target / relative, content)
        publish_status(target, "restored", len(data), rollback_snapshot=snapshot,
                       archive_sha256=digest(archive.read_bytes()))
        print(f"RESTORED: {len(data)} files to {settings}")
        print(f"PREVIOUS SETTINGS COPIED TO: {rollback}")
        print("NOTE: restart KoLmafia so it reads the restored settings")
    else:
        imports = target / "kolfix-imports"
        if imports.is_symlink():
            raise KolfixError("Symlinked staging parent")
        staged = imports / f"staged-{date_tag}"
        ensure_dir(staged / "settings")
        for relative, content in data.items():
            atomic_write(staged / relative, content)
        publish_status(target, "staged", len(data), archive_sha256=digest(archive.read_bytes()))
        print(f"STAGED: {len(data)} files at {staged}")
        print("Target settings were NOT replaced. Use deliver --apply --stopped after KoLmafia exits.")


def main() -> int:
    p = argparse.ArgumentParser(description="don_kolfix host-side KoLmafia settings backup and delivery")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="Create a byte-exact ZIP archive of selected settings")
    b.add_argument("--source", type=Path, default=Path.home() / ".kolmafia", help="KoLmafia home (not settings/)")
    b.add_argument("--out", type=Path, default=Path.home() / ".local/share/don_kolfix/backups")
    b.add_argument("--player", action="append", help="Limit to this character (repeatable); default all discovered characters")
    b.add_argument("--target", type=Path, help="Also stage a verified copy inside another KoLmafia root (never overwrite settings)")
    v = sub.add_parser("verify", help="Verify archive path whitelist, SHA-256 and byte sizes")
    v.add_argument("archive", type=Path)
    d = sub.add_parser("deliver", help="Stage archive, or apply to a stopped KoLmafia directory")
    d.add_argument("archive", type=Path)
    d.add_argument("--target", type=Path, required=True, help="KoLmafia home, e.g. kolmafia-xpra/data")
    d.add_argument("--apply", action="store_true", help="Replace selected target settings with archive contents")
    d.add_argument("--stopped", action="store_true", help="Acknowledge KoLmafia is fully stopped (required with --apply)")
    d.add_argument(
        "--container", help="Verify this Docker container is stopped and bind-mounts "
        "the target; allows stale session markers to remain untouched"
    )
    rb = sub.add_parser("rollback", help="Preview or undo a previous guarded restore")
    rb.add_argument("--target", type=Path, required=True)
    rb.add_argument("--snapshot", required=True, help="Timestamp from the rollback directory")
    rb.add_argument("--apply", action="store_true")
    rb.add_argument("--stopped", action="store_true")
    rb.add_argument("--container")
    rb.add_argument("--legacy", action="store_true", help="Accept v1.1 folder without manifest; restore only saved originals")
    st = sub.add_parser("status", help="Read the last published host operation without mutation")
    st.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == "backup":
            archive = backup(args.source.expanduser(), args.out.expanduser(), args.player)
            if args.target:
                deliver(archive, args.target.expanduser(), False, False)
        elif args.command == "verify":
            mf, content = verify(args.archive.expanduser())
            print(f"VERIFIED: {len(content)} files; created {mf['created_utc']}")
        elif args.command == "status":
            root = args.root.expanduser()
            path = root / "data" / STATUS_FILENAME
            if path.is_symlink() or not path.is_file():
                print("No host backup status published for this KoLmafia root")
            else:
                print(read_regular(path).decode("utf-8"), end="")
        elif args.command == "rollback":
            rollback_snapshot(args.target.expanduser(), args.snapshot, args.apply,
                              args.stopped, args.container, args.legacy)
        elif args.command == "deliver":
            deliver(args.archive.expanduser(), args.target.expanduser(), args.apply, args.stopped, args.container)
    except (KolfixError, OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
