import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('appInfo', {
  name: 'Computer-Use Harness', version: '0.3.0', mode: 'desktop-shell',
})

function subscribe(channel, listener) {
  const handler = (_event, value) => listener(value)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

contextBridge.exposeInMainWorld('electronBridge', {
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  startComputerPreview: (taskId, title) => ipcRenderer.invoke('computer-preview-start', taskId, title),
  updateComputerPreview: (taskId, patch) => ipcRenderer.send('computer-preview-update', taskId, patch),
  openComputerPreview: () => ipcRenderer.invoke('computer-preview-open'),
  getComputerPreview: () => ipcRenderer.invoke('computer-preview-state'),
  onComputerPreview: listener => subscribe('computer-preview-state', listener),
  expandComputerPreview: value => ipcRenderer.send('computer-preview-expand', value),
  stopComputerPreview: () => ipcRenderer.send('computer-preview-stop'),
  onComputerStop: listener => subscribe('computer-preview-stop-request', listener),
})
