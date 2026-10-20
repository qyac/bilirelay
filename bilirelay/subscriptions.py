"""UP 主订阅存储与后台轮询推送。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from .api import BiliAPI
from .errors import BiliError, NotLoggedIn, RiskControl
from .formatting import (
    format_dynamic,
    format_live,
    human_count,
    human_duration,
    truncate,
)

from .logging_utils import logger

ALL_TYPES = ("video", "dynamic", "live")
TYPE_ALIASES = {
    "video": "video",
    "视频": "video",
    "投稿": "video",
    "dynamic": "dynamic",
    "动态": "dynamic",
    "live": "live",
    "直播": "live",
    "all": "all",
    "全部": "all",
}


@dataclass
class Subscription:
    umo: str
    uid: int
    name: str = ""
    types: list[str] = field(default_factory=lambda: list(ALL_TYPES))
    last_video_pubdate: int = 0
    last_video_bvid: str = ""
    last_dynamic_id: str = ""
    last_live_status: int = -1
    created_at: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Subscription" | None:
        try:
            umo = str(data.get("umo") or "")
            uid = int(data.get("uid") or 0)
        except (TypeError, ValueError):
            return None
        if not umo or uid <= 0:
            return None
        types = [t for t in (data.get("types") or []) if t in ALL_TYPES]
        return cls(
            umo=umo,
            uid=uid,
            name=str(data.get("name") or ""),
            types=types or list(ALL_TYPES),
            last_video_pubdate=int(data.get("last_video_pubdate") or 0),
            last_video_bvid=str(data.get("last_video_bvid") or ""),
            last_dynamic_id=str(data.get("last_dynamic_id") or ""),
            last_live_status=int(data.get("last_live_status", -1)),
            created_at=int(data.get("created_at") or time.time()),
        )


class SubscriptionStore:
    """按会话（unified_msg_origin）保存订阅。"""

    def __init__(self, path: Path, *, max_per_session: int = 20) -> None:
        self.path = Path(path)
        self.max_per_session = max(1, max_per_session)
        self._subs: list[Subscription] = []
        self.load()

    def load(self) -> None:
        self._subs = []
        try:
            if not self.path.is_file():
                return
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            raw = data.get("subscriptions") if isinstance(data, dict) else data
            for item in raw or []:
                if isinstance(item, dict):
                    sub = Subscription.from_dict(item)
                    if sub:
                        self._subs.append(sub)
        except (OSError, ValueError) as exc:
            logger.warning("读取 B 站订阅失败：%s", exc)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "updated_at": int(time.time()),
            "subscriptions": [sub.to_dict() for sub in self._subs],
        }
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            temp.replace(self.path)
        except OSError as exc:
            logger.warning("保存 B 站订阅失败：%s", exc)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def all(self) -> list[Subscription]:
        return list(self._subs)

    def for_session(self, umo: str) -> list[Subscription]:
        return [sub for sub in self._subs if sub.umo == umo]

    def get(self, umo: str, uid: int) -> Subscription | None:
        for sub in self._subs:
            if sub.umo == umo and sub.uid == uid:
                return sub
        return None

    def add(self, sub: Subscription) -> Subscription:
        existing = self.get(sub.umo, sub.uid)
        if existing:
            existing.types = sorted(set(existing.types) | set(sub.types))
            if sub.name:
                existing.name = sub.name
            self.save()
            return existing
        if len(self.for_session(sub.umo)) >= self.max_per_session:
            raise BiliError(
                -400,
                f"每个会话最多订阅 {self.max_per_session} 个 UP 主",
            )
        self._subs.append(sub)
        self.save()
        return sub

    def remove(self, umo: str, uid: int) -> bool:
        before = len(self._subs)
        self._subs = [sub for sub in self._subs if not (sub.umo == umo and sub.uid == uid)]
        if len(self._subs) != before:
            self.save()
            return True
        return False

    def update(self, sub: Subscription) -> None:
        for index, current in enumerate(self._subs):
            if current.umo == sub.umo and current.uid == sub.uid:
                self._subs[index] = sub
                self.save()
                return

    def counts(self) -> dict[str, Any]:
        sessions = {sub.umo for sub in self._subs}
        return {
            "total": len(self._subs),
            "sessions": len(sessions),
            "ups": len({sub.uid for sub in self._subs}),
            "by_type": {
                t: sum(1 for sub in self._subs if t in sub.types) for t in ALL_TYPES
            },
        }


SendFunc = Callable[[str, str, str], Awaitable[None]]
"""send(umo, text, cover_url)"""


class SubscriptionPoller:
    """后台轮询 UP 主投稿 / 动态 / 开播，并主动推送。"""

    def __init__(
        self,
        api: BiliAPI,
        store: SubscriptionStore,
        send: SendFunc,
        *,
        interval_seconds: int = 300,
        notify: Iterable[str] = ALL_TYPES,
        max_pushes_per_round: int = 10,
    ) -> None:
        self.api = api
        self.store = store
        self.send = send
        self.interval_seconds = max(60, int(interval_seconds))
        self.notify = set(notify) or set(ALL_TYPES)
        self.max_pushes_per_round = max(1, max_pushes_per_round)
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._round_lock = asyncio.Lock()
        self.last_round_at = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="bilirelay-subscriptions")
        logger.info("B 站订阅轮询已启动，间隔 %s 秒", self.interval_seconds)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止 B 站订阅轮询时出错：%s", exc)
        self._task = None

    async def _run(self) -> None:
        # 启动后延迟一小段时间，避免和 AstrBot 初始化抢资源
        await asyncio.sleep(8)
        while not self._stopping:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("B 站订阅轮询失败：%s", exc)
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise

    async def run_once(self) -> None:
        """执行一轮检查；测试和手动 `/bili sub check` 也调用这里。"""
        async with self._round_lock:
            subs = self.store.all()
            if not subs:
                self.last_round_at = int(time.time())
                return
            grouped: dict[int, list[Subscription]] = {}
            for sub in subs:
                grouped.setdefault(sub.uid, []).append(sub)
            pushed = 0
            for uid, entries in grouped.items():
                if pushed >= self.max_pushes_per_round:
                    break
                try:
                    pushed += await self._check_uid(uid, entries, pushed)
                except (NotLoggedIn, RiskControl) as exc:
                    self.last_error = str(exc)
                    logger.warning("检查 UID %s 时被风控/需要登录：%s", uid, exc)
                except BiliError as exc:
                    self.last_error = str(exc)
                    logger.warning("检查 UID %s 失败：%s", uid, exc)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)
                    logger.exception("检查 UID %s 时发生未预期错误", uid)
                await asyncio.sleep(0.3)
            self.last_round_at = int(time.time())

    async def _check_uid(
        self,
        uid: int,
        entries: list[Subscription],
        pushed: int,
    ) -> int:
        name = next((sub.name for sub in entries if sub.name), "")
        want_video = any("video" in sub.types for sub in entries)
        want_dynamic = any("dynamic" in sub.types for sub in entries)
        want_live = any("live" in sub.types for sub in entries)
        new_count = 0

        if want_video and "video" in self.notify:
            try:
                result = await self.api.user_videos(uid, limit=1)
                items = result.get("items") or []
                latest = items[0] if items else None
                if latest and latest.get("bvid"):
                    for sub in entries:
                        if "video" not in sub.types:
                            continue
                        if not sub.last_video_bvid:
                            self._prime_video(sub, latest)
                            continue
                        if (
                            latest["bvid"] != sub.last_video_bvid
                            and latest.get("pubdate", 0) >= sub.last_video_pubdate
                        ):
                            sub.name = sub.name or latest.get("author") or name
                            text = self._video_message(sub.name, latest)
                            await self._push(sub, text, latest.get("cover", ""))
                            new_count += 1
                            if pushed + new_count >= self.max_pushes_per_round:
                                break
                        self._prime_video(sub, latest)
            except BiliError as exc:
                logger.debug("检查 UID %s 投稿失败：%s", uid, exc)

        if want_dynamic and "dynamic" in self.notify and pushed + new_count < self.max_pushes_per_round:
            try:
                result = await self.api.user_dynamics(uid, limit=3)
                items = result.get("items") or []
                latest = items[0] if items else None
                if latest and latest.get("id"):
                    for sub in entries:
                        if "dynamic" not in sub.types:
                            continue
                        if not sub.last_dynamic_id:
                            sub.last_dynamic_id = latest["id"]
                            self.store.update(sub)
                            continue
                        if latest["id"] != sub.last_dynamic_id:
                            sub.name = sub.name or latest.get("author") or name
                            text = self._dynamic_message(sub.name, latest)
                            await self._push(sub, text, "")
                            new_count += 1
                            if pushed + new_count >= self.max_pushes_per_round:
                                break
                        sub.last_dynamic_id = latest["id"]
                        self.store.update(sub)
            except BiliError as exc:
                logger.debug("检查 UID %s 动态失败：%s", uid, exc)

        if want_live and "live" in self.notify and pushed + new_count < self.max_pushes_per_round:
            try:
                live = await self.api.live(uid, with_user=False)
                current = int(live.get("live_status") or 0)
                for sub in entries:
                    if "live" not in sub.types:
                        continue
                    previous = sub.last_live_status
                    if previous < 0:
                        sub.last_live_status = current
                        self.store.update(sub)
                        continue
                    if current == 1 and previous != 1:
                        sub.name = sub.name or live.get("name") or name
                        text = self._live_message(sub.name, live)
                        await self._push(sub, text, live.get("cover", ""))
                        new_count += 1
                        if pushed + new_count >= self.max_pushes_per_round:
                            break
                    sub.last_live_status = current
                    self.store.update(sub)
            except BiliError as exc:
                logger.debug("检查 UID %s 直播状态失败：%s", uid, exc)

        return new_count

    def _prime_video(self, sub: Subscription, latest: dict[str, Any]) -> None:
        sub.last_video_bvid = str(latest.get("bvid") or "")
        sub.last_video_pubdate = int(latest.get("pubdate") or 0)
        self.store.update(sub)

    async def prime(self, sub: Subscription) -> None:
        """添加订阅后立即记录当前基线，避免第一轮把旧内容当成新内容。"""
        name = sub.name
        if "video" in sub.types:
            try:
                result = await self.api.user_videos(sub.uid, limit=1)
                items = result.get("items") or []
                if items:
                    sub.last_video_bvid = str(items[0].get("bvid") or "")
                    sub.last_video_pubdate = int(items[0].get("pubdate") or 0)
                    name = name or str(items[0].get("author") or "")
            except BiliError:
                pass
        if "dynamic" in sub.types:
            try:
                result = await self.api.user_dynamics(sub.uid, limit=1)
                items = result.get("items") or []
                if items:
                    sub.last_dynamic_id = str(items[0].get("id") or "")
                    name = name or str(items[0].get("author") or "")
            except BiliError:
                pass
        if "live" in sub.types:
            try:
                live = await self.api.live(sub.uid, with_user=False)
                sub.last_live_status = int(live.get("live_status") or 0)
            except BiliError:
                sub.last_live_status = 0
        if name:
            sub.name = name
        self.store.update(sub)

    async def _push(self, sub: Subscription, text: str, cover: str) -> None:
        try:
            await self.send(sub.umo, text, cover)
        except Exception as exc:  # noqa: BLE001
            logger.warning("推送 B 站消息到 %s 失败：%s", sub.umo, exc)

    @staticmethod
    def _video_message(name: str, video: dict[str, Any]) -> str:
        title = truncate(video.get("title"), 120)
        stat = video.get("stat") or {}
        play = video.get("play") or stat.get("view")
        return "\n".join(
            part
            for part in (
                f"🔔 B站新视频 · {name or 'UP主'}",
                f"📺 {title}",
                f"▶ {human_count(play)}播放 · ⏱ {human_duration(video.get('duration'))}",
                f"🔗 https://www.bilibili.com/video/{video.get('bvid', '')}",
            )
            if part
        )

    @staticmethod
    def _dynamic_message(name: str, dynamic: dict[str, Any]) -> str:
        body = format_dynamic(dynamic, include_author=False)
        return f"🔔 B站新动态 · {name or dynamic.get('author') or 'UP主'}\n{body}"

    @staticmethod
    def _live_message(name: str, live: dict[str, Any]) -> str:
        body = format_live(live)
        return f"🔔 B站开播 · {name or live.get('name') or 'UP主'}\n{body}"
