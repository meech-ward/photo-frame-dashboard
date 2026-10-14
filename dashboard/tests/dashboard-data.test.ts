import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import fixture from '../src/demo-fixture.json';
import type { Snapshot } from '../src/types';
import { householdDate, projectSnapshot, type OriginalSamples } from '../src/dashboard-data';

const snapshot = (): Snapshot => structuredClone(fixture) as Snapshot;
const samples: OriginalSamples = {
  stores: [{ id: 'grocer', name: 'FreshCo' }, { id: 'costco', name: 'Costco' }],
  catOrder: { all: ['Produce', 'Bakery', 'Meat & Fish', 'Dairy & Eggs'], costco: ['Household', 'Produce'] },
  catalog: [['Bananas', 'Produce'], ['Bread', 'Bakery']], usuals: ['Bananas'],
  chores: [{ title: 'Make bed', emoji: '🛏️' }],
  agents: [{ id: 'claude', name: 'Claude', color: '#D97757', rgb: '217 119 87', plan: 'Max 20×', status: 'ok', meters: [{ label: 'Session', used: 62, left: 134, win: 300 }], tokens: 3.1, cost: 21.4, week: [2.2, 3.8, 2.9, 4.4, 1.6, .8, 3.1] }],
};

describe('Original Wes dashboard data boundary', () => {
  it('accepts exact upstream DATA without leaking its mock household collections', () => {
    const context = { window: {} as { DATA: OriginalSamples & { events: unknown[]; devices: unknown[]; photos: { seed: string }[]; stars: Record<string, number> } } };
    runInNewContext(readFileSync(new URL('../js/data.js', import.meta.url), 'utf8'), context);
    const original = context.window.DATA;
    const source = snapshot(); source.home.demo = false;
    const data = projectSnapshot(source, original);
    expect(data.events).toHaveLength(source.events.length);
    expect(data.events.length).toBeLessThan(original.events.length);
    expect(data.devices).toHaveLength(source.devices!.length);
    expect(data.devices.length).toBeLessThan(original.devices.length);
    expect(data.photos.some((p) => original.photos.some((mock) => mock.seed === p.seed))).toBe(false);
    expect(data.agents[0].plan).toBe('Max 20×');
    expect(data.agents[0].meters[0].win).toBe(300);
    expect(data.weather.p).toEqual(original.weather!.p);
    expect(data.stars).not.toEqual(original.stars);
    data.weather.p[0] = 999;
    expect(original.weather!.p[0]).toBe(0);
  });

  it('preserves household IDs and data while adapting the original Date/r/qty keys', () => {
    const source = snapshot();
    const data = projectSnapshot(source, samples);
    expect(data.people.map((p) => p.name)).toEqual(['Wes', 'Claudia', 'Buzzsaw', 'Skidmark']);
    expect(data.ALL).toEqual(source.people.map((p) => p.id));
    expect(data.events).toHaveLength(source.events.length);
    const piano = data.events.find((e) => e.title === 'Piano lesson')!;
    expect(piano.id).toBe('e8');
    expect(piano.start).toBeInstanceOf(Date);
    expect([piano.start.getHours(), piano.start.getMinutes()]).toEqual([15, 45]);
    expect(data.events[0].allDay).toBe(true);
    expect(data.chores[0]).toMatchObject({ id: 'c1', r: 'morning', who: 'maya', emoji: '🛏️', done: true, doneBy: 'maya' });
    expect(data.groceries[0]).toMatchObject({ id: 'g1', name: 'Bananas', qty: 1, store: 'grocer', cat: 'Produce', sourceStore: 'FreshCo' });
    expect(data.devices.map((d) => d.id)).toEqual(source.devices!.map((d) => d.id));
    expect(data.rooms.find((r) => r.id === data.devices[0].room)?.name).toBe('Kitchen');
    expect(source).toEqual(fixture);
  });

  it('changes projection on Realtime refresh without mutating the previous snapshot or sample DATA', () => {
    const source = snapshot();
    const before = projectSnapshot(source, samples);
    const next = structuredClone(source);
    next.revision++;
    next.events = [];
    next.shopping[0].quantity = 9;
    next.chores[0].done = false; next.chores[0].done_by = null;
    const after = projectSnapshot(next, samples);
    expect(after.events).toEqual([]);
    expect(after.groceries[0].qty).toBe(9);
    expect(after.chores[0].doneBy).toBeUndefined();
    expect(after._homehq.revision).toBe(before._homehq.revision + 1);
    after.people[0].name = 'Changed locally';
    after.agents[0].week[0] = 999;
    after.catOrder.all.push('New');
    expect(before.people[0].name).toBe('Wes');
    expect(before.groceries[0].qty).toBe(1);
    expect(samples.agents![0].week[0]).toBe(2.2);
    expect(samples.catOrder!.all).not.toContain('New');
  });

  it('preserves portrait orientation for web photos and legacy landscape fallback', () => {
    const source = snapshot();
    source.photos[0] = { ...source.photos[0], web_width: 1365, web_height: 2048 };
    expect(projectSnapshot(source).photos[0].o).toBe('p');
    expect(projectSnapshot(source).photos[1].o).toBe('l');
  });

  it('keeps empty live household collections empty instead of pulling in mock records', () => {
    const source = snapshot();
    source.home.demo = false;
    source.people = []; source.events = []; source.chores = []; source.shopping = []; source.photos = []; source.devices = [];
    const data = projectSnapshot(source, samples);
    for (const collection of ['people', 'events', 'chores', 'groceries', 'photos', 'devices', 'busyExtras', 'rooms', 'scenes', 'cameras'] as const) expect(data[collection]).toEqual([]);
    expect(data.stars).toEqual({});
    expect(data.week).toEqual({});
  });

  it('uses the household IANA clock across summer/winter and midnight boundaries', () => {
    const source = snapshot();
    const summer = householdDate(source, Date.parse('2026-10-11T19:45:00Z') / 1000);
    const winter = householdDate(source, Date.parse('2026-11-15T20:45:00Z') / 1000);
    expect([summer.getHours(), summer.getMinutes()]).toEqual([15, 45]);
    expect([winter.getHours(), winter.getMinutes()]).toEqual([15, 45]);
    source.home.timezone = 'Asia/Tokyo';
    const nextDay = householdDate(source, Date.parse('2026-10-11T23:30:00Z') / 1000);
    expect([nextDay.getFullYear(), nextDay.getMonth() + 1, nextDay.getDate(), nextDay.getHours()]).toEqual([2026, 10, 12, 8]);
  });

  it('escapes upstream raw HTML sinks once and leaves upstream-escaped edit values raw', () => {
    const source = snapshot();
    source.people[0].name = '<img onerror="bad()">'; source.people[0].status = '<script>bad()</script>'; source.people[0].color = 'red;position:fixed';
    source.events[0].title = 'A & B <script>';
    source.shopping[0].name = 'A & B <script>'; source.shopping[0].category = '<script>'; source.shopping[0].store = '<img>';
    source.devices![0].name = '<img>'; source.devices![0].room = '<script>';
    source.agents[0].name = '<script>'; source.agents[0].meters[0].label = '<img>';
    const data = projectSnapshot(source, samples);
    expect(data.people[0].name).toBe('&lt;img onerror=&quot;bad()&quot;&gt;');
    expect(data.people[0].status).not.toContain('<');
    expect(data.people[0].color).toBe('#343C35');
    expect(data.events[0].title).toBe('A & B <script>');
    expect(data.groceries[0].name).toBe('A & B <script>');
    expect(data.groceries[0].cat).toBe('&lt;script&gt;');
    expect(data.groceries[0].sourceCategory).toBe('<script>');
    expect(data.stores.find((s) => s.sourceName === '<img>')?.name).toBe('&lt;img&gt;');
    expect(data.devices[0].name).toBe('&lt;img&gt;');
    expect(data.agents[0].meters[0].label).toBe('&lt;img&gt;');
  });

  it('supports custom stores/categories without discarding their rows or unstable keys', () => {
    const source = snapshot();
    source.shopping = [{ ...source.shopping[0], store: 'Neighbourhood shop', category: 'Pet care' }];
    const first = projectSnapshot(source, samples);
    const selected = first.groceries[0].store;
    source.shopping.unshift({ ...source.shopping[0], id: 'new-item', store: 'Another shop' });
    const next = projectSnapshot(source, samples);
    expect(next.groceries.find((g) => g.id === 'g1')!.store).toBe(selected);
    expect(next.catOrder[selected]).toContain('Pet care');
    expect(next.stores.find((s) => s.id === selected)?.sourceName).toBe('Neighbourhood shop');
  });

  it('uses signed bucket photos and never invents capture dates or upstream image seeds', () => {
    const source = snapshot();
    source.photos = [{ id: 'portrait', caption: 'Our holiday', place: 'Home', asset: null, path: 'household/image.png', url: 'https://example.supabase.co/storage/v1/object/sign/homehq-photos/household/image.png?token=x&download=1' }];
    const data = projectSnapshot(source, samples);
    expect(data.photos[0]).toMatchObject({ id: 'portrait', seed: 'homehq-photo-portrait', caption: 'Our holiday', date: '', from: 'family', sample: false });
    expect(data.photos[0].src).toContain('/homehq-photos/');
    expect(data.photos[0].src).toContain('&amp;download=1');
    source.photos[0].url = 'javascript:alert(1)'; source.photos[0].caption = '2026-02-30';
    expect(projectSnapshot(source, samples).photos[0]).toMatchObject({ src: '', date: '' });
    source.photos[0].url = 'https://';
    expect(projectSnapshot(source, samples).photos[0].src).toBe('');
    source.photos[0].caption = '2026-10-12';
    expect(projectSnapshot(source, samples).photos[0].date).toBe('2026-10-12');
  });

  it('uses provider extras only for labelled samples and does not invent history or connected home services', () => {
    const source = snapshot();
    const data = projectSnapshot(source, samples);
    expect(data.agents[0]).toMatchObject({ sample: true, plan: 'Max 20×', tokens: 3.1, cost: 21.4 });
    expect(data.agents[0].meters[0]).toMatchObject({ used: 62, left: 134, win: 300 });
    expect(data.stars.maya).toBe(4);
    expect(data.stars.otto).toBe(3);
    expect(data.week).toEqual({});
    expect(data._homehq.unavailable).toEqual(expect.arrayContaining(['chore-history', 'reward-bank', 'thermostat', 'media', 'cameras', 'scenes']));
    source.agents[0].sample = false;
    const real = projectSnapshot(source, samples);
    expect(real.agents[0]).toMatchObject({ plan: 'Usage only', status: 'unknown', tokens: 0, cost: 0 });
    expect(real._homehq.unavailable).toContain('agent-window-length');
  });

  it('generates noncolliding upstream add IDs and rejects identifiers that would break HTML attributes', () => {
    const data = projectSnapshot(snapshot(), samples);
    const grocery = data._gid(); const event = data._eid();
    expect(data.groceries.some((g) => g.id === grocery)).toBe(false);
    expect(data.events.some((e) => e.id === event)).toBe(false);
    expect(data._gid()).not.toBe(grocery);
    const source = snapshot(); source.events[0].id = 'bad" onclick="bad';
    expect(() => projectSnapshot(source, samples)).toThrow('identifier');
  });
});
