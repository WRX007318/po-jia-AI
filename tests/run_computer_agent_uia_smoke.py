"""Live Windows UIA smoke test against a fresh, isolated Notepad instance."""
from __future__ import annotations
import json, os, tempfile, time
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from computer_agent import ComputerAgent
from pywinauto import Desktop


def approved(agent, action, args):
    plan=agent.plan(action,args)
    ticket=agent.approve(plan.id,True) if plan.mutating else None
    return agent.execute(ticket or plan.id,approval_ticket=ticket)


def close_own_window(agent, window_id):
    if window_id is None:return
    try:
        window=agent._window(window_id)
        pid=window.element_info.process_id
        window.close()
        time.sleep(.35)
        for candidate in Desktop(backend="uia").windows():
            if candidate.element_info.process_id!=pid:continue
            buttons=[x for x in candidate.descendants() if x.element_info.control_type=="Button"]
            discard=next((x for x in buttons if x.element_info.name.startswith("不保存") or x.element_info.name=="Don't Save"),None)
            if discard:discard.click_input()
    except Exception:pass


def main():
    notepad=Path(os.environ.get("WINDIR",r"C:\Windows"))/"System32"/"notepad.exe"
    if not notepad.exists():raise SystemExit("Windows Notepad executable not found")
    for win in Desktop(backend="uia").windows():
        try:
            if ComputerAgent._process_image(win.element_info.process_id)==notepad.resolve():
                raise SystemExit("A Notepad window already exists; refusing to attach to a user window")
        except SystemExit:raise
        except Exception:pass

    with tempfile.TemporaryDirectory(prefix="pojia-uia-smoke-") as td:
        root=Path(td);agent=ComputerAgent(root,max_steps=12);agent.begin_task();app_id=agent.add_allowed_app(notepad);window_id=None
        try:
            launch=approved(agent,"launch_app",{"app_id":app_id,"document":None})
            deadline=time.time()+15;window=None
            while time.time()<deadline:
                rows=approved(agent,"list_windows",{})
                candidates=[x for x in rows if x["process"].lower()=="notepad.exe"]
                if candidates:
                    window=candidates[-1];window_id=window["window_id"];break
                time.sleep(.25)
            if window is None:raise SystemExit("UIA did not expose the launched Notepad window")
            controls=approved(agent,"inspect_window",{"window_id":window_id})
            edit=next((x for x in controls if x["control_type"]=="Edit" and (x["automation_id"] or x["name"])),None)
            if edit is None:raise SystemExit("Notepad UIA tree exposed no uniquely addressable Edit control")
            selector=edit["automation_id"] or edit["name"]
            text="破甲 AI UIA 实机测试：授权目录、文本输入、文件校验。"
            typed=approved(agent,"type_text",{"window_id":window_id,"selector":selector,"control_type":"Edit","content":text})
            observed=approved(agent,"read_control_text",{"window_id":window_id,"selector":selector,"control_type":"Edit"})
            if observed!=text:raise SystemExit(f"UIA content mismatch: expected {len(text)} chars, observed {len(observed)}")
            saved=approved(agent,"write_text",{"path":"uia-smoke.txt","content":observed})
            disk=(root/"uia-smoke.txt").read_text(encoding="utf-8")
            if disk!=text:raise SystemExit("Workspace save verification failed")
            print(json.dumps({"backend":"pywinauto UIA","program":"Windows Notepad","window_id":window_id,
                "launch_pid":launch["pid"],"control_type":edit["control_type"],"characters_typed":typed["set_characters"],
                "characters_read_back":len(observed),"saved_file":saved["path"],"disk_match":disk==text,
                "mutations_used_approval":True,"steps":agent.steps},ensure_ascii=False))
        finally:
            close_own_window(agent,window_id)


if __name__=="__main__":main()
