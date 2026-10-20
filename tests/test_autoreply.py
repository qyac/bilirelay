from __future__ import annotations

import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.autoreply import (
    AutoReplyEngine,
    _parse_bvids,
    _parse_ids,
    _parse_keywords,
)

TEMP_ROOT = ROOT / "tests" / ".tmp"


class FakeClient:
    def __init__(self, uid: int = 1) -> None:
        self.cookies = {
            "DedeUserID": str(uid),
            "bili_jct": "csrf-test",
            "SESSDATA": "sess-test",
        }

    def has_login_cookie(self) -> bool:
        return True


class FakeAPI:
    def __init__(self) -> None:
        self.comment_items: list[dict] = []
        self.reply_calls: list[tuple[str, str, int, int]] = []
        self.sessions: list[dict] = []
        self.messages: dict[int, list[dict]] = {}
        self.sent_dms: list[tuple[int, str]] = []
        self.videos: list[dict] = []

    async def video(self, ref: str) -> dict:
        return {"bvid": ref, "title": "测试视频"}

    async def latest_comments(self, ref: str, **kwargs) -> dict:
        return {"video": {"title": "测试视频"}, "items": list(self.comment_items)}

    async def reply_comment(self, ref: str, message: str, *, root: int = 0, parent: int = 0) -> dict:
        self.reply_calls.append((ref, message, root, parent))
        return {"rpid": 999}

    async def user_videos(self, uid: int, *, limit: int = 5) -> dict:
        return {"items": self.videos}

    async def dm_sessions(self, *, size: int = 20) -> list[dict]:
        return list(self.sessions)

    async def dm_messages(self, uid: int, *, size: int = 20) -> list[dict]:
        return list(self.messages.get(uid, []))

    async def send_dm(self, uid: int, message: str) -> dict:
        self.sent_dms.append((uid, message))
        return {"msg_key": 1}


class AutoReplyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.work = TEMP_ROOT / uuid.uuid4().hex
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def config(self, **overrides) -> dict:
        base = {
            "enable_auto_reply": True,
            "auto_reply_comments": True,
            "auto_reply_dms": False,
            "comment_targets": "BV1xx411c7mD",
            "comment_poll_interval": 180,
            "comment_max_per_round": 3,
            "comment_cooldown_minutes": 30,
            "comment_max_age_minutes": 999,
            "comment_min_chars": 1,
            "comment_reply_mode": "template",
            "comment_template": "谢谢{user}",
            "auto_reply_dry_run": False,
            "dm_reply_mode": "template",
            "dm_template": "你好{user}",
            "dm_allow_all": False,
            "dm_whitelist": "",
            "dm_max_age_minutes": 999,
            "dm_min_chars": 1,
            "dm_cooldown_minutes": 10,
            "dm_context_messages": 6,
            "auto_reply_reply_interval": 0,
        }
        base.update(overrides)
        return base

    def engine(self, api: FakeAPI, **config) -> AutoReplyEngine:
        return AutoReplyEngine(
            None,
            api,
            FakeClient(),
            self.config(**config),
            self.work,
        )

    async def test_comment_baseline_then_reply_once(self) -> None:
        api = FakeAPI()
        now = int(time.time())
        api.comment_items = [
            {"rpid": 1, "mid": 2, "uname": "观众A", "message": "旧评论", "ctime": now, "root": 0, "parent": 0}
        ]
        engine = self.engine(api)
        await engine.run_comments_once()
        self.assertEqual(api.reply_calls, [])

        api.comment_items.append(
            {"rpid": 2, "mid": 3, "uname": "观众B", "message": "新评论", "ctime": now + 1, "root": 0, "parent": 0}
        )
        await engine.run_comments_once()
        self.assertEqual(len(api.reply_calls), 1)
        ref, message, root, parent = api.reply_calls[0]
        self.assertEqual(message, "谢谢观众B")
        self.assertEqual(root, 2)
        self.assertEqual(parent, 2)

        await engine.run_comments_once()
        self.assertEqual(len(api.reply_calls), 1)

    async def test_comment_skip_own_and_keywords(self) -> None:
        api = FakeAPI()
        now = int(time.time())
        api.comment_items = [
            {"rpid": 1, "mid": 1, "uname": "自己", "message": "自己的评论", "ctime": now, "root": 0, "parent": 0},
            {"rpid": 2, "mid": 2, "uname": "观众", "message": "广告内容", "ctime": now, "root": 0, "parent": 0},
        ]
        engine = self.engine(api, comment_ignore_keywords="广告")
        await engine.run_comments_once()  # baseline
        api.comment_items.append(
            {"rpid": 3, "mid": 2, "uname": "观众", "message": "广告内容", "ctime": now + 1, "root": 0, "parent": 0}
        )
        api.comment_items.append(
            {"rpid": 4, "mid": 1, "uname": "自己", "message": "自己的新评论", "ctime": now + 1, "root": 0, "parent": 0}
        )
        await engine.run_comments_once()
        self.assertEqual(api.reply_calls, [])

    async def test_dm_baseline_then_reply_allowed(self) -> None:
        api = FakeAPI()
        now = int(time.time())
        api.sessions = [{"uid": 2}]
        api.messages[2] = [
            {
                "msg_key": "m1",
                "sender_uid": 2,
                "msg_type": 1,
                "msg_status": 0,
                "timestamp": now,
                "content": "你好",
            }
        ]
        engine = self.engine(api, auto_reply_comments=False, auto_reply_dms=True, dm_allow_all=True)
        await engine.run_dms_once()
        self.assertEqual(api.sent_dms, [])

        api.messages[2].append(
            {
                "msg_key": "m2",
                "sender_uid": 2,
                "msg_type": 1,
                "msg_status": 0,
                "timestamp": now + 1,
                "content": "催更",
            }
        )
        await engine.run_dms_once()
        self.assertEqual(len(api.sent_dms), 1)
        self.assertEqual(api.sent_dms[0], (2, "你好UID 2"))

    async def test_dm_whitelist(self) -> None:
        api = FakeAPI()
        api.sessions = [{"uid": 2}]
        api.messages[2] = []
        engine = self.engine(api, auto_reply_comments=False, auto_reply_dms=True, dm_allow_all=False)
        await engine.run_dms_once()
        self.assertEqual(api.sent_dms, [])


    async def test_llm_generation_and_sanitize(self) -> None:
        api = FakeAPI()

        async def fake_llm(prompt: str, system: str) -> str:
            self.assertIn("新评论", prompt)
            self.assertIn("B 站", system)
            return "  「收到啦」 \n 谢谢反馈！ "

        engine = AutoReplyEngine(
            None,
            api,
            FakeClient(),
            self.config(comment_reply_mode="llm", comment_template="fallback"),
            self.work,
            llm_func=fake_llm,
        )
        reply = await engine.generate_reply("comment", user="观众", content="新评论")
        self.assertEqual(reply, "收到啦 谢谢反馈！")

    async def test_start_requires_login_and_master(self) -> None:
        api = FakeAPI()
        engine = self.engine(api, enable_auto_reply=False)
        ok, message = engine.start()
        self.assertFalse(ok)
        self.assertIn("总开关", message)

    def test_parse_helpers(self) -> None:
        self.assertEqual(_parse_bvids("BV1xx411c7mD, https://www.bilibili.com/video/BV1GJ411x7h7"), ["BV1xx411c7mD", "BV1GJ411x7h7"])
        self.assertEqual(_parse_ids("2, UID 3; 2"), {2, 3})
        self.assertEqual(_parse_keywords("广告, 互关\n刷屏"), ["广告", "互关", "刷屏"])


if __name__ == "__main__":
    unittest.main()
