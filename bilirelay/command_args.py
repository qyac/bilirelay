"""指令参数解析小工具（与 AstrBot 解耦，方便单元测试）。"""

from __future__ import annotations

import re
from typing import Iterable

_LEADING_PUNCT = "/!！。,#＃~～"


def normalize_text(text: str) -> str:
    """统一全角空格、去除多余空白。"""
    return re.sub(r"\s+", " ", (text or "").replace("\u3000", " ")).strip()


def strip_command(
    message: str,
    group_names: Iterable[str],
    sub_names: Iterable[str],
) -> str:
    """从完整消息中剥离 ``/bili search`` 前缀，返回剩余参数文本。

    兼容平台自带唤醒前缀（``/``、``!`` 等）以及 ``@bot`` 被适配器移除后
    只剩下 ``bili search`` 的情况。
    """
    text = normalize_text(message)
    if not text:
        return ""
    groups = {name.lower() for name in group_names}
    subs = {name.lower() for name in sub_names}
    tokens = text.split(" ")
    cleaned: list[str] = []
    for index, token in enumerate(tokens):
        value = token
        if index == 0:
            value = value.lstrip(_LEADING_PUNCT)
        cleaned.append(value)

    # 找到指令组位置（通常在第 0/1 个 token）
    group_index = -1
    for index, token in enumerate(cleaned[:3]):
        if token.lstrip(_LEADING_PUNCT).lower() in groups:
            group_index = index
            break
    if group_index >= 0:
        rest = cleaned[group_index + 1 :]
        if rest and rest[0].lower() in subs:
            rest = rest[1:]
        return " ".join(rest).strip()

    # 适配器可能已经把指令组去掉，只留下子指令
    for index, token in enumerate(cleaned[:2]):
        if token.lower() in subs:
            return " ".join(cleaned[index + 1 :]).strip()
    return text


def split_args(text: str) -> list[str]:
    """按空白拆分参数，保留带空格的剩余文本时用 ``join``。"""
    return [part for part in normalize_text(text).split(" ") if part]


def to_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_sub_types(values: Iterable[str]) -> list[str]:
    """解析订阅类型：``视频 动态`` / ``video,dynamic`` / ``all``。"""
    aliases = {
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
    result: set[str] = set()
    for raw in values:
        for part in re.split(r"[,，/、\s]+", str(raw).strip()):
            if not part:
                continue
            mapped = aliases.get(part.lower(), aliases.get(part))
            if mapped == "all":
                return ["video", "dynamic", "live"]
            if mapped:
                result.add(mapped)
    return [t for t in ("video", "dynamic", "live") if t in result] or [
        "video",
        "dynamic",
        "live",
    ]
