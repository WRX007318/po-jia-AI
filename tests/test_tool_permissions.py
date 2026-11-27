import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from tool_permissions import ToolPermissionsStore,DEFAULT_TOOL_IDS

class ToolPermissionsTests(unittest.TestCase):
    def test_independent_atomic_tool_allowlist_and_fail_closed_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            store=ToolPermissionsStore(Path(td)/"permissions.json")
            self.assertEqual(store.load(),set(DEFAULT_TOOL_IDS))
            self.assertEqual(store.save({"read_text","list_windows"}),{"read_text","list_windows"})
            self.assertEqual(store.load(),{"read_text","list_windows"})
            with self.assertRaisesRegex(ValueError,"未知工具"):
                store.save({"shell"})
            store.path.write_text(json.dumps({"schema_version":1,"enabled_tools":["shell"]}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"未知或重复"):
                store.load()

if __name__=="__main__":unittest.main()
