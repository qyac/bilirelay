from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.command_args import parse_sub_types, split_args, strip_command, to_int
from bilirelay.formatting import (
    clean_html,
    format_comment_list,
    format_search,
    format_video,
    human_count,
    human_duration,
    truncate,
)
from bilirelay.refs import (
    parse_article_ref,
    parse_bangumi_ref,
    parse_dynamic_ref,
    parse_uid,
    parse_video_ref,
)


class RefsTest(unittest.TestCase):
    def test_video_refs(self) -> None:
        self.assertEqual(parse_video_ref("BV1GJ411x7h7"), ("bvid", "BV1GJ411x7h7"))
        self.assertEqual(
            parse_video_ref("https://www.bilibili.com/video/BV1GJ411x7h7?p=2"),
            ("bvid", "BV1GJ411x7h7"),
        )
        self.assertEqual(parse_video_ref("av170001"), ("aid", "170001"))
        self.assertEqual(parse_video_ref("170001"), ("aid", "170001"))
        self.assertIsNone(parse_video_ref("not a video"))

    def test_uid(self) -> None:
        self.assertEqual(parse_uid("2"), 2)
        self.assertEqual(parse_uid("UID 2"), 2)
        self.assertEqual(parse_uid("uid:2"), 2)
        self.assertEqual(parse_uid("https://space.bilibili.com/2/video"), 2)
        self.assertIsNone(parse_uid("abc"))

    def test_bangumi_and_article(self) -> None:
        self.assertEqual(parse_bangumi_ref("ss28747"), ("season_id", 28747))
        self.assertEqual(parse_bangumi_ref("ep233333"), ("ep_id", 233333))
        self.assertEqual(parse_article_ref("cv417529"), 417529)
        self.assertEqual(parse_article_ref("417529"), 417529)
        self.assertEqual(parse_dynamic_ref("1255716547539763206"), "1255716547539763206")


class CommandArgsTest(unittest.TestCase):
    def test_strip_command(self) -> None:
        groups = {"bili", "b站"}
        subs = {"search", "搜索"}
        self.assertEqual(strip_command("/bili search AstrBot", groups, subs), "AstrBot")
        self.assertEqual(strip_command("bili search AstrBot", groups, subs), "AstrBot")
        self.assertEqual(strip_command("!b站 搜索 AstrBot", groups, subs), "AstrBot")
        self.assertEqual(
            strip_command("@bot /bili search AstrBot", groups, subs), "AstrBot"
        )
        self.assertEqual(strip_command("/bili search", groups, subs), "")
        self.assertEqual(
            strip_command("/bili sub add 2", groups, {"sub"}), "add 2"
        )

    def test_split_and_types(self) -> None:
        self.assertEqual(split_args("a  b\u3000c"), ["a", "b", "c"])
        self.assertEqual(to_int("3", 1), 3)
        self.assertEqual(to_int("x", 1), 1)
        self.assertEqual(parse_sub_types(["视频", "直播"]), ["video", "live"])
        self.assertEqual(parse_sub_types(["all"]), ["video", "dynamic", "live"])
        self.assertEqual(parse_sub_types([]), ["video", "dynamic", "live"])


class FormattingTest(unittest.TestCase):
    def test_human_count(self) -> None:
        self.assertEqual(human_count(999), "999")
        self.assertEqual(human_count(12_345), "1.2万")
        self.assertEqual(human_count(120_000_000), "1.2亿")
        self.assertEqual(human_count("bad"), "0")

    def test_human_duration(self) -> None:
        self.assertEqual(human_duration(83), "01:23")
        self.assertEqual(human_duration("10:3"), "10:03")
        self.assertEqual(human_duration("1:02:03"), "1:02:03")
        self.assertEqual(human_duration(None), "未知")

    def test_clean_and_truncate(self) -> None:
        self.assertEqual(clean_html('<em class="keyword">Astr</em>Bot'), "AstrBot")
        self.assertEqual(clean_html("&amp;"), "&")
        self.assertEqual(truncate("abcdef", 5), "abcd…")
        self.assertEqual(truncate("abc", 5), "abc")

    def test_format_search(self) -> None:
        text = format_search(
            "AstrBot",
            "video",
            [
                {
                    "title": "<em>AstrBot</em> 教程",
                    "author": "UP",
                    "play": 12345,
                    "duration": "10:03",
                    "bvid": "BV1xx411c7mD",
                }
            ],
        )
        self.assertIn("（视频）", text)
        self.assertIn("AstrBot 教程", text)
        self.assertIn("1.2万播放", text)
        self.assertIn("https://www.bilibili.com/video/BV1xx411c7mD", text)

    def test_format_video(self) -> None:
        text = format_video(
            {
                "title": "标题",
                "owner": {"name": "UP", "mid": 2},
                "stat": {"view": 100, "danmaku": 2, "favorite": 3, "coin": 4},
                "duration": 83,
                "pubdate": 1700000000,
                "bvid": "BV1xx411c7mD",
                "desc": "简介",
            }
        )
        self.assertIn("📺 标题", text)
        self.assertIn("UP（UID 2）", text)
        self.assertIn("01:23", text)

    def test_format_comments(self) -> None:
        text = format_comment_list(
            [{"uname": "A", "message": "hi", "like": 10000}], limit=5
        )
        self.assertIn("A（👍 1万）", text)


if __name__ == "__main__":
    unittest.main()
