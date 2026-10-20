(() => {
  "use strict";

  let bridge = window.AstrBotPluginPage || window.AstrBotPluginView || null;

  const $ = (id) => document.getElementById(id);
  const state = {
    status: null,
    cfg: null,
    subs: null,
    tab: "overview",
    qrKey: "",
    qrDeadline: 0,
    pollTimer: null,
    pollFailures: 0,
    busy: false,
  };

  const TABS = {
    overview: ["概览", "登录状态、订阅和自动回复一览。"],
    account: ["账号", "扫码登录、Cookie 状态和账号信息。"],
    dm: ["主动私信", "用登录的 B 站账号主动发一条私信。"],
    subs: ["订阅", "按会话管理 UP 主的新投稿、动态和开播提醒。"],
    autoreply: ["自动回复", "评论 / 私信自动回复的运行状态与参数。"],
    settings: ["设置", "订阅、网络、主动私信和账号 Cookie。"],
  };

  const AUTO_GROUPS = [
    {
      section: "总开关",
      items: [
        { key: "enable_auto_reply", label: "启用自动回复", type: "bool", note: "总开关；关闭后两个轮询任务都会停止" },
        { key: "auto_reply_comments", label: "自动回复评论", type: "bool", note: "轮询自己投稿下的新一级评论" },
        { key: "auto_reply_dms", label: "自动回复私信", type: "bool", note: "轮询私信会话；默认只回白名单" },
        { key: "auto_reply_dry_run", label: "只记录不发送", type: "bool", note: "dry-run：只写日志，适合先观察" },
      ],
    },
    {
      section: "节奏与上限",
      items: [
        { key: "comment_poll_interval", label: "评论轮询间隔（秒）", type: "int", min: 60, max: 86400 },
        { key: "dm_poll_interval", label: "私信轮询间隔（秒）", type: "int", min: 60, max: 86400 },
        { key: "comment_max_per_round", label: "每轮最多回评论", type: "int", min: 1, max: 10 },
        { key: "dm_max_per_round", label: "每轮最多回私信", type: "int", min: 1, max: 10 },
        { key: "comment_cooldown_minutes", label: "评论同用户冷却（分钟）", type: "int", min: 1, max: 1440 },
        { key: "dm_cooldown_minutes", label: "私信同用户冷却（分钟）", type: "int", min: 1, max: 1440 },
        { key: "comment_max_age_minutes", label: "评论只回多少分钟内", type: "int", min: 1, max: 10080 },
        { key: "dm_max_age_minutes", label: "私信只回多少分钟内", type: "int", min: 1, max: 10080 },
        { key: "auto_reply_reply_interval", label: "发送间隔（秒）", type: "float", min: 0, max: 60, step: "0.5" },
        { key: "auto_reply_max_chars", label: "回复最大字数", type: "int", min: 20, max: 1000 },
      ],
    },
    {
      section: "评论",
      items: [
        { key: "comment_targets", label: "监控 BV 号", type: "string", note: "逗号分隔；留空 = 自动用最近投稿", wide: true },
        { key: "comment_auto_videos", label: "自动监控最近投稿", type: "bool" },
        { key: "comment_video_limit", label: "监控最近几条投稿", type: "int", min: 1, max: 20 },
        { key: "comment_include_replies", label: "也回楼中楼", type: "bool", note: "只回直接回复自己/别人的一层，不递归" },
        { key: "comment_min_chars", label: "最短字数", type: "int", min: 1, max: 100 },
        { key: "comment_ignore_keywords", label: "忽略关键词", type: "string", wide: true, note: "逗号分隔；命中就不回复" },
        { key: "comment_reply_mode", label: "回复方式", type: "select", options: ["llm", "template"] },
        { key: "comment_template", label: "模板回复", type: "text", wide: true, note: "变量：{user} {content} {bvid} {title}" },
      ],
    },
    {
      section: "私信",
      items: [
        { key: "dm_min_chars", label: "最短字数", type: "int", min: 1, max: 100 },
        { key: "dm_context_messages", label: "上下文条数", type: "int", min: 0, max: 20, note: "给 LLM 参考的最近消息数" },
        { key: "dm_ignore_keywords", label: "忽略关键词", type: "string", wide: true },
        { key: "dm_reply_mode", label: "回复方式", type: "select", options: ["llm", "template"] },
        { key: "dm_template", label: "模板回复", type: "text", wide: true, note: "变量：{user} {content} {uid}" },
        { key: "dm_allow_all", label: "允许回复所有陌生人", type: "bool", note: "默认关；开启前想清楚" },
        { key: "dm_whitelist", label: "私信白名单 UID", type: "string", wide: true, note: "逗号分隔；allow_all=false 时只回这些 UID" },
        { key: "dm_blacklist", label: "私信黑名单 UID", type: "string", wide: true },
      ],
    },
  ];

  const SETTING_GROUPS = [
    {
      section: "运行",
      items: [
        { key: "enable_llm_tools", label: "启用 LLM 工具", type: "bool" },
        { key: "enable_subscriptions", label: "启用订阅轮询", type: "bool" },
        { key: "subscription_interval", label: "订阅轮询间隔（分钟）", type: "int", min: 1, max: 1440 },
        { key: "max_subscriptions", label: "每个会话最多订阅", type: "int", min: 1, max: 200 },
        { key: "push_cover", label: "推送带封面图", type: "bool" },
        { key: "login_qr_in_chat", label: "允许聊天内发登录二维码", type: "bool" },
      ],
    },
    {
      section: "网络与缓存",
      items: [
        { key: "request_interval", label: "请求间隔（秒）", type: "float", min: 0, max: 10, step: "0.05" },
        { key: "timeout", label: "请求超时（秒）", type: "int", min: 1, max: 120 },
        { key: "cache_ttl", label: "缓存有效（秒）", type: "int", min: 0, max: 3600 },
        { key: "max_reply_chars", label: "聊天回复最大字数", type: "int", min: 200, max: 10000 },
      ],
    },
    {
      section: "主动私信",
      items: [
        { key: "send_dm_admin_only", label: "/bili send 仅管理员", type: "bool" },
        { key: "send_dm_dry_run", label: "主动私信 dry-run", type: "bool", note: "命令、工具、订阅转发都只预览" },
        { key: "enable_llm_send_dm", label: "允许 LLM 主动私信", type: "bool" },
        { key: "llm_send_dm_whitelist", label: "LLM 私信白名单 UID", type: "string", wide: true },
        { key: "subscription_dm_uid", label: "订阅转发目标 UID", type: "string", note: "留空关闭；可填 self" },
        { key: "subscription_dm_mode", label: "订阅转发方式", type: "select", options: ["off", "both", "only"] },
      ],
    },
  ];

  function toast(text, kind = "") {
    const box = $("toast");
    if (!box) return;
    box.textContent = text || "";
    box.className = `toast ${kind}`.trim();
    box.classList.toggle("hidden", !text);
    if (state.toastTimer) clearTimeout(state.toastTimer);
    if (text) state.toastTimer = setTimeout(() => box.classList.add("hidden"), 5200);
  }

  function setBusy(busy) {
    state.busy = Boolean(busy);
    for (const id of [
      "refreshBtn", "authBtn", "regenBtn", "logoutBtn", "sendDmBtn", "addSubBtn",
      "autoRunBtn", "autoResetBtn", "saveAutoBtn", "saveSettingsBtn", "saveCookieBtn",
    ]) {
      const node = $(id);
      if (node) node.disabled = state.busy;
    }
  }

  function formatTime(timestamp) {
    if (!timestamp) return "—";
    const number = Number(timestamp);
    if (!Number.isFinite(number) || number <= 0) return "—";
    const ms = number < 1e12 ? number * 1000 : number;
    try {
      return new Date(ms).toLocaleString();
    } catch {
      return String(timestamp);
    }
  }

  function errorText(error) {
    return (error && (error.message || error.error)) || "操作失败";
  }

  function activateTab(name) {
    if (!TABS[name]) return;
    state.tab = name;
    for (const button of document.querySelectorAll(".nav-item")) {
      button.classList.toggle("active", button.dataset.tab === name);
    }
    for (const section of document.querySelectorAll(".tab")) {
      section.classList.toggle("hidden", section.id !== `tab-${name}`);
    }
    $("pageTitle").textContent = TABS[name][0];
    $("pageDesc").textContent = TABS[name][1];
    if (name === "subs" && bridge) loadSubs().catch((error) => toast(errorText(error), "error"));
  }

  /* ────────────── status ────────────── */

  function renderStatus(data) {
    state.status = data;
    const user = (data && data.user) || {};
    const loggedIn = Boolean(data && data.logged_in);
    const poller = (data && data.poller) || {};
    const auto = (data && data.autoreply) || {};
    const stats = auto.stats || {};
    const counts = (data && data.subscriptions) || {};

    const pill = $("loginPill");
    pill.textContent = loggedIn ? (user.name ? `已登录 · ${user.name}` : "已登录") : "游客模式";
    pill.className = `pill ${loggedIn ? "ok" : "warn"}`;

    $("heroDot").className = `dot ${loggedIn ? "ok" : "warn"}`;
    $("heroStatus").textContent = loggedIn ? "B 站账号已连接" : "未登录，部分功能不可用";
    $("heroName").textContent = loggedIn ? user.name || "已登录" : "游客模式";
    const heroMeta = [];
    if (loggedIn && user.uid) heroMeta.push(`UID ${user.uid}`);
    if (loggedIn && user.level) heroMeta.push(`Lv${user.level}`);
    if (loggedIn && user.vip) heroMeta.push(user.vip);
    if (loggedIn && data.source === "qr") heroMeta.push("扫码登录");
    if (loggedIn && data.source === "config") heroMeta.push("Cookie 登录");
    $("heroMeta").textContent = heroMeta.join(" · ") || "登录后可发私信、读字幕与自动回复";
    $("heroSubs").textContent = String(counts.total || 0);

    $("statSessions").textContent = String(counts.sessions || 0);
    $("statUps").textContent = String(counts.ups || 0);
    $("statComments").textContent = String(stats.comment_replies || 0);
    $("statDms").textContent = String(stats.dm_replies || 0);

    const pollerPill = $("pollerPill");
    pollerPill.textContent = poller.running ? "运行中" : "未运行";
    pollerPill.className = `pill ${poller.running ? "ok" : "warn"}`;
    const pollerParts = [`上次检查：${formatTime(poller.last_round_at)}`];
    if (poller.interval_seconds) pollerParts.push(`间隔 ${Math.round(poller.interval_seconds / 60)} 分钟`);
    if (poller.last_error) pollerParts.push(`错误：${poller.last_error}`);
    $("pollerInfo").textContent = pollerParts.join(" · ");

    const autoPill = $("autoPill");
    autoPill.textContent = auto.master_enabled ? (auto.running ? "运行中" : "未运行") : "未启用";
    autoPill.className = `pill ${auto.running ? "ok" : "warn"}`;
    const autoParts = [
      `评论：${auto.comments_enabled ? "开" : "关"}`,
      `私信：${auto.dms_enabled ? "开" : "关"}`,
    ];
    if (auto.dry_run) autoParts.push("dry-run");
    if (stats.last_error) autoParts.push(`错误：${stats.last_error}`);
    $("autoInfo").textContent = autoParts.join(" · ");

    $("autoSectionPill").textContent = auto.running ? "运行中" : auto.master_enabled ? "未运行" : "未启用";
    $("autoSectionPill").className = `pill ${auto.running ? "ok" : "warn"}`;
    $("autoSectionInfo").textContent =
      `评论回复 ${stats.comment_replies || 0} 条 / 私信回复 ${stats.dm_replies || 0} 条` +
      ` · 上次评论轮询 ${formatTime(stats.last_comment_round)}` +
      ` · 上次私信轮询 ${formatTime(stats.last_dm_round)}` +
      (stats.last_error ? ` · 最近错误：${stats.last_error}` : "");

    $("version").textContent = data.version ? `v${data.version}` : "—";
    $("footVersion").textContent = data.version ? `v${data.version}` : "";
    renderAccount(data);
  }

  function renderAccount(data) {
    const user = (data && data.user) || {};
    const loggedIn = Boolean(data && data.logged_in);
    $("accountDot").className = `dot ${loggedIn ? "ok" : "warn"}`;
    $("accountStatus").textContent = loggedIn ? "已连接" : "未登录";
    $("accountName").textContent = loggedIn ? user.name || "已登录" : "游客模式";
    const meta = [];
    if (loggedIn && user.uid) meta.push(`UID ${user.uid}`);
    if (loggedIn && user.level) meta.push(`Lv${user.level}`);
    if (loggedIn && user.vip) meta.push(user.vip);
    $("accountMeta").textContent = meta.join(" · ") || "扫码登录后可用";
    $("loginSource").textContent =
      data.source === "qr" ? "扫码登录" : data.source === "config" ? "配置 Cookie" : "未登录";
    $("cookieState").textContent = loggedIn ? "已保存" : data.has_config_cookie ? "配置 Cookie 无效/过期" : "未配置";
    $("loginNeeded").textContent = loggedIn ? "可用" : "需要登录";

    const avatar = $("avatar");
    avatar.style.backgroundImage = "";
    avatar.textContent = "B";
    if (loggedIn && user.face) {
      avatar.style.backgroundImage = `url("${String(user.face).replace(/"/g, "")}")`;
      avatar.textContent = "";
    }
    $("authBtn").classList.toggle("hidden", loggedIn);
    $("logoutBtn").classList.toggle("hidden", !loggedIn);
    if (loggedIn) {
      $("qrPanel").classList.add("hidden");
      stopQr();
    }
  }

  /* ────────────── config forms ────────────── */

  function renderGroups(container, groups, values) {
    if (!container) return;
    container.textContent = "";
    for (const group of groups) {
      const section = document.createElement("div");
      section.className = "cfg-section";
      const title = document.createElement("div");
      title.className = "cfg-title";
      title.textContent = group.section;
      section.appendChild(title);
      const grid = document.createElement("div");
      grid.className = "cfg-grid";

      for (const item of group.items) {
        const value = values[item.key];
        if (item.type === "bool") {
          const row = document.createElement("div");
          row.className = "switch-row";
          const text = document.createElement("div");
          text.className = "switch-text";
          const strong = document.createElement("strong");
          strong.textContent = item.label;
          text.appendChild(strong);
          if (item.note) {
            const small = document.createElement("small");
            small.textContent = item.note;
            text.appendChild(small);
          }
          const button = document.createElement("button");
          button.type = "button";
          button.className = `switch ${value ? "on" : ""}`.trim();
          button.dataset.key = item.key;
          button.dataset.kind = "bool";
          button.setAttribute("aria-pressed", value ? "true" : "false");
          button.addEventListener("click", () => {
            const on = !button.classList.contains("on");
            button.classList.toggle("on", on);
            button.setAttribute("aria-pressed", on ? "true" : "false");
          });
          row.append(text, button);
          grid.appendChild(row);
          continue;
        }

        const wrap = document.createElement("div");
        wrap.className = `cfg-item ${item.wide || item.type === "text" ? "full" : ""}`.trim();
        const label = document.createElement("label");
        label.textContent = item.label;
        const id = `cfg-${item.key}`;
        label.htmlFor = id;

        let input;
        if (item.type === "select") {
          input = document.createElement("select");
          for (const option of item.options || []) {
            const optionNode = document.createElement("option");
            optionNode.value = option;
            optionNode.textContent = option;
            input.appendChild(optionNode);
          }
          input.value = String(value ?? "");
        } else if (item.type === "text") {
          input = document.createElement("textarea");
          input.rows = 3;
          input.value = String(value ?? "");
        } else {
          input = document.createElement("input");
          input.type = item.type === "string" ? "text" : "number";
          if (item.type === "int" || item.type === "float") {
            if (item.min !== undefined) input.min = String(item.min);
            if (item.max !== undefined) input.max = String(item.max);
            input.step = item.step || (item.type === "int" ? "1" : "0.1");
          }
          input.value = value === undefined || value === null ? "" : String(value);
        }
        input.id = id;
        input.dataset.key = item.key;
        input.dataset.kind = item.type;
        wrap.append(label, input);
        if (item.note) {
          const note = document.createElement("small");
          note.textContent = item.note;
          wrap.appendChild(note);
        }
        grid.appendChild(wrap);
      }

      section.appendChild(grid);
      container.appendChild(section);
    }
  }

  function collectGroups(container) {
    const values = {};
    if (!container) return values;
    for (const node of container.querySelectorAll("[data-key]")) {
      const key = node.dataset.key;
      const kind = node.dataset.kind;
      if (!key) continue;
      if (kind === "bool") values[key] = node.classList.contains("on");
      else if (kind === "int") values[key] = Number.parseInt(node.value, 10) || 0;
      else if (kind === "float") values[key] = Number.parseFloat(node.value) || 0;
      else values[key] = node.value;
    }
    return values;
  }

  function renderConfig(data) {
    state.cfg = data;
    const values = (data && data.values) || {};
    renderGroups($("autoreplyFields"), AUTO_GROUPS, values);
    renderGroups($("settingsFields"), SETTING_GROUPS, values);
    const notify = values.subscription_notify || {};
    $("notifyVideo").checked = notify.video !== false;
    $("notifyDynamic").checked = notify.dynamic !== false;
    $("notifyLive").checked = notify.live !== false;
  }

  async function loadConfig() {
    if (!bridge) return;
    const data = await bridge.apiGet("config");
    renderConfig(data);
  }

  async function saveConfigPatch(values, cookie) {
    if (!bridge) throw new Error("页面桥不可用");
    const body = { values };
    if (cookie) body.cookie = cookie;
    const data = await bridge.apiPost("config", body);
    renderConfig(data);
    await loadStatus();
    return data;
  }

  /* ────────────── subscriptions ────────────── */

  function renderSubs(data) {
    state.subs = data;
    const items = Array.isArray(data && data.items) ? data.items : [];
    const sessions = Array.isArray(data && data.sessions) ? data.sessions : [];
    const counts = (data && data.counts) || {};
    $("subsCount").textContent = String(counts.total || items.length);
    $("heroSubs").textContent = String(counts.total || items.length);
    $("statSessions").textContent = String(counts.sessions || 0);
    $("statUps").textContent = String(counts.ups || 0);

    const list = $("subSessions");
    list.textContent = "";
    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session;
      list.appendChild(option);
    }

    const body = $("subsBody");
    body.textContent = "";
    const labels = { video: "投稿", dynamic: "动态", live: "直播" };
    for (const item of items) {
      const row = document.createElement("tr");
      const umo = document.createElement("td");
      umo.textContent = item.umo || "—";
      umo.title = item.umo || "";
      const name = document.createElement("td");
      name.textContent = item.name || "—";
      const uid = document.createElement("td");
      uid.textContent = String(item.uid || "");
      const types = document.createElement("td");
      for (const type of item.types || []) {
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = labels[type] || type;
        types.appendChild(badge);
      }
      const baseline = document.createElement("td");
      const marks = [];
      if (item.last_video_pubdate) marks.push("投稿");
      if (item.last_dynamic_id) marks.push("动态");
      if (item.last_live_status >= 0) marks.push("直播");
      baseline.textContent = marks.join(" / ") || "待建立";
      const action = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn ghost";
      remove.textContent = "删除";
      remove.dataset.removeUmo = item.umo || "";
      remove.dataset.removeUid = String(item.uid || "");
      action.appendChild(remove);
      row.append(umo, name, uid, types, baseline, action);
      body.appendChild(row);
    }
    $("subsEmpty").classList.toggle("hidden", items.length > 0);
  }

  async function loadSubs() {
    if (!bridge) return;
    const data = await bridge.apiGet("subs/list");
    renderSubs(data);
  }

  async function addSub() {
    if (!bridge || state.busy) return;
    const umo = $("subUmo").value.trim();
    const uid = $("subUid").value.trim();
    const types = [...document.querySelectorAll("#tab-subs .checks input:checked")].map((node) => node.value);
    if (!umo) return toast("请填写会话 UMO", "error");
    if (!uid) return toast("请填写 UP 主 UID", "error");
    setBusy(true);
    try {
      await bridge.apiPost("subs/add", { umo, uid, types });
      $("subUid").value = "";
      await loadSubs();
      toast("订阅已添加", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function removeSub(umo, uid) {
    if (!bridge || state.busy) return;
    if (!umo || !uid) return;
    setBusy(true);
    try {
      await bridge.apiPost("subs/remove", { umo, uid });
      await loadSubs();
      toast("订阅已删除", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  /* ────────────── account / QR ────────────── */

  function stopQr() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    state.qrKey = "";
    state.qrDeadline = 0;
    state.pollFailures = 0;
  }

  function renderQr(svg, url) {
    const box = $("qrBox");
    box.textContent = "";
    if (svg) {
      const cleaned = String(svg).replace(/^<\?xml[^>]*\?>\s*/i, "");
      box.innerHTML = cleaned;
      return;
    }
    if (url) {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "打开登录链接";
      box.appendChild(link);
    }
  }

  async function startQr() {
    if (!bridge || state.busy) return;
    setBusy(true);
    try {
      const qr = await bridge.apiPost("login/qrcode", {});
      if (!qr || !qr.qrcode_key) throw new Error("服务器没有返回 qrcode_key");
      stopQr();
      state.qrKey = qr.qrcode_key;
      state.qrDeadline = Date.now() + (Number(qr.expires_in) || 180) * 1000;
      renderQr(qr.svg, qr.url);
      $("qrState").textContent = "等待扫码…";
      $("qrPanel").classList.remove("hidden");
      state.pollTimer = setInterval(pollQr, 2000);
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function pollQr() {
    if (!state.qrKey || !bridge) return;
    if (Date.now() > state.qrDeadline) {
      stopQr();
      $("qrState").textContent = "二维码已失效，请重新生成";
      return;
    }
    try {
      const result = await bridge.apiPost("login/poll", { qrcode_key: state.qrKey });
      state.pollFailures = 0;
      const status = (result && result.state) || "waiting";
      if (status === "confirmed") {
        stopQr();
        $("qrState").textContent = "登录成功";
        $("qrPanel").classList.add("hidden");
        toast("B 站登录成功", "ok");
        await loadStatus();
        return;
      }
      if (status === "expired") {
        stopQr();
        $("qrState").textContent = "二维码已失效，请重新生成";
        return;
      }
      if (status === "scanned") {
        $("qrState").textContent = "已扫码，请在手机上确认";
        return;
      }
      $("qrState").textContent = "等待扫码…";
    } catch (error) {
      state.pollFailures += 1;
      if (state.pollFailures >= 4) {
        stopQr();
        toast(errorText(error), "error");
      }
    }
  }

  async function logout() {
    if (!bridge || state.busy) return;
    if (!window.confirm("确定退出 B 站登录？扫码凭证会被清除。")) return;
    setBusy(true);
    try {
      await bridge.apiPost("logout", {});
      stopQr();
      $("qrPanel").classList.add("hidden");
      await loadStatus();
      toast("已退出 B 站登录", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  /* ────────────── actions ────────────── */

  async function sendDm() {
    if (!bridge || state.busy) return;
    const uid = $("dmUid").value.trim();
    const text = $("dmText").value.trim();
    if (!uid) return toast("请填写接收者 UID", "error");
    if (!text) return toast("私信内容不能为空", "error");
    setBusy(true);
    try {
      const data = await bridge.apiPost("send-dm", { uid, text });
      if (data && data.dry_run) {
        toast(`dry-run：准备发给 UID ${data.uid}，未发送`, "ok");
      } else {
        toast(`已向 UID ${data.uid} 发送私信`, "ok");
        $("dmText").value = "";
      }
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function runAuto() {
    if (!bridge || state.busy) return;
    setBusy(true);
    try {
      const data = await bridge.apiPost("autoreply/run", {});
      if (data && data.ok) {
        toast(`已执行：评论 ${data.comment_replies || 0} / 私信 ${data.dm_replies || 0}`, "ok");
      } else {
        toast((data && data.message) || "执行完成，但没有新回复", "ok");
      }
      await loadStatus();
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function resetAuto() {
    if (!bridge || state.busy) return;
    if (!window.confirm("清空自动回复的去重和冷却状态？下一轮会重新建立基线。")) return;
    setBusy(true);
    try {
      await bridge.apiPost("autoreply/reset", {});
      toast("自动回复状态已清空", "ok");
      await loadStatus();
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveAuto() {
    if (!bridge || state.busy) return;
    setBusy(true);
    try {
      await saveConfigPatch(collectGroups($("autoreplyFields")));
      toast("自动回复设置已保存", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings() {
    if (!bridge || state.busy) return;
    const values = collectGroups($("settingsFields"));
    values.subscription_notify = {
      video: $("notifyVideo").checked,
      dynamic: $("notifyDynamic").checked,
      live: $("notifyLive").checked,
    };
    setBusy(true);
    try {
      await saveConfigPatch(values);
      toast("通用设置已保存", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveCookie() {
    if (!bridge || state.busy) return;
    const cookie = $("cookieInput").value.trim();
    if (!cookie) return toast("请先粘贴 Cookie", "error");
    if (!cookie.includes("SESSDATA")) {
      return toast("Cookie 里至少要包含 SESSDATA", "error");
    }
    setBusy(true);
    try {
      await saveConfigPatch({}, cookie);
      $("cookieInput").value = "";
      toast("Cookie 已保存并应用", "ok");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    try {
      await loadStatus();
      if (state.tab === "subs") await loadSubs();
    } catch (error) {
      toast(errorText(error), "error");
    }
  }

  /* ────────────── wiring ────────────── */

  function bind() {
    for (const button of document.querySelectorAll(".nav-item")) {
      button.addEventListener("click", () => activateTab(button.dataset.tab));
    }
    for (const button of document.querySelectorAll("[data-goto]")) {
      button.addEventListener("click", () => activateTab(button.dataset.goto));
    }
    $("refreshBtn").addEventListener("click", refresh);
    $("authBtn").addEventListener("click", startQr);
    $("regenBtn").addEventListener("click", startQr);
    $("logoutBtn").addEventListener("click", logout);
    $("sendDmBtn").addEventListener("click", sendDm);
    $("addSubBtn").addEventListener("click", addSub);
    $("subsBody").addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-umo]");
      if (button) removeSub(button.dataset.removeUmo, button.dataset.removeUid);
    });
    $("autoRunBtn").addEventListener("click", runAuto);
    $("autoResetBtn").addEventListener("click", resetAuto);
    $("saveAutoBtn").addEventListener("click", saveAuto);
    $("saveSettingsBtn").addEventListener("click", saveSettings);
    $("saveCookieBtn").addEventListener("click", saveCookie);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") refresh();
    });
  }

  async function waitForBridge() {
    for (let index = 0; index < 80; index += 1) {
      bridge = window.AstrBotPluginPage || window.AstrBotPluginView || bridge;
      if (bridge) return true;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return Boolean(bridge);
  }

  async function main() {
    if (!(await waitForBridge())) {
      toast("AstrBot Plugin Bridge 不可用，请从 AstrBot WebUI 打开本页面", "error");
      return;
    }
    try {
      await bridge.ready();
    } catch {
      // 仍然尝试读取数据
    }
    bind();
    activateTab("overview");
    try {
      await loadStatus();
      await loadConfig();
      await loadSubs();
    } catch (error) {
      toast(errorText(error), "error");
    }
    setInterval(() => {
      if (document.visibilityState === "visible") loadStatus().catch(() => {});
    }, 15000);
  }

  main().catch((error) => toast(errorText(error), "error"));
})();
