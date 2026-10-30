import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile
import json

S = Path(__file__).resolve().parents[1] / "tools/kolfix_settings.py"
spec = importlib.util.spec_from_file_location("kolfix_settings", S)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "old"
        (self.source / "settings").mkdir(parents=True)
        self.settings = self.source / "settings"
        (self.settings / "GLOBAL_aliases.txt").write_bytes(b'barf\tgarbo target="cockroach"\n' + b'with space\tfoo\n')
        (self.settings / "GLOBAL_prefs.txt").write_bytes(b"a=true\npass=localsecret\n")
        (self.settings / "GLOBAL_prefs.bak").write_bytes(b"old global backup\n")
        (self.settings / "GLOBAL_moods.txt").write_bytes(b"global mood\r\n")
        (self.settings / "human_prefs.txt").write_bytes(b"human's prefs\n")
        (self.settings / "human_moods.txt").write_bytes(b"mood\n")
        (self.settings / "human_prefs.bak").write_bytes(b"older prefs\n")
        self.output = self.root / "vault"

    def tearDown(self):
        self.tmp.cleanup()

    def make_backup(self):
        return mod.backup(self.source, self.output, None)

    def test_roundtrip_and_raw_aliases(self):
        archive = self.make_backup()
        manifest, b = mod.verify(archive)
        self.assertEqual(len(b), 7)
        self.assertEqual(b["settings/GLOBAL_aliases.txt"], (self.settings / "GLOBAL_aliases.txt").read_bytes())
        self.assertEqual(manifest["missing"], [])
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        target = self.root / "xpra" / "data"
        target.mkdir(parents=True)
        mod.deliver(archive, target, False, False)
        self.assertFalse((target / "settings").exists())
        self.assertEqual(len(list((target / "kolfix-imports").rglob("GLOBAL_aliases.txt"))), 1)
        (target / "settings").mkdir()
        (target / "settings" / "GLOBAL_aliases.txt").write_bytes(b"old-keep-me\n")
        with self.assertRaises(mod.KolfixError):
            mod.deliver(archive, target, True, False)
        mod.deliver(archive, target, True, True)
        self.assertEqual((target / "settings" / "GLOBAL_aliases.txt").read_bytes(), (self.settings / "GLOBAL_aliases.txt").read_bytes())
        rollback = list((target / "kolfix-imports" / "rollback").rglob("GLOBAL_aliases.txt"))
        self.assertEqual(len(rollback), 1)
        self.assertEqual(rollback[0].read_bytes(), b"old-keep-me\n")

    def test_missing_optional_reported(self):
        (self.settings / "human_prefs.bak").unlink()
        manifest, b = mod.verify(self.make_backup())
        self.assertEqual(len(b), 6)
        self.assertIn("human_prefs.bak", manifest["missing"])

    def test_reject_unsafe_symlink(self):
        f = self.settings / "human_moods.txt"
        f.unlink()
        f.symlink_to(self.root / "private")
        with self.assertRaises(mod.KolfixError):
            self.make_backup()

    def test_reject_bad_archive_entry(self):
        archive = self.make_backup()
        bad = self.root / "tampered.zip"
        with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(bad, "w") as zout:
            for item in zin.namelist():
                if item == "settings/GLOBAL_aliases.txt":
                    zout.writestr(item, b"changed")
                else:
                    zout.writestr(item, zin.read(item))
        with self.assertRaises(mod.KolfixError):
            mod.verify(bad)

    def test_refuse_active_session_marker(self):
        archive = self.make_backup()
        target = self.root / "xpra"
        (target / "sessions").mkdir(parents=True)
        (target / "sessions" / "active_session.human").touch()
        with self.assertRaises(mod.KolfixError):
            mod.deliver(archive, target, True, True)

    def test_stale_marker_with_verified_container(self):
        archive = self.make_backup()
        target = self.root / "xpra"
        (target / "sessions").mkdir(parents=True)
        marker = target / "sessions" / "active_session.human"
        marker.write_bytes(b"preserve-session-record")
        with patch.object(mod, "verify_stopped_container") as verify_docker:
            mod.deliver(archive, target, True, True, "ko-xpra-test")
            self.assertEqual(verify_docker.call_count, 2)
            self.assertTrue((target / "settings" / "GLOBAL_aliases.txt").exists())
            self.assertEqual(marker.read_bytes(), b"preserve-session-record")

    def test_container_guard_cannot_bypass_stopped_ack(self):
        archive = self.make_backup()
        target = self.root / "xpra"
        target.mkdir()
        with patch.object(mod, "verify_stopped_container") as guard:
            with self.assertRaises(mod.KolfixError):
                mod.deliver(archive, target, True, False, "ko-xpra-test")
            guard.assert_not_called()

    def test_docker_stop_check_rejects_running(self):
        target = self.root / "xpra"
        target.mkdir()
        with patch.object(mod, "_docker_json", return_value=[{
            "State": {"Running": True, "Status": "running"},
            "Mounts": [{"Type": "bind", "Source": str(target),
                         "Destination": "/home/kolmafia/.kolmafia"}],
        }]):
            with self.assertRaisesRegex(mod.KolfixError, "not stopped"):
                mod.verify_stopped_container(target, "ko-xpra-test")

    def test_docker_check_rejects_wrong_mount(self):
        target = self.root / "xpra"
        other = self.root / "different"
        target.mkdir()
        other.mkdir()
        with patch.object(mod, "_docker_json", return_value=[{
            "State": {"Running": False, "Status": "exited"},
            "Mounts": [{"Type": "bind", "Source": str(other),
                         "Destination": "/home/kolmafia/.kolmafia"}],
        }]):
            with self.assertRaisesRegex(mod.KolfixError, "does not bind-mount"):
                mod.verify_stopped_container(target, "ko-xpra-test")

    def test_docker_guard_blocks_other_running_container(self):
        target = self.root / "xpra"
        target.mkdir()
        stopped = {
            "State": {"Running": False, "Status": "exited"},
            "Mounts": [{"Type": "bind", "Source": str(target),
                         "Destination": "/home/kolmafia/.kolmafia"}],
        }
        active = {"Mounts": [{"Type": "bind", "Source": str(target),
                                "Destination": "/home/kolmafia/.kolmafia"}]}
        with patch.object(mod, "_docker_json", side_effect=[[stopped], [active]]), \
             patch.object(mod, "_docker_ps_ids", return_value=["another-running-container"]):
            with self.assertRaisesRegex(mod.KolfixError, "Another running"):
                mod.verify_stopped_container(target, "ko-xpra-test")

    def test_docker_guard_accepts_stopped_owned_mount(self):
        target = self.root / "xpra"
        target.mkdir()
        stopped = {
            "State": {"Running": False, "Status": "exited"},
            "Mounts": [{"Type": "bind", "Source": str(target),
                         "Destination": "/home/kolmafia/.kolmafia"}],
        }
        with patch.object(mod, "_docker_json", return_value=[stopped]), \
             patch.object(mod, "_docker_ps_ids", return_value=[]):
            mod.verify_stopped_container(target, "ko-xpra-test")

    def test_only_one_player(self):
        (self.settings / "another_prefs.txt").write_bytes(b"another\n")
        archive = mod.backup(self.source, self.output, ["human"])
        m, b = mod.verify(archive)
        self.assertEqual(len(b), 7)
        self.assertNotIn("settings/another_prefs.txt", b)

    def test_aliases_tab_formatted(self):
        file = Path(__file__).resolve().parents[1] / 'GLOBAL_aliases_refined.txt'
        raw = file.read_bytes()
        names = []
        for line in raw.decode().splitlines():
            self.assertEqual(line.count('\t'), 1, line)
            self.assertFalse(line.startswith('alias '))
            self.assertNotIn('=>', line)
            names.append(line.split('\t')[0])
        self.assertEqual(len(names), 51)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('barf', names)
        self.assertIn('nobarf', names)
        self.assertIn('combo', names)
        self.assertIn('bottle of wine', names)

if __name__ == "__main__": unittest.main()

class PermanentFeatureTests(SettingsTests):
    def test_gcli_status_snapshot_sanitized(self):
        archive = self.make_backup()
        root = self.source
        data = (root / "data" / mod.STATUS_FILENAME).read_text()
        self.assertIn("action\tbackup\n", data)
        self.assertIn("files\t7\n", data)
        self.assertNotIn("localsecret", data)
        self.assertNotIn(str(root), data)
        self.assertNotIn("GLOBAL_prefs", data)
        self.assertNotIn("human", data)

    def test_v2_rollback_and_redo_keep_exact_bytes(self):
        a = self.make_backup()
        target = self.root / "xpra"
        (target / "settings").mkdir(parents=True)
        original = b'combo\tcall original.ash\n'
        (target / "settings" / "GLOBAL_aliases.txt").write_bytes(original)
        mod.deliver(a, target, True, True)
        snapshot = sorted((target / "kolfix-imports" / "rollback").iterdir())[-1].name
        self.assertEqual((target / "settings" / "GLOBAL_aliases.txt").read_bytes(), (self.settings / "GLOBAL_aliases.txt").read_bytes())
        self.assertTrue((target / "settings" / "human_moods.txt").exists())
        mod.rollback_snapshot(target, snapshot, False, False, None)
        self.assertNotEqual((target / "settings" / "GLOBAL_aliases.txt").read_bytes(), original)
        mod.rollback_snapshot(target, snapshot, True, True, None)
        self.assertEqual((target / "settings" / "GLOBAL_aliases.txt").read_bytes(), original)
        self.assertFalse((target / "settings" / "human_moods.txt").exists())
        self.assertIn("action\trolled-back", (target / "data" / mod.STATUS_FILENAME).read_text())
        redo_snapshot = sorted((target / "kolfix-imports" / "rollback").iterdir())[-1].name
        self.assertNotEqual(redo_snapshot, snapshot)
        mod.rollback_snapshot(target, redo_snapshot, True, True, None)
        self.assertEqual((target / "settings" / "GLOBAL_aliases.txt").read_bytes(), (self.settings / "GLOBAL_aliases.txt").read_bytes())
        self.assertTrue((target / "settings" / "human_moods.txt").exists())

    def test_rollback_rejects_divergence_without_writes(self):
        a = self.make_backup()
        target = self.root / "xpra"
        target.mkdir()
        mod.deliver(a, target, True, True)
        snapshot = next((target / "kolfix-imports" / "rollback").iterdir()).name
        divergent = target / "settings" / "GLOBAL_aliases.txt"
        divergent.write_bytes(b'manually-changed\n')
        with self.assertRaisesRegex(mod.KolfixError, "diverged"):
            mod.rollback_snapshot(target, snapshot, True, True, None)
        self.assertEqual(divergent.read_bytes(), b'manually-changed\n')

    def test_rollback_requires_stop_with_stale_marker(self):
        a = self.make_backup()
        target = self.root / "xpra"
        target.mkdir()
        mod.deliver(a, target, True, True)
        snapshot = next((target / "kolfix-imports" / "rollback").iterdir()).name
        with self.assertRaisesRegex(mod.KolfixError, "stopped"):
            mod.rollback_snapshot(target, snapshot, True, False, None)
        (target / "sessions").mkdir()
        (target / "sessions" / "active_session.human").touch()
        with self.assertRaisesRegex(mod.KolfixError, "Session markers"):
            mod.rollback_snapshot(target, snapshot, True, True, None)

    def test_legacy_rollback_v1_1(self):
        target = self.root / "xpra"
        (target / "settings").mkdir(parents=True)
        snapshot = "20261030T220202789948Z"
        legacy = target / "kolfix-imports" / "rollback" / snapshot / "settings"
        legacy.mkdir(parents=True)
        (legacy / "GLOBAL_aliases.txt").write_bytes(b'old aliases\n')
        active = target / "settings" / "GLOBAL_aliases.txt"
        active.write_bytes(b'new aliases\n')
        with self.assertRaisesRegex(mod.KolfixError, "--legacy"):
            mod.rollback_snapshot(target, snapshot, False, False, None)
        mod.rollback_snapshot(target, snapshot, True, True, None, legacy=True)
        self.assertEqual(active.read_bytes(), b'old aliases\n')

    def test_bad_snapshot_name_rejected(self):
        target = self.root / "xpra"
        target.mkdir()
        with self.assertRaisesRegex(mod.KolfixError, "Invalid snapshot"):
            mod.rollback_snapshot(target, "../../etc", True, True, None)
