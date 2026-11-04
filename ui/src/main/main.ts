// CHAD's tray application: one hidden-on-close window per data root, driven by the dispatcher.

import { app, BrowserWindow, ipcMain, Menu, Tray } from 'electron';
import os from 'node:os';
import path from 'node:path';

import { MODE_LABELS, type UiRequest, type UiState } from '../shared/types';
import { DispatcherClient } from './dispatcher';
import { trayIcon } from './icon';

const TITLE = 'CHAD - Cross Harness Allow/Deny';
// Once connected, a dispatcher that stays gone this long is not coming back: the UI leaves too.
const ORPHAN_MS = 30000;
// For automated tests: the window is never put on screen; raising it only counts.
const HIDDEN = ['1', 'true', 'yes', 'on', 'y'].includes((process.env.CHAD_UI_HIDDEN ?? '').trim().toLowerCase());

function dataRoot(): string {
  const flag = process.argv.indexOf('--data-root');
  if (flag >= 0 && process.argv[flag + 1]) return path.resolve(process.argv[flag + 1]);
  if (process.env.CHAD_HOME) return path.resolve(process.env.CHAD_HOME);
  // Same as paths.default_root() in the Python package.
  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'CHAD');
  }
  return path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state'), 'chad');
}

const root = dataRoot();
// Electron's single-instance lock is per profile folder, so a profile per data root gives one
// window per data root.
app.setPath('userData', path.join(root, 'ui-profile'));

let window: BrowserWindow | null = null;
let tray: Tray | null = null;
let state: UiState | null = null;
let seenAttention = 0;
let quitting = false;
let orphanTimer: NodeJS.Timeout | null = null;
const client = new DispatcherClient(root);

function createWindow(): BrowserWindow {
  const created = new BrowserWindow({
    width: 1040,
    height: 790,
    minWidth: 600,
    minHeight: 460,
    show: false,
    title: TITLE,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      // A hidden window must keep rendering: it is shown on demand and driven by tests unseen.
      backgroundThrottling: false,
    },
  });
  created.on('close', (event) => {
    if (!quitting) {
      event.preventDefault();
      created.hide();
    }
  });
  created.webContents.on('will-navigate', (event) => event.preventDefault());
  created.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  void created.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  return created;
}

let raised = 0;

function showWindow(): void {
  if (!window) return;
  raised += 1;
  (globalThis as { chadRaised?: number }).chadRaised = raised;
  if (HIDDEN) return;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
}

function updateTray(): void {
  if (!tray) return;
  const pending = state?.pending.length ?? 0;
  const headline = state
    ? `CHAD: ${MODE_LABELS[state.mode]}${pending ? ` - ${pending} waiting` : ''}`
    : 'CHAD: not connected';
  tray.setImage(trayIcon(state ? state.mode : 'offline', pending));
  tray.setToolTip(headline);
  const open = (target: string) => () => void client.request({ action: 'open', target });
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: headline, enabled: false },
      { type: 'separator' },
      {
        label: 'Rules and mode…',
        click: () => void client.request({ action: 'showPolicy' }).then(showWindow),
      },
      { label: 'Edit allow-list.yaml', click: open('allow') },
      { label: 'Edit deny-list.yaml', click: open('deny') },
      { label: 'Edit config.yaml', click: open('config') },
      { label: 'Show audit.log', click: open('audit') },
      { label: 'Show the CHAD folder', click: open('folder') },
      { type: 'separator' },
      { label: 'Quit CHAD', click: () => void exit() },
    ]),
  );
}

async function exit(): Promise<void> {
  await client.request({ action: 'shutdown' }, 3000);
  quitting = true;
  app.quit();
}

function onState(next: UiState): void {
  state = next;
  if (orphanTimer) {
    clearTimeout(orphanTimer);
    orphanTimer = null;
  }
  window?.webContents.send('state', state);
  updateTray();
  // Raise the window when the dispatcher asks for attention: a queued command or a control
  // request. A fresh window raises itself only if something asked before it connected.
  if (state.attentionVersion !== seenAttention) {
    const raise = seenAttention !== 0 || state.attentionVersion > 0;
    seenAttention = state.attentionVersion;
    if (raise) showWindow();
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showWindow);
  app.on('window-all-closed', () => undefined); // the tray keeps the app alive
  app.on('before-quit', () => {
    quitting = true;
  });

  void app.whenReady().then(() => {
    window = createWindow();
    tray = new Tray(trayIcon('offline', 0));
    tray.on('click', showWindow);
    updateTray();

    ipcMain.handle('get-state', () => state);
    ipcMain.handle('act', (_event, request: UiRequest) => client.request(request));
    ipcMain.on('hide', () => window?.hide());

    client.on('state', onState);
    client.on('disconnected', () => {
      state = null;
      window?.webContents.send('state', null);
      updateTray();
      orphanTimer ??= setTimeout(() => {
        quitting = true;
        app.quit();
      }, ORPHAN_MS);
    });
    client.start();
  });
}
