/**
 * lib/autoreply.mjs —— 评论 / 私信自动回复（宿主半端）
 * ============================================================================
 * 这是 dsh-bili-scroll 的新增功能，用来补上「只发不收」的空缺：
 *   - 定期读取自己最近投稿下的新评论，按模板回复；
 *   - 定期读取私信会话，按模板回复普通用户发来的文字私信。
 *
 * ⭐ 来源与署名：
 *   本文件的设计、去重/冷却/基线策略与默认字段，移植并改写自 **Neko BiliRelay**
 *   （AstrBot 插件 `astrbot_plugin_bilirelay`，MIT，Copyright (c) 2026 NekoHome）：
 *   https://github.com/qyac/bilirelay
 *   原始实现使用自建 B 站 HTTP 客户端；这里改为复用本仓库内置的 bilibili-mcp
 *   本文件所在仓库基于 **c1overzz/dsh-bili-scroll**（MIT，Copyright (c) 2026 c1overzz）：
 *   https://github.com/c1overzz/dsh-bili-scroll
 *   （bilibili-api-python），只保留「轮询 → 判断 → 模板回复」这一层。
 *   上游 bilibili-mcp 的 MIT 署名见 vendor/bilibili-mcp/LICENSE 与仓库 NOTICE.md。
 *
 * 设计原则（与 Neko BiliRelay 一致）：
 *   * 默认关闭，必须用户显式打开；
 *   * 首次轮询只记录基线，不回复历史消息；
 *   * 评论按 rpid、私信按 msg_key 去重，按用户冷却；
 *   * 每轮有数量上限，发送之间有间隔；
 *   * 私信默认只回白名单，allowAll 才回复所有陌生人；
 *   * dry-run 只写日志，不真正发送。
 * ============================================================================
 */
import { join } from 'node:path'
import { readJson, writeJson } from './state.mjs'

const BV_RE = /BV[0-9A-Za-z]{10}/g
const SEEN_LIMIT = 500

const clampInt = (value, min, max, fallback) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.max(min, Math.min(Math.trunc(n), max))
}

export function parseBvids(raw) {
  const out = []
  const text = Array.isArray(raw) ? raw.join(',') : String(raw || '')
  for (const match of text.matchAll(BV_RE)) {
    if (!out.includes(match[0])) out.push(match[0])
  }
  return out
}

export function parseUids(raw) {
  const out = new Set()
  const text = Array.isArray(raw) ? raw.join(',') : String(raw || '')
  for (const part of text.split(/[,，;；\s]+/)) {
    const n = Number(String(part).replace(/^uid[:：]?/i, '').trim())
    if (Number.isFinite(n) && n > 0) out.add(Math.trunc(n))
  }
  return out
}

export function parseKeywords(raw) {
  const text = Array.isArray(raw) ? raw.join(',') : String(raw || '')
  return text.split(/[,，;；\n]+/).map((s) => s.trim().toLowerCase()).filter(Boolean)
}

/** 极简模板：{user} {content} {bvid} {title} {uid}；未知占位符原样保留。 */
export function renderTemplate(template, vars = {}) {
  return String(template || '').replace(/\{(\w+)\}/g, (all, key) => (
    Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key] ?? '') : all
  ))
}

function oneLine(text, maxChars) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > maxChars ? value.slice(0, maxChars) : value
}

/**
 * 创建一个自动回复器。
 *
 * @param {object} opts
 * @param {(name: string, args?: object) => Promise<any>} opts.call  MCP 调用器
 * @param {() => object} opts.getCfg  每次读取最新配置（宿主会 refreshCfg）
 * @param {string} opts.stateDir      插件家目录
 * @param {(msg: string) => void} [opts.log] 日志
 */
export function createAutoReply({ call, getCfg, stateDir, log = () => {} }) {
  const file = join(stateDir, 'autoreply-state.json')
  const empty = () => ({ version: 1, comments: {}, dms: {}, cooldowns: {}, lastRunAt: 0, lastResult: null })
  let state = readJson(file, empty())
  if (!state || typeof state !== 'object') state = empty()
  for (const key of ['comments', 'dms', 'cooldowns']) {
    if (!state[key] || typeof state[key] !== 'object' || Array.isArray(state[key])) state[key] = {}
  }
  let busy = false
  let lastRunAt = Number(state.lastRunAt) || 0
  let lastResult = state.lastResult || null
  let lastError = ''

  const save = () => {
    try {
      state.lastRunAt = lastRunAt
      state.lastResult = lastResult
      writeJson(file, state)
    } catch (e) {
      log(`保存自动回复状态失败：${e?.message ?? e}`)
    }
  }

  const commentEntry = (bvid) => {
    if (!state.comments[bvid] || typeof state.comments[bvid] !== 'object') {
      state.comments[bvid] = { initialized: false, seen: [], lastTs: 0 }
    }
    const entry = state.comments[bvid]
    if (!Array.isArray(entry.seen)) entry.seen = []
    return entry
  }

  const dmEntry = (uid) => {
    const key = String(uid)
    if (!state.dms[key] || typeof state.dms[key] !== 'object') {
      state.dms[key] = { initialized: false, seen: [], lastTs: 0 }
    }
    const entry = state.dms[key]
    if (!Array.isArray(entry.seen)) entry.seen = []
    return entry
  }

  const mark = (entry, key, timestamp) => {
    const id = String(key || '')
    if (id && !entry.seen.includes(id)) {
      entry.seen.push(id)
      if (entry.seen.length > SEEN_LIMIT) entry.seen.splice(0, entry.seen.length - SEEN_LIMIT)
    }
    const ts = Number(timestamp) || 0
    if (ts > (Number(entry.lastTs) || 0)) entry.lastTs = ts
  }

  const cooldownLeft = (key, seconds) => {
    const last = Number(state.cooldowns[key]) || 0
    return Math.max(0, last + Math.max(0, seconds) - Date.now())
  }

  const setCooldown = (key) => { state.cooldowns[key] = Date.now() }

  const status = () => {
    const cfg = getCfg()
    return {
      enabled: Boolean(cfg.autoReply),
      comments: Boolean(cfg.autoReplyComments),
      dms: Boolean(cfg.autoReplyDms),
      running: busy,
      intervalMinutes: clampInt(cfg.autoReplyInterval, 2, 240, 10),
      lastRunAt: lastRunAt || null,
      lastResult,
      lastError,
      dryRun: Boolean(cfg.autoReplyDryRun),
      allowAll: Boolean(cfg.autoReplyAllowAll),
      whitelistCount: parseUids(cfg.autoReplyWhitelist).size,
      commentTargets: parseBvids(cfg.autoReplyTargets),
      stateFile: file,
    }
  }

  const reset = () => {
    state = empty()
    lastRunAt = 0
    lastResult = null
    lastError = ''
    save()
    log('自动回复状态已清空（下一轮会重新建立基线）')
    return { ok: true }
  }

  async function getMe() {
    const info = await call('bili_check_credential', {})
    if (!info || info.logged_in === false) throw new Error('未登录 B站，先在设置页扫码登录')
    const uid = Number(info.uid) || 0
    if (!uid) throw new Error('拿不到登录账号 UID')
    return uid
  }

  async function runComments(cfg, me, stats) {
    let targets = parseBvids(cfg.autoReplyTargets)
    if (!targets.length && cfg.autoReplyAutoVideos !== false) {
      const mine = await call('bili_my_videos', { num: clampInt(cfg.autoReplyVideoLimit, 1, 20, 5) })
      if (mine?.error) throw new Error(`读取自己的投稿失败：${mine.error}`)
      targets = (mine?.videos || []).map((v) => v.bvid).filter(Boolean)
    }
    if (!targets.length) {
      log('自动回复评论：没有可监控的视频（可在设置里填 BV 号，或先发布投稿）')
      return
    }
    const template = String(cfg.autoReplyTemplate || '感谢你的评论，{user}！')
    const maxPerRound = clampInt(cfg.autoReplyMaxPerRound, 1, 10, 3)
    const cooldownSec = clampInt(cfg.autoReplyCooldown, 1, 1440, 30) * 60
    const maxAgeSec = clampInt(cfg.autoReplyMaxAge, 1, 10080, 180) * 60
    const minChars = clampInt(cfg.autoReplyMinChars, 1, 100, 2)
    const maxChars = clampInt(cfg.autoReplyMaxChars, 20, 1000, 200)
    const keywords = parseKeywords(cfg.autoReplyIgnoreKeywords)
    const dryRun = Boolean(cfg.autoReplyDryRun)

    for (const bvid of targets) {
      let data
      try {
        data = await call('bili_latest_comments', { bvid, num: 20 })
      } catch (e) {
        stats.errors += 1
        log(`自动回复评论：读 ${bvid} 失败：${e?.message ?? e}`)
        continue
      }
      if (data?.error) {
        stats.errors += 1
        log(`自动回复评论：读 ${bvid} 失败：${data.error}`)
        continue
      }
      const entry = commentEntry(bvid)
      const list = Array.isArray(data.comments) ? data.comments : []
      stats.scannedComments += list.length
      if (!entry.initialized) {
        for (const c of list) mark(entry, c.rpid, c.time)
        entry.initialized = true
        save()
        log(`自动回复评论：已建立 ${bvid} 的基线（${list.length} 条）`)
        continue
      }
      const now = Date.now()
      const fresh = []
      for (const c of list) {
        const rpid = String(c.rpid || '')
        if (!rpid || entry.seen.includes(rpid)) continue
        if (Number(c.user_id) === me) { mark(entry, rpid, c.time); continue }
        // 只回一级评论；楼中楼留给值班轮的「回复评论」功能
        if (Number(c.parent || 0) !== 0) { mark(entry, rpid, c.time); continue }
        const time = Number(c.time) || 0
        if (!time || now - time * 1000 > maxAgeSec * 1000) { mark(entry, rpid, time); continue }
        const content = String(c.content || '').trim()
        if (content.length < minChars) { mark(entry, rpid, time); continue }
        const lower = content.toLowerCase()
        if (keywords.some((k) => lower.includes(k))) { mark(entry, rpid, time); continue }
        fresh.push(c)
      }
      fresh.sort((a, b) => (Number(a.time) || 0) - (Number(b.time) || 0))
      for (const c of fresh) {
        if (stats.comments >= maxPerRound) break
        const rpid = String(c.rpid || '')
        const uid = Number(c.user_id) || 0
        const key = `comment:${uid}`
        if (cooldownLeft(key, cooldownSec) > 0) { mark(entry, rpid, c.time); continue }
        const text = oneLine(renderTemplate(template, {
          user: c.user || `UID ${uid}`,
          content: c.content || '',
          bvid,
          title: data.title || '',
          uid,
        }), maxChars)
        if (!text) { mark(entry, rpid, c.time); continue }
        try {
          if (dryRun) {
            log(`[dry-run] 自动回复评论 ${bvid}/${rpid}：${text}`)
          } else {
            const r = await call('bili_reply', { bvid, text, rpid: Number(c.rpid) || 0, root: Number(c.rpid) || 0 })
            if (r?.success === false) throw new Error(r.error || '发送失败')
            stats.comments += 1
            log(`自动回复评论 ${bvid}/${rpid}：${text}`)
          }
          mark(entry, rpid, c.time)
          setCooldown(key)
          save()
          if (!dryRun) await new Promise((resolve) => setTimeout(resolve, 300))
        } catch (e) {
          stats.errors += 1
          log(`自动回复评论失败 ${bvid}/${rpid}：${e?.message ?? e}`)
          mark(entry, rpid, c.time)
          save()
        }
      }
    }
  }

  async function runDms(cfg, me, stats) {
    const allowAll = Boolean(cfg.autoReplyAllowAll)
    const whitelist = parseUids(cfg.autoReplyWhitelist)
    const blacklist = parseUids(cfg.autoReplyBlacklist)
    if (!allowAll && !whitelist.size) {
      log('自动回复私信：白名单为空（autoReplyAllowAll=false）⇒ 跳过')
      return
    }
    let data
    try {
      data = await call('bili_dm_sessions', { num: 20 })
    } catch (e) {
      throw new Error(`读取私信会话失败：${e?.message ?? e}`)
    }
    if (data?.error) throw new Error(`读取私信会话失败：${data.error}`)
    const template = String(cfg.autoReplyDmTemplate || '你好，{user}！')
    const maxPerRound = clampInt(cfg.autoReplyMaxPerRound, 1, 10, 3)
    const cooldownSec = clampInt(cfg.autoReplyCooldown, 1, 1440, 30) * 60
    const maxAgeSec = clampInt(cfg.autoReplyMaxAge, 1, 10080, 180) * 60
    const minChars = clampInt(cfg.autoReplyMinChars, 1, 100, 1)
    const maxChars = clampInt(cfg.autoReplyMaxChars, 20, 500, 200)
    const keywords = parseKeywords(cfg.autoReplyIgnoreKeywords)
    const dryRun = Boolean(cfg.autoReplyDryRun)

    for (const session of data.sessions || []) {
      const uid = Number(session.uid) || 0
      if (!uid || uid === me) continue
      if (blacklist.has(uid)) continue
      if (!allowAll && !whitelist.has(uid)) continue
      let msgData
      try {
        msgData = await call('bili_dm_messages', { talker_id: uid, num: 20 })
      } catch (e) {
        stats.errors += 1
        log(`自动回复私信：读 UID ${uid} 失败：${e?.message ?? e}`)
        continue
      }
      if (msgData?.error) {
        stats.errors += 1
        log(`自动回复私信：读 UID ${uid} 失败：${msgData.error}`)
        continue
      }
      const entry = dmEntry(uid)
      const messages = Array.isArray(msgData.messages) ? msgData.messages : []
      stats.scannedDms += messages.length
      if (!entry.initialized) {
        for (const m of messages) mark(entry, m.msg_key, m.time)
        entry.initialized = true
        save()
        log(`自动回复私信：已建立 UID ${uid} 的基线（${messages.length} 条）`)
        continue
      }
      const now = Date.now()
      const fresh = []
      for (const m of messages) {
        const key = String(m.msg_key || '')
        if (!key || entry.seen.includes(key)) continue
        if (Number(m.sender_uid) !== uid) { mark(entry, key, m.time); continue }
        if (Number(m.msg_type) !== 1 || Number(m.msg_status) !== 0) { mark(entry, key, m.time); continue }
        const time = Number(m.time) || 0
        if (!time || now - time * 1000 > maxAgeSec * 1000) { mark(entry, key, time); continue }
        const content = String(m.content || '').trim()
        if (content.length < minChars) { mark(entry, key, time); continue }
        const lower = content.toLowerCase()
        if (keywords.some((k) => lower.includes(k))) { mark(entry, key, time); continue }
        fresh.push(m)
      }
      fresh.sort((a, b) => (Number(a.time) || 0) - (Number(b.time) || 0))
      for (const m of fresh) {
        if (stats.dms >= maxPerRound) break
        const key = `dm:${uid}`
        if (cooldownLeft(key, cooldownSec) > 0) { mark(entry, m.msg_key, m.time); continue }
        const text = oneLine(renderTemplate(template, {
          user: `UID ${uid}`,
          content: m.content || '',
          uid,
        }), maxChars)
        if (!text) { mark(entry, m.msg_key, m.time); continue }
        try {
          if (dryRun) {
            log(`[dry-run] 自动回复私信 UID ${uid}/${m.msg_key}：${text}`)
          } else {
            const r = await call('bili_send_message', { receiver_uid: uid, text })
            if (r?.success === false) throw new Error(r.error || '发送失败')
            stats.dms += 1
            log(`自动回复私信 UID ${uid}/${m.msg_key}：${text}`)
          }
          mark(entry, m.msg_key, m.time)
          setCooldown(key)
          save()
          if (!dryRun) await new Promise((resolve) => setTimeout(resolve, 300))
        } catch (e) {
          stats.errors += 1
          log(`自动回复私信失败 UID ${uid}/${m.msg_key}：${e?.message ?? e}`)
          mark(entry, m.msg_key, m.time)
          save()
        }
      }
    }
  }

  async function runOnce(why = 'manual') {
    if (busy) return { ok: false, error: '上一轮自动回复还没跑完' }
    busy = true
    const startedAt = Date.now()
    const stats = { comments: 0, dms: 0, errors: 0, scannedComments: 0, scannedDms: 0 }
    try {
      const cfg = getCfg()
      if (!cfg.autoReply) return { ok: false, error: '自动回复总开关未开启' }
      const me = await getMe()
      if (cfg.autoReplyComments) await runComments(cfg, me, stats)
      if (cfg.autoReplyDms) await runDms(cfg, me, stats)
      lastRunAt = Date.now()
      lastError = ''
      lastResult = { ok: true, why, at: new Date().toISOString(), ms: Date.now() - startedAt, ...stats }
      save()
      if (stats.comments || stats.dms || stats.errors) {
        log(`自动回复完成（${why}）：评论 ${stats.comments} / 私信 ${stats.dms} / 错误 ${stats.errors}`)
      }
      return { ok: true, ...lastResult }
    } catch (e) {
      lastRunAt = Date.now()
      lastError = String(e?.message ?? e)
      lastResult = { ok: false, why, at: new Date().toISOString(), ms: Date.now() - startedAt, error: lastError, ...stats }
      save()
      log(`自动回复失败（${why}）：${lastError}`)
      return { ok: false, error: lastError, ...lastResult }
    } finally {
      busy = false
    }
  }

  async function tick() {
    try {
      const cfg = getCfg()
      if (!cfg.autoReply) return
      const intervalMs = clampInt(cfg.autoReplyInterval, 2, 240, 10) * 60_000
      if (lastRunAt && Date.now() - lastRunAt < intervalMs) return
      await runOnce('interval')
    } catch (e) {
      log(`自动回复定时器这一跳出错（已兜住）：${e?.message ?? e}`)
    }
  }

  return { tick, runOnce, status, reset }
}
