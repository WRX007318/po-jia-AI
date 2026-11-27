"""Independent, offline-capable scheduler for authorized local image folders."""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import json
import signal
import threading
import time
import urllib.request
from pathlib import Path

from store import Store
from vision_pipeline import analyze
from inference_lock import InferenceLease
from service_endpoint import service_base

BASE=service_base()


class Worker:
    def __init__(self, root: Path, analysis_timeout: float = 20):
        self.store = Store(root)
        self.analysis_timeout=max(.1,float(analysis_timeout))
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.control = root / "worker.json"
        self.lock_file = None

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
        self._active_checkpoint=task["checkpoint"] or ""
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
        checkpoint = task["checkpoint"] or ""
        processed = int(task["processed"])
        for p in files:
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=checkpoint)
                return
            while self.pause.is_set() and not self.stop.wait(.25):
                self.serve_once()
                self.store.update_task(tid, status="paused")
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=checkpoint)
                return
            if str(p) <= checkpoint:
                continue
            try:
                self.serve_once()
                while self.pause.is_set() and not self.stop.is_set():
                    self.store.update_task(tid,status="paused",checkpoint=str(p))
                    self.stop.wait(.25);self.serve_once()
                added, digest = self.store.import_image(p, source="授权本地目录")
                newly_processed=added
                row=self.store.sample(digest[:24])
                if row and not row["category"]:
                    # The current image is the recoverable boundary until model
                    # annotation commits; persist it before an interrupt or timeout.
                    self._active_checkpoint=str(p)
                    annotation=self.analyze_interruptible(p)
                    if annotation is None:
                        if self.stop.is_set():
                            self.store.update_task(tid,status="stopped",processed=processed,checkpoint=checkpoint)
                            return
                        if not self.pause.is_set():
                            # Model failure stays resumable and never advances
                            # the checkpoint beyond this unannotated sample.
                            return
                        self.store.update_task(tid,status="paused",processed=processed,checkpoint=checkpoint)
                        while self.pause.is_set() and not self.stop.is_set():
                            self.stop.wait(.25);self.serve_once()
                        if self.stop.is_set():
                            self.store.update_task(tid,status="stopped",processed=processed,checkpoint=checkpoint)
                            return
                        continue
                    self.store.annotate_sample(row["id"],annotation["page_type"],annotation["ocr"],annotation["labels"],annotation["needs_human_review"])
                    newly_processed=True
                if newly_processed:processed+=1
                self.store.update_task(tid, processed=processed, checkpoint=str(p), status="running")
                checkpoint=str(p)
                self._active_checkpoint=checkpoint
                if newly_processed and processed >= int(task["limit_count"]):
                    break
            except TimeoutError as e:
                self.store.update_task(self._active_task,status="error",error=str(e),checkpoint=self._active_checkpoint)
                return None
            except Exception as e:
                self.store.update_task(tid, status="error", error=f"{p.name}: {e}", checkpoint=str(p))
                return
        self.store.update_task(tid, status="completed")

    def analyze_interruptible(self,path):
        while not self.stop.is_set():
            while self.pause.is_set() and not self.stop.is_set():
                self.store.update_task(self._active_task,status="paused",checkpoint=self._active_checkpoint)
                self.stop.wait(.25);self.serve_once()
            if not self.stop.is_set():self.store.update_task(self._active_task,status="running",checkpoint=self._active_checkpoint)
            lease=InferenceLease(self.store.root/"inference.lock")
            if not lease.acquire(cancel_event=self.stop,pause_event=self.pause,timeout=.25):
                self.serve_once()
                continue
            cancel_request=threading.Event()
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future=pool.submit(analyze,path,120,None,True,cancel_request)
                retry=False;cancel_sent=False;started=time.monotonic()
                while not future.done():
                    self.stop.wait(.15);self.serve_once()
                    if time.monotonic()-started>self.analysis_timeout and not cancel_sent:
                        cancel_request.set();cancel_sent=True
                        retry=False
                        raise TimeoutError(f"视觉处理超过 {self.analysis_timeout:g} 秒验收门槛；检查点保留")
                    if (self.stop.is_set() or self.pause.is_set()) and not cancel_sent:
                        cancel_request.set()
                        cancel_sent=True
                    if cancel_sent and future.done():break
                    if self.stop.is_set() or self.pause.is_set():
                        retry=True
                if self.stop.is_set():return None
                if retry:continue
                return future.result()
            except TimeoutError:
                # Preserve the explicit timeout state from run_task; never relabel
                # a hard acceptance timeout as a transient model outage.
                raise
            except Exception as e:
                self.store.update_task(self._active_task,status="waiting_model",error=f"视觉识别暂不可用，稍后从同一检查点重试：{e}",checkpoint=self._active_checkpoint)
                return None
            finally:
                pool.shutdown(wait=True,cancel_futures=True)
                lease.release()
        return None

    def serve(self):
        while not self.stop.is_set():
            self.serve_once()
            if self.stop.is_set():
                break
            if getattr(self,"_stop_worker",False):
                break
            queued = [t for t in self.store.tasks() if t["status"] in ("queued", "running", "paused", "waiting_model")]
            if queued and not self.pause.is_set():
                self.run_task(queued[-1])
                if getattr(self,"_stop_worker",False):
                    break
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
                self.stop.set()
                self._stop_worker=True
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
