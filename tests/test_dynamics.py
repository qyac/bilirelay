from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.dynamics import parse_dynamic
from bilirelay.formatting import format_dynamic


class DynamicsTest(unittest.TestCase):
    def test_parse_archive_dynamic(self) -> None:
        item = {
            "id_str": "1255716547539763206",
            "type": "DYNAMIC_TYPE_AV",
            "modules": {
                "module_author": {
                    "name": "测试UP",
                    "mid": 2,
                    "pub_ts": 1700000000,
                    "face": "https://example.com/a.jpg",
                },
                "module_dynamic": {
                    "desc": {"text": "新视频来啦"},
                    "major": {
                        "type": "MAJOR_TYPE_ARCHIVE",
                        "archive": {
                            "bvid": "BV1xx411c7mD",
                            "title": "视频标题",
                            "cover": "https://example.com/c.jpg",
                            "duration_text": "01:23",
                            "stat": {"play": "3.8万", "danmaku": 12},
                        },
                    },
                },
            },
        }
        result = parse_dynamic(item)
        self.assertEqual(result["id"], "1255716547539763206")
        self.assertEqual(result["author"], "测试UP")
        self.assertEqual(result["uid"], 2)
        self.assertEqual(result["text"], "新视频来啦")
        self.assertEqual(result["archive"]["bvid"], "BV1xx411c7mD")
        self.assertEqual(result["archive"]["play"], 38000)
        self.assertEqual(result["archive"]["danmaku"], 12)
        self.assertEqual(
            result["url"], "https://www.bilibili.com/opus/1255716547539763206"
        )
        text = format_dynamic(result)
        self.assertIn("新视频来啦", text)
        self.assertIn("视频标题", text)
        self.assertIn("https://www.bilibili.com/video/BV1xx411c7mD", text)

    def test_parse_opus_dynamic(self) -> None:
        item = {
            "id_str": "1234567890123456789",
            "type": "DYNAMIC_TYPE_DRAW",
            "modules": {
                "module_author": {"name": "画师", "mid": 3, "pub_ts": 1700000000},
                "module_dynamic": {
                    "major": {
                        "type": "MAJOR_TYPE_OPUS",
                        "opus": {
                            "summary": {"text": "今日摸鱼"},
                            "pics": [
                                {"url": "https://example.com/1.jpg"},
                                {"url": "https://example.com/2.jpg"},
                            ],
                        },
                    }
                },
            },
        }
        result = parse_dynamic(item)
        self.assertEqual(result["text"], "今日摸鱼")
        self.assertEqual(len(result["images"]), 2)

    def test_forward_without_author_does_not_crash(self) -> None:
        item = {
            "id_str": "1",
            "type": "DYNAMIC_TYPE_FORWARD",
            "modules": {},
            "orig": {
                "id_str": "2",
                "type": "DYNAMIC_TYPE_WORD",
                "modules": {"module_dynamic": {"desc": {"text": "原动态"}}},
            },
        }
        result = parse_dynamic(item)
        self.assertIn("转发动态", result["text"])

    def test_json_roundtrip(self) -> None:
        # 动态里经常出现 "3.8万" 之类字符串，确保不会抛异常
        payload = json.loads(
            '{"id_str":"1","type":"DYNAMIC_TYPE_AV","modules":{"module_author":{"name":"a","mid":1,"pub_ts":1},"module_dynamic":{"major":{"type":"MAJOR_TYPE_ARCHIVE","archive":{"bvid":"BV1xx411c7mD","title":"t","stat":{"play":"1.2万","danmaku":"3"}}}}}}'
        )
        result = parse_dynamic(payload)
        self.assertEqual(result["archive"]["play"], 12000)


if __name__ == "__main__":
    unittest.main()
