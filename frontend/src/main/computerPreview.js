import { BrowserWindow, ipcMain, screen } from 'electron'
import { join } from 'path'

// The main renderer owns execution. This window only observes its state and
// sends Stop requests back; opening/reloading it never starts a second task.
export function registerComputerPreview(getOwner) {
  let preview = null
  let expanded = false
  let snapshot = null
  let overlay = null
  let overlayTimer = null

  function isOwner(event) {
    return event.sender === getOwner()?.webContents
  }

  function isPreview(event) {
    return preview && event.sender === preview.webContents
  }

  function clearOverlay() {
    clearTimeout(overlayTimer)
    if (overlay && !overlay.isDestroyed()) overlay.destroy()
    overlay = null
  }

  function updateOverlay() {
    const cursor = snapshot?.cursor
    if (!preview || snapshot?.status !== 'running' || snapshot?.dryRun || cursor?.dry_run || !cursor || cursor.target_pid <= 0 || cursor.phase === 'failed') {
      clearOverlay()
      return
    }
    const x = cursor.global_x, y = cursor.global_y
    if (!Number.isFinite(x) || !Number.isFinite(y) || !screen.getAllDisplays().some(({ bounds: b }) => x >= b.x && y >= b.y && x < b.x + b.width && y < b.y + b.height)) {
      clearOverlay()
      return
    }
    if (!overlay || overlay.isDestroyed()) {
      overlay = new BrowserWindow({
        width: 110, height: 80, show: false, frame: false, transparent: true,
        hasShadow: false, focusable: false, skipTaskbar: true, resizable: false,
        alwaysOnTop: true, backgroundColor: '#00000000',
        webPreferences: { preload: join(__dirname, '../preload/index.js'), contextIsolation: true, sandbox: false, nodeIntegration: false },
      })
      overlay.setIgnoreMouseEvents(true)
      overlay.setContentProtection(true)
      overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
      overlay.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
      overlay.webContents.on('will-navigate', event => event.preventDefault())
      const created = overlay
      overlay.on('ready-to-show', () => {
        if (overlay === created && snapshot?.status === 'running') {
          created.webContents.send('computer-preview-state', { cursor: snapshot.cursor })
          created.showInactive()
        }
      })
      if (process.env.ELECTRON_RENDERER_URL) {
        const url = new URL(process.env.ELECTRON_RENDERER_URL)
        url.searchParams.set('cursor', '1')
        overlay.loadURL(url.toString())
      } else overlay.loadFile(join(__dirname, '../renderer/index.html'), { query: { cursor: '1' } })
    }
    overlay.setPosition(Math.round(x - 10), Math.round(y - 10), false)
    overlay.webContents.send('computer-preview-state', { cursor })
    clearTimeout(overlayTimer)
    // Remove even if a model call hangs or the renderer stops publishing.
    overlayTimer = setTimeout(clearOverlay, 2000)
  }

  function broadcast() {
    if (preview && !preview.isDestroyed()) {
      preview.webContents.send('computer-preview-state', { ...snapshot, expanded })
    }
  }

  function resize(large) {
    if (!preview) return
    expanded = large
    const area = screen.getDisplayMatching(preview.getBounds()).workArea
    const width = Math.min(large ? 1100 : 400, area.width)
    const height = Math.min(large ? 760 : 320, area.height)
    const old = preview.getBounds()
    preview.setBounds({
      x: Math.max(area.x, Math.min(old.x, area.x + area.width - width)),
      y: Math.max(area.y, Math.min(old.y, area.y + area.height - height)),
      width, height,
    })
    preview.setAlwaysOnTop(!large)
    broadcast()
  }

  function open() {
    if (preview && !preview.isDestroyed()) {
      preview.showInactive()
      broadcast()
      return
    }
    expanded = false
    const area = screen.getDisplayMatching(getOwner().getBounds()).workArea
    preview = new BrowserWindow({
      width: 400, height: 320, minWidth: 340, minHeight: 260,
      x: Math.max(area.x, area.x + area.width - 420), y: area.y + 24,
      show: false, alwaysOnTop: true, backgroundColor: '#101015',
      title: 'Agent computer', titleBarStyle: 'hiddenInset',
      trafficLightPosition: { x: 14, y: 14 },
      webPreferences: {
        preload: join(__dirname, '../preload/index.js'),
        contextIsolation: true, sandbox: false, nodeIntegration: false,
      },
    })
    // Ask macOS to omit this observation window from desktop captures.
    // Support depends on the OS/capture API; this is not an isolation boundary.
    preview.setContentProtection(true)
    preview.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    preview.webContents.on('will-navigate', event => event.preventDefault())
    preview.on('ready-to-show', () => preview?.showInactive())
    preview.on('closed', () => { preview = null; clearOverlay() })
    if (process.env.ELECTRON_RENDERER_URL) {
      const url = new URL(process.env.ELECTRON_RENDERER_URL)
      url.searchParams.set('computer', '1')
      preview.loadURL(url.toString())
    } else {
      preview.loadFile(join(__dirname, '../renderer/index.html'), { query: { computer: '1' } })
    }
  }

  ipcMain.handle('computer-preview-open', (event) => {
    if (!isOwner(event) || !snapshot) return false
    open()
    // Focus is intentional only when the user explicitly opens the preview.
    // Automatic task-start and cursor updates never activate our windows.
    preview.show()
    preview.focus()
    return true
  })

  ipcMain.handle('computer-preview-start', (event, taskId, title) => {
    if (!isOwner(event) || typeof taskId !== 'string' || typeof title !== 'string') return false
    clearOverlay()
    snapshot = { taskId, title, status: 'running', frame: null, cursor: null, action: 'Starting…', error: '' }
    open()
    broadcast()
    return true
  })

  ipcMain.on('computer-preview-update', (event, taskId, patch) => {
    if (!isOwner(event) || taskId !== snapshot?.taskId || !patch || typeof patch !== 'object') return
    for (const key of ['frame', 'cursor', 'status', 'action', 'error', 'dryRun', 'targetPid', 'targetApp']) {
      if (Object.hasOwn(patch, key)) snapshot[key] = patch[key]
    }
    if (Object.hasOwn(patch, 'cursor') || Object.hasOwn(patch, 'status') || Object.hasOwn(patch, 'dryRun')) updateOverlay()
    broadcast()
  })

  ipcMain.handle('computer-preview-state', event => {
    if (overlay && event.sender === overlay.webContents) return { cursor: snapshot?.cursor }
    if (!isPreview(event)) return null
    return { ...snapshot, expanded }
  })

  ipcMain.on('computer-preview-expand', (event, value) => {
    if (isPreview(event)) resize(Boolean(value))
  })

  ipcMain.on('computer-preview-stop', event => {
    if (!isPreview(event) || snapshot?.status !== 'running') return
    snapshot.status = 'stopping'
    clearOverlay()
    broadcast()
    getOwner()?.webContents.send('computer-preview-stop-request', snapshot.taskId)
  })

  return () => {
    clearOverlay()
    if (preview && !preview.isDestroyed()) preview.destroy()
    preview = null
    snapshot = null
  }
}
