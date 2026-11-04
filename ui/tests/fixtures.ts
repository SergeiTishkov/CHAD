// End-to-end fixtures: a real Python dispatcher in a throwaway data root, the real Electron
// window, and hook processes started exactly as Claude Code starts them.

import { _electron as electron, test as base, type ElectronApplication, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

export const uiDir = path.resolve(__dirname, '..');
const repo = path.resolve(uiDir, '..');
const python =
  process.platform === 'win32'
    ? path.join(repo, '.venv', 'Scripts', 'python.exe')
    : path.join(repo, '.venv', 'bin', 'python');

export interface Chad {
  home: string;
  env: NodeJS.ProcessEnv;
  request(body: Record<string, unknown>): Promise<any>;
  hook(command: string, tool?: string, description?: string): HookRun;
  readFile(name: string): string;
}

export interface HookRun {
  result: Promise<any>;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function send(home: string, body: Record<string, unknown>): Promise<any> {
  const runtime = JSON.parse(readFileSync(path.join(home, 'dispatcher.json'), 'utf8'));
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: '127.0.0.1', port: runtime.port });
    let buffer = '';
    socket.setEncoding('utf8');
    socket.on('connect', () => socket.write(JSON.stringify({ ...body, token: runtime.token }) + '\n'));
    socket.on('data', (chunk: string) => {
      buffer += chunk;
      const newline = buffer.indexOf('\n');
      if (newline >= 0) {
        socket.destroy();
        resolve(JSON.parse(buffer.slice(0, newline)));
      }
    });
    socket.on('error', reject);
  });
}

async function waitForDispatcher(home: string): Promise<void> {
  for (let i = 0; i < 200; i++) {
    if (existsSync(path.join(home, 'dispatcher.json'))) {
      try {
        if ((await send(home, { op: 'ping' })).ok) return;
      } catch {
        // still starting
      }
    }
    await sleep(100);
  }
  throw new Error('the dispatcher did not start');
}

export const test = base.extend<{ chad: Chad; app: ElectronApplication; page: Page }>({
  chad: async ({}, use) => {
    const home = mkdtempSync(path.join(os.tmpdir(), 'chad-e2e-'));
    // CHAD runs the commands it is asked about, so they run in a throwaway folder, never the repo.
    const work = path.join(home, 'work');
    mkdirSync(work);
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      CHAD_HOME: home,
      CHAD_ISOLATED: '1',
      // The test launches the window itself; the dispatcher must not start a second one.
      CHAD_UI_DISABLED: '1',
      CLAUDE_CONFIG_DIR: path.join(home, 'claude'),
    };
    // VS Code sets this for its children; Electron would start as plain Node.
    delete env.ELECTRON_RUN_AS_NODE;
    // Never put a window on the screen of whoever runs the tests.
    env.CHAD_UI_HIDDEN = '1';
    const dispatcher: ChildProcess = spawn(python, ['-m', 'chad.dispatcher'], { env, stdio: 'ignore' });
    const hooks: ChildProcess[] = [];
    await waitForDispatcher(home);
    await use({
      home,
      env,
      request: (body) => send(home, body),
      readFile: (name) => readFileSync(path.join(home, name), 'utf8'),
      hook(command, tool = 'Bash', description = 'end-to-end test') {
        const child = spawn(python, ['-m', 'chad.hook'], { env });
        hooks.push(child);
        let stdout = '';
        child.stdout!.setEncoding('utf8');
        child.stdout!.on('data', (chunk: string) => (stdout += chunk));
        child.stdin!.end(
          JSON.stringify({
            session_id: 'e2e',
            cwd: work,
            permission_mode: 'default',
            hook_event_name: 'PreToolUse',
            tool_name: tool,
            tool_input: { command, description },
          }),
        );
        return {
          result: new Promise((resolve) => child.on('close', () => resolve(JSON.parse(stdout || '{}')))),
        };
      },
    });
    try {
      await send(home, { op: 'ui', action: 'shutdown' });
    } catch {
      // already gone
    }
    await sleep(500);
    for (const child of [...hooks, dispatcher]) if (child.exitCode === null) child.kill();
    rmSync(home, { recursive: true, force: true, maxRetries: 5 });
  },
  app: async ({ chad }, use) => {
    const app = await electron.launch({ args: [uiDir, '--data-root', chad.home], env: chad.env as Record<string, string> });
    await use(app);
    await app.evaluate(({ app: electronApp }) => {
      electronApp.exit(0);
    }).catch(() => undefined);
    await app.close().catch(() => undefined);
  },
  page: async ({ app }, use) => {
    const page = await app.firstWindow();
    await page.waitForLoadState('domcontentloaded');
    await use(page);
  },
});

export { expect } from '@playwright/test';

/** How many times the app raised its window (counted even though it stays hidden). */
export function timesRaised(app: ElectronApplication): Promise<number> {
  return app.evaluate(() => (globalThis as { chadRaised?: number }).chadRaised ?? 0);
}

export function decisionOf(output: any): string | undefined {
  return output?.hookSpecificOutput?.permissionDecision;
}

/** CHAD never answers allow: an allowed command is run by CHAD and answered deny with its output. */
export function ranByChad(output: any): boolean {
  const reason: string = output?.hookSpecificOutput?.permissionDecisionReason ?? '';
  return decisionOf(output) === 'deny' && reason.includes('COMMAND EXECUTED');
}
