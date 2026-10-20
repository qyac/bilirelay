"""面向插件的高层 B 站数据接口。

这一层负责：

* 选择合适（且尽量低风控）的接口
* 把 B 站原始 JSON 归一化成稳定的字典结构
* 在接口失效时做一次合理的降级
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from .client import LIVE_BASE, BiliClient
from .dynamics import parse_dynamic
from .errors import BiliError, NotLoggedIn, RiskControl
from .formatting import clean_html, truncate
from .refs import parse_bangumi_ref, parse_uid, parse_video_ref

# 游客访问 space 系接口时使用的 dm_img 风控参数（与浏览器一致）
_DM_PARAMS = {
    "dm_img_list": "[]",
    "dm_img_str": base64.b64encode(b"WebGL 1.0 (OpenGL ES 2.0 Chromium)")
    .decode()
    .rstrip("="),
    "dm_cover_img_str": base64.b64encode(
        b"ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) "
        b"Direct3D11 vs_5_0 ps_5_0), or similar"
    )
    .decode()
    .rstrip("="),
    "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
}

SEARCH_TYPES = {
    "video": "video",
    "视频": "video",
    "v": "video",
    "user": "bili_user",
    "up": "bili_user",
    "用户": "bili_user",
    "up主": "bili_user",
    "live": "live",
    "直播": "live",
    "bangumi": "media_bangumi",
    "番剧": "media_bangumi",
    "anime": "media_bangumi",
    "article": "article",
    "专栏": "article",
    "cv": "article",
    "影视": "media_ft",
    "film": "media_ft",
}
SEARCH_TYPE_LABELS = {
    "video": "视频",
    "bili_user": "用户",
    "live": "直播",
    "media_bangumi": "番剧",
    "media_ft": "影视",
    "article": "专栏",
}

RANK_AREAS = {
    "全站": 0,
    "动画": 1,
    "番剧": 13,
    "国创": 168,
    "音乐": 3,
    "舞蹈": 129,
    "游戏": 4,
    "知识": 36,
    "科技": 188,
    "运动": 234,
    "汽车": 223,
    "生活": 160,
    "美食": 211,
    "动物": 217,
    "鬼畜": 119,
    "时尚": 155,
    "资讯": 202,
    "影视": 181,
    "纪录": 177,
    "电影": 23,
    "电视剧": 11,
}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _stat(stat: Any) -> dict[str, int]:
    raw = stat if isinstance(stat, Mapping) else {}
    return {
        "view": _int(raw.get("view")),
        "danmaku": _int(raw.get("danmaku")),
        "reply": _int(raw.get("reply")),
        "favorite": _int(raw.get("favorite")),
        "coin": _int(raw.get("coin")),
        "share": _int(raw.get("share")),
        "like": _int(raw.get("like")),
    }


def _pic(value: Any) -> str:
    url = _str(value)
    if url.startswith("//"):
        return "https:" + url
    return url


def normalize_video(data: Mapping[str, Any]) -> dict[str, Any]:
    owner = data.get("owner") or {}
    return {
        "aid": _int(data.get("aid")),
        "bvid": _str(data.get("bvid")),
        "cid": _int(data.get("cid")),
        "title": clean_html(data.get("title")),
        "desc": clean_html(data.get("desc")),
        "cover": _pic(data.get("pic")),
        "pubdate": _int(data.get("pubdate")),
        "ctime": _int(data.get("ctime")),
        "duration": _int(data.get("duration")),
        "tname": _str(data.get("tname")),
        "tid": _int(data.get("tid")),
        "videos": _int(data.get("videos"), 1),
        "state": _int(data.get("state")),
        "copyright": _int(data.get("copyright")),
        "dynamic": clean_html(data.get("dynamic")),
        "owner": {
            "mid": _int(owner.get("mid")),
            "name": _str(owner.get("name")),
            "face": _pic(owner.get("face")),
        },
        "stat": _stat(data.get("stat")),
        "pages": [
            {
                "cid": _int(page.get("cid")),
                "page": _int(page.get("page")),
                "part": _str(page.get("part")),
                "duration": _int(page.get("duration")),
            }
            for page in (data.get("pages") or [])
            if isinstance(page, Mapping)
        ],
    }


def normalize_user_search(data: Mapping[str, Any]) -> dict[str, Any]:
    verify = data.get("official_verify") or {}
    return {
        "uid": _int(data.get("mid")),
        "name": clean_html(data.get("uname")),
        "sign": clean_html(data.get("usign")),
        "fans": _int(data.get("fans")),
        "videos": _int(data.get("videos")),
        "level": _int(data.get("level")),
        "face": _pic(data.get("upic")),
        "official": clean_html(verify.get("desc")) if verify.get("type", -1) >= 0 else "",
    }


def normalize_video_search(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "aid": _int(data.get("aid")),
        "bvid": _str(data.get("bvid")),
        "title": clean_html(data.get("title")),
        "author": clean_html(data.get("author")),
        "mid": _int(data.get("mid")),
        "play": _int(data.get("play")),
        "danmaku": _int(data.get("video_review")),
        "favorite": _int(data.get("favorites")),
        "duration": _str(data.get("duration")),
        "pubdate": _int(data.get("pubdate")),
        "description": clean_html(data.get("description")),
        "cover": _pic(data.get("pic")),
        "url": _pic(data.get("arcurl")),
    }


def normalize_live_search(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "roomid": _int(data.get("roomid")),
        "uid": _int(data.get("uid")),
        "title": clean_html(data.get("title")),
        "uname": clean_html(data.get("uname")),
        "online": _int(data.get("online")),
        "cover": _pic(data.get("cover")),
        "area": clean_html(data.get("area_v2_name")),
    }


def normalize_bangumi_search(data: Mapping[str, Any]) -> dict[str, Any]:
    score = data.get("media_score") or {}
    return {
        "season_id": _int(data.get("season_id")),
        "title": clean_html(data.get("title")),
        "cover": _pic(data.get("cover")),
        "desc": clean_html(data.get("desc")),
        "score": score.get("score") or 0,
        "season_type_name": _str(data.get("season_type_name")),
    }


def normalize_article_search(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _int(data.get("id")),
        "title": clean_html(data.get("title")),
        "desc": clean_html(data.get("desc")),
        "author": clean_html(data.get("author_name") or data.get("up_name")),
        "view": _int(data.get("view")),
        "like": _int(data.get("like")),
    }


def normalize_reply_items(
    raw: list[Mapping[str, Any]],
    *,
    include_replies: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """把评论接口返回的 reply 数组归一化，可选展开楼中楼。"""
    seen: set[int] = set()
    items: list[dict[str, Any]] = []

    def add_item(reply: Mapping[str, Any], default_root: int = 0, default_parent: int = 0) -> None:
        rpid = _int(reply.get("rpid"))
        if not rpid or rpid in seen:
            return
        seen.add(rpid)
        member = reply.get("member") or {}
        content = reply.get("content") or {}
        items.append(
            {
                "rpid": rpid,
                "root": _int(reply.get("root"), default_root),
                "parent": _int(reply.get("parent"), default_parent),
                "uname": clean_html(member.get("uname")),
                "mid": _int(member.get("mid")),
                "message": clean_html(content.get("message")),
                "like": _int(reply.get("like")),
                "ctime": _int(reply.get("ctime")),
                "rcount": _int(reply.get("rcount")),
            }
        )
        if include_replies:
            for child in reply.get("replies") or []:
                if isinstance(child, Mapping):
                    add_item(child, default_root=rpid, default_parent=rpid)

    for reply in raw:
        add_item(reply)
    return items[: max(1, limit) + 1]



class BiliAPI:
    """B 站数据接口集合。"""

    def __init__(self, client: BiliClient) -> None:
        self.client = client

    # ------------------------------------------------------------------ 搜索
    async def search(
        self,
        keyword: str,
        search_type: str = "video",
        *,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        keyword = (keyword or "").strip()
        if not keyword:
            raise BiliError(-400, "搜索关键词不能为空")
        api_type = SEARCH_TYPES.get(search_type.lower(), SEARCH_TYPES.get(search_type, "video"))
        params = {
            "search_type": api_type,
            "keyword": keyword,
            "page": max(1, page),
            "page_size": max(1, min(50, limit)),
        }
        try:
            payload = await self.client.request_json(
                "/x/web-interface/wbi/search/type",
                params,
                signed=True,
                referer="https://search.bilibili.com/",
            )
        except RiskControl:
            # 新版 WBI 搜索被风控时，旧版接口通常还能用
            payload = await self.client.request_json(
                "/x/web-interface/search/type",
                params,
                signed=False,
                no_cache=True,
                retries=1,
                referer="https://search.bilibili.com/",
            )
        data = payload.get("data") or {}
        raw_items = data.get("result") or []
        if isinstance(raw_items, Mapping):
            raw_items = [raw_items]
        if api_type == "video":
            items = [normalize_video_search(item) for item in raw_items if isinstance(item, Mapping)]
        elif api_type == "bili_user":
            items = [normalize_user_search(item) for item in raw_items if isinstance(item, Mapping)]
        elif api_type == "live":
            items = [normalize_live_search(item) for item in raw_items if isinstance(item, Mapping)]
        elif api_type in ("media_bangumi", "media_ft"):
            items = [normalize_bangumi_search(item) for item in raw_items if isinstance(item, Mapping)]
        elif api_type == "article":
            items = [normalize_article_search(item) for item in raw_items if isinstance(item, Mapping)]
        else:
            items = [dict(item) for item in raw_items if isinstance(item, Mapping)]
        return {
            "type": api_type,
            "label": SEARCH_TYPE_LABELS.get(api_type, api_type),
            "keyword": keyword,
            "page": _int(data.get("page"), page),
            "pages": _int(data.get("numPages"), 1),
            "total": _int(data.get("numResults"), len(items)),
            "items": items,
        }

    # ------------------------------------------------------------------ 视频
    async def _resolve_video_input(self, ref: str) -> str:
        text = (ref or "").strip()
        if "b23.tv" in text or "bili2233.cn" in text:
            text = await self.client.resolve_redirect(text)
        return text

    async def video(self, ref: str) -> dict[str, Any]:
        text = await self._resolve_video_input(ref)
        parsed = parse_video_ref(text)
        if not parsed:
            raise BiliError(-400, "无法识别视频，请发送 BV 号、av 号或视频链接")
        key, value = parsed
        payload = await self.client.request_json(
            "/x/web-interface/view",
            {key: value},
            referer=f"https://www.bilibili.com/video/{value}",
        )
        data = payload.get("data") or {}
        video = normalize_video(data)
        if not video["bvid"]:
            raise BiliError(-404, "视频不存在")
        return video

    async def video_summary(self, ref: str) -> dict[str, Any]:
        video = await self.video(ref)
        if not video.get("cid"):
            raise BiliError(-404, "视频缺少 cid，无法获取总结")
        params = {
            "aid": video["aid"],
            "bvid": video["bvid"],
            "cid": video["cid"],
            "up_mid": video["owner"]["mid"],
        }
        payload = await self.client.request_json(
            "/x/web-interface/view/conclusion/get",
            params,
            signed=True,
            no_cache=True,
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        data = payload.get("data") or {}
        model = data.get("model_result") or {}
        summary = clean_html(model.get("summary"))
        outline: list[dict[str, Any]] = []
        for section in model.get("outline") or []:
            if not isinstance(section, Mapping):
                continue
            outline.append(
                {
                    "title": clean_html(section.get("title")),
                    "timestamp": _int(section.get("timestamp")),
                    "points": [
                        {
                            "timestamp": _int(point.get("timestamp")),
                            "content": clean_html(point.get("content")),
                        }
                        for point in (section.get("part_outline") or [])
                        if isinstance(point, Mapping)
                    ],
                }
            )
        ai_subtitle = ""
        subtitles = model.get("subtitle") or []
        if subtitles and isinstance(subtitles[0], Mapping):
            parts = subtitles[0].get("part_subtitle") or []
            ai_subtitle = "\n".join(
                clean_html(part.get("content"))
                for part in parts
                if isinstance(part, Mapping) and part.get("content")
            )
        return {
            "video": video,
            "available": bool(summary or outline),
            "summary": summary,
            "outline": outline,
            "ai_subtitle": truncate(ai_subtitle, 12000),
            "code": _int(data.get("code")),
            "stid": _str(data.get("stid")),
        }

    async def video_subtitles(self, ref: str, lang: str = "") -> dict[str, Any]:
        video = await self.video(ref)
        if not video.get("cid"):
            raise BiliError(-404, "视频缺少 cid，无法读取字幕")
        payload = await self.client.request_json(
            "/x/player/wbi/v2",
            {"bvid": video["bvid"], "cid": video["cid"]},
            signed=True,
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        data = payload.get("data") or {}
        subtitle_data = data.get("subtitle") or {}
        subtitles = [
            item
            for item in (subtitle_data.get("subtitles") or [])
            if isinstance(item, Mapping) and item.get("subtitle_url")
        ]
        if not subtitles:
            return {
                "video": video,
                "available": False,
                "logged_in": self.client.has_login_cookie(),
                "subtitles": [],
                "selected": None,
                "segments": [],
                "text": "",
            }

        selected = None
        if lang:
            for item in subtitles:
                if lang in (_str(item.get("lan")), _str(item.get("lan_doc"))):
                    selected = item
                    break
        if selected is None:
            for item in subtitles:
                if _str(item.get("lan")) in ("zh-CN", "zh-Hans", "ai-zh"):
                    selected = item
                    break
        selected = selected or subtitles[0]
        subtitle_url = _pic(selected.get("subtitle_url"))
        body_payload = await self.client.request_json(
            subtitle_url,
            no_cache=True,
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        segments = [
            {
                "from": float(item.get("from") or 0),
                "to": float(item.get("to") or 0),
                "content": clean_html(item.get("content")),
            }
            for item in (body_payload.get("body") or [])
            if isinstance(item, Mapping) and item.get("content")
        ]
        text = "\n".join(segment["content"] for segment in segments)
        return {
            "video": video,
            "available": bool(segments),
            "logged_in": self.client.has_login_cookie(),
            "subtitles": [
                {
                    "lan": _str(item.get("lan")),
                    "lan_doc": _str(item.get("lan_doc")),
                    "ai_type": _int(item.get("ai_type")),
                }
                for item in subtitles
            ],
            "selected": {
                "lan": _str(selected.get("lan")),
                "lan_doc": _str(selected.get("lan_doc")),
            },
            "segments": segments,
            "text": truncate(text, 20000),
        }

    async def comments(
        self,
        ref: str,
        *,
        page: int = 1,
        limit: int = 20,
        sort: int = 2,
        include_replies: bool = False,
    ) -> dict[str, Any]:
        video = await self.video(ref)
        payload = await self.client.request_json(
            "/x/v2/reply",
            {
                "type": 1,
                "oid": video["aid"],
                "pn": max(1, page),
                "ps": max(1, min(20, limit)),
                "sort": sort,
            },
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        data = payload.get("data") or {}
        raw: list[Mapping[str, Any]] = []
        for key in ("top_replies", "replies"):
            value = data.get(key)
            if isinstance(value, list):
                raw.extend(item for item in value if isinstance(item, Mapping))
        return {
            "video": video,
            "page": _int(data.get("page"), page),
            "items": normalize_reply_items(
                raw, include_replies=include_replies, limit=limit
            ),
            "total": _int((data.get("page") or {}).get("count")),
        }

    async def latest_comments(
        self,
        ref: str,
        *,
        limit: int = 20,
        include_replies: bool = False,
    ) -> dict[str, Any]:
        """按时间获取最新评论（懒加载接口，适合自动回复轮询）。"""
        video = await self.video(ref)
        params = {
            "type": 1,
            "oid": video["aid"],
            "mode": 2,
            "plat": 1,
            "web_location": 1315875,
        }
        try:
            payload = await self.client.request_json(
                "/x/v2/reply/wbi/main",
                params,
                signed=True,
                no_cache=True,
                referer=f"https://www.bilibili.com/video/{video['bvid']}",
            )
        except BiliError as exc:
            if exc.code != -403:
                raise
            # WBI 签名密钥轮换时新版评论接口会返回 -403，换一套密钥重试
            self.client.reset_session()
            payload = await self.client.request_json(
                "/x/v2/reply/wbi/main",
                params,
                signed=True,
                no_cache=True,
                retries=1,
                referer=f"https://www.bilibili.com/video/{video['bvid']}",
            )
        data = payload.get("data") or {}
        raw: list[Mapping[str, Any]] = []
        for key in ("top_replies", "replies"):
            value = data.get(key)
            if isinstance(value, list):
                raw.extend(item for item in value if isinstance(item, Mapping))
        cursor = data.get("cursor") or {}
        return {
            "video": video,
            "items": normalize_reply_items(
                raw, include_replies=include_replies, limit=limit
            ),
            "total": _int(cursor.get("all_count")),
            "cursor": cursor,
        }

    async def _login_identity(self, feature: str) -> tuple[int, str]:
        """返回 (自己的 UID, 可用于 POST 的 csrf)。"""
        uid = _int(self.client.cookies.get("DedeUserID"))
        csrf = _str(self.client.cookies.get("bili_jct"))
        if not uid or not csrf:
            nav = await self.client.nav_info()
            if not nav.get("is_login"):
                raise NotLoggedIn(feature)
            uid = uid or _int(nav.get("mid"))
            csrf = csrf or _str(self.client.cookies.get("bili_jct"))
        if not uid or not csrf:
            raise NotLoggedIn(feature)
        return uid, csrf

    async def reply_comment(
        self,
        ref: str,
        message: str,
        *,
        root: int = 0,
        parent: int = 0,
    ) -> dict[str, Any]:
        """回复视频评论。root/parent 都为 0 时是发一条新的一级评论。"""
        video = await self.video(ref)
        _, csrf = await self._login_identity("回复评论")
        text = truncate(message, 1000, suffix="")
        if not text:
            raise BiliError(-400, "回复内容为空")
        data: dict[str, Any] = {
            "type": 1,
            "oid": video["aid"],
            "message": text,
            "plat": 1,
            "csrf": csrf,
        }
        if root:
            data["root"] = root
        if parent:
            data["parent"] = parent
        payload = await self.client.request_json(
            "/x/v2/reply/add",
            method="POST",
            data=data,
            no_cache=True,
            retries=1,
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        return payload.get("data") or {}

    async def dm_sessions(self, *, size: int = 20) -> list[dict[str, Any]]:
        """获取私信会话列表（只保留普通用户会话）。"""
        await self._login_identity("读取私信")
        last_payload: dict[str, Any] = {}
        for session_type in (1, 4):
            payload = await self.client.request_json(
                "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions",
                {
                    "session_type": session_type,
                    "group_fold": 0,
                    "unfollow_fold": 0,
                    "sort_rule": 2,
                    "size": max(1, min(100, size)),
                    "build": 0,
                    "mobi_app": "web",
                },
                referer="https://message.bilibili.com/",
                headers={"Origin": "https://message.bilibili.com"},
                no_cache=True,
                retries=1,
            )
            last_payload = payload
            data = payload.get("data") or {}
            sessions = []
            for item in data.get("session_list") or []:
                if not isinstance(item, Mapping):
                    continue
                talker_id = _int(item.get("talker_id"))
                if not talker_id or talker_id >= 10_000_000_000:
                    # 系统消息/粉丝团等 talker_id 远大于普通用户 UID
                    continue
                if _int(item.get("session_type")) != 1:
                    continue
                last_msg = item.get("last_msg") or {}
                if last_msg.get("sender_uid") is not None and _int(last_msg.get("sender_uid")) == 0:
                    continue
                sessions.append(
                    {
                        "uid": talker_id,
                        "session_type": 1,
                        "unread": _int(item.get("unread_count")),
                        "last_ts": _int(last_msg.get("timestamp")),
                        "last_msg_key": _str(last_msg.get("msg_key")),
                    }
                )
            if sessions:
                return sessions
        if last_payload and last_payload.get("code") not in (0, None):
            raise BiliError(last_payload.get("code", -1), str(last_payload.get("message") or ""))
        return []

    async def dm_messages(self, talker_id: int | str, *, size: int = 20) -> list[dict[str, Any]]:
        """读取与某个用户的私信记录（按 B 站返回的时间倒序）。"""
        await self._login_identity("读取私信")
        payload = await self.client.request_json(
            "https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs",
            {
                "talker_id": int(talker_id),
                "session_type": 1,
                "size": max(1, min(2000, size)),
                "sender_device_id": 1,
                "build": 0,
                "mobi_app": "web",
            },
            referer="https://message.bilibili.com/",
            headers={"Origin": "https://message.bilibili.com"},
            no_cache=True,
            retries=1,
        )
        data = payload.get("data") or {}
        messages = []
        for item in data.get("messages") or []:
            if not isinstance(item, Mapping):
                continue
            messages.append(
                {
                    "msg_key": _str(item.get("msg_key")),
                    "sender_uid": _int(item.get("sender_uid")),
                    "receiver_id": _int(item.get("receiver_id")),
                    "receiver_type": _int(item.get("receiver_type")),
                    "msg_type": _int(item.get("msg_type")),
                    "msg_status": _int(item.get("msg_status")),
                    "timestamp": _int(item.get("timestamp")),
                    "content": self._dm_content(item.get("content")),
                }
            )
        messages.sort(key=lambda msg: (msg["timestamp"], msg["msg_key"]))
        return messages

    @staticmethod
    def _dm_content(raw: Any) -> str:
        text = _str(raw)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if isinstance(parsed, Mapping):
            for key in ("content", "text", "title"):
                if parsed.get(key):
                    return _str(parsed[key])
        return text

    async def send_dm(self, talker_id: int | str, message: str) -> dict[str, Any]:
        """给指定 UID 发送一条文字私信。"""
        uid, csrf = await self._login_identity("发送私信")
        text = truncate(message, 500, suffix="")
        if not text:
            raise BiliError(-400, "私信内容为空")
        dev_id = str(uuid.uuid4()).upper()
        receiver = int(talker_id)
        params = {
            "w_sender_uid": uid,
            "w_receiver_id": receiver,
            "w_dev_id": dev_id,
        }
        data: dict[str, Any] = {
            "msg[sender_uid]": uid,
            "msg[receiver_id]": receiver,
            "msg[receiver_type]": 1,
            "msg[msg_type]": 1,
            "msg[msg_status]": 0,
            "msg[dev_id]": dev_id,
            "msg[timestamp]": int(time.time()),
            "msg[new_face_version]": 1,
            "msg[content]": json.dumps({"content": text}, ensure_ascii=False),
            "csrf": csrf,
            "csrf_token": csrf,
            "build": 0,
            "mobi_app": "web",
        }
        url = "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg"
        try:
            # WBI 签名是可选的，先用普通 Cookie + csrf 发送
            payload = await self.client.request_json(
                url,
                params,
                method="POST",
                data=data,
                no_cache=True,
                retries=0,
                referer="https://message.bilibili.com/",
                headers={"Origin": "https://message.bilibili.com"},
            )
        except RiskControl:
            payload = await self.client.request_json(
                url,
                params,
                signed=True,
                method="POST",
                data=data,
                no_cache=True,
                retries=1,
                referer="https://message.bilibili.com/",
                headers={"Origin": "https://message.bilibili.com"},
            )
        return payload.get("data") or {}

    async def danmaku(self, ref: str, *, limit: int = 50) -> dict[str, Any]:
        video = await self.video(ref)
        if not video.get("cid"):
            raise BiliError(-404, "视频缺少 cid，无法读取弹幕")
        xml_text = await self.client.request_text(
            f"https://api.bilibili.com/x/v1/dm/list.so",
            {"oid": video["cid"]},
            referer=f"https://www.bilibili.com/video/{video['bvid']}",
        )
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise BiliError(-1, "弹幕数据解析失败") from exc
        items = []
        seen: set[str] = set()
        for node in root.iter("d"):
            text = (node.text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            p = (node.get("p") or "").split(",")
            try:
                seconds = float(p[0]) if p else 0.0
            except ValueError:
                seconds = 0.0
            items.append({"time": seconds, "text": text})
            if len(items) >= max(1, limit):
                break
        return {"video": video, "items": items, "total": len(items)}

    # ------------------------------------------------------------------ 用户
    async def user(self, uid: int | str) -> dict[str, Any]:
        uid_int = int(uid)
        try:
            payload = await self.client.request_json(
                "/x/web-interface/card",
                {"mid": uid_int},
                referer=f"https://space.bilibili.com/{uid_int}",
            )
            card = (payload.get("data") or {}).get("card") or {}
        except BiliError:
            card = {}
        if not card:
            params = {
                "mid": uid_int,
                "platform": "web",
                "web_location": 1550101,
                **_DM_PARAMS,
            }
            payload = await self.client.request_json(
                "/x/space/wbi/acc/info",
                params,
                signed=True,
                referer=f"https://space.bilibili.com/{uid_int}",
            )
            card = payload.get("data") or {}
            if not card:
                raise BiliError(-404, f"未找到 UID {uid_int} 的用户")

        stat: dict[str, Any] = {}
        try:
            stat_payload = await self.client.request_json(
                "/x/relation/stat",
                {"vmid": uid_int},
                referer=f"https://space.bilibili.com/{uid_int}",
            )
            stat = stat_payload.get("data") or {}
        except BiliError:
            stat = {}
        level_info = card.get("level_info") or {}
        official = card.get("official_verify") or {}
        vip = card.get("vip") or {}
        return {
            "uid": _int(card.get("mid"), uid_int),
            "name": clean_html(card.get("name")),
            "face": _pic(card.get("face")),
            "sign": clean_html(card.get("sign")),
            "fans": _int(card.get("fans"), _int(stat.get("follower"))),
            "following": _int(card.get("attention"), _int(stat.get("following"))),
            "archive_count": _int(card.get("archive_count")),
            "level": _int(level_info.get("current_level")),
            "official": clean_html(official.get("desc")) if _int(official.get("type"), -1) >= 0 else "",
            "vip": clean_html((vip.get("label") or {}).get("text")),
        }

    async def user_videos(
        self,
        uid: int | str,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        uid_int = int(uid)
        page = max(1, page)
        limit = max(1, min(50, limit))
        try:
            payload = await self.client.request_json(
                "/x/series/recArchivesByKeywords",
                {
                    "mid": uid_int,
                    "keywords": "",
                    "ps": limit,
                    "pn": page,
                    "orderby": "pubdate",
                },
                referer=f"https://space.bilibili.com/{uid_int}/video",
            )
            data = payload.get("data") or {}
            archives = data.get("archives") or []
            total = _int((data.get("page") or {}).get("count"), len(archives))
            return {
                "uid": uid_int,
                "page": page,
                "total": total,
                "items": [self._normalize_archive(item) for item in archives if isinstance(item, Mapping)],
            }
        except BiliError as first_error:
            try:
                payload = await self.client.request_json(
                    "/x/space/wbi/arc/search",
                    {
                        "mid": uid_int,
                        "pn": page,
                        "ps": limit,
                        "order": "pubdate",
                        "tid": 0,
                        "keyword": "",
                        "platform": "web",
                        "web_location": 1550101,
                        **_DM_PARAMS,
                    },
                    signed=True,
                    referer=f"https://space.bilibili.com/{uid_int}/video",
                )
            except BiliError:
                # 两套投稿接口都被风控时，退而使用 UP 主的动态里的视频卡片
                try:
                    dynamics = await self.user_dynamics(uid_int, limit=limit)
                except BiliError:
                    raise first_error
                items: list[dict[str, Any]] = []
                seen: set[str] = set()
                for dynamic in dynamics.get("items") or []:
                    archive = dynamic.get("archive") or {}
                    bvid = archive.get("bvid")
                    if not bvid or bvid in seen:
                        continue
                    seen.add(bvid)
                    items.append(
                        {
                            "aid": 0,
                            "bvid": bvid,
                            "title": archive.get("title") or "",
                            "cover": archive.get("cover") or "",
                            "duration": 0,
                            "pubdate": _int(dynamic.get("pub_ts")),
                            "play": _int(archive.get("play")),
                            "comment": _int(archive.get("danmaku")),
                            "author": dynamic.get("author") or "",
                        }
                    )
                return {
                    "uid": uid_int,
                    "page": page,
                    "total": len(items),
                    "source": "dynamics",
                    "items": items,
                }
            data = payload.get("data") or {}
            listing = data.get("list") or {}
            vlist = listing.get("vlist") or []
            total = _int((data.get("page") or {}).get("count"), len(vlist))
            return {
                "uid": uid_int,
                "page": page,
                "total": total,
                "items": [self._normalize_archive(item) for item in vlist if isinstance(item, Mapping)],
            }

    @staticmethod
    def _normalize_archive(item: Mapping[str, Any]) -> dict[str, Any]:
        stat = item.get("stat") or {}
        duration = item.get("duration")
        if duration is None:
            length = _str(item.get("length"))
            if ":" in length:
                parts = [part for part in length.split(":") if part.isdigit()]
                duration = 0
                for part in parts:
                    duration = duration * 60 + int(part)
            else:
                duration = _int(length)
        return {
            "aid": _int(item.get("aid")),
            "bvid": _str(item.get("bvid")),
            "title": clean_html(item.get("title")),
            "cover": _pic(item.get("pic")),
            "duration": _int(duration),
            "pubdate": _int(item.get("pubdate") or item.get("created")),
            "play": _int(item.get("play"), _int(stat.get("view"))),
            "comment": _int(item.get("comment"), _int(stat.get("reply"))),
            "author": clean_html(item.get("author")),
        }

    async def user_dynamics(
        self,
        uid: int | str,
        *,
        limit: int = 10,
        offset: str = "",
    ) -> dict[str, Any]:
        uid_int = int(uid)
        params: dict[str, Any] = {
            "host_mid": uid_int,
            "timezone_offset": -480,
            "features": (
                "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,"
                "forwardListHidden,decorationCard,commentsNewVersion,"
                "onlyfansAssetsV2,ugcDelete,onlyfansQaCard"
            ),
            "platform": "web",
            "web_location": 333.1387,
        }
        if offset:
            params["offset"] = offset
        if not self.client.has_login_cookie():
            params.update(_DM_PARAMS)
        payload: dict[str, Any] = {}
        raw_items: list[Any] = []
        for attempt in range(2):
            payload = await self.client.request_json(
                "/x/polymer/web-dynamic/v1/feed/space",
                params,
                signed=True,
                referer=f"https://space.bilibili.com/{uid_int}/dynamic",
            )
            data = payload.get("data") or {}
            raw_items = list(data.get("items") or [])
            if raw_items or attempt == 1:
                break
            # 游客请求偶尔会返回 code=0 但 items 为空，换一套游客指纹再试一次
            self.client.reset_session()
            await asyncio.sleep(1.2)
        data = payload.get("data") or {}
        items = [
            parse_dynamic(item)
            for item in raw_items
            if isinstance(item, Mapping)
        ]
        return {
            "uid": uid_int,
            "items": items[: max(1, limit)],
            "offset": _str(data.get("offset")),
            "has_more": bool(data.get("has_more")),
        }

    async def dynamic(self, dynamic_id: str) -> dict[str, Any]:
        payload = await self.client.request_json(
            "/x/polymer/web-dynamic/v1/detail",
            {"id": dynamic_id},
            referer=f"https://www.bilibili.com/opus/{dynamic_id}",
        )
        item = (payload.get("data") or {}).get("item") or {}
        if not item:
            raise BiliError(-404, "动态不存在")
        return parse_dynamic(item)

    # ------------------------------------------------------------------ 直播
    async def live(self, ref: str, *, with_user: bool = True) -> dict[str, Any]:
        text = str(ref or "").strip()
        parsed_uid = parse_uid(text)
        room_id = 0
        uid = 0
        if "live.bilibili.com" in text:
            match = re.search(r"live\.bilibili\.com/(?:h5/)?(\d+)", text)
            if match:
                room_id = int(match.group(1))
        elif text.lower().startswith("room"):
            match = re.search(r"(\d+)", text)
            if match:
                room_id = int(match.group(1))
        elif parsed_uid is not None:
            uid = parsed_uid

        info: dict[str, Any] = {}
        if uid:
            old = await self.client.request_json(
                f"{LIVE_BASE}/room/v1/Room/getRoomInfoOld",
                {"mid": uid},
                referer=f"https://live.bilibili.com/{uid}",
            )
            old_data = old.get("data") or {}
            if _int(old_data.get("roomStatus")) == 0:
                return {
                    "exists": False,
                    "uid": uid,
                    "room_id": 0,
                    "live_status": 0,
                    "title": "",
                    "name": "",
                }
            room_id = _int(old_data.get("roomid"))
            info = {
                "title": clean_html(old_data.get("title")),
                "cover": _pic(old_data.get("cover")),
                "online": _int(old_data.get("online")),
                "live_status": _int(old_data.get("live_status")),
                "url": _str(old_data.get("url")),
            }
        if not room_id:
            raise BiliError(-400, "无法识别直播间，请发送房间号或 UP 主 UID")

        try:
            detail = await self.client.request_json(
                f"{LIVE_BASE}/room/v1/Room/get_info",
                {"room_id": room_id},
                referer=f"https://live.bilibili.com/{room_id}",
            )
        except BiliError as exc:
            if exc.code == 1:
                return {
                    "exists": False,
                    "uid": uid,
                    "room_id": room_id,
                    "live_status": 0,
                    "title": "",
                    "name": "",
                }
            raise
        data = detail.get("data") or {}
        if not data:
            return {
                "exists": False,
                "uid": uid,
                "room_id": room_id,
                "live_status": 0,
                "title": "",
                "name": "",
            }
        uid = uid or _int(data.get("uid"))
        name = ""
        if with_user and uid:
            try:
                user = await self.user(uid)
                name = user.get("name", "")
            except BiliError:
                name = ""
        return {
            "exists": True,
            "uid": uid,
            "name": name,
            "room_id": _int(data.get("room_id"), room_id),
            "short_id": _int(data.get("short_id")),
            "live_status": _int(data.get("live_status"), _int(info.get("live_status"))),
            "title": clean_html(data.get("title")) or info.get("title", ""),
            "cover": _pic(data.get("user_cover")) or info.get("cover", ""),
            "online": _int(data.get("online"), _int(info.get("online"))),
            "attention": _int(data.get("attention")),
            "area": clean_html(data.get("area_name")),
            "parent_area": clean_html(data.get("parent_area_name")),
            "live_time": _str(data.get("live_time")),
            "description": clean_html(data.get("description")),
            "url": f"https://live.bilibili.com/{_int(data.get('room_id'), room_id)}",
        }

    # ------------------------------------------------------------------ 榜单
    async def popular(self, *, limit: int = 10) -> list[dict[str, Any]]:
        payload = await self.client.request_json(
            "/x/web-interface/popular",
            {"ps": max(1, min(50, limit)), "pn": 1},
            referer="https://www.bilibili.com/v/popular/all",
        )
        data = payload.get("data") or {}
        return [
            normalize_video(item)
            for item in (data.get("list") or [])
            if isinstance(item, Mapping)
        ]

    async def ranking(self, rid: int = 0, *, limit: int = 10) -> list[dict[str, Any]]:
        payload = await self.client.request_json(
            "/x/web-interface/ranking/v2",
            {"rid": rid, "type": "all"},
            referer="https://www.bilibili.com/v/popular/rank/all",
        )
        data = payload.get("data") or {}
        return [
            normalize_video(item)
            for item in (data.get("list") or [])
            if isinstance(item, Mapping)
        ]

    async def hot_search(self, *, limit: int = 10) -> list[dict[str, Any]]:
        payload = await self.client.request_json(
            "/x/web-interface/search/square",
            {"limit": max(1, min(20, limit))},
            referer="https://www.bilibili.com/",
        )
        data = payload.get("data") or {}
        trending = data.get("trending") or {}
        return [
            {
                "keyword": clean_html(item.get("keyword")),
                "show_name": clean_html(item.get("show_name")),
                "heat": _int(item.get("heat_score")),
            }
            for item in (trending.get("list") or [])
            if isinstance(item, Mapping)
        ]

    # ------------------------------------------------------------------ 专栏 / 番剧 / 收藏
    async def article(self, cvid: int | str) -> dict[str, Any]:
        cvid_int = int(cvid)
        try:
            payload = await self.client.request_json(
                "/x/article/view",
                {"id": cvid_int},
                referer=f"https://www.bilibili.com/read/cv{cvid_int}",
            )
        except BiliError as first_error:
            # 正文接口偶发风控时，用卡片接口至少返回标题和摘要
            try:
                payload = await self.client.request_json(
                    "/x/article/cards",
                    {"ids": f"cv{cvid_int}", "web_location": "333.1305"},
                    no_cache=True,
                    retries=1,
                    referer=f"https://www.bilibili.com/read/cv{cvid_int}",
                )
            except BiliError:
                raise first_error
            card = (payload.get("data") or {}).get(f"cv{cvid_int}") or {}
            if not card:
                raise first_error
            author = card.get("author") or {}
            stats = card.get("stats") or {}
            return {
                "id": _int(card.get("id"), cvid_int),
                "title": clean_html(card.get("title")),
                "author": clean_html(author.get("name")),
                "publish_time": _int(card.get("publish_time") or card.get("ctime")),
                "stats": {
                    "view": _int(stats.get("view")),
                    "like": _int(stats.get("like")),
                    "favorite": _int(stats.get("favorite")),
                    "coin": _int(stats.get("coin")),
                    "share": _int(stats.get("share")),
                },
                "summary": truncate(clean_html(card.get("summary")), 800),
                "cover": _pic(card.get("banner_url")),
                "partial": True,
            }
        data = payload.get("data") or {}
        if not data:
            raise BiliError(-404, "专栏不存在")
        content = clean_html(data.get("content"))
        return {
            "id": _int(data.get("id"), cvid_int),
            "title": clean_html(data.get("title")),
            "author": clean_html(data.get("author_name")),
            "publish_time": _int(data.get("publish_time")),
            "stats": {
                "view": _int(data.get("view")),
                "like": _int(data.get("like")),
                "favorite": _int(data.get("favorite")),
                "coin": _int(data.get("coin")),
                "share": _int(data.get("share")),
            },
            "summary": truncate(data.get("summary") or content, 800),
            "cover": _pic(data.get("banner_url")),
            "partial": False,
        }

    async def bangumi(self, ref: str) -> dict[str, Any]:
        parsed = parse_bangumi_ref(ref)
        if not parsed:
            raise BiliError(-400, "无法识别番剧，请发送 ss 号、ep 号或番剧链接")
        key, value = parsed
        payload = await self.client.request_json(
            "/pgc/view/web/season",
            {key: value},
            referer=f"https://www.bilibili.com/bangumi/play/{key}{value}",
        )
        data = payload.get("result") or payload.get("data") or {}
        if not data:
            raise BiliError(-404, "番剧不存在")
        episodes = data.get("episodes") or []
        areas = data.get("areas") or []
        return {
            "season_id": _int(data.get("season_id")),
            "title": clean_html(data.get("title")),
            "subtitle": clean_html(data.get("subtitle")),
            "cover": _pic(data.get("cover")),
            "score": (data.get("rating") or {}).get("score") or 0,
            "total": len(episodes),
            "area": clean_html(areas[0].get("name")) if areas and isinstance(areas[0], Mapping) else "",
            "summary": clean_html(data.get("evaluate")),
            "episodes": [
                {
                    "id": _int(ep.get("id")),
                    "title": clean_html(ep.get("title")),
                    "bvid": _str(ep.get("bvid")),
                    "duration": _int(ep.get("duration")),
                }
                for ep in episodes[:20]
                if isinstance(ep, Mapping)
            ],
        }

    async def fav(self, media_id: int | str, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
        media_id_int = int(media_id)
        payload = await self.client.request_json(
            "/x/v3/fav/resource/list",
            {
                "media_id": media_id_int,
                "ps": max(1, min(40, limit)),
                "pn": max(1, page),
                "platform": "web",
            },
            referer=f"https://www.bilibili.com/medialist/detail/ml{media_id_int}",
        )
        data = payload.get("data") or {}
        info = data.get("info") or {}
        if not info:
            raise BiliError(-404, "收藏夹不存在或不可见")
        medias = []
        for media in data.get("medias") or []:
            if not isinstance(media, Mapping):
                continue
            medias.append(
                {
                    "id": _int(media.get("id")),
                    "title": clean_html(media.get("title")),
                    "bvid": _str(media.get("bvid")),
                    "cover": _pic(media.get("cover")),
                    "duration": _int(media.get("duration")),
                    "type": _int(media.get("type")),
                }
            )
        return {
            "id": _int(info.get("id"), media_id_int),
            "title": clean_html(info.get("title")),
            "media_count": _int(info.get("media_count")),
            "items": medias,
        }

    async def nav(self) -> dict[str, Any]:
        return await self.client.nav_info()
