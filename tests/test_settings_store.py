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
            changed=dict(first,system_prompt="用中文回答",context_budget_tokens=3584)
            saved=store.save(changed)
            self.assertEqual(saved["revision"],1)
            with self.assertRaisesRegex(ValueError,"上下文预算"):
                store.save(dict(saved,context_budget_tokens=20000))
            self.assertEqual(store.load()["system_prompt"],"用中文回答")
            rolled=store.rollback()
            self.assertEqual(rolled["revision"],2)
            self.assertEqual(rolled["system_prompt"],first["system_prompt"])
            self.assertEqual(rolled["context_budget_tokens"],first["context_budget_tokens"])

    def test_pa004_character_budget_migrates_to_token_budget(self):
        with tempfile.TemporaryDirectory() as td:
            store=SettingsStore(Path(td))
            store.path.write_text('{"schema_version":1,"revision":2,"system_prompt":"用中文回答","context_budget_chars":12000,"auto_continue":false,"auto_continue_limit":2}',encoding="utf-8")
            loaded=store.load()
            self.assertEqual(loaded["context_budget_tokens"],3000)
            self.assertEqual(loaded["runtime_profile"],"iq2_m_cuda")

    def test_specific_version_diff_and_rollback_create_new_revision(self):
        with tempfile.TemporaryDirectory() as td:
            store=SettingsStore(Path(td));base=store.load()
            one=store.save(dict(base,system_prompt="第一版",behavior_rules="规则一"))
            two=store.save(dict(one,system_prompt="第二版",behavior_rules="规则二"))
            diff=store.diff(one["revision"])
            self.assertIn("第一版",diff);self.assertIn("第二版",diff)
            rolled=store.rollback_to(one["revision"])
            self.assertEqual(rolled["revision"],two["revision"]+1)
            self.assertEqual(rolled["system_prompt"],"第一版")
            self.assertEqual([x["revision"] for x in store.versions()][:2],[rolled["revision"],two["revision"]])

    def test_gpu_layer_override_is_bounded_versioned_and_rollbackable(self):
        with tempfile.TemporaryDirectory() as td:
            store=SettingsStore(Path(td));base=store.load()
            low=store.save(dict(base,gpu_layers=96))
            self.assertEqual(low["gpu_layers"],96)
            with self.assertRaisesRegex(ValueError,"GPU 卸载层数"):
                store.save(dict(low,gpu_layers=0))
            restored=store.rollback_to(base["revision"])
            self.assertEqual(restored["gpu_layers"],99)

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
