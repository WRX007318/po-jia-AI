"""Validated, versioned local behavior settings with atomic replacement."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


DEFAULTS = {
    "schema_version": 1,
    "revision": 0,
    "system_prompt": "你是破甲 AI，本地运行的中文助手。清楚区分已验证事实与推测；不要声称执行了未实际完成的操作。",
    "context_budget_chars": 12000,
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
        budget = merged["context_budget_chars"]
        if not isinstance(budget, int) or isinstance(budget, bool) or not 1000 <= budget <= 48000:
            raise ValueError("上下文预算必须在 1000–48000 字符之间")
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
        try:
            previous = self.validate(json.loads(candidates[0].read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("最近历史版本无效；当前设置未更改") from exc
        return self.save(previous)
