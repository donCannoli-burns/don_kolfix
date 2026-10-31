"""Isolated Don Report host-writer tests. No user files touched."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "don-report-store.py"
spec = importlib.util.spec_from_file_location("don_report_store", SCRIPT)
store_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store_module)

def record(source="philter", id="r001"):
    return {
        "schema": "don-report-v1", "id": id,
        "address": "donstate:v1:12345:20261030:32:inventory:item/13:quantity",
        "scope": {"playerId": "12345", "day": "20261030", "life": 32},
        "node": {"domain": "inventory", "subject": "item/13", "metric": "quantity"},
        "source": source, "state": "observed", "evidence": "cached",
        "value": 2, "observedAt": "2026-10-30T20:45:00-05:00",
        "reason": None, "receiptId": None,
    }

class DonReportStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def test_atomic_write_and_replay(self):
        r = record()
        first = store_module.store(self.root, r)
        self.assertEqual(first["disposition"], "written")
        path = Path(first["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text()), r)
        self.assertEqual(store_module.store(self.root, r)["disposition"], "duplicate")
        self.assertEqual(len(list(path.parent.glob("r001.json"))), 1)
    def test_cross_source_different_files(self):
        a = store_module.store(self.root, record())
        b = store_module.store(self.root, record("greenbox"))
        self.assertNotEqual(a["path"], b["path"])
    def test_conflicting_id_rejected_without_overwrite(self):
        first = store_module.store(self.root, record())
        changed = record(); changed["value"] = 3
        with self.assertRaisesRegex(store_module.UnsafeReport, "IDEMPOTENCY_CONFLICT"):
            store_module.store(self.root, changed)
        self.assertEqual(json.loads(Path(first["path"]).read_text())["value"], 2)
    def test_bad_scope_never_creates_d_data(self):
        r = record(); r["scope"]["playerId"] = "../secret"
        with self.assertRaises(store_module.UnsafeReport):
            store_module.store(self.root, r)
        self.assertFalse((self.root / "d_data").exists())
    def test_mismatched_address_rejected(self):
        r = record(); r["scope"]["life"] = 33
        with self.assertRaises(store_module.UnsafeReport):
            store_module.store(self.root, r)
    def test_nonobserved_must_be_null(self):
        r = record(); r["state"] = "ignored"
        with self.assertRaises(store_module.UnsafeReport):
            store_module.store(self.root, r)
    def test_secret_like_value_rejected(self):
        r = record(); r["value"] = "pwd=secret"
        with self.assertRaises(store_module.UnsafeReport):
            store_module.store(self.root, r)
    def test_symlinked_directory_fails_closed(self):
        outside = self.root / "outside"; outside.mkdir()
        base = self.root / "d_data"; base.mkdir()
        (base / "d_philter").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(store_module.UnsafeReport, "symlink"):
            store_module.store(self.root, record())
        self.assertEqual(list(outside.iterdir()), [])
    def test_malformed_extra_field_rejected(self):
        r = record(); r["rawPage"] = "sensitive"
        with self.assertRaises(store_module.UnsafeReport):
            store_module.validate(r)
    def test_requires_preexisting_root(self):
        with self.assertRaisesRegex(store_module.UnsafeReport, "root"):
            store_module.store(self.root / "missing", record())

if __name__ == "__main__":
    unittest.main(verbosity=2)
