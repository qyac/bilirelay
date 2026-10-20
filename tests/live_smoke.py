"""真实网络冒烟测试（不依赖 AstrBot）。

用法：
    python tests/live_smoke.py

注意：会请求真实 B 站接口；同一 IP 频繁运行可能触发风控。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bilirelay.api import BiliAPI  # noqa: E402
from bilirelay.client import BiliClient  # noqa: E402
from bilirelay.errors import BiliError  # noqa: E402


async def check(label: str, coro) -> None:
    try:
        result = await coro
        if isinstance(result, dict):
            preview = list(result)[:6]
        elif isinstance(result, list):
            preview = f"{len(result)} items"
        else:
            preview = str(result)[:120]
        print(f"[OK] {label}: {preview}")
    except BiliError as exc:
        print(f"[BILI-ERR] {label}: code={exc.code} {exc.user_message}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] {label}: {type(exc).__name__}: {exc}")


async def main() -> None:
    client = BiliClient(
        request_interval=0.8,
        cache_ttl=0,
        timeout=20,
    )
    api = BiliAPI(client)
    try:
        await check("nav", api.nav())
        await check("search video", api.search("AstrBot", "video", limit=3))
        await check("search user", api.search("AstrBot", "user", limit=3))
        video = await api.video("BV1GJ411x7h7")
        print(f"[OK] video: {video['title']} / {video['owner']['name']}")
        await check("comments", api.comments("BV1GJ411x7h7", limit=3))
        await check("latest comments", api.latest_comments("BV1GJ411x7h7", limit=3))
        await check("danmaku", api.danmaku("BV1GJ411x7h7", limit=5))
        await check("user", api.user(2))
        await check("user videos", api.user_videos(2, limit=3))
        await check("user dynamics", api.user_dynamics(2, limit=2))
        await check("live", api.live(2))
        await check("popular", api.popular(limit=3))
        await check("ranking", api.ranking(0, limit=3))
        await check("hot search", api.hot_search(limit=5))
        await check("article", api.article(417529))
        await check("bangumi", api.bangumi("ss28747"))
        await check("fav", api.fav(1169178, limit=3))
        await check("qr generate", client.generate_qr())
        await check("nav after", api.nav())
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
