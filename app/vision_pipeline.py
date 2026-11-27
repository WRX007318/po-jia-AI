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


def tesseract_ocr(path:Path):
    exe=shutil.which("tesseract")
    if not exe:return ""
    try:
        result=subprocess.run([exe,str(path),"stdout","-l","chi_sim+eng"],capture_output=True,text=True,timeout=30,check=True)
        return result.stdout[:30000].strip()
    except Exception:return ""


def analyze(path:Path,timeout=360,lease_path:Path|None=None,lease_held=False,cancel_event=None):
    if path.stat().st_size>50*1024*1024:raise ValueError("图片超过识别大小限制")
    if cancel_event and cancel_event.is_set():raise InterruptedError("视觉推理已取消")
    ext=path.suffix.lower();mime={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".bmp":"image/bmp"}.get(ext)
    if not mime:raise ValueError("不支持的图片类型")
    started=time.monotonic()
    if timeout > 20: timeout=20
    image=base64.b64encode(path.read_bytes()).decode("ascii")
    local_ocr=tesseract_ocr(path)
    if cancel_event and cancel_event.is_set():raise InterruptedError("视觉推理已取消")
    prompt=("对这张由用户授权提供的业务页面截图做 OCR 与页面元素标注。只返回符合 JSON Schema 的结果。"
            "识别页面类别、最多4条重要可见文字（优先页面标题、列表/表格标题、订单号及状态）、最多1个主要页面元素、最多2个分类标签；每项用几个字简短表达。"
            "如果包含验证码、安全验证、人机校验、登录挑战或访问限制，needs_human_review=true；不要识别、转录或描述挑战内容。"
            "不要输出或推测账号、密钥等未显示内容。")
    if local_ocr:prompt+=f"\n本地 OCR 引擎提取文字如下，可用于核对但需以图片为准：\n{local_ocr[:12000]}"
    payload={"model":"local","messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:{mime};base64,{image}"}}]}],"temperature":0,"max_tokens":512,"thinking_budget_tokens":64,"stream":cancel_event is not None,"chat_template_kwargs":{"reasoning_effort":"none"},"response_format":{"type":"json_schema","json_schema":{"name":"visual_annotation","schema":SCHEMA,"strict":True}}}
    req=urllib.request.Request(API,json.dumps(payload,ensure_ascii=False).encode(),{"Content-Type":"application/json"})
    lease=(InferenceLease(lease_path) if lease_path and not lease_held else contextlib.nullcontext())
    with lease:
        if cancel_event is None:
            with urllib.request.urlopen(req,timeout=timeout) as r:raw=json.load(r)["choices"][0]["message"]["content"]
        else:
            response=urllib.request.urlopen(req,timeout=timeout);finished=threading.Event()
            def watch_cancel():
                while not finished.wait(.05):
                    if cancel_event.is_set():
                        try:response.close()
                        except Exception:pass
                        return
            watcher=threading.Thread(target=watch_cancel,daemon=True);watcher.start()
            try:
                chunks=[]
                for line in response:
                    line=line.decode("utf-8").strip()
                    if not line.startswith("data:"):continue
                    data=line[5:].strip()
                    if data=="[DONE]":break
                    if not data:continue
                    event=json.loads(data)
                    if event.get("error"):raise RuntimeError("视觉推理服务返回错误")
                    choices=event.get("choices") or []
                    if choices:
                        chunk=(choices[0].get("delta") or {}).get("content") or ""
                        if chunk:chunks.append(chunk)
                if cancel_event.is_set():raise InterruptedError("视觉推理已取消")
                raw="".join(chunks)
                if not raw:raise ValueError("视觉模型没有返回结构化结果")
            except Exception as exc:
                if cancel_event.is_set():raise InterruptedError("视觉推理已取消") from exc
                raise
            finally:
                try:response.close()
                except Exception:pass
                finished.set();watcher.join(.5)
                # llama.cpp releases a streamed generation on disconnect.
                # Retain the caller's inference lease until its slot clears,
                # even when cancellation raises out of the response loop.
                while True:
                    try:
                        with urllib.request.urlopen(BASE+"/slots",timeout=2) as slot_response:slots=json.load(slot_response)
                        if not any(item.get("is_processing") for item in slots):break
                    except Exception:
                        try:
                            with urllib.request.urlopen(BASE+"/health",timeout=2):pass
                        except Exception:break
                    time.sleep(.1)
    if time.monotonic()-started >= 20:raise TimeoutError("视觉处理超过 20 秒验收门槛")
    result=json.loads(raw)
    _validate_schema(result)
    ocr=merge_ocr_text(local_ocr,result["visible_text"])
    try:
        with urllib.request.urlopen(BASE+"/props",timeout=2) as r:loaded=Path(json.load(r).get("model_path","" )).name
    except Exception:loaded="unknown local model"
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
