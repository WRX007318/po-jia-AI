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
from bootstrap import check_model_dir


class Runtime:
    def __init__(self, root: Path, models: Path):
        self.root, self.models = root, models
        self.process = None
        self.base = "http://127.0.0.1:59871"
        self.log_path = root / "logs" / "llama-server.log"

    def status(self):
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=2) as r:
                if r.status != 200:return "loading"
            with urllib.request.urlopen(self.base + "/props", timeout=3) as r:
                props=json.load(r)
            expected=str(self.models / "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf")
            return "ready" if Path(props.get("model_path","")).resolve()==Path(expected).resolve() and props.get("modalities",{}).get("vision") else "foreign"
        except Exception:
            return "stopped" if not (self.process and self.process.poll() is None) else "loading"

    def start(self, gpu_layers=14, context=2048, threads=6):
        if not check_model_dir():
            raise RuntimeError("模型/视觉组件未完成 SHA-256 校验，拒绝启动推理服务。")
        exe = self.root / "runtime" / "llama-server.exe"
        model = self.models / "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf"
        mmproj = self.models / "mmproj-Inkling-2-Mini-Uncensored-F16.gguf"
        if not exe.exists():
            raise FileNotFoundError(f"缺少 llama-server.exe：{exe}")
        if not model.exists() or not mmproj.exists():
            raise FileNotFoundError("模型或视觉投影文件尚未完整下载")
        if self.status()=="ready":
            return
        if self.status()=="foreign":
            raise RuntimeError("59871 端口已有其他模型服务，占用本地服务地址；已拒绝使用错误模型实例。")
        threads = max(1, min(os.cpu_count() or 4, threads))
        args = [str(exe), "-m", str(model), "--mmproj", str(mmproj), "--host", "127.0.0.1", "--port", "59871", "-ngl", str(gpu_layers), "-c", str(context), "-np", "1", "-t", str(threads), "-tb", str(threads), "--reasoning", "off", "--no-reasoning-preserve", "--metrics"]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab", buffering=0)
        self.process = subprocess.Popen(args, cwd=self.root / "runtime", stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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

    def chat(self, messages, image_path=None, timeout=240, stream=False, json_schema=None, max_tokens=256):
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        if image_path:
            import base64
            mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
            image_data = base64.b64encode(image_path.read_bytes()).decode()
            last = msgs[-1]
            last["content"] = [{"type": "text", "text": last["content"]}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}}]
        body = {"model": "local", "messages": msgs, "temperature": .2, "max_tokens": max_tokens, "stream": stream,"chat_template_kwargs":{"reasoning_effort":"none"}}
        if json_schema:
            body["response_format"] = {"type":"json_schema","json_schema":{"name":"page_analysis","schema":json_schema,"strict":True}}
        payload = json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/v1/chat/completions", payload, {"Content-Type": "application/json"})
        if stream:
            return self._stream_request(req, timeout)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            message=json.load(r)["choices"][0]["message"]
            content=message.get("content") or ""
            if not content.strip():
                raise RuntimeError(f"模型没有生成最终回答（reasoning_content={len(message.get('reasoning_content') or '')} 字符）；请提升生成上限或检查 Inkling chat template。")
            return content

    @staticmethod
    def _stream_request(req, timeout):
        with urllib.request.urlopen(req, timeout=timeout) as response:
            produced=False;finish=""
            for line in response:
                line=line.decode("utf-8",errors="replace").strip()
                if not line.startswith("data:") or line=="data: [DONE]":continue
                event=json.loads(line[5:])
                choice=event["choices"][0];finish=choice.get("finish_reason") or finish
                piece=choice.get("delta",{}).get("content") or ""
                if piece:produced=True;yield piece
            if not produced:
                raise RuntimeError(f"模型没有生成最终回答（finish_reason={finish or 'unknown'}）；reasoning trace 不能当作回答。")


def verify_hash(path: Path, expected: str):
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    actual = h.hexdigest()
    return actual == expected, actual
