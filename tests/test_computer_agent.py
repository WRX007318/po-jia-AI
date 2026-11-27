import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from computer_agent import ComputerAgent, ToolRejected


class ComputerAgentTests(unittest.TestCase):
    def test_write_requires_one_time_explicit_approval_and_stays_in_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);agent=ComputerAgent(root)
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
            root=Path(td);agent=ComputerAgent(root)
            with self.assertRaisesRegex(ToolRejected,"越出"):
                agent.plan("read_text",{"path":"../outside.txt"})
            with self.assertRaisesRegex(ToolRejected,"不支持"):
                agent.plan("exec_shell",{"command":"whoami"})
            with self.assertRaisesRegex(ToolRejected,"schema"):
                agent.plan("list_windows",{"process_id":1})
            with self.assertRaisesRegex(ToolRejected,"1 MiB"):
                agent.plan("write_text",{"path":"large.txt","content":"x"*(1_000_001)})

    def test_allowlisted_launch_and_window_controls_require_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fake=root/"safe-test.exe";fake.write_bytes(b"MZ")
            agent=ComputerAgent(root);app_id=agent.add_allowed_app(fake)
            plan=agent.plan("launch_app",{"app_id":app_id,"document":None})
            self.assertTrue(plan.mutating)
            with self.assertRaisesRegex(ToolRejected,"white|白名单"):
                agent.plan("launch_app",{"app_id":"unknown","document":None})

    def test_per_task_step_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"a.txt").write_text("a",encoding="utf-8")
            agent=ComputerAgent(root,max_steps=1)
            first=agent.plan("read_text",{"path":"a.txt"})
            self.assertEqual(agent.execute(first.id),"a")
            second=agent.plan("read_text",{"path":"a.txt"})
            with self.assertRaisesRegex(ToolRejected,"最大操作步数"):
                agent.execute(second.id)
            agent.begin_task()
            third=agent.plan("read_text",{"path":"a.txt"})
            self.assertEqual(agent.execute(third.id),"a")


if __name__=="__main__":unittest.main()
