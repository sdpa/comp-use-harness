import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('appInfo', {
  name:    'Computer-Use Harness',
  version: '0.1.0',
  mode:    'desktop-shell',
})

// Expose the backend URL resolved from the main process
contextBridge.exposeInMainWorld('electronBridge', {
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
})
