import type { Snapshot } from './types';
import { escape, safeColor } from './utils';

export interface DashboardPerson { id: string; name: string; color: string; rgb: string; ink: string; home?: boolean; status?: string; eta?: number }
export interface DashboardEvent { id: string; title: string; start: Date; end: Date; people: string[]; allDay: boolean; loc: string; notes: string; travel: number }
export interface DashboardChore { id: string; title: string; r: string; who: string; emoji: string; stars: number; done: boolean; doneBy?: string }
export interface DashboardGrocery { id: string; name: string; cat: string; qty: number; store: string; done: boolean; note: string; sourceCategory: string; sourceStore: string }
export interface DashboardRoutine { id: string; name: string; range: string; from: number; to: number }
export interface DashboardRoom { id: string; name: string }
export interface DashboardDevice { id: string; room: string; type: 'light' | 'lock' | 'garage'; name: string; on?: boolean; level?: number; locked?: boolean; state?: string; sample: boolean }
export interface DashboardPhoto { id: string; seed: string; src: string; o: 'l'; date: string; place: string; caption: string; from: 'family'; tag: string; sample: boolean }
export interface DashboardWeather { hi: number; lo: number; feels: number; humidity: number; wind: number; t: number[]; c: string[]; p: number[] }
export interface DashboardMeter { label: string; used: number; left: number; win: number; detail?: string }
export interface DashboardAgent { id: string; name: string; color: string; rgb: string; plan: string; status: string; incident?: string; meters: DashboardMeter[]; tokens: number; cost: number; week: number[]; sample?: boolean }
export interface DashboardClimate { current: number; set: number; mode: string; humidity: number; outside: number }
export interface DashboardMedia { room: string; title: string; artist: string; playing: boolean; volume: number; seed: string }
export interface DashboardCamera { id: string; name: string; seed: string }
export interface DashboardScene { id: string; name: string; icon: string; set: Record<string, number> }

/** Original DATA supplies presentation defaults and explicitly labelled provider samples. */
export interface OriginalSamples {
  routines?: DashboardRoutine[];
  catalog?: [string, string][];
  usuals?: string[];
  stores?: { id: string; name: string }[];
  catOrder?: Record<string, string[]>;
  chores?: { title: string; emoji: string }[];
  weather?: DashboardWeather;
  agents?: DashboardAgent[];
}

export interface DashboardData {
  people: DashboardPerson[]; family: DashboardPerson; ALL: string[];
  events: DashboardEvent[]; busyExtras: DashboardEvent[];
  routines: DashboardRoutine[]; chores: DashboardChore[]; stars: Record<string, number>; week: Record<string, (number | null)[]>;
  stores: { id: string; name: string; sourceName: string }[]; catOrder: Record<string, string[]>;
  groceries: DashboardGrocery[]; catalog: [string, string][]; usuals: string[];
  rooms: DashboardRoom[]; devices: DashboardDevice[]; climate: DashboardClimate; media: DashboardMedia; cameras: DashboardCamera[]; scenes: DashboardScene[];
  weather: DashboardWeather; photos: DashboardPhoto[]; agents: DashboardAgent[];
  _gid: () => string; _eid: () => string;
  _homehq: {
    revision: number; sourceNow: number; timezone: string;
    weather: { label: string; summary: string; sample: boolean };
    samples: { weather: boolean; home: boolean; agents: boolean; photos: boolean };
    unavailable: string[];
  };
}

const routines: DashboardRoutine[] = [
  { id: 'morning', name: 'Morning', range: '6 – 11 AM', from: 0, to: 11 },
  { id: 'after', name: 'After school', range: '11 AM – 5 PM', from: 11, to: 17 },
  { id: 'evening', name: 'Evening', range: '5 – 10 PM', from: 17, to: 24 },
];

function id(value: string): string {
  // Wes interpolates IDs into HTML attributes and selectors. This is the same
  // restricted alphabet as the existing database, so no row is silently renamed.
  if (!/^[a-z0-9_-]{1,64}$/.test(value)) throw new Error('Invalid Home HQ row identifier.');
  return value;
}

function palette(value: string): { color: string; rgb: string; ink: string } {
  const color = safeColor(value);
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(color.slice(start, start + 2), 16));
  return { color, rgb: `${r} ${g} ${b}`, ink: r * .299 + g * .587 + b * .114 > 150 ? '#111111' : '#FFFFFF' };
}

/** A Date whose local getters show the household clock, as Wes's helpers expect. */
export function householdDate(snapshot: Pick<Snapshot, 'home'>, seconds: number): Date {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: snapshot.home.timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(seconds * 1000));
  const part = (name: string) => Number(parts.find((p) => p.type === name)!.value);
  // Each endpoint gets its own IANA offset: today's offset is wrong for events
  // on the other side of a daylight saving change. App.now uses this same helper.
  return new Date(part('year'), part('month') - 1, part('day'), part('hour'), part('minute'), part('second'));
}

function token(prefix: string, value: string): string {
  // Labels can contain punctuation; deterministic ASCII keys keep Wes's selected
  // store/room stable when a Realtime refresh inserts another label before it.
  return `${prefix}-${Array.from(value).map((c) => c.codePointAt(0)!.toString(16)).join('_') || 'none'}`;
}

function photoUrl(value: string | undefined): string {
  if (!value) return '';
  let url: URL;
  try { url = new URL(value, 'http://127.0.0.1'); } catch { return ''; }
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) return '';
  // App.img returns this directly inside a quoted src attribute; keep signed URL
  // ampersands intact in the DOM while preventing an attribute breakout.
  return escape(value);
}

function dateCaption(caption: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(caption)) return '';
  const date = new Date(`${caption}T00:00:00Z`);
  return Number.isFinite(+date) && date.toISOString().slice(0, 10) === caption ? caption : '';
}

/** Project the existing household contract into the original dashboard's DATA. */
export function projectSnapshot(snapshot: Snapshot, originalSamples: OriginalSamples = {}, now = snapshot.server_time): DashboardData {
  // Only fields that upstream inserts without App.esc are escaped here. Titles,
  // notes and grocery names remain raw: upstream already escapes them, and its
  // edit forms must not persist HTML entities back into Supabase.
  const people = snapshot.people.map((p) => ({ id: id(p.id), name: escape(p.name), ...palette(p.color), home: p.home, status: escape(p.status), ...(p.eta == null ? {} : { eta: p.eta }) }));
  const knownStores = originalSamples.stores || [];
  const storeNames = [...new Set(snapshot.shopping.map((g) => g.store))];
  const stores = storeNames.map((name) => ({ id: knownStores.find((s) => s.name === name)?.id || token('store', name), name: escape(name || 'Any store'), sourceName: name }));
  const storeId = (name: string) => stores.find((s) => s.sourceName === name)!.id;
  const groceries = snapshot.shopping.map((g) => ({ id: id(g.id), name: g.name, cat: escape(g.category || 'Other'), qty: g.quantity, store: storeId(g.store), done: g.done, note: g.note, sourceCategory: g.category, sourceStore: g.store }));
  const defaultCategories = originalSamples.catOrder?.all || ['Produce', 'Bakery', 'Meat & Fish', 'Dairy & Eggs', 'Pantry', 'Frozen', 'Snacks', 'Household'];
  const categories = [...new Set([...defaultCategories.map(escape), ...groceries.map((g) => g.cat)])].filter((cat) => cat !== 'Other');
  const catOrder: Record<string, string[]> = { all: categories };
  stores.forEach((s) => { catOrder[s.id] = [...new Set([...(originalSamples.catOrder?.[s.id] || []).map(escape), ...categories])]; });
  const roomNames = [...new Set((snapshot.devices || []).map((d) => d.room))];
  const rooms = roomNames.map((name) => ({ id: token('room', name), name: escape(name) }));
  const chores = snapshot.chores.map((c) => ({ id: id(c.id), title: c.title, r: c.routine, who: id(c.who), emoji: originalSamples.chores?.find((sample) => sample.title === c.title)?.emoji || '✓', stars: c.stars, done: c.done, ...(c.done_by ? { doneBy: id(c.done_by) } : {}) }));
  // The contract contains today's checklist, not a saved reward bank or daily
  // history. Derive today's earned stars and omit the unsupported streak grid.
  const stars: Record<string, number> = {};
  people.forEach((p) => {
    if (chores.some((c) => c.who === p.id && c.stars > 0)) stars[p.id] = chores.filter((c) => c.done && c.doneBy === p.id).reduce((sum, c) => sum + c.stars, 0);
  });
  const weatherSample = snapshot.weather.sample && originalSamples.weather;
  const cond = /rain/i.test(snapshot.weather.label) ? 'rain' : /clear|sun/i.test(snapshot.weather.label) ? 'sun' : /partly/i.test(snapshot.weather.label) ? 'partly' : 'cloud';
  const weather: DashboardWeather = {
    hi: snapshot.weather.high, lo: snapshot.weather.low,
    feels: weatherSample ? weatherSample.feels : 0, humidity: weatherSample ? weatherSample.humidity : 0, wind: weatherSample ? weatherSample.wind : 0,
    t: weatherSample ? [...weatherSample.t] : Array(24).fill(snapshot.weather.temp),
    c: weatherSample ? [...weatherSample.c] : Array(24).fill(cond),
    p: weatherSample ? [...weatherSample.p] : Array(24).fill(0),
  };
  weather.t[householdDate(snapshot, now).getHours()] = snapshot.weather.temp;
  const agents = snapshot.agents.map((a) => {
    const sample = a.sample ? originalSamples.agents?.find((x) => x.id === a.id) : undefined;
    return { id: id(a.id), name: escape(a.name), ...palette(a.color), sample: a.sample,
      plan: sample ? escape(sample.plan) : 'Usage only', status: sample?.status || 'unknown',
      ...(sample?.incident ? { incident: escape(sample.incident) } : {}),
      meters: a.meters.map((m, index) => ({ label: escape(m.label), used: m.used, left: m.reset_minutes,
        win: sample?.meters[index]?.win || Math.max(1, m.reset_minutes),
        ...(sample?.meters[index]?.detail ? { detail: escape(sample.meters[index].detail!) } : {}) })),
      tokens: sample?.tokens || 0, cost: sample?.cost || 0, week: [...a.week] };
  });
  let nextGrocery = 0, nextEvent = 0;
  const unique = (prefix: string, ids: string[], sequence: () => number) => {
    let candidate: string;
    do { candidate = `${prefix}${sequence()}`; } while (ids.includes(candidate));
    return candidate;
  };
  const data: DashboardData = {
    people, family: { id: 'family', name: 'Family', ...palette('#111111') }, ALL: people.map((p) => p.id),
    events: snapshot.events.map((e) => ({ id: id(e.id), title: e.title, start: householdDate(snapshot, e.start), end: householdDate(snapshot, e.end), people: e.people.map(id), allDay: e.all_day, loc: e.loc, notes: e.notes, travel: e.travel })), busyExtras: [],
    routines: (originalSamples.routines || routines).map((r) => ({ ...r })), chores, stars, week: {}, stores, catOrder, groceries,
    catalog: (originalSamples.catalog || []).map(([name, cat]) => [name, escape(cat)]), usuals: [...(originalSamples.usuals || [])], rooms,
    devices: (snapshot.devices || []).map((d) => ({ ...d, id: id(d.id), name: escape(d.name), room: token('room', d.room) })),
    climate: { current: snapshot.home_status.temperature, set: snapshot.home_status.temperature, mode: 'off', humidity: 0, outside: snapshot.weather.temp },
    media: { room: '', title: 'Not connected', artist: '', playing: false, volume: 0, seed: '' }, cameras: [], scenes: [], weather,
    photos: snapshot.photos.map((p) => ({ id: id(p.id), seed: `homehq-photo-${p.id}`, src: photoUrl(p.url), o: 'l', date: dateCaption(p.caption), place: p.place, caption: p.caption, from: 'family', tag: p.id, sample: !p.path })), agents,
    _gid: () => unique('g', data.groceries.map((g) => g.id), () => ++nextGrocery),
    _eid: () => unique('e', data.events.map((e) => e.id), () => ++nextEvent),
    _homehq: {
      revision: snapshot.revision, sourceNow: now, timezone: snapshot.home.timezone,
      weather: { label: escape(snapshot.weather.label), summary: escape(snapshot.weather.summary), sample: snapshot.weather.sample },
      samples: { weather: snapshot.weather.sample, home: snapshot.home_status.sample, agents: snapshot.agents.some((a) => a.sample), photos: snapshot.photos.some((p) => !p.path) },
      unavailable: ['chore-history', 'reward-bank', 'photo-taken-date', 'photo-uploader', 'thermostat', 'humidity', 'media', 'cameras', 'scenes', ...(snapshot.weather.sample ? [] : ['hourly-forecast']), ...(snapshot.agents.some((a) => !a.sample) ? ['agent-plan', 'agent-provider-status', 'agent-token-count', 'agent-cost', 'agent-window-length'] : [])],
    },
  };
  return data;
}
