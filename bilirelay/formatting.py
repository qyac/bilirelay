"""把 B 站数据格式化为适合聊天窗口阅读的纯文本。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

CST = timezone(timedelta(hours=8))
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")


def human_count(value: Any) -> str:
    """把播放量/粉丝数格式化为 1.2万 / 3.4亿。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "0"
    if number < 0:
        return str(number)
    if number >= 100_000_000:
        return f"{number / 100_000_000:.1f}亿".replace(".0亿", "亿")
    if number >= 10_000:
        return f"{number / 10_000:.1f}万".replace(".0万", "万")
    return str(number)


def human_duration(value: Any) -> str:
    """秒数或 ``MM:SS`` / ``HH:MM:SS`` 统一成 ``MM:SS``。"""
    if value is None or value == "":
        return "未知"
    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return value
        if len(numbers) == 2:
            return f"{numbers[0]:02d}:{numbers[1]:02d}"
        if len(numbers) == 3:
            return f"{numbers[0]}:{numbers[1]:02d}:{numbers[2]:02d}"
        return value
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    hours, rem = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_timestamp(timestamp: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        return "未知时间"
    if value <= 0:
        return "未知时间"
    return datetime.fromtimestamp(value, tz=CST).strftime(fmt)


def clean_html(value: Any) -> str:
    """去掉搜索结果里的 ``<em class="keyword">`` 等标签。"""
    text = _TAG_RE.sub("", str(value or ""))
    text = html.unescape(text)
    return _SPACE_RE.sub(" ", text).strip()


def truncate(value: Any, limit: int = 300, suffix: str = "…") -> str:
    text = str(value or "").strip()
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - len(suffix))] + suffix
    return text


def absolute_url(url: Any) -> str:
    text = str(url or "").strip()
    if text.startswith("//"):
        return "https:" + text
    return text


def _stat(video: Mapping[str, Any]) -> Mapping[str, Any]:
    return video.get("stat") or {}


def format_video(video: Mapping[str, Any], *, detailed: bool = True) -> str:
    """格式化单个视频。"""
    title = truncate(clean_html(video.get("title")), 160)
    owner = video.get("owner") or {}
    stat = _stat(video)
    lines = [f"📺 {title}"]
    if owner.get("name"):
        lines.append(f"👤 {owner['name']}（UID {owner.get('mid', '?')}）")
    lines.append(
        "▶ {play}  💬 {danmaku}  ⭐ {favorite}  🪙 {coin}".format(
            play=human_count(stat.get("view")),
            danmaku=human_count(stat.get("danmaku")),
            favorite=human_count(stat.get("favorite")),
            coin=human_count(stat.get("coin")),
        )
    )
    lines.append(
        f"⏱ {human_duration(video.get('duration'))}  "
        f"📅 {format_timestamp(video.get('pubdate'), '%Y-%m-%d')}"
    )
    if video.get("tname"):
        lines.append(f"🏷 {video['tname']}")
    if video.get("bvid"):
        lines.append(f"🔗 https://www.bilibili.com/video/{video['bvid']}")
    desc = truncate(clean_html(video.get("desc")), 180 if detailed else 60)
    if desc:
        lines.append(f"📝 {desc}")
    return "\n".join(lines)


def format_video_list(videos: Iterable[Mapping[str, Any]], *, limit: int = 10) -> str:
    lines: list[str] = []
    for index, video in enumerate(videos, 1):
        if index > limit:
            break
        stat = _stat(video)
        title = truncate(clean_html(video.get("title")), 90)
        views = stat.get("view") or video.get("play")
        meta = " · ".join(
            part
            for part in (
                human_count(views) + "播放" if views else "",
                human_duration(video.get("duration")),
                format_timestamp(video.get("pubdate"), "%m-%d"),
            )
            if part
        )
        lines.append(f"{index}. {title}")
        if meta:
            lines.append(f"   {meta}")
        if video.get("bvid"):
            lines.append(f"   https://www.bilibili.com/video/{video['bvid']}")
    return "\n".join(lines)


def format_user(user: Mapping[str, Any]) -> str:
    lines = [f"👤 {user.get('name') or '未知用户'}（UID {user.get('uid', '?')}）"]
    meta = []
    if user.get("fans") is not None:
        meta.append(f"粉丝 {human_count(user.get('fans'))}")
    if user.get("following") is not None:
        meta.append(f"关注 {human_count(user.get('following'))}")
    if user.get("archive_count"):
        meta.append(f"投稿 {human_count(user.get('archive_count'))}")
    if user.get("level"):
        meta.append(f"Lv{user['level']}")
    if meta:
        lines.append(" · ".join(meta))
    if user.get("official"):
        lines.append(f"✅ {user['official']}")
    if user.get("sign"):
        lines.append(f"📝 {truncate(clean_html(user['sign']), 180)}")
    if user.get("uid"):
        lines.append(f"🔗 https://space.bilibili.com/{user['uid']}")
    return "\n".join(lines)


def format_dynamic(dynamic: Mapping[str, Any], *, include_author: bool = True) -> str:
    lines: list[str] = []
    head = "📝 "
    if include_author and dynamic.get("author"):
        head += f"{dynamic['author']} · "
    head += format_timestamp(dynamic.get("pub_ts"), "%m-%d %H:%M")
    lines.append(head)
    text = truncate(clean_html(dynamic.get("text")), 240)
    if text:
        lines.append(text)
    archive = dynamic.get("archive") or {}
    if archive.get("title"):
        lines.append(
            f"📺 {truncate(clean_html(archive['title']), 100)}"
            + (f"（{archive['duration']}）" if archive.get("duration") else "")
        )
        if archive.get("bvid"):
            lines.append(f"🔗 https://www.bilibili.com/video/{archive['bvid']}")
    article = dynamic.get("article") or {}
    if article.get("title"):
        lines.append(f"📰 {truncate(clean_html(article['title']), 100)}")
        if article.get("id"):
            lines.append(f"🔗 https://www.bilibili.com/read/cv{article['id']}")
    live = dynamic.get("live") or {}
    if live.get("title"):
        lines.append(f"🔴 直播：{truncate(clean_html(live['title']), 100)}")
        if live.get("room_id"):
            lines.append(f"🔗 https://live.bilibili.com/{live['room_id']}")
    if dynamic.get("images"):
        lines.append(f"🖼 图片 {len(dynamic['images'])} 张")
    if not text and not archive.get("title") and not article.get("title") and not live.get("title"):
        lines.append("（这条动态没有可展示的文字内容）")
    if dynamic.get("url"):
        lines.append(f"🔗 {dynamic['url']}")
    return "\n".join(lines)


def format_live(live: Mapping[str, Any]) -> str:
    status = int(live.get("live_status") or 0)
    icon = "🔴 直播中" if status == 1 else ("🎬 轮播中" if status == 2 else "⚫ 未开播")
    lines = [f"{icon}  {live.get('title') or '未命名直播间'}"]
    if live.get("name"):
        lines.append(f"👤 {live['name']}")
    meta = []
    if live.get("online"):
        meta.append(f"人气 {human_count(live['online'])}")
    if live.get("area"):
        meta.append(str(live["area"]))
    if live.get("live_time") and status == 1:
        meta.append(f"开播于 {live['live_time']}")
    if meta:
        lines.append(" · ".join(meta))
    if live.get("room_id"):
        lines.append(f"🔗 https://live.bilibili.com/{live['room_id']}")
    return "\n".join(lines)


def format_comment_list(comments: Iterable[Mapping[str, Any]], *, limit: int = 10) -> str:
    lines: list[str] = []
    for index, comment in enumerate(comments, 1):
        if index > limit:
            break
        name = comment.get("uname") or "匿名"
        text = truncate(clean_html(comment.get("message")), 160)
        suffix = f"（👍 {human_count(comment.get('like'))}）" if comment.get("like") else ""
        lines.append(f"{index}. {name}{suffix}：{text}")
    return "\n".join(lines)


def format_search(
    keyword: str,
    search_type: str,
    items: Iterable[Mapping[str, Any]],
    *,
    limit: int = 10,
) -> str:
    type_labels = {
        "video": "视频",
        "user": "用户",
        "bili_user": "用户",
        "live": "直播",
        "bangumi": "番剧",
        "media_bangumi": "番剧",
        "media_ft": "影视",
        "article": "专栏",
    }
    lines = [
        f"🔍 B 站搜索「{truncate(keyword, 40)}」"
        f"（{type_labels.get(search_type, search_type)}）"
    ]
    index = 0
    for item in items:
        if index >= limit:
            break
        index += 1
        if search_type == "video":
            lines.append(
                f"{index}. {truncate(clean_html(item.get('title')), 80)}"
            )
            meta = " · ".join(
                part
                for part in (
                    str(item.get("author") or ""),
                    human_count(item.get("play")) + "播放" if item.get("play") else "",
                    human_duration(item.get("duration")),
                )
                if part
            )
            if meta:
                lines.append(f"   {meta}")
            if item.get("bvid"):
                lines.append(f"   https://www.bilibili.com/video/{item['bvid']}")
        elif search_type in ("user", "bili_user"):
            lines.append(
                f"{index}. {truncate(clean_html(item.get('uname')), 60)}"
                f"（UID {item.get('mid')}）"
            )
            meta = " · ".join(
                part
                for part in (
                    f"粉丝 {human_count(item.get('fans'))}" if item.get("fans") else "",
                    truncate(clean_html(item.get("usign")), 60),
                )
                if part
            )
            if meta:
                lines.append(f"   {meta}")
        elif search_type == "live":
            lines.append(f"{index}. {truncate(clean_html(item.get('title')), 80)}")
            meta = " · ".join(
                part
                for part in (
                    str(item.get("uname") or ""),
                    f"人气 {human_count(item.get('online'))}" if item.get("online") else "",
                    str(item.get("area_v2_name") or ""),
                )
                if part
            )
            if meta:
                lines.append(f"   {meta}")
            if item.get("roomid"):
                lines.append(f"   https://live.bilibili.com/{item['roomid']}")
        elif search_type == "article":
            lines.append(f"{index}. {truncate(clean_html(item.get('title')), 80)}")
            if item.get("id"):
                lines.append(f"   https://www.bilibili.com/read/cv{item['id']}")
        elif search_type in ("bangumi", "media_bangumi", "media_ft"):
            lines.append(f"{index}. {truncate(clean_html(item.get('title')), 80)}")
            score = (item.get("media_score") or {}).get("score")
            meta = " · ".join(
                part
                for part in (
                    str(score) + " 分" if score else "",
                    str(item.get("season_type_name") or ""),
                )
                if part
            )
            if meta:
                lines.append(f"   {meta}")
            if item.get("season_id"):
                lines.append(f"   https://www.bilibili.com/bangumi/play/ss{item['season_id']}")
    if index == 0:
        lines.append("没有找到结果。")
    return "\n".join(lines)


def format_article(article: Mapping[str, Any]) -> str:
    lines = [f"📰 {truncate(clean_html(article.get('title')), 160)}"]
    if article.get("author"):
        lines.append(f"✍️ {article['author']}")
    meta = []
    if article.get("publish_time"):
        meta.append(format_timestamp(article["publish_time"], "%Y-%m-%d"))
    stats = article.get("stats") or {}
    for key, label in (("view", "阅读"), ("like", "点赞"), ("favorite", "收藏")):
        if stats.get(key):
            meta.append(f"{label} {human_count(stats[key])}")
    if meta:
        lines.append(" · ".join(meta))
    if article.get("id"):
        lines.append(f"🔗 https://www.bilibili.com/read/cv{article['id']}")
    summary = truncate(clean_html(article.get("summary")), 500)
    if summary:
        lines.append(f"📝 {summary}")
    if article.get("partial"):
        lines.append("ℹ️ 正文接口被风控，仅获取到卡片摘要。")
    return "\n".join(lines)


def format_bangumi(bangumi: Mapping[str, Any]) -> str:
    lines = [f"📺 {truncate(clean_html(bangumi.get('title')), 160)}"]
    if bangumi.get("subtitle"):
        lines.append(f"🏷 {truncate(clean_html(bangumi['subtitle']), 120)}")
    meta = []
    if bangumi.get("score"):
        meta.append(f"{bangumi['score']} 分")
    if bangumi.get("total"):
        meta.append(f"共 {bangumi['total']} 话")
    if bangumi.get("area"):
        meta.append(str(bangumi["area"]))
    if meta:
        lines.append(" · ".join(meta))
    if bangumi.get("season_id"):
        lines.append(
            f"🔗 https://www.bilibili.com/bangumi/play/ss{bangumi['season_id']}"
        )
    summary = truncate(clean_html(bangumi.get("summary")), 400)
    if summary:
        lines.append(f"📝 {summary}")
    return "\n".join(lines)


def format_fav(fav: Mapping[str, Any], *, limit: int = 10) -> str:
    lines = [f"⭐ 收藏夹：{truncate(clean_html(fav.get('title')), 80)}"]
    if fav.get("media_count") is not None:
        lines.append(f"共 {human_count(fav.get('media_count'))} 个内容")
    for index, media in enumerate((fav.get("medias") or [])[:limit], 1):
        lines.append(f"{index}. {truncate(clean_html(media.get('title')), 80)}")
        if media.get("bvid"):
            lines.append(f"   https://www.bilibili.com/video/{media['bvid']}")
        elif media.get("id"):
            lines.append(f"   https://www.bilibili.com/read/cv{media['id']}")
    return "\n".join(lines)


def format_hot(items: Iterable[Mapping[str, Any]], *, limit: int = 10) -> str:
    lines = ["🔥 B 站热门"]
    index = 0
    for item in items:
        if index >= limit:
            break
        index += 1
        lines.append(f"{index}. {truncate(clean_html(item.get('title')), 80)}")
        if item.get("owner"):
            lines.append(f"   {item['owner'].get('name', '')}")
        if item.get("bvid"):
            lines.append(f"   https://www.bilibili.com/video/{item['bvid']}")
    return "\n".join(lines)


def format_rank(items: Iterable[Mapping[str, Any]], *, limit: int = 10) -> str:
    lines = ["🏆 B 站排行榜"]
    index = 0
    for item in items:
        if index >= limit:
            break
        index += 1
        stat = item.get("stat") or {}
        lines.append(f"{index}. {truncate(clean_html(item.get('title')), 80)}")
        lines.append(
            f"   {item.get('owner', {}).get('name', '')} · "
            f"{human_count(stat.get('view'))}播放"
        )
        if item.get("bvid"):
            lines.append(f"   https://www.bilibili.com/video/{item['bvid']}")
    return "\n".join(lines)


def format_subscriptions(items: Iterable[Mapping[str, Any]]) -> str:
    lines = ["🔔 当前会话的 B 站订阅"]
    count = 0
    for item in items:
        count += 1
        types = item.get("types") or []
        type_names = {"video": "投稿", "dynamic": "动态", "live": "直播"}
        label = " / ".join(type_names.get(t, t) for t in types)
        lines.append(
            f"{count}. {item.get('name') or 'UID ' + str(item.get('uid'))}"
            f"（UID {item.get('uid')}）— {label}"
        )
    if count == 0:
        lines.append("还没有订阅，使用 /bili sub add <UID> 添加。")
    return "\n".join(lines)
