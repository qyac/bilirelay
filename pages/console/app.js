(() => {
  "use strict";

  let bridge = window.AstrBotPluginPage || window.AstrBotPluginView || null;

  const $ = (id) => document.getElementById(id);
  const state = {
    status: null,
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
  };

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
      "autoRunBtn", "autoResetBtn",
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
