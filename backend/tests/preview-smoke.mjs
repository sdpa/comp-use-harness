// Manual UI smoke test: start this instead of the normal backend, then launch
// Electron and submit any prompt. The backend is strictly dry-run: no OS input.
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../..')
const dir = await mkdtemp(join(tmpdir(), 'harness-preview-'))
const model = createServer(async (req, res) => {
  let raw = ''
  for await (const part of req) raw += part
  const body = JSON.parse(raw)
  const text = body.messages.at(-1).content.find(part => part.type === 'text').text
  const history = JSON.parse(text.split('History: ')[1].split('\nScreen grid:')[0])
  const index = history.length
  await new Promise(resolve => setTimeout(resolve, 3000))
  const actions = [
    { name: 'move_mouse', args: { x: 220, y: 180 } },
    { name: 'click', args: { x: 640, y: 400 } },
    { name: 'drag', args: { x1: 640, y1: 400, x2: 850, y2: 500 } },
    { name: 'finished', args: { summary: 'Preview smoke test complete; no desktop input was sent.' } },
  ]
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(actions[Math.min(index, actions.length - 1)]) } }] }))
})
await new Promise((resolve, reject) => { model.once('error', reject); model.listen(0, '127.0.0.1', resolve) })
const config = join(dir, 'config.json')
await writeFile(config, JSON.stringify({ vlm_base_url: `http://127.0.0.1:${model.address().port}/v1`, vlm_model: 'preview-smoke', vlm_api_key: 'local-test' }))
const backend = spawn(join(root, 'backend/build/harness'), ['--dry-run', '--port', process.env.PORT || '7123', '--config', config, '--db', join(dir, 'sessions.db'), '--logs', join(dir, 'logs')], { stdio: 'inherit' })
let closing = false
async function cleanup(code = 0) {
  if (closing) return
  closing = true
  backend.kill('SIGTERM')
  model.closeAllConnections()
  model.close()
  await rm(dir, { recursive: true, force: true })
  process.exit(code)
}
backend.on('error', error => { console.error(error); cleanup(1) })
backend.on('exit', code => cleanup(code || 0))
process.on('SIGINT', () => cleanup())
process.on('SIGTERM', () => cleanup())
console.log('Preview smoke backend: submit a prompt in the UI to test frames, pointer, expansion, and Stop. All actions are simulated.')
