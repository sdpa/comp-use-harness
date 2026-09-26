import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

async function setup(callbacks) {
  let socket
  class WebSocket {
    constructor() { socket = this }
    close() { this.onclose?.({ code: 1000, reason: '' }) }
  }
  const context = vm.createContext({ window: {}, WebSocket, console: { log() {}, warn() {}, error() {} } })
  const module = new vm.SourceTextModule(await readFile(new URL('../src/renderer/src/lib/api.js', import.meta.url), 'utf8'), { context })
  await module.link(() => { throw new Error('Unexpected import') })
  await module.evaluate()
  const abort = module.namespace.streamTask('test-task', callbacks)
  return { socket, abort, message: data => socket.onmessage({ data: JSON.stringify(data) }) }
}

test('frames, target changes, and cursor telemetry reach their subscribers', async () => {
  const seen = []
  const s = await setup({ onComputerFrame: e => seen.push(e.type), onComputerCursor: e => seen.push(e.type), onComputerTarget: e => seen.push(e.type) })
  for (const type of ['computer_frame', 'computer_cursor', 'computer_target']) s.message({ type })
  assert.deepEqual(seen, ['computer_frame', 'computer_cursor', 'computer_target'])
  s.abort()
})

test('completion, cancellation and unexpected disconnect settle only once', async () => {
  let errors = 0, completed = 0
  const s = await setup({ onError: () => errors++, onComplete: () => completed++ })
  s.message({ type: 'complete' })
  s.socket.onerror()
  assert.equal(completed, 1)
  assert.equal(errors, 0)
  const cancelled = await setup({ onError: () => errors++ })
  cancelled.abort()
  assert.equal(errors, 0)
  const disconnected = await setup({ onError: () => errors++ })
  disconnected.socket.onclose({ code: 1006 })
  disconnected.socket.onerror()
  assert.equal(errors, 1)
})
