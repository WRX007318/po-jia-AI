"""Offline-first visual OCR/classification pipeline for authorized image files."""
from __future__ import annotations

import base64
import contextlib
import json
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from inference_lock import InferenceLease
from service_endpoint import service_base

BASE=service_base()
API=BASE+"/v1/chat/completions"
SCHEMA={"type":"object","properties":{"page_type":{"type":"string"},"visible_text":{"type":"array","maxItems":4,"items":{"type":"string"}},"elements":{"type":"array","maxItems":2,"items":{"type":"object","properties":{"type":{"type":"string"},"text":{"type":"string"},"label":{"type":"string"}},"required":["type","text","label"],"additionalProperties":False}},"labels":{"type":"array","maxItems":3,"items":{"type":"string"}},"needs_human_review":{"type":"boolean"}},"required":["page_type","visible_text","elements","labels","needs_human_review"],"additionalProperties":False}


class IncompleteVisualResponse(RuntimeError):
    """The inference stream ended without an explicit normal stop reason."""


class InferenceIsolationError(RuntimeError):
    """The model slot could not be proven idle within a bounded drain period."""


_QUARANTINED_LEASES=[]


class _OwnedInferenceLease:
    def __init__(self,path,timeout):self.lease=InferenceLease(path);self.timeout=timeout
    def __enter__(self):
        if not self.lease.acquire(timeout=self.timeout):raise TimeoutError("等待本地视觉推理租约超时")
        return self.lease
    def __exit__(self,exc_type,exc_value,_traceback):
        if exc_type is not None and issubclass(exc_type,InferenceIsolationError):
            _QUARANTINED_LEASES.append(self.lease)
        else:self.lease.release()


def wait_for_model_slot_idle(timeout=5):
    deadline=time.monotonic()+max(.05,float(timeout))
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(BASE+"/slots",timeout=min(2,max(.05,deadline-time.monotonic()))) as response:
                slots=json.load(response)
        except Exception as exc:raise InferenceIsolationError("无法查询 llama.cpp 模型槽；推理所有权仍不确定") from exc
        if not any(slot.get("is_processing") for slot in slots):return True
        time.sleep(.1)
    raise InferenceIsolationError(f"模型槽在 {timeout:g} 秒内仍未确认空闲")


def tesseract_ocr(path:Path,timeout=15):
    exe=shutil.which("tesseract")
    if not exe:return ""
    try:
        result=subprocess.run([exe,str(path),"stdout","-l","chi_sim+eng"],capture_output=True,text=True,timeout=timeout,check=True)
        return result.stdout[:30000].strip()
    except subprocess.TimeoutExpired as exc:raise TimeoutError("标准 OCR 超出视觉总时间预算") from exc
    except FileNotFoundError:return ""
    except subprocess.CalledProcessError as exc:return (exc.stdout or "")[:30000].strip()


def analyze(path:Path,timeout=360,lease_path:Path|None=None,lease_held=False,cancel_event=None,slot_drain_timeout=5):
    started=time.monotonic();budget=min(max(.1,float(timeout)),20.0);deadline=started+budget
    def remaining():
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError("OCR、视觉推理及结果校验总耗时超过 20 秒")
        return left
    if path.stat().st_size>50*1024*1024:raise ValueError("图片超过识别大小限制")
    if cancel_event and cancel_event.is_set():raise InterruptedError("视觉推理已取消")
    ext=path.suffix.lower();mime={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".bmp":"image/bmp"}.get(ext)
    if not mime:raise ValueError("不支持的图片类型")
    image=base64.b64encode(path.read_bytes()).decode("ascii")
    local_ocr=tesseract_ocr(path,timeout=min(15,remaining()))
    if cancel_event and cancel_event.is_set():raise InterruptedError("视觉推理已取消")
    prompt=("对这张由用户授权提供的业务页面截图做 OCR 与页面元素标注。只返回符合 JSON Schema 的结果。"
            "识别页面类别、最多4条重要可见文字（优先页面标题、列表/表格标题、订单号及状态）、最多1个主要页面元素、最多2个分类标签；每项用几个字简短表达。"
            "如果包含验证码、安全验证、人机校验、登录挑战或访问限制，needs_human_review=true；不要识别、转录或描述挑战内容。"
            "不要输出或推测账号、密钥等未显示内容。")
    if local_ocr:prompt+=f"\n本地 OCR 引擎提取文字如下，可用于核对但需以图片为准：\n{local_ocr[:12000]}"
    payload={"model":"local","messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:{mime};base64,{image}"}}]}],"temperature":0,"max_tokens":512,"thinking_budget_tokens":64,"stream":cancel_event is not None,"chat_template_kwargs":{"reasoning_effort":"none"},"response_format":{"type":"json_schema","json_schema":{"name":"visual_annotation","schema":SCHEMA,"strict":True}}}
    req=urllib.request.Request(API,json.dumps(payload,ensure_ascii=False).encode(),{"Content-Type":"application/json"})
    lease=(_OwnedInferenceLease(lease_path,budget) if lease_path and not lease_held else contextlib.nullcontext())
    with lease:
        if cancel_event is None:
            try:
                with urllib.request.urlopen(req,timeout=remaining()) as r:
                    choice=json.load(r)["choices"][0]
                    if choice.get("finish_reason")!="stop":raise IncompleteVisualResponse(f"视觉响应未正常结束：{choice.get('finish_reason') or 'missing'}")
                    raw=choice["message"]["content"]
            except Exception:
                wait_for_model_slot_idle(slot_drain_timeout)
                raise
        else:
            response=urllib.request.urlopen(req,timeout=remaining());finished=threading.Event()
            def watch_cancel():
                while not finished.wait(.05):
                    if cancel_event.is_set():
                        try:response.close()
                        except Exception:pass
                        return
            watcher=threading.Thread(target=watch_cancel,daemon=True);watcher.start()
            try:
                chunks=[];finish_reason=None;done_marker=False
                for line in response:
                    line=line.decode("utf-8").strip()
                    if not line.startswith("data:"):continue
                    data=line[5:].strip()
                    if data=="[DONE]":done_marker=True;break
                    if not data:continue
                    event=json.loads(data)
                    if event.get("error"):raise RuntimeError("视觉推理服务返回错误")
                    choices=event.get("choices") or []
                    if choices:
                        if choices[0].get("finish_reason") is not None:finish_reason=choices[0]["finish_reason"]
                        chunk=(choices[0].get("delta") or {}).get("content") or ""
                        if chunk:chunks.append(chunk)
                if cancel_event.is_set():raise InterruptedError("视觉推理已取消")
                raw="".join(chunks)
                if not raw:raise ValueError("视觉模型没有返回结构化结果")
                if not done_marker:raise IncompleteVisualResponse("视觉响应缺少 SSE [DONE]")
                if finish_reason!="stop":raise IncompleteVisualResponse(f"视觉响应未正常结束：{finish_reason or 'missing'}")
            except Exception as exc:
                if cancel_event.is_set():raise InterruptedError("视觉推理已取消") from exc
                raise
            finally:
                try:response.close()
                except Exception:pass
                finished.set();watcher.join(.5)
                # A bounded drain is mandatory even when the HTTP stream closes.
                # If we cannot prove the slot is idle, callers isolate the worker
                # and retain their shared inference lease.
                wait_for_model_slot_idle(slot_drain_timeout)
    remaining()
    result=json.loads(raw)
    _validate_schema(result)
    remaining()
    ocr=merge_ocr_text(local_ocr,result["visible_text"])
    try:
        with urllib.request.urlopen(BASE+"/props",timeout=min(2,remaining())) as r:loaded=Path(json.load(r).get("model_path","" )).name
    except Exception:loaded="unknown local model"
    remaining()
    return {"page_type":result["page_type"],"ocr":ocr,"elements":result["elements"],"labels":result["labels"],"needs_human_review":result["needs_human_review"],"model":loaded,"raw":result}


def _validate_schema(value):
    """Validate the complete strict annotation schema without optional packages."""
    def fail(path, expected):raise ValueError(f"视觉JSON Schema不匹配：{path} 应为 {expected}")
    if not isinstance(value,dict):fail("$","object")
    required=set(SCHEMA["required"])
    if set(value)!=required:fail("$ keys", "exactly "+", ".join(sorted(required)))
    if not isinstance(value["page_type"],str):fail("$.page_type","string")
    if not isinstance(value["visible_text"],list) or len(value["visible_text"])>4 or any(not isinstance(x,str) for x in value["visible_text"]):fail("$.visible_text","array<string> maxItems=4")
    if not isinstance(value["elements"],list) or len(value["elements"])>2:fail("$.elements","array maxItems=2")
    for i,item in enumerate(value["elements"]):
        if not isinstance(item,dict) or set(item)!={"type","text","label"} or any(not isinstance(item[k],str) for k in item):fail(f"$.elements[{i}]","strict element object")
    if not isinstance(value["labels"],list) or len(value["labels"])>3 or any(not isinstance(x,str) for x in value["labels"]):fail("$.labels","array<string> maxItems=3")
    if not isinstance(value["needs_human_review"],bool):fail("$.needs_human_review","boolean")


def merge_ocr_text(local_ocr,visible_text):
    """Retain local OCR and model-detected text; partial OCR must not mask model text."""
    values=[];seen=set()
    for text in [local_ocr,*visible_text]:
        for line in str(text).splitlines():
            line=line.strip()
            if line and line not in seen:
                seen.add(line);values.append(line)
    return "\n".join(values)
