"""Constrained Windows UIA and workspace tools with separate approval tickets.

This module deliberately exposes no shell, network, arbitrary process kill, or
unscoped filesystem operation. A UI must show each plan before calling approve.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
import threading
from dataclasses import dataclass
from pathlib import Path


class ToolRejected(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    id: str
    action: str
    args_json: str
    description: str
    mutating: bool
    scope_fingerprint: str
    window_identity: tuple | None = None

    @property
    def args(self):
        return json.loads(self.args_json)

    @property
    def binding(self):
        return hashlib.sha256((self.action+"\0"+self.args_json+"\0"+self.scope_fingerprint).encode("utf-8")).hexdigest()


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

    def __init__(self, workspace: Path, max_steps: int = 20, checkpoint_path: Path | None = None, allowed_actions=None):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("工作目录必须是现有文件夹")
        self.max_steps = max(1, min(50, int(max_steps)))
        self.steps = 0
        self.task_id = None
        self.state = "idle"
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self.cancel_requested = False
        self.apps: dict[str, Path] = {}
        self.plans: dict[str, Plan] = {}
        self.approved: dict[str,tuple] = {}
        self.plan_expiry: dict[str,float] = {}
        self.allowed_actions=set(self.ACTION_ARGS if allowed_actions is None else allowed_actions)
        if self.allowed_actions-set(self.ACTION_ARGS):raise ValueError("工具权限包含未知操作")
        self.audit_path=(Path(checkpoint_path).parent/"computer-agent-audit.jsonl") if checkpoint_path else None
        self._gate_lock=threading.RLock()
        self._audit("agent_initialized",{"workspace":str(self.workspace)})

    def _audit(self,event: str,details: dict):
        """Append a hash-chained, content-minimized local audit record."""
        if self.audit_path is None:return
        self.audit_path.parent.mkdir(parents=True,exist_ok=True)
        previous="0"*64
        if self.audit_path.exists():
            try:
                lines=self.audit_path.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    item=json.loads(line);saved=item.pop("hash")
                    if item.get("previous_hash")!=previous:
                        raise ToolRejected("审计日志哈希链不连续；拒绝执行 Agent 操作")
                    canonical=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(",",":"))
                    if hashlib.sha256(canonical.encode("utf-8")).hexdigest()!=saved:
                        raise ToolRejected("审计日志校验失败；拒绝执行 Agent 操作")
                    previous=saved
            except (OSError,json.JSONDecodeError,IndexError,KeyError):
                raise ToolRejected("审计日志不可读取；拒绝执行 Agent 操作")
        record={"time":time.time(),"task_id":self.task_id,"event":event,"details":details,"previous_hash":previous}
        canonical=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        record["hash"]=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.audit_path.open("a",encoding="utf-8",newline="\n") as handle:
            handle.write(json.dumps(record,ensure_ascii=False,sort_keys=True)+"\n")
            handle.flush();os.fsync(handle.fileno())

    def _prevalidate_audit(self):
        """Fail closed before any operation if the protected audit chain is invalid."""
        if self.audit_path is None or not self.audit_path.exists():return
        previous="0"*64
        try:
            for line in self.audit_path.read_text(encoding="utf-8").splitlines():
                item=json.loads(line);saved=item.pop("hash")
                if item.get("previous_hash")!=previous:raise ToolRejected("审计日志哈希链不连续；拒绝执行 Agent 操作")
                canonical=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(",",":"))
                if hashlib.sha256(canonical.encode("utf-8")).hexdigest()!=saved:raise ToolRejected("审计日志校验失败；拒绝执行 Agent 操作")
                previous=saved
        except ToolRejected:raise
        except Exception as exc:raise ToolRejected("审计日志不可读取；拒绝执行 Agent 操作") from exc

    def begin_task(self):
        self.steps=0;self.plans.clear();self.approved.clear();self.plan_expiry.clear()
        self.task_id=secrets.token_urlsafe(12);self.state="running";self.cancel_requested=False
        self._audit("task_started",{"max_steps":self.max_steps})
        self._save_checkpoint()

    def pause(self):
        if self.state!="running":return False
        self.state="paused";self.plans.clear();self.approved.clear();self.plan_expiry.clear();self._audit("task_paused",{});self._save_checkpoint();return True

    def resume(self):
        if self.state not in {"paused","failed"}:return False
        self.state="running";self.cancel_requested=False;self._audit("task_resumed",{});self._save_checkpoint();return True

    def stop(self):
        if self.state in {"idle","stopped","completed"}:return False
        self.cancel_requested=True;self.state="stopped";self.plans.clear();self.approved.clear();self.plan_expiry.clear()
        self._audit("emergency_stop",{});self._save_checkpoint();return True

    def complete_task(self):
        if self.state!="running":return False
        self.state="completed";self.plans.clear();self.approved.clear();self.plan_expiry.clear()
        self._save_checkpoint();return True

    def restore_checkpoint(self):
        if not self.checkpoint_path or not self.checkpoint_path.is_file():return False
        data=json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if data.get("workspace")!=str(self.workspace) or data.get("state") not in {"paused","failed","running"}:
            raise ToolRejected("任务检查点与当前授权工作目录不符，或状态不可恢复")
        self.task_id=data["task_id"];self.steps=int(data["steps"]);self.state="paused"
        self.cancel_requested=False;self.plans.clear();self.approved.clear();self.plan_expiry.clear()
        return True

    def _save_checkpoint(self):
        if not self.checkpoint_path:return
        self.checkpoint_path.parent.mkdir(parents=True,exist_ok=True)
        value={"schema_version":1,"task_id":self.task_id,"workspace":str(self.workspace),
               "state":self.state,"steps":self.steps,"max_steps":self.max_steps,"updated":time.time()}
        temp=self.checkpoint_path.with_name(self.checkpoint_path.name+"."+secrets.token_hex(4)+".tmp")
        try:
            with temp.open("w",encoding="utf-8",newline="\n") as f:
                json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            os.replace(temp,self.checkpoint_path)
        finally:temp.unlink(missing_ok=True)

    def add_allowed_app(self, executable: Path) -> str:
        exe = Path(executable).resolve(strict=True)
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            raise ToolRejected("只允许用户明确选择的现有 EXE 程序")
        app_id = secrets.token_urlsafe(8)
        self.apps[app_id] = exe
        return app_id

    def set_allowed_actions(self,actions):
        selected=set(actions)
        if selected-set(self.ACTION_ARGS):raise ToolRejected("不能启用未知工具")
        with self._gate_lock:
            self.allowed_actions=selected;self.plans.clear();self.approved.clear();self.plan_expiry.clear()
        self._audit("tool_permissions_changed",{"enabled_tools":sorted(selected)})

    def revoke_app(self, app_id: str):
        with self._gate_lock:
            if app_id not in self.apps:return False
            del self.apps[app_id];self.plans.clear();self.approved.clear();self.plan_expiry.clear()
            if self.state=="running":self.state="paused"
        self._audit("app_revoked",{"app_id_hash":hashlib.sha256(app_id.encode()).hexdigest()});self._save_checkpoint()
        return True

    def revoke_all(self):
        with self._gate_lock:
            self.apps.clear();self.plans.clear();self.approved.clear();self.plan_expiry.clear()
            self.cancel_requested=True
            if self.state=="running":self.state="paused"
        self._audit("all_apps_revoked",{});self._save_checkpoint()

    def plan(self, action: str, args: dict) -> Plan:
        if self.state!="running" or self.cancel_requested:
            raise ToolRejected(f"任务当前状态为 {self.state}，不能创建新计划")
        if action not in self.ACTION_ARGS or not isinstance(args, dict):
            raise ToolRejected("不支持的工具或参数格式")
        if action not in self.allowed_actions:raise ToolRejected("该工具已在独立工具权限中停用")
        expected = self.ACTION_ARGS[action]
        optional=self.OPTIONAL_ARGS.get(action,set())
        if not expected.issubset(args) or set(args)-expected-optional:
            raise ToolRejected("工具参数与 schema 不匹配")
        checked = dict(args)
        for key in optional:checked.setdefault(key,None)
        self._expire_plans()
        if len(self.plans)>=50:raise ToolRejected("待执行计划过多；请先执行或开始新任务")
        desc = self._describe(action, checked)
        window_identity=None
        if action in {"inspect_window","read_control_text","click_control","type_text"}:
            window_identity=self._window_identity(checked["window_id"])
        scope=self._scope_for(action,checked,window_identity)
        encoded=json.dumps(checked,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
        item = Plan(secrets.token_urlsafe(18), action, encoded, desc, action in self.MUTATING,scope,window_identity)
        self._audit("plan_created",{"plan_id":item.id,"action":action,"arguments_hash":hashlib.sha256(encoded.encode()).hexdigest(),"scope_hash":scope,"approval_required":item.mutating})
        self.plans[item.id] = item
        self.plan_expiry[item.id]=time.monotonic()+60
        return item

    def _scope_for(self,action,args,window_identity=None):
        bound={"workspace":str(self.workspace),"window":window_identity}
        if action=="launch_app":
            path=self.apps.get(args["app_id"])
            if path is None:raise ToolRejected("应用授权已撤销")
            st=path.stat()
            if st.st_size>200*1024*1024:raise ToolRejected("拒绝加入超过 200 MiB 的应用白名单")
            h=hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
            bound["app"]=(str(path),st.st_size,st.st_mtime_ns,h.hexdigest())
        if action in {"read_text","write_text"}:
            path=self._workspace_path(args["path"],allow_missing=action=="write_text")
            if path.exists():
                st=path.stat();h=hashlib.sha256(path.read_bytes()).hexdigest()
                bound["file"]=(str(path),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,h)
            else:bound["file"]=(str(path),None)
        return hashlib.sha256(json.dumps(bound,sort_keys=True,ensure_ascii=False,default=list).encode("utf-8")).hexdigest()

    def _expire_plans(self):
        now=time.monotonic()
        for key,deadline in list(self.plan_expiry.items()):
            if deadline<=now:
                self.plan_expiry.pop(key,None);self.plans.pop(key,None)
        for key,(_,_,deadline) in list(self.approved.items()):
            if deadline<=now:
                self.approved.pop(key,None);self.plans.pop(key,None);self.plan_expiry.pop(key,None)

    def approve(self, plan_id: str, user_confirmed: bool) -> str:
        plan = self.plans.get(plan_id)
        self._expire_plans()
        plan = self.plans.get(plan_id)
        if not plan or not plan.mutating:
            raise ToolRejected("计划不存在或不需要变更审批")
        if user_confirmed is not True:
            raise ToolRejected("变更操作必须由用户在计划预览后明确批准")
        if self.state!="running" or self.cancel_requested:
            raise ToolRejected("任务已暂停或停止；审批不能继续")
        ticket = secrets.token_urlsafe(24)
        expires=time.monotonic()+30
        self.approved[ticket]=(ticket,plan.binding,expires)
        self._audit("plan_approved",{"plan_id":ticket,"action":plan.action,"binding":plan.binding,"expires_in_seconds":30})
        self.plans[ticket] = Plan(ticket, plan.action, plan.args_json, plan.description, True,plan.scope_fingerprint,plan.window_identity)
        self.plan_expiry[ticket]=expires
        del self.plans[plan_id]
        self.plan_expiry.pop(plan_id,None)
        return ticket

    def execute(self, plan_id: str, approval_ticket: str | None = None):
        with self._gate_lock:
            self._prevalidate_audit()
            self._expire_plans()
            if self.state!="running" or self.cancel_requested:
                raise ToolRejected(f"任务当前状态为 {self.state}，已拒绝执行")
            if self.steps >= self.max_steps:raise ToolRejected("已达到本任务最大操作步数")
            plan=self.plans.get(plan_id)
            if plan is None:plan=next((p for p in self.plans.values() if p.id==plan_id),None)
            if plan is None:raise ToolRejected("计划不存在、已执行或已失效")
            if action:=plan.action:
                if action not in self.allowed_actions:raise ToolRejected("该工具权限已撤销")
            if plan.mutating:
                approval=self.approved.get(approval_ticket)
                if approval_ticket!=plan.id or not approval or approval[0]!=plan.id or approval[1]!=plan.binding:
                    raise ToolRejected("变更操作缺少绑定当前不可变计划参数的一次性审批")
            current_window=self._window_identity(plan.args["window_id"]) if plan.action in {"inspect_window","read_control_text","click_control","type_text"} else None
            if self._scope_for(plan.action,plan.args,current_window)!=plan.scope_fingerprint:raise ToolRejected("授权工作区、目标进程或对象状态已变化；审批与计划失效")
            self._describe(plan.action,plan.args)
            # Consume the approval atomically before entering the side-effecting executor.
            if approval_ticket:self.approved.pop(approval_ticket,None)
            self.plans.pop(plan_id,None)
            self.plan_expiry.pop(plan_id,None)
            self.steps+=1
            self._audit("operation_started",{"plan_id":plan.id,"action":plan.action,"step":self.steps})
        try:
            result = self._run(plan.action, plan.args)
            self._audit("operation_succeeded",{"plan_id":plan.id,"action":plan.action,"step":self.steps,"result_hash":hashlib.sha256(json.dumps(result,ensure_ascii=False,default=str,sort_keys=True).encode()).hexdigest()})
            if self.cancel_requested:self.state="stopped"
            elif self.state!="paused":self.state="running"
            self._save_checkpoint()
        except Exception as exc:
            self._audit("operation_failed",{"plan_id":plan.id,"action":plan.action,"step":self.steps,"error_type":type(exc).__name__})
            self.state="failed" if not self.cancel_requested else "stopped"
            self._save_checkpoint()
            raise
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

    @staticmethod
    def _process_created(pid: int) -> int:
        class FILETIME(ctypes.Structure):
            _fields_=[("low",ctypes.c_ulong),("high",ctypes.c_ulong)]
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel32.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
        kernel32.OpenProcess.restype=ctypes.c_void_p
        kernel32.GetProcessTimes.argtypes=[ctypes.c_void_p,ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]
        kernel32.GetProcessTimes.restype=ctypes.c_bool
        kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel32.OpenProcess(0x1000,False,int(pid))
        if not handle:raise ToolRejected("无法核验目标进程启动时间")
        try:
            created=FILETIME();exited=FILETIME();kernel=FILETIME();user=FILETIME()
            if not kernel32.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)):
                raise ToolRejected("无法核验目标进程身份")
            return (int(created.high)<<32)|int(created.low)
        finally:kernel32.CloseHandle(handle)

    def _window_identity(self,window_id):
        window=self._window(window_id)
        pid=int(window.element_info.process_id)
        image=self._process_image(pid)
        app_id=next((key for key,path in self.apps.items() if path==image),None)
        if app_id is None:raise ToolRejected("目标窗口未绑定本次应用授权")
        return (int(window.handle),pid,str(image),self._process_created(pid),app_id)

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
            observed=path.read_text(encoding="utf-8")
            if observed!=args["content"]:raise ToolRejected("写入后复读校验失败")
            return {"path":str(path.relative_to(self.workspace)),"characters":len(args["content"]),
                    "backup":str(backup.relative_to(self.workspace)) if backup else None,
                    "verified_sha256":hashlib.sha256(observed.encode("utf-8")).hexdigest()}
        if action == "launch_app":
            exe=self.apps[args["app_id"]]
            command=[str(exe)]
            if args["document"] is not None:command.append(str(self._workspace_path(args["document"])))
            process=subprocess.Popen(command,cwd=self.workspace,close_fds=True)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and process.poll() is not None:time.sleep(.05)
            if process.poll() is not None:raise ToolRejected(f"白名单程序启动后退出，exit={process.returncode}")
            actual=self._process_image(process.pid)
            if actual!=exe:raise ToolRejected("启动进程路径与已批准的程序不一致")
            return {"pid":process.pid,"app":exe.name,"verified_path":str(actual)}
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
            if action=="click_control":
                target.click_input()
                refreshed=self._window(args["window_id"])
                return {"clicked":selector,"window_still_verified":refreshed is not None}
            if target.element_info.control_type!="Edit":raise ToolRejected("为避免按键序列注入，只允许向 Edit 控件写入纯文本")
            target.set_edit_text(args["content"])
            try:observed=target.get_value()
            except Exception:observed=target.window_text()
            if observed!=args["content"]:raise ToolRejected("文本输入后复读校验失败")
            return {"set_characters":len(args["content"]),"verified":True}
        raise ToolRejected("未实现的操作")
