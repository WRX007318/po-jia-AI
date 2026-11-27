import json
import tempfile
import threading
import time
from unittest.mock import MagicMock
import unittest
from unittest.mock import patch
from pathlib import Path

sys_path_added = False
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from store import Store
from vision_worker import Worker
from runtime import Runtime
import bootstrap
FIXTURE=Path(__file__).resolve().parent/"fixtures"/"synthetic_business.png"


class StoreWorkerTests(unittest.TestCase):
    def test_confirmed_memory_retrieval_and_correction_history(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td));old=store.add_memory("喜欢使用中文回复，并优先写 Python 工具。")
            self.assertTrue(store.relevant_memories("请用中文写一个 Python 工具。"))
            replacement=store.add_memory("中文优先；代码示例使用 Python。",supersedes=old)
            active=store.memories();all_rows=store.memories(active_only=False)
            self.assertEqual([row["id"] for row in active],[replacement])
            self.assertEqual(len(all_rows),2)
            self.assertEqual(all_rows[1]["active"],0)
            self.assertTrue(store.deactivate_memory(replacement))
            self.assertEqual(store.relevant_memories("Python 中文"),[])

    def test_session_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)); sid=s.new_session("测试")
            s.add_message(sid,"user","保留消息")
            self.assertEqual(Store(Path(td)).messages(sid)[0]["content"],"保留消息")

    def test_image_hash_dedup_and_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"x.png"; source.write_bytes(FIXTURE.read_bytes())
            s=Store(root/"db")
            self.assertTrue(s.import_image(source)[0])
            self.assertFalse(s.import_image(source)[0])
            row=s.samples()[0];s.update_sample(row["id"],"演示页",["合成"],True)
            self.assertEqual(s.samples()[0]["category"],"演示页")

    def test_task_checkpoint_completion(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir()
            for name in ("a.png","b.png"):(source/name).write_bytes(FIXTURE.read_bytes())
            s=Store(root/"db");tid=s.create_task(str(source),10)
            worker=Worker(root/"db")
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            with patch("vision_worker.urllib.request.urlopen",return_value=health), patch("vision_worker.analyze",return_value={"page_type":"合成页","ocr":"样本文字","labels":["合成"],"needs_human_review":False}):
                worker.run_task(s.task(tid))
            task=s.task(tid)
            self.assertEqual(task["status"],"completed")
            self.assertEqual(task["processed"],1)
            self.assertEqual(len(s.samples()),1)

    def test_pause_control_persists(self):
        with tempfile.TemporaryDirectory() as td:
            worker=Worker(Path(td));worker.control.write_text(json.dumps({"action":"pause"}))
            worker.serve_once()
            self.assertTrue(worker.pause.is_set())

    def test_vision_failure_preserves_checkpoint_and_never_completes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();(source/"a.png").write_bytes(FIXTURE.read_bytes())
            s=Store(root/"db");tid=s.create_task(str(source),10);worker=Worker(root/"db")
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",side_effect=RuntimeError("synthetic timeout")):
                worker.run_task(s.task(tid))
            task=s.task(tid)
            self.assertEqual(task["status"],"waiting_model")
            self.assertFalse(task["checkpoint"])
            self.assertEqual(task["processed"],0)

    def test_resume_counts_imported_but_unannotated_unique_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();(source/"a.png").write_bytes(FIXTURE.read_bytes())
            s=Store(root/"db");s.import_image(source/"a.png");tid=s.create_task(str(source),1);worker=Worker(root/"db")
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            annotation={"page_type":"合成页","ocr":"样本文字","labels":["合成"],"needs_human_review":False}
            with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",return_value=annotation):
                worker.run_task(s.task(tid))
            task=s.task(tid)
            self.assertEqual(task["status"],"completed")
            self.assertEqual(task["processed"],1)
            self.assertEqual(len(s.samples()),1)

    def test_model_sha256_guard_and_start_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);model_dir=root/"models";model_dir.mkdir();file=model_dir/"tiny.gguf";file.write_bytes(b"trusted content")
            import hashlib
            digest=hashlib.sha256(file.read_bytes()).hexdigest()
            with patch.object(bootstrap,"MODEL_DIR",model_dir),patch.object(bootstrap,"FILES",{"tiny.gguf":(len(file.read_bytes()),digest)}):
                self.assertTrue(bootstrap.check_model_dir())
                file.write_bytes(b"changed content")
                with self.assertRaisesRegex(RuntimeError,"SHA-256 不匹配"):
                    bootstrap.check_model_dir()
            with patch("runtime.check_model_dir",return_value=False):
                with self.assertRaisesRegex(RuntimeError,"SHA-256 校验"):
                    Runtime(root,model_dir).start()


if __name__=="__main__":unittest.main()
