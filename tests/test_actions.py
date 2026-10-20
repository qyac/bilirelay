from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.api import BiliAPI


class FakeClient:
    def __init__(self) -> None:
        self.cookies = {"DedeUserID": "10", "bili_jct": "csrf", "SESSDATA": "s"}
        self.calls: list[dict[str, Any]] = []

    def has_login_cookie(self) -> bool:
        return True

    async def request_json(self, path: str, params=None, **kwargs):
        self.calls.append({"path": path, "params": params or {}, **kwargs})
        if path == "/x/web-interface/view":
            return {
                "code": 0,
                "data": {
                    "bvid": "BV1xx411c7mD",
                    "aid": 123,
                    "title": "t",
                    "owner": {"mid": 10, "name": "UP"},
                    "stat": {},
                },
            }
        if path == "/x/v2/reply/add":
            return {"code": 0, "data": {"rpid": 456}}
        if "get_sessions" in path:
            return {
                "code": 0,
                "data": {
                    "session_list": [
                        {"talker_id": 2, "session_type": 1, "last_msg": {"timestamp": 100}},
                        {"talker_id": 844424930131966, "session_type": 1},
                        {"talker_id": 3, "session_type": 2},
                    ]
                },
            }
        if "fetch_session_msgs" in path:
            return {
                "code": 0,
                "data": {
                    "messages": [
                        {"msg_key": 2, "sender_uid": 2, "msg_type": 1, "msg_status": 0, "timestamp": 200, "content": '{"content":"hi"}'},
                    ]
                },
            }
        if "send_msg" in path:
            return {"code": 0, "data": {"msg_key": 999}}
        return {"code": 0, "data": {}}


class ActionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_reply_comment(self) -> None:
        client = FakeClient()
        api = BiliAPI(client)  # type: ignore[arg-type]
        result = await api.reply_comment("BV1xx411c7mD", "谢谢", root=11, parent=12)
        self.assertEqual(result["rpid"], 456)
        call = next(item for item in client.calls if item["path"] == "/x/v2/reply/add")
        self.assertEqual(call["data"]["oid"], 123)
        self.assertEqual(call["data"]["root"], 11)
        self.assertEqual(call["data"]["parent"], 12)
        self.assertEqual(call["data"]["csrf"], "csrf")
        self.assertEqual(call["method"], "POST")

    async def test_dm_sessions_filters_system(self) -> None:
        client = FakeClient()
        api = BiliAPI(client)  # type: ignore[arg-type]
        sessions = await api.dm_sessions()
        self.assertEqual([s["uid"] for s in sessions], [2])

    async def test_dm_messages_text(self) -> None:
        client = FakeClient()
        api = BiliAPI(client)  # type: ignore[arg-type]
        messages = await api.dm_messages(2)
        self.assertEqual(messages[0]["content"], "hi")
        self.assertEqual(messages[0]["sender_uid"], 2)

    async def test_send_dm(self) -> None:
        client = FakeClient()
        api = BiliAPI(client)  # type: ignore[arg-type]
        result = await api.send_dm(2, "你好")
        self.assertEqual(result["msg_key"], 999)
        call = next(item for item in client.calls if "send_msg" in item["path"])
        self.assertEqual(call["data"]["msg[sender_uid]"], 10)
        self.assertEqual(call["data"]["msg[receiver_id]"], 2)
        self.assertEqual(call["data"]["csrf"], "csrf")
        self.assertEqual(json.loads(call["data"]["msg[content]"])["content"], "你好")
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["params"]["w_receiver_id"], 2)


if __name__ == "__main__":
    unittest.main()
