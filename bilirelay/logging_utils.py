"""统一日志入口。

⚠️ AstrBot 的队列/控制台 Formatter 会读取 ``record.plugin_tag``。
直接 ``logging.getLogger("astrbot.plugin.xxx")`` 产生的记录不会经过 AstrBot 的
``_RecordEnricherFilter``，一旦有 WARNING/ERROR 就会报：

    Formatting field not found in record: 'plugin_tag'

所以子模块统一用 ``astrbot.api.logger``（它会路由到当前插件的专用 logger，
并带上 plugin_tag）；脱离 AstrBot 单独运行时退回 ``astrbot`` logger。
"""

from __future__ import annotations

import logging

try:  # AstrBot 运行时
    from astrbot.api import logger as logger
except ImportError:  # pragma: no cover - 独立运行/测试兜底
    logger = logging.getLogger("astrbot")

__all__ = ["logger"]
