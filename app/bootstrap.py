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

ROOT = Path(os.environ.get("POJIA_HOME", Path.home() / "PoJiaAI"))
MODEL_DIR = ROOT / "models" / "inkling2mini"
REPO_ID = "AtomicChat/Inkling-2-Mini-Uncensored-GGUF"
REVISION = "82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2"
FILES = {
    "Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf": (13340510176, "d1cbd09d44094420c7fda8c4fa7689d2d56a0070d5a2ada50d0e992b96ed5a81"),
    "mmproj-Inkling-2-Mini-Uncensored-F16.gguf": (639348448, "88cd139393afcf0342de8983c41f5b388adcdbf764c04b5ec13661e63451feeb"),
}
LLAMA_RELEASE = "v1.1.0"


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def check_model_dir():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (size, oid) in FILES.items():
        path = MODEL_DIR / name
        if not path.exists() or path.stat().st_size != size:
            continue
        # SHA-256 values come from the pinned Hugging Face Resolve ETag headers.
        digest = sha256(path)
        if digest != oid:
            raise RuntimeError(f"SHA-256 不匹配：{name}，应为 {oid}，实为 {digest}")
    return all((MODEL_DIR / n).exists() and (MODEL_DIR / n).stat().st_size == s and sha256(MODEL_DIR / n) == oid for n,(s,oid) in FILES.items())


def download(progress=None, cancel=None):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (expected_size, expected_hash) in FILES.items():
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
    # Official release assets are queried from GitHub API, then the NVIDIA CUDA 12.4 build is selected.
    api=f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{LLAMA_RELEASE}"
    req=urllib.request.Request(api,headers={"Accept":"application/vnd.github+json","User-Agent":"PoJiaAI/0.1"})
    release=json.load(urllib.request.urlopen(req,timeout=30))
    assets=release.get("assets",[])
    candidates=[a for a in assets if "win-cuda-12.4" in a["name"].lower() and a["name"].lower().endswith(".zip")]
    if not candidates:
        candidates=[a for a in assets if "win-cuda" in a["name"].lower() and a["name"].lower().endswith(".zip")]
    if not candidates:raise RuntimeError("官方 llama.cpp Release 未提供 Windows CUDA 压缩包")
    asset=candidates[0];archive=ROOT/asset["name"]
    req=urllib.request.Request(asset["browser_download_url"],headers={"User-Agent":"PoJiaAI/0.1"})
    with urllib.request.urlopen(req,timeout=60) as response,archive.open("wb") as out:
        total=int(response.headers.get("Content-Length","0"));done=0
        while block:=response.read(1024*1024):
            out.write(block);done+=len(block)
            if progress:progress(asset["name"],done,total)
    shutil.unpack_archive(archive,runtime_dir)
    matches=list(runtime_dir.rglob("llama-server.exe"))
    if not matches:raise RuntimeError("Release 压缩包中找不到 llama-server.exe")
    if matches[0]!=exe:shutil.copy2(matches[0],exe)
    return exe


if __name__ == "__main__":
    print("模型完整且校验通过" if check_model_dir() else "模型文件缺失或未校验")
