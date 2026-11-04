import { decisionOf, expect, ranByChad, test, timesRaised } from './fixtures';

test('a new command raises the window, arms after a moment, and is run once', async ({ app, chad, page }) => {
  const before = await timesRaised(app);
  const run = chad.hook('git push origin main');
  await expect(page.getByTestId('command')).toHaveText('git push origin main');
  expect(await timesRaised(app)).toBeGreaterThan(before);
  expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isVisible())).toBe(false);
  const allowOnce = page.getByRole('button', { name: 'Allow once' });
  await expect(allowOnce).toBeDisabled();
  await expect(allowOnce).toBeEnabled({ timeout: 3000 });
  await allowOnce.click();
  expect(ranByChad(await run.result)).toBe(true);
  await expect(page.getByText('No command is waiting for approval.')).toBeAttached();
});

test('a wildcard word turns Allow forever into a pattern rule', async ({ chad, page }) => {
  const run = chad.hook('git commit -m "first try"');
  await page.getByRole('button', { name: 'Wildcard "first try"' }).click();
  await expect(page.getByTestId('preview')).toHaveText('Allows: git commit -m *');
  await page.getByRole('button', { name: 'Allow forever' }).click();
  expect(ranByChad(await run.result)).toBe(true);
  expect(chad.readFile('allow-list.yaml')).toContain('value: git commit -m *');

  const again = chad.hook('git commit -m "second"');
  expect(ranByChad(await again.result)).toBe(true);
});

test('dropping a word the rule needs blocks remembering it', async ({ chad, page }) => {
  const run = chad.hook('npm test');
  await page.getByRole('checkbox', { name: 'Keep test' }).uncheck();
  await expect(page.getByTestId('preview')).toContainText('would not allow this statement itself');
  await expect(page.getByRole('button', { name: 'Allow once' })).toBeEnabled({ timeout: 3000 });
  await expect(page.getByRole('button', { name: 'Allow forever' })).toBeDisabled();
  await page.getByRole('button', { name: 'Allow once' }).click();
  expect(ranByChad(await run.result)).toBe(true);
});

test('deny takes two steps and carries the reason to the model', async ({ chad, page }) => {
  const run = chad.hook('npm publish');
  await page.getByRole('button', { name: 'Deny…' }).click();
  await page.getByPlaceholder('Why not? The model reads this. (optional)').fill('wrong registry');
  await page.getByRole('button', { name: 'Deny', exact: true }).click();
  const output = await run.result;
  expect(decisionOf(output)).toBe('deny');
  expect(output.hookSpecificOutput.permissionDecisionReason).toContain('wrong registry');
});

test('commands queue in order and can be browsed', async ({ chad, page }) => {
  const first = chad.hook('echo one');
  await expect(page.getByTestId('command')).toHaveText('echo one');
  const second = chad.hook('echo two');
  await expect(page.getByText('Command 1 of 2')).toBeVisible();
  await expect(page.getByTestId('command')).toHaveText('echo one');
  await page.getByRole('button', { name: 'Next command' }).click();
  await expect(page.getByTestId('command')).toHaveText('echo two');
  await expect(page.getByRole('button', { name: 'Allow once' })).toBeEnabled({ timeout: 3000 });
  await page.getByRole('button', { name: 'Allow once' }).click();
  expect(ranByChad(await second.result)).toBe(true);
  await expect(page.getByTestId('command')).toHaveText('echo one');
  await expect(page.getByRole('button', { name: 'Allow once' })).toBeEnabled({ timeout: 3000 });
  await page.getByRole('button', { name: 'Allow once' }).click();
  expect(ranByChad(await first.result)).toBe(true);
});

test('the policy view switches modes and edits both lists', async ({ chad, page }) => {
  await chad.request({ op: 'ui', action: 'showPolicy' });
  await page.getByRole('radio', { name: /Allow all/ }).check();
  await expect.poll(() => chad.readFile('user-environment.json')).toContain('CHAD_ALLOW_ALL');
  expect(ranByChad(await chad.hook('anything goes').result)).toBe(true);
  await page.getByRole('radio', { name: /^CHAD/ }).check();

  await page.getByRole('checkbox', { name: /Deny list armed/ }).check();
  await expect.poll(() => chad.readFile('user-environment.json')).toContain('CHAD_DENY');

  await page.getByPlaceholder('Allow a command or pattern, e.g. git log *').fill('git log *');
  await page.getByRole('button', { name: 'Add' }).click();
  await expect(page.getByRole('cell', { name: 'git log *', exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Selective: git log *' }).check();
  await expect.poll(() => chad.readFile('allow-list.yaml')).toContain('selective: true');
  expect(ranByChad(await chad.hook('git log -5').result)).toBe(true);
  await page.getByRole('button', { name: 'Delete git log *' }).click();
  await expect(page.getByRole('cell', { name: 'git log *', exact: true })).toHaveCount(0);

  await page.getByRole('tab', { name: /Denied/ }).click();
  await page.getByPlaceholder('Search').fill('reset');
  await expect(page.getByRole('cell', { name: 'git reset --hard', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'rm -rf', exact: true })).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'Enabled: git reset --hard' }).uncheck();
  await expect.poll(() => chad.readFile('deny-list.yaml')).toContain('enabled: false');
});

test('the policy marker brings the policy view forward', async ({ chad, page }) => {
  const output = await chad.hook('#chad:allow-deny-list').result;
  expect(decisionOf(output)).toBe('deny');
  await expect(page.getByRole('radiogroup', { name: 'Mode' })).toBeVisible();
});

test('a long allow list scrolls inside the window', async ({ chad, page }) => {
  for (let i = 1; i <= 40; i++) {
    expect((await chad.request({ op: 'ui', action: 'addAllow', value: `echo rule-${i}` })).ok).toBe(true);
  }
  await chad.request({ op: 'ui', action: 'showPolicy' });
  const last = page.getByRole('cell', { name: 'echo rule-40', exact: true });
  await expect(last).toBeAttached();
  await expect(last).not.toBeInViewport();
  await page.mouse.move(400, 400);
  // A hidden window answers each wheel event slowly, so two large steps instead of many small ones.
  for (let i = 0; i < 2; i++) await page.mouse.wheel(0, 3000);
  await expect(last).toBeInViewport();
  await page.getByRole('button', { name: 'Delete echo rule-40' }).click();
  await expect(last).toHaveCount(0);
});

test('an allow rule is edited word by word where it stands', async ({ chad, page }) => {
  for (const value of ['echo first', 'git log -5', 'echo last']) {
    expect((await chad.request({ op: 'ui', action: 'addAllow', value })).ok).toBe(true);
  }
  await chad.request({ op: 'ui', action: 'showPolicy' });
  await page.getByRole('button', { name: 'Edit git log -5' }).click();
  await page.getByRole('button', { name: 'Wildcard word 3' }).click();
  await page.getByRole('button', { name: '+ Word' }).click();
  await page.getByRole('textbox', { name: 'Word 4' }).fill('--oneline');
  await page.getByRole('button', { name: 'Move word 4 left' }).click();
  await page.getByRole('textbox', { name: 'Word 2' }).fill('lg');
  await expect(page.getByTestId('edit-preview')).toHaveText('git lg --oneline *');
  await page.getByRole('textbox', { name: 'Word 2' }).fill('log');
  await page.getByRole('button', { name: 'Save' }).click();

  const rules = page.locator('td.rule code');
  await expect(rules).toHaveText(['echo first', 'git log --oneline *', 'echo last']);
  await expect.poll(() => chad.readFile('allow-list.yaml')).toContain('value: git log --oneline *');
  expect(ranByChad(await chad.hook('git log --oneline -3').result)).toBe(true);

  await page.getByRole('button', { name: 'Edit git log --oneline *' }).click();
  await page.getByRole('button', { name: 'Remove word 4' }).click();
  await page.getByRole('button', { name: 'Remove word 3' }).click();
  await page.getByRole('button', { name: 'Cancel editing git log --oneline *' }).click();
  await expect(rules).toHaveText(['echo first', 'git log --oneline *', 'echo last']);
});

test('a redirect to a local file is remembered only as written', async ({ chad, page }) => {
  const run = chad.hook('echo built > out.log');
  await expect(page.getByTestId('command')).toHaveText('echo built > out.log');
  await page.getByRole('button', { name: 'Wildcard out.log' }).click();
  await expect(page.getByTestId('preview')).toContainText('would not allow this statement itself');
  await expect(page.getByRole('button', { name: 'Allow forever' })).toBeDisabled();
  await page.getByRole('button', { name: 'Wildcard out.log' }).click();
  await page.getByRole('button', { name: 'Wildcard built' }).click();
  await expect(page.getByTestId('preview')).toHaveText('Allows: echo * > out.log');
  await page.getByRole('button', { name: 'Allow forever' }).click();
  expect(ranByChad(await run.result)).toBe(true);
  expect(chad.readFile('allow-list.yaml')).toContain('value: echo * > out.log');

  expect(ranByChad(await chad.hook('echo again > out.log').result)).toBe(true);
  expect(chad.readFile('work/out.log').trim()).toBe('again');
});
