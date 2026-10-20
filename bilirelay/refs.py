"""从用户输入中解析 B 站 BV/AV/UID/直播间/番剧/专栏标识。"""

from __future__ import annotations

import re

_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_AV_RE = re.compile(r"(?:^|[/?=&])av(\d+)", re.IGNORECASE)
_UID_RE = re.compile(r"space\.bilibili\.com/(\d+)", re.IGNORECASE)
_LIVE_RE = re.compile(r"live\.bilibili\.com/(?:h5/)?(\d+)", re.IGNORECASE)
_SS_RE = re.compile(r"(?:^|[/?=&])ss(\d+)", re.IGNORECASE)
_EP_RE = re.compile(r"(?:^|[/?=&])ep(\d+)", re.IGNORECASE)
_CV_RE = re.compile(r"(?:read/cv|/cv)(\d+)", re.IGNORECASE)
_DYNAMIC_RE = re.compile(r"(?:t\.bilibili\.com|bilibili\.com/opus)/(\d+)", re.IGNORECASE)
_PLAIN_UID_RE = re.compile(r"^\s*(?:uid\s*[:：]?\s*)?(\d+)\s*$", re.IGNORECASE)
_PLAIN_ROOM_RE = re.compile(r"^\s*(?:room|房间号?)[:：]?\s*(\d+)\s*$", re.IGNORECASE)
_PLAIN_CV_RE = re.compile(r"^\s*(?:cv|专栏)?(\d+)\s*$", re.IGNORECASE)


def parse_video_ref(ref: str) -> tuple[str, str] | None:
    """返回 ``("bvid", value)`` 或 ``("aid", value)``；无法识别返回 None。"""
    text = (ref or "").strip()
    if not text:
        return None
    match = _BV_RE.search(text)
    if match:
        return "bvid", match.group(0)
    match = _AV_RE.search(text)
    if match:
        return "aid", match.group(1)
    if text.isdigit():
        return "aid", text
    return None


def parse_uid(ref: str) -> int | None:
    """从 UID、空间链接或 ``uid:123`` 中解析 UID。"""
    text = (ref or "").strip()
    match = _UID_RE.search(text)
    if match:
        return int(match.group(1))
    match = _PLAIN_UID_RE.match(text)
    if match:
        return int(match.group(1))
    return None


def parse_room(ref: str) -> tuple[str, int] | None:
    """解析直播间：返回 ``("room", id)``；普通数字按 UID 处理。"""
    text = (ref or "").strip()
    match = _LIVE_RE.search(text)
    if match:
        return "room", int(match.group(1))
    match = _PLAIN_ROOM_RE.match(text)
    if match:
        return "room", int(match.group(1))
    if text.isdigit():
        return "uid", int(text)
    return None


def parse_bangumi_ref(ref: str) -> tuple[str, int] | None:
    """解析番剧 season_id / ep_id。"""
    text = (ref or "").strip()
    match = _SS_RE.search(text)
    if match:
        return "season_id", int(match.group(1))
    match = _EP_RE.search(text)
    if match:
        return "ep_id", int(match.group(1))
    if text.isdigit():
        return "season_id", int(text)
    return None


def parse_article_ref(ref: str) -> int | None:
    """解析专栏 cv 号。"""
    text = (ref or "").strip()
    match = _CV_RE.search(text)
    if match:
        return int(match.group(1))
    match = _PLAIN_CV_RE.match(text)
    if match:
        return int(match.group(1))
    return None


def parse_dynamic_ref(ref: str) -> str | None:
    """解析动态 id（opus / t.bilibili.com 链接或纯数字）。"""
    text = (ref or "").strip()
    match = _DYNAMIC_RE.search(text)
    if match:
        return match.group(1)
    if text.isdigit() and len(text) >= 10:
        return text
    return None
