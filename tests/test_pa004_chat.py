"""Regression tests for chat response integrity and durable draft recovery."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from runtime import IncompleteGeneration, iter_answer
from store import Store


def event(delta=None, finish=None):
    return ("data: "+json.dumps({"choices":[{"delta":delta or {},"finish_reason":finish}]})+"\n").encode()


class StreamIntegrityTests(unittest.TestCase):
    def test_complete(self):
        frames=[event({"reasoning_content":"hidden"}),event({"content":"答"}),event({"content":"案"}),
                event(finish="stop"),b'data: {"choices":[],"usage":{"completion_tokens":2}}\n',b"data: [DONE]\n"]
        self.assertEqual("".join(iter_answer(frames)),"答案")

    def test_length_preserves_partial_and_fails(self):
        stream=iter_answer([event({"content":"partial"}),event(finish="length"),b"data: [DONE]\n"])
        self.assertEqual(next(stream),"partial")
        with self.assertRaises(IncompleteGeneration) as cm:
            next(stream)
        self.assertEqual(cm.exception.reason,"length")

    def test_disconnect_after_visible_content(self):
        stream=iter_answer([event({"content":"partial"}),event(finish="stop")])
        self.assertEqual(next(stream),"partial")
        with self.assertRaisesRegex(IncompleteGeneration,"stream_disconnected"):
            next(stream)

    def test_reasoning_only_not_complete(self):
        with self.assertRaisesRegex(IncompleteGeneration,"empty_final_answer"):
            list(iter_answer([event({"reasoning_content":"not an answer"}),event(finish="stop"),b"data: [DONE]\n"]))


class DraftRecoveryTests(unittest.TestCase):
    def test_reopen_and_complete_only_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);store=Store(root);sid=store.new_session()
            store.begin_draft(sid,"写长文")
            store.save_draft(sid,"第一段","length")
            reopened=Store(root)
            self.assertEqual(reopened.draft(sid)["content"],"第一段")
            self.assertEqual(reopened.draft(sid)["status"],"length")
            self.assertEqual([m["role"] for m in reopened.messages(sid)],["user"])
            reopened.finish_draft(sid,"第一段第二段")
            self.assertIsNone(reopened.draft(sid))
            self.assertEqual(reopened.messages(sid)[-1]["content"],"第一段第二段")
            with self.assertRaises(RuntimeError):
                reopened.finish_draft(sid,"不能重复保存")
            self.assertEqual(len(reopened.messages(sid)),2)

    def test_sessions_isolated_and_explicit_discard(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td));a=store.new_session();b=store.new_session()
            store.begin_draft(a,"A");store.begin_draft(b,"B")
            store.save_draft(a,"partial A","cancelled")
            store.discard_draft(a)
            self.assertIn("未完成",store.messages(a)[-1]["content"])
            self.assertEqual(store.draft(b)["content"],"")
            self.assertEqual(len(store.messages(b)),1)

    def test_empty_answer_and_duplicate_draft_not_committed(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td));sid=store.new_session();store.begin_draft(sid,"问")
            with self.assertRaises(ValueError):store.finish_draft(sid,"")
            with self.assertRaises(Exception):store.begin_draft(sid,"重复")
            self.assertEqual(len(store.messages(sid)),1)
            self.assertIsNotNone(store.draft(sid))


if __name__=="__main__":unittest.main()
