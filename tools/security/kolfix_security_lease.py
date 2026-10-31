#!/usr/bin/env python3
"""Root-owned privilege helper: 30-minute metadata recorder lease only.

INSTALL THIS FILE as root in /usr/local/libexec/don-kolfix-security-lease,
owned by root and not writable by other users. Never run a copy from a
user-writable Git checkout or Conda environment through sudo.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

LEASE_DIR = Path('/run/don-kolfix-security')


def verified_helper() -> bool:
    path = Path(__file__).resolve()
    parents = [path, *path.parents]
    # /run is root-owned. Require the helper and its installation path to be
    # root-owned and neither group nor world writable.
    return all(p.stat().st_uid == 0 and not (p.stat().st_mode & 0o022) for p in parents)


def write_lease(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix='.lease-', dir=LEASE_DIR)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'w') as file:
            json.dump(value, file, sort_keys=True)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['enable', 'disable', 'status'])
    p.add_argument('--minutes', type=int, default=30)
    p.add_argument('--planes', default='push,kolmafia')
    args = p.parse_args()
    if os.geteuid() != 0 or not verified_helper():
        print('Refusing privilege: execute only the root-owned installed helper with sudo', file=sys.stderr)
        return 2
    uid = int(os.environ.get('SUDO_UID', '-1'))
    if uid < 1 or uid > 2**31 - 1:
        print('No valid non-root sudo requester; refusing to issue a lease', file=sys.stderr)
        return 2
    if args.minutes < 1 or args.minutes > 30 or not set(args.planes.split(',')) <= {'push', 'kolmafia', 'outbound'}:
        print('Only 1–30 minutes and push/kolmafia/outbound planes are supported', file=sys.stderr)
        return 2
    LEASE_DIR.mkdir(mode=0o755, exist_ok=True)
    st = LEASE_DIR.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        print('Unsafe lease directory', file=sys.stderr)
        return 2
    path = LEASE_DIR / f'lease-{uid}.json'
    if path.is_symlink():
        print('Unsafe symlinked lease', file=sys.stderr)
        return 2
    if args.action == 'enable':
        expires = dt.datetime.now(dt.timezone.utc).timestamp() + args.minutes * 60
        write_lease(path, {'uid': uid, 'expires_epoch': expires,
                           'planes': sorted(set(args.planes.split(','))), 'schema': 1})
        print(f'Lease enabled for {args.minutes} minute(s); auto-expires; metadata only')
    elif args.action == 'disable':
        path.unlink(missing_ok=True)
        print('Lease disabled')
    else:
        if path.exists():
            entry = json.loads(path.read_text())
            remaining = max(0, int(entry.get('expires_epoch', 0) - dt.datetime.now(dt.timezone.utc).timestamp()))
            print(f'Lease has {remaining} seconds remaining')
        else:
            print('No lease')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
