"""Loopback llama-server lifecycle and OpenAI-compatible client helpers."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


class Runtime:
    def __init__(self, root: Path, models: Path):
        self.root, self.models = root, models
        self.process = None
        self.base = "http://127.0.0.1:59871"

    def status(self):
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=2) as r:
                return "ready" if r.status == 200 else "loading"
        except Exception:
            return "stopped" if not (self.process and self.process.poll() is None) else "loading"

    def start(self):
        exe = self.root / "runtime" / "llama-server.exe"
        model = self.models / "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf"
        mmproj = self.models / "mmproj-Inkling-2-Mini-Uncensored-F16.gguf"
        if not exe.exists():
            raise FileNotFoundError(f"缺少 llama-server.exe：{exe}")
        if not model.exists() or not mmproj.exists():
            raise FileNotFoundError("模型或视觉投影文件尚未完整下载")
        args = [str(exe), "-m", str(model), "--mmproj", str(mmproj), "--host", "127.0.0.1", "--port", "59871", "-ngl", "28", "-c", "4096", "-np", "1", "--metrics"]
        self.process = subprocess.Popen(args, cwd=self.root / "runtime", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.time() + 240
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"llama-server 异常退出，代码 {self.process.returncode}")
            if self.status() == "ready":
                return
            time.sleep(.5)
        raise TimeoutError("模型加载超时（240 秒）")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(12)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def chat(self, messages, image_path=None, timeout=240):
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        if image_path:
            import base64
            mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
            image_data = base64.b64encode(image_path.read_bytes()).decode()
            last = msgs[-1]
            last["content"] = [{"type": "text", "text": last["content"]}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}}]
        payload = json.dumps({"model": "local", "messages": msgs, "temperature": .2, "max_tokens": 1024, "stream": False}).encode()
        req = urllib.request.Request(self.base + "/v1/chat/completions", payload, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]


def verify_hash(path: Path, expected: str):
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    actual = h.hexdigest()
    return actual == expected, actual
