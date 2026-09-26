import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { once } from 'node:events'

const scratch = await mkdtemp(join(tmpdir(), 'harness-integration-'))
const binary = resolve('build/harness')
let backend
let output = ''
let calls = 0
let slowStarted
const mock = createServer(async (req, res) => {
  let raw = ''
  for await (const chunk of req) raw += chunk
  const body = JSON.parse(raw)
  assert.equal(req.url, '/v1/chat/completions')
  assert.equal(req.headers.authorization, 'Bearer test-key')
  assert.equal(body.model, 'test-model')
  const context = JSON.stringify(body.messages)
  ++calls
  if (context.includes('slow task')) {
    slowStarted?.()
    await new Promise(resolve => setTimeout(resolve, 800))
  }
  if (context.includes('http failure')) { res.writeHead(503).end('Unavailable'); return }
  let content
  if (context.includes('malformed task')) content = 'not a tool call'
  else if (context.includes('failed task')) content = JSON.stringify({ name: 'failed', args: { reason: 'Model failure' } })
  else if (context.includes('ask human')) content = JSON.stringify({ name: 'call_user', args: { question: 'Which file?' } })
  else if (context.includes('repeated task')) content = JSON.stringify({ name: 'click', args: { x: 1, y: 2 } })
  else if (context.includes('cursor task') && !context.includes('result_ok')) content = JSON.stringify({ name: 'drag', args: { x1: 120, y1: 80, x2: 640, y2: 400 } })
  else if (!context.includes('result_ok')) content = JSON.stringify({ name: 'type_text', args: { text: 'Hello 世界' } })
  else content = JSON.stringify({ name: 'finished', args: { summary: 'Mock verified' } })
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ choices: [{ message: { content } }] }))
})
await new Promise((resolve, reject) => {
  mock.once('error', reject)
  mock.listen(0, '127.0.0.1', resolve)
})
const modelPort = mock.address().port
// Reserve an ephemeral port and release immediately before starting the backend.
const reserve = createServer()
await new Promise((resolve, reject) => {
  reserve.once('error', reject)
  reserve.listen(0, '127.0.0.1', resolve)
})
const port = reserve.address().port
await new Promise(resolve => reserve.close(resolve))
const base = `http://127.0.0.1:${port}`
const config = join(scratch, 'config.json')
const db = join(scratch, 'sessions.db')
const env = { ...process.env, COMPUTER_USE_VLM_BASE_URL: '', COMPUTER_USE_VLM_MODEL: '', COMPUTER_USE_VLM_API_KEY: '' }
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function start() {
  backend = spawn(binary, ['--dry-run', '--port', String(port), '--db', db, '--config', config, '--logs', join(scratch, 'logs')], { env })
  backend.stdout.on('data', chunk => { output += chunk })
  backend.stderr.on('data', chunk => { output += chunk })
  for (let i = 0; i < 100; ++i) {
    if (backend.exitCode !== null) throw new Error(output)
    try { if ((await fetch(`${base}/api/health`)).ok) return } catch {}
    await delay(50)
  }
  throw new Error(`Backend did not start: ${output}`)
}
async function stop() { if (backend && backend.exitCode === null) { const exited = once(backend, 'exit'); backend.kill('SIGTERM'); await exited } }
async function post(path, data) { return fetch(`${base}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }) }
async function task(prompt) { const res = await post('/api/tasks', { prompt }); assert.equal(res.status, 200); return res.json() }
async function stream(id, onEvent) {
  return new Promise((resolve, reject) => {
    const events = [], ws = new WebSocket(`ws://127.0.0.1:${port}/api/tasks/${id}/stream`)
    const timeout = setTimeout(() => { ws.close(); reject(new Error(`Stream timeout: ${JSON.stringify(events)}\n${output}`)) }, 15000)
    ws.onmessage = event => { const data = JSON.parse(event.data); events.push(data); onEvent?.(data, ws) }
    ws.onerror = () => { clearTimeout(timeout); reject(new Error('WebSocket error')) }
    ws.onclose = () => { clearTimeout(timeout); resolve(events) }
  })
}
try {
  await writeFile(config, '{}')
  await start()
  assert.equal((await (await fetch(`${base}/api/health`)).json()).status, 'ok')
  assert.equal((await fetch(`${base}/api/config`, { method: 'OPTIONS' })).status, 204)
  assert.equal((await post('/api/tasks', { prompt: '' })).status, 400)
  assert.equal((await post('/api/tasks', { prompt: 'test', target_pid: -1 })).status, 400)
  assert.equal((await post('/api/tasks', { prompt: 'test', target_pid: '123' })).status, 400)
  assert.equal((await fetch(`${base}/api/tasks`, { method: 'POST', body: '{' })).status, 400)
  assert.equal((await fetch(`${base}/api/sessions/missing`)).status, 404)
  const offline = await task('type Preserve CASE')
  const offlineEvents = await stream(offline.id)
  assert.equal(offlineEvents.at(-1).type, 'complete')
  assert(offlineEvents.some(e => e.step?.detail.includes('Preserve CASE')))
  assert.equal((await stream(offline.id)).at(-1).type, 'error')
  assert.equal((await stream('missing')).at(-1).type, 'error')
  assert.equal((await post('/api/config', { vlm_base_url: `http://127.0.0.1:${modelPort}/v1`, vlm_model: 'test-model', vlm_api_key: 'test-key' })).status, 200)
  const cfg = await (await fetch(`${base}/api/config`)).json()
  assert.equal(cfg.vlm_enabled, true)
  assert(!('vlm_api_key' in cfg))
  const success = await task('mock success')
  const events = await stream(success.id)
  assert.equal(events.at(-1).type, 'complete')
  assert(events.some(e => e.step?.type === 'keyboard'))
  const dragTask = await (await post('/api/tasks', { prompt: 'cursor task', target_pid: 999 })).json()
  const dragEvents = await stream(dragTask.id)
  assert.equal(dragEvents.at(-1).type, 'complete')
  const cursorEvents = dragEvents.filter(e => e.type === 'computer_cursor')
  assert.equal(cursorEvents.length, 2)
  assert.deepEqual(cursorEvents.map(e => [e.x, e.y, e.global_x, e.global_y, e.phase, e.target_pid]), [
    [120, 80, 120, 80, 'acting', 999], [640, 400, 640, 400, 'settled', 999],
  ])
  const frames = dragEvents.filter(e => e.type === 'computer_frame')
  assert.deepEqual(frames.map(e => e.sequence), [0, 1, 2])
  assert(frames.every(e => e.dry_run && e.target_pid === 999 && e.width === 1280 && e.height === 800))
  const dragLog = await readFile(join(scratch, 'logs', dragTask.run_id, 'run.log'), 'utf8')
  assert(!dragLog.includes('image_b64'))
  const dragSession = await (await fetch(`${base}/api/sessions/${dragTask.id}`)).json()
  assert(!JSON.stringify(dragSession).includes('image_b64'))
  for (const prompt of ['failed task', 'malformed task', 'http failure', 'repeated task', 'ask human']) {
    const t = await task(prompt), events = await stream(t.id)
    assert.equal(events.at(-1).type, 'error', prompt)
    if (prompt === 'ask human') assert(events.some(e => e.type === 'call_user'))
    assert.equal((await (await fetch(`${base}/api/sessions/${t.id}`)).json()).status, 'error')
  }
  let release
  const started = new Promise(resolve => { release = resolve })
  slowStarted = release
  const slow = await task('slow task')
  const cancelled = stream(slow.id, (event, ws) => {
    if (event.type === 'info') started.then(() => ws.close())
  })
  await started
  const concurrent = await task('concurrent task')
  assert.equal((await stream(concurrent.id)).at(-1).type, 'error')
  await cancelled
  for (let i = 0; i < 80; i++) {
    const session = await (await fetch(`${base}/api/sessions/${slow.id}`)).json()
    if (session.status === 'cancelled') break
    if (i === 79) assert.fail(`Cancellation was not persisted: ${JSON.stringify(session)}`)
    await delay(50)
  }
  await stop()
  await start()
  const restored = await (await fetch(`${base}/api/sessions/${success.id}`)).json()
  assert.equal(restored.status, 'success')
  assert(restored.steps.some(s => s.type === 'keyboard'))
  assert.equal((await (await fetch(`${base}/api/config`)).json()).vlm_model, 'test-model')
  assert(calls >= 5)
  const mcp = spawn(binary, ['--mcp', '--dry-run'], { env })
  let rpc = ''
  mcp.stdout.on('data', chunk => { rpc += chunk })
  mcp.stdin.end([
    { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05' } },
    { jsonrpc: '2.0', method: 'notifications/initialized' },
    { jsonrpc: '2.0', id: 2, method: 'tools/list' },
    { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'click', arguments: { x: 2, y: 3 } } },
    { jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'bad' } },
    { jsonrpc: '2.0', id: 5, method: 'unknown' },
  ].map(x => JSON.stringify(x)).join('\n') + '\n')
  assert.equal((await once(mcp, 'exit'))[0], 0)
  const replies = rpc.trim().split('\n').map(JSON.parse)
  assert.equal(replies.length, 5)
  assert.equal(replies[0].result.serverInfo.name, 'computer-control')
  assert(replies[1].result.tools.some(t => t.name === 'screenshot'))
  assert.equal(replies[2].result.isError, false)
  assert.equal(replies[3].result.isError, true)
  assert.equal(replies[4].error.code, -32601)
  assert((await readFile(join(scratch, 'logs', success.run_id, 'run.log'), 'utf8')).includes('Mock verified'))
  console.log('HTTP, WebSocket, mock VLM, cancellation, persistence, run logs, and MCP integration checks passed')
} finally {
  await stop()
  mock.closeAllConnections()
  await new Promise(resolve => mock.close(resolve))
  await rm(scratch, { recursive: true, force: true })
}
