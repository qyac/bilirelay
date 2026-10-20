"""Neko BiliRelay — 让 AstrBot 完整接入 Bilibili。

包含：LLM 工具、查询指令、UP 主动态/投稿/开播订阅推送、Cookie 与扫码登录。
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Iterable

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

try:  # AstrBot < 4.26 没有 Plugin Pages Web API
    from astrbot.api.web import error_response, json_response, request

    WEB_API_SUPPORTED = True
except ImportError:  # pragma: no cover - 兼容旧版本
    error_response = json_response = request = None  # type: ignore[assignment]
    WEB_API_SUPPORTED = False

from .bilirelay.api import RANK_AREAS, SEARCH_TYPES, BiliAPI
from .bilirelay.auth import AuthManager, CredentialStore
from .bilirelay.autoreply import AutoReplyEngine
from .bilirelay.client import BiliClient
from .bilirelay.command_args import (
    parse_sub_types,
    split_args,
    strip_command,
    to_int,
)
from .bilirelay.errors import BiliError
from .bilirelay.formatting import (
    format_article,
    format_bangumi,
    format_comment_list,
    format_dynamic,
    format_fav,
    format_hot,
    format_live,
    format_rank,
    format_search,
    format_subscriptions,
    format_timestamp,
    format_user,
    format_video,
    format_video_list,
    human_duration,
    truncate,
)
from .bilirelay.refs import (
    parse_article_ref,
    parse_dynamic_ref,
    parse_uid,
)
from .bilirelay.subscriptions import (
    ALL_TYPES,
    Subscription,
    SubscriptionPoller,
    SubscriptionStore,
)

PLUGIN_NAME = "astrbot_plugin_bilirelay"
VERSION = "1.3.0"
GROUP_NAMES = {"bili", "b站", "哔哩哔哩"}

TOOL_NAMES = (
    "bilibili_search",
    "bilibili_video",
    "bilibili_video_summary",
    "bilibili_video_subtitle",
    "bilibili_video_comments",
    "bilibili_video_danmaku",
    "bilibili_user",
    "bilibili_user_videos",
    "bilibili_user_dynamics",
    "bilibili_live",
    "bilibili_hot",
    "bilibili_rank",
    "bilibili_article",
    "bilibili_bangumi",
    "bilibili_fav",
    "bilibili_send_dm",
)

HELP_TEXT = """📺 Neko BiliRelay — B 站指令

🔍 内容查询
/bili search <关键词> [类型]   搜索（类型：视频/用户/直播/番剧/专栏）
/bili video <BV/av/链接>       视频详情
/bili summary <BV/av/链接>     视频 AI 总结（需登录）
/bili subtitle <BV/av/链接>    视频字幕（需登录）
/bili comments <BV/av/链接>    热门评论
/bili danmaku <BV/av/链接>     弹幕
/bili article <cv号/链接>      专栏
/bili bangumi <ss/ep/链接>     番剧信息
/bili fav <收藏夹ID>           公开收藏夹

👤 UP 主
/bili up <UID/空间链接>         UP 主资料 + 最近投稿
/bili videos <UID> [页码]       UP 主投稿列表
/bili dynamics <UID> [数量]     UP 主最新动态
/bili live <UID/房间号/链接>    直播状态

📈 榜单
/bili hot                      热门视频
/bili hot search               热搜
/bili rank [分区]              排行榜

🔔 订阅推送
/bili sub add <UID> [类型]     订阅（类型：视频/动态/直播，默认全部）
/bili sub del <UID>            取消订阅
/bili sub list                 查看本会话订阅
/bili sub check                立即检查一轮

✉️ 主动私信
/bili send <UID/self> <文本>   用 B 站账号主动发一条私信

🤖 自动回复（管理员）
/bili autoreply status         查看自动回复状态
/bili autoreply on|off         启动 / 停止自动回复任务
/bili autoreply test <文本>    预览一条自动回复（不发送）
/bili autoreply reset          清空去重状态并重新建立基线

🔐 账号
/bili login                    登录状态；未登录时发送扫码二维码
/bili whoami                   当前账号
/bili help                     显示本帮助

提示：登录、订阅管理和自动回复状态在 AstrBot WebUI 的插件页面中。"""


def _cfg_number(value: Any, default: int | float, cast: type = int) -> int | float:
    """容错读取数值配置，避免手动改 JSON 写错类型导致插件加载失败。"""
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


# WebUI 可编辑配置：key -> (类型, 默认值, 最小值/选项, 最大值)
CONFIG_SPEC: dict[str, dict[str, Any]] = {
    "enable_llm_tools": {"type": "bool", "default": True},
    "enable_subscriptions": {"type": "bool", "default": True},
    "subscription_interval": {"type": "int", "default": 5, "min": 1, "max": 1440},
    "max_subscriptions": {"type": "int", "default": 20, "min": 1, "max": 200},
    "push_cover": {"type": "bool", "default": False},
    "login_qr_in_chat": {"type": "bool", "default": True},
    "request_interval": {"type": "float", "default": 0.45, "min": 0, "max": 10},
    "timeout": {"type": "int", "default": 15, "min": 1, "max": 120},
    "cache_ttl": {"type": "int", "default": 90, "min": 0, "max": 3600},
    "max_reply_chars": {"type": "int", "default": 1800, "min": 200, "max": 10000},
    "send_dm_admin_only": {"type": "bool", "default": True},
    "send_dm_dry_run": {"type": "bool", "default": False},
    "enable_llm_send_dm": {"type": "bool", "default": False},
    "llm_send_dm_whitelist": {"type": "string", "default": ""},
    "subscription_dm_uid": {"type": "string", "default": ""},
    "subscription_dm_mode": {"type": "string", "default": "off", "options": ["off", "both", "only"]},
    "enable_auto_reply": {"type": "bool", "default": False},
    "auto_reply_comments": {"type": "bool", "default": True},
    "auto_reply_dms": {"type": "bool", "default": False},
    "auto_reply_dry_run": {"type": "bool", "default": False},
    "auto_reply_max_chars": {"type": "int", "default": 200, "min": 20, "max": 1000},
    "auto_reply_reply_interval": {"type": "float", "default": 3, "min": 0, "max": 60},
    "comment_targets": {"type": "string", "default": ""},
    "comment_auto_videos": {"type": "bool", "default": True},
    "comment_video_limit": {"type": "int", "default": 5, "min": 1, "max": 20},
    "comment_include_replies": {"type": "bool", "default": False},
    "comment_poll_interval": {"type": "int", "default": 180, "min": 60, "max": 86400},
    "comment_max_per_round": {"type": "int", "default": 3, "min": 1, "max": 10},
    "comment_cooldown_minutes": {"type": "int", "default": 30, "min": 1, "max": 1440},
    "comment_max_age_minutes": {"type": "int", "default": 180, "min": 1, "max": 10080},
    "comment_min_chars": {"type": "int", "default": 2, "min": 1, "max": 100},
    "comment_ignore_keywords": {"type": "string", "default": ""},
    "comment_reply_mode": {"type": "string", "default": "llm", "options": ["llm", "template"]},
    "comment_template": {"type": "text", "default": "感谢你的评论，{user}！"},
    "dm_poll_interval": {"type": "int", "default": 120, "min": 60, "max": 86400},
    "dm_max_per_round": {"type": "int", "default": 3, "min": 1, "max": 10},
    "dm_cooldown_minutes": {"type": "int", "default": 10, "min": 1, "max": 1440},
    "dm_max_age_minutes": {"type": "int", "default": 180, "min": 1, "max": 10080},
    "dm_min_chars": {"type": "int", "default": 1, "min": 1, "max": 100},
    "dm_ignore_keywords": {"type": "string", "default": ""},
    "dm_context_messages": {"type": "int", "default": 6, "min": 0, "max": 20},
    "dm_reply_mode": {"type": "string", "default": "llm", "options": ["llm", "template"]},
    "dm_template": {"type": "text", "default": "你好，{user}！"},
    "dm_allow_all": {"type": "bool", "default": False},
    "dm_whitelist": {"type": "string", "default": ""},
    "dm_blacklist": {"type": "string", "default": ""},
}


def _cfg_number(value: Any, default: float, cast: type = float) -> float:
    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(default)


def _coerce_config_value(spec: dict[str, Any], value: Any) -> Any:
    kind = spec["type"]
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind in ("int", "float"):
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            return spec["default"]
        if "min" in spec:
            number = max(spec["min"], number)
        if "max" in spec:
            number = min(spec["max"], number)
        return number
    text = str(value or "")
    options = spec.get("options")
    if options and text not in options:
        return spec["default"]
    return text


class BiliRelayPlugin(Star):
    """AstrBot B 站中继插件。"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.client = BiliClient(
            cookie=str(self.config.get("cookie", "") or ""),
            timeout=max(
                1.0, float(_cfg_number(self.config.get("timeout", 15), 15, float))
            ),
            request_interval=float(
                _cfg_number(self.config.get("request_interval", 0.45), 0.45, float)
            ),
            cache_ttl=int(_cfg_number(self.config.get("cache_ttl", 90), 90, int)),
        )
        self.api = BiliAPI(self.client)
        self.auth = AuthManager(
            self.client,
            CredentialStore(self.data_dir / "credential.json"),
            config_cookie=str(self.config.get("cookie", "") or ""),
        )
        self.subs = SubscriptionStore(
            self.data_dir / "subscriptions.json",
            max_per_session=int(
                _cfg_number(self.config.get("max_subscriptions", 20), 20, int)
            ),
        )
        self.poller = SubscriptionPoller(
            self.api,
            self.subs,
            self._send_push,
            interval_seconds=int(
                _cfg_number(self.config.get("subscription_interval", 5), 5, int)
            )
            * 60,
            notify=self._enabled_push_types(),
        )
        self.autoreply = AutoReplyEngine(
            self.context,
            self.api,
            self.client,
            self.config,
            self.data_dir,
            logger_=self.logger,
        )
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._register_web_apis()
        self.logger.info("Neko BiliRelay %s 已加载，数据目录：%s", VERSION, self.data_dir)

    # --------------------------------------------------------------- 生命周期
    async def initialize(self) -> None:
        try:
            await self.auth.load()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("加载 B 站登录态失败：%s", exc)
        try:
            await self._apply_tool_toggles()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("应用 LLM 工具开关失败：%s", exc)
        if bool(self.config.get("enable_subscriptions", True)):
            self.poller.start()
        if bool(self.config.get("enable_auto_reply", False)):
            ok, message = self.autoreply.start()
            self.logger.info("自动回复：%s（%s）", "已启动" if ok else "未启动", message)

    async def terminate(self) -> None:
        await self.autoreply.stop()
        await self.poller.stop()
        for task in list(self._bg_tasks):
            task.cancel()
        self._bg_tasks.clear()
        await self.client.close()
        self.logger.info("Neko BiliRelay 已卸载")

    # ------------------------------------------------------------------ 配置
    def _clip(self, text: str) -> str:
        limit = max(
            200,
            int(_cfg_number(self.config.get("max_reply_chars", 1800), 1800, int)),
        )
        if len(text) <= limit:
            return text
        return text[: limit - 20].rstrip() + "\n…（内容过长已截断）"

    def _enabled_push_types(self) -> list[str]:
        raw = self.config.get("subscription_notify") or {}
        if not isinstance(raw, dict):
            return list(ALL_TYPES)
        return [key for key in ALL_TYPES if bool(raw.get(key, True))] or list(ALL_TYPES)

    def _public_config(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, spec in CONFIG_SPEC.items():
            values[key] = self.config.get(key, spec["default"])
        notify = self.config.get("subscription_notify") or {}
        values["subscription_notify"] = {
            key: bool(notify.get(key, True)) for key in ("video", "dynamic", "live")
        }
        return {
            "values": values,
            "cookie_configured": bool(str(self.config.get("cookie", "") or "").strip()),
            "version": VERSION,
        }

    async def _apply_runtime_config(self) -> None:
        """保存设置后尽量让运行时立刻生效（不让用户必须重启）。"""
        self.client.request_interval = float(
            _cfg_number(self.config.get("request_interval", 0.45), 0.45, float)
        )
        self.client.cache_ttl = int(
            _cfg_number(self.config.get("cache_ttl", 90), 90, int)
        )
        self.poller.interval_seconds = max(
            60,
            int(_cfg_number(self.config.get("subscription_interval", 5), 5, int)) * 60,
        )
        self.poller.notify = set(self._enabled_push_types())
        self.subs.max_per_session = max(
            1, int(_cfg_number(self.config.get("max_subscriptions", 20), 20, int))
        )
        if bool(self.config.get("enable_subscriptions", True)):
            self.poller.start()
        else:
            await self.poller.stop()
        if bool(self.config.get("enable_auto_reply", False)):
            await self.autoreply.stop()
            self.autoreply.start()
        else:
            await self.autoreply.stop()
        await self._apply_tool_toggles()

    def _tool_enabled(self, name: str) -> bool:
        if not bool(self.config.get("enable_llm_tools", True)):
            return False
        if name == "bilibili_send_dm" and not bool(self.config.get("enable_llm_send_dm", False)):
            return False
        raw = self.config.get("llm_tools") or {}
        if isinstance(raw, dict) and name in raw:
            return bool(raw[name])
        return True

    async def _apply_tool_toggles(self) -> None:
        for name in TOOL_NAMES:
            enabled = self._tool_enabled(name)
            try:
                async_name = "activate_llm_tool_async" if enabled else "deactivate_llm_tool_async"
                async_method = getattr(self.context, async_name, None)
                if async_method is not None:
                    await async_method(name)
                    continue
                sync_name = "activate_llm_tool" if enabled else "deactivate_llm_tool"
                sync_method = getattr(self.context, sync_name, None)
                if sync_method is not None:
                    sync_method(name)
                    continue
                # 最后兜底：直接修改工具对象的 active 标记
                tool = self.context.provider_manager.llm_tools.get_func(name)
                if tool is not None:
                    tool.active = enabled
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("切换工具 %s 状态失败：%s", name, exc)

    # ------------------------------------------------------------------ 推送
    async def _resolve_dm_uid(self, ref: str) -> int:
        """把 ``self`` / ``me`` / UID 解析成接收者 UID。"""
        text = str(ref or "").strip()
        if text.lower() in ("self", "me", "我", "自己", "自己号"):
            uid = int((self.auth.user or {}).get("uid") or 0)
            if not uid:
                uid = int(self.client.cookies.get("DedeUserID") or 0)
            if not uid:
                try:
                    await self.auth.refresh_user(force=True)
                except Exception:  # noqa: BLE001
                    pass
                uid = int((self.auth.user or {}).get("uid") or 0)
            return uid
        return parse_uid(text) or 0

    async def _send_bili_dm(self, uid: int, text: str) -> None:
        """主动发一条 B 站私信（文本）。"""
        await self.api.send_dm(uid, truncate(text, 500, suffix=""))

    async def _send_push(self, umo: str, text: str, cover_url: str = "") -> None:
        """订阅推送：按配置转发到 B 站私信，或继续发到聊天。"""
        mode = str(self.config.get("subscription_dm_mode", "off") or "off").lower()
        dm_uid = await self._resolve_dm_uid(str(self.config.get("subscription_dm_uid", "") or ""))
        if dm_uid and mode in ("both", "only"):
            if bool(self.config.get("send_dm_dry_run", False)):
                self.logger.info("[dry-run] 订阅推送将转发到 B 站私信 UID %s：%s", dm_uid, truncate(text, 200))
                if mode == "only":
                    mode = "both"  # dry-run 的 only 模式回退到聊天，避免完全静音
            else:
                try:
                    await self._send_bili_dm(dm_uid, text)
                    self.logger.info("订阅推送已转发到 B 站私信 UID %s", dm_uid)
                    if mode == "only":
                        return
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("订阅推送转发 B 站私信失败，回退到聊天：%s", exc)
        chain = MessageChain().message(self._clip(text))
        if cover_url and bool(self.config.get("push_cover", False)):
            try:
                import astrbot.api.message_components as Comp

                chain.chain.append(Comp.Image.fromURL(cover_url))
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("添加封面图失败：%s", exc)
        await self.context.send_message(umo, chain)

    # ------------------------------------------------------------------ 参数
    def _args(self, event: AstrMessageEvent, sub_names: Iterable[str]) -> str:
        return strip_command(event.get_message_str(), GROUP_NAMES, sub_names)

    def _error(self, exc: Exception) -> str:
        if isinstance(exc, BiliError):
            return f"❌ {exc.user_message}"
        self.logger.exception("B 站指令执行失败")
        return f"❌ 执行失败：{exc}"

    # ------------------------------------------------------------------ 指令
    @filter.command_group("bili", alias={"b站", "哔哩哔哩"})
    def bili(self) -> None:
        pass

    @bili.command("help", alias={"帮助", "菜单"})
    async def bili_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @bili.command("search", alias={"搜索", "搜"})
    async def bili_search(self, event: AstrMessageEvent):
        raw = self._args(event, {"search", "搜索", "搜"})
        parts = split_args(raw)
        if not parts:
            yield event.plain_result("用法：/bili search <关键词> [视频/用户/直播/番剧/专栏]")
            return
        search_type = "video"
        if len(parts) > 1 and parts[-1].lower() in SEARCH_TYPES:
            search_type = parts.pop().lower()
        keyword = " ".join(parts).strip()
        if not keyword:
            yield event.plain_result("请输入搜索关键词。")
            return
        try:
            result = await self.api.search(keyword, search_type, limit=10)
            text = format_search(
                keyword,
                result.get("type", search_type),
                result.get("items") or [],
                limit=10,
            )
            if result.get("total"):
                text += f"\n\n共 {result['total']} 条结果，仅展示前 10 条。"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("video", alias={"视频", "bv"})
    async def bili_video(self, event: AstrMessageEvent):
        raw = self._args(event, {"video", "视频", "bv"})
        if not raw:
            yield event.plain_result("用法：/bili video <BV号/av号/视频链接>")
            return
        try:
            video = await self.api.video(raw.split()[0])
            text = format_video(video)
            if video.get("videos", 1) > 1:
                text += f"\n📚 共 {video['videos']} P"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("summary", alias={"总结", "摘要"})
    async def bili_summary(self, event: AstrMessageEvent):
        raw = self._args(event, {"summary", "总结", "摘要"})
        if not raw:
            yield event.plain_result("用法：/bili summary <BV号/av号/视频链接>")
            return
        try:
            result = await self.api.video_summary(raw.split()[0])
            if not result.get("available"):
                text = "🧠 该视频暂无 AI 总结（可能需要登录，或视频没有可识别的语音）。"
            else:
                lines = [
                    f"🧠 {truncate(result['video'].get('title'), 80)} 的 AI 总结",
                    result.get("summary") or "（无摘要正文）",
                ]
                if result.get("outline"):
                    lines.append("\n📌 分段提纲：")
                    for section in result["outline"][:12]:
                        stamp = human_duration(section.get("timestamp"))
                        lines.append(f"[{stamp}] {section.get('title') or ''}")
                        for point in (section.get("points") or [])[:4]:
                            if point.get("content"):
                                lines.append(f"  · {point['content']}")
                lines.append(f"\n🔗 https://www.bilibili.com/video/{result['video'].get('bvid', '')}")
                text = "\n".join(lines)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("subtitle", alias={"字幕"})
    async def bili_subtitle(self, event: AstrMessageEvent):
        raw = self._args(event, {"subtitle", "字幕"})
        parts = split_args(raw)
        if not parts:
            yield event.plain_result("用法：/bili subtitle <BV号/av号/视频链接> [语言]")
            return
        lang = parts[1] if len(parts) > 1 else ""
        try:
            result = await self.api.video_subtitles(parts[0], lang)
            if not result.get("available"):
                reason = (
                    "该视频没有可用字幕。"
                    if result.get("logged_in")
                    else "该视频没有公开字幕；AI 字幕需要登录 B 站账号。"
                )
                text = f"💬 {reason}"
            else:
                selected = result.get("selected") or {}
                lines = [
                    f"💬 {truncate(result['video'].get('title'), 80)} 的字幕"
                    f"（{selected.get('lan_doc') or selected.get('lan') or '默认'}）",
                ]
                for segment in (result.get("segments") or [])[:80]:
                    lines.append(f"[{human_duration(segment.get('from'))}] {segment.get('content')}")
                text = "\n".join(lines)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("comments", alias={"评论"})
    async def bili_comments(self, event: AstrMessageEvent):
        raw = self._args(event, {"comments", "评论"})
        parts = split_args(raw)
        if not parts:
            yield event.plain_result("用法：/bili comments <BV号/av号/视频链接> [页码]")
            return
        page = to_int(parts[1], 1) if len(parts) > 1 else 1
        try:
            result = await self.api.comments(parts[0], page=page, limit=15)
            text = (
                f"💬 {truncate(result['video'].get('title'), 80)} 的热门评论"
                f"（第 {result.get('page', page)} 页）\n\n"
                + format_comment_list(result.get("items") or [], limit=15)
            )
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("danmaku", alias={"弹幕"})
    async def bili_danmaku(self, event: AstrMessageEvent):
        raw = self._args(event, {"danmaku", "弹幕"})
        parts = split_args(raw)
        if not parts:
            yield event.plain_result("用法：/bili danmaku <BV号/av号/视频链接> [数量]")
            return
        limit = to_int(parts[1], 30) if len(parts) > 1 else 30
        try:
            result = await self.api.danmaku(parts[0], limit=max(1, min(100, limit)))
            lines = [f"💬 {truncate(result['video'].get('title'), 80)} 的弹幕"]
            for item in result.get("items") or []:
                lines.append(f"[{human_duration(item.get('time'))}] {item.get('text')}")
            text = "\n".join(lines)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("up", alias={"用户", "up主"})
    async def bili_up(self, event: AstrMessageEvent):
        raw = self._args(event, {"up", "用户", "up主"})
        uid = parse_uid(raw.split()[0]) if raw.split() else None
        if not uid:
            yield event.plain_result("用法：/bili up <UID/空间链接>")
            return
        try:
            user = await self.api.user(uid)
            text = format_user(user)
            videos = await self.api.user_videos(uid, limit=3)
            if videos.get("items"):
                text += "\n\n🆕 最近投稿\n" + format_video_list(videos["items"], limit=3)
                if videos.get("total"):
                    text += f"\n共 {videos['total']} 个投稿"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("videos", alias={"投稿"})
    async def bili_videos(self, event: AstrMessageEvent):
        raw = self._args(event, {"videos", "投稿"})
        parts = split_args(raw)
        uid = parse_uid(parts[0]) if parts else None
        if not uid:
            yield event.plain_result("用法：/bili videos <UID/空间链接> [页码]")
            return
        page = to_int(parts[1], 1) if len(parts) > 1 else 1
        try:
            result = await self.api.user_videos(uid, page=page, limit=10)
            text = f"📚 UID {uid} 的投稿（第 {page} 页）\n\n" + format_video_list(
                result.get("items") or [], limit=10
            )
            if result.get("total"):
                text += f"\n\n共 {result['total']} 个投稿。"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("dynamics", alias={"动态"})
    async def bili_dynamics(self, event: AstrMessageEvent):
        raw = self._args(event, {"dynamics", "动态"})
        parts = split_args(raw)
        uid = parse_uid(parts[0]) if parts else None
        if not uid:
            yield event.plain_result("用法：/bili dynamics <UID/空间链接> [数量]")
            return
        limit = to_int(parts[1], 3) if len(parts) > 1 else 3
        try:
            result = await self.api.user_dynamics(uid, limit=max(1, min(10, limit)))
            items = result.get("items") or []
            text = f"📝 UID {uid} 的最新动态\n\n" + "\n\n".join(
                format_dynamic(item) for item in items
            )
            if not items:
                text = "该 UP 主最近没有公开动态。"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("dynamic", alias={"动态详情"})
    async def bili_dynamic(self, event: AstrMessageEvent):
        raw = self._args(event, {"dynamic", "动态详情"})
        dynamic_id = parse_dynamic_ref(raw.split()[0]) if raw.split() else None
        if not dynamic_id:
            yield event.plain_result("用法：/bili dynamic <动态ID/链接>")
            return
        try:
            item = await self.api.dynamic(dynamic_id)
            text = format_dynamic(item)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("live", alias={"直播"})
    async def bili_live(self, event: AstrMessageEvent):
        raw = self._args(event, {"live", "直播"})
        if not raw:
            yield event.plain_result("用法：/bili live <UID/房间号/直播间链接>")
            return
        try:
            live = await self.api.live(raw.split()[0], with_user=True)
            text = format_live(live) if live.get("exists") else "该 UP 主没有开通直播间。"
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("hot", alias={"热门"})
    async def bili_hot(self, event: AstrMessageEvent):
        raw = self._args(event, {"hot", "热门"})
        try:
            if raw.strip().lower() in ("search", "热搜", "搜索"):
                items = await self.api.hot_search(limit=10)
                text = "🔥 B 站热搜\n" + "\n".join(
                    f"{index}. {item.get('show_name') or item.get('keyword')}"
                    for index, item in enumerate(items, 1)
                )
            else:
                items = await self.api.popular(limit=10)
                text = format_hot(
                    [{"title": video.get("title"), "owner": video.get("owner"), "bvid": video.get("bvid")} for video in items],
                    limit=10,
                )
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("rank", alias={"排行榜"})
    async def bili_rank(self, event: AstrMessageEvent):
        raw = self._args(event, {"rank", "排行榜"}).strip()
        rid = 0
        if raw:
            if raw.isdigit():
                rid = int(raw)
            elif raw in RANK_AREAS:
                rid = RANK_AREAS[raw]
        try:
            items = await self.api.ranking(rid, limit=10)
            text = format_rank(items, limit=10)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("article", alias={"专栏"})
    async def bili_article(self, event: AstrMessageEvent):
        raw = self._args(event, {"article", "专栏"})
        cvid = parse_article_ref(raw.split()[0]) if raw.split() else None
        if not cvid:
            yield event.plain_result("用法：/bili article <cv号/专栏链接>")
            return
        try:
            article = await self.api.article(cvid)
            text = format_article(article)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("bangumi", alias={"番剧"})
    async def bili_bangumi(self, event: AstrMessageEvent):
        raw = self._args(event, {"bangumi", "番剧"})
        if not raw:
            yield event.plain_result("用法：/bili bangumi <ss号/ep号/番剧链接>")
            return
        try:
            bangumi = await self.api.bangumi(raw.split()[0])
            text = format_bangumi(bangumi)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("fav", alias={"收藏夹"})
    async def bili_fav(self, event: AstrMessageEvent):
        raw = self._args(event, {"fav", "收藏夹"})
        parts = split_args(raw)
        if not parts or not parts[0].isdigit():
            yield event.plain_result("用法：/bili fav <收藏夹ID>")
            return
        page = to_int(parts[1], 1) if len(parts) > 1 else 1
        try:
            fav = await self.api.fav(parts[0], page=page, limit=15)
            text = format_fav(fav, limit=15)
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("sub", alias={"订阅"})
    async def bili_sub(self, event: AstrMessageEvent):
        raw = self._args(event, {"sub", "订阅"})
        parts = split_args(raw)
        umo = event.unified_msg_origin
        action = parts[0].lower() if parts else "list"
        try:
            if action in ("add", "添加", "新增"):
                if len(parts) < 2:
                    text = "用法：/bili sub add <UID> [视频/动态/直播]"
                else:
                    uid = parse_uid(parts[1])
                    if not uid:
                        text = "无法识别 UID。"
                    else:
                        types = parse_sub_types(parts[2:])
                        name = ""
                        try:
                            user = await self.api.user(uid)
                            name = user.get("name") or ""
                        except BiliError:
                            pass
                        sub = self.subs.add(
                            Subscription(
                                umo=umo,
                                uid=uid,
                                name=name,
                                types=types,
                            )
                        )
                        await self.poller.prime(sub)
                        text = (
                            f"✅ 已订阅 {sub.name or ('UID ' + str(sub.uid))}（UID {sub.uid}）\n"
                            f"推送类型：{' / '.join(sub.types)}\n"
                            "有新内容时会主动推送到本会话。"
                        )
            elif action in ("del", "delete", "remove", "删除", "取消"):
                if len(parts) < 2:
                    text = "用法：/bili sub del <UID>"
                else:
                    uid = parse_uid(parts[1])
                    if uid and self.subs.remove(umo, uid):
                        text = f"✅ 已取消订阅 UID {uid}。"
                    else:
                        text = "没有找到该订阅。"
            elif action in ("check", "检查"):
                await self.poller.run_once()
                text = (
                    "✅ 已检查一轮订阅。\n"
                    f"上次检查：{format_timestamp(self.poller.last_round_at)}\n"
                    f"订阅数：{len(self.subs.for_session(umo))}"
                )
            elif action in ("list", "ls", "列表", "查看"):
                text = format_subscriptions(
                    [sub.to_dict() for sub in self.subs.for_session(umo)]
                )
            else:
                text = HELP_TEXT
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bili.command("autoreply", alias={"自动回复"})
    async def bili_autoreply(self, event: AstrMessageEvent):
        raw = self._args(event, {"autoreply", "自动回复"})
        parts = split_args(raw)
        action = parts[0].lower() if parts else "status"
        try:
            if action in ("status", "状态"):
                status = self.autoreply.status()
                stats = status.get("stats") or {}
                lines = [
                    "🤖 B 站自动回复",
                    f"总开关：{'开启' if status.get('master_enabled') else '关闭'}",
                    f"评论回复：{'开启' if status.get('comments_enabled') else '关闭'}",
                    f"私信回复：{'开启' if status.get('dms_enabled') else '关闭'}",
                    f"运行状态：{'运行中' if status.get('running') else '未运行'}"
                    + ("（dry-run，只记录不发送）" if status.get("dry_run") else ""),
                    f"已回复：评论 {stats.get('comment_replies', 0)} 条 / 私信 {stats.get('dm_replies', 0)} 条",
                ]
                if stats.get("comment_targets"):
                    lines.append("监控视频：" + "、".join(stats["comment_targets"][:8]))
                if stats.get("last_comment_round"):
                    lines.append(
                        "评论上次检查："
                        + format_timestamp(stats.get("last_comment_round"))
                    )
                if stats.get("last_dm_round"):
                    lines.append(
                        "私信上次检查：" + format_timestamp(stats.get("last_dm_round"))
                    )
                if stats.get("last_reply"):
                    lines.append("最近生成：" + truncate(stats["last_reply"], 120))
                if stats.get("last_error"):
                    lines.append("最近错误：" + truncate(stats["last_error"], 160))
                text = "\n".join(lines)
            elif action in ("on", "开启", "启动"):
                ok, message = self.autoreply.start()
                text = ("✅ " if ok else "❌ ") + message
                if not ok:
                    text += "\n请在插件配置中开启 enable_auto_reply，并确认已登录。"
            elif action in ("off", "关闭", "停止"):
                await self.autoreply.stop()
                text = "✅ 已停止自动回复任务（配置文件里的开关保持不变）。"
            elif action in ("reset", "重置"):
                await self.autoreply.reset()
                text = "✅ 已清空自动回复去重状态；下一轮会重新建立基线。"
            elif action in ("test", "测试", "预览"):
                sample = " ".join(parts[1:]).strip() or "这是一条测试评论，你好呀！"
                preview = await self.autoreply.preview(sample, kind="comment")
                text = f"🧪 自动回复预览（未发送）：\n{preview}"
            else:
                text = (
                    "用法：/bili autoreply status|on|off|reset|test <文本>\n"
                    "配置项：enable_auto_reply、auto_reply_comments、auto_reply_dms 等，"
                    "详见插件配置页和 README。"
                )
        except BiliError as exc:
            text = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text = self._error(exc)
        yield event.plain_result(self._clip(text))

    @bili.command("send", alias={"私信", "发私信", "dm"})
    async def bili_send(self, event: AstrMessageEvent):
        """主动给 B 站用户发一条私信。默认仅管理员可用。"""
        if bool(self.config.get("send_dm_admin_only", True)) and not event.is_admin():
            yield event.plain_result("❌ 主动私信默认仅管理员可用（可关闭 send_dm_admin_only）。")
            return
        raw = self._args(event, {"send", "私信", "发私信", "dm"})
        parts = split_args(raw)
        if len(parts) < 2:
            yield event.plain_result("用法：/bili send <UID/self> <文本>\n例如：/bili send 12345678 你好呀")
            return
        target = parts[0]
        text = " ".join(parts[1:]).strip()
        if not text:
            yield event.plain_result("私信内容不能为空。")
            return
        try:
            uid = await self._resolve_dm_uid(target)
            if not uid:
                yield event.plain_result("无法识别接收者 UID；也可以填 self 发给自己。")
                return
            if bool(self.config.get("send_dm_dry_run", False)):
                text_out = f"🧪 私信预览（未发送）\nUID {uid}：{truncate(text, 500)}"
            else:
                await self._send_bili_dm(uid, text)
                text_out = f"✅ 已向 UID {uid} 发送 B 站私信。"
        except BiliError as exc:
            text_out = self._error(exc)
        except Exception as exc:  # noqa: BLE001
            text_out = self._error(exc)
        yield event.plain_result(self._clip(text_out))

    @bili.command("login", alias={"登录"})
    async def bili_login(self, event: AstrMessageEvent):
        status = self.auth.status()
        if status.get("logged_in"):
            user = status.get("user") or {}
            yield event.plain_result(
                f"✅ 已登录 B 站\n👤 {user.get('name') or '未知'}（UID {user.get('uid') or '?'}）\n"
                "如需退出，请在 WebUI 插件页面操作。"
            )
            return
        try:
            qr = await self.auth.generate_qr()
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"生成登录二维码失败：{exc}")
            return
        text = (
            "📱 请使用 B 站手机客户端扫描二维码登录\n"
            f"链接：{qr['url']}\n"
            "二维码 180 秒内有效。"
        )
        png = qr.get("png_base64") or ""
        if png and bool(self.config.get("login_qr_in_chat", True)):
            try:
                import astrbot.api.message_components as Comp

                chain = [
                    Comp.Plain(text),
                    Comp.Image.fromBytes(base64.b64decode(png)),
                ]
                yield event.chain_result(chain)
            except Exception:
                yield event.plain_result(text)
        else:
            yield event.plain_result(text)
        self._start_bg(self._wait_chat_login(qr["qrcode_key"], event.unified_msg_origin))

    async def _wait_chat_login(self, qrcode_key: str, umo: str) -> None:
        """聊天内扫码后轮询登录结果，并主动告知用户。"""
        for _ in range(90):
            await asyncio.sleep(2)
            try:
                result = await self.auth.poll_qr(qrcode_key)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("轮询扫码登录失败：%s", exc)
                continue
            state = result.get("state")
            if state == "confirmed":
                user = result.get("user") or {}
                self.autoreply.start()
                await self.context.send_message(
                    umo,
                    MessageChain().message(
                        f"✅ B 站登录成功：{user.get('name') or '已登录'}（UID {user.get('uid') or '?'}）"
                    ),
                )
                return
            if state == "expired":
                await self.context.send_message(
                    umo, MessageChain().message("⌛ 登录二维码已失效，请重新发送 /bili login。")
                )
                return

    @bili.command("whoami", alias={"我的账号"})
    async def bili_whoami(self, event: AstrMessageEvent):
        status = self.auth.status()
        if not status.get("logged_in"):
            yield event.plain_result(
                "当前为游客模式。发送 /bili login 扫码登录，或在插件配置中填写 Cookie。"
            )
            return
        user = status.get("user") or {}
        yield event.plain_result(
            f"👤 {user.get('name') or '未知'}（UID {user.get('uid') or '?'}）\n"
            f"Lv{user.get('level') or 0}  {user.get('vip') or ''}\n"
            f"登录来源：{'扫码登录' if status.get('source') == 'qr' else '配置 Cookie'}"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bili.command("logout", alias={"退出登录"})
    async def bili_logout(self, event: AstrMessageEvent):
        await self.autoreply.stop()
        await self.auth.logout()
        yield event.plain_result("✅ 已退出 B 站登录。")

    def _start_bg(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ------------------------------------------------------------------ LLM 工具
    @filter.llm_tool(name="bilibili_search")
    async def tool_search(self, event: AstrMessageEvent, keyword: str, type: str = "video") -> str:
        """搜索 Bilibili 内容。当用户想找 B 站视频、UP 主、直播、番剧或专栏时使用。

        Args:
            keyword(string): 搜索关键词
            type(string): 搜索类型，可选 video、user、live、bangumi、article，默认 video
        """
        try:
            result = await self.api.search(keyword, type or "video", limit=8)
            return self._clip(
                format_search(
                    keyword, result.get("type", type), result.get("items") or [], limit=8
                )
            )
        except BiliError as exc:
            return f"搜索失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_video")
    async def tool_video(self, event: AstrMessageEvent, ref: str) -> str:
        """获取 B 站视频的标题、UP 主、播放量、简介等信息。ref 可以是 BV 号、av 号或视频链接。

        Args:
            ref(string): BV 号、av 号或视频链接
        """
        try:
            return self._clip(format_video(await self.api.video(ref)))
        except BiliError as exc:
            return f"获取视频失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_video_summary")
    async def tool_summary(self, event: AstrMessageEvent, ref: str) -> str:
        """获取 B 站视频的 AI 总结和分段提纲（需要登录 B 站账号）。

        Args:
            ref(string): BV 号、av 号或视频链接
        """
        try:
            result = await self.api.video_summary(ref)
            if not result.get("available"):
                return "该视频暂无 AI 总结。"
            lines = [result.get("summary") or ""]
            for section in (result.get("outline") or [])[:10]:
                lines.append(f"[{human_duration(section.get('timestamp'))}] {section.get('title')}")
            return self._clip("\n".join(lines))
        except BiliError as exc:
            return f"获取视频总结失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_video_subtitle")
    async def tool_subtitle(self, event: AstrMessageEvent, ref: str, lang: str = "") -> str:
        """读取 B 站视频字幕文本（需要登录 B 站账号，且视频有字幕）。

        Args:
            ref(string): BV 号、av 号或视频链接
            lang(string): 可选语言代码，例如 zh-CN；留空自动选择
        """
        try:
            result = await self.api.video_subtitles(ref, lang)
            if not result.get("available"):
                return "该视频没有可用字幕（AI 字幕需要登录 B 站账号）。"
            return self._clip(result.get("text") or "")
        except BiliError as exc:
            return f"获取字幕失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_video_comments")
    async def tool_comments(
        self,
        event: AstrMessageEvent,
        ref: str,
        page: int = 1,
        limit: int = 10,
    ) -> str:
        """读取 B 站视频的热门评论，用于了解观众观点。

        Args:
            ref(string): BV 号、av 号或视频链接
            page(number): 页码，默认 1
            limit(number): 返回条数，默认 10，最大 20
        """
        try:
            result = await self.api.comments(ref, page=page, limit=limit)
            return self._clip(
                format_comment_list(result.get("items") or [], limit=min(20, limit))
            )
        except BiliError as exc:
            return f"获取评论失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_video_danmaku")
    async def tool_danmaku(self, event: AstrMessageEvent, ref: str, limit: int = 30) -> str:
        """读取 B 站视频弹幕，用于了解视频名场面或观众反应。

        Args:
            ref(string): BV 号、av 号或视频链接
            limit(number): 返回条数，默认 30，最大 100
        """
        try:
            result = await self.api.danmaku(ref, limit=limit)
            return self._clip(
                "\n".join(
                    f"[{human_duration(item.get('time'))}] {item.get('text')}"
                    for item in (result.get("items") or [])
                )
            )
        except BiliError as exc:
            return f"获取弹幕失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_user")
    async def tool_user(self, event: AstrMessageEvent, uid: str) -> str:
        """获取 B 站 UP 主的资料：昵称、粉丝数、签名、等级。

        Args:
            uid(string): UP 主 UID
        """
        parsed = parse_uid(uid)
        if not parsed:
            return "UID 格式不正确。"
        try:
            return self._clip(format_user(await self.api.user(parsed)))
        except BiliError as exc:
            return f"获取用户失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_user_videos")
    async def tool_user_videos(
        self,
        event: AstrMessageEvent,
        uid: str,
        page: int = 1,
    ) -> str:
        """获取 B 站 UP 主最近的投稿视频列表。

        Args:
            uid(string): UP 主 UID
            page(number): 页码，默认 1
        """
        parsed = parse_uid(uid)
        if not parsed:
            return "UID 格式不正确。"
        try:
            result = await self.api.user_videos(parsed, page=page, limit=10)
            return self._clip(format_video_list(result.get("items") or [], limit=10))
        except BiliError as exc:
            return f"获取投稿失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_user_dynamics")
    async def tool_user_dynamics(
        self,
        event: AstrMessageEvent,
        uid: str,
        limit: int = 5,
    ) -> str:
        """获取 B 站 UP 主最近发布的动态。

        Args:
            uid(string): UP 主 UID
            limit(number): 返回条数，默认 5，最大 10
        """
        parsed = parse_uid(uid)
        if not parsed:
            return "UID 格式不正确。"
        try:
            result = await self.api.user_dynamics(parsed, limit=limit)
            return self._clip(
                "\n\n".join(format_dynamic(item) for item in (result.get("items") or []))
            )
        except BiliError as exc:
            return f"获取动态失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_live")
    async def tool_live(self, event: AstrMessageEvent, ref: str) -> str:
        """查询 B 站直播间状态：是否开播、标题、人气。

        Args:
            ref(string): UP 主 UID、直播间房间号或直播间链接
        """
        try:
            live = await self.api.live(ref, with_user=True)
            return self._clip(format_live(live) if live.get("exists") else "没有找到直播间。")
        except BiliError as exc:
            return f"查询直播失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_hot")
    async def tool_hot(self, event: AstrMessageEvent, limit: int = 10) -> str:
        """获取 B 站当前热门视频或热搜，用于回答“B 站最近有什么热门”。

        Args:
            limit(number): 返回条数，默认 10
        """
        try:
            items = await self.api.popular(limit=limit)
            return self._clip(
                format_hot(
                    [
                        {"title": video.get("title"), "owner": video.get("owner"), "bvid": video.get("bvid")}
                        for video in items
                    ],
                    limit=limit,
                )
            )
        except BiliError as exc:
            return f"获取热门失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_rank")
    async def tool_rank(self, event: AstrMessageEvent, area: str = "全站") -> str:
        """获取 B 站排行榜，可按分区筛选。

        Args:
            area(string): 分区名称，例如 全站、动画、音乐、游戏、知识、科技；默认全站
        """
        rid = RANK_AREAS.get(area, 0)
        try:
            items = await self.api.ranking(rid, limit=10)
            return self._clip(format_rank(items, limit=10))
        except BiliError as exc:
            return f"获取排行榜失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_article")
    async def tool_article(self, event: AstrMessageEvent, cvid: str) -> str:
        """获取 B 站专栏文章的内容摘要。

        Args:
            cvid(string): 专栏 cv 号或专栏链接
        """
        parsed = parse_article_ref(cvid)
        if not parsed:
            return "无法识别专栏 cv 号。"
        try:
            return self._clip(format_article(await self.api.article(parsed)))
        except BiliError as exc:
            return f"获取专栏失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_bangumi")
    async def tool_bangumi(self, event: AstrMessageEvent, ref: str) -> str:
        """获取 B 站番剧/影视的基本信息。

        Args:
            ref(string): ss 号、ep 号或番剧链接
        """
        try:
            return self._clip(format_bangumi(await self.api.bangumi(ref)))
        except BiliError as exc:
            return f"获取番剧失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_fav")
    async def tool_fav(self, event: AstrMessageEvent, media_id: str) -> str:
        """获取公开 B 站收藏夹的内容列表。

        Args:
            media_id(string): 收藏夹 ID
        """
        if not str(media_id).strip().isdigit():
            return "收藏夹 ID 应为数字。"
        try:
            return self._clip(format_fav(await self.api.fav(int(media_id)), limit=10))
        except BiliError as exc:
            return f"获取收藏夹失败：{exc.user_message}"

    @filter.llm_tool(name="bilibili_send_dm")
    async def tool_send_dm(self, event: AstrMessageEvent, uid: str, text: str) -> str:
        """主动给 B 站用户发送一条私信。只有配置里开启 enable_llm_send_dm、且对方在
        llm_send_dm_whitelist 中（或发给自己）时才允许，避免被滥用成骚扰工具。

        Args:
            uid(string): 接收者 UID，也可以填 self 发给自己
            text(string): 私信正文，建议不超过 200 字
        """
        if not bool(self.config.get("enable_llm_send_dm", False)):
            return "主动私信工具未启用（enable_llm_send_dm=false）。"
        try:
            target = await self._resolve_dm_uid(uid)
            if not target:
                return "无法识别接收者 UID。"
            me = await self._resolve_dm_uid("self")
            whitelist = {
                parsed
                for token in split_args(str(self.config.get("llm_send_dm_whitelist", "") or "").replace(",", " ").replace("，", " "))
                if (parsed := parse_uid(token))
            }
            if target != me and target not in whitelist:
                return "该 UID 不在 llm_send_dm_whitelist 中，已拒绝发送。"
            if bool(self.config.get("send_dm_dry_run", False)):
                return f"（dry-run）将向 UID {target} 发送：{truncate(text, 500)}"
            await self._send_bili_dm(target, text)
            return f"已向 UID {target} 发送 B 站私信。"
        except BiliError as exc:
            return f"发送私信失败：{exc.user_message}"
        except Exception as exc:  # noqa: BLE001
            return f"发送私信失败：{exc}"

    # ------------------------------------------------------------------ Web API
    def _register_web_apis(self) -> None:
        if not WEB_API_SUPPORTED:
            self.logger.warning(
                "当前 AstrBot 版本不支持插件 Pages Web API，"
                "WebUI 扫码登录页不可用；聊天指令和 LLM 工具不受影响。"
            )
            return
        routes = (
            ("status", self.page_status, ["GET"], "B 站登录与订阅状态"),
            ("login/qrcode", self.page_login_qrcode, ["POST"], "生成 B 站扫码登录二维码"),
            ("login/poll", self.page_login_poll, ["POST"], "轮询扫码登录状态"),
            ("logout", self.page_logout, ["POST"], "退出 B 站登录"),
            ("subs", self.page_subs, ["GET"], "订阅概览"),
            ("subs/list", self.page_subs_list, ["GET"], "订阅明细"),
            ("subs/add", self.page_subs_add, ["POST"], "添加订阅"),
            ("subs/remove", self.page_subs_remove, ["POST"], "删除订阅"),
            ("send-dm", self.page_send_dm, ["POST"], "主动发送 B 站私信"),
            ("autoreply/run", self.page_autoreply_run, ["POST"], "立即检查自动回复"),
            ("autoreply/reset", self.page_autoreply_reset, ["POST"], "重置自动回复状态"),
            ("config", self.page_config, ["GET", "POST"], "读取/保存插件配置"),
        )
        for path, handler, methods, desc in routes:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/{path}", handler, methods, desc
            )

    async def _json_body(self) -> dict[str, Any]:
        try:
            body = await request.json(default={})
        except Exception:  # noqa: BLE001
            body = {}
        return body if isinstance(body, dict) else {}

    async def page_config(self):
        if request.method == "POST":
            body = await self._json_body()
            values = body.get("values") or {}
            if not isinstance(values, dict):
                return error_response("values 必须是对象", status_code=400)
            for key, value in values.items():
                spec = CONFIG_SPEC.get(key)
                if spec is None:
                    continue
                self.config[key] = _coerce_config_value(spec, value)
            notify = values.get("subscription_notify")
            if isinstance(notify, dict):
                self.config["subscription_notify"] = {
                    key: bool(notify.get(key, True)) for key in ("video", "dynamic", "live")
                }
            cookie = body.get("cookie")
            if cookie is not None and str(cookie).strip():
                cookie_text = str(cookie).strip()
                self.config["cookie"] = cookie_text
                self.auth.config_cookie = cookie_text
                self.client.update_cookies_from_string(cookie_text)
                # 手动 Cookie 优先：清掉旧的扫码凭据，避免下次启动时被旧凭据覆盖
                self.auth.store.clear()
            try:
                save = getattr(self.config, "save_config", None)
                if callable(save):
                    save()
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("保存插件配置失败")
                return error_response(f"保存配置失败：{exc}", status_code=500)
            try:
                await self._apply_runtime_config()
                if cookie is not None and str(cookie).strip():
                    await self.auth.refresh_user(force=True)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("应用运行时配置失败：%s", exc)
            return json_response(self._public_config())
        return json_response(self._public_config())

    async def page_subs_list(self):
        items = [sub.to_dict() for sub in self.subs.all()]
        sessions = sorted({sub.umo for sub in self.subs.all()})
        return json_response(
            {"items": items, "sessions": sessions, "counts": self.subs.counts()}
        )

    async def page_subs_add(self):
        body = await self._json_body()
        umo = str(body.get("umo") or "").strip()
        uid = parse_uid(str(body.get("uid") or ""))
        raw_types = body.get("types")
        types = parse_sub_types(raw_types if isinstance(raw_types, list) else [str(raw_types or "")])
        if not umo:
            return error_response("请填写会话 UMO", status_code=400)
        if not uid:
            return error_response("UID 格式不正确", status_code=400)
        name = ""
        try:
            user = await self.api.user(uid)
            name = str(user.get("name") or "")
        except BiliError:
            name = ""
        try:
            sub = self.subs.add(Subscription(umo=umo, uid=uid, name=name, types=types))
        except BiliError as exc:
            return error_response(exc.user_message, status_code=400)
        try:
            await self.poller.prime(sub)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("建立订阅基线失败：%s", exc)
        return json_response({"ok": True, "item": sub.to_dict()})

    async def page_subs_remove(self):
        body = await self._json_body()
        umo = str(body.get("umo") or "").strip()
        uid = parse_uid(str(body.get("uid") or ""))
        if not umo or not uid:
            return error_response("需要 umo 和 uid", status_code=400)
        removed = self.subs.remove(umo, uid)
        return json_response({"ok": removed})

    async def page_send_dm(self):
        body = await self._json_body()
        uid = await self._resolve_dm_uid(str(body.get("uid") or ""))
        text = str(body.get("text") or "").strip()
        if not uid:
            return error_response("UID 格式不正确", status_code=400)
        if not text:
            return error_response("私信内容不能为空", status_code=400)
        if bool(self.config.get("send_dm_dry_run", False)):
            return json_response(
                {"ok": True, "dry_run": True, "uid": uid, "text": truncate(text, 500)}
            )
        try:
            await self._send_bili_dm(uid, text)
        except BiliError as exc:
            return error_response(exc.user_message, status_code=400)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("WebUI 发送私信失败")
            return error_response(f"发送失败：{exc}", status_code=500)
        return json_response({"ok": True, "uid": uid, "text": truncate(text, 500)})

    async def page_autoreply_run(self):
        status = self.autoreply.status()
        if not status.get("master_enabled"):
            return error_response("自动回复总开关未开启", status_code=400)
        before = (status.get("stats") or {}).copy()
        try:
            if status.get("comments_enabled"):
                await self.autoreply.run_comments_once()
            if status.get("dms_enabled"):
                await self.autoreply.run_dms_once()
        except BiliError as exc:
            return error_response(exc.user_message, status_code=400)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("WebUI 自动回复执行失败")
            return error_response(f"执行失败：{exc}", status_code=500)
        after = self.autoreply.status().get("stats") or {}
        return json_response(
            {
                "ok": True,
                "comment_replies": max(0, int(after.get("comment_replies", 0)) - int(before.get("comment_replies", 0))),
                "dm_replies": max(0, int(after.get("dm_replies", 0)) - int(before.get("dm_replies", 0))),
                "stats": after,
            }
        )

    async def page_autoreply_reset(self):
        try:
            await self.autoreply.reset()
        except Exception as exc:  # noqa: BLE001
            return error_response(f"重置失败：{exc}", status_code=500)
        return json_response({"ok": True})

    async def page_status(self):
        status = self.auth.status()
        return json_response(
            {
                **status,
                "subscriptions": self.subs.counts(),
                "poller": {
                    "running": self.poller.running,
                    "interval_seconds": self.poller.interval_seconds,
                    "last_round_at": self.poller.last_round_at,
                    "last_error": self.poller.last_error,
                },
                "autoreply": self.autoreply.status(),
                "version": VERSION,
            }
        )

    async def page_login_qrcode(self):
        try:
            qr = await self.auth.generate_qr()
        except BiliError as exc:
            return error_response(exc.user_message, status_code=400)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("生成扫码登录二维码失败")
            return error_response(f"生成二维码失败：{exc}", status_code=500)
        return json_response(
            {
                "qrcode_key": qr.get("qrcode_key", ""),
                "url": qr.get("url", ""),
                "svg": qr.get("svg", ""),
                "expires_in": qr.get("expires_in", 180),
            }
        )

    async def page_login_poll(self):
        try:
            body = await request.json(default={})
        except Exception:  # noqa: BLE001
            body = {}
        key = str((body or {}).get("qrcode_key") or "").strip()
        if not key or len(key) != 32 or not key.isalnum():
            return error_response("缺少有效的 qrcode_key", status_code=400)
        try:
            result = await self.auth.poll_qr(key)
        except BiliError as exc:
            return error_response(exc.user_message, status_code=400)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("轮询扫码登录失败")
            return error_response(f"轮询失败：{exc}", status_code=500)
        if result.get("state") == "confirmed":
            self.autoreply.start()
        return json_response({**result, "status": self.auth.status()})

    async def page_logout(self):
        try:
            await self.autoreply.stop()
            status = await self.auth.logout()
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("退出 B 站登录失败")
            return error_response(f"退出失败：{exc}", status_code=500)
        return json_response(status)

    async def page_subs(self):
        grouped: dict[int, dict[str, Any]] = {}
        for sub in self.subs.all():
            entry = grouped.setdefault(
                sub.uid,
                {"uid": sub.uid, "name": sub.name, "types": set(), "sessions": 0},
            )
            entry["types"].update(sub.types)
            entry["sessions"] += 1
            if sub.name and not entry["name"]:
                entry["name"] = sub.name
        items = [
            {
                "uid": entry["uid"],
                "name": entry["name"],
                "types": sorted(entry["types"]),
                "sessions": entry["sessions"],
            }
            for entry in grouped.values()
        ]
        items.sort(key=lambda item: item["uid"])
        return json_response({"counts": self.subs.counts(), "items": items})
