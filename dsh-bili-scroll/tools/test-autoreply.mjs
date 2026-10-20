/**
 * 自动回复宿主模块的离线测试（不启动 dsh / 不连 B站）。
 * 运行：node --test tools/test-autoreply.mjs
 *
 * ⚠️ 被测逻辑移植自 Neko BiliRelay（MIT，NekoHome），见 lib/autoreply.mjs 顶部署名。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { createAutoReply, parseBvids, parseUids, renderTemplate } from '../lib/autoreply.mjs'

const makeState = () => ({
  comments: [],
  messages: [],
  replies: [],
  sent: [],
})

const makeCall = (data) => async (name, args = {}) => {
  switch (name) {
    case 'bili_check_credential': return { logged_in: true, uid: 1, username: 'me' }
    case 'bili_my_videos': return { videos: [{ bvid: 'BV1xx411c7mD' }] }
    case 'bili_latest_comments': return { bvid: args.bvid, title: '测试视频', comments: data.comments }
    case 'bili_reply': data.replies.push(args); return { success: true, rpid: args.rpid }
    case 'bili_dm_sessions': return { sessions: [{ uid: 2 }] }
    case 'bili_dm_messages': return { messages: data.messages }
    case 'bili_send_message': data.sent.push(args); return { success: true }
    default: throw new Error('unknown tool: ' + name)
  }
}

const baseCfg = (over = {}) => ({
  autoReply: true,
  autoReplyComments: true,
  autoReplyDms: false,
  autoReplyInterval: 10,
  autoReplyMaxPerRound: 3,
  autoReplyCooldown: 30,
  autoReplyMaxAge: 180,
  autoReplyMinChars: 1,
  autoReplyMaxChars: 200,
  autoReplyTemplate: '谢谢{user}',
  autoReplyDmTemplate: '你好{user}',
  autoReplyTargets: 'BV1xx411c7mD',
  autoReplyAutoVideos: true,
  autoReplyVideoLimit: 5,
  autoReplyAllowAll: false,
  autoReplyWhitelist: '',
  autoReplyBlacklist: '',
  autoReplyDryRun: false,
  autoReplyIgnoreKeywords: '',
  ...over,
})

const now = () => Math.floor(Date.now() / 1000)

test('parse helpers', () => {
  assert.deepEqual(parseBvids('BV1xx411c7mD, https://www.bilibili.com/video/BV1GJ411x7h7'), ['BV1xx411c7mD', 'BV1GJ411x7h7'])
  assert.deepEqual([...parseUids('2, UID 3; 2')], [2, 3])
  assert.equal(renderTemplate('谢谢{user}：{content}', { user: 'A', content: 'B' }), '谢谢A：B')
})

test('comment baseline then reply only new', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bili-autoreply-'))
  try {
    const data = makeState()
    const cfg = baseCfg()
    data.comments = [{ rpid: 1, root: 0, parent: 0, user: '观众', user_id: 2, content: '旧评论', time: now() }]
    const ar = createAutoReply({ call: makeCall(data), getCfg: () => cfg, stateDir: dir, log: () => {} })
    await ar.runOnce('test')
    assert.equal(data.replies.length, 0)
    data.comments.push({ rpid: 2, root: 0, parent: 0, user: '新观众', user_id: 3, content: '新评论', time: now() + 1 })
    await ar.runOnce('test')
    assert.equal(data.replies.length, 1)
    assert.equal(data.replies[0].text, '谢谢新观众')
    assert.equal(data.replies[0].rpid, 2)
    await ar.runOnce('test')
    assert.equal(data.replies.length, 1)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('dm whitelist and baseline', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bili-autoreply-'))
  try {
    const data = makeState()
    data.messages = [{ msg_key: 'm1', sender_uid: 2, msg_type: 1, msg_status: 0, time: now(), content: '你好' }]
    const cfg = baseCfg({ autoReplyComments: false, autoReplyDms: true, autoReplyAllowAll: true })
    const ar = createAutoReply({ call: makeCall(data), getCfg: () => cfg, stateDir: dir, log: () => {} })
    await ar.runOnce('test')
    assert.equal(data.sent.length, 0)
    data.messages.push({ msg_key: 'm2', sender_uid: 2, msg_type: 1, msg_status: 0, time: now() + 1, content: '催更' })
    await ar.runOnce('test')
    assert.equal(data.sent.length, 1)
    assert.equal(data.sent[0].text, '你好UID 2')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('dm whitelist empty means no reply', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'bili-autoreply-'))
  try {
    const data = makeState()
    data.messages = [{ msg_key: 'm1', sender_uid: 2, msg_type: 1, msg_status: 0, time: now(), content: '你好' }]
    const cfg = baseCfg({ autoReplyComments: false, autoReplyDms: true })
    const ar = createAutoReply({ call: makeCall(data), getCfg: () => cfg, stateDir: dir, log: () => {} })
    await ar.runOnce('test')
    assert.equal(data.sent.length, 0)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
