#!/usr/bin/env python3
"""Opt-in, locked, atomic Don Report v1 local record store.

This CLI is a host-side building block, NOT invoked by KoLmafia/relay hooks.
Always requires an explicit --root and --write, or uses --plan without writes.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

SOURCES = frozenset((
    "accountval", "philter", "greenbox", "consume", "chit",
    "excavator", "watersheep", "custom_ash",
))
STATES = frozenset(("observed", "known_unknown", "ignored", "unobserved", "conflict"))
EVIDENCE = frozenset(("cached", "parsed_page", "derived", "manual_claim"))
KEYS = frozenset((
    "schema", "id", "address", "scope", "node", "source", "state",
    "evidence", "value", "observedAt", "reason", "receiptId",
))
TAGS = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SUBJECT = re.compile(r"^[a-z][a-z0-9_]*/[1-9][0-9]*$")
RECEIPT = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
DATE = re.compile(r"^[0-9]{8}$")
TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
SECRET = re.compile(r"https?:|pwd\s*[:=]|password\s*[:=]|token\s*[:=]|cookie\s*[:=]|authorization\s*[:=]|@|[<>\r\n]", re.I)


class UnsafeReport(ValueError):
    pass


def valid_value(value):
    return (type(value) is bool or
            (type(value) is int and abs(value) <= 2**53 - 1) or
            (type(value) is str and 0 < len(value) <= 160 and not SECRET.search(value)))


def validate(record):
    if type(record) is not dict or set(record) != KEYS:
        raise UnsafeReport("invalid report fields")
    if record["schema"] != "don-report-v1" or not RECEIPT.fullmatch(record["id"]):
        raise UnsafeReport("invalid schema or receipt id")
    if record["source"] not in SOURCES or record["state"] not in STATES or record["evidence"] not in EVIDENCE:
        raise UnsafeReport("unrecognized source, status or evidence")
    scope, node = record["scope"], record["node"]
    if type(scope) is not dict or set(scope) != {"playerId", "day", "life"} or type(node) is not dict or set(node) != {"domain", "subject", "metric"}:
        raise UnsafeReport("invalid node or scope fields")
    if not re.fullmatch(r"[0-9]{1,12}", scope["playerId"]) or not DATE.fullmatch(scope["day"]):
        raise UnsafeReport("invalid player or rollover day")
    if type(scope["life"]) is not int or not 0 <= scope["life"] <= 2**53 - 1:
        raise UnsafeReport("invalid lifetime ascensions")
    if not TAGS.fullmatch(node["domain"]) or not SUBJECT.fullmatch(node["subject"]) or not TAGS.fullmatch(node["metric"]):
        raise UnsafeReport("invalid node token")
    address = (f'donstate:v1:{scope["playerId"]}:{scope["day"]}:'
               f'{scope["life"]}:{node["domain"]}:{node["subject"]}:{node["metric"]}')
    if record["address"] != address or not TIME.fullmatch(record["observedAt"]):
        raise UnsafeReport("address or observation timestamp mismatch")
    value = record["value"]
    if (record["state"] == "observed" and not valid_value(value)) or (record["state"] != "observed" and value is not None):
        raise UnsafeReport("non-observation value or unsafe observed data")
    reason, receipt = record["reason"], record["receiptId"]
    if reason is not None and (type(reason) is not str or len(reason) > 160 or SECRET.search(reason)):
        raise UnsafeReport("unsafe reason")
    if receipt is not None and (type(receipt) is not str or not RECEIPT.fullmatch(receipt)):
        raise UnsafeReport("unsafe receipt id")
    return record


def destination(root, r):
    s = r["scope"]
    return root / "d_data" / ("d_" + r["source"]) / s["playerId"] / s["day"] / ("life-" + str(s["life"])) / (r["id"] + ".json")


def store(root, r):
    """Exclusive lock per source/scope; atomically publish a unique immutable file.

    All consumers of this store must use this writer. No silent overwrite.
    """
    root = Path(root)
    if not root.is_dir():
        raise UnsafeReport("explicit root directory must already exist")
    validate(r)
    target = destination(root, r)
    data = (json.dumps(r, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > 8192:
        raise UnsafeReport("receipt exceeds 8KiB")
    # Reject a symlink in any path component beneath the supplied data root.
    current = root
    for segment in target.relative_to(root).parts[:-1]:
        current = current / segment
        if current.is_symlink():
            raise UnsafeReport("symlink in report directory")
        current.mkdir(exist_ok=True)
    if target.is_symlink():
        raise UnsafeReport("symlink at report destination")
    lock = target.parent / ".don_report.lock"
    with open(lock, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            if target.exists():
                raw = target.read_bytes()
                if raw != data:
                    raise UnsafeReport("DON_REPORT_IDEMPOTENCY_CONFLICT")
                return {"disposition": "duplicate", "path": str(target)}
            temp_name = None
            try:
                fd, temp_name = tempfile.mkstemp(prefix=".record-", suffix=".tmp", dir=target.parent)
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.link(temp_name, target)  # Atomic, no-clobber publication.
                dir_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if temp_name is not None:
                    os.unlink(temp_name)
            if target.read_bytes() != data:
                raise UnsafeReport("DON_REPORT_READBACK_FAILED")
            return {"disposition": "written", "path": str(target)}
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Existing KoLmafia data directory; never autodetected")
    parser.add_argument("--input", required=True, help="JSON report file, not an executable script")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Validate and show target without writing")
    mode.add_argument("--write", action="store_true", help="Explicitly persist one immutable report")
    args = parser.parse_args()
    if not Path(args.root).is_dir():
        parser.error("--root must identify an existing directory")
    path = Path(args.input)
    if not path.is_file() or path.stat().st_size > 8192:
        parser.error("input must be an existing <=8KiB JSON file")
    r = validate(json.loads(path.read_text(encoding="utf-8")))
    if args.plan:
        print(json.dumps({"disposition": "plan_only", "path": str(destination(Path(args.root), r))}))
        return
    print(json.dumps(store(args.root, r)))


if __name__ == "__main__":
    main()
