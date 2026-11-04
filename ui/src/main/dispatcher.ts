// The window's link to the Python dispatcher: a subscription for state, one connection per action.

import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';

import type { UiRequest, UiResponse, UiState } from '../shared/types';

const HOST = '127.0.0.1';
const RECONNECT_MS = 1000;

interface Runtime {
  pid: number;
  port: number;
  token: string;
  protocol: number;
}

export class DispatcherClient extends EventEmitter {
  private socket: net.Socket | null = null;
  private timer: NodeJS.Timeout | null = null;
  private connected = false;

  constructor(private readonly dataRoot: string) {
    super();
  }

  private runtime(): Runtime | null {
    // Re-read on every connection: a restarted dispatcher listens on a new port.
    try {
      const text = readFileSync(path.join(this.dataRoot, 'dispatcher.json'), 'utf8');
      const runtime = JSON.parse(text) as Runtime;
      return runtime.protocol === 1 ? runtime : null;
    } catch {
      return null;
    }
  }

  start(): void {
    this.connect();
  }

  private retry(): void {
    if (this.connected) {
      this.connected = false;
      this.emit('disconnected');
    }
    if (!this.timer) {
      this.timer = setTimeout(() => {
        this.timer = null;
        this.connect();
      }, RECONNECT_MS);
    }
  }

  private connect(): void {
    const runtime = this.runtime();
    if (!runtime) {
      this.retry();
      return;
    }
    const socket = net.createConnection({ host: HOST, port: runtime.port });
    this.socket = socket;
    let buffer = '';
    socket.setEncoding('utf8');
    socket.on('connect', () => {
      socket.write(JSON.stringify({ op: 'subscribe', token: runtime.token }) + '\n');
    });
    socket.on('data', (chunk: string) => {
      buffer += chunk;
      let newline: number;
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        try {
          const message = JSON.parse(line) as { state?: UiState; ok?: boolean };
          if (message.state) {
            this.connected = true;
            this.emit('state', message.state);
          } else if (message.ok === false) {
            socket.destroy();
          }
        } catch {
          // A torn line is followed by a reconnect; nothing to do here.
        }
      }
    });
    socket.on('error', () => undefined);
    socket.on('close', () => {
      if (this.socket === socket) this.socket = null;
      this.retry();
    });
  }

  request(body: UiRequest, timeoutMs = 10000): Promise<UiResponse> {
    const runtime = this.runtime();
    if (!runtime) return Promise.resolve({ ok: false, error: 'CHAD is not running.' });
    return new Promise((resolve) => {
      const socket = net.createConnection({ host: HOST, port: runtime.port });
      let buffer = '';
      let settled = false;
      const finish = (response: UiResponse) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        resolve(response);
      };
      socket.setEncoding('utf8');
      socket.setTimeout(timeoutMs, () => finish({ ok: false, error: 'CHAD did not answer.' }));
      socket.on('connect', () => {
        socket.write(JSON.stringify({ op: 'ui', ...body, token: runtime.token }) + '\n');
      });
      socket.on('data', (chunk: string) => {
        buffer += chunk;
        const newline = buffer.indexOf('\n');
        if (newline < 0) return;
        try {
          finish(JSON.parse(buffer.slice(0, newline)) as UiResponse);
        } catch {
          finish({ ok: false, error: 'CHAD sent an unreadable answer.' });
        }
      });
      socket.on('error', (error) => finish({ ok: false, error: `CHAD is not reachable: ${error.message}` }));
      socket.on('close', () => finish({ ok: false, error: 'CHAD closed the connection.' }));
    });
  }
}
