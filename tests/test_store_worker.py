import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys_path_added = False
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from store import Store
from vision_worker import Worker


class StoreWorkerTests(unittest.TestCase):
    def test_session_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            s=Store(Path(td)); sid=s.new_session("测试")
            s.add_message(sid,"user","保留消息")
            self.assertEqual(Store(Path(td)).messages(sid)[0]["content"],"保留消息")

    def test_image_hash_dedup_and_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"x.png"; source.write_bytes(b"synthetic authorized sample")
            s=Store(root/"db")
            self.assertTrue(s.import_image(source)[0])
            self.assertFalse(s.import_image(source)[0])
            row=s.samples()[0];s.update_sample(row["id"],"演示页",["合成"],True)
            self.assertEqual(s.samples()[0]["category"],"演示页")

    def test_task_checkpoint_completion(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir()
            for name in ("a.png","b.jpg"):(source/name).write_bytes(name.encode())
            s=Store(root/"db");tid=s.create_task(str(source),10)
            worker=Worker(root/"db");worker.run_task(s.task(tid))
            task=s.task(tid)
            self.assertEqual(task["status"],"completed")
            self.assertEqual(task["processed"],2)
            self.assertEqual(len(s.samples()),2)

    def test_pause_control_persists(self):
        with tempfile.TemporaryDirectory() as td:
            worker=Worker(Path(td));worker.control.write_text(json.dumps({"action":"pause"}))
            worker.serve_once()
            self.assertTrue(worker.pause.is_set())


if __name__=="__main__":unittest.main()
