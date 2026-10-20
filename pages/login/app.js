(() => {
  "use strict";

  let bridge = window.AstrBotPluginPage || window.AstrBotPluginView || null;
  const $ = (id) => document.getElementById(id);
  const state = {
    qrKey: "",
    qrDeadline: 0,
    pollTimer: null,
    pollFailures: 0,
    busy: false,
    status: null,
  };

  function t(key, fallback) {
    if (!bridge || typeof bridge.t !== "function") return fallback || "";
    return bridge.t(key, fallback || "");
  }

  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (!key) return;
      const fallback = element.textContent || "";
      const value = t(key, fallback);
      if (value) element.textContent = value;
    });
  }

  function showMessage(text, isError = false) {
    const box = $("message");
    if (!box) return;
    box.textContent = text || "";
    box.classList.toggle("hidden", !text);
    box.classList.toggle("error", Boolean(isError));
  }

  function setBusy(busy) {
    state.busy = busy;
    for (const id of ["authBtn", "regenBtn", "refreshBtn", "logoutBtn"]) {
      const button = $(id);
      if (button) button.disabled = busy;
    }
  }

  function formatTime(timestamp) {
    if (!timestamp) return t("views.login.never", "尚未检查");
    try {
      return new Date(timestamp * 1000).toLocaleString();
    } catch (error) {
      return String(timestamp);
    }
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    state.qrKey = "";
    state.qrDeadline = 0;
    state.pollFailures = 0;
  }

  function renderAccount(status) {
    const loggedIn = Boolean(status && status.logged_in);
    const user = (status && status.user) || {};
    $("statusDot").className = `dot ${loggedIn ? "ok" : "warn"}`;
    $("statusText").textContent = loggedIn
      ? t("views.login.logged_in", "已登录")
      : t("views.login.guest", "当前为游客模式");
    $("userName").textContent = loggedIn
      ? user.name || t("views.login.logged_in", "已登录")
      : "—";

    const meta = [];
    if (loggedIn && user.uid) meta.push(`UID ${user.uid}`);
    if (loggedIn && user.level) meta.push(`Lv${user.level}`);
    if (loggedIn && user.vip) meta.push(user.vip);
    if (loggedIn && status.source === "config") meta.push("Cookie");
    if (!loggedIn && status && status.has_config_cookie) {
      meta.push("配置中的 Cookie 无效或已过期");
    }
    $("userMeta").textContent = meta.join(" · ");

    const avatar = $("avatar");
    avatar.textContent = loggedIn ? "B" : "B";
    if (loggedIn && user.face) {
      avatar.style.backgroundImage = `url("${String(user.face).replace(/"/g, "")}")`;
      avatar.textContent = "";
    } else {
      avatar.style.backgroundImage = "";
    }

    $("authBtn").classList.toggle("hidden", loggedIn);
    $("logoutBtn").classList.toggle("hidden", !loggedIn);
    if (loggedIn) {
      $("qrPanel").classList.add("hidden");
      stopPolling();
    }
  }

  function renderSubs(counts, items) {
    const data = counts || {};
    $("statTotal").textContent = String(data.total || 0);
    $("statSessions").textContent = String(data.sessions || 0);
    $("statUps").textContent = String(data.ups || 0);

    const body = $("subsBody");
    body.textContent = "";
    const list = Array.isArray(items) ? items : [];
    for (const item of list) {
      const row = document.createElement("tr");
      const uidCell = document.createElement("td");
      uidCell.textContent = String(item.uid || "");
      const nameCell = document.createElement("td");
      nameCell.textContent = item.name || "—";
      const typesCell = document.createElement("td");
      for (const type of item.types || []) {
        const badge = document.createElement("span");
        badge.className = "badge";
        const labels = {
          video: "投稿",
          dynamic: "动态",
          live: "直播",
        };
        badge.textContent = labels[type] || type;
        typesCell.appendChild(badge);
      }
      const sessionsCell = document.createElement("td");
      sessionsCell.textContent = String(item.sessions || 0);
      row.append(uidCell, nameCell, typesCell, sessionsCell);
      body.appendChild(row);
    }
    $("subsEmpty").classList.toggle("hidden", list.length > 0);
  }

  function renderAutoReply(status) {
    const data = status || {};
    const pill = $("autoreplyPill");
    const info = $("autoreplyInfo");
    const master = Boolean(data.master_enabled);
    const running = Boolean(data.running);
    pill.textContent = master
      ? running
        ? t("views.login.poller_running", "运行中")
        : t("views.login.poller_stopped", "未运行")
      : t("views.login.autoreply_disabled", "未启用");
    pill.classList.toggle("ok", running);
    const stats = data.stats || {};
    const parts = [
      `${t("views.login.autoreply_comments", "评论")}：${data.comments_enabled ? "开" : "关"}`,
      `${t("views.login.autoreply_dms", "私信")}：${data.dms_enabled ? "开" : "关"}`,
      `已回复 评论 ${stats.comment_replies || 0} / 私信 ${stats.dm_replies || 0}`,
    ];
    if (data.dry_run) parts.push("dry-run");
    if (stats.last_error) parts.push("有错误，详见 /bili autoreply status");
    info.textContent = parts.join(" · ");
  }

  async function loadSubs() {
    if (!bridge) return;
    try {
      const data = await bridge.apiGet("subs");
      renderSubs(data && data.counts, data && data.items);
    } catch (error) {
      showMessage(error.message || t("views.login.failed", "操作失败"), true);
    }
  }

  async function loadStatus() {
    if (!bridge) {
      showMessage("AstrBot Plugin Bridge 不可用，请从 AstrBot WebUI 打开本页面。", true);
      return;
    }
    try {
      const data = await bridge.apiGet("status");
      state.status = data;
      renderAccount(data);
      const poller = (data && data.poller) || {};
      const running = Boolean(poller.running);
      const pill = $("poller");
      pill.textContent = running
        ? t("views.login.poller_running", "运行中")
        : t("views.login.poller_stopped", "未运行");
      pill.classList.toggle("ok", running);
      $("lastCheck").textContent =
        t("views.login.last_check", "上次检查") +
        "：" +
        formatTime(poller.last_round_at);
      if (data && data.version) {
        $("version").textContent = `v${data.version}`;
      }
      renderAutoReply(data && data.autoreply);
      await loadSubs();
    } catch (error) {
      showMessage(error.message || t("views.login.failed", "操作失败"), true);
    }
  }

  function renderQrSvg(svg, url) {
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
    showMessage("");
    try {
      const qr = await bridge.apiPost("login/qrcode", {});
      if (!qr || !qr.qrcode_key) throw new Error("服务器没有返回 qrcode_key");
      stopPolling();
      state.qrKey = qr.qrcode_key;
      state.qrDeadline = Date.now() + (Number(qr.expires_in) || 180) * 1000;
      renderQrSvg(qr.svg, qr.url);
      $("qrState").textContent = t("views.login.waiting", "等待扫码…");
      $("qrPanel").classList.remove("hidden");
      state.pollTimer = setInterval(pollQr, 2000);
    } catch (error) {
      showMessage(error.message || t("views.login.failed", "操作失败"), true);
    } finally {
      setBusy(false);
    }
  }

  async function pollQr() {
    if (!state.qrKey || !bridge) return;
    if (Date.now() > state.qrDeadline) {
      stopPolling();
      $("qrState").textContent = t("views.login.expired", "二维码已失效，请重新生成");
      return;
    }
    try {
      const result = await bridge.apiPost("login/poll", {
        qrcode_key: state.qrKey,
      });
      state.pollFailures = 0;
      const status = (result && result.state) || "waiting";
      if (status === "confirmed") {
        stopPolling();
        $("qrState").textContent = t("views.login.success", "登录成功");
        showMessage(t("views.login.success", "登录成功"));
        $("qrPanel").classList.add("hidden");
        await loadStatus();
        return;
      }
      if (status === "expired") {
        stopPolling();
        $("qrState").textContent = t("views.login.expired", "二维码已失效，请重新生成");
        return;
      }
      if (status === "scanned") {
        $("qrState").textContent = t(
          "views.login.scanned",
          "已扫码，请在手机上确认",
        );
        return;
      }
      $("qrState").textContent = t("views.login.waiting", "等待扫码…");
    } catch (error) {
      state.pollFailures += 1;
      if (state.pollFailures >= 4) {
        stopPolling();
        showMessage(error.message || t("views.login.failed", "操作失败"), true);
      }
    }
  }

  async function logout() {
    if (!bridge || state.busy) return;
    setBusy(true);
    showMessage("");
    try {
      await bridge.apiPost("logout", {});
      stopPolling();
      $("qrPanel").classList.add("hidden");
      await loadStatus();
      showMessage("");
    } catch (error) {
      showMessage(error.message || t("views.login.failed", "操作失败"), true);
    } finally {
      setBusy(false);
    }
  }

  function bind() {
    $("authBtn").addEventListener("click", startQr);
    $("regenBtn").addEventListener("click", startQr);
    $("refreshBtn").addEventListener("click", loadStatus);
    $("logoutBtn").addEventListener("click", logout);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") loadStatus();
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
      showMessage("AstrBot Plugin Bridge 不可用，请从 AstrBot WebUI 打开本页面。", true);
      return;
    }
    try {
      await bridge.ready();
    } catch (error) {
      // ready 失败时仍然尝试读取状态
    }
    applyI18n();
    bind();
    if (typeof bridge.onContext === "function") {
      bridge.onContext(() => applyI18n());
    }
    await loadStatus();
    setInterval(loadStatus, 15000);
  }

  main().catch((error) => {
    showMessage(error && error.message ? error.message : "页面初始化失败", true);
  });
})();
