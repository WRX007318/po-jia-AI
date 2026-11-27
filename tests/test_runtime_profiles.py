import tempfile
import threading
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from runtime import Runtime, MODEL_PROFILES
from inference_lock import InferenceLease


class RuntimeProfileTests(unittest.TestCase):
    def test_iq2_cuda_is_primary_and_rollbacks_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=Runtime(root,root/"models")
            self.assertEqual(runtime.profile_id,"iq2_m_cuda")
            self.assertEqual(runtime.profile["model"],"Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf")
            self.assertEqual((runtime.profile["gpu_layers"],runtime.profile["cpu_moe"],runtime.context_size,runtime.profile["threads"]),(99,0,4096,4))
            runtime.set_profile("iq3_s_cuda")
            self.assertIn("IQ3_S",runtime.profile["model"])
            runtime.set_profile("iq3_s_vulkan")
            self.assertEqual(runtime.profile["backend"],"Vulkan")
            self.assertIn("vulkan",runtime.profile["runtime"])
            with self.assertRaises(ValueError):runtime.set_profile("unknown")

    def test_context_uses_exact_counter_and_keeps_first_constraint_and_latest_turn(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=Runtime(root,root/"models")
            calls=[]
            def counter(messages,timeout=15,image_path=None):
                calls.append(messages)
                return sum(len(m["content"]) for m in messages)
            runtime.count_tokens=counter
            messages=[{"role":"system","content":"sys"},
                      {"role":"user","content":"PIN"},{"role":"assistant","content":"old answer"},
                      {"role":"user","content":"middle question"},{"role":"assistant","content":"middle answer"},
                      {"role":"user","content":"LATEST"}]
            selected=runtime.build_context(messages,token_budget=27,output_tokens=512)
            self.assertEqual(selected[0]["content"],"sys")
            self.assertIn("PIN",[m["content"] for m in selected])
            self.assertIn("LATEST",[m["content"] for m in selected])
            self.assertNotIn("middle answer",[m["content"] for m in selected])
            self.assertGreaterEqual(len(calls),2)
            with self.assertRaisesRegex(ValueError,"超过"):
                runtime.build_context(messages,token_budget=4000,output_tokens=512)

    def test_inference_lease_serializes_local_threads_and_observes_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"inference.lock";first=InferenceLease(path)
            self.assertTrue(first.acquire(timeout=.2))
            results=[]
            def contender():results.append(InferenceLease(path).acquire(timeout=.15))
            thread=threading.Thread(target=contender);thread.start();thread.join()
            self.assertEqual(results,[False])
            first.release()
            cancel=threading.Event();cancel.set()
            self.assertFalse(InferenceLease(path).acquire(cancel_event=cancel,timeout=.2))
            next_lease=InferenceLease(path)
            self.assertTrue(next_lease.acquire(timeout=.2));next_lease.release()


if __name__=="__main__":unittest.main()
