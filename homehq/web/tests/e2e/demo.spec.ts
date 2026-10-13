import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => { await page.goto('/editor.html'); });

test('Today preserves the original family, afternoon hero and all seven sections', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Next up · Skidmark' })).toContainText('Piano lesson');
  await expect(page.getByText('Good afternoon, home.')).toBeVisible();
  for (const name of ['Wes', 'Claudia', 'Buzzsaw', 'Skidmark']) await expect(page.locator('.family-lanes').getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Sections' }).getByRole('button')).toHaveCount(7);
  await page.screenshot({ path: 'test-results/homehq-desktop.png', fullPage: true });
});

test('event editing preserves attendees and validates a backwards time range', async ({ page }) => {
  await page.getByRole('button', { name: 'Next up · Skidmark' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Event title').fill('Piano + theory');
  await dialog.getByRole('button', { name: 'Save event' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('.hero')).toContainText('Piano + theory');
  await page.reload();
  await expect(page.locator('.hero')).toContainText('Piano + theory');
  await page.locator('.hero').click();
  const start = await dialog.getByLabel('Starts').inputValue();
  await dialog.getByLabel('Ends').fill(start.slice(0, 10) + 'T01:00');
  await dialog.getByRole('button', { name: 'Save event' }).click();
  await expect(dialog.getByRole('alert')).toContainText('end must be');
});

test('chore completion and Undo set the desired state; team chores award a named person', async ({ page }) => {
  await page.getByRole('button', { name: 'Chores', exact: true }).click();
  const homework = page.getByRole('checkbox', { name: 'Homework', exact: true });
  await expect(homework).toHaveAttribute('aria-checked', 'false');
  await homework.click();
  await expect(homework).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(homework).toHaveAttribute('aria-checked', 'false');
  await page.getByRole('checkbox', { name: 'Water the plants', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Who gets the little win?');
  await page.getByRole('dialog').getByRole('button', { name: 'Claudia', exact: false }).click();
  await expect(page.getByRole('checkbox', { name: 'Water the plants', exact: true })).toContainText('Done by Claudia');
});

test('shopping supports adding, completing and undoing an item', async ({ page }) => {
  await page.getByRole('button', { name: 'Shopping', exact: true }).click();
  await page.getByRole('button', { name: 'Add item', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Item', { exact: true }).fill('Strawberries');
  await page.getByRole('dialog').getByRole('button', { name: 'Save item' }).click();
  const item = page.getByRole('checkbox', { name: 'Strawberries' });
  await item.click(); await expect(item).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(item).toHaveAttribute('aria-checked', 'false');
});

test('family editing and calendar paging preserve a readable week', async ({ page }) => {
  await page.getByRole('button', { name: 'Edit the family', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Buzzsaw', exact: false }).click();
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Maya');
  await page.getByRole('dialog').getByRole('button', { name: 'Save person' }).click();
  await expect(page.locator('.family-lanes').getByText('Maya', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Calendar', exact: true }).click();
  await page.getByRole('button', { name: 'Next days', exact: true }).click();
  await expect(page.locator('.day-column')).toHaveCount(3);
  await page.getByRole('button', { name: 'Next days', exact: true }).click();
  await expect(page.locator('.day-column')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Next days', exact: true })).toBeDisabled();
});

test('sample lock changes require a deliberate confirmation', async ({ page }) => {
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await page.getByRole('button', { name: 'Front door, Locked' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('button', { name: 'Front door, Locked' })).toBeVisible();
  await page.getByRole('button', { name: 'Front door, Locked' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Unlock sample lock' }).click();
  await expect(page.getByRole('button', { name: 'Front door, Unlocked' })).toBeVisible();
});

test('uploaded demo photos become actual 320x240 PNGs', async ({ page }) => {
  const source = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const context = canvas.getContext('2d')!; context.fillStyle = '#315342'; context.fillRect(0, 0, 640, 480);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.getByRole('button', { name: 'Photos', exact: true }).click();
  await page.getByRole('button', { name: 'Add photo', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Photo', { exact: true }).setInputFiles({
    name: 'test.png', mimeType: 'image/png',
    buffer: Buffer.from(source, 'base64'),
  });
  await page.getByRole('dialog').getByLabel('Place').fill('The kitchen');
  await page.getByRole('dialog').getByRole('button', { name: 'Add photo', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  const image = page.getByRole('img', { name: 'The kitchen', exact: true });
  await expect(image).toHaveAttribute('src', /^data:image\/png;base64,/);
  await expect.poll(async () => image.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([320, 240]);
});

test('mobile screens remain readable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of ['Today', 'Calendar', 'Chores', 'Shopping', 'Photos', 'Home', 'Agents']) {
    await page.getByRole('navigation', { name: 'Sections' }).getByRole('button', { name, exact: true }).click();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.screenshot({ path: 'test-results/homehq-mobile.png', fullPage: true });
});

test('a poorly compressible 320x240 photo is accepted within the badge output cap', async ({ page }) => {
  const source = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
    const context = canvas.getContext('2d')!;
    const pixels = context.createImageData(320, 240);
    // Deterministic high-entropy RGB exercises the real PNG size boundary.
    // Every alpha is opaque, matching the converter's filled badge canvas.
    let state = 123456789;
    for (let i = 0; i < pixels.data.length; i += 4) {
      for (let channel = 0; channel < 3; channel++) { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; pixels.data[i + channel] = state & 255; }
      pixels.data[i + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.getByRole('button', { name: 'Photos', exact: true }).click();
  await page.getByRole('button', { name: 'Add photo', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Photo', { exact: true }).setInputFiles({ name: 'noise.png', mimeType: 'image/png', buffer: Buffer.from(source, 'base64') });
  await page.getByRole('dialog').getByLabel('Place').fill('Noise boundary test');
  await page.getByRole('dialog').getByRole('button', { name: 'Add photo', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  const image = page.getByRole('img', { name: 'Noise boundary test', exact: true });
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([320, 240]);
  const data = Buffer.from((await image.getAttribute('src'))!.split(',')[1], 'base64');
  expect(data.length).toBeGreaterThan(262_144);
  expect(data.length).toBeLessThanOrEqual(327_680);
  expect(data.readUInt32BE(16)).toBe(320);
  expect(data.readUInt32BE(20)).toBe(240);
  expect(data[24]).toBe(8); // PNG bit depth.
  expect([2, 3, 6]).toContain(data[25]); // Badge-supported colour types.
  expect(data[28]).toBe(0); // Interlaced PNGs are not supported by the badge.
  let idatChunks = 0;
  for (let offset = 8; offset < data.length;) {
    if (data.toString('ascii', offset + 4, offset + 8) === 'IDAT') idatChunks++;
    offset += data.readUInt32BE(offset) + 12;
  }
  // The native decoder cannot cross the IDAT boundaries that browsers emit
  // for a large image; a browser displaying it is not a badge decode check.
  expect(idatChunks).toBe(1);
});
