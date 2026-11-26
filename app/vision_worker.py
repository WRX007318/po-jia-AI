"""Independent, offline-capable scheduler for authorized local image folders."""
from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from pathlib import Path

from store import Store


class Worker:
    def __init__(self, root: Path):
        self.store = Store(root)
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.control = root / "worker.json"

    def run_task(self, task):
        tid = task["id"]
        source = Path(task["source"])
        if not source.is_dir():
            self.store.update_task(tid, status="error", error="本地来源目录不存在")
            return
        self.store.update_task(tid, status="running", error=None)
        files = sorted(p for p in source.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"})
        checkpoint = task["checkpoint"] or ""
        processed = int(task["processed"])
        for p in files:
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=str(p))
                return
            while self.pause.is_set() and not self.stop.wait(.25):
                self.store.update_task(tid, status="paused")
            if self.stop.is_set():
                self.store.update_task(tid, status="stopped", checkpoint=str(p))
                return
            if str(p) <= checkpoint:
                continue
            try:
                self.store.import_image(p, source="授权本地目录")
                processed += 1
                self.store.update_task(tid, processed=processed, checkpoint=str(p), status="running")
                if processed >= int(task["limit_count"]):
                    break
            except Exception as e:
                self.store.update_task(tid, status="error", error=f"{p.name}: {e}", checkpoint=str(p))
                return
        self.store.update_task(tid, status="completed")

    def serve(self):
        while not self.stop.is_set():
            self.serve_once()
            queued = [t for t in self.store.tasks() if t["status"] in ("queued", "running", "paused")]
            if queued and not self.pause.is_set():
                self.run_task(queued[-1])
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
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: worker.stop.set())
    worker.serve()


if __name__ == "__main__":
    main()
