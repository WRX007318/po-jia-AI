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


class Worker:
    def __init__(self, root: Path):
        self.store = Store(root)
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
            with urllib.request.urlopen("http://127.0.0.1:59871/health",timeout=2):pass
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
            except Exception as e:
                self.store.update_task(tid, status="error", error=f"{p.name}: {e}", checkpoint=str(p))
                return
        self.store.update_task(tid, status="completed")

    def analyze_interruptible(self,path):
        while not self.stop.is_set():
            while self.pause.is_set() and not self.stop.is_set():
                self.stop.wait(.25);self.serve_once()
            lease=InferenceLease(self.store.root/"inference.lock")
            if not lease.acquire(cancel_event=self.stop,pause_event=self.pause,timeout=.25):
                self.serve_once()
                continue
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future=pool.submit(analyze,path,120,None,True)
                retry=False;cancel_sent=False
                while not future.done():
                    self.stop.wait(.15);self.serve_once()
                    if (self.stop.is_set() or self.pause.is_set()) and not cancel_sent:
                        try:
                            req=urllib.request.Request("http://127.0.0.1:59871/slots/0?action=cancel",method="POST")
                            urllib.request.urlopen(req,timeout=2).close()
                        except Exception:pass
                        cancel_sent=True
                    if cancel_sent and future.done():break
                    if self.stop.is_set() or self.pause.is_set():
                        retry=True
                if self.stop.is_set():return None
                if retry:continue
                return future.result()
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
