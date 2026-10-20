# Neko BiliRelay

让 AstrBot **完整接入 Bilibili** 的插件：把 B 站搜索、视频/UP 主/动态/直播/番剧/专栏查询、字幕与 AI 总结、热门榜单，做成聊天指令和 **LLM 工具**；同时支持 UP 主**新投稿 / 新动态 / 开播**的主动订阅推送、**评论 / 私信自动回复**，以及 WebUI 扫码登录。

> 插件名：`astrbot_plugin_bilirelay` · 版本：`1.2.0` · 作者：NekoHome

## 功能

### 聊天指令

| 指令 | 说明 |
| --- | --- |
| `/bili help` | 显示指令帮助 |
| `/bili search <关键词> [类型]` | 搜索视频、用户、直播、番剧、专栏 |
| `/bili video <BV/av/链接>` | 视频详情：UP 主、播放/弹幕/收藏/投币、时长、简介 |
| `/bili summary <BV/av/链接>` | 视频 AI 总结与分段提纲（需登录） |
| `/bili subtitle <BV/av/链接> [语言]` | 读取视频字幕（AI 字幕需登录） |
| `/bili comments <BV/av/链接> [页码]` | 热门评论 |
| `/bili danmaku <BV/av/链接> [数量]` | 弹幕 |
| `/bili up <UID/空间链接>` | UP 主资料 + 最近投稿 |
| `/bili videos <UID> [页码]` | UP 主投稿列表 |
| `/bili dynamics <UID> [数量]` | UP 主最新动态 |
| `/bili dynamic <动态ID/链接>` | 单条动态详情 |
| `/bili live <UID/房间号/链接>` | 直播状态、标题、人气 |
| `/bili hot` / `/bili hot search` | 热门视频 / 热搜 |
| `/bili rank [分区]` | 排行榜（全站、动画、音乐、游戏、知识……） |
| `/bili article <cv号/链接>` | 专栏文章摘要 |
| `/bili bangumi <ss/ep/链接>` | 番剧/影视信息 |
| `/bili fav <收藏夹ID>` | 公开收藏夹内容 |
| `/bili sub add <UID> [视频/动态/直播]` | 订阅 UP 主更新 |
| `/bili sub del <UID>` / `sub list` / `sub check` | 取消、查看、立即检查订阅 |
| `/bili login` | 查看登录态；未登录时发送扫码二维码 |
| `/bili whoami` | 当前登录账号 |
| `/bili logout` | 退出登录（仅管理员） |
| `/bili autoreply status` | 查看自动回复状态（仅管理员） |
| `/bili autoreply on` / `off` | 启动 / 停止自动回复任务（仅管理员） |
| `/bili autoreply test <文本>` | 预览一条自动回复，不发送（仅管理员） |
| `/bili autoreply reset` | 清空去重状态并重新建立基线（仅管理员） |
| `/bili send <UID/self> <文本>` | 用 B 站账号主动发一条私信（默认仅管理员） |

指令组别名：`/bili`、`/b站`、`/哔哩哔哩`。

### LLM 工具（Function Calling）

开启后，大模型可以在对话中自动调用：

`bilibili_search`、`bilibili_video`、`bilibili_video_summary`、`bilibili_video_subtitle`、`bilibili_video_comments`、`bilibili_video_danmaku`、`bilibili_user`、`bilibili_user_videos`、`bilibili_user_dynamics`、`bilibili_live`、`bilibili_hot`、`bilibili_rank`、`bilibili_article`、`bilibili_bangumi`、`bilibili_fav`、`bilibili_send_dm`。

所有工具都可以在配置里单独关闭，避免工具 schema 占用过多上下文。弹幕、排行榜、收藏夹、主动私信工具默认关闭。主动私信还要求 `enable_llm_send_dm=true` 且对方在 `llm_send_dm_whitelist` 中。

### 订阅推送

- **新投稿**：检测到 UP 主发布新视频时推送标题、播放量、时长和链接。
- **新动态**：检测到 UP 主发布动态时推送正文、视频卡片或图片数量。
- **开播提醒**：检测到 UP 主从「未开播」变为「直播中」时推送直播间标题和链接。
- 订阅按会话（群聊/私聊）隔离，每个会话有数量上限。
- 首次添加会先记录当前基线，不会把旧内容当成新内容刷屏。
- 后台轮询默认 5 分钟一次，可在配置中调整。

### 自动回复评论 / 私信

使用**你自己的 B 站账号**自动回复视频评论和私信。默认关闭，必须登录后显式开启。

- **评论**：监控指定 BV 号，或自动监控自己最近的投稿；检测到新的一级评论（可选楼中楼）后生成回复。
- **私信**：轮询私信会话，只回复普通用户发来的文字私信。
- **回复来源**：模板（便宜、可控）或 LLM（默认，使用 `auto_reply_provider` 指定的 Provider；未指定时使用默认对话模型）。
- **安全限制**：首次轮询只记录基线，不回复历史消息；按评论 `rpid` / 私信 `msg_key` 去重；同一用户有冷却时间；每轮有数量上限；默认私信只回复白名单，`dm_allow_all` 才回复所有陌生人。
- **dry-run**：`auto_reply_dry_run=true` 时只写日志不发送，适合先观察生成效果。
- **测试**：`/bili autoreply test 你好呀` 可以预览一条评论回复，不会发送。

启用步骤：

1. 扫码登录，或配置 Cookie（需要 `SESSDATA` 和 `bili_jct`，扫码登录会自动保存）；
2. 配置 `enable_auto_reply=true`；
3. 评论：`auto_reply_comments=true`，可选填 `comment_targets`（留空自动监控最近投稿）；
4. 私信：`auto_reply_dms=true`，填写 `dm_whitelist`，或明确打开 `dm_allow_all`；
5. 建议先打开 `auto_reply_dry_run=true`，用 `/bili autoreply test` 和日志确认效果，再关闭；
6. `/bili autoreply on` 启动运行时任务，`/bili autoreply status` 查看状态。

> 修改自动回复相关配置后，建议在 WebUI 重载插件，或先 `/bili autoreply off` 再 `/bili autoreply on`，让新的轮询间隔/白名单生效。

> B 站对评论/私信发送有严格频率限制。未绑定手机号的账号可能无法发私信（错误码 `21015`），发送过快会触发 `21020/21046`。插件会限制每轮数量并做冷却，但请自行控制频率，避免账号被限制。

### 主动发 B 站私信

除“自动回复”外，也可以让插件**主动**用你的 B 站账号发私信：

- **聊天指令**：`/bili send <UID/self> <文本>`。默认仅管理员可用；`self` 表示发给自己，适合先测试。
- **LLM 工具**：`bilibili_send_dm`。默认关闭；开启 `enable_llm_send_dm` 后，仍只允许发给 `llm_send_dm_whitelist` 里的 UID（或自己）。
- **订阅转发**：`subscription_dm_uid` + `subscription_dm_mode` 可把新投稿/新动态/开播推送转发到 B 站私信；
  `mode=both` 同时发聊天，`mode=only` 只发私信（发送失败会自动回退聊天）。
- **dry-run**：`send_dm_dry_run=true` 时命令/工具只预览不发送，方便确认内容。

> 私信会拿你的号主动打扰别人，也可能触发 B 站频率限制；默认仅管理员、默认关闭 LLM 工具、默认白名单。
> 未绑定手机号的账号可能无法发私信。

### 扫码登录

- 打开 AstrBot WebUI → 插件管理 → Neko BiliRelay → 页签「B 站账号与订阅」。
- 点击「生成登录二维码」，用 B 站手机客户端扫码并确认。
- 登录成功后 Cookie 自动保存到 AstrBot 的 `plugin_data` 目录，重启后仍然有效。
- 也可以直接在聊天里发送 `/bili login`，插件会发送二维码并在后台等待扫码结果。
- 也可以不用扫码，在插件配置里粘贴浏览器 Cookie（至少需要 `SESSDATA`）。

> 登录不是必须的。游客模式可以使用搜索、视频、评论、弹幕、用户、直播、榜单、番剧和公开收藏夹；AI 字幕、AI 总结、动态接口和部分投稿接口在登录后更稳定。

## 安装

### 方式一：手动放入插件目录

```bash
cd AstrBot/data/plugins
git clone <本仓库地址> astrbot_plugin_bilirelay
```

**目录名建议使用 `astrbot_plugin_bilirelay`**（与 `metadata.yaml` 的 `name` 一致）。如果直接从仓库名安装，AstrBot 可能把目录命名为 `neko_bilirelay`，这也能加载，但配置文件名会跟着目录名变化。

然后在 AstrBot WebUI → 插件管理 → 安装/重载插件，或重启 AstrBot。

### 方式二：从 WebUI 安装

在插件市场/「从仓库安装」中填入本仓库地址。安装完成后进入插件详情页，按提示安装依赖（`requirements.txt`）。

### 依赖

```text
httpx>=0.27
qrcode>=7.4
pillow>=9.0
```

AstrBot 本身通常已经带有 `httpx` 和 `Pillow`；`qrcode` 用于扫码登录（缺失时页面仍会显示登录链接，但无法显示二维码图片）。

## 配置

配置文件：`data/config/<插件目录名>_config.json`，也可以在 WebUI 插件配置页编辑。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `cookie` | string（secret） | 空 | B 站 Cookie；留空则使用扫码登录或游客模式 |
| `enable_llm_tools` | bool | `true` | 是否向 LLM 注册工具 |
| `llm_tools` | object | 见默认 | 单独开关每个工具 |
| `enable_subscriptions` | bool | `true` | 启用订阅轮询 |
| `subscription_interval` | int | `5` | 轮询间隔（分钟），最小 1 分钟 |
| `subscription_notify` | object | 全开 | 投稿/动态/开播推送开关 |
| `max_subscriptions` | int | `20` | 每个会话最多订阅的 UP 数 |
| `push_cover` | bool | `false` | 推送时附带封面图 |
| `login_qr_in_chat` | bool | `true` | 允许在聊天中发送登录二维码 |
| `send_dm_admin_only` | bool | `true` | `/bili send` 仅管理员可用 |
| `send_dm_dry_run` | bool | `false` | 主动私信只预览不发送 |
| `enable_llm_send_dm` | bool | `false` | 允许 LLM 工具主动发私信 |
| `llm_send_dm_whitelist` | string | 空 | LLM 主动私信白名单 UID |
| `subscription_dm_uid` | string | 空 | 订阅推送转发到 B 站私信的目标 UID；可填 `self` |
| `subscription_dm_mode` | string | `off` | `off` / `both` / `only` |
| `request_interval` | float | `0.45` | 请求最小间隔（秒），用于降低风控 |
| `timeout` | int | `15` | HTTP 超时（秒） |
| `cache_ttl` | int | `90` | 接口缓存时间（秒），`0` 关闭 |
| `max_reply_chars` | int | `1800` | 单条回复最大字符数 |

### 自动回复配置

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable_auto_reply` | bool | `false` | 自动回复总开关 |
| `auto_reply_provider` | string | 空 | LLM Provider ID；留空使用默认对话模型 |
| `auto_reply_system_prompt` | text | 空 | 自定义人设/提示词 |
| `auto_reply_max_chars` | int | `200` | 自动回复最大字数 |
| `auto_reply_reply_interval` | float | `3` | 两条回复之间的最小间隔（秒） |
| `auto_reply_dry_run` | bool | `false` | 只写日志，不发送 |
| `auto_reply_comments` | bool | `true` | 评论自动回复 |
| `comment_targets` | string | 空 | 监控的 BV 号，逗号分隔；留空自动监控最近投稿 |
| `comment_auto_videos` | bool | `true` | 自动监控自己的最近投稿 |
| `comment_video_limit` | int | `5` | 自动监控的视频数 |
| `comment_poll_interval` | int | `180` | 评论轮询间隔（秒） |
| `comment_include_replies` | bool | `false` | 是否也回复楼中楼 |
| `comment_max_per_round` | int | `3` | 每轮最多回复评论数 |
| `comment_cooldown_minutes` | int | `30` | 同一用户评论冷却（分钟） |
| `comment_max_age_minutes` | int | `180` | 只回复多少分钟内的评论 |
| `comment_min_chars` | int | `2` | 评论最短字数 |
| `comment_ignore_keywords` | string | 空 | 命中就不回复的关键词，逗号分隔 |
| `comment_reply_mode` | string | `llm` | `llm` 或 `template` |
| `comment_template` | text | `感谢你的评论，{user}！` | 模板模式内容 |
| `auto_reply_dms` | bool | `false` | 私信自动回复 |
| `dm_allow_all` | bool | `false` | 回复所有私信用户；默认只回复白名单 |
| `dm_whitelist` | string | 空 | 私信白名单 UID，逗号分隔 |
| `dm_blacklist` | string | 空 | 私信黑名单 UID，优先级更高 |
| `dm_poll_interval` | int | `120` | 私信轮询间隔（秒） |
| `dm_max_per_round` | int | `3` | 每轮最多回复私信数 |
| `dm_cooldown_minutes` | int | `10` | 同一用户私信冷却（分钟） |
| `dm_max_age_minutes` | int | `180` | 只回复多少分钟内的私信 |
| `dm_min_chars` | int | `1` | 私信最短字数 |
| `dm_ignore_keywords` | string | 空 | 私信忽略关键词 |
| `dm_context_messages` | int | `6` | 生成回复时携带的历史消息条数 |
| `dm_reply_mode` | string | `llm` | `llm` 或 `template` |
| `dm_template` | text | `你好，{user}！` | 模板模式内容 |

模板可用变量：`{user}`、`{content}`、`{title}`、`{bvid}`、`{max}`。

## 数据与隐私

持久化数据位于 AstrBot 的 `data/plugin_data/astrbot_plugin_bilirelay/`：

| 文件 | 内容 |
| --- | --- |
| `credential.json` | 扫码登录后的 Cookie、昵称、UID、更新时间 |
| `subscriptions.json` | 各会话的 UP 订阅与推送基线 |
| `autoreply_state.json` | 已处理的评论/私信 ID、时间戳和用户冷却 |

- 文件写入时在 POSIX 系统上会尝试设置 `0600` 权限。
- 插件不会上传 Cookie，也不会在日志中打印 Cookie。
- 配置里的 `cookie` 字段使用 `secret: true`，WebUI 只做遮罩显示，不会加密存储；请自行保护好 AstrBot 的 `data` 目录。
- 共享机器人时请注意：任何能使用指令的人都能看到公开 B 站信息；订阅按会话隔离。

## 常见问题

### 1. 提示「触发了 B 站风控」

B 站对未登录、短时间高频的请求有风控（`-352` / `-412`）。插件会自动重建游客会话并重试一次，但无法保证 100% 成功。建议：

1. 在 WebUI 扫码登录 B 站账号；
2. 把 `request_interval` 调到 `0.8` 或更高；
3. 把 `subscription_interval` 调到 5 分钟以上；
4. 稍等几分钟再试。

### 2. AI 总结 / 字幕为空

这两个功能依赖登录态和视频本身的语音识别结果：

- 未登录时看不到 AI 字幕；
- 部分视频没有字幕或 AI 总结；
- B 站可能对单个视频禁用总结。

### 3. UP 主动态返回空列表

游客访问动态接口存在较强风控，偶尔会返回 `code=0` 但 `items` 为空。插件会自动换一套游客指纹重试一次；仍然为空时，登录账号或稍后再试。订阅轮询遇到空结果不会误报新动态。

### 4. 安装后插件没有加载

- 确认目录里有 `metadata.yaml` 和 `main.py`；
- 推荐目录名与 `metadata.yaml` 的 `name` 一致：`astrbot_plugin_bilirelay`；
- 检查 AstrBot 版本是否满足 `>=4.16,<5`；
- WebUI 插件页（扫码登录/订阅面板）需要 AstrBot `>=4.26`；更早版本仍可使用聊天指令、LLM 工具和订阅推送；
- 在 WebUI 插件管理里点「重载」，查看日志中的 `ImportError`。

### 5. 订阅没有推送

- 确认 `enable_subscriptions` 和对应的 `subscription_notify` 已开启；
- 用 `/bili sub list` 确认本会话有订阅；
- 用 `/bili sub check` 手动跑一轮；
- 首次添加后的第一轮只记录基线，不会立刻推送旧内容；
- 平台必须支持主动消息（QQ 官方 API 的部分场景不支持）。

### 6. 自动回复没有生效

- 确认 `enable_auto_reply`、`auto_reply_comments` / `auto_reply_dms` 已开启；
- 确认已登录 B 站账号（`/bili whoami`）；
- 首次轮询只建立基线，新评论/新私信才会回复；
- 私信默认只回复 `dm_whitelist`；要么填白名单，要么打开 `dm_allow_all`；
- `auto_reply_dry_run=true` 时只写日志，不会真正发送；
- 用 `/bili autoreply status` 查看运行状态和最近错误；
- 评论超过 `comment_max_age_minutes`、私信超过 `dm_max_age_minutes` 会被跳过；
- 若报 `21015`，需要先给 B 站账号绑定手机号；`21020/21046` 是发送频率限制，调大冷却和轮询间隔。

## 开发与测试

```bash
# 纯 B 站接口冒烟测试（会请求真实网络）
python tests/live_smoke.py

# 离线单元测试（unittest）
python -m unittest discover -s tests -v
```

代码结构：

```text
main.py                     AstrBot 插件入口：指令、LLM 工具、Web API
bilirelay/                  B 站客户端、接口、解析、订阅
  client.py                 httpx 会话、WBI 签名、Cookie、风控重试、缓存
  api.py                    搜索/视频/用户/动态/直播/榜单/专栏/番剧/收藏
  auth.py                   Cookie 持久化与扫码登录
  subscriptions.py          订阅存储与后台轮询
  autoreply.py              评论/私信自动回复、去重、冷却与 LLM 生成
  formatting.py             聊天文本格式化
  dynamics.py               动态结构解析
  refs.py                   BV/av/UID/直播间/番剧/专栏标识解析
pages/login/                WebUI 扫码登录与订阅面板
.astrbot-plugin/i18n/       中英文文案
```


## 与 dsh-bili-scroll 的关系

本仓库的「评论 / 私信自动回复」能力已移植到 [dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)
（DSH 插件，MIT），对应本地目录 [`dsh-bili-scroll/`](dsh-bili-scroll/)：
新增 `lib/autoreply.mjs`、MCP 读取工具、宿主定时器与设置页；出处与 MIT 署名见该目录的
[NOTICE.md](dsh-bili-scroll/NOTICE.md) 与 [CHANGELOG.md](dsh-bili-scroll/CHANGELOG.md)（0.1.19）。

## 声明与致谢

- 本插件是个人自用项目，与哔哩哔哩官方无关，未获得官方授权。
- 仅用于学习与个人自动化，请遵守 B 站用户协议、robots 规则和当地法律法规；不要用于批量抓取、商业分发或绕过付费/权限内容。
- 登录功能只使用用户自己的账号扫码，不提供账号密码登录，不绕过任何付费或权限控制。
- B 站接口为未公开接口，可能随时变更；插件会做降级和错误提示，但不保证长期可用。
- 实现参考了 [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html) 与社区整理的 B 站接口行为（`bilibili-API-collect` 及其镜像，CC BY-NC 4.0）；代码为独立实现。
- Logo 由插件自带生成，不使用 B 站官方素材。

## License

MIT
