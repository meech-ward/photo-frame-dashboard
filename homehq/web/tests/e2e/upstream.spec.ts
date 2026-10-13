import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import type { Snapshot } from '../../src/types';
import { validateBadgeJPEG } from '../../src/badge-jpeg';

const fixture = JSON.parse(readFileSync(new URL('../../src/demo-fixture.json', import.meta.url), 'utf8')) as Snapshot;
const project = 'https://reload-test.supabase.co';
const authKey = 'homehq.auth.reload-test.supabase.co';
const userId = '00000000-0000-4000-8000-000000000001';
const homeId = '00000000-0000-4000-8000-000000000099';
const instant = '2026-10-12T19:18:00Z';
const expiresAt = Math.floor(Date.parse(instant) / 1000) + 3600;
const encode = (value: object): string => Buffer.from(JSON.stringify(value)).toString('base64url');
const session = {
  access_token: `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub: userId, role: 'authenticated', exp: expiresAt })}.test-signature`,
  refresh_token: 'synthetic-upstream-refresh', expires_at: expiresAt, expires_in: 3600, token_type: 'bearer',
  user: { id: userId, email: 'claudia@example.test', aud: 'authenticated', role: 'authenticated' },
};

test.use({ timezoneId: 'America/Toronto', baseURL: process.env.HOMEHQ_CONFIGURED_WEB_URL || 'http://127.0.0.1:5185' });

async function isolatedHousehold(page: Page, signedIn = true, privatePhoto = false, rejectJPEG = false) {
  const snapshot = structuredClone(fixture);
  const shift = Math.floor(Date.parse(instant) / 1000) - snapshot.server_time;
  snapshot.server_time += shift;
  snapshot.home = { ...snapshot.home, id: homeId, demo: false };
  snapshot.viewer = { user_id: userId, person_id: 'jordan', is_owner: false };
  snapshot.members = [{ user_id: userId, person_id: 'jordan' }];
  snapshot.people[0].name = 'Live Wes';
  for (const event of snapshot.events) { event.start += shift; event.end += shift; }
  const photoPath = `${homeId}/synthetic-photo.png`;
  if (privatePhoto) snapshot.photos = [{ id: 'uploaded', path: photoPath, asset: null, caption: 'Family photo', place: 'Our back garden' }];

  const bodies: { path: string; body: Record<string, unknown>; authorization: string | undefined }[] = [];
  const topics: string[] = [];
  const privateJoins: boolean[] = [];
  const uploads: { path: string; bytes: Buffer; type: string }[] = [];
  let snapshotReads = 0;
  let broadcast: (() => void) | undefined;
  await page.clock.setFixedTime(new Date(instant));
  await page.addInitScript(({ authKey, signedIn, session }) => {
    if (localStorage.getItem('homehq.upstream.test.seeded')) return;
    localStorage.setItem('homehq.upstream.test.seeded', 'yes');
    if (signedIn) localStorage.setItem(authKey, JSON.stringify(session));
  }, { authKey, signedIn, session });

  // The real supabase-js Auth/RPC/Storage/WebSocket client runs here, but every
  // project request is intercepted. This never edits a hosted household.
  await page.route(`${project}/**`, async (route) => {
    if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204 }); return; }
    const path = new URL(route.request().url()).pathname;
    const contentType = route.request().headers()['content-type'] || '';
    const body = contentType.includes('application/json') ? route.request().postDataJSON() as Record<string, unknown> | null : null;
    if (body) bodies.push({ path, body, authorization: route.request().headers().authorization });
    if (path === '/rest/v1/rpc/homehq_snapshot') {
      snapshotReads++;
      await route.fulfill({ json: structuredClone(snapshot) });
    } else if (path === '/rest/v1/rpc/homehq_seed_demo') await route.fulfill({ json: {} });
    else if (path === '/auth/v1/token') await route.fulfill({ json: session });
    else if (path === '/auth/v1/logout') await route.fulfill({ json: {} });
    else if (path === '/rest/v1/rpc/homehq_set_done') {
      const rows = body!.p_kind === 'chore' ? snapshot.chores : snapshot.shopping;
      const row = rows.find((item) => item.id === body!.p_id)!;
      expect(body!.p_version).toBe(row.version);
      row.done = Boolean(body!.p_done);
      row.version++;
      row.completed_by_user_id = row.done ? userId : null;
      if ('done_by' in row) row.done_by = body!.p_done_by as string | null;
      snapshot.revision++;
      await route.fulfill({ json: { status: 'saved' } });
    } else if (path.startsWith(`/storage/v1/object/homehq-photos/${homeId}/`) && route.request().method() === 'POST') {
      const multipart = route.request().postDataBuffer()!;
      const boundary = contentType.split('boundary=')[1];
      const fileHeader = multipart.indexOf('filename="blob"');
      expect(fileHeader).toBeGreaterThan(0);
      const start = multipart.indexOf('\r\n\r\n', fileHeader) + 4;
      const end = multipart.indexOf(`\r\n--${boundary}`, start);
      const type = multipart.subarray(fileHeader, start).toString().match(/Content-Type: ([^\r]+)/)![1];
      uploads.push({ path: path.replace('/storage/v1/object/homehq-photos/', ''), bytes: multipart.subarray(start, end), type });
      if (rejectJPEG && path.endsWith('.jpg')) await route.fulfill({ status: 400, json: { message: 'Synthetic JPEG upload refused' } });
      else await route.fulfill({ json: { Key: path.replace('/storage/v1/object/', '') } });
    } else if (path === '/rest/v1/homehq_photos' && route.request().method() === 'PATCH') {
      expect(new URL(route.request().url()).searchParams.get('owner_id')).toBe(`eq.${homeId}`);
      const photo = snapshot.photos.find((entry) => entry.id === body!.id)!;
      Object.assign(photo, body);
      await route.fulfill({ json: {} });
    } else if (path.startsWith('/storage/v1/object/sign/homehq-photos/') && route.request().method() === 'POST') {
      await route.fulfill({ json: { signedURL: `${path.replace('/storage/v1', '')}?token=synthetic-photo-token` } });
    } else if (path.startsWith('/storage/v1/object/sign/homehq-photos/') && route.request().method() === 'GET') {
      const upload = uploads.find((entry) => path.endsWith(entry.path));
      await route.fulfill({ contentType: upload?.type || 'image/png', body: upload?.bytes || Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64') });
    } else throw new Error(`Unexpected synthetic project request: ${route.request().method()} ${path}`);
  });
  await page.routeWebSocket('**/realtime/v1/websocket**', (socket) => {
    socket.onMessage((message) => {
      // The pinned client uses Phoenix's version-2 tuple serializer. Answering
      // its real join proves the shared household topic reaches SUBSCRIBED.
      const [joinRef, ref, topic, event, payload] = JSON.parse(String(message));
      if (event === 'phx_join') {
        topics.push(topic);
        privateJoins.push(Boolean(payload.config.private));
        broadcast = () => socket.send(JSON.stringify([null, null, topic, 'broadcast', { event: 'changed', payload: { revision: snapshot.revision }, type: 'broadcast' }]));
      }
      if (['phx_join', 'phx_leave', 'heartbeat'].includes(event)) socket.send(JSON.stringify([joinRef, ref, topic, 'phx_reply', { status: 'ok', response: {} }]));
    });
  });
  return { snapshot, bodies, topics, privateJoins, uploads, reads: () => snapshotReads, changed: () => broadcast!(), allowJPEG: () => { rejectJPEG = false; } };
}

async function expectLiveDashboard(page: Page): Promise<void> {
  await expect(page.locator('#view-home .h-lanes')).toContainText('Live Wes');
  await expect(page.locator('#homehq-status')).toContainText(/live/i);
}

async function addTestPhoto(page: Page, type: 'image/png' | 'image/jpeg' | 'image/webp' = 'image/png'): Promise<void> {
  const source = await page.evaluate((type) => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
    const context = canvas.getContext('2d')!;
    const pixels = context.createImageData(320, 240);
    let state = 345678901;
    for (let offset = 0; offset < pixels.data.length; offset += 4) {
      for (let channel = 0; channel < 3; channel++) { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; pixels.data[offset + channel] = state & 255; }
      pixels.data[offset + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
    return canvas.toDataURL(type, 0.92).split(',')[1];
  }, type);
  await page.getByRole('button', { name: 'Photos', exact: true }).click();
  await page.getByRole('button', { name: 'Add photo', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Photo', { exact: true }).setInputFiles({ name: `family.${type.split('/')[1]}`, mimeType: type, buffer: Buffer.from(source, 'base64') });
  await page.getByRole('dialog').getByLabel('Caption').fill('A family memory');
  await page.getByRole('dialog').getByLabel('Place').fill('Our garden');
  await page.getByRole('dialog').getByRole('button', { name: 'Add photo', exact: true }).click();
}

for (const inputType of ['image/png', 'image/jpeg', 'image/webp'] as const) {
  test(`a live ${inputType} upload publishes content-addressed PNG and smaller baseline JPEG variants`, async ({ page }) => {
    const household = await isolatedHousehold(page);
    await page.goto('/editor.html');
    await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
    await addTestPhoto(page, inputType);
    await expect(page.getByRole('dialog')).not.toBeVisible();
    expect(household.uploads).toHaveLength(2);
    const [png, jpeg] = household.uploads;
    expect(png.type).toBe('image/png'); expect(jpeg.type).toBe('image/jpeg');
    expect(png.bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    expect(png.bytes.readUInt32BE(16)).toBe(320); expect(png.bytes.readUInt32BE(20)).toBe(240);
    let idats = 0;
    for (let offset = 8; offset < png.bytes.length; offset += png.bytes.readUInt32BE(offset) + 12) if (png.bytes.toString('ascii', offset + 4, offset + 8) === 'IDAT') idats++;
    expect(idats).toBe(1);
    expect(() => validateBadgeJPEG(jpeg.bytes)).not.toThrow();
    expect(jpeg.bytes.length).toBeLessThan(png.bytes.length);
    for (const [upload, extension] of [[png, 'png'], [jpeg, 'jpg']] as const) {
      expect(upload.path).toBe(`${homeId}/${createHash('sha256').update(upload.bytes).digest('hex')}.${extension}`);
      expect(upload.bytes.length).toBeLessThanOrEqual(327_680);
    }
    const writes = household.bodies.filter((entry) => entry.path === '/rest/v1/homehq_photos');
    expect(writes).toHaveLength(1);
    expect(writes[0].body).toMatchObject({ id: 'p1', owner_id: homeId, path: png.path, jpeg_path: jpeg.path, caption: 'A family memory', place: 'Our garden' });
    const image = page.getByRole('img', { name: 'Our garden', exact: true });
    await expect(image).toHaveAttribute('src', new RegExp(jpeg.path.replace('.', '\\.')));
    await expect.poll(() => image.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([320, 240]);
    await page.getByRole('button', { name: 'Edit photo caption' }).first().click();
    await page.getByRole('dialog').getByLabel('Caption').fill('Same photo, new caption');
    await page.getByRole('dialog').getByRole('button', { name: 'Save photo', exact: true }).click();
    await expect(page.getByRole('dialog')).not.toBeVisible();
    expect(household.snapshot.photos[0]).toMatchObject({ path: png.path, jpeg_path: jpeg.path, caption: 'Same photo, new caption' });
  });
}

test('a failed JPEG upload preserves the photo and retry publishes both variants together', async ({ page }) => {
  const household = await isolatedHousehold(page, true, false, true);
  const original = structuredClone(household.snapshot.photos[0]);
  await page.goto('/editor.html');
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  await addTestPhoto(page);
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Synthetic JPEG upload refused');
  expect(household.snapshot.photos[0]).toEqual(original);
  expect(household.bodies.filter((entry) => entry.path === '/rest/v1/homehq_photos')).toEqual([]);
  household.allowJPEG();
  await page.getByRole('dialog').getByRole('button', { name: 'Add photo', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  expect(household.uploads).toHaveLength(4);
  expect(household.uploads[2].path).toBe(household.uploads[0].path);
  expect(household.uploads[3].path).toBe(household.uploads[1].path);
  expect(household.bodies.filter((entry) => entry.path === '/rest/v1/homehq_photos')).toHaveLength(1);
});

test('the default page uses Wes’s original shell and all seven views with household data', async ({ page }) => {
  await isolatedHousehold(page);
  await page.goto('/');
  await expectLiveDashboard(page);
  await expect(page.locator('#rail .rail-item')).toHaveText(['Today', 'Calendar', 'Chores', 'Shopping', 'Photos', 'Home', 'Agents']);
  await expect(page.locator('#stage.stage')).toBeVisible();
  await expect(page.locator('#view-home .h-clock .h-time')).toContainText('3:18');
  await expect(page.locator('#view-home .h-hero-title')).toHaveText('Piano lesson');
  await expect(page.getByRole('link', { name: 'Edit household', exact: true })).toHaveAttribute('href', '/editor.html');
  await expect(page.locator('.family-lanes')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/homehq-upstream-today.png', fullPage: true });
  for (const [id, root] of [['calendar', '.cal'], ['tasks', '.tasks'], ['shopping', '.shop'], ['photos', '.photos'], ['control', '.hc'], ['agents', '.agents']]) {
    await page.locator(`#rail [data-go="${id}"]`).click();
    await expect(page.locator(`#view-${id}`)).toHaveClass(/is-active/);
    await expect(page.locator(`#view-${id} ${root}`)).toBeVisible();
  }
});

test('a member joins the household’s private channel and broadcast refreshes the original lanes', async ({ page }) => {
  const mock = await isolatedHousehold(page);
  await page.goto('/');
  await expectLiveDashboard(page);
  expect(mock.topics).toContain(`realtime:homehq:${homeId}`);
  expect(mock.topics).not.toContain(`realtime:homehq:${userId}`);
  expect(mock.privateJoins).toEqual([true]);
  const before = mock.reads();
  mock.snapshot.people[0].name = 'Wes from another badge';
  mock.snapshot.revision++;
  mock.changed();
  await expect(page.locator('#view-home .h-lanes')).toContainText('Wes from another badge');
  expect(mock.reads()).toBeGreaterThan(before);
});

test('an original chore button and toast undo save versioned household actions', async ({ page }) => {
  const mock = await isolatedHousehold(page);
  const chore = mock.snapshot.chores.find((item) => item.who === 'jordan' && item.routine === 'after' && !item.done)!;
  await page.goto('/');
  await expectLiveDashboard(page);
  await page.locator('#rail [data-go="tasks"]').click();
  const row = page.locator(`#view-tasks [data-ch="${chore.id}"]`);
  await expect(row).toContainText(chore.title);
  await row.click();
  await expect.poll(() => mock.bodies.filter((request) => request.path.endsWith('/homehq_set_done'))).toHaveLength(1);
  expect(mock.bodies.find((request) => request.path.endsWith('/homehq_set_done'))!.body).toEqual({ p_kind: 'chore', p_id: chore.id, p_done: true, p_version: 1, p_done_by: 'jordan' });
  await expect(row).toHaveClass(/is-done/);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(() => mock.bodies.filter((request) => request.path.endsWith('/homehq_set_done'))).toHaveLength(2);
  expect(mock.bodies.filter((request) => request.path.endsWith('/homehq_set_done'))[1].body).toMatchObject({ p_done: false, p_version: 2 });
  await expect(row).not.toHaveClass(/is-done/);
});

test('the original shopping checklist saves completion to the same backend', async ({ page }) => {
  const mock = await isolatedHousehold(page);
  const item = mock.snapshot.shopping.find((row) => !row.done)!;
  await page.goto('/');
  await expectLiveDashboard(page);
  await page.locator('#rail [data-go="shopping"]').click();
  await page.locator(`#view-shopping [data-check="${item.id}"]`).click();
  await expect.poll(() => mock.bodies.find((request) => request.path.endsWith('/homehq_set_done'))?.body).toEqual({ p_kind: 'shopping', p_id: item.id, p_done: true, p_version: 1, p_done_by: null });
  await expect(page.locator(`#view-shopping .s-list [data-check="${item.id}"]`)).toHaveCount(0);
});

test('a member completing another person’s chore keeps assigned credit and their own Auth identity', async ({ page }) => {
  const mock = await isolatedHousehold(page);
  const chore = mock.snapshot.chores.find((item) => item.who === 'maya' && item.routine === 'after' && !item.done)!;
  await page.goto('/');
  await expectLiveDashboard(page);
  await page.locator('#rail [data-go="tasks"]').click();
  await page.locator(`#view-tasks [data-ch="${chore.id}"]`).click();
  await expect.poll(() => mock.bodies.find((request) => request.path.endsWith('/homehq_set_done'))?.body.p_done_by).toBe('maya');
  const request = mock.bodies.find((request) => request.path.endsWith('/homehq_set_done'))!;
  // Star credit is the assigned person. The normal session's bearer token
  // lets SQL stamp a different signed-in member as the completion actor.
  expect(request.authorization).toBe(`Bearer ${session.access_token}`);
  expect(JSON.parse(Buffer.from(request.authorization!.split('.')[1], 'base64url').toString()).sub).toBe(userId);
  await expect(page.locator(`#view-tasks [data-ch="${chore.id}"]`)).toHaveClass(/is-done/);
});

test('the original photo slideshow uses private bucket signed URLs and works with one photo', async ({ page }) => {
  await isolatedHousehold(page, true, true);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expectLiveDashboard(page);
  await page.locator('#rail [data-go="photos"]').click();
  await expect(page.locator('#view-photos .ph-stage img').first()).toHaveAttribute('src', /storage\/v1\/object\/sign\/homehq-photos\/.+synthetic-photo-token/);
  await expect(page.locator('#view-photos .ph-stage')).toContainText('Our back garden');
  for (const layout of ['cover', 'pair', 'collage', 'polaroid']) {
    await page.locator(`#view-photos [data-layout="${layout}"]`).click();
    await expect(page.locator('#view-photos .ph-stage img').first()).toHaveAttribute('src', /homehq-photos/);
  }
  expect(errors).toEqual([]);
});

test('sign-in lives in the retained editor and its session opens the original dashboard', async ({ page }) => {
  const mock = await isolatedHousehold(page, false);
  await page.goto('/');
  const signIn = page.locator('#homehq-gate').getByRole('link', { name: 'Sign in', exact: true });
  await expect(page.locator('#homehq-gate')).toBeVisible();
  await expect(signIn).toHaveAttribute('href', '/editor.html?settings=1');
  await expect(page.locator('#view-home .h-lanes')).toHaveCount(0);
  await signIn.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('input')).toHaveCount(2);
  await expect(dialog.getByLabel('Supabase project URL')).toHaveCount(0);
  await expect(dialog.getByLabel('Publishable API key')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Save connection', exact: true })).toHaveCount(0);
  await dialog.getByLabel('Email', { exact: true }).fill('claudia@example.test');
  await dialog.getByLabel('Password', { exact: true }).fill('synthetic-password');
  await dialog.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Live sync', exact: true })).toBeVisible();
  expect(mock.bodies.find((request) => request.path === '/auth/v1/token')?.body).toMatchObject({ email: 'claudia@example.test', password: 'synthetic-password' });
  await page.getByRole('link', { name: /dashboard/i }).click();
  await expectLiveDashboard(page);
  expect(await page.evaluate(() => localStorage.getItem('homehq.connection.v1'))).toBeNull();
});
