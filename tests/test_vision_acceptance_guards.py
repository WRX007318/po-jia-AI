from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.service_endpoint import service_base
from app.vision_pipeline import SCHEMA,_validate_schema


class VisionAcceptanceGuardTests(unittest.TestCase):
    def test_annotation_matches_strict_json_schema(self):
        value={"page_type":"订单管理","visible_text":["订单列表"],"elements":[{"type":"table","text":"订单列表","label":"业务订单"}],"labels":["普通业务"],"needs_human_review":False}
        _validate_schema(value)
        invalid=dict(value);invalid["extra"]="unexpected"
        with self.assertRaisesRegex(ValueError,"Schema"):_validate_schema(invalid)
        invalid=dict(value);invalid["elements"]=[{"type":"table","text":"x","label":"y","unexpected":1}]
        with self.assertRaisesRegex(ValueError,"Schema"):_validate_schema(invalid)
        self.assertEqual(SCHEMA["required"],list(value))

    def test_endpoint_port_is_configurable_and_loopback_only(self):
        with patch.dict(os.environ,{"POJIA_LLM_PORT":"61234","POJIA_LLM_HOST":"127.0.0.1"}):
            self.assertEqual(service_base(),"http://127.0.0.1:61234")
        with patch.dict(os.environ,{"POJIA_LLM_HOST":"0.0.0.0"}):
            with self.assertRaisesRegex(ValueError,"loopback"):service_base()
        with patch.dict(os.environ,{"POJIA_LLM_PORT":"70000"}):
            with self.assertRaisesRegex(ValueError,"TCP port"):service_base()


if __name__=="__main__":unittest.main()
