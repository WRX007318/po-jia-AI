"""Offline-first visual OCR/classification pipeline for authorized image files."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

API="http://127.0.0.1:59871/v1/chat/completions"
SCHEMA={"type":"object","properties":{"page_type":{"type":"string"},"visible_text":{"type":"array","maxItems":4,"items":{"type":"string"}},"elements":{"type":"array","maxItems":2,"items":{"type":"object","properties":{"type":{"type":"string"},"text":{"type":"string"},"label":{"type":"string"}},"required":["type","text","label"],"additionalProperties":False}},"labels":{"type":"array","maxItems":3,"items":{"type":"string"}},"needs_human_review":{"type":"boolean"}},"required":["page_type","visible_text","elements","labels","needs_human_review"],"additionalProperties":False}


def tesseract_ocr(path:Path):
    exe=shutil.which("tesseract")
    if not exe:return ""
    try:
        result=subprocess.run([exe,str(path),"stdout","-l","chi_sim+eng"],capture_output=True,text=True,timeout=30,check=True)
        return result.stdout[:30000].strip()
    except Exception:return ""


def analyze(path:Path,timeout=360):
    if path.stat().st_size>50*1024*1024:raise ValueError("图片超过识别大小限制")
    ext=path.suffix.lower();mime={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".bmp":"image/bmp"}.get(ext)
    if not mime:raise ValueError("不支持的图片类型")
    image=base64.b64encode(path.read_bytes()).decode("ascii")
    local_ocr=tesseract_ocr(path)
    prompt=("对这张由用户授权提供的业务页面截图做 OCR 与页面元素标注。只返回符合 JSON Schema 的结果。"
            "识别页面类别、最多3条最重要的可见文字、最多1个主要页面元素、最多2个分类标签；每项用几个字简短表达。"
            "如果包含验证码、安全验证、人机校验、登录挑战或访问限制，needs_human_review=true；不要识别、转录或描述挑战内容。"
            "不要输出或推测账号、密钥等未显示内容。")
    if local_ocr:prompt+=f"\n本地 OCR 引擎提取文字如下，可用于核对但需以图片为准：\n{local_ocr[:12000]}"
    payload={"model":"local","messages":[{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":f"data:{mime};base64,{image}"}}]}],"temperature":0,"max_tokens":512,"thinking_budget_tokens":64,"stream":False,"chat_template_kwargs":{"reasoning_effort":"none"},"response_format":{"type":"json_schema","json_schema":{"name":"visual_annotation","schema":SCHEMA,"strict":True}}}
    req=urllib.request.Request(API,json.dumps(payload,ensure_ascii=False).encode(),{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:raw=json.load(r)["choices"][0]["message"]["content"]
    result=json.loads(raw)
    if not isinstance(result.get("visible_text"),list) or not isinstance(result.get("elements"),list):raise ValueError("视觉模型返回结构不符合要求")
    ocr=local_ocr or "\n".join(result["visible_text"])
    return {"page_type":result["page_type"],"ocr":ocr,"elements":result["elements"],"labels":result["labels"],"needs_human_review":result["needs_human_review"],"model":"Inkling-2-Mini-AD-IQ3_S","raw":result}
