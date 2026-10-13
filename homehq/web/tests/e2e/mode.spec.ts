import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type { Snapshot } from '../../src/types';

const fixture = JSON.parse(readFileSync(new URL('../../src/demo-fixture.json', import.meta.url), 'utf8')) as Snapshot;

test.use({ timezoneId: 'America/Los_Angeles', baseURL: process.env.HOMEHQ_CONFIGURED_WEB_URL || 'http://127.0.0.1:5185' });
const project = 'https://reload-test.supabase.co';
const authKey = 'homehq.auth.reload-test.supabase.co';
const modeKey = 'homehq.mode.v1';
const instant = '2026-10-12T00:30:00Z';
const expires_at = Math.floor(Date.parse(instant) / 1000) + 3600;
const claims = { sub: '00000000-0000-4000-8000-000000000001', role: 'authenticated', exp: expires_at };
const encode = (value: object): string => Buffer.from(JSON.stringify(value)).toString('base64url');
const session = { access_token: `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(claims)}.test-signature`,
  refresh_token: 'test-refresh-only', expires_at, expires_in: 3600, token_type: 'bearer',
  user: { id: claims.sub, email: 'owner@example.test', aud: 'authenticated', role: 'authenticated' } };

type ProjectOptions = { expired?: boolean; snapshot?: 'ready' | 'held' | 'failed'; rejectSignIn?: boolean; member?: boolean };
async function isolatedProject(page: Page, mode: 'demo' | 'live' | null, signedIn: boolean, options: ProjectOptions = {}) {
  const requests: string[] = [];
  const logoutScopes: (string | null)[] = [];
  const bodies: { path: string; body: Record<string, unknown> }[] = [];
  const topics: string[] = [];
  const homeId = options.member ? '00000000-0000-4000-8000-000000000099' : claims.sub;
  const linked: {user_id: string; person_id: string}[] = [{ user_id: claims.sub, person_id: options.member ? 'jordan' : 'alex' }];
  let lastCompletion: { id: string; done: boolean; done_by: string | null } | null = null;
  let releaseSnapshot!: () => void;
  const snapshotReady = new Promise<void>((resolve) => { releaseSnapshot = resolve; });
  if (options.snapshot !== 'held') releaseSnapshot();
  const expired = !!options.expired;
  await page.clock.setFixedTime(new Date(instant));
  await page.addInitScript(({ authKey, modeKey, mode, signedIn, session, expired }) => {
    if (localStorage.getItem('homehq.test.seeded')) return;
    localStorage.setItem('homehq.test.seeded', 'yes');
    if (mode) localStorage.setItem(modeKey, mode);
    if (!signedIn) return;
    localStorage.setItem(authKey, JSON.stringify(expired ? { ...session, expires_at: session.expires_at - 7200 } : session));
  }, { authKey, modeKey, mode, signedIn, session, expired });
  // This browser context has a synthetic session and entirely intercepted
  // network. No test touches a user's real project, Auth identity or browser.
  await page.route(`${project}/**`, async (route) => {
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204 }); return; }
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push(path);
    const body = route.request().postDataJSON() as Record<string, unknown> | null;
    if (body) bodies.push({ path, body });
    if (path === '/rest/v1/rpc/homehq_snapshot') {
      await snapshotReady;
      if (options.snapshot === 'failed') {
        await route.fulfill({ status: 503, json: { message: 'Synthetic project unavailable' } });
        return;
      }
      const live = structuredClone(fixture);
      live.home.timezone = 'Asia/Tokyo';
      live.home.demo = false;
      live.home.id = homeId;
      live.viewer = { user_id: claims.sub, person_id: options.member ? 'jordan' : 'alex', is_owner: !options.member };
      live.members = linked;
      if (lastCompletion) {
        const row = live.chores.find((c) => c.id === lastCompletion!.id)!;
        Object.assign(row, lastCompletion, { completed_by_user_id: claims.sub });
      }
      live.people[0].name = 'Live owner';
      await route.fulfill({ json: live });
    } else if (path === '/auth/v1/token') await route.fulfill((expired && url.searchParams.get('grant_type') === 'refresh_token') || options.rejectSignIn
      ? { status: 400, json: { code: 'invalid_credentials', msg: 'Synthetic rejected session' } }
      : { json: session });
    else if (path === '/auth/v1/logout') { logoutScopes.push(url.searchParams.get('scope')); await route.fulfill({ json: {} }); }
    else if (path === '/rest/v1/rpc/homehq_seed_demo') await route.fulfill({ json: {} });
    else if (path === '/auth/v1/signup') {
      await route.fulfill({ json: { ...session, refresh_token: 'separate-member-refresh', user: { ...session.user, id: '00000000-0000-4000-8000-000000000002', email: body!.email, identities: [{ id: 'member-email' }] } } });
    } else if (path === '/rest/v1/rpc/homehq_link_member') {
      linked.push({ user_id: '00000000-0000-4000-8000-000000000002', person_id: String(body!.p_person_id) });
      await route.fulfill({ json: { home_id: homeId } });
    } else if (path === '/rest/v1/rpc/homehq_set_done') {
      lastCompletion = { id: String(body!.p_id), done: !!body!.p_done, done_by: body!.p_done_by as string | null };
      await route.fulfill({ json: { status: 'saved' } });
    } else if (path === '/rest/v1/homehq_checklist') await route.fulfill({ status: 201, json: {} });
    else throw new Error(`Unexpected synthetic project request: ${path}`);
  });
  await page.routeWebSocket('**/realtime/v1/websocket**', (socket) => {
    socket.onMessage((message) => {
      // The pinned Supabase client uses Phoenix's version-2 tuple serializer.
      const [joinRef, ref, topic, event] = JSON.parse(String(message));
      if (event === 'phx_join') topics.push(topic);
      if (!['phx_join', 'phx_leave', 'heartbeat'].includes(event)) return;
      socket.send(JSON.stringify([joinRef, ref, topic, 'phx_reply', { status: 'ok', response: {} }]));
    });
  });
  return { requests, logoutScopes, releaseSnapshot, bodies, topics, homeId };
}

async function expectNoLocalEditor(page: Page): Promise<void> {
  await expect(page.getByRole('button', { name: 'Offline demo', exact: true })).toHaveCount(0);
  await expect(page.locator('.family-lanes')).toHaveCount(0);
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.locator('[data-new], [data-edit], [data-complete], [data-upload], [data-device]')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('homehq.demo.v1'))).toBeNull();
}

test('the environment project ignores legacy browser configuration and restores live data on reload', async ({ page }) => {
  await isolatedProject(page, 'demo', true);
  await page.addInitScript(() => {
    localStorage.setItem('homehq.connection.v1', JSON.stringify({ url: 'https://old-project.supabase.co', key: 'sb_publishable_old' }));
  });
  const legacyRequests: string[] = [];
  await page.route('https://old-project.supabase.co/**', (route) => { legacyRequests.push(route.request().url()); return route.abort(); });
  await page.goto('/editor.html');
  await expect(page.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Offline demo', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  // The home is next-day morning while this browser is still yesterday
  // afternoon. The clock and its greeting must describe the same instant.
  await expect(page.getByText('Good morning, home.', { exact: true })).toBeVisible();
  await expect(page.locator('.big-clock')).toContainText('9:30');
  expect(legacyRequests).toEqual([]);

  await page.getByRole('button', { name: 'Account settings' }).click();
  for (const name of ['Open my project', 'Open offline demo', 'Reset demo']) {
    await expect(page.getByRole('dialog').getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
});

test('a member uses the shared home channel, saves there, and receives their own chore view', async ({ page }) => {
  const mock = await isolatedProject(page, null, true, { member: true });
  await page.goto('/editor.html');
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  expect(mock.topics).toContain(`realtime:homehq:${mock.homeId}`);
  expect(mock.topics).not.toContain(`realtime:homehq:${claims.sub}`);
  await page.getByRole('button', { name: 'Chores', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Claudia', exact: true })).toHaveClass(/on/);
  await page.getByRole('button', { name: 'Account settings' }).click();
  await expect(page.getByRole('dialog')).toContainText('Signed in as Claudia');
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Set up member login' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByRole('button', { name: 'Add chore', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Chore', { exact: true }).fill('Member-created task');
  await page.getByRole('dialog').locator('select[name="who"]').selectOption('jordan');
  await page.getByRole('dialog').getByRole('button', { name: 'Save chore', exact: true }).click();
  await expect.poll(() => mock.bodies.find((r) => r.path === '/rest/v1/homehq_checklist')?.body.owner_id).toBe(mock.homeId);
  const anyone = fixture.chores.find((c) => c.who === 'any' && c.routine === 'after' && !c.done)!;
  await page.getByRole('checkbox', { name: anyone.title, exact: true }).click();
  await expect.poll(() => mock.bodies.find((r) => r.path === '/rest/v1/rpc/homehq_set_done')?.body.p_done_by).toBe('jordan');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.check-row').filter({ has: page.getByRole('checkbox', { name: anyone.title, exact: true }) }).getByText('Done by Claudia', { exact: true })).toBeVisible();
});

test('an owner creates and links a member without switching or persisting the member session', async ({ page }) => {
  const mock = await isolatedProject(page, null, true);
  await page.goto('/editor.html');
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Account settings' }).click();
  const form = page.getByRole('dialog').locator('[data-member]');
  await form.locator('select[name="person_id"]').selectOption('jordan');
  await form.getByLabel('Member email', { exact: true }).fill('claudia@example.test');
  await form.getByLabel('New account password (optional)', { exact: true }).fill('Member-Password-Only');
  await form.getByRole('button', { name: 'Set up member login', exact: true }).click();
  await expect.poll(() => mock.bodies.find((r) => r.path === '/rest/v1/rpc/homehq_link_member')?.body).toEqual({ p_email: 'claudia@example.test', p_person_id: 'jordan' });
  await expect(page.getByRole('dialog').locator('.account-email')).toHaveText('owner@example.test');
  await expect(page.getByRole('dialog').locator('.member-login-row').filter({ hasText: 'Claudia' })).toContainText('Login linked');
  const saved = await page.evaluate((key) => ({ session: JSON.parse(localStorage.getItem(key)!), signup: Object.keys(localStorage).filter((name) => name.startsWith('homehq.signup.')) }), authKey);
  expect(saved.session.user.id).toBe(claims.sub);
  expect(saved.signup).toEqual([]);
  expect(mock.logoutScopes).toEqual(['local']);
});

test('a configured project with no session stays at sign-in and cannot edit local sample data', async ({ page }) => {
  const mock = await isolatedProject(page, 'demo', false);
  await page.goto('/editor.html');
  await expect(page.locator('.connection')).toHaveText('Sign in');
  await expectNoLocalEditor(page);
  await page.getByRole('button', { name: 'Shopping', exact: true }).click();
  await expectNoLocalEditor(page);
  await page.getByRole('button', { name: 'Account settings' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(dialog.locator('input')).toHaveCount(2);
  await expect(dialog.getByLabel('Email', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('Password', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('Supabase project URL')).toHaveCount(0);
  await expect(dialog.getByLabel('Publishable API key')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Save connection', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Open my project', exact: true })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/homehq-env-signin.png', fullPage: true });
  expect(mock.requests).toEqual([]);
});

test('a normal Auth session restores the environment project after reload', async ({ page }) => {
  await isolatedProject(page, null, false);
  await page.goto('/editor.html');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await page.getByRole('dialog').getByLabel('Email', { exact: true }).fill('owner@example.test');
  await page.getByRole('dialog').getByLabel('Password', { exact: true }).fill('Test-Password-Only');
  await page.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  await expect(page.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('homehq.connection.v1'))).toBeNull();
});

test('a rejected expired session requires sign-in and a new login recovers live data', async ({ page }) => {
  const authWarnings: string[] = [];
  page.on('console', (message) => { if (message.text().includes('Multiple GoTrueClient')) authWarnings.push(message.text()); });
  const mock = await isolatedProject(page, 'live', true, { expired: true });
  await page.goto('/editor.html');
  await expect(page.locator('.connection')).toHaveText('Sign in');
  await expectNoLocalEditor(page);
  expect(mock.requests).toContain('/auth/v1/token');
  expect(mock.requests).not.toContain('/rest/v1/rpc/homehq_seed_demo');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await page.getByRole('dialog').getByLabel('Email', { exact: true }).fill('owner@example.test');
  await page.getByRole('dialog').getByLabel('Password', { exact: true }).fill('Test-Password-Only');
  await page.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  expect(mock.topics).toEqual([`realtime:homehq:${mock.homeId}`]);
  expect(authWarnings).toEqual([]);
});

test('initial snapshot loading shows no sample editor until the project data arrives', async ({ page }) => {
  const mock = await isolatedProject(page, 'demo', true, { snapshot: 'held' });
  await page.goto('/editor.html');
  await expect.poll(() => mock.requests.filter((path) => path === '/rest/v1/rpc/homehq_snapshot').length).toBeGreaterThan(0);
  await expectNoLocalEditor(page);
  await page.getByRole('button', { name: 'Shopping', exact: true }).click();
  await expectNoLocalEditor(page);
  mock.releaseSnapshot();
  await expect(page.getByRole('checkbox', { name: 'Bananas', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
});

test('initial snapshot failure keeps the project connection and does not substitute local edits', async ({ page }) => {
  const mock = await isolatedProject(page, 'demo', true, { snapshot: 'failed' });
  await page.goto('/editor.html');
  await expect(page.getByRole('alert')).toContainText('Synthetic project unavailable');
  await expectNoLocalEditor(page);
  await page.getByRole('button', { name: 'Shopping', exact: true }).click();
  await expectNoLocalEditor(page);
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('Synthetic project unavailable');
  await expectNoLocalEditor(page);
  expect(mock.requests.filter((path) => path === '/rest/v1/rpc/homehq_snapshot').length).toBeGreaterThanOrEqual(2);
});

test('a rejected password does not enable an offline editor', async ({ page }) => {
  await isolatedProject(page, 'demo', false, { rejectSignIn: true });
  await page.goto('/editor.html');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await page.getByRole('dialog').getByLabel('Email', { exact: true }).fill('owner@example.test');
  await page.getByRole('dialog').getByLabel('Password', { exact: true }).fill('Test-Password-Only');
  await page.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('dialog').locator('[data-auth]').getByRole('alert')).toContainText('Synthetic rejected session');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expectNoLocalEditor(page);
});

test('browser sign-out revokes only its session and keeps the configured sign-in screen', async ({ browser, page }) => {
  const mock = await isolatedProject(page, 'demo', true);
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  try {
    const otherMock = await isolatedProject(other, null, true);
    await Promise.all([page.goto('/editor.html'), other.goto('/editor.html')]);
    for (const tab of [page, other]) await expect(tab.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Account settings' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.locator('.connection')).toHaveText('Sign in');
    await expectNoLocalEditor(page);
    expect(mock.logoutScopes).toEqual(['local']);
    await page.reload();
    await expect(page.locator('.connection')).toHaveText('Sign in');
    await expectNoLocalEditor(page);
    await other.reload();
    await expect(other.locator('.family-lanes').getByText('Live owner', { exact: true })).toBeVisible();
    expect(otherMock.logoutScopes).toEqual([]);
    expect(await other.evaluate((key) => !!localStorage.getItem(key), authKey)).toBe(true);
  } finally { await otherContext.close(); }
});
