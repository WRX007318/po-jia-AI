"""Independent, local tool allowlist persisted separately from behavior prompts."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

TOOL_IDS=("list_windows","inspect_window","read_control_text","read_text","write_text","launch_app","click_control","type_text")
DEFAULT_TOOL_IDS={"list_windows","inspect_window","read_control_text","read_text"}

class ToolPermissionsStore:
    def __init__(self,path:Path):self.path=Path(path)
    def load(self):
        if not self.path.exists():return set(DEFAULT_TOOL_IDS)
        try:value=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc:raise ValueError("工具权限文件损坏；拒绝加载 Agent 工具") from exc
        if not isinstance(value,dict) or value.get("schema_version")!=1 or not isinstance(value.get("enabled_tools"),list):
            raise ValueError("工具权限文件格式无效；拒绝加载 Agent 工具")
        tools=value["enabled_tools"]
        if any(not isinstance(x,str) or x not in TOOL_IDS for x in tools) or len(set(tools))!=len(tools):
            raise ValueError("工具权限包含未知或重复工具")
        return set(tools)
    def save(self,tools):
        selected=set(tools)
        if selected-set(TOOL_IDS):raise ValueError("不能授权未知工具")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix="tool-permissions-",suffix=".tmp",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as handle:
                json.dump({"schema_version":1,"enabled_tools":sorted(selected)},handle,ensure_ascii=False,indent=2)
                handle.write("\n");handle.flush();os.fsync(handle.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
        return selected
