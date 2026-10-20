"""动态（Dynamic）结构解析。

B 站动态返回的是 ``modules`` 嵌套结构，不同动态类型差异很大。
这里统一抽取成便于格式化和订阅判断的扁平字典。
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: Any, default: int = 0) -> int:
    """兼容 ``3.8万`` / ``123`` / 空值等动态数字字段。"""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except (TypeError, ValueError):
        return default


def _first_image(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    for item in values:
        if isinstance(item, str) and item:
            return item
        if isinstance(item, Mapping):
            for key in ("src", "url", "cover"):
                if item.get(key):
                    return str(item[key])
    return ""


def parse_dynamic(item: Mapping[str, Any]) -> dict[str, Any]:
    """把一条动态解析为统一结构。"""
    modules = item.get("modules") or {}
    author = modules.get("module_author") or {}
    dynamic = modules.get("module_dynamic") or {}
    desc = dynamic.get("desc") or {}
    major = dynamic.get("major") or {}
    major_type = _text(major.get("type"))
    uid = author.get("mid") or 0
    dynamic_id = _text(item.get("id_str") or item.get("id"))
    text = _text(desc.get("text"))

    archive: dict[str, Any] = {}
    live: dict[str, Any] = {}
    article: dict[str, Any] = {}
    images: list[str] = []

    archive_data = major.get("archive") or {}
    if archive_data:
        stat = archive_data.get("stat") or {}
        archive = {
            "bvid": _text(archive_data.get("bvid")),
            "title": _text(archive_data.get("title")),
            "cover": _text(archive_data.get("cover")),
            "duration": _text(archive_data.get("duration_text")),
            "play": _int(stat.get("play")),
            "danmaku": _int(stat.get("danmaku")),
            "desc": _text(archive_data.get("desc")),
        }

    draw = major.get("draw") or {}
    if draw:
        images = [
            _text(image.get("src"))
            for image in (draw.get("items") or [])
            if isinstance(image, Mapping) and image.get("src")
        ]

    opus = major.get("opus") or {}
    if opus:
        summary = opus.get("summary") or {}
        if not text:
            text = _text(summary.get("text"))
        for pic in opus.get("pics") or []:
            if isinstance(pic, Mapping) and pic.get("url"):
                images.append(_text(pic["url"]))

    article_data = major.get("article") or {}
    if article_data:
        article = {
            "id": _text(article_data.get("id")),
            "title": _text(article_data.get("title")),
            "desc": _text(article_data.get("desc")),
            "cover": _first_image(article_data.get("covers")),
        }

    live_data = major.get("live") or {}
    if live_data:
        live = {
            "title": _text(live_data.get("title")),
            "cover": _text(live_data.get("cover")),
            "state": _int(live_data.get("live_state")),
            "room_id": _int(live_data.get("room_id")),
            "online": _int(live_data.get("online")),
        }
    live_rcmd = major.get("live_rcmd") or {}
    if live_rcmd and not live:
        content = live_rcmd.get("content") or ""
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            live_info = (parsed.get("live_play_info") or {}) if isinstance(parsed, Mapping) else {}
            live = {
                "title": _text(live_info.get("title")),
                "cover": _text(live_info.get("cover")),
                "state": _int(live_info.get("live_status")),
                "room_id": _int(live_info.get("room_id")),
                "online": _int(live_info.get("online")),
            }
        except (TypeError, ValueError):
            pass

    common = major.get("common") or {}
    if common and not archive and not article:
        archive = {
            "bvid": "",
            "title": _text(common.get("title")),
            "cover": _text(common.get("cover")),
            "duration": "",
            "play": 0,
            "danmaku": 0,
            "desc": _text(common.get("desc")),
        }

    original = item.get("orig")
    orig_parsed = parse_dynamic(original) if isinstance(original, Mapping) else None
    if not text and orig_parsed:
        text = f"转发动态：{orig_parsed.get('text', '')}"

    dynamic_type = _text(item.get("type"))
    url = f"https://www.bilibili.com/opus/{dynamic_id}" if dynamic_id else ""

    return {
        "id": dynamic_id,
        "type": dynamic_type,
        "major_type": major_type,
        "uid": _int(uid),
        "author": _text(author.get("name")),
        "face": _text(author.get("face")),
        "pub_ts": _int(author.get("pub_ts")),
        "text": text,
        "images": images[:9],
        "archive": archive,
        "article": article,
        "live": live,
        "url": url,
        "orig": orig_parsed,
    }
