# Neko BiliRelay v1.3.0

**AstrBot 插件 1.3.0 · dsh-bili-scroll 0.1.19 · 2026-10-20**

这是一个功能合并版本：AstrBot 插件新增完整 WebUI 控制台、主动 B 站私信和订阅私信转发；
同时包含移植到 `dsh-bili-scroll` 的评论 / 私信自动回复。

## 亮点

### AstrBot 插件 1.3.0

- **完整 WebUI 控制台**（替换原扫码登录页）：
  - 概览：登录态、订阅数、自动回复统计、轮询状态
  - 账号：扫码登录 / 退出、Cookie 来源与有效性
  - 主动私信：填 UID 或 `self`，直接发 B 站私信
  - 订阅：按会话 UMO 添加 / 删除 UP 主，选择投稿 / 动态 / 开播
  - 自动回复：运行状态、立即跑一轮、清空去重
- **配置开关在 AstrBot 插件配置页**：自动回复、订阅轮询、网络缓存、主动私信策略、Cookie
  等全部通过 `_conf_schema.json` 的原生配置界面修改；控制台不直接写 `config.json`。
- **主动私信**：
  - 聊天指令 `/bili send <UID/self> <文本>`，默认仅管理员
  - LLM 工具 `bilibili_send_dm`，默认关闭 + UID 白名单
  - 订阅推送可转发到 B 站私信（`off` / `both` / `only`）
- **评论 / 私信自动回复**：默认关；首次基线、rpid/msg_key 去重、冷却、每轮上限、私信白名单、dry-run。
- **修复**：子模块日志统一走 AstrBot 的插件 logger，避免出现
  `Formatting field not found in record: 'plugin_tag'`。

### dsh-bili-scroll 0.1.19（基于 c1overzz/dsh-bili-scroll）

> **上游署名**：`dsh-bili-scroll` 原作者 **c1overzz**，
> <https://github.com/c1overzz/dsh-bili-scroll>，MIT，Copyright (c) 2026 c1overzz。
> 本发布包保留上游 `LICENSE` 与 `NOTICE.md`；0.1.19 仅在 0.1.18 基础上新增自动回复。

- 新增 `lib/autoreply.mjs` 自动回复引擎；
- MCP 新增 `bili_latest_comments` / `bili_my_videos` / `bili_dm_sessions` / `bili_dm_messages`；
- 宿主定时器、配置、设置页和状态接口；
- 自动回复逻辑移植并改写自 **Neko BiliRelay**（MIT，Copyright (c) 2026 NekoHome）；
  读取层复用内置 bilibili-mcp（MIT，AGI_Ananas）。

## 资产

| 文件 | 用途 |
| --- | --- |
| `astrbot_plugin_bilirelay-1.3.0.zip` | AstrBot 插件，解压后目录名必须是 `astrbot_plugin_bilirelay` |
| `dsh-bili-scroll-0.1.19.zip` | DSH 插件源码包 |
| `dsh-bili-scroll-0.1.19.tgz` | DSH npm 包，含 `package.json` / `client.js` / `lib/autoreply.mjs` |
| `SHA256SUMS.txt` | 上述文件的 SHA-256 |

```text
686ed510e682f14c5fb286db6ff0f1cd21f1c1f7c8262e62449bf042dead5251  astrbot_plugin_bilirelay-1.3.0.zip
172f674a9714cd79c1ef244c6782533ccd9d01dc7c41075790458cfe4570906e  dsh-bili-scroll-0.1.19.zip
c8f7e74c011e4abf7ba9fe24892f72bbaf0e8f730fc036ac0fb763e1bb25e975  dsh-bili-scroll-0.1.19.tgz
```

校验：

```bash
sha256sum -c SHA256SUMS.txt
```

## AstrBot 安装

1. 下载 `astrbot_plugin_bilirelay-1.3.0.zip` 并解压；
2. 把解压出的 `astrbot_plugin_bilirelay/` 放到 AstrBot 的 `data/plugins/` 下
   （确保 `metadata.yaml` 就在这个目录里）；
3. 安装依赖：

   ```bash
   pip install -r astrbot_plugin_bilirelay/requirements.txt
   ```

4. 重启 AstrBot（或在 WebUI 插件管理里重载）；
5. 打开 **AstrBot WebUI → 插件管理 → Neko BiliRelay → B 站控制台**；
6. 先用「账号」扫码登录，再按需开启订阅 / 自动回复 / 主动私信。

> WebUI 控制台需要 AstrBot `>=4.26`；更早版本仍可用聊天指令和 LLM 工具。

### 从 1.2.0 升级

直接覆盖旧插件目录即可。订阅、登录凭据和自动回复状态在 AstrBot 的 `plugin_data` 目录，
不会随插件包覆盖；升级后重载插件，再到控制台确认登录态和设置。

## dsh-bili-scroll 安装

优先使用 npm 包：

```bash
dsh plugin --profile web add ./dsh-bili-scroll-0.1.19.tgz
```

或解压 `dsh-bili-scroll-0.1.19.zip`，把 `dsh-bili-scroll/` 作为插件目录安装。
安装后重启 DSH，在 **设置 → 刷B站** 里配置。

## 已知限制

- 主动私信、评论自动回复都需要 B 站登录；私信通常还要求账号绑定手机号。
- B 站评论 / 私信有频率限制，默认配置已限速；请从低频、白名单、dry-run 开始。
- 自动回复的“评论 / 私信”是模板或 LLM 回复，实际发送效果取决于登录账号状态和 B 站风控。
- 发布前未用真实账号做批量发送测试，只做了接口构造、离线逻辑和假请求验证。

## 出处与许可

- 本插件：MIT，Copyright (c) 2026 NekoHome。
- `dsh-bili-scroll/`：来自 **c1overzz/dsh-bili-scroll**，MIT，Copyright (c) 2026 c1overzz，
  <https://github.com/c1overzz/dsh-bili-scroll>；本仓库保留其 LICENSE 版权行与 NOTICE，
  0.1.19 新增部分为自动回复。
- 自动回复设计来源：**Neko BiliRelay**（`astrbot_plugin_bilirelay`），
  <https://github.com/qyac/bilirelay>。
- 内置 `vendor/bilibili-mcp`：MIT，Copyright (c) 2026 AGI_Ananas。
- 完整第三方声明见 `NOTICE.md` 与 `dsh-bili-scroll/NOTICE.md`。
