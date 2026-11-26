"""Local persistence for sessions, visual tasks and reviewed samples."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "pojia.sqlite3"
        self.images = root / "samples"
        self.images.mkdir(exist_ok=True)
        with self.connect() as c:
            c.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created REAL NOT NULL,FOREIGN KEY(session_id) REFERENCES sessions(id));
              CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,source TEXT NOT NULL,status TEXT NOT NULL,limit_count INTEGER NOT NULL,processed INTEGER NOT NULL DEFAULT 0,checkpoint TEXT,error TEXT,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT UNIQUE NOT NULL,width INTEGER,height INTEGER,source TEXT NOT NULL,category TEXT NOT NULL DEFAULT '',ocr TEXT NOT NULL DEFAULT '',labels TEXT NOT NULL DEFAULT '[]',reviewed INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
            """)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def new_session(self, title="新对话") -> str:
        import uuid
        sid = str(uuid.uuid4())
        with self.connect() as c:
            now = time.time()
            c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (sid, title, now, now))
        return sid

    def sessions(self):
        with self.connect() as c:
            return c.execute("SELECT * FROM sessions ORDER BY updated DESC").fetchall()

    def messages(self, sid):
        with self.connect() as c:
            return c.execute("SELECT role,content,created FROM messages WHERE session_id=? ORDER BY id", (sid,)).fetchall()

    def add_message(self, sid, role, content):
        with self.connect() as c:
            now = time.time()
            c.execute("INSERT INTO messages(session_id,role,content,created) VALUES(?,?,?,?)", (sid, role, content, now))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))

    def create_task(self, source, limit_count):
        import uuid
        tid = str(uuid.uuid4())
        with self.connect() as c:
            c.execute("INSERT INTO tasks(id,source,status,limit_count,updated) VALUES(?,?,'queued',?,?)", (tid, source, limit_count, time.time()))
        return tid

    def task(self, tid):
        with self.connect() as c:
            return c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

    def tasks(self):
        with self.connect() as c:
            return c.execute("SELECT * FROM tasks ORDER BY updated DESC").fetchall()

    def update_task(self, tid, **fields):
        allowed = {"status", "processed", "checkpoint", "error"}
        pairs = [(k, v) for k, v in fields.items() if k in allowed]
        if pairs:
            pairs.append(("updated", time.time()))
            with self.connect() as c:
                c.execute("UPDATE tasks SET " + ",".join(f"{k}=?" for k, _ in pairs) + " WHERE id=?", [v for _, v in pairs] + [tid])

    def import_image(self, path: Path, source="本地文件夹") -> tuple[bool, str]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.connect() as c:
            if c.execute("SELECT 1 FROM samples WHERE sha256=?", (digest,)).fetchone():
                return False, digest
        target = self.images / f"{digest}{path.suffix.lower()}"
        if not target.exists():
            target.write_bytes(path.read_bytes())
        width = height = None
        try:
            from PIL import Image
            with Image.open(target) as im:
                width, height = im.size
        except (ImportError, OSError):
            pass
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO samples(id,path,sha256,width,height,source,created) VALUES(?,?,?,?,?,?,?)", (digest[:24], target.name, digest, width, height, source, time.time()))
        return True, digest

    def samples(self, query="", pending_only=False):
        sql = "SELECT * FROM samples WHERE (category LIKE ? OR ocr LIKE ? OR labels LIKE ?)"
        args: list[Any] = [f"%{query}%"] * 3
        if pending_only:
            sql += " AND reviewed=0"
        sql += " ORDER BY created DESC"
        with self.connect() as c:
            return c.execute(sql, args).fetchall()

    def update_sample(self, sid, category, labels, reviewed):
        with self.connect() as c:
            c.execute("UPDATE samples SET category=?,labels=?,reviewed=? WHERE id=?", (category, json.dumps(labels, ensure_ascii=False), int(reviewed), sid))
