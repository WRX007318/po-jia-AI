import tempfile
import threading
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from computer_agent import ComputerAgent, ToolRejected


class ComputerAgentTests(unittest.TestCase):
    def test_write_requires_one_time_explicit_approval_and_stays_in_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);agent=ComputerAgent(root);agent.begin_task()
            plan=agent.plan("write_text",{"path":"notes.txt","content":"UIA smoke test"})
            with self.assertRaisesRegex(ToolRejected,"审批"):
                agent.execute(plan.id)
            with self.assertRaisesRegex(ToolRejected,"明确批准"):
                agent.approve(plan.id,user_confirmed=False)
            ticket=agent.approve(plan.id,user_confirmed=True)
            result=agent.execute(ticket,approval_ticket=ticket)
            self.assertEqual(result["characters"],14)
            self.assertEqual((root/"notes.txt").read_text(encoding="utf-8"),"UIA smoke test")
            replace=agent.plan("write_text",{"path":"notes.txt","content":"replacement"})
            replace_ticket=agent.approve(replace.id,user_confirmed=True)
            replaced=agent.execute(replace_ticket,approval_ticket=replace_ticket)
            self.assertEqual((root/replaced["backup"]).read_text(encoding="utf-8"),"UIA smoke test")
            self.assertEqual((root/"notes.txt").read_text(encoding="utf-8"),"replacement")
            with self.assertRaisesRegex(ToolRejected,"不存在"):
                agent.execute(ticket,approval_ticket=ticket)

    def test_paths_and_action_schema_are_restricted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);agent=ComputerAgent(root);agent.begin_task()
            with self.assertRaisesRegex(ToolRejected,"越出"):
                agent.plan("read_text",{"path":"../outside.txt"})
            with self.assertRaisesRegex(ToolRejected,"不支持"):
                agent.plan("exec_shell",{"command":"whoami"})
            with self.assertRaisesRegex(ToolRejected,"schema"):
                agent.plan("list_windows",{"process_id":1})
            with self.assertRaisesRegex(ToolRejected,"1 MiB"):
                agent.plan("write_text",{"path":"large.txt","content":"x"*(1_000_001)})

    def test_independent_tool_permissions_are_enforced_by_executor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"a.txt").write_text("read",encoding="utf-8")
            agent=ComputerAgent(root,allowed_actions={"read_text"});agent.begin_task()
            self.assertEqual(agent.execute(agent.plan("read_text",{"path":"a.txt"}).id),"read")
            with self.assertRaisesRegex(ToolRejected,"独立工具权限"):
                agent.plan("write_text",{"path":"a.txt","content":"no"})

    def test_allowlisted_launch_and_window_controls_require_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fake=root/"safe-test.exe";fake.write_bytes(b"MZ")
            agent=ComputerAgent(root);agent.begin_task();app_id=agent.add_allowed_app(fake)
            plan=agent.plan("launch_app",{"app_id":app_id,"document":None})
            self.assertTrue(plan.mutating)
            with self.assertRaisesRegex(ToolRejected,"white|白名单"):
                agent.plan("launch_app",{"app_id":"unknown","document":None})

    def test_per_task_step_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"a.txt").write_text("a",encoding="utf-8")
            agent=ComputerAgent(root,max_steps=1);agent.begin_task()
            first=agent.plan("read_text",{"path":"a.txt"})
            self.assertEqual(agent.execute(first.id),"a")
            second=agent.plan("read_text",{"path":"a.txt"})
            with self.assertRaisesRegex(ToolRejected,"最大操作步数"):
                agent.execute(second.id)
            agent.begin_task()
            third=agent.plan("read_text",{"path":"a.txt"})
            self.assertEqual(agent.execute(third.id),"a")

    def test_plan_arguments_are_immutable_and_approval_dies_on_pause(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);agent=ComputerAgent(root);agent.begin_task()
            plan=agent.plan("write_text",{"path":"a.txt","content":"original"})
            leaked=plan.args;leaked["content"]="tampered"
            self.assertEqual(plan.args["content"],"original")
            ticket=agent.approve(plan.id,True)
            self.assertTrue(agent.pause())
            self.assertEqual(agent.state,"paused")
            self.assertTrue(agent.resume())
            with self.assertRaisesRegex(ToolRejected,"不存在|已失效"):
                agent.execute(ticket,approval_ticket=ticket)

    def test_checkpoint_resume_and_workspace_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);checkpoint=root/"agent.json";agent=ComputerAgent(root,checkpoint_path=checkpoint)
            agent.begin_task();agent.steps=3;agent.pause()
            restored=ComputerAgent(root,checkpoint_path=checkpoint)
            self.assertTrue(restored.restore_checkpoint())
            self.assertEqual((restored.state,restored.steps),("paused",3))
            with tempfile.TemporaryDirectory() as other:
                foreign=ComputerAgent(Path(other),checkpoint_path=checkpoint)
                with self.assertRaisesRegex(ToolRejected,"工作目录"):
                    foreign.restore_checkpoint()

    def test_audit_chain_detects_manual_tampering_and_records_approved_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);checkpoint=root/"state"/"agent.json"
            agent=ComputerAgent(root,checkpoint_path=checkpoint);agent.begin_task()
            plan=agent.plan("write_text",{"path":"note.txt","content":"approved"})
            ticket=agent.approve(plan.id,True)
            agent.execute(ticket,approval_ticket=ticket)
            audit=checkpoint.parent/"computer-agent-audit.jsonl"
            records=[__import__("json").loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
            self.assertIn("plan_approved",[row["event"] for row in records])
            self.assertIn("operation_succeeded",[row["event"] for row in records])
            audit.write_text(audit.read_text(encoding="utf-8").replace("operation_succeeded","tampered"),encoding="utf-8")
            with self.assertRaisesRegex(ToolRejected,"审计日志"):
                ComputerAgent(root,checkpoint_path=checkpoint)

    def test_revoking_app_invalidates_plans_and_stops_future_steps(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fake=root/"safe-test.exe";fake.write_bytes(b"MZ")
            agent=ComputerAgent(root);agent.begin_task();app_id=agent.add_allowed_app(fake)
            plan=agent.plan("launch_app",{"app_id":app_id,"document":None})
            self.assertTrue(agent.revoke_app(app_id))
            with self.assertRaisesRegex(ToolRejected,"paused"):
                agent.execute(plan.id)

    def test_execute_prevalidates_audit_and_consumes_ticket_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);checkpoint=root/"state"/"agent.json";agent=ComputerAgent(root,checkpoint_path=checkpoint)
            agent.begin_task();plan=agent.plan("write_text",{"path":"approved.txt","content":"safe"})
            ticket=agent.approve(plan.id,True);audit=checkpoint.parent/"computer-agent-audit.jsonl"
            audit.write_text(audit.read_text(encoding="utf-8").replace("task_started","task_broken"),encoding="utf-8")
            with self.assertRaisesRegex(ToolRejected,"审计日志"):
                agent.execute(ticket,approval_ticket=ticket)
            self.assertFalse((root/"approved.txt").exists())

    def test_approval_ticket_is_consumed_once_under_concurrent_execute(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);agent=ComputerAgent(root);agent.begin_task()
            plan=agent.plan("write_text",{"path":"once.txt","content":"once"})
            ticket=agent.approve(plan.id,True);barrier=threading.Barrier(3);results=[]
            def run():
                barrier.wait()
                try:results.append(("ok",agent.execute(ticket,approval_ticket=ticket)))
                except ToolRejected as exc:results.append(("rejected",str(exc)))
            threads=[threading.Thread(target=run) for _ in range(2)]
            for thread in threads:thread.start()
            barrier.wait()
            for thread in threads:thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual([item[0] for item in results].count("ok"),1)
            self.assertEqual((root/"once.txt").read_text(encoding="utf-8"),"once")

    def test_emergency_stop_is_terminal_and_recovery_stays_paused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);checkpoint=root/"state"/"agent.json"
            agent=ComputerAgent(root,checkpoint_path=checkpoint);agent.begin_task()
            plan=agent.plan("write_text",{"path":"blocked.txt","content":"no"})
            ticket=agent.approve(plan.id,True)
            self.assertTrue(agent.stop());self.assertEqual(agent.state,"stopped")
            self.assertFalse(agent.resume())
            with self.assertRaisesRegex(ToolRejected,"stopped"):
                agent.execute(ticket,approval_ticket=ticket)
            self.assertFalse((root/"blocked.txt").exists())
            restored=ComputerAgent(root,checkpoint_path=checkpoint)
            with self.assertRaisesRegex(ToolRejected,"状态不可恢复"):
                restored.restore_checkpoint()


if __name__=="__main__":unittest.main()
