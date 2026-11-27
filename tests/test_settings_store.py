import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from settings_store import SettingsStore, DEFAULTS


class SettingsStoreTests(unittest.TestCase):
    def test_atomic_validated_version_and_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            store=SettingsStore(Path(td));first=store.load()
            changed=dict(first,system_prompt="用中文回答",context_budget_chars=16000)
            saved=store.save(changed)
            self.assertEqual(saved["revision"],1)
            with self.assertRaisesRegex(ValueError,"上下文预算"):
                store.save(dict(saved,context_budget_chars=999999))
            self.assertEqual(store.load()["system_prompt"],"用中文回答")
            rolled=store.rollback()
            self.assertEqual(rolled["revision"],2)
            self.assertEqual(rolled["system_prompt"],first["system_prompt"])
            self.assertEqual(rolled["context_budget_chars"],first["context_budget_chars"])

    def test_invalid_existing_file_is_preserved_until_valid_replacement(self):
        with tempfile.TemporaryDirectory() as td:
            store=SettingsStore(Path(td));store.root.mkdir(parents=True,exist_ok=True)
            store.path.write_text("{broken",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"未覆盖"):
                store.load()
            replacement=store.save(dict(DEFAULTS,system_prompt="修复后"))
            self.assertEqual(replacement["system_prompt"],"修复后")
            self.assertTrue(list(store.history.glob("invalid-*.json")))
            self.assertEqual(store.load(),replacement)


if __name__=="__main__":unittest.main()
