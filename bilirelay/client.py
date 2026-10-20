"""异步 Bilibili HTTP 客户端。

只依赖 httpx，自行处理：

* buvid3 / buvid4 / b_nut / bili_ticket 游客指纹
* WBI（wts + w_rid）签名
* Cookie 导入 / 导出
* 请求节流、短期缓存、风控重试
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import time
import urllib.parse
from collections import OrderedDict
from typing import Any, Iterable, Mapping

import httpx

from .errors import BiliError, NotLoggedIn, NotFound, RiskControl

from .logging_utils import logger

API_BASE = "https://api.bilibili.com"
PASSPORT_BASE = "https://passport.bilibili.com"
LIVE_BASE = "https://api.live.bilibili.com"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.bilibili.com/",
}

# WBI mixin key 重排表（公开算法）
_WBI_MIXIN_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
)

_RISK_CODES = {-352, -412, -509}
_LOGIN_CODES = {-101}
_NOT_FOUND_CODES = {-404, 62002, 62004, 62008, 62012, 62014}

# 风控时清理的游客指纹 Cookie，保留登录态
_FINGERPRINT_COOKIES = (
    "buvid3",
    "buvid4",
    "buvid_fp",
    "b_nut",
    "bili_ticket",
    "bili_ticket_expires",
    "_uuid",
    "b_lsid",
)


def mixin_key(img_key: str, sub_key: str) -> str:
    """将 nav 返回的 img_key/sub_key 重排为 32 位 mixin key。"""
    origin = img_key + sub_key
    return "".join(origin[i] for i in _WBI_MIXIN_TAB if i < len(origin))[:32]


def sign_wbi(params: Mapping[str, Any], key: str) -> dict[str, str]:
    """按 B 站 WBI 规则对参数签名，返回可直接用于请求的新字典。"""
    signed = {
        str(k): "".join(ch for ch in str(v) if ch not in "!'()*")
        for k, v in params.items()
    }
    signed["wts"] = str(int(time.time()))
    signed = dict(sorted(signed.items()))
    query = urllib.parse.urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + key).encode("utf-8")).hexdigest()
    return signed


def parse_cookie_string(cookie: str | Mapping[str, str] | None) -> dict[str, str]:
    """解析 ``a=1; b=2`` 形式的 Cookie 字符串。"""
    if not cookie:
        return {}
    if isinstance(cookie, Mapping):
        return {str(k).strip(): str(v).strip() for k, v in cookie.items() if k}
    result: dict[str, str] = {}
    for part in str(cookie).replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            result[name] = value.strip()
    return result


def _extract_keys(nav_data: Mapping[str, Any]) -> tuple[str, str] | None:
    wbi = nav_data.get("wbi_img") or {}
    img_url = str(wbi.get("img_url") or "")
    sub_url = str(wbi.get("sub_url") or "")
    if not img_url or not sub_url:
        return None
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    if not img_key or not sub_key:
        return None
    return img_key, sub_key


class BiliClient:
    """一个带会话状态的异步 B 站客户端。"""

    def __init__(
        self,
        cookie: str | Mapping[str, str] | None = "",
        *,
        timeout: float = 15.0,
        request_interval: float = 0.4,
        cache_ttl: int = 90,
        max_cache: int = 256,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout = timeout
        self.request_interval = max(0.0, request_interval)
        self.cache_ttl = max(0, cache_ttl)
        self.max_cache = max(16, max_cache)
        self._http = httpx.AsyncClient(
            headers=_BASE_HEADERS,
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=True,
            transport=transport,
        )
        self._cache: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._throttle_lock = asyncio.Lock()
        self._session_ready = False
        self._last_request = 0.0
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_expire = 0.0
        self._ticket_expire = 0.0
        self.last_voucher: str = ""
        self.cookies: dict[str, str] = {}
        self.update_cookies(parse_cookie_string(cookie))

    # ------------------------------------------------------------------ Cookie
    def update_cookies(self, cookies: Mapping[str, str], *, replace: bool = False) -> None:
        """写入 Cookie（默认合并），并同步到 httpx CookieJar。"""
        if replace:
            self.cookies.clear()
            self._http.cookies.clear()
        for name, value in cookies.items():
            if not name:
                continue
            self.cookies[name] = value
            try:
                self._http.cookies.set(name, value, domain=".bilibili.com", path="/")
            except (TypeError, ValueError):
                continue

    def update_cookies_from_string(self, cookie: str | Mapping[str, str] | None) -> None:
        """从 ``a=1; b=2`` 字符串导入 Cookie。"""
        self.update_cookies(parse_cookie_string(cookie))

    def export_cookie(self) -> str:
        """导出当前 Cookie（仅 bilibili.com 域），用于持久化。"""
        merged: dict[str, str] = {}
        for cookie in self._http.cookies.jar:
            domain = (cookie.domain or "").lstrip(".").lower()
            if domain and "bilibili.com" not in domain:
                continue
            if cookie.name:
                merged[cookie.name] = cookie.value
        merged.update(self.cookies)
        return "; ".join(f"{k}={v}" for k, v in merged.items() if v)

    def has_login_cookie(self) -> bool:
        return bool(self.cookies.get("SESSDATA"))

    def clear_login_cookie(self) -> None:
        """退出登录：删除登录 Cookie，但保留游客指纹。"""
        for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
            self.cookies.pop(name, None)
            try:
                self._http.cookies.delete(name, domain=".bilibili.com", path="/")
            except (KeyError, TypeError):
                pass

    def _clear_fingerprint(self) -> None:
        for name in _FINGERPRINT_COOKIES:
            self.cookies.pop(name, None)
            try:
                self._http.cookies.delete(name, domain=".bilibili.com", path="/")
            except (KeyError, TypeError):
                pass
        self._session_ready = False
        self._wbi_keys = None
        self._wbi_expire = 0.0
        self._ticket_expire = 0.0

    # --------------------------------------------------------------- HTTP 基础
    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "BiliClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _throttle(self) -> None:
        if self.request_interval <= 0:
            return
        async with self._throttle_lock:
            now = time.monotonic()
            wait = self.request_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _ensure_session(self) -> None:
        """准备游客指纹：buvid3/4、b_nut、bili_ticket。失败不影响主流程。"""
        if self._session_ready:
            return
        async with self._session_lock:
            if self._session_ready:
                return
            try:
                resp = await self._http.get(f"{API_BASE}/x/frontend/finger/spi")
                data = resp.json().get("data") or {}
                b3, b4 = data.get("b_3"), data.get("b_4")
                if b3:
                    self.update_cookies({"buvid3": str(b3)})
                if b4:
                    self.update_cookies({"buvid4": str(b4)})
                self.update_cookies({"b_nut": str(int(time.time()))})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.debug("获取 B 站游客指纹失败：%s", exc)
            await self._refresh_ticket()
            self._session_ready = True

    async def _refresh_ticket(self) -> None:
        """生成 bili_ticket，可降低游客请求被风控的概率。"""
        if self._ticket_expire and time.time() < self._ticket_expire - 300:
            return
        ts = int(time.time())
        hexsign = hmac.new(
            b"XgwSnGZ1p", f"ts{ts}".encode(), hashlib.sha256
        ).hexdigest()
        try:
            resp = await self._http.post(
                f"{API_BASE}/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket",
                params={
                    "key_id": "ec02",
                    "hexsign": hexsign,
                    "context[ts]": ts,
                    "csrf": self.cookies.get("bili_jct", ""),
                },
                headers={"Referer": "https://www.bilibili.com/"},
            )
            payload = resp.json()
            data = payload.get("data") or {}
            ticket = data.get("ticket")
            if payload.get("code") == 0 and ticket:
                created = int(data.get("created_at") or ts)
                ttl = int(data.get("ttl") or 259200)
                self.update_cookies(
                    {
                        "bili_ticket": str(ticket),
                        "bili_ticket_expires": str(created + ttl),
                    }
                )
                self._ticket_expire = created + ttl
        except Exception as exc:  # noqa: BLE001 - 游客票据失败不应中断请求
            logger.debug("生成 bili_ticket 失败：%s", exc)

    async def _get_wbi_keys(self, *, force: bool = False) -> tuple[str, str]:
        now = time.time()
        if not force and self._wbi_keys and now < self._wbi_expire:
            return self._wbi_keys
        resp = await self._http.get(
            f"{API_BASE}/x/web-interface/nav",
            headers={"Referer": "https://www.bilibili.com/"},
        )
        if resp.status_code in (412, 429):
            raise RiskControl(-412 if resp.status_code == 412 else -509)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RiskControl(-412, "获取 WBI 密钥失败") from exc
        keys = _extract_keys(payload.get("data") or {})
        if not keys:
            raise BiliError(payload.get("code", -1), "无法获取 WBI 签名密钥")
        self._wbi_keys = keys
        self._wbi_expire = now + 600
        return keys

    async def _sign(self, params: Mapping[str, Any], *, force_keys: bool = False) -> dict[str, str]:
        img_key, sub_key = await self._get_wbi_keys(force=force_keys)
        return sign_wbi(params, mixin_key(img_key, sub_key))

    # ------------------------------------------------------------------ 缓存
    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self.cache_ttl <= 0:
            return None
        async with self._cache_lock:
            item = self._cache.get(key)
            if not item:
                return None
            created, payload = item
            if time.time() - created > self.cache_ttl:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return payload

    async def _cache_set(self, key: str, payload: dict[str, Any]) -> None:
        if self.cache_ttl <= 0:
            return
        async with self._cache_lock:
            self._cache[key] = (time.time(), payload)
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_cache:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------ 请求
    async def request_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        signed: bool = False,
        method: str = "GET",
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        referer: str | None = None,
        no_cache: bool = False,
        retries: int = 2,
        allow_codes: Iterable[int] = (),
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """请求 B 站 JSON 接口，返回完整响应体（含 code/message/data）。

        Args:
            path: 完整 URL 或以 ``/`` 开头的 API 路径。
            params: URL 查询参数。
            signed: 是否进行 WBI 签名。
            method: GET / POST。
            data: POST 表单。
            headers: 额外请求头。
            referer: 覆盖 Referer。
            no_cache: 跳过缓存。
            retries: 风控 / 网络错误时的额外重试次数。
            allow_codes: 不视为错误的返回码（例如 nav 的 -101）。
            timeout: 单次请求超时覆盖。
        """
        url = path if path.startswith("http") else API_BASE + path
        query = {k: v for k, v in (params or {}).items() if v is not None}
        allowed = {int(c) for c in allow_codes}
        cache_key = ""
        if method.upper() == "GET" and not no_cache and self.cache_ttl > 0:
            raw = url + "|" + urllib.parse.urlencode(sorted(query.items()), doseq=True)
            cache_key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
            cached = await self._cache_get(cache_key)
            if cached is not None:
                return cached

        await self._ensure_session()
        request_headers = {"Referer": referer} if referer else {}
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        for attempt in range(max(0, retries) + 1):
            await self._throttle()
            try:
                signed_params = (
                    await self._sign(query, force_keys=attempt > 0)
                    if signed
                    else dict(query)
                )
                kwargs: dict[str, Any] = {
                    "params": signed_params,
                    "headers": request_headers,
                }
                if timeout is not None:
                    kwargs["timeout"] = timeout
                if method.upper() == "POST":
                    kwargs["data"] = dict(data or {})
                    resp = await self._http.post(url, **kwargs)
                else:
                    resp = await self._http.get(url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("B 站请求失败（%s）：%s", url, exc)
                if attempt < retries:
                    await asyncio.sleep(1.0 + attempt * 1.2 + random.random() * 0.4)
                    continue
                raise BiliError(-1, "网络请求失败，请稍后重试") from exc

            try:
                payload = self._decode_payload(resp, url)
            except RiskControl as exc:
                if attempt < retries:
                    logger.warning(
                        "B 站请求被拦截（HTTP %s），重建游客会话后重试（%s/%s）",
                        resp.status_code,
                        attempt + 1,
                        retries,
                    )
                    self._clear_fingerprint()
                    await self._ensure_session()
                    await asyncio.sleep(1.2 + attempt * 1.6 + random.random() * 0.5)
                    continue
                raise exc
            code = payload.get("code", 0)
            try:
                code = int(code)
            except (TypeError, ValueError):
                code = 0
            message = ""

            if code == 0:
                # B 站有时会返回 code=0，但 data 里只有 v_voucher（实质是风控）
                data = payload.get("data")
                if (
                    isinstance(data, dict)
                    and data.get("v_voucher")
                    and set(data).issubset({"v_voucher", "gaia_res_type", "gaia_data"})
                ):
                    code = -352
                    message = "风控校验失败"
                else:
                    if cache_key:
                        await self._cache_set(cache_key, payload)
                    return payload
            if code in allowed:
                return payload

            message = str(payload.get("message") or message or "")
            if code in _LOGIN_CODES:
                raise NotLoggedIn()
            if code in _NOT_FOUND_CODES:
                raise NotFound(code, message)
            if code in _RISK_CODES:
                if attempt < retries:
                    voucher = (payload.get("data") or {}).get("v_voucher") or ""
                    if voucher:
                        self.last_voucher = str(voucher)
                    logger.warning(
                        "B 站风控 code=%s，重建游客会话后重试（%s/%s）",
                        code,
                        attempt + 1,
                        retries,
                    )
                    self._clear_fingerprint()
                    await self._ensure_session()
                    await asyncio.sleep(1.2 + attempt * 1.6 + random.random() * 0.5)
                    continue
                raise RiskControl(code, message)

            raise BiliError(code, message)

        raise BiliError(-1, str(last_error) if last_error else "请求失败")

    @staticmethod
    def _decode_payload(resp: httpx.Response, url: str) -> dict[str, Any]:
        if resp.status_code in (412, 429) and "json" not in (
            resp.headers.get("content-type") or ""
        ):
            raise RiskControl(-412 if resp.status_code == 412 else -509)
        try:
            payload = resp.json()
        except ValueError as exc:
            if resp.status_code in (412, 429):
                raise RiskControl(-412 if resp.status_code == 412 else -509) from exc
            raise BiliError(-1, f"接口返回了非 JSON 内容（HTTP {resp.status_code}）") from exc
        if not isinstance(payload, dict):
            raise BiliError(-1, "接口返回格式异常")
        return payload

    async def request_data(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """请求接口并只返回 ``data`` 字段。"""
        payload = await self.request_json(path, params, **kwargs)
        return payload.get("data")

    async def request_text(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        referer: str = "https://www.bilibili.com/",
        retries: int = 1,
    ) -> str:
        """请求非 JSON 资源（例如弹幕 XML）。"""
        await self._ensure_session()
        for attempt in range(max(0, retries) + 1):
            await self._throttle()
            try:
                resp = await self._http.get(
                    url,
                    params=dict(params or {}),
                    headers={"Referer": referer, "Accept": "*/*"},
                )
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (412, 429):
                    raise RiskControl(-412 if resp.status_code == 412 else -509)
                raise BiliError(-1, f"HTTP {resp.status_code}")
            except httpx.HTTPError as exc:
                if attempt < retries:
                    await asyncio.sleep(1.0 + random.random() * 0.5)
                    continue
                raise BiliError(-1, "网络请求失败，请稍后重试") from exc
        raise BiliError(-1, "请求失败")

    async def resolve_redirect(self, url: str) -> str:
        """解析 b23.tv 等短链，返回最终 URL。"""
        await self._ensure_session()
        try:
            resp = await self._http.get(url)
            return str(resp.url)
        except httpx.HTTPError as exc:
            raise BiliError(-1, "短链解析失败") from exc

    # ------------------------------------------------------------------ 账号
    async def nav_info(self) -> dict[str, Any]:
        """获取当前登录状态；未登录也返回 wbi 信息，不抛异常。"""
        payload = await self.request_json(
            "/x/web-interface/nav",
            no_cache=True,
            retries=1,
            allow_codes=(-101,),
        )
        data = payload.get("data") or {}
        return {
            "is_login": bool(data.get("isLogin")),
            "mid": data.get("mid") or 0,
            "uname": data.get("uname") or "",
            "face": data.get("face") or "",
            "level": (data.get("level_info") or {}).get("current_level", 0),
            "vip_status": data.get("vipStatus", 0),
            "vip_label": ((data.get("vip_label") or {}).get("text") or ""),
            "code": payload.get("code", 0),
        }

    async def generate_qr(self) -> dict[str, Any]:
        """申请 Web 端扫码登录二维码。"""
        payload = await self.request_json(
            f"{PASSPORT_BASE}/x/passport-login/web/qrcode/generate",
            no_cache=True,
        )
        data = payload.get("data") or {}
        if not data.get("url") or not data.get("qrcode_key"):
            raise BiliError(-1, "获取登录二维码失败")
        return {
            "url": str(data["url"]),
            "qrcode_key": str(data["qrcode_key"]),
            "expires_in": 180,
        }

    async def poll_qr(self, qrcode_key: str) -> dict[str, Any]:
        """轮询扫码状态。

        Returns:
            ``{"state": waiting|scanned|confirmed|expired, ...}``
        """
        payload = await self.request_json(
            f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll",
            {"qrcode_key": qrcode_key},
            no_cache=True,
        )
        data = payload.get("data") or {}
        code = int(data.get("code", -1))
        state_map = {0: "confirmed", 86038: "expired", 86090: "scanned", 86101: "waiting"}
        state = state_map.get(code, "waiting")
        result = {
            "state": state,
            "code": code,
            "message": data.get("message") or "",
        }
        if state == "confirmed":
            # 登录成功时 Cookie 通过 Set-Cookie 写入，url 里也可能带一份
            cookies_from_url = self._parse_qr_redirect(str(data.get("url") or ""))
            if cookies_from_url:
                self.update_cookies(cookies_from_url)
            self.update_cookies(self._cookies_from_jar())
            self._session_ready = False
            self._wbi_keys = None
            self._wbi_expire = 0.0
        return result

    @staticmethod
    def _parse_qr_redirect(url: str) -> dict[str, str]:
        if not url:
            return {}
        parsed = urllib.parse.urlparse(url)
        values = urllib.parse.parse_qs(parsed.query)
        return {
            key: values[key][0]
            for key in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
            if values.get(key)
        }

    def _cookies_from_jar(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for cookie in self._http.cookies.jar:
            domain = (cookie.domain or "").lstrip(".").lower()
            if domain and "bilibili.com" not in domain:
                continue
            if cookie.name:
                cookies[cookie.name] = cookie.value
        return cookies

    def reset_session(self) -> None:
        """清空游客指纹和缓存（不清登录态）。"""
        self._clear_fingerprint()
        self.clear_cache()
