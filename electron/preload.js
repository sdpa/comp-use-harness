const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('appInfo', {
  name: 'Computer-Use Harness',
  version: '0.1.0',
  mode: 'desktop-shell',
});
