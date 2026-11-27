"""Cross-process lease for the single local llama-server inference slot."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class InferenceLease:
    def __init__(self, path: Path):
        self.path=Path(path)
        key=str(self.path.resolve()).casefold()
        with _THREAD_LOCKS_GUARD:
            self.thread_lock=_THREAD_LOCKS.setdefault(key,threading.Lock())
        self.handle=None
        self.file_locked=False

    def acquire(self,cancel_event=None,pause_event=None,timeout=None,poll=.1):
        started=time.monotonic()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        while True:
            if cancel_event is not None and cancel_event.is_set():return False
            if pause_event is not None and pause_event.is_set():return False
            if timeout is not None and time.monotonic()-started>=timeout:return False
            if not self.thread_lock.acquire(timeout=poll):continue
            try:
                self.handle=self.path.open("a+b")
                self.handle.seek(0,os.SEEK_END)
                if self.handle.tell()==0:
                    self.handle.write(b"\0");self.handle.flush()
                self.handle.seek(0)
                if os.name=="nt":
                    import msvcrt
                    try:msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
                    except OSError:
                        self.handle.close();self.handle=None;self.thread_lock.release();time.sleep(poll);continue
                else:
                    import fcntl
                    try:fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:
                        self.handle.close();self.handle=None;self.thread_lock.release();time.sleep(poll);continue
                self.file_locked=True
                return True
            except Exception:
                if self.handle:self.handle.close();self.handle=None
                self.thread_lock.release()
                raise

    def release(self):
        try:
            if self.file_locked and self.handle:
                self.handle.seek(0)
                if os.name=="nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        finally:
            self.file_locked=False
            if self.handle:self.handle.close();self.handle=None
            if self.thread_lock.locked():self.thread_lock.release()

    def __enter__(self):
        if not self.acquire():raise TimeoutError("等待本地推理队列租约被取消")
        return self

    def __exit__(self,*_):self.release()
