# 第三方代码与署名说明

本插件（`dsh-bili-scroll` / 刷B站）本体以 **MIT** 协议发布，正文见仓库根目录的 `LICENSE`。

## 上游项目

`dsh-bili-scroll/` 来自 **c1overzz/dsh-bili-scroll**：

- 项目：<https://github.com/c1overzz/dsh-bili-scroll>
- 许可证：**MIT**，Copyright (c) 2026 c1overzz
- 本仓库在 0.1.18 的基础上新增了评论 / 私信自动回复（0.1.19），
  其余代码、文档、提示词与设置页均归上游作者；`LICENSE` 中保留原始版权行。

## 内含第三方代码

- 目录：`vendor/bilibili-mcp/`
- 项目：**bilibili-mcp**
- 许可证：**MIT**，Copyright (c) 2026 AGI_Ananas
- 完整许可见该目录下的 `LICENSE`

## 关于版权署名

`LICENSE` 第一行写的是 `Copyright (c) 2026 c1overzz`。
如果你要基于本仓库做二次分发，保留这一行和 MIT 正文即可，不必另行取得授权（MIT 本身就允许改、再发、商用）。

---
*本文件只是说明，不构成额外限制。*
## 本次新增：自动回复评论 / 私信

- 文件：`lib/autoreply.mjs`、`vendor/bilibili-mcp/mcp_server.py` 中的
  `bili_latest_comments` / `bili_my_videos` / `bili_dm_sessions` / `bili_dm_messages`，
  以及 `index.js` / `client.js` 里的自动回复配置与设置页。
- 来源：**Neko BiliRelay**（AstrBot 插件 `astrbot_plugin_bilirelay`）
  - 许可证：**MIT**，Copyright (c) 2026 NekoHome
  - 项目地址：<https://github.com/qyac/bilirelay>
  - 移植内容：评论/私信轮询、首次基线、rpid/msg_key 去重、按用户冷却、每轮上限、
    私信白名单、dry-run、模板渲染等设计；原实现为自建 B 站 HTTP 客户端，
    本仓库改写为复用内置的 `vendor/bilibili-mcp`（bilibili-api-python）。

> MIT 允许修改、再分发与商用；此处保留原作者署名，方便追溯来源。
