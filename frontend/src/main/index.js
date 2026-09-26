import { app, BrowserWindow, Menu, MenuItem, shell, ipcMain } from 'electron'
import { join } from 'path'

const BACKEND_PORT = 7123

const log = {
  info:  (...a) => console.log( '[main]', ...a),
  warn:  (...a) => console.warn('[main]', ...a),
  error: (...a) => console.error('[main]', ...a),
}

// ── Window ────────────────────────────────────────────────────

function createWindow() {
  const win = new BrowserWindow({
    width: 860,
    height: 820,
    minWidth: 340,
    minHeight: 260,
    show: false,
    backgroundColor: '#0d0e11',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 11 },
    title: 'Computer-Use Harness',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Right-click → Inspect Element
  win.webContents.on('context-menu', (_event, params) => {
    const menu = new Menu()

    // "Inspect Element" always available
    menu.append(new MenuItem({
      label: 'Inspect Element',
      click: () => win.webContents.inspectElement(params.x, params.y),
    }))

    // Standard edit actions when text is selected or input is focused
    if (params.selectionText) {
      menu.append(new MenuItem({ type: 'separator' }))
      menu.append(new MenuItem({ role: 'copy' }))
    }
    if (params.isEditable) {
      menu.append(new MenuItem({ type: 'separator' }))
      menu.append(new MenuItem({ role: 'cut' }))
      menu.append(new MenuItem({ role: 'copy' }))
      menu.append(new MenuItem({ role: 'paste' }))
      menu.append(new MenuItem({ role: 'selectAll' }))
    }

    menu.append(new MenuItem({ type: 'separator' }))
    menu.append(new MenuItem({
      label: 'Toggle DevTools',
      accelerator: 'CmdOrCtrl+Alt+I',
      click: () => win.webContents.toggleDevTools(),
    }))
    menu.append(new MenuItem({
      label: 'Reload',
      accelerator: 'CmdOrCtrl+R',
      click: () => win.webContents.reload(),
    }))

    menu.popup({ window: win })
  })

  win.on('ready-to-show', () => {
    log.info('window ready-to-show')
    win.show()
  })

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }

  buildMenu(win)
}

// ── IPC ───────────────────────────────────────────────────────

ipcMain.handle('get-backend-url', () => {
  const url = `http://127.0.0.1:${BACKEND_PORT}`
  log.info(`get-backend-url → ${url}`)
  return url
})

// ── Menu ──────────────────────────────────────────────────────

function buildMenu(win) {
  const isMac = process.platform === 'darwin'

  const template = [
    ...(isMac
      ? [{
          label: app.name,
          submenu: [
            { role: 'about' },
            { type: 'separator' },
            { role: 'services' },
            { type: 'separator' },
            { role: 'hide' },
            { role: 'hideOthers' },
            { role: 'unhide' },
            { type: 'separator' },
            { role: 'quit' },
          ],
        }]
      : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'New Chat',
          accelerator: 'CmdOrCtrl+N',
          click: () =>
            win.webContents.executeJavaScript(
              'window.__cuNewTask && window.__cuNewTask()',
            ),
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        {
          label: 'Window Size',
          submenu: [
            {
              label: 'Tiny  (400 × 600)',
              accelerator: 'CmdOrCtrl+1',
              click: () => { win.setSize(400, 600); win.center() },
            },
            {
              label: 'Compact  (560 × 720)',
              accelerator: 'CmdOrCtrl+2',
              click: () => { win.setSize(560, 720); win.center() },
            },
            {
              label: 'Normal  (860 × 820)',
              accelerator: 'CmdOrCtrl+3',
              click: () => { win.setSize(860, 820); win.center() },
            },
            {
              label: 'Wide  (1280 × 820)',
              accelerator: 'CmdOrCtrl+4',
              click: () => { win.setSize(1280, 820); win.center() },
            },
          ],
        },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac ? [{ type: 'separator' }, { role: 'front' }] : []),
      ],
    },
  ]

  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ── Lifecycle ─────────────────────────────────────────────────

app.whenReady().then(() => {
  log.info('app ready — backend expected at http://127.0.0.1:' + BACKEND_PORT)
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      log.info('activate: no windows open, creating new window')
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  log.info('all windows closed')
  if (process.platform !== 'darwin') app.quit()
})
