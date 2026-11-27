"""Loopback llama-server lifecycle and OpenAI-compatible client helpers."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from bootstrap import DEFAULT_MODEL, VISION_PROJECTOR, check_model_dir
from inference_lock import InferenceLease
from service_endpoint import service_base


MODEL_PROFILES = {
    "iq2_m_vulkan": {
        "label": "IQ2_M / Vulkan（CUDA 回滚对照）",
        "model": DEFAULT_MODEL,
        "runtime": "runtime-vulkan-b12774-backup",
        "backend": "Vulkan",
        "gpu_layers": 99,
        "cpu_moe": None,
        "context": 4096,
        "threads": 4,
        "threads_batch": 4,
        "extra": ["--mmproj-offload", "-fa", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"],
    },
    "iq2_m_cuda": {
        "label": "IQ2_M / CUDA（推荐）",
        "model": DEFAULT_MODEL,
        "runtime": "runtime",
        "backend": "CUDA",
        "gpu_layers": 99,
        "cpu_moe": 0,
        "context": 4096,
        "threads": 4,
        "threads_batch": 4,
        "extra": ["--mmproj-offload", "-fa", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"],
    },
    "iq3_s_cuda": {
        "label": "IQ3_S / CUDA（回滚）",
        "model": "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf",
        "runtime": "runtime",
        "backend": "CUDA",
        "gpu_layers": 99,
        "cpu_moe": 23,
        "context": 4096,
        "threads": 4,
        "threads_batch": 4,
        "extra": ["--mmproj-offload", "-fa", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"],
    },
    "iq3_s_vulkan": {
        "label": "IQ3_S / Vulkan（驱动回滚）",
        "model": "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf",
        "runtime": "runtime-vulkan-b12774-backup",
        "backend": "Vulkan",
        "gpu_layers": 12,
        "cpu_moe": None,
        "context": 2048,
        "threads": 6,
        "threads_batch": 6,
        "extra": [],
    },
}


class IncompleteGeneration(RuntimeError):
    """A request ended without a complete final answer."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"生成未完成（{reason}）")


def iter_answer(response):
    """Yield visible text only; require an explicit successful final event."""
    finish = None
    done = False
    produced = False
    for raw in response:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            done = True
            break
        if not data:
            continue
        event = json.loads(data)
        if event.get("error"):
            raise IncompleteGeneration("server_error")
        choices = event.get("choices") or []
        if not choices:
            continue  # usage/timings-only event
        choice = choices[0]
        finish = choice.get("finish_reason") or finish
        piece = (choice.get("delta") or {}).get("content") or ""
        if piece:
            if not isinstance(piece, str):
                raise IncompleteGeneration("invalid_content")
            produced = produced or bool(piece.strip())
            yield piece
    if finish != "stop":
        raise IncompleteGeneration(finish or "stream_disconnected")
    if not done:
        raise IncompleteGeneration("stream_disconnected")
    if not produced:
        raise IncompleteGeneration("empty_final_answer")


def build_context(messages, max_chars=12000):
    """Build a bounded prompt without mutating or deleting durable history.

    Preserve system messages and the earliest user constraints, then include
    the newest complete turns that fit. Character count is a conservative UI
    budget estimate, not a tokenizer measurement.
    """
    if max_chars < 1000:
        raise ValueError("上下文字符预算至少为 1000")
    copied = [{"role": m["role"], "content": m["content"]} for m in messages]
    systems = [m for m in copied if m["role"] == "system"]
    turns = [m for m in copied if m["role"] != "system"]
    if not turns:
        return systems
    first_user = next((m for m in turns if m["role"] == "user"), turns[0])
    latest_user = next((m for m in reversed(turns) if m["role"] == "user"), turns[-1])
    selected = []
    used = sum(len(m["content"]) for m in systems)
    pinned = [first_user] if first_user is not latest_user else []
    if len(first_user["content"]) > max_chars:
        raise ValueError("首轮用户约束超过上下文预算；请提高预算或新建对话，未自动裁剪约束。")
    for msg in pinned:
        if msg not in selected:
            selected.append(msg); used += len(msg["content"])
    tail = []
    for msg in reversed(turns):
        if msg in selected:
            continue
        size = len(msg["content"])
        if msg is latest_user and used + size > max_chars:
            raise ValueError("当前问题与固定约束超过上下文预算；请提高预算或缩短问题。")
        if used + size > max_chars and (tail or msg is not latest_user):
            continue
        tail.append(msg); used += size
    ordered = sorted({id(m): m for m in selected + list(reversed(tail))}.values(), key=turns.index)
    return systems + ordered


def continuation_overlap(previous: str, segment: str, minimum: int = 32) -> int:
    """Return a long exact boundary overlap; never silently rewrite user-visible text."""
    limit = min(len(previous), len(segment))
    for size in range(limit, minimum - 1, -1):
        if previous[-size:] == segment[:size]:
            return size
    return 0


class Runtime:
    def __init__(self, root: Path, models: Path, profile_id="iq2_m_cuda"):
        self.root, self.models = root, models
        self.set_profile(profile_id)
        self.process = None
        self.base = service_base()
        self.log_path = root / "logs" / "llama-server.log"

    def set_profile(self, profile_id):
        if profile_id not in MODEL_PROFILES:
            raise ValueError(f"未知推理配置：{profile_id}")
        if getattr(self, "process", None) is not None and self.process.poll() is None:
            raise RuntimeError("推理服务运行中，必须先停止本应用启动的服务再切换配置。")
        self.profile_id = profile_id
        self.profile = dict(MODEL_PROFILES[profile_id])

    @property
    def model_path(self):
        return self.models / self.profile["model"]

    @property
    def context_size(self):
        return int(self.profile["context"])

    def status(self):
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=2) as r:
                if r.status != 200:return "loading"
            with urllib.request.urlopen(self.base + "/props", timeout=3) as r:
                props=json.load(r)
            expected=str(self.model_path)
            actual_context=props.get("default_generation_settings",{}).get("n_ctx")
            return "ready" if (Path(props.get("model_path","")).resolve()==Path(expected).resolve()
                                and props.get("modalities",{}).get("vision")
                                and actual_context==self.context_size) else "foreign"
        except Exception:
            return "stopped" if not (self.process and self.process.poll() is None) else "loading"

    def start(self, gpu_layers=None, context=None, threads=None):
        if not check_model_dir(self.profile["model"]):
            raise RuntimeError("模型/视觉组件未完成 SHA-256 校验，拒绝启动推理服务。")
        exe = self.root / self.profile["runtime"] / "llama-server.exe"
        model = self.model_path
        mmproj = self.models / VISION_PROJECTOR
        if not exe.exists():
            raise FileNotFoundError(f"缺少 llama-server.exe：{exe}")
        if not model.exists() or not mmproj.exists():
            raise FileNotFoundError("模型或视觉投影文件尚未完整下载")
        if self.status()=="ready":
            return
        if self.status()=="foreign":
            raise RuntimeError("59871 端口已有其他模型服务，占用本地服务地址；已拒绝使用错误模型实例。")
        gpu_layers = self.profile["gpu_layers"] if gpu_layers is None else gpu_layers
        if not isinstance(gpu_layers,int) or isinstance(gpu_layers,bool) or not 1<=gpu_layers<=99:
            raise ValueError("GPU 卸载层数必须是 1–99 的整数")
        context = self.profile["context"] if context is None else context
        threads = self.profile["threads"] if threads is None else threads
        threads = max(1, min(os.cpu_count() or 4, threads))
        threads_batch = self.profile["threads_batch"]
        from urllib.parse import urlsplit
        endpoint=urlsplit(self.base)
        args = [str(exe), "-m", str(model), "--mmproj", str(mmproj), "--host", endpoint.hostname or "127.0.0.1", "--port", str(endpoint.port), "-ngl", str(gpu_layers)]
        if self.profile["cpu_moe"] is not None:
            args += ["--n-cpu-moe", str(self.profile["cpu_moe"])]
        args += ["-c", str(context), "-np", "1", "-t", str(threads), "-tb", str(threads_batch), *self.profile["extra"], "--reasoning", "off", "--reasoning-budget", "64", "--no-reasoning-preserve", "--metrics"]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab", buffering=0)
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)|getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
        self.process = subprocess.Popen(args, cwd=exe.parent, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        deadline = time.time() + 240
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"llama-server 异常退出，代码 {self.process.returncode}")
            if self.status() == "ready":
                return
            time.sleep(.5)
        raise TimeoutError("模型加载超时（240 秒）")

    def stop(self):
        if not self.process:
            if self.status() in {"ready","foreign"}:
                raise RuntimeError("端口服务不是由当前 Runtime 实例启动，未尝试停止其他进程。请通过该服务所属桌面入口正常关闭。")
            return
        if self.process and self.process.poll() is None:
            if os.name=="nt":self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(12)
            except subprocess.TimeoutExpired:
                raise TimeoutError("推理服务未响应正常停止信号；进程仍在运行，未强制终止。")
        self.process = None

    def cancel_active(self,timeout=3):
        response=getattr(self,"_active_response",None)
        if response is None:return False
        response.close()
        return True

    def wait_until_idle(self, timeout=15):
        """Do not release the shared inference lease while llama.cpp still owns its slot."""
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(self.base+"/slots",timeout=2) as response:
                    slots=json.load(response)
                if slots and not any(item.get("is_processing") for item in slots):return True
            except Exception:
                pass
            time.sleep(.1)
        return False

    def chat(self, messages, image_path=None, timeout=240, stream=False, json_schema=None, max_tokens=256,cancel_event=None):
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        if image_path:
            import base64
            mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
            image_data = base64.b64encode(image_path.read_bytes()).decode()
            last = next((m for m in reversed(msgs) if m["role"] == "user"), None)
            if last is None:raise ValueError("图片消息必须包含 user 消息")
            last["content"] = [{"type": "text", "text": last["content"]}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}}]
        cancellable=cancel_event is not None
        body = {"model": "local", "messages": msgs, "temperature": .2, "max_tokens": max_tokens, "stream": bool(stream or cancellable),"thinking_budget_tokens":64,"chat_template_kwargs":{"reasoning_effort":"none"}}
        if json_schema:
            body["response_format"] = {"type":"json_schema","json_schema":{"name":"page_analysis","schema":json_schema,"strict":True}}
        payload = json.dumps(body).encode()
        req = urllib.request.Request(self.base + "/v1/chat/completions", payload, {"Content-Type": "application/json"})
        if stream:
            return self._stream_request(req, timeout,cancel_event)
        if cancellable:
            return "".join(self._stream_request(req,timeout,cancel_event))
        lease=InferenceLease(self.root/"data"/"inference.lock")
        if not lease.acquire(cancel_event=cancel_event,timeout=timeout):raise IncompleteGeneration("cancelled_before_start")
        finished=threading.Event()
        cancel_sent=threading.Event()
        def watch_cancel():
            if cancel_event is None:return
            while not finished.wait(.05):
                if cancel_event.is_set():
                    try:self.cancel_active()
                    except Exception:pass
                    cancel_sent.set();return
        watcher=threading.Thread(target=watch_cancel,daemon=True)
        watcher.start()
        try:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    choice=json.load(r)["choices"][0]
            except TimeoutError:
                if cancel_event and cancel_event.is_set():
                    self.cancel_active();raise IncompleteGeneration("cancelled")
                raise
            if cancel_event and cancel_event.is_set():
                self.cancel_active();raise IncompleteGeneration("cancelled")
            if choice.get("finish_reason") != "stop":
                raise IncompleteGeneration(choice.get("finish_reason") or "missing_finish_reason")
            message=choice["message"]
            content=message.get("content") or ""
            if not isinstance(content,str) or not content.strip():
                raise IncompleteGeneration("empty_final_answer")
            return content
        finally:
            finished.set()
            if watcher.is_alive():watcher.join(.5)
            if cancel_sent.is_set():
                if not self.wait_until_idle():
                    lease.release()
                    raise TimeoutError("取消请求后模型槽仍未空闲；推理锁已释放，服务需要人工检查。")
            lease.release()


    def count_tokens(self, messages, timeout=15, image_path=None):
        """Count the exact rendered chat prompt with the loaded model tokenizer."""
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        if image_path:
            import base64
            mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            last = next((m for m in reversed(msgs) if m["role"] == "user"), None)
            if last is None:raise ValueError("图片消息必须包含 user 消息")
            last["content"] = [
                {"type": "text", "text": last["content"]},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]
        body = {
            "model": "local",
            "messages": msgs,
            "max_tokens": 1,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"reasoning_effort": "none"},
        }
        req = urllib.request.Request(
            self.base + "/v1/chat/completions/input_tokens",
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            value = json.load(response)
        count = value.get("input_tokens")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise RuntimeError("推理服务未返回有效的精确 token 计数。")
        return count

    def build_context(self, messages, token_budget, output_tokens=512, image_path=None):
        """Fit full turns using the active server's actual chat-template tokenizer."""
        if not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 1:
            raise ValueError("token 预算必须为正整数")
        if token_budget + output_tokens > self.context_size:
            raise ValueError(f"输入与输出预算总和超过当前 {self.context_size} token 上下文")
        copied = [{"role": m["role"], "content": m["content"]} for m in messages]
        count = lambda items: self.count_tokens(items, image_path=image_path)
        systems = [m for m in copied if m["role"] == "system"]
        turns = [m for m in copied if m["role"] != "system"]
        if not turns:
            selected = systems
            if count(selected) > token_budget:
                raise ValueError("系统指令超过 token 预算")
            return selected

        first_user = next((m for m in turns if m["role"] == "user"), turns[0])
        latest_user = next((m for m in reversed(turns) if m["role"] == "user"), turns[-1])
        pinned = systems + [first_user]
        groups = []
        current = []
        for message in turns:
            if message is first_user:
                continue
            if message["role"] == "user" and current:
                groups.append(current)
                current = []
            current.append(message)
        if current:
            groups.append(current)
        selected_groups = list(groups)
        candidate = pinned + [m for group in selected_groups for m in group]
        if count(candidate) <= token_budget:
            return candidate
        # Keep the latest complete user turn and the first user constraint. Drop
        # oldest complete turns one at a time, recounting the exact rendered prompt.
        while len(selected_groups) > 1:
            selected_groups.pop(0)
            candidate = pinned + [m for group in selected_groups for m in group]
            if count(candidate) <= token_budget:
                return candidate
        minimum = pinned + [m for group in selected_groups for m in group]
        if latest_user not in minimum:
            minimum.append(latest_user)
        if count(minimum) > token_budget:
            raise ValueError("首轮约束和当前问题已超过 token 预算；请提高预算或缩短内容。")
        return minimum

    def _stream_request(self,req,timeout,cancel_event=None):
        lease=InferenceLease(self.root/"data"/"inference.lock")
        if not lease.acquire(cancel_event=cancel_event,timeout=timeout):
            raise IncompleteGeneration("cancelled_before_start")
        response=None;cancel_sent=threading.Event();finished=threading.Event()
        request_started=False;completed=False
        def watch_cancel():
            if cancel_event is None:return
            while not finished.wait(.05):
                if cancel_event.is_set():
                    try:self.cancel_active()
                    except Exception:pass
                    cancel_sent.set();return
        watcher=threading.Thread(target=watch_cancel,daemon=True)
        try:
            response=urllib.request.urlopen(req,timeout=timeout)
            request_started=True
            self._active_response=response
            watcher.start()
            try:
                yield from iter_answer(response)
                completed=True
                if cancel_event and cancel_event.is_set():raise IncompleteGeneration("cancelled")
            finally:
                if not completed:
                    if cancel_event is None or not cancel_event.is_set():
                        try:self.cancel_active()
                        except Exception:pass
                if response:response.close()
                self._active_response=None
                finished.set()
                if watcher.is_alive():watcher.join(.5)
        finally:
            finished.set()
            cancelled=bool(cancel_event and cancel_event.is_set())
            if request_started and (cancelled or cancel_sent.is_set() or not completed):
                if self.wait_until_idle(timeout=12):lease.release()
                else:
                    def release_after_idle():
                        while not self.wait_until_idle(timeout=60):pass
                        lease.release()
                    threading.Thread(target=release_after_idle,daemon=True).start()
                    raise TimeoutError("HTTP 流已关闭，但模型槽尚未空闲；推理锁保持占用，空闲后自动释放。")
            else:lease.release()


def verify_hash(path: Path, expected: str):
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    actual = h.hexdigest()
    return actual == expected, actual
