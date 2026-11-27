"""Per-user model and runtime installer with pinned revisions and SHA-256 checks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("POJIA_HOME", r"D:\PoJiaAI"))
MODEL_DIR = ROOT / "models" / "inkling2mini"
REPO_ID = "AtomicChat/Inkling-2-Mini-Uncensored-GGUF"
REVISION = "82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2"
FILES = {
    # The `lfs.oid` values from the pinned HF tree API are the content SHA-256.
    # `xetHash` and the Resolve ETag are Xet content identifiers, not SHA-256.
    "Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf": (8665091680, "fca99d488bff5d401c8bc6b0110c5377c743f0ffb3a6d19c1ae4a3b9071fa2cd"),
    "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf": (13340510176, "23a8e6792481b6f1d0ebad51399e9ee2a2c2be8525b09ed1ae6737811159f892"),
    "mmproj-Inkling-2-Mini-Uncensored-F16.gguf": (639348448, "5a72e0b6e2bef13c3f455f4edb85df0c752b92ff76ab46af879eae088163efe6"),
}
DEFAULT_MODEL = "Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf"
VISION_PROJECTOR = "mmproj-Inkling-2-Mini-Uncensored-F16.gguf"
XET_HASHES = {
    "Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf": "1d983a50f3c3ba36588b49399c5654325b93f773aaf4b185d8b0aa0c990caf79",
    "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf": "d1cbd09d44094420c7fda8c4fa7689d2d56a0070d5a2ada50d0e992b96ed5a81",
    "mmproj-Inkling-2-Mini-Uncensored-F16.gguf": "88cd139393afcf0342de8983c41f5b388adcdbf764c04b5ec13661e63451feeb",
}
LLAMA_BUILD = "b12774"
LLAMA_ARCHIVE = "llama-b12774-bin-win-vulkan-x64.zip"
LLAMA_ARCHIVE_SHA256 = "d29a16265d26ef7598209caaf1a544cbfa6abe2858c24b0ce4ae6bff87a76f22"


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def required_files(model_name=DEFAULT_MODEL):
    if model_name not in FILES or model_name == VISION_PROJECTOR:
        raise ValueError(f"不支持的模型配置：{model_name}")
    return {model_name: FILES[model_name], VISION_PROJECTOR: FILES[VISION_PROJECTOR]}


def check_model_dir(model_name=DEFAULT_MODEL):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    valid = True
    for name, (size, oid) in required_files(model_name).items():
        path = MODEL_DIR / name
        if not path.exists():
            valid = False
            continue
        if path.stat().st_size != size:
            raise RuntimeError(f"文件大小不匹配：{name}，应为 {size}，实为 {path.stat().st_size}")
        digest = sha256(path)
        if digest != oid:
            raise RuntimeError(f"SHA-256 不匹配：{name}，应为 {oid}，实为 {digest}")
    return valid


def download(progress=None, cancel=None, model_name=DEFAULT_MODEL):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (expected_size, expected_hash) in required_files(model_name).items():
        target = MODEL_DIR / name
        if target.exists() and target.stat().st_size == expected_size and sha256(target) == expected_hash:
            continue
        part = target.with_suffix(target.suffix + ".part")
        url = f"https://huggingface.co/{REPO_ID}/resolve/{REVISION}/{name}"
        offset = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent":"PoJiaAI/0.1", **({"Range":f"bytes={offset}-"} if offset else {})})
        with urllib.request.urlopen(req, timeout=60) as response:
            if offset and response.status != 206:
                offset=0; part.unlink(missing_ok=True)
            total = int(response.headers.get("Content-Length", "0")) + offset
            mode = "ab" if offset else "wb"
            done=offset
            with part.open(mode) as out:
                while True:
                    if cancel and cancel.is_set():
                        return False
                    block=response.read(4*1024*1024)
                    if not block:break
                    out.write(block);done+=len(block)
                    if progress:progress(name,done,total)
        if part.stat().st_size != expected_size:
            raise RuntimeError(f"文件大小不匹配：{name}，收到 {part.stat().st_size}，应为 {expected_size}")
        digest=sha256(part)
        if digest != expected_hash:
            raise RuntimeError(f"SHA-256 不匹配：{name}，应为 {expected_hash}，实为 {digest}")
        part.replace(target)
    return True


def install_llama(progress=None):
    runtime_dir=ROOT/"runtime";runtime_dir.mkdir(parents=True,exist_ok=True)
    exe=runtime_dir/"llama-server.exe"
    if exe.exists():return exe
    archive=ROOT/LLAMA_ARCHIVE
    url=f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/{LLAMA_ARCHIVE}"
    req=urllib.request.Request(url,headers={"User-Agent":"PoJiaAI/0.1"})
    with urllib.request.urlopen(req,timeout=60) as response,archive.open("wb") as out:
        total=int(response.headers.get("Content-Length","0"));done=0
        while block:=response.read(1024*1024):
            out.write(block);done+=len(block)
            if progress:progress(LLAMA_ARCHIVE,done,total)
    if sha256(archive)!=LLAMA_ARCHIVE_SHA256:raise RuntimeError("llama.cpp 官方 Release ZIP SHA-256 校验失败")
    shutil.unpack_archive(archive,runtime_dir)
    matches=list(runtime_dir.rglob("llama-server.exe"))
    if not matches:raise RuntimeError("Release 压缩包中找不到 llama-server.exe")
    if matches[0]!=exe:shutil.copy2(matches[0],exe)
    return exe


if __name__ == "__main__":
    print("模型完整且校验通过" if check_model_dir() else "模型文件缺失或未校验")
