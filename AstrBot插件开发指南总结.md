# AstrBot 插件开发指南总结

> 根据 AstrBot 插件开发文档整理。

## 1. 环境准备与目录结构

- 使用 `helloworld` 模板创建插件仓库。
- 插件名建议以 `astrbot_plugin_` 开头，不能有空格，建议全小写、简短。
- 插件目录：`AstrBot/data/plugins/<插件名>/`。
- 调试需启动 AstrBot 本体，修改代码后在 WebUI 插件管理中重载。
- 第三方依赖写入插件目录 `requirements.txt`。
- 持久化数据必须放 AstrBot 的 `data` 目录，不要放插件自身目录。

## 2. metadata.yaml

- 必需文件，AstrBot 靠它识别插件元数据。
- `support_platforms`：平台列表，值使用 `ADAPTER_NAME_2_TYPE` key，如 `telegram`、`discord`、`aiocqhttp`、`qq_official`、`lark`、`dingtalk`、`slack`、`kook`、`satori`、`line`、`matrix`、`mattermost` 等。
- `astrbot_version`：PEP 440 版本范围，如 ">=4.16,<5"，不加 `v` 前缀。
- 版本不满足时插件会被阻止加载；WebUI 安装时可选择 "无视警告，继续安装"。
- 可选：`logo.png`（1:1，建议 256x256）、`display_name`、`short_desc`、`skills/`。
- `skills/` 会被加载进 Skill Manager，WebUI 中作为只读来源展示。

## 3. 开发原则

- 功能需测试，代码需注释。
- 良好错误处理，避免单个错误导致插件崩溃。
- 提交前使用 `ruff` 格式化。
- 网络请求使用 `aiohttp`、`httpx` 等异步库，不要使用 `requests`。
- 扩展现有插件优先提交 PR，除非原作者已停止维护。
- 借鉴设计或代码需在 README 注明来源，并遵守原开源许可。
- 持久化数据放 `data` 目录，不要放插件目录。

## 4. 消息事件处理

### 4.1 导入

```python
from astrbot.api.event import filter, AstrMessageEvent
```

必须从 `astrbot.api.event` 导入 `filter`，避免和 Python 内置 `filter` 冲突。

### 4.2 消息对象

`AstrMessageEvent` 包含发送者、消息内容等信息，`event.message_obj` 可获取 `AstrBotMessage`。

`AstrBotMessage` 常用字段：

```python
type: MessageType          # 消息类型
self_id: str               # 机器人识别 id
session_id: str            # 会话 id
message_id: str            # 消息 id
group_id: str = ""         # 群组 id，私聊为空
sender: MessageMember      # 发送者
message: List[BaseMessageComponent]  # 消息链
message_str: str           # Plain 文本连接后的纯文本
raw_message: object        # 平台原始消息对象
timestamp: int             # 消息时间戳
```

### 4.3 消息链

消息链是 `List[BaseMessageComponent]`，常见消息段：`Plain`、`At`、`Image`、`Record`、`Video`、`File`。

OneBot v11 还支持 `Face`、`Node`、`Nodes`、`Poke`。

### 4.4 指令

```python
@filter.command("helloworld")
async def helloworld(self, event: AstrMessageEvent):
    user_name = event.get_sender_name()
    yield event.plain_result(f"Hello, {user_name}!")
```

- 指令不能带空格，否则会被解析到第二个参数。
- 带参指令由 AstrBot 自动解析：

```python
@filter.command("add")
async def add(self, event: AstrMessageEvent, a: int, b: int):
    yield event.plain_result(f"结果是: {a + b}")
```

### 4.5 指令组

```python
@filter.command_group("math")
def math():
    pass

@math.command("add")
async def add(self, event: AstrMessageEvent, a: int, b: int):
    yield event.plain_result(f"结果是: {a + b}")
```

- 指令组函数内直接 `pass` 或写注释。
- 子指令使用 `指令组名.command` 注册。
- 没有输入子指令时，AstrBot 会报错并渲染树形结构。
- 指令组可以嵌套，嵌套使用 `.group()`。
- 指令别名示例：`@filter.command("help", alias={"帮助", "helpme"})`。

### 4.6 事件过滤

```python
@filter.event_message_type(filter.EventMessageType.ALL)
async def on_all_message(self, event: AstrMessageEvent):
    yield event.plain_result("收到了一条消息。")
```

`EventMessageType` 当前包括 `PRIVATE_MESSAGE`、`GROUP_MESSAGE`、`ALL`。

### 4.7 平台过滤

```python
@filter.platform_adapter_type(
    filter.PlatformAdapterType.AIOCQHTTP | filter.PlatformAdapterType.QQOFFICIAL
)
async def handler(self, event: AstrMessageEvent):
    yield event.plain_result("收到了一条信息")
```

支持 `AIOCQHTTP`、`QQOFFICIAL`、`TELEGRAM`、`WECOM`、`DISCORD`、`SLACK`、`KOOK`、`LINE`、`MATRIX`、`MISSKEY`、`SATORI`、`ALL` 等。

### 4.8 权限与多过滤器

```python
@filter.permission_type(filter.PermissionType.ADMIN)
@filter.command("test")
async def test(self, event: AstrMessageEvent):
    pass
```

多个过滤器是 AND 逻辑，全部通过才会执行。

### 4.9 事件钩子

常用钩子：

- `@filter.on_astrbot_loaded()`：AstrBot 初始化完成。
- `@filter.on_waiting_llm_request()`：等待 LLM 请求，未获取会话锁时；用 `event.send()` 发送消息。
- `@filter.on_llm_request()`：LLM 请求前，可修改 `ProviderRequest`。
- `@filter.on_llm_response()`：LLM 请求完成，可修改 `LLMResponse`。
- `@filter.on_agent_begin()`：Agent 开始运行，AstrBot >= v4.23.1。
- `@filter.on_using_llm_tool()`：LLM 工具调用前。
- `@filter.on_llm_tool_respond()`：LLM 工具调用后。
- `@filter.on_agent_done()`：Agent 运行完成，在 `on_llm_response` 之后。
- `@filter.on_decorating_result()`：发送消息前，可修改 `event.get_result().chain`。
- `@filter.after_message_sent()`：消息发送后。

限制：

- 事件钩子不能和 `command`、`command_group`、`event_message_type`、`platform_adapter_type`、`permission_type` 混用。
- 除 `on_decorating_result` 等钩子外，不能 `yield` 发送消息，应使用 `await event.send(event.plain_result(...))`。
- 动态提示词优先放 `req.extra_user_content_parts`；只在本轮生效可用 `.mark_as_temp()`；不要频繁改 `system_prompt`，以免破坏缓存。

### 4.10 优先级与事件传播

- 指令、监听器、钩子均可设置 `priority`，默认 `0`。
- 调用 `event.stop_event()` 可停止事件继续传播，后续 handler 和 LLM 请求都不会执行。

## 5. 插件配置

### 5.1 配置定义

在插件目录添加 `_conf_schema.json`，AstrBot 自动解析并保存到：

```text
data/config/<plugin_name>_config.json
```

### 5.2 type 类型

`type` 必填，支持：

- `string`、`text`、`int`、`float`、`bool`
- `object`、`list`、`dict`
- `template_list`
- `file`（v4.13.0+）

### 5.3 常用字段

- `description`、`hint`、`obvious_hint`
- `default`
- `items`：`object` 类型必填
- `invisible`
- `secret`：仅对 `string` 和字符串 `list` 生效，只做界面遮罩，不加密
- `options`
- `editor_mode`、`editor_language`、`editor_theme`
- `_special`
- `file_types`：`file` 类型使用
- `template_schema` 和 `slider`：用于 `dict` 可视化编辑

### 5.4 敏感配置

API Key、访问令牌、密码等应设置 `"secret": true`。它不改变插件读取到的值，插件不应记录、回显或暴露这些值。

### 5.5 _special

插件常用 `_special`：

- `select_provider`、`select_provider_tts`、`select_provider_stt`、`select_persona`：结果为字符串。
- `select_knowledgebase`：结果为列表，建议对应配置项 `type` 设为 `list`，默认值 `[]`。

不要使用 Core 内部值，如 `select_providers`、`provider_pool`、`persona_pool`、`t2i_template` 等。

### 5.6 template_list

保存后每个条目包含 `__template_key`，模板可选：

- `display_item`：折叠列表展示的字段，支持点号路径。
- `hide_hint_in_list`：折叠列表中隐藏模板 `hint`。

### 5.7 在插件中使用

```python
from astrbot.api import AstrBotConfig

class ConfigPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
```

`AstrBotConfig` 继承自 `dict`，可直接当字典使用；需要时调用 `self.config.save_config()`。

### 5.8 配置更新

修改 Schema 后，AstrBot 会递归检查：自动补缺失项默认值，移除已不存在的配置项。

## 6. 插件 Pages

### 6.1 定位与目录

简单配置优先用 `_conf_schema.json`；Pages 适合复杂表单、状态面板、日志、文件上传下载、SSE、图表等。

```text
your_plugin/
├─ main.py
└─ pages/
   ├─ bridge-demo/
   │  ├─ index.html
   │  ├─ app.js
   │  └─ style.css
   └─ settings/
      └─ index.html
```

- Pages 由 Dashboard 以受限 iframe 加载。
- 每个一级子目录是一个 Page，只扫描 `pages/<page_name>/index.html`。
- Page 名称不要用空名、`.`、`..`、以 `.` 开头或包含 `/`、`\`。
- Page 脚本通过 `window.AstrBotPluginPage` bridge 与 Dashboard 通信。

### 6.2 注册后端 API

```python
context.register_web_api(
    f"/{PLUGIN_NAME}/ping",
    self.page_ping,
    ["GET"],
    "Page ping",
)
```

- 路由必须包含插件名前缀。
- Page 端 endpoint 不带插件名前缀，例如 `bridge.apiGet("ping")`。
- 支持动态片段 `<name>` 和 `<path:name>`。

推荐使用 `from astrbot.api.web import request, json_response, error_response`。新插件不要直接暴露 FastAPI、Starlette、Quart 原始请求对象。

### 6.3 request 请求对象

- `request.method`、`request.path`、`request.plugin_name`、`request.username`
- `request.headers`、`request.cookies`、`request.content_type`、`request.client_host`
- `request.path_params`
- `request.query.get()` / `getlist()`
- `await request.body()`
- `await request.json(default={})`
- `await request.form()`：表单字段，不含文件
- `await request.files()`：上传文件，返回 `PluginUploadFile`

### 6.4 响应 helper

```python
from astrbot.api.web import (
    error_response,
    file_response,
    json_response,
    stream_response,
)
```

- `json_response({...})`
- `error_response("...", status_code=400)`
- `file_response(path, filename="...", content_type="...")`
- `stream_response(async_generator())`：SSE 必须返回 `text/event-stream`，消息以空行结尾。

旧插件仍可使用 Quart 的 `jsonify`、`request`；新插件推荐 `astrbot.api.web`，不要在同一个 handler 中混用两个 `request`。

### 6.5 Bridge API

```js
const bridge = window.AstrBotPluginPage;
const context = await bridge.ready();
```

上下文 API：

- `bridge.ready()`：等待并返回上下文。
- `bridge.getContext()`、`bridge.getLocale()`、`bridge.getI18n()`。
- `bridge.t(key, fallback)`：按点分隔 key 翻译。
- `bridge.onContext(handler)`：监听上下文变化，返回取消函数。

请求 API：

- `bridge.apiGet(endpoint, params)`
- `bridge.apiPost(endpoint, body)`
- `bridge.upload(endpoint, file)`：字段名固定为 `file`。
- `bridge.download(endpoint, params, filename)`
- `bridge.subscribeSSE(endpoint, handlers, params)`，用 `bridge.unsubscribeSSE(id)` 取消。

endpoint 是插件内相对路径，推荐不以 `/` 开头；不能为空，不能包含 `\`、URL scheme、query、hash、空路径片段、`.` 或 `..`。

### 6.6 返回值规则

- 后端返回 `{"status": "ok", "data": value}`，前端 resolve 为 `value`。
- 普通 JSON 返回完整 JSON。
- `{"status": "error", ...}` 或 HTTP 失败，Promise reject。
- Page-only API 推荐直接返回业务 JSON，错误用 `error_response`。

### 6.7 国际化与主题

Page 复用插件 i18n 资源：`.astrbot-plugin/i18n/<locale>.json`。

```json
{
  "pages": {
    "bridge-demo": {
      "title": "Bridge 演示页",
      "description": "页面描述",
      "heading": "插件页面"
    }
  }
}
```

- `title` 用于 WebUI 外壳和 Page 组件名称。
- `description` 用于插件详情页 Page 组件描述。
- 用 `bridge.t("pages.<page>.heading", "fallback")` 渲染，并通过 `onContext()` 响应语言切换。

主题：bridge SDK 维护 `<html data-theme="light|dark">`，可用 CSS 变量适配；JS 中读取 `bridge.getContext()?.isDark`。

### 6.8 静态资源与安全

- 使用相对路径引用资源，如 `./style.css`、`./app.js`。
- 不要手动拼 `/api/plugin/page/content/...`，不要自己加 `asset_token`，不要用 `..` 逃逸根目录。
- 会被重写：HTML `src`/`href`、CSS `url(...)`、JS `import`、`export ... from`、动态 `import()`。
- iframe 沙箱：`allow-scripts allow-forms allow-downloads`。
- Page 不能直接访问 Dashboard cookies、LocalStorage 或父页面 DOM。
- 后端必须验证输入；文件落盘使用安全目录，处理文件名。
- 常见安全头：`X-Frame-Options: SAMEORIGIN`、`Content-Security-Policy: frame-ancestors 'self'; object-src 'none'; base-uri 'self'`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`。

### 6.9 调试清单

- Page 不出现：检查 `pages/<page_name>/index.html`、插件是否启用、详情页是否刷新。
- bridge 不存在：确认脚本在 SDK 注入后运行，推荐外部 `type="module"` 脚本。
- API 未匹配：确认后端路由带插件名前缀，前端 endpoint 不带前缀。
- 文件上传为空：前端 `upload()` 字段名固定为 `file`，后端用 `(await request.files()).get("file")`。
- SSE 无消息：确认 `text/event-stream` 且每条消息以 `\n\n` 结尾。
- SSE 401：不要用原生 `EventSource`，应使用 `bridge.subscribeSSE()`。

## 7. 最小插件骨架

```python
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        yield event.plain_result(f"Hello, {event.get_sender_name()}!")

    async def terminate(self):
        pass
```

## 8. 开发检查清单

- [ ] `metadata.yaml` 已填写，插件名符合规范。
- [ ] 需要时添加 `requirements.txt`、`logo.png`、`skills/`。
- [ ] 需要时配置 `support_platforms`、`astrbot_version`。
- [ ] 持久化数据存放在 AstrBot `data` 目录。
- [ ] 已从 `astrbot.api.event` 导入 `filter`，未与内置 `filter` 冲突。
- [ ] 指令、指令组、别名、参数解析符合规范。
- [ ] 多个过滤器使用 AND 逻辑；权限和平台过滤正确。
- [ ] 事件钩子未与不兼容过滤器混用。
- [ ] 需要发送消息时使用 `event.send()`，而不是在钩子中 `yield`。
- [ ] 动态 LLM 内容优先放 `extra_user_content_parts`，必要时 `mark_as_temp()`。
- [ ] `_conf_schema.json` 类型、默认值、`secret`、`_special` 正确。
- [ ] Pages 路由带插件名前缀，前端 endpoint 不带前缀。
- [ ] Page 通过 bridge 通信，后端验证输入，文件上传安全处理。
- [ ] SSE 正确返回 `text/event-stream` 并取消订阅。
- [ ] 代码已用 `ruff` 格式化，网络请求使用异步库，未使用 `requests`。
- [ ] 功能已测试，错误处理完善，借鉴代码已注明来源。

> 具体 API 和版本行为请以当前 AstrBot 文档及实际代码为准。
