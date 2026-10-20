"""B 站账号登录态管理（Cookie 持久化 + 扫码登录）。"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .client import BiliClient

from .logging_utils import logger


class CredentialStore:
    """把 Cookie 持久化到 AstrBot 的 plugin_data 目录。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        try:
            if self.path.is_file():
                with self.path.open(encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self._data = data
        except (OSError, ValueError) as exc:
            logger.warning("读取 B 站登录凭据失败：%s", exc)
            self._data = {}
        return self._data

    def save(self, cookie: str, user: dict[str, Any] | None = None) -> None:
        self._data = {
            "cookie": cookie,
            "user": user or {},
            "updated_at": int(time.time()),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            temp.replace(self.path)
        except OSError as exc:
            logger.warning("保存 B 站登录凭据失败：%s", exc)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> None:
        self._data = {}
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除 B 站登录凭据失败：%s", exc)

    @property
    def cookie(self) -> str:
        return str(self._data.get("cookie") or "")

    @property
    def user(self) -> dict[str, Any]:
        value = self._data.get("user")
        return value if isinstance(value, dict) else {}


class AuthManager:
    """管理当前 B 站账号：配置 Cookie、扫码登录、状态查询。"""

    def __init__(
        self,
        client: BiliClient,
        store: CredentialStore,
        *,
        config_cookie: str = "",
    ) -> None:
        self.client = client
        self.store = store
        self.config_cookie = (config_cookie or "").strip()
        self.user: dict[str, Any] = {}
        self._loaded = False
        self._last_check = 0.0

    async def load(self) -> dict[str, Any]:
        """加载持久化 Cookie，并校验登录状态。网络失败时静默降级为游客。"""
        if self._loaded:
            return self.status()
        self._loaded = True
        self.store.load()
        cookie = self.store.cookie or self.config_cookie
        if cookie:
            self.client.update_cookies_from_string(cookie)
        if not self.client.has_login_cookie():
            self.user = {}
            return self.status()
        try:
            await self.refresh_user(force=True)
        except Exception as exc:  # noqa: BLE001 - 启动阶段不应因网络失败崩溃
            logger.warning("检查 B 站登录状态失败：%s", exc)
            self.user = self.store.user
        return self.status()

    async def refresh_user(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and now - self._last_check < 60:
            return self.user
        nav = await self.client.nav_info()
        self._last_check = now
        if nav.get("is_login"):
            self.user = {
                "uid": nav.get("mid"),
                "name": nav.get("uname"),
                "face": nav.get("face"),
                "level": nav.get("level"),
                "vip": nav.get("vip_label"),
            }
            # 如果是从配置 Cookie 登录的，也持久化一份，便于页面显示
            if not self.store.cookie and self.client.has_login_cookie():
                self.store.save(self.client.export_cookie(), self.user)
            return self.user

        # 持久化 Cookie 失效时，尝试回退到配置里的 Cookie
        if self.config_cookie and self.config_cookie != self.store.cookie:
            self.client.update_cookies_from_string(self.config_cookie)
            nav = await self.client.nav_info()
            if nav.get("is_login"):
                self.user = {
                    "uid": nav.get("mid"),
                    "name": nav.get("uname"),
                    "face": nav.get("face"),
                    "level": nav.get("level"),
                    "vip": nav.get("vip_label"),
                }
                return self.user
        # 登录态确实失效：清掉过期的 Cookie，避免状态栏误报“已登录”
        self.client.clear_login_cookie()
        if self.store.cookie:
            self.store.clear()
        self.user = {}
        return self.user

    def status(self) -> dict[str, Any]:
        logged_in = self.client.has_login_cookie()
        return {
            "logged_in": logged_in,
            "user": self.user if logged_in else {},
            "source": "qr" if self.store.cookie else ("config" if self.config_cookie else "guest"),
            "has_config_cookie": bool(self.config_cookie),
        }

    async def generate_qr(self) -> dict[str, Any]:
        qr = await self.client.generate_qr()
        qr["svg"] = make_qr_svg(qr["url"])
        qr["png_base64"] = make_qr_png_base64(qr["url"])
        return qr

    async def poll_qr(self, qrcode_key: str) -> dict[str, Any]:
        result = await self.client.poll_qr(qrcode_key)
        # 不要把内部 Cookie 暴露给页面 / 聊天消息
        result.pop("cookies", None)
        if result.get("state") == "confirmed":
            await self.refresh_user(force=True)
            if not self.client.has_login_cookie():
                raise RuntimeError("扫码成功，但没有拿到登录 Cookie，请重试")
            self.store.save(self.client.export_cookie(), self.user)
            result["user"] = self.user
        return result

    async def logout(self) -> dict[str, Any]:
        self.client.clear_login_cookie()
        self.client.reset_session()
        self.store.clear()
        self.user = {}
        self._last_check = 0.0
        return self.status()

    def ensure_login(self, feature: str = "") -> None:
        from .errors import NotLoggedIn

        if not self.client.has_login_cookie():
            raise NotLoggedIn(feature)


def make_qr_svg(url: str) -> str:
    """生成二维码 SVG；缺少 qrcode 依赖时返回空字符串。"""
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return ""
    try:
        image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("生成二维码 SVG 失败：%s", exc)
        return ""


def make_qr_png_base64(url: str) -> str:
    """生成二维码 PNG（base64），用于聊天窗口直接发图。"""
    try:
        import base64

        import qrcode
    except ImportError:
        return ""
    try:
        image = qrcode.make(url)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        logger.debug("生成二维码 PNG 失败：%s", exc)
        return ""
