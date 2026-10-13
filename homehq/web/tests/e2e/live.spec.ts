import { randomUUID } from 'node:crypto';
import { test, expect, type Page } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';

const url = process.env.HOMEHQ_TEST_URL;
const key = process.env.HOMEHQ_TEST_KEY;
const webURL = process.env.HOMEHQ_LIVE_WEB_URL;
test.use({ baseURL: webURL || 'http://127.0.0.1:5186' });
test.skip(!url || !key || !webURL, 'Live tests require a disposable local Supabase project and a Vite server configured for it.');

async function connect(page: Page): Promise<void> {
  await page.goto('/editor.html');
  await page.getByRole('button', { name: 'Account settings' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Email', { exact: true })).toBeVisible();
  await expect(dialog.locator('input')).toHaveCount(2);
  await expect(dialog.getByLabel('Supabase project URL')).toHaveCount(0);
  await expect(dialog.getByLabel('Publishable API key')).toHaveCount(0);
}

test('new owner signup, independent same-owner sessions, private Realtime and RLS', async ({ browser, page }) => {
  const email = `homehq-ui-${randomUUID()}@example.com`;
  const password = `Local-Test-${randomUUID()}`;
  await connect(page);
  await page.getByRole('dialog').getByLabel('Email', { exact: true }).fill(email);
  await page.getByRole('dialog').getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('dialog').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible({ timeout: 25_000 });
  await expect(page.locator('.family-lanes').getByText('Wes', { exact: true })).toBeVisible();

  const secondContext = await browser.newContext();
  const second = await secondContext.newPage();
  await connect(second);
  await second.getByRole('dialog').getByLabel('Email', { exact: true }).fill(email);
  await second.getByRole('dialog').getByLabel('Password', { exact: true }).fill(password);
  await second.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(second.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  for (const tab of [page, second]) await tab.getByRole('button', { name: 'Chores', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Homework', exact: true }).click();
  await expect(second.getByRole('checkbox', { name: 'Homework', exact: true })).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(second.getByRole('checkbox', { name: 'Homework', exact: true })).toHaveAttribute('aria-checked', 'false');

  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.locator('.person-header').filter({ hasText: 'Wes' }).click();
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Wes on the badge');
  await page.getByRole('dialog').getByRole('button', { name: 'Save person', exact: true }).click();
  await second.getByRole('button', { name: 'Today', exact: true }).click();
  await expect(second.locator('.family-lanes').getByText('Wes on the badge', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Calendar', exact: true }).click();
  await page.getByRole('button', { name: 'Add event', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Event title').fill('Family pickup');
  await page.getByRole('dialog').getByLabel('Who’s going?').selectOption(['otto', 'jordan']);
  await page.getByRole('dialog').getByRole('button', { name: 'Save event' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await second.getByRole('button', { name: 'Calendar', exact: true }).click();
  await expect(second.locator('.calendar-event').filter({ hasText: 'Family pickup' })).toContainText('Skidmark');
  await expect(second.locator('.calendar-event').filter({ hasText: 'Family pickup' })).toContainText('Claudia');

  const source = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const context = canvas.getContext('2d')!; context.fillStyle = '#315342'; context.fillRect(0, 0, 640, 480);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.getByRole('button', { name: 'Photos', exact: true }).click();
  await page.getByRole('button', { name: 'Add photo', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Photo', { exact: true }).setInputFiles({ name: 'family.png', mimeType: 'image/png', buffer: Buffer.from(source, 'base64') });
  await page.getByRole('dialog').getByLabel('Place').fill('A private little memory');
  await page.getByRole('dialog').getByRole('button', { name: 'Add photo', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await second.getByRole('button', { name: 'Photos', exact: true }).click();
  const uploaded = second.getByRole('img', { name: 'A private little memory', exact: true });
  await expect(uploaded).toHaveAttribute('src', /storage\/v1\/object\/sign\/homehq-photos\//);
  await expect.poll(() => uploaded.evaluate((image: HTMLImageElement) => [image.naturalWidth, image.naturalHeight])).toEqual([320, 240]);
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.screenshot({ path: 'test-results/homehq-live.png', fullPage: true });

  const owner = createClient(url!, key!, { auth: { persistSession: false, autoRefreshToken: false } });
  const ownerSignIn = await owner.auth.signInWithPassword({ email, password });
  expect(ownerSignIn.error).toBeNull();
  const ownerId = ownerSignIn.data.user!.id;
  const other = createClient(url!, key!, { auth: { persistSession: false, autoRefreshToken: false } });
  const otherSignup = await other.auth.signUp({ email: `homehq-other-${randomUUID()}@example.com`, password: `Local-Test-${randomUUID()}` });
  expect(otherSignup.error).toBeNull();
  const read = await other.from('homehq_people').select('id').eq('owner_id', ownerId);
  expect(read.error).toBeNull(); expect(read.data).toEqual([]);
  const write = await other.from('homehq_people').update({ name: 'Unexpected cross-owner edit' }).eq('owner_id', ownerId).eq('id', 'alex').select('id');
  expect(write.data).toEqual([]);
  const check = await owner.from('homehq_people').select('name').eq('id', 'alex').single();
  expect(check.data?.name).toBe('Wes on the badge');
  const photos = await owner.from('homehq_photos').select('path').not('path', 'is', null).limit(1).single();
  const privateObject = await other.storage.from('homehq-photos').download(photos.data!.path);
  expect(privateObject.error).not.toBeNull();
  const privateChannel = other.channel(`homehq:${ownerId}`, { config: { private: true } });
  const joinStatus = await new Promise<string>((resolve) => {
    const timeout = setTimeout(() => resolve('TIMED_OUT'), 12_000);
    privateChannel.subscribe((status) => { if (status === 'SUBSCRIBED' || status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') { clearTimeout(timeout); resolve(status); } });
  });
  expect(joinStatus).not.toBe('SUBSCRIBED');
  await other.removeChannel(privateChannel);
  await secondContext.close();
});
