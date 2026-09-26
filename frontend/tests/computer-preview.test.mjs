import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFile } from 'node:fs/promises'
import { EventEmitter } from 'node:events'
import vm from 'node:vm'
import { join } from 'node:path'

async function setup() {
  const windows = [], handles = new Map(), timers = new Set()
  const ipcMain = new EventEmitter()
  ipcMain.handle = (channel, handler) => handles.set(channel, handler)
  class Window extends EventEmitter {
    constructor(options = {}) {
      super()
      this.options = options
      this.bounds = { x: options.x ?? 0, y: options.y ?? 0, width: options.width ?? 860, height: options.height ?? 820 }
      this.webContents = new EventEmitter()
      this.messages = []
      this.webContents.send = (channel, value) => this.messages.push({ channel, value })
      this.webContents.setWindowOpenHandler = () => {}
      windows.push(this)
    }
    getBounds() { return this.bounds }
    setBounds(bounds) { this.bounds = bounds }
    setPosition(x, y) { this.bounds.x = x; this.bounds.y = y }
    setAlwaysOnTop(value) { this.alwaysOnTop = value }
    setContentProtection(value) { this.protected = value }
    setIgnoreMouseEvents(value) { this.ignoresMouse = value }
    setVisibleOnAllWorkspaces(value) { this.allSpaces = value }
    showInactive() { this.visible = true }
    show() { this.visible = true }
    focus() { this.focused = true }
    isDestroyed() { return Boolean(this.destroyed) }
    destroy() { this.destroyed = true; this.emit('closed') }
    loadFile(path, options) { this.file = path; this.query = options.query }
  }
  const owner = new Window()
  const display = { workArea: { x: 0, y: 0, width: 1440, height: 900 }, bounds: { x: 0, y: 0, width: 1440, height: 900 } }
  const screen = { getDisplayMatching: () => display, getAllDisplays: () => [display] }
  const context = vm.createContext({ __dirname: '/app/out/main', process: { env: {} }, URL,
    setTimeout: callback => { timers.add(callback); return callback }, clearTimeout: callback => timers.delete(callback),
  })
  const electron = new vm.SyntheticModule(['BrowserWindow', 'ipcMain', 'screen'], function () {
    this.setExport('BrowserWindow', Window); this.setExport('ipcMain', ipcMain); this.setExport('screen', screen)
  }, { context })
  const path = new vm.SyntheticModule(['join'], function () { this.setExport('join', join) }, { context })
  const module = new vm.SourceTextModule(await readFile(new URL('../src/main/computerPreview.js', import.meta.url), 'utf8'), { context })
  await module.link(specifier => specifier === 'electron' ? electron : path)
  await module.evaluate()
  const dispose = module.namespace.registerComputerPreview(() => owner)
  const invoke = (channel, sender, ...args) => handles.get(channel)({ sender: sender.webContents }, ...args)
  const send = (channel, sender, ...args) => ipcMain.emit(channel, { sender: sender.webContents }, ...args)
  return { owner, windows, timers, dispose, invoke, send }
}

const cursor = { x: 80, y: 90, global_x: 280, global_y: 190, target_pid: 456, action: 'click', phase: 'acting' }

test('preview expands without rerunning a task; overlay never intercepts mouse input', async () => {
  const s = await setup()
  assert.equal(s.invoke('computer-preview-start', s.owner, 'task-a', 'Test app'), true)
  const preview = s.windows[1]
  assert.equal(preview.bounds.width, 400)
  s.send('computer-preview-expand', preview, true)
  assert.equal(preview.bounds.width, 1100)
  s.send('computer-preview-expand', preview, false)
  assert.equal(preview.bounds.width, 400)
  s.send('computer-preview-update', s.owner, 'task-a', { cursor })
  const overlay = s.windows[2]
  assert.equal(overlay.ignoresMouse, true)
  assert.equal(overlay.options.focusable, false)
  assert.equal(overlay.options.transparent, true)
  assert.equal(overlay.bounds.x, 270)
  assert.equal(overlay.bounds.y, 180)
  assert.equal(overlay.query.cursor, '1')
  overlay.emit('ready-to-show')
  assert.equal(overlay.visible, true)
  s.send('computer-preview-stop', preview)
  assert(overlay.isDestroyed())
  assert.equal(s.owner.messages.at(-1).channel, 'computer-preview-stop-request')
  assert.equal(s.owner.messages.at(-1).value, 'task-a')
  s.dispose()
})

test('stale tasks and untrusted windows cannot publish; terminal states clean overlays', async () => {
  const s = await setup()
  s.invoke('computer-preview-start', s.owner, 'task-b', 'Test app')
  const preview = s.windows[1]
  s.send('computer-preview-update', preview, 'task-b', { cursor })
  s.send('computer-preview-update', s.owner, 'old-task', { cursor })
  assert.equal(s.windows.length, 2)
  s.send('computer-preview-update', s.owner, 'task-b', { cursor })
  const overlay = s.windows[2]
  s.send('computer-preview-update', s.owner, 'task-b', { status: 'error' })
  assert(overlay.isDestroyed())
  overlay.emit('ready-to-show')
  assert(!overlay.visible, 'late ready event must not resurrect a ghost cursor')
  s.dispose()
})

test('timeout, dry runs, closing preview, and owner teardown remove cursor windows', async () => {
  const s = await setup()
  s.invoke('computer-preview-start', s.owner, 'task-c', 'Test app')
  const preview = s.windows[1]
  s.send('computer-preview-update', s.owner, 'task-c', { cursor, dryRun: true })
  assert.equal(s.windows.length, 2)
  s.send('computer-preview-update', s.owner, 'task-c', { dryRun: false, cursor })
  const first = s.windows.at(-1)
  for (const callback of [...s.timers]) callback()
  assert(first.isDestroyed())
  s.send('computer-preview-update', s.owner, 'task-c', { cursor })
  const second = s.windows.at(-1)
  preview.destroy()
  assert(second.isDestroyed())
  s.invoke('computer-preview-open', s.owner)
  s.send('computer-preview-update', s.owner, 'task-c', { cursor })
  const third = s.windows.at(-1)
  s.dispose()
  assert(third.isDestroyed())
  assert.equal(s.timers.size, 0)
})
