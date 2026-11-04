// The README screenshots. Opt in with CHAD_SCREENSHOTS=1; the window stays hidden while it
// renders, like in every other test.

import path from 'node:path';
import { expect, test, uiDir } from './fixtures';

const images = path.resolve(uiDir, '..', 'docs', 'images');

test.skip(process.env.CHAD_SCREENSHOTS !== '1', 'set CHAD_SCREENSHOTS=1 to refresh docs/images');

test.beforeEach(async ({ app }) => {
  await app.evaluate(({ nativeTheme }) => {
    nativeTheme.themeSource = 'light';
  });
});

test('approval window', async ({ chad, page }) => {
  chad.hook('git add -A && git commit -m "Fix the date parser"', 'Bash', 'Commit the parser fix');
  await expect(page.getByTestId('command')).toContainText('git commit');
  await page.getByRole('button', { name: 'Wildcard "Fix the date parser"' }).click();
  await expect(page.getByRole('button', { name: 'Allow forever' })).toBeEnabled({ timeout: 3000 });
  await page.screenshot({ path: path.join(images, 'approval.png') });
});

test('policy window', async ({ chad, page }) => {
  for (const [value, selective] of [
    ['git status', true],
    ['git log *', true],
    ['git diff *', false],
    ['git commit -m *', false],
    ['npm run *', false],
    ['uv run pytest *', false],
  ] as const) {
    await chad.request({ op: 'ui', action: 'addAllow', value, selective });
  }
  await chad.request({ op: 'ui', action: 'setDeny', value: true });
  await chad.request({ op: 'ui', action: 'showPolicy' });
  await expect(page.getByRole('cell', { name: 'uv run pytest *', exact: true })).toBeVisible();
  // Down to the add row: the summary under it names the test's temporary folder.
  const add = await page.getByRole('button', { name: 'Add' }).boundingBox();
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  await page.screenshot({
    path: path.join(images, 'policy.png'),
    clip: { x: 0, y: 0, width, height: Math.ceil(add!.y + add!.height + 12) },
  });
});
