"""Independent, offline-capable scheduler for authorized local image folders."""
from __future__ import annotations

import argparse
import os
import json
import queue
import signal
import threading
import time
import urllib.request
from pathlib import Path

from store import Store
from vision_pipeline import analyze, wait_for_model_slot_idle, InferenceIsolationError as PipelineIsolationError
from inference_lock import InferenceLease
from service_endpoint import service_base

BASE=service_base()


class InferenceIsolationError(PipelineIsolationError):
    """The model slot could not be confirmed idle; retain the cross-process lease."""


class Worker:
    def __init__(self, root: Path, analysis_timeout: float = 20, cancel_grace: float = 5, lease_wait_timeout: float = 120):
        self.store = Store(root)
        self.analysis_timeout=max(.1,float(analysis_timeout))
        self.cancel_grace=max(.1,float(cancel_grace))
        self.lease_wait_timeout=max(.1,float(lease_wait_timeout))
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.control = root / "worker.json"
        self.lock_file = None
        self.fault_isolated = False
        self._held_leases=[]

    def acquire_singleton(self):
        if os.name != "nt": return True
        import msvcrt
        self.store.root.mkdir(parents=True, exist_ok=True)
        self.lock_file = (self.store.root / "worker.lock").open("a+")
        try:
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def run_task(self, task):
        tid = task["id"]
        self._active_task=tid
        success_checkpoint=task["success_checkpoint"] or (task["checkpoint"] if task["status"]=="completed" else "") or ""
        self._active_checkpoint=success_checkpoint
        source = Path(task["source"])
        if not source.is_dir():
            self.store.update_task(tid, status="error", error="本地来源目录不存在")
            return
        try:
            with urllib.request.urlopen(BASE+"/health",timeout=2):pass
        except Exception:
            self.store.update_task(tid,status="waiting_model",error="等待本机模型服务；任务检查点已保留")
            return
        self.store.update_task(tid, status="running", error=None)
        files = sorted(p for p in source.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"})
        checkpoint = success_checkpoint
        processed = int(task["processed"])
        for p in files:
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=checkpoint,success_checkpoint=checkpoint)
                return
            while self.pause.is_set() and not self.stop.wait(.25):
                self.serve_once()
                self.store.update_task(tid, status="paused")
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=checkpoint,success_checkpoint=checkpoint)
                return
            if str(p) <= checkpoint:
                continue
            try:
                self.serve_once()
                while self.pause.is_set() and not self.stop.is_set():
                    self.store.update_task(tid,status="paused",checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                    self.stop.wait(.25);self.serve_once()
                if self.stop.is_set():
                    self.store.update_task(tid,status="stopped",checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                    return
                self.store.set_task_current_image(tid,p)
                added, digest = self.store.import_image(p, source="授权本地目录")
                row=self.store.sample(digest[:24])
                annotation=None
                if row and not row["category"]:
                    # Keep in-progress image separate from the last committed one.
                    self._active_checkpoint=checkpoint
                    while True:
                        annotation=self.analyze_interruptible(p)
                        if annotation is not None:break
                        if self.stop.is_set():
                            self.store.update_task(tid,status="stopped",processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                            return
                        if not self.pause.is_set():
                            # Error/fault states retain this image for explicit recovery.
                            return
                        self.store.update_task(tid,status="paused",processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                        while self.pause.is_set() and not self.stop.is_set():
                            self.stop.wait(.25);self.serve_once()
                        if self.stop.is_set():
                            self.store.update_task(tid,status="stopped",processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                            return
                # Schema validation is performed in analyze(); annotation, unique
                # task count and successful cursor now commit in one transaction.
                _,processed=self.store.commit_task_sample(tid,row["id"],p,annotation)
                checkpoint=str(p)
                self._active_checkpoint=checkpoint
                if processed >= int(task["limit_count"]):
                    break
            except InferenceIsolationError as e:
                self.fault_isolated=True
                self.store.update_task(tid,status="faulted",processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p),error=str(e))
                return
            except TimeoutError as e:
                self.store.update_task(self._active_task,status="error",error=str(e),processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                return None
            except Exception as e:
                self.store.update_task(tid,status="error",error=f"{p.name}: {e}",processed=processed,checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=str(p))
                return
        self.store.update_task(tid,status="completed",checkpoint=checkpoint,success_checkpoint=checkpoint,current_image=None,error=None)

    def analyze_interruptible(self,path):
        queue_started=time.monotonic()
        while not self.stop.is_set():
            paused=self.pause.is_set()
            while self.pause.is_set() and not self.stop.is_set():
                self.store.update_task(self._active_task,status="paused",checkpoint=self._active_checkpoint)
                self.stop.wait(.25);self.serve_once()
            if paused:queue_started=time.monotonic()
            if not self.stop.is_set():self.store.update_task(self._active_task,status="running",checkpoint=self._active_checkpoint)
            lease=InferenceLease(self.store.root/"inference.lock")
            if not lease.acquire(cancel_event=self.stop,pause_event=self.pause,timeout=.25):
                self.serve_once()
                if self.pause.is_set() or self.stop.is_set():continue
                if time.monotonic()-queue_started>self.lease_wait_timeout:
                    raise TimeoutError(f"等待本地推理队列超过 {self.lease_wait_timeout:g} 秒；当前图片保留待恢复")
                continue
            cancel_request=threading.Event();completed=threading.Event();result_queue=queue.Queue(maxsize=1)
            def execute_analysis():
                try:result_queue.put((True,analyze(path,self.analysis_timeout,None,True,cancel_request)))
                except BaseException as exc:result_queue.put((False,exc))
                finally:completed.set()
            analysis_thread=threading.Thread(target=execute_analysis,name="pojia-vision-inference",daemon=True)
            analysis_thread.start()
            try:
                retry=False;cancel_sent=False;started=time.monotonic()
                while not completed.is_set():
                    self.stop.wait(.15);self.serve_once()
                    if time.monotonic()-started>self.analysis_timeout and not cancel_sent:
                        cancel_request.set();cancel_sent=True
                        retry=False
                        raise TimeoutError(f"视觉处理超过 {self.analysis_timeout:g} 秒验收门槛；检查点保留")
                    if (self.stop.is_set() or self.pause.is_set()) and not cancel_sent:
                        cancel_request.set()
                        cancel_sent=True
                    if cancel_sent and completed.is_set():break
                    if self.stop.is_set() or self.pause.is_set():
                        retry=True
                if self.stop.is_set() or self.pause.is_set():
                    cancel_request.set()
                    if not completed.wait(self.cancel_grace):
                        self.fault_isolated=True;self.stop.clear();self._stop_worker=True;self._held_leases.append(lease);lease=None
                        raise InferenceIsolationError(f"取消后 {self.cancel_grace:g} 秒内无法确认推理线程结束；Worker 已隔离并保留推理租约")
                    return None
                if retry:continue
                succeeded,value=result_queue.get_nowait()
                if succeeded:return value
                if isinstance(value,PipelineIsolationError):
                    self.fault_isolated=True;self.stop.clear();self._stop_worker=True;self._held_leases.append(lease);lease=None
                    raise InferenceIsolationError(str(value)) from value
                raise value
            except InferenceIsolationError:
                raise
            except TimeoutError:
                cancel_request.set()
                if not completed.wait(self.cancel_grace):
                    self.fault_isolated=True;self.stop.clear();self._stop_worker=True;self._held_leases.append(lease);lease=None
                    raise InferenceIsolationError(f"超时后 {self.cancel_grace:g} 秒内无法确认推理线程结束；Worker 已隔离并保留推理租约")
                try:ok,value=result_queue.get_nowait()
                except queue.Empty:ok,value=True,None
                if not ok and isinstance(value,PipelineIsolationError):
                    self.fault_isolated=True;self.stop.clear();self._stop_worker=True;self._held_leases.append(lease);lease=None
                    raise InferenceIsolationError(str(value)) from value
                # Preserve the explicit timeout state from run_task; never relabel
                # a hard acceptance timeout as a transient model outage.
                raise
            except Exception as e:
                self.store.update_task(self._active_task,status="error",error=f"视觉识别未完成；保留当前图片以供恢复：{e}",checkpoint=self._active_checkpoint,success_checkpoint=self._active_checkpoint,current_image=str(path))
                return None
            finally:
                if lease is not None:lease.release()
        return None

    def serve(self):
        while not self.stop.is_set():
            self.serve_once()
            if self.stop.is_set():
                break
            if getattr(self,"_stop_worker",False) and not self.fault_isolated:
                break
            if self.fault_isolated:
                try:wait_for_model_slot_idle(timeout=1)
                except InferenceIsolationError:
                    self.stop.wait(1);continue
                for lease in self._held_leases:lease.release()
                self._held_leases.clear();self.fault_isolated=False
                if getattr(self,"_stop_worker",False):break
            queued = [t for t in self.store.tasks() if t["status"] in ("queued", "running", "paused", "waiting_model")]
            if queued and not self.pause.is_set():
                self.run_task(queued[-1])
                if getattr(self,"_stop_worker",False):break
                if (task:=self.store.task(queued[-1]["id"])) and task["status"]=="waiting_model":
                    for _ in range(20):
                        if self.stop.is_set() or self.pause.is_set():break
                        self.stop.wait(.25);self.serve_once()
            elif queued and self.pause.is_set():
                for task in queued:
                    self.store.update_task(task["id"], status="paused")
                self.stop.wait(.5)
            else:
                self.stop.wait(1)

    def serve_once(self):
        try:
            action = json.loads(self.control.read_text(encoding="utf-8")).get("action")
            if action == "pause": self.pause.set()
            elif action == "resume": self.pause.clear()
            elif action == "stop": self.stop.set()
            elif action == "stop_worker":
                self._stop_worker=True
                if not self.fault_isolated:self.stop.set()
            self.control.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError):
            pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    worker = Worker(Path(args.data_dir))
    if not worker.acquire_singleton():
        return
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: worker.stop.set())
    worker.serve()


if __name__ == "__main__":
    main()
