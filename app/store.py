"""Local persistence for sessions, visual tasks and reviewed samples."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
import struct
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
              CREATE TABLE IF NOT EXISTS chat_drafts(session_id TEXT PRIMARY KEY,content TEXT NOT NULL,status TEXT NOT NULL,updated REAL NOT NULL,FOREIGN KEY(session_id) REFERENCES sessions(id));
              CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,source TEXT NOT NULL,status TEXT NOT NULL,limit_count INTEGER NOT NULL,processed INTEGER NOT NULL DEFAULT 0,checkpoint TEXT,error TEXT,updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT UNIQUE NOT NULL,width INTEGER,height INTEGER,source TEXT NOT NULL,category TEXT NOT NULL DEFAULT '',ocr TEXT NOT NULL DEFAULT '',labels TEXT NOT NULL DEFAULT '[]',reviewed INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY,content TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,source TEXT NOT NULL DEFAULT 'user',supersedes INTEGER,created REAL NOT NULL,updated REAL NOT NULL,FOREIGN KEY(supersedes) REFERENCES memories(id));
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

    def draft(self, sid):
        with self.connect() as c:
            return c.execute("SELECT * FROM chat_drafts WHERE session_id=?", (sid,)).fetchone()

    def begin_draft(self, sid, prompt):
        """Commit the user message and empty answer together."""
        with self.connect() as c:
            now = time.time()
            c.execute("INSERT INTO chat_drafts VALUES(?,?,'generating',?)", (sid, "", now))
            c.execute("INSERT INTO messages(session_id,role,content,created) VALUES(?,?,?,?)", (sid, "user", prompt, now))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))

    def save_draft(self, sid, content, status):
        with self.connect() as c:
            now = time.time()
            changed = c.execute("UPDATE chat_drafts SET content=?,status=?,updated=? WHERE session_id=?", (content,status,now,sid))
            if changed.rowcount != 1:
                raise RuntimeError("对话草稿不存在")
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now,sid))

    def finish_draft(self, sid, content):
        if not content.strip():
            raise ValueError("空回答不能标为完成")
        with self.connect() as c:
            now = time.time()
            changed = c.execute("DELETE FROM chat_drafts WHERE session_id=?", (sid,))
            if changed.rowcount != 1:
                raise RuntimeError("对话草稿不存在")
            c.execute("INSERT INTO messages(session_id,role,content,created) VALUES(?,?,?,?)", (sid,"assistant",content,now))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now,sid))

    def discard_draft(self, sid):
        """Explicit user action: keep received text in history as unfinished."""
        with self.connect() as c:
            row = c.execute("SELECT content FROM chat_drafts WHERE session_id=?", (sid,)).fetchone()
            if row is None:
                return
            now = time.time()
            c.execute("INSERT INTO messages(session_id,role,content,created) VALUES(?,?,?,?)",
                      (sid,"assistant",row["content"] + "\n\n[用户结束未完成的生成]",now))
            c.execute("DELETE FROM chat_drafts WHERE session_id=?", (sid,))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (now,sid))

    def memories(self, active_only=True):
        sql="SELECT * FROM memories"+(" WHERE active=1" if active_only else "")+" ORDER BY updated DESC,id DESC"
        with self.connect() as c:return c.execute(sql).fetchall()

    def add_memory(self, content, source="user", supersedes=None):
        content=" ".join(str(content).split())
        if not content or len(content)>1000:raise ValueError("记忆内容必须为 1–1000 个字符")
        with self.connect() as c:
            now=time.time()
            if supersedes is not None:
                changed=c.execute("UPDATE memories SET active=0,updated=? WHERE id=? AND active=1",(now,supersedes))
                if changed.rowcount!=1:raise ValueError("待校正记忆不存在或已停用")
            cur=c.execute("INSERT INTO memories(content,active,source,supersedes,created,updated) VALUES(?,1,?,?,?,?)",
                          (content,source,supersedes,now,now))
            return cur.lastrowid

    def deactivate_memory(self, memory_id):
        with self.connect() as c:
            return c.execute("UPDATE memories SET active=0,updated=? WHERE id=? AND active=1",(time.time(),memory_id)).rowcount==1

    def relevant_memories(self, query, max_items=8, max_chars=1500):
        """Return bounded, query-overlapping confirmed memories without model-written mutations."""
        query=str(query).casefold();ranked=[]
        for row in self.memories():
            content=row["content"];normalized=content.casefold()
            ascii_terms=set(__import__("re").findall(r"[a-z0-9_]{3,}",query))
            score=sum(1 for term in ascii_terms if term in normalized)
            for i in range(max(0,len(query)-1)):
                pair=query[i:i+2]
                if any("\u4e00"<=ch<="\u9fff" for ch in pair) and pair in normalized:score+=1
            if score:ranked.append((score,row["updated"],content))
        ranked.sort(key=lambda x:(-x[0],-x[1]))
        result=[];used=0
        for _,_,content in ranked:
            if len(result)>=max_items or used+len(content)>max_chars:continue
            result.append(content);used+=len(content)
        return result

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
        h=hashlib.sha256()
        with path.open("rb") as f:
            header=f.read(24)
            if path.stat().st_size>50*1024*1024:
                raise ValueError("图片超过 50 MiB 导入上限")
            if path.suffix.lower()==".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("PNG 文件头无效")
            if path.suffix.lower() in {".jpg",".jpeg"} and not header.startswith(b"\xff\xd8"):
                raise ValueError("JPEG 文件头无效")
            h.update(header)
            for block in iter(lambda:f.read(8*1024*1024),b""):h.update(block)
        digest = h.hexdigest()
        with self.connect() as c:
            if c.execute("SELECT 1 FROM samples WHERE sha256=?", (digest,)).fetchone():
                return False, digest
        target = self.images / f"{digest}{path.suffix.lower()}"
        if not target.exists():
            shutil.copy2(path,target)
        width = height = None
        if path.suffix.lower()==".png":
            with path.open("rb") as f:data=f.read(24)
            width,height=struct.unpack(">II",data[16:24])
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

    def sample(self,sid):
        with self.connect() as c:return c.execute("SELECT * FROM samples WHERE id=?",(sid,)).fetchone()

    def update_sample(self, sid, category, labels, reviewed):
        with self.connect() as c:
            c.execute("UPDATE samples SET category=?,labels=?,reviewed=? WHERE id=?", (category, json.dumps(labels, ensure_ascii=False), int(reviewed), sid))

    def annotate_sample(self, sid, category, ocr, labels, needs_human_review):
        label_set=list(labels or [])
        if needs_human_review:label_set.append("需要人工复核")
        with self.connect() as c:
            c.execute("UPDATE samples SET category=?,ocr=?,labels=?,reviewed=0 WHERE id=?", (category, ocr, json.dumps(label_set,ensure_ascii=False),sid))
