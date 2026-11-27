"""Constrained Windows UIA and workspace tools with separate approval tickets.

This module deliberately exposes no shell, network, arbitrary process kill, or
unscoped filesystem operation. A UI must show each plan before calling approve.
"""
from __future__ import annotations

import ctypes
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class ToolRejected(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    id: str
    action: str
    args: dict
    description: str
    mutating: bool


class ComputerAgent:
    ACTION_ARGS = {
        "list_windows": set(),
        "inspect_window": {"window_id"},
        "read_control_text": {"window_id","selector"},
        "read_text": {"path"},
        "write_text": {"path", "content"},
        "launch_app": {"app_id"},
        "click_control": {"window_id", "selector"},
        "type_text": {"window_id", "selector", "content"},
    }
    OPTIONAL_ARGS={"launch_app":{"document"},"click_control":{"control_type"},"type_text":{"control_type"},"read_control_text":{"control_type"}}
    MUTATING = {"write_text", "launch_app", "click_control", "type_text"}

    def __init__(self, workspace: Path, max_steps: int = 20):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("工作目录必须是现有文件夹")
        self.max_steps = max(1, min(50, int(max_steps)))
        self.steps = 0
        self.apps: dict[str, Path] = {}
        self.plans: dict[str, Plan] = {}
        self.approved: dict[str,float] = {}
        self.plan_expiry: dict[str,float] = {}

    def begin_task(self):
        self.steps=0;self.plans.clear();self.approved.clear();self.plan_expiry.clear()

    def add_allowed_app(self, executable: Path) -> str:
        exe = Path(executable).resolve(strict=True)
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            raise ToolRejected("只允许用户明确选择的现有 EXE 程序")
        app_id = secrets.token_urlsafe(8)
        self.apps[app_id] = exe
        return app_id

    def plan(self, action: str, args: dict) -> Plan:
        if action not in self.ACTION_ARGS or not isinstance(args, dict):
            raise ToolRejected("不支持的工具或参数格式")
        expected = self.ACTION_ARGS[action]
        optional=self.OPTIONAL_ARGS.get(action,set())
        if not expected.issubset(args) or set(args)-expected-optional:
            raise ToolRejected("工具参数与 schema 不匹配")
        checked = dict(args)
        for key in optional:checked.setdefault(key,None)
        self._expire_plans()
        if len(self.plans)>=50:raise ToolRejected("待执行计划过多；请先执行或开始新任务")
        desc = self._describe(action, checked)
        item = Plan(secrets.token_urlsafe(18), action, checked, desc, action in self.MUTATING)
        self.plans[item.id] = item
        self.plan_expiry[item.id]=time.monotonic()+300
        return item

    def _expire_plans(self):
        now=time.monotonic()
        for key,deadline in list(self.plan_expiry.items()):
            if deadline<=now:
                self.plan_expiry.pop(key,None);self.plans.pop(key,None)
        for key,deadline in list(self.approved.items()):
            if deadline<=now:
                self.approved.pop(key,None);self.plans.pop(key,None)

    def approve(self, plan_id: str, user_confirmed: bool) -> str:
        plan = self.plans.get(plan_id)
        self._expire_plans()
        plan = self.plans.get(plan_id)
        if not plan or not plan.mutating:
            raise ToolRejected("计划不存在或不需要变更审批")
        if user_confirmed is not True:
            raise ToolRejected("变更操作必须由用户在计划预览后明确批准")
        ticket = secrets.token_urlsafe(24)
        self.approved[ticket]=time.monotonic()+60
        self.plans[ticket] = Plan(ticket, plan.action, plan.args, plan.description, True)
        self.plan_expiry[ticket]=time.monotonic()+60
        del self.plans[plan_id]
        self.plan_expiry.pop(plan_id,None)
        return ticket

    def execute(self, plan_id: str, approval_ticket: str | None = None):
        self._expire_plans()
        if self.steps >= self.max_steps:
            raise ToolRejected("已达到本任务最大操作步数")
        plan = self.plans.get(plan_id)
        if plan is None:
            # Approved plans use the ticket as their one-time plan ID.
            plan = next((p for p in self.plans.values() if p.id == plan_id), None)
        if plan is None:
            raise ToolRejected("计划不存在、已执行或已失效")
        if plan.mutating and (approval_ticket != plan.id or approval_ticket not in self.approved):
            raise ToolRejected("变更操作缺少有效的一次性用户审批")
        self.steps += 1
        try:
            result = self._run(plan.action, plan.args)
        finally:
            self.plans.pop(plan_id, None)
            self.plan_expiry.pop(plan_id,None)
            if approval_ticket:self.approved.pop(approval_ticket,None)
        return result

    def _describe(self, action: str, args: dict) -> str:
        if action in {"read_text", "write_text"}:
            target = self._workspace_path(args["path"], allow_missing=action == "write_text")
            if action == "write_text":
                if not isinstance(args["content"], str) or len(args["content"]) > 1_000_000:
                    raise ToolRejected("文本写入必须是字符串且不超过 1 MiB")
                if target.exists() and target.stat().st_size>1_000_000:
                    raise ToolRejected("拒绝覆盖超过 1 MiB 的既有文件")
                verb="覆盖" if target.exists() else "新建"
                return f"在授权目录{verb}文本文件：{target.relative_to(self.workspace)}；已有内容将先备份"
            return f"读取授权目录文本文件：{target.relative_to(self.workspace)}"
        if action == "launch_app":
            exe = self.apps.get(args["app_id"])
            if exe is None or not exe.exists():
                raise ToolRejected("程序未由用户加入本次任务白名单")
            if args["document"] is not None:
                self._workspace_path(args["document"])
            return f"启动白名单程序：{exe.name}"
        if action in {"inspect_window", "read_control_text", "click_control", "type_text"}:
            self._window(args["window_id"])
            if action == "type_text" and (not isinstance(args["content"], str) or len(args["content"]) > 10000):
                raise ToolRejected("输入文本必须是字符串且不超过 10000 字符")
            if action != "inspect_window" and (not isinstance(args["selector"], str) or not args["selector"].strip()):
                raise ToolRejected("控件 selector 不能为空")
            return f"对本任务白名单窗口执行 {action}：{args.get('selector','读取控件树')}"
        return "读取本任务白名单窗口列表"

    def _workspace_path(self, raw: str, allow_missing=False) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise ToolRejected("文件路径不能为空")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        # Reject symlinks/junctions before resolving to prevent escape through an alias.
        try:relative = os.path.relpath(str(candidate), str(self.workspace))
        except ValueError as exc:raise ToolRejected("路径不在授权工作目录所在磁盘") from exc
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            raise ToolRejected("路径越出已授权工作目录")
        probe = self.workspace
        for part in Path(relative).parts:
            if part in {".", ""}: continue
            probe = probe / part
            is_junction=getattr(probe,"is_junction",lambda:False)
            if probe.is_symlink() or is_junction():
                raise ToolRejected("工作目录内的符号链接不允许访问")
        if allow_missing:
            target = candidate.resolve(strict=False)
        else:
            target = candidate.resolve(strict=True)
        try:target.relative_to(self.workspace)
        except ValueError as exc:raise ToolRejected("路径越出已授权工作目录") from exc
        if not allow_missing and (not target.is_file() or target.stat().st_size > 1_000_000):
            raise ToolRejected("只支持不超过 1 MiB 的普通文本文件")
        return target

    @staticmethod
    def _process_image(pid: int) -> Path:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
        kernel32.OpenProcess.restype=ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
        kernel32.QueryFullProcessImageNameW.restype=ctypes.c_bool
        kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel32.CloseHandle.restype=ctypes.c_bool
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:raise ToolRejected("无法核验窗口所属程序")
        try:
            buffer = ctypes.create_unicode_buffer(32768);size=ctypes.c_ulong(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise ToolRejected("无法核验窗口所属程序路径")
            return Path(buffer.value).resolve()
        finally:kernel32.CloseHandle(handle)

    def _window(self, window_id: int):
        if not isinstance(window_id, int) or isinstance(window_id, bool) or window_id <= 0:
            raise ToolRejected("window_id 必须为窗口句柄")
        try:
            from pywinauto import Desktop
            window = Desktop(backend="uia").window(handle=window_id)
            if not window.exists(timeout=1):raise ToolRejected("目标窗口已关闭")
            pid = window.element_info.process_id
            image = self._process_image(pid)
        except ToolRejected:raise
        except Exception as exc:raise ToolRejected(f"UI Automation 无法连接目标窗口：{type(exc).__name__}") from exc
        if image not in self.apps.values():
            raise ToolRejected("窗口所属程序不在本次任务白名单")
        return window

    @staticmethod
    def _control(window, selector: str, control_type: str | None = None):
        try:controls=window.descendants()
        except Exception as exc:raise ToolRejected("无法读取目标窗口控件树") from exc
        matches=[]
        for control in controls[:1000]:
            info=control.element_info
            if selector in {info.name, info.automation_id} and (not control_type or info.control_type == control_type):
                matches.append(control)
        if len(matches)!=1:raise ToolRejected(f"控件需唯一匹配；当前匹配数 {len(matches)}")
        return matches[0]

    def _run(self, action: str, args: dict):
        if action == "list_windows":
            from pywinauto import Desktop
            result=[]
            for window in Desktop(backend="uia").windows():
                try:
                    pid=window.element_info.process_id;image=self._process_image(pid)
                    if image in self.apps.values():
                        result.append({"window_id":int(window.handle),"title":window.window_text()[:200],"process":image.name})
                except Exception:continue
            return result
        if action == "read_text":
            path=self._workspace_path(args["path"])
            try:return path.read_text(encoding="utf-8")
            except (UnicodeError,OSError) as exc:raise ToolRejected("文件不是可读取的 UTF-8 文本") from exc
        if action == "write_text":
            path=self._workspace_path(args["path"],allow_missing=True)
            if path.exists() and not path.is_file():raise ToolRejected("目标不是普通文件")
            path.parent.mkdir(parents=True,exist_ok=True)
            backup=None
            if path.exists():
                backup=path.with_name(path.name+f".pojia-backup-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}")
                shutil.copy2(path,backup)
            temp=path.with_name(path.name+"."+secrets.token_hex(6)+".tmp")
            try:
                with temp.open("w",encoding="utf-8",newline="\n") as f:f.write(args["content"]);f.flush();os.fsync(f.fileno())
                os.replace(temp,path)
            finally:
                if temp.exists():temp.unlink()
            return {"path":str(path.relative_to(self.workspace)),"characters":len(args["content"]),
                    "backup":str(backup.relative_to(self.workspace)) if backup else None}
        if action == "launch_app":
            exe=self.apps[args["app_id"]]
            command=[str(exe)]
            if args["document"] is not None:command.append(str(self._workspace_path(args["document"])))
            process=subprocess.Popen(command,cwd=self.workspace,close_fds=True)
            return {"pid":process.pid,"app":exe.name}
        if action in {"inspect_window","read_control_text","click_control","type_text"}:
            window=self._window(args["window_id"])
            if action=="inspect_window":
                rows=[]
                for control in window.descendants()[:300]:
                    info=control.element_info
                    rows.append({"name":(info.name or "")[:160],"automation_id":(info.automation_id or "")[:120],"control_type":info.control_type})
                return rows
            selector=args["selector"]
            control_type=args.get("control_type")
            target=self._control(window,selector,control_type)
            if action=="read_control_text":
                try:value=target.get_value()
                except Exception:
                    try:value=target.window_text()
                    except Exception as exc:raise ToolRejected("控件不支持读取文本") from exc
                return str(value)[:10000]
            if action=="click_control":target.click_input();return {"clicked":selector}
            if target.element_info.control_type!="Edit":raise ToolRejected("为避免按键序列注入，只允许向 Edit 控件写入纯文本")
            target.set_edit_text(args["content"])
            return {"set_characters":len(args["content"])}
        raise ToolRejected("未实现的操作")
