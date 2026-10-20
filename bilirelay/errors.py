"""Bilibili 接口错误类型与用户可读提示。"""

from __future__ import annotations


class BiliError(Exception):
    """B 站接口返回的非零 code，或网络层错误。"""

    def __init__(self, code: int | str, message: str = "", *, detail: str = "") -> None:
        self.code = code
        self.raw_message = message or ""
        self.detail = detail
        super().__init__(self.raw_message or str(code))

    @property
    def user_message(self) -> str:
        """把接口错误翻译成适合直接发给用户的中文提示。"""
        code = self.code
        known = {
            -1: "网络请求失败，请稍后重试",
            -101: "需要登录 B 站账号后才能使用该功能",
            -352: "触发了 B 站风控，请稍后重试；登录账号可以显著降低风控概率",
            -400: "请求参数有误，或内容不存在",
            -403: "没有访问权限",
            -404: "内容不存在或已被删除",
            -412: "请求被 B 站拦截（-412），请稍后重试，或更换网络 / 登录账号",
            -509: "请求过于频繁，请稍后重试",
            62002: "该稿件不可见（可能已删除或设为私密）",
            62004: "该稿件正在审核中",
            62008: "该稿件已被 UP 主删除",
            62012: "该稿件仅 UP 主自己可见",
            62014: "该稿件已被 UP 主设为私密",
        }
        if code in known:
            return known[code]
        if self.raw_message:
            return f"B 站接口返回错误（{code}）：{self.raw_message}"
        return f"B 站接口返回错误（{code}）"

    def __str__(self) -> str:
        return self.user_message


class NotLoggedIn(BiliError):
    """接口需要登录态（SESSDATA）。"""

    def __init__(self, feature: str = "") -> None:
        message = f"需要登录 B 站账号后才能{feature}" if feature else "需要登录 B 站账号"
        super().__init__(-101, message)

    @property
    def user_message(self) -> str:
        return self.raw_message


class RiskControl(BiliError):
    """-352 / -412 风控。"""

    def __init__(self, code: int = -352, message: str = "") -> None:
        super().__init__(code, message or "请求被 B 站风控拦截")

    @property
    def user_message(self) -> str:
        return (
            "触发了 B 站风控拦截，请稍后再试；"
            "登录 B 站账号、降低请求频率通常可以恢复。"
        )


class NotFound(BiliError):
    """内容不存在或无权访问。"""

    @property
    def user_message(self) -> str:
        return "没有找到对应的 B 站内容，可能已删除或不可见。"
