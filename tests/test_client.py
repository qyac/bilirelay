from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.client import BiliClient, mixin_key, parse_cookie_string, sign_wbi


class ClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.risk_remaining = 0
        self.counts: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        self.counts[path] = self.counts.get(path, 0) + 1
        if path.endswith("/x/frontend/finger/spi"):
            return httpx.Response(
                200, json={"code": 0, "data": {"b_3": "buvid3-test", "b_4": "buvid4-test"}}
            )
        if "GenWebTicket" in path:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "ticket": "ticket-test",
                        "created_at": 1700000000,
                        "ttl": 259200,
                    },
                },
            )
        if path.endswith("/x/web-interface/nav"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "isLogin": False,
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                        },
                    },
                },
            )
        if path.endswith("/x/risk"):
            if self.risk_remaining > 0:
                self.risk_remaining -= 1
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "message": "OK",
                        "data": {"v_voucher": "voucher_test"},
                    },
                )
            return httpx.Response(200, json={"code": 0, "data": {"ok": True}})
        if path.endswith("/x/test"):
            return httpx.Response(200, json={"code": 0, "data": {"ok": True}})
        if path.endswith("/x/cache"):
            return httpx.Response(200, json={"code": 0, "data": {"n": self.counts[path]}})
        return httpx.Response(404, json={"code": -404, "message": "not found"})

    async def make_client(self, **kwargs) -> BiliClient:
        options = {"request_interval": 0, "cache_ttl": 0}
        options.update(kwargs)
        client = BiliClient(
            transport=httpx.MockTransport(self.handler),
            **options,
        )
        self.addAsyncCleanup(client.close)
        return client

    async def test_wbi_signature(self) -> None:
        client = await self.make_client()
        await client.request_json("/x/test", {"keyword": "AstrBot"}, signed=True)
        signed = [
            request
            for request in self.requests
            if request.url.path.endswith("/x/test")
        ][-1]
        params = dict(signed.url.params)
        self.assertIn("wts", params)
        self.assertIn("w_rid", params)
        self.assertEqual(len(params["w_rid"]), 32)

    async def test_cache(self) -> None:
        client = await self.make_client(cache_ttl=120)
        first = await client.request_json("/x/cache")
        second = await client.request_json("/x/cache")
        self.assertEqual(first, second)
        self.assertEqual(self.counts.get("/x/cache"), 1)

    async def test_voucher_only_is_retried(self) -> None:
        self.risk_remaining = 1
        client = await self.make_client()
        with patch("bilirelay.client.asyncio.sleep", new=AsyncMock()):
            payload = await client.request_json("/x/risk", retries=1)
        self.assertTrue(payload["data"]["ok"])
        self.assertEqual(self.counts.get("/x/risk"), 2)

    async def test_cookie_roundtrip(self) -> None:
        cookies = parse_cookie_string("SESSDATA=abc%2Cdef; bili_jct=xyz; DedeUserID=2")
        self.assertEqual(cookies["SESSDATA"], "abc%2Cdef")
        client = await self.make_client()
        client.update_cookies(cookies)
        self.assertTrue(client.has_login_cookie())
        exported = client.export_cookie()
        self.assertIn("SESSDATA=abc%2Cdef", exported)
        self.assertIn("bili_jct=xyz", exported)
        client.clear_login_cookie()
        self.assertFalse(client.has_login_cookie())

    def test_mixin_key_and_sign(self) -> None:
        key = mixin_key(
            "7cd084941338484aae1ad9425b84077c",
            "4932caff0ff746eab6f01bf08b70ac45",
        )
        self.assertEqual(key, "ea1db124af3c7062474693fa704f4ff8")
        signed = sign_wbi({"b": "a!'()*b", "a": 1}, key)
        self.assertEqual(signed["b"], "ab")
        self.assertIn("wts", signed)
        self.assertEqual(len(signed["w_rid"]), 32)


if __name__ == "__main__":
    unittest.main()
