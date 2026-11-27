"""Validated, versioned local behavior settings with atomic replacement."""
from __future__ import annotations

import json
import os
import tempfile
import time
import difflib
from pathlib import Path


DEFAULTS = {
    "schema_version": 1,
    "revision": 0,
    "system_prompt": "你是破甲 AI，本地运行的中文助手。清楚区分已验证事实与推测；不要声称执行了未实际完成的操作。",
    "behavior_rules": "",
    "runtime_profile": "iq2_m_cuda",
    "gpu_layers": 99,
    "context_budget_tokens": 3072,
    "auto_continue": False,
    "auto_continue_limit": 2,
}


class SettingsStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "settings.json"
        self.history = self.root / "history"

    @staticmethod
    def validate(value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("设置必须是 JSON 对象")
        # Migrate the PA-004 character budget once; all later enforcement uses
        # the active model server's real tokenizer rather than this estimate.
        value=dict(value)
        legacy_budget=value.pop("context_budget_chars",None)
        if "context_budget_tokens" not in value and legacy_budget is not None:
            if not isinstance(legacy_budget,int) or isinstance(legacy_budget,bool):
                raise ValueError("旧版上下文预算无效")
            value["context_budget_tokens"]=max(512,min(16000,(legacy_budget+3)//4))
        allowed = set(DEFAULTS)
        if set(value) - allowed:
            raise ValueError("设置包含未知字段")
        merged = dict(DEFAULTS)
        merged.update(value)
        if merged["schema_version"] != 1:
            raise ValueError("不支持的设置版本")
        if not isinstance(merged["revision"], int) or isinstance(merged["revision"], bool) or merged["revision"] < 0:
            raise ValueError("revision 必须是非负整数")
        prompt = merged["system_prompt"]
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("角色指令必须为 1–8000 个字符")
        rules=merged["behavior_rules"]
        if not isinstance(rules,str) or len(rules)>8000:
            raise ValueError("行为规则必须为不超过 8000 个字符的文本")
        if merged["runtime_profile"] not in {"iq2_m_cuda","iq2_m_vulkan","iq3_s_cuda","iq3_s_vulkan"}:
            raise ValueError("推理配置必须选择 IQ2_M CUDA、IQ3_S CUDA 或 IQ3_S Vulkan")
        layers=merged["gpu_layers"]
        if not isinstance(layers,int) or isinstance(layers,bool) or not 1<=layers<=99:
            raise ValueError("GPU 卸载层数必须是 1–99 的整数")
        budget = merged["context_budget_tokens"]
        if not isinstance(budget, int) or isinstance(budget, bool) or not 512 <= budget <= 16000:
            raise ValueError("上下文预算必须在 512–16000 tokens 之间")
        if not isinstance(merged["auto_continue"], bool):
            raise ValueError("auto_continue 必须为布尔值")
        limit = merged["auto_continue_limit"]
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 4:
            raise ValueError("自动续写次数必须在 1–4 之间")
        return merged

    def load(self) -> dict:
        if not self.path.exists():
            return dict(DEFAULTS)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("本地设置文件损坏；未覆盖原文件") from exc
        return self.validate(value)

    def save(self, value: dict) -> dict:
        try:
            current = self.load()
        except ValueError:
            current = dict(DEFAULTS)
            if self.path.exists():
                self.history.mkdir(parents=True, exist_ok=True)
                damaged = self.history / f"invalid-{int(time.time())}.json"
                if not damaged.exists():damaged.write_bytes(self.path.read_bytes())
        normalized = self.validate(value)
        normalized["revision"] = current["revision"] + 1
        self.root.mkdir(parents=True, exist_ok=True)
        self.history.mkdir(parents=True, exist_ok=True)
        snapshot = self.history / f"{current['revision']:06d}.json"
        if not snapshot.exists():
            snapshot.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(normalized, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return normalized

    def rollback(self) -> dict:
        candidates = sorted(self.history.glob("[0-9]*.json"), reverse=True) if self.history.exists() else []
        if not candidates:
            raise ValueError("没有可恢复的历史版本")
        current=self.load()
        return self.rollback_to(int(candidates[0].stem),current=current)

    def versions(self):
        """Return validated snapshots and the current version, newest first."""
        values=[]
        if self.history.exists():
            for path in sorted(self.history.glob("[0-9]*.json"),reverse=True):
                try:values.append(self.validate(json.loads(path.read_text(encoding="utf-8"))))
                except (OSError,json.JSONDecodeError,ValueError):continue
        try:current=self.load()
        except ValueError:current=None
        if current is not None:values.insert(0,current)
        return values

    def diff(self, revision: int) -> str:
        target=self._read_revision(revision)
        current=self.load()
        before=json.dumps(target,ensure_ascii=False,indent=2,sort_keys=True).splitlines()
        after=json.dumps(current,ensure_ascii=False,indent=2,sort_keys=True).splitlines()
        return "\n".join(difflib.unified_diff(before,after,fromfile=f"revision {revision}",tofile=f"revision {current['revision']}",lineterm=""))

    def _read_revision(self,revision: int):
        if not isinstance(revision,int) or isinstance(revision,bool) or revision<0:
            raise ValueError("版本号无效")
        candidates=[self.history/f"{revision:06d}.json"]
        if self.path.exists():candidates.append(self.path)
        for path in candidates:
            if path.exists():
                try:
                    value=self.validate(json.loads(path.read_text(encoding="utf-8")))
                    if value["revision"]==revision:return value
                except (OSError,json.JSONDecodeError,ValueError):continue
        raise ValueError(f"找不到有效配置版本 {revision}")

    def rollback_to(self,revision: int,current=None) -> dict:
        try:
            previous=self._read_revision(revision)
        except ValueError as exc:raise ValueError("指定历史版本无效；当前设置未更改") from exc
        if current is None:current=self.load()
        return self.save(previous)
