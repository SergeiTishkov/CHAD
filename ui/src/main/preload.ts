// The only surface the page sees: state in, actions out. No Node APIs reach the renderer.

import { contextBridge, ipcRenderer } from 'electron';

import type { ChadBridge, UiRequest, UiState } from '../shared/types';

const bridge: ChadBridge = {
  onState(listener) {
    ipcRenderer.on('state', (_event, state: UiState | null) => listener(state));
  },
  getState: () => ipcRenderer.invoke('get-state'),
  act: (request: UiRequest) => ipcRenderer.invoke('act', request),
  hide: () => ipcRenderer.send('hide'),
};

contextBridge.exposeInMainWorld('chad', bridge);
