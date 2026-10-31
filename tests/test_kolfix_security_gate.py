"""Offline tests: temporary Git repos only; no networking or user files."""
from __future__ import annotations
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

TOOL = Path(__file__).resolve().parents[1] / 'tools/security/kolfix_security.py'
spec = importlib.util.spec_from_file_location('gate', TOOL)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


def git(root: Path, *args):
    p = subprocess.run(['git', '-C', str(root), *args], text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise AssertionError(p.stderr)
    return p.stdout.strip()


class SecurityGate(unittest.TestCase):
    def setUp(self):
        self.ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.ctx.cleanup)
        self.repo = Path(self.ctx.name) / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo/'README.md').write_text('harmless\n')
        git(self.repo, 'add', 'README.md')
        git(self.repo, 'commit', '-qm', 'initial')
        self.base = git(self.repo, 'rev-parse', 'HEAD')

    def commit(self, name: str, content: bytes) -> str:
        path = self.repo/name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(content)
        git(self.repo, 'add', name)
        git(self.repo, 'commit', '-qm', 'more')
        return git(self.repo, 'rev-parse', 'HEAD')

    def test_scans_outgoing_committed_history_even_after_delete(self):
        token = b'ghp_' + b'A'*36
        self.commit('private.txt', token)
        git(self.repo, 'rm', 'private.txt')
        git(self.repo, 'commit', '-qm', 'delete evidence')
        results, count = gate.inspect_objects(self.repo, [git(self.repo,'rev-parse','HEAD'), '^'+self.base])
        self.assertTrue(any(f.rule == 'github-token' for f in results))
        self.assertGreater(count, 0)

    def test_clean_history_and_ref_hook(self):
        local = self.commit('public.txt', b'hello world')
        self.assertEqual(gate.scan_push(self.repo, f'refs/heads/main {local} refs/heads/main {self.base}\n'.encode()), 0)
        self.assertEqual(gate.scan_push(self.repo, f'refs/heads/main {"0"*40} refs/heads/main {self.base}\n'.encode()), 0)

    def test_protected_paths_and_nested_archives(self):
        self.assertEqual(gate.scan_bytes(b'not actually sensitive', 'player_backup/stuff.bin')[0].rule, 'protected-path')
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as z:
            z.writestr('settings/character_prefs.txt', b'some info')
        rules = [f.rule for f in gate.scan_bytes(output.getvalue(), 'backup.zip')]
        self.assertIn('protected-path', rules)

    def test_no_secret_leak_on_output(self):
        path = 'name-ghi_' + 'ABCDEF'*20
        result = gate.sanitized_path(path)
        self.assertNotIn('ABCDEF', result)

    def test_redacts_auth_and_session(self):
        raw = (b'Authorization: Bearer secret\nCookie: PHPSESSID=test\n'
               b'https://example.invalid/choice.php?' + b'pwd=' + b'abcdefghijklmnopqrstuvwxyz&x=1\n')
        result = gate.scrub_bytes(raw)
        self.assertNotIn(b'Bearer secret', result)
        self.assertNotIn(b'abcdefghijklmnopqrstuvwxyz', result)
        self.assertIn(b'x=1', result)

    def test_hook_installed_but_custom_hooks_unmodified(self):
        code = Path(sys.executable)
        self.assertTrue(code.exists())
        # Tests copy the tool into repo, exactly where the installed hook expects it.
        dest = self.repo/'tools/security/kolfix_security.py'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(TOOL.read_bytes())
        gate.install_hook(self.repo)
        hook = self.repo/'.git/hooks/pre-push'
        self.assertTrue(hook.exists())
        self.assertIn('kolfix_security.py" hook', hook.read_text())
        self.assertTrue(gate.read_policy(self.repo)['push_gate'])
        self.assertFalse(gate.read_policy(self.repo)['kolmafia_scrubber'])
        with self.assertRaises(gate.GateError):
            gate.install_hook(self.repo)
        hook.unlink()
        git(self.repo, 'config', '--local', 'core.hooksPath', 'external-hooks')
        with self.assertRaises(gate.GateError):
            gate.install_hook(self.repo)

    def test_system_python_without_conda_and_safe_rebind(self):
        # Installs with the current interpreter and remains operational in a
        # non-Conda shell. Rebinding is allowed only for our exact hook format.
        dest = self.repo / 'tools/security/kolfix_security.py'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(TOOL.read_bytes())
        gate.install_hook(self.repo)
        hook = self.repo / '.git/hooks/pre-push'
        content = hook.read_bytes()
        self.assertIn(str(Path(sys.executable).absolute()).encode(), content)
        self.assertNotIn(b'conda run', content)
        self.assertNotIn(b'source ', content)
        head = git(self.repo, 'rev-parse', 'HEAD')
        ref_line = f'refs/heads/main {head} refs/heads/main {head}\n'
        env = dict(os.environ, PATH='/usr/bin:/bin')
        # No "conda" executable or activation required at push time.
        proc = subprocess.run(['sh', str(hook)], cwd=self.repo, env=env,
                              input=ref_line, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        gate.install_hook(self.repo, rebind=True)
        self.assertEqual(hook.read_bytes(), content)
        hook.write_text('#!/bin/sh\necho existing external logic\n')
        with self.assertRaises(gate.GateError):
            gate.install_hook(self.repo, rebind=True)
        self.assertEqual(hook.read_text(), '#!/bin/sh\necho existing external logic\n')

    def test_pip_pipx_hook_form_and_safe_rebind(self):
        # The packaged entrypoint can protect a repo without a checkout copy of
        # tools/security/kolfix_security.py. Source and module hooks both rebind.
        from unittest.mock import patch
        with patch.object(gate, "package_invocation", return_value=True):
            gate.install_hook(self.repo)
        hook = self.repo / '.git/hooks/pre-push'
        module_script = hook.read_bytes()
        self.assertIn(b' -m kolfix_security hook\n', module_script)
        self.assertNotIn(b'tools/security/kolfix_security.py', module_script)
        self.assertEqual(gate.managed_hook_interpreter(module_script), Path(sys.executable).absolute())
        with patch.object(gate, "package_invocation", return_value=False):
            gate.install_hook(self.repo, rebind=True)
        self.assertIn(b'tools/security/kolfix_security.py', hook.read_bytes())
        with patch.object(gate, "package_invocation", return_value=True):
            gate.install_hook(self.repo, rebind=True)
        self.assertEqual(hook.read_bytes(), module_script)
        hook.write_text('#!/bin/sh\necho foreign hook\n')
        with patch.object(gate, "package_invocation", return_value=True):
            with self.assertRaises(gate.GateError):
                gate.install_hook(self.repo, rebind=True)
        self.assertEqual(hook.read_text(), '#!/bin/sh\necho foreign hook\n')

    def test_real_git_push_blocked_before_remote_update(self):
        remote = Path(self.ctx.name) / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
        git(self.repo, 'remote', 'add', 'origin', str(remote))
        git(self.repo, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
        dest = self.repo / 'tools/security/kolfix_security.py'
        dest.parent.mkdir(parents=True)
        dest.write_bytes(TOOL.read_bytes())
        git(self.repo, 'add', 'tools/security/kolfix_security.py')
        git(self.repo, 'commit', '-qm', 'tool install')
        gate.install_hook(self.repo)
        clean = subprocess.run(['git', '-C', str(self.repo), 'push', '-q', 'origin', 'HEAD:refs/heads/main'],
                               capture_output=True, text=True)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        clean_head = git(remote, 'rev-parse', 'refs/heads/main')
        self.commit('notes.txt', b'ghp_' + b'X'*36)
        blocked = subprocess.run(['git', '-C', str(self.repo), 'push', '-q', 'origin', 'HEAD:refs/heads/main'],
                                 capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('github-token', blocked.stderr)
        self.assertNotIn('X'*36, blocked.stderr)
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/main'), clean_head)

    def test_invalid_ref_fails_closed(self):
        with self.assertRaises(gate.GateError):
            gate.scan_push(self.repo, b'nonsense input\n')

    def test_lease_inactive_by_default(self):
        self.assertFalse(gate.active_lease('push'))
        self.assertFalse(gate.active_lease('kolmafia'))


if __name__ == '__main__':
    unittest.main()
