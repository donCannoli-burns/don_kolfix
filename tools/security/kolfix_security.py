#!/usr/bin/env python3
"""Host-only don_kolfix security gate. Python 3.11+, stdlib only.

This is NOT a packet filter, TLS MITM, or KoLmafia gameplay hook. A local Git
pre-push hook is enforceable for normal pushes; a GitHub branch ruleset is
required to prohibit --no-verify or other clients from bypassing it.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile

VERSION = "0.1.2"
MIN_PYTHON = (3, 11)
MAX_BLOB = 8 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_OBJECTS = 40000
MAX_ZIP_MEMBERS = 500
MAX_ZIP_UNPACKED = 24 * 1024 * 1024
POLICY_NAME = "kolfix-security-policy.json"
AUDIT_NAME = "kolfix-security-audit.jsonl"
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:player_backup|\.kolmafia|settings|credentials|secrets)(?:/|$)|"
    r"(?:^|/)(?:\.env(?:\.[^/]*)?|id_(?:rsa|ed25519|ecdsa)|[^/]*(?:_prefs(?:\.bak)?|_moods)\.txt)$",
    re.I,
)
RESTRICTED_EXT = (".p12", ".pfx", ".key", ".kdbx")
PATTERNS = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("github-token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("openai-key", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(rb"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("slack-token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{18,}\b")),
    ("kol-session-password", re.compile(rb"(?i)(?:[?&]|\b)(?:pwd|password|sessionid|phpsessid)=[^\s&\"'<>]{8,}")),
    ("credential-assignment", re.compile(rb"(?im)^\s*(?:export\s+)?(?:password|secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*['\"]?(?!example\b|placeholder\b|changeme\b|redacted\b|<)[^\s'\"]{12,}")),
)
SCRUB = (
    re.compile(rb"(?i)\b(?:Authorization|Proxy-Authorization|Cookie|Set-Cookie):[^\r\n]*"),
    re.compile(rb"(?i)((?:[?&]|\b)(?:pwd|password|sessionid|phpsessid)=)[^&\s\"'<>]+"),
    re.compile(rb"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{10,}|sk-(?:proj-)?[A-Za-z0-9_-]{12,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b"),
    re.compile(rb"(?i)(\b(?:password|secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*)[^\r\n]+"),
)


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    severity: str = "high"


class GateError(Exception):
    pass


def run_git(repo: Path, *args: str, input_data: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], input=input_data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise GateError(f"git {args[0]} failed (exit {proc.returncode}); refusing push")
    return proc.stdout


def git_root() -> Path:
    return Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip()).resolve()


def git_private_dir(repo: Path) -> Path:
    return Path(run_git(repo, "rev-parse", "--absolute-git-dir").decode().strip())


def policy_path(repo: Path) -> Path:
    return git_private_dir(repo) / POLICY_NAME


def read_policy(repo: Path) -> dict:
    path = policy_path(repo)
    policy = {"schema": 1, "push_gate": True, "kolmafia_scrubber": False,
              "outbound_plane": "off"}
    if path.exists():
        st = path.lstat()
        if path.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o022 or st.st_size > 4096:
            raise GateError("Unsafe security policy file")
        content = json.loads(path.read_text())
        if not isinstance(content, dict) or content.get("schema") != 1:
            raise GateError("Unsupported security policy")
        if content.get("push_gate") is not True:
            raise GateError("Push gate cannot be disabled by configuration")
        if type(content.get("kolmafia_scrubber")) is not bool or content.get("outbound_plane") not in ("off", "explicit-proxy"):
            raise GateError("Invalid security policy")
        policy.update(content)
    return policy


def atomic_private(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise GateError("Refusing symlinked destination")
    fd, temp = tempfile.mkstemp(prefix=".kolfix-security-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sanitized_path(path: str) -> str:
    # Filenames themselves may contain private values. Never print them.
    return "path-sha256:" + hashlib.sha256(path.encode("utf-8", "backslashreplace")).hexdigest()[:16]


def scan_bytes(data: bytes, path: str, *, depth: int = 0) -> list[Finding]:
    if SENSITIVE_PATH.search(path) or path.lower().endswith(RESTRICTED_EXT):
        return [Finding(path, "protected-path")]
    if len(data) > MAX_BLOB:
        return [Finding(path, "oversize-uninspected")]
    findings = [Finding(path, rule) for rule, pattern in PATTERNS if pattern.search(data)]
    if data[:4] == b"PK\x03\x04" and depth < 2:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ZIP_MEMBERS or sum(x.file_size for x in entries) > MAX_ZIP_UNPACKED:
                    return findings + [Finding(path, "archive-uninspected")]
                for info in entries:
                    if info.is_dir():
                        continue
                    if info.flag_bits & 1 or info.file_size > MAX_BLOB:
                        findings.append(Finding(path, "archive-encrypted-or-oversize"))
                        continue
                    if info.compress_size == 0 and info.file_size or info.compress_size and info.file_size > info.compress_size * 100:
                        findings.append(Finding(path, "archive-expansion-limit"))
                        continue
                    try:
                        member = archive.read(info)
                    except (RuntimeError, OSError, ValueError, zipfile.BadZipFile):
                        findings.append(Finding(path, "archive-read-failed"))
                        continue
                    findings.extend(scan_bytes(member, path + "!" + info.filename, depth=depth + 1))
        except (zipfile.BadZipFile, OSError, ValueError):
            findings.append(Finding(path, "invalid-archive"))
    elif data[:4] == b"PK\x03\x04" and depth >= 2:
        findings.append(Finding(path, "archive-depth-limit"))
    return findings


def inspect_objects(repo: Path, spec: list[str]) -> tuple[list[Finding], int]:
    # Git object enumeration scans *history*, not just the final tree. A secret
    # committed then deleted still reaches GitHub and must be blocked.
    rows = run_git(repo, "rev-list", "--objects", *spec).splitlines()
    findings: list[Finding] = []
    if len(rows) > MAX_OBJECTS:
        return [Finding("<outgoing-history>", "object-count-limit")], 0
    # `rev-list --objects` names each blob once, even when the identical
    # blob also appears under a protected path. Inspect changed path names
    # independently, across every outgoing commit (including merge parents).
    changed_paths = run_git(repo, "log", "--format=", "--name-only", "-z",
                            "--no-renames", "--root", "-m", *spec).split(b"\0")
    if len(changed_paths) > MAX_OBJECTS * 8:
        return [Finding("<outgoing-history>", "path-count-limit")], 0
    for raw_path in changed_paths:
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", "backslashreplace")
        if SENSITIVE_PATH.search(path) or path.lower().endswith(RESTRICTED_EXT):
            findings.append(Finding(path, "protected-path"))
    total = 0
    scanned = 0
    by_sha: dict[bytes, str] = {}
    for row in rows:
        sha, _, path_raw = row.partition(b" ")
        if not SHA.fullmatch(sha.decode("ascii", "replace")):
            findings.append(Finding("<git-object>", "invalid-object-id"))
            continue
        by_sha.setdefault(sha, path_raw.decode("utf-8", "backslashreplace") or "<unnamed-blob>")
    # One cat-file metadata process for the batch rather than thousands of
    # subprocesses. Actual blob reads are still capped and made on demand.
    metadata = run_git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                       input_data=b"".join(sha + b"\n" for sha in by_sha)).splitlines()
    if len(metadata) != len(by_sha):
        raise GateError("Unexpected Git object count; refusing push")
    for record in metadata:
        fields = record.split()
        if len(fields) != 3 or fields[0] not in by_sha:
            raise GateError("Malformed Git object metadata; refusing push")
        sha, kind, raw_size = fields
        if kind != b"blob":
            continue
        path = by_sha[sha]
        size = int(raw_size)
        total += size
        if size > MAX_BLOB:
            findings.append(Finding(path, "oversize-uninspected"))
            continue
        if total > MAX_TOTAL:
            findings.append(Finding("<outgoing-history>", "total-byte-limit"))
            break
        blob = run_git(repo, "cat-file", "blob", sha.decode())
        findings.extend(scan_bytes(blob, path))
        scanned += 1
    return findings, scanned


def scan_index(repo: Path) -> tuple[list[Finding], int]:
    # Index-only inspection for CI and manual pre-commit review. Does not replace
    # pre-push history scanning.
    findings: list[Finding] = []
    seen = 0
    entries = run_git(repo, "ls-files", "-s", "-z").split(b"\0")
    for entry in entries:
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"\t")
        parts = meta.split()
        if len(parts) != 3 or parts[2] != b"0":
            continue
        path = raw_path.decode("utf-8", "backslashreplace")
        size = int(run_git(repo, "cat-file", "-s", parts[1].decode()).strip())
        if size > MAX_BLOB:
            findings.append(Finding(path, "oversize-uninspected"))
            continue
        findings.extend(scan_bytes(run_git(repo, "cat-file", "blob", parts[1].decode()), path))
        seen += 1
    return findings, seen


def format_findings(findings: list[Finding]) -> int:
    if not findings:
        print("Kolfix Security: PASS — no protected credentials found")
        return 0
    unique = sorted(set(findings), key=lambda x: (x.path, x.rule))
    print(f"Kolfix Security: BLOCK — {len(unique)} finding(s); no secret values printed", file=sys.stderr)
    for item in unique[:40]:
        print(f"  {item.severity}: {item.rule} at {sanitized_path(item.path)}", file=sys.stderr)
    if len(unique) > 40:
        print(f"  ... {len(unique)-40} additional finding(s) suppressed", file=sys.stderr)
    return 1


def audit(repo: Path, plane: str, event: str, ok: bool, count: int) -> None:
    # Metadata only. Never store secret-bearing arguments or raw inputs.
    if not active_lease(plane):
        return
    record = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "plane": plane,
              "event": event, "allow": ok, "count": count, "pid": os.getpid()}
    path = git_private_dir(repo) / AUDIT_NAME
    if path.is_symlink():
        return
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as out:
        out.write((json.dumps(record, sort_keys=True) + "\n").encode())


def active_lease(plane: str) -> bool:
    path = Path(f"/run/don-kolfix-security/lease-{os.getuid()}.json")
    try:
        s = path.stat(follow_symlinks=False)
        if s.st_uid != 0 or s.st_mode & 0o022 or s.st_size > 2048 or path.is_symlink():
            return False
        value = json.loads(path.read_text())
        return (value.get("uid") == os.getuid() and
                value.get("expires_epoch", 0) > dt.datetime.now(dt.timezone.utc).timestamp() and
                plane in value.get("planes", []))
    except (OSError, ValueError, TypeError):
        return False


def scan_push(repo: Path, lines: bytes) -> int:
    refs = 0
    combined: list[Finding] = []
    for raw in lines.splitlines():
        words = raw.decode("ascii", "replace").split()
        if len(words) != 4 or not all(SHA.fullmatch(x) for x in (words[1], words[3])):
            raise GateError("Malformed pre-push ref; refusing push")
        _, local_sha, _, remote_sha = words
        if int(local_sha, 16) == 0:  # deleting branch: nothing new to upload
            continue
        refs += 1
        if int(remote_sha, 16) == 0:
            spec = [local_sha]  # new branch: inspect entire reachable history
        else:
            spec = [local_sha, "^" + remote_sha]
        findings, _ = inspect_objects(repo, spec)
        combined.extend(findings)
    if not refs:
        print("Kolfix Security: PASS — no new ref objects to upload")
        return 0
    outcome = format_findings(combined)
    audit(repo, "push", "pre-push-decision", outcome == 0, len(combined))
    return outcome


def scrub_bytes(data: bytes) -> bytes:
    out = data
    out = SCRUB[0].sub(b"[REDACTED-HEADER]", out)
    out = SCRUB[1].sub(lambda m: m.group(1) + b"[REDACTED]", out)
    out = SCRUB[2].sub(b"[REDACTED-TOKEN]", out)
    out = SCRUB[3].sub(lambda m: m.group(1) + b"[REDACTED]", out)
    return out


def require_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise GateError("Python 3.11+ required; use a suitable system python3 or optional Conda environment")


def git_hook_path(repo: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get", "core.hooksPath"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode not in (0, 1):
        raise GateError("Cannot inspect core.hooksPath")
    if proc.returncode == 0 and proc.stdout.strip():
        raise GateError("Custom core.hooksPath is active; refusing to mask existing hooks")
    hook = Path(run_git(repo, "rev-parse", "--git-path", "hooks/pre-push").decode().strip())
    return hook if hook.is_absolute() else repo / hook


def package_invocation() -> bool:
    """Choose pip/pipx module mode; direct-script invocations use repo sources.

    The installed console script imports ``kolfix_security``. ``python -m``
    sets ``__name__`` to __main__ but retains the real module name in spec.
    """
    return __name__ == "kolfix_security" or (
        __name__ == "__main__" and getattr(__spec__, "name", None) == "kolfix_security"
    )


def hook_content(python: Path, *, mode: str = "source") -> bytes:
    # Pin the interpreter, not a wrapper subject to PATH/Conda activation.
    # Packaged installs use -m so no developer checkout file is required.
    if mode == "module":
        target = " -m kolfix_security hook\n"
    elif mode == "source":
        target = ' "$root/tools/security/kolfix_security.py" hook\n'
    else:
        raise GateError("Invalid hook mode")
    return ('#!/bin/sh\nset -eu\n'
            'root="$(git rev-parse --show-toplevel)"\n'
            f'exec {shlex.quote(str(python))}{target}').encode()


def managed_hook_interpreter(content: bytes) -> Path:
    prefix = b'#!/bin/sh\nset -eu\nroot="$(git rev-parse --show-toplevel)"\nexec '
    suffixes = {
        "source": b' "$root/tools/security/kolfix_security.py" hook\n',
        "module": b' -m kolfix_security hook\n',
    }
    for mode, suffix in suffixes.items():
        if not content.startswith(prefix) or not content.endswith(suffix):
            continue
        try:
            word = shlex.split(content[len(prefix):-len(suffix)].decode("utf-8"))
        except (UnicodeError, ValueError):
            break
        if len(word) != 1 or not Path(word[0]).is_absolute():
            break
        python = Path(word[0])
        if hook_content(python, mode=mode) == content:
            return python
        break
    raise GateError("Existing pre-push hook is not an exact managed security gate; refusing replacement")


def install_hook(repo: Path, *, rebind: bool = False) -> None:
    require_python()
    hook = git_hook_path(repo)
    exists = hook.exists() or hook.is_symlink()
    if rebind:
        if not exists or hook.is_symlink() or not hook.is_file():
            raise GateError("No safe, existing managed pre-push hook to rebind")
        st = hook.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o022 or st.st_size > 1024:
            raise GateError("Unsafe existing hook permissions or size")
        managed_hook_interpreter(hook.read_bytes())
    elif exists:
        raise GateError("Existing pre-push hook found; refusing overwrite (use rebind-hook for this gate only)")
    hook.parent.mkdir(parents=True, exist_ok=True)
    # Do not resolve symlinks here: pipx/venv's bin/python often points to
    # /usr/bin/python, but its *venv path* activates the installed package.
    # Resolving it would silently lose site-packages and block every push.
    python = Path(sys.executable).absolute()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise GateError("Selected Python interpreter is not executable")
    # Chosen interpreter may be system python3 or Conda Python; both are
    # stdlib-only. A missing interpreter fails closed rather than bypassing.
    atomic_private(hook, hook_content(python, mode="module" if package_invocation() else "source"))
    hook.chmod(0o700)
    if not policy_path(repo).exists():
        atomic_private(policy_path(repo), (json.dumps(read_policy(repo), indent=2) + "\n").encode())
    print(("Rebound" if rebind else "Installed") + " active pre-push gate (interpreter path withheld from logs)")
    print("Warning: --no-verify or alternate Git clients can bypass local hooks. Add a required GitHub check/ruleset.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="cmd", required=True)
    subs.add_parser("install-hook")
    subs.add_parser("rebind-hook", help="switch only our own managed hook to the current Python interpreter")
    subs.add_parser("status")
    subs.add_parser("hook")
    scan = subs.add_parser("scan")
    scan.add_argument("--index", action="store_true", help="scan tracked index, not push history")
    scan.add_argument("--revision", help="git commit/revision range e.g. BASE..HEAD")
    pol = subs.add_parser("policy")
    pol.add_argument("--kolmafia-scrubber", choices=["on", "off"])
    pol.add_argument("--outbound-plane", choices=["off", "explicit-proxy"])
    scrub = subs.add_parser("scrub")
    scrub.add_argument("--plane", choices=["kolmafia"], default="kolmafia")
    rec = subs.add_parser("record", help="explicit instrumented metadata-only debug event")
    rec.add_argument("--plane", choices=["push", "kolmafia", "outbound"], required=True)
    rec.add_argument("--direction", choices=["request", "response"], required=True)
    rec.add_argument("--outcome", choices=["allow", "block", "observed"], required=True)
    rec.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    try:
        require_python()
        repo = git_root()
        if args.cmd == "install-hook":
            install_hook(repo)
        elif args.cmd == "rebind-hook":
            install_hook(repo, rebind=True)
        elif args.cmd == "status":
            policy = read_policy(repo)
            print(json.dumps({"version": VERSION, "policy": policy,
                              "push_recorder_lease": active_lease("push"),
                              "kolmafia_recorder_lease": active_lease("kolmafia"),
                              "outbound_recorder_lease": active_lease("outbound")}, indent=2))
        elif args.cmd == "policy":
            policy = read_policy(repo)
            if args.kolmafia_scrubber:
                policy["kolmafia_scrubber"] = args.kolmafia_scrubber == "on"
            if args.outbound_plane:
                policy["outbound_plane"] = args.outbound_plane
            atomic_private(policy_path(repo), (json.dumps(policy, sort_keys=True, indent=2) + "\n").encode())
            print("Policy stored inside private .git metadata; transport wiring is never automatic")
        elif args.cmd == "scan":
            if args.revision:
                # Accept only a narrow safe revision range; no git shell invocation.
                if args.revision.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./^~-]{1,150}", args.revision):
                    raise GateError("Unsafe revision specification")
                findings, count = inspect_objects(repo, [args.revision])
            else:
                findings, count = scan_index(repo)
            print(f"Scanned {count} Git blob(s). No credential values shown.")
            return format_findings(findings)
        elif args.cmd == "hook":
            read_policy(repo)
            return scan_push(repo, sys.stdin.buffer.read(65536))
        elif args.cmd == "record":
            policy = read_policy(repo)
            if args.plane == "outbound" and policy["outbound_plane"] != "explicit-proxy":
                raise GateError("Outbound debug plane is OFF")
            if not active_lease(args.plane):
                raise GateError("No active root-authorized diagnostic lease for this plane")
            if not 0 <= args.count <= 100000:
                raise GateError("Invalid debug count")
            audit(repo, args.plane, f"{args.direction}-{args.outcome}",
                  args.outcome != "block", args.count)
            print("Metadata-only event recorded; payloads not captured")
        elif args.cmd == "scrub":
            if not read_policy(repo)["kolmafia_scrubber"]:
                raise GateError("KoLmafia log scrubber is OFF; explicitly enable the policy first")
            raw = sys.stdin.buffer.read(MAX_BLOB + 1)
            if len(raw) > MAX_BLOB:
                raise GateError("Input exceeds scrub limit; refusing to emit partial content")
            out = scrub_bytes(raw)
            sys.stdout.buffer.write(out)
            audit(repo, "kolmafia", "redacted-capture", True, 1)
        return 0
    except (GateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Kolfix Security: BLOCK — {type(exc).__name__}: {str(exc)[:150]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
