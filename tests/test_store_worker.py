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
            self.assertEqual(task["status"],"error")
            self.assertFalse(task["checkpoint"])
            self.assertTrue(task["current_image"].endswith("a.png"))
            self.assertEqual(task["processed"],0)

    def test_hard_visual_timeout_remains_error_with_retry_checkpoint(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();(source/"a.png").write_bytes(FIXTURE.read_bytes())
            s=Store(root/"db");tid=s.create_task(str(source),10);worker=Worker(root/"db",analysis_timeout=.1)
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            def slow(*_args,**_kwargs):
                time.sleep(.35)
                return {"page_type":"synthetic","ocr":"text","labels":[],"needs_human_review":False}
            with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",side_effect=slow):
                worker.run_task(s.task(tid))
            task=s.task(tid)
            self.assertEqual(task["status"],"error")
            self.assertIn("超过 0.1 秒",task["error"])
            self.assertFalse(task["checkpoint"])
            self.assertTrue(task["current_image"].endswith("a.png"))
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

    def test_sample_annotation_count_and_success_cursor_commit_atomically_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);image=root/"fixture.png";image.write_bytes(FIXTURE.read_bytes())
            store=Store(root/"db");tid=store.create_task(str(root),10);_,digest=store.import_image(image)
            sid=digest[:24];store.set_task_current_image(tid,image)
            before=store.task(tid)
            self.assertFalse(before["success_checkpoint"])
            self.assertEqual(before["current_image"],str(image))
            annotation={"page_type":"业务页","ocr":"样本","labels":["普通"],"needs_human_review":False}
            self.assertEqual(store.commit_task_sample(tid,sid,image,annotation),(True,1))
            reopened=Store(root/"db");task=reopened.task(tid)
            self.assertEqual(task["success_checkpoint"],str(image))
            self.assertIsNone(task["current_image"])
            self.assertEqual(task["processed"],1)
            self.assertEqual(reopened.commit_task_sample(tid,sid,root/"duplicate.png"),(False,1))

    def test_failure_then_database_reopen_retries_current_image_without_skipping(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();image=source/"a.png";image.write_bytes(FIXTURE.read_bytes())
            store=Store(root/"db");tid=store.create_task(str(source),1);worker=Worker(root/"db")
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",side_effect=RuntimeError("injected schema error")):
                worker.run_task(store.task(tid))
            failed=Store(root/"db").task(tid)
            self.assertEqual(failed["status"],"error")
            self.assertFalse(failed["success_checkpoint"])
            self.assertEqual(failed["current_image"],str(image))
            self.assertEqual(failed["processed"],0)
            resumed=Store(root/"db");resumed.update_task(tid,status="queued",error=None)
            annotation={"page_type":"业务页","ocr":"恢复后成功","labels":["普通"],"needs_human_review":False}
            with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",return_value=annotation):
                Worker(root/"db").run_task(Store(root/"db").task(tid))
            recovered=Store(root/"db");complete=recovered.task(tid)
            self.assertEqual(complete["status"],"completed")
            self.assertEqual(complete["success_checkpoint"],str(image))
            self.assertIsNone(complete["current_image"])
            self.assertEqual(complete["processed"],1)
            self.assertEqual(recovered.samples()[0]["ocr"],"恢复后成功")

    def test_pause_and_stop_do_not_advance_success_cursor(self):
        for action in ("pause","stop"):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as td:
                root=Path(td);source=root/"src";source.mkdir();image=source/"a.png";image.write_bytes(FIXTURE.read_bytes())
                store=Store(root/"db");tid=store.create_task(str(source),1);worker=Worker(root/"db")
                health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
                calls=[]
                def interrupted(*_args,**_kwargs):
                    calls.append(1)
                    if action=="stop" or len(calls)==1:getattr(worker,action).set()
                    return {"page_type":"业务页","ocr":"尚未提交","labels":[],"needs_human_review":False}
                with patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",side_effect=interrupted):
                    if action=="pause":
                        thread=threading.Thread(target=worker.run_task,args=(store.task(tid),),daemon=True);thread.start()
                        deadline=time.monotonic()+3
                        while Store(root/"db").task(tid)["status"]!="paused" and time.monotonic()<deadline:time.sleep(.02)
                        paused=Store(root/"db").task(tid)
                        self.assertEqual(paused["status"],"paused")
                        self.assertFalse(paused["success_checkpoint"])
                        self.assertEqual(paused["current_image"],str(image))
                        self.assertEqual(paused["processed"],0)
                        worker.pause.clear();thread.join(3)
                        self.assertFalse(thread.is_alive())
                        self.assertEqual(Store(root/"db").task(tid)["status"],"completed")
                    else:
                        worker.run_task(store.task(tid))
                        task=Store(root/"db").task(tid)
                        self.assertEqual(task["status"],"stopped")
                        self.assertFalse(task["success_checkpoint"])
                        self.assertEqual(task["current_image"],str(image))
                        self.assertEqual(task["processed"],0)

    def test_unstoppable_inference_fault_isolates_worker_and_keeps_shared_lease(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();image=source/"a.png";image.write_bytes(FIXTURE.read_bytes())
            store=Store(root/"db");tid=store.create_task(str(source),1);worker=Worker(root/"db",analysis_timeout=.1,cancel_grace=.1)
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            blocked=threading.Event();started=threading.Event()
            leases=[]
            class FakeLease:
                def __init__(self,*_args):self.released=False;leases.append(self)
                def acquire(self,**_kwargs):return True
                def release(self):self.released=True
            def never_stops(*_args,**_kwargs):
                started.set();blocked.wait(10)
                raise InterruptedError("released by test cleanup")
            with patch("vision_worker.InferenceLease",FakeLease),patch("vision_worker.urllib.request.urlopen",return_value=health),patch("vision_worker.analyze",side_effect=never_stops):
                worker.run_task(store.task(tid))
            task=Store(root/"db").task(tid)
            self.assertTrue(started.is_set())
            self.assertTrue(worker.fault_isolated)
            self.assertEqual(task["status"],"faulted")
            self.assertFalse(task["success_checkpoint"])
            self.assertEqual(task["current_image"],str(image))
            self.assertEqual(len(worker._held_leases),1)
            self.assertFalse(leases[0].released)
            blocked.set()

    def test_fault_isolated_worker_holds_lease_until_slot_is_confirmed_idle(self):
        with tempfile.TemporaryDirectory() as td:
            worker=Worker(Path(td))
            class Lease:
                released=False
                def release(self):self.released=True
            lease=Lease();worker._held_leases=[lease];worker.fault_isolated=True;worker._stop_worker=True
            from vision_worker import InferenceIsolationError
            with patch("vision_worker.wait_for_model_slot_idle",side_effect=[InferenceIsolationError("still busy"),True]) as idle, patch.object(worker.stop,"wait",return_value=False):
                worker.serve()
            self.assertEqual(idle.call_count,2)
            self.assertTrue(lease.released)
            self.assertFalse(worker.fault_isolated)

    def test_shared_inference_queue_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"src";source.mkdir();image=source/"a.png";image.write_bytes(FIXTURE.read_bytes())
            store=Store(root/"db");tid=store.create_task(str(source),1);worker=Worker(root/"db",lease_wait_timeout=.1)
            health=MagicMock();health.__enter__.return_value=health;health.__exit__.return_value=False
            class BusyLease:
                def __init__(self,*_args):pass
                def acquire(self,**_kwargs):return False
                def release(self):pass
            with patch("vision_worker.InferenceLease",BusyLease),patch("vision_worker.urllib.request.urlopen",return_value=health):
                worker.run_task(store.task(tid))
            task=Store(root/"db").task(tid)
            self.assertEqual(task["status"],"error")
            self.assertIn("推理队列超过 0.1 秒",task["error"])
            self.assertFalse(task["success_checkpoint"])
            self.assertEqual(task["current_image"],str(image))

    def test_model_sha256_guard_and_start_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);model_dir=root/"models";model_dir.mkdir();file=model_dir/"tiny.gguf";file.write_bytes(b"trusted content")
            mmproj=model_dir/"tiny-mmproj.gguf";mmproj.write_bytes(b"projector")
            import hashlib
            digest=hashlib.sha256(file.read_bytes()).hexdigest()
            mmhash=hashlib.sha256(mmproj.read_bytes()).hexdigest()
            with patch.object(bootstrap,"MODEL_DIR",model_dir),patch.object(bootstrap,"VISION_PROJECTOR","tiny-mmproj.gguf"),patch.object(bootstrap,"FILES",{"tiny.gguf":(len(file.read_bytes()),digest),"tiny-mmproj.gguf":(len(mmproj.read_bytes()),mmhash)}):
                self.assertTrue(bootstrap.check_model_dir("tiny.gguf"))
                file.write_bytes(b"changed content")
                with self.assertRaisesRegex(RuntimeError,"SHA-256 不匹配"):
                    bootstrap.check_model_dir("tiny.gguf")
            with patch("runtime.check_model_dir",return_value=False):
                with self.assertRaisesRegex(RuntimeError,"SHA-256 校验"):
                    Runtime(root,model_dir).start()


if __name__=="__main__":unittest.main()
