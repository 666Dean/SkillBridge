import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bridge import BridgeError, Library, inventory, linked, make_link, metadata, valid_name


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="skillbridge-", dir=os.environ.get("SKILLBRIDGE_TEST_ROOT"))
        self.root = Path(self.tmp.name)
        self.lib = Library(home=self.root)
        self.source = self.root / "素材 与空格' $symbol" / "sample"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: sample\ndescription: 测试共享技能\n---\n请输出测试。\n", encoding="utf-8")
        (self.source / "scripts").mkdir()
        (self.source / "scripts/run.py").write_text("print('hello')", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def copy_to(self, host):
        path = self.lib.hosts[host] / "sample"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.source, path)
        return path

    def test_import_mount_edit_and_detach(self):
        name = self.lib.import_skill(self.source)
        self.lib.mount(name)
        self.lib.mount(name)  # Idempotent.
        for h in self.lib.hosts:
            self.assertEqual(self.lib.status(name, h), "已共享")
            self.assertTrue(linked(self.lib.hosts[h] / name))
        (self.lib.skill(name) / "scripts/run.py").write_text("new", encoding="utf-8")
        for p in self.lib.hosts.values():
            self.assertEqual((p / name / "scripts/run.py").read_text(), "new")
        self.lib.detach(name, "codex")
        self.assertTrue(self.lib.skill(name).exists())
        self.assertTrue(self.source.exists())
        self.assertEqual(self.lib.status(name, "workbuddy"), "已共享")

    def test_conflict_never_overwritten(self):
        self.lib.import_skill(self.source)
        existing = self.copy_to("workbuddy")
        (existing / "scripts/run.py").write_text("different")
        with self.assertRaises(BridgeError):
            self.lib.mount("sample")
        self.assertFalse((self.lib.hosts["codex"] / "sample").exists())
        with self.assertRaises(BridgeError):
            self.lib.consolidate("sample")
        self.assertEqual((existing / "scripts/run.py").read_text(), "different")

    def test_consolidate_and_restore(self):
        codex = self.copy_to("codex")
        buddy = self.copy_to("workbuddy")
        original = inventory(codex)
        result = self.lib.consolidate("sample")
        self.assertEqual(len(self.lib.transactions()), 1)
        self.assertEqual(inventory(self.lib.skill("sample")), original)
        self.assertTrue(linked(codex) and linked(buddy))
        self.lib.restore(result["transaction"])
        self.assertFalse(linked(codex) or linked(buddy))
        self.assertEqual(inventory(codex), original)
        self.assertEqual(inventory(buddy), original)
        self.assertFalse(self.lib.skill("sample").exists())

    def test_consolidate_existing_store_purge(self):
        self.lib.import_skill(self.source)
        self.copy_to("codex")
        self.copy_to("workbuddy")
        result = self.lib.consolidate("sample")
        n = self.lib.purge(result["transaction"])
        self.assertGreater(n, 0)
        self.assertTrue(self.lib.skill("sample").is_dir())
        self.assertEqual(self.lib.transactions(), [])
        for h in self.lib.hosts:
            self.assertEqual(self.lib.status("sample", h), "已共享")

    def test_failed_second_link_rolls_back(self):
        codex = self.copy_to("codex")
        buddy = self.copy_to("workbuddy")
        calls = []
        def fail_second(target, path):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("simulated failure")
            make_link(target, path)
        with patch("bridge.make_link", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.lib.consolidate("sample")
        self.assertTrue(codex.is_dir() and buddy.is_dir())
        self.assertFalse(linked(codex) or linked(buddy))
        self.assertFalse(self.lib.skill("sample").exists())

    def test_modified_store_blocks_restore_and_purge(self):
        self.copy_to("codex")
        self.copy_to("workbuddy")
        result = self.lib.consolidate("sample")
        (self.lib.skill("sample") / "SKILL.md").write_text("changed")
        for operation in [self.lib.restore, self.lib.purge]:
            with self.assertRaises(BridgeError):
                operation(result["transaction"])
        self.assertTrue(self.lib.skill("sample").exists())

    def test_nested_links_rejected(self):
        external = self.root / "outside"
        external.mkdir()
        make_link(external, self.source / "external")
        with self.assertRaises(BridgeError):
            self.lib.import_skill(self.source)
        self.assertFalse(self.lib.skill("sample").exists())

    def test_names_and_roots_guarded(self):
        for name in ["../outside", "CON", "nul", "com1", "a/b", "", "a' $x", "A"]:
            with self.assertRaises(BridgeError):
                valid_name(name)
        with self.assertRaises(BridgeError):
            Library(home=self.root, store=self.root / ".codex/skills/sample")

    def test_tampered_backup_path_rejected(self):
        self.copy_to("codex")
        result = self.lib.consolidate("sample")
        record_path = self.lib.state / "backups" / result["transaction"] / "transaction.json"
        record = json.loads(record_path.read_text())
        record["moves"][0][1] = str(self.source)
        record_path.write_text(json.dumps(record))
        with self.assertRaises(BridgeError):
            self.lib.purge(result["transaction"])
        self.assertTrue(self.source.exists())

    def test_metadata_yaml_multiline_and_bom(self):
        (self.source / "SKILL.md").write_text("\ufeff---\nname: sample\ndescription: |\n  A multiline\n  description\n---\nBody\n", encoding="utf-8")
        self.assertEqual(metadata(self.source)["name"], "sample")
        self.assertEqual(metadata(self.source)["description"], "A multiline\ndescription")

    def test_foreign_link_untouched(self):
        self.lib.import_skill(self.source)
        path = self.lib.hosts["workbuddy"] / "sample"
        make_link(self.source, path)
        with self.assertRaises(BridgeError):
            self.lib.mount("sample")
        with self.assertRaises(BridgeError):
            self.lib.detach("sample", "workbuddy")
        self.assertEqual(path.resolve(), self.source.resolve())

    def test_lock_prevents_concurrent_writer(self):
        with self.lib.lock():
            with self.assertRaises(BridgeError):
                self.lib.import_skill(self.source)
        self.assertFalse((self.lib.state / "write.lock").exists())

    def test_restore_failure_returns_to_shared_state(self):
        self.copy_to("codex")
        self.copy_to("workbuddy")
        result = self.lib.consolidate("sample")
        original_rename = Path.rename
        failed = []
        def failing_rename(path, destination):
            if path == self.lib.skill("sample") and not failed:
                failed.append(True)
                raise OSError("simulated restore failure")
            return original_rename(path, destination)
        with patch.object(Path, "rename", failing_rename):
            with self.assertRaises(OSError):
                self.lib.restore(result["transaction"])
        for host in self.lib.hosts:
            self.assertEqual(self.lib.status("sample", host), "已共享")
        self.assertEqual(len(self.lib.transactions()), 1)
        self.lib.restore(result["transaction"])

    def test_interrupted_transaction_blocks_automatic_actions(self):
        self.copy_to("codex")
        result = self.lib.consolidate("sample")
        journal = self.lib.state / "backups" / result["transaction"] / "transaction.json"
        record = json.loads(journal.read_text())
        record["status"] = "pending"
        journal.write_text(json.dumps(record))
        for operation in [self.lib.restore, self.lib.purge]:
            with self.assertRaises(BridgeError):
                operation(result["transaction"])
        self.assertTrue(self.lib.skill("sample").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
