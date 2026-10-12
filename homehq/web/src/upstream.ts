// The original scripts keep their global DATA reference. Import them before the
// adapter, and install overrides before their DOMContentLoaded startup runs.
import '../upstream/js/main.js';
import './upstream.css';
import { HomeHQBackend, loadConfig, type LiveStatus } from './backend';
import { householdDate, projectSnapshot, type OriginalSamples } from './upstream-data';
import type { Snapshot, Chore, Shopping, Device } from './types';

// This seam deliberately describes the upstream's dynamic globals rather than
// translating its renderer into another implementation.
declare global { interface Window { App: any; DATA: any } }
const app = window.App;
const data = window.DATA;
const samples: OriginalSamples = JSON.parse(JSON.stringify(data));
const config = loadConfig();
const gate = document.querySelector<HTMLDivElement>('#homehq-gate')!;
const gateMessage = document.querySelector<HTMLParagraphElement>('#homehq-gate-message')!;
const statusLabel = document.querySelector<HTMLSpanElement>('#homehq-status')!;
let snapshot: Snapshot | null = null;
let backend: HomeHQBackend | null = null;
let status: LiveStatus = 'connecting';
let started = false;
let saving = false;
let photoGeneration = '';
const deviceIds = new Map<string, string>();
const originalImg = app.img;
const originalPhotoMeta = app.photoMeta;
const originalPick = app.Slideshow.prototype.pick;
const originalSlideStart = app.Slideshow.prototype.start;
const originalStart = app.start;
app.start = () => {
  // A configured dashboard has no local household to show before Auth resolves.
  if (started || (config && !snapshot)) return;
  originalStart();
};

function renderStatus(error = ''): void {
  gate.hidden = !config || !!snapshot;
  document.querySelector<HTMLElement>('#stage')!.style.visibility = gate.hidden ? '' : 'hidden';
  const name = snapshot?.people.find((p) => p.id === snapshot?.viewer?.person_id)?.name;
  statusLabel.textContent = !config ? 'Original prototype · local only' : status === 'signed-out' ? 'Sign in' : status === 'live' ? `Live sync${name ? ` · ${name}` : ''}` : snapshot ? 'Reconnecting' : 'Connecting';
  gateMessage.textContent = error || (status === 'signed-out' ? 'Sign in with your family account to load your household.' : 'Connecting to your household.');
  statusLabel.title = error;
}

function applySnapshot(next: Snapshot): void {
  snapshot = next;
  const projected = projectSnapshot(next, samples, Date.now() / 1000);
  deviceIds.clear();
  // The original security summary asks for g-door by ID. Alias only its first
  // garage/lock in the display; every write still uses the database's real ID.
  let garage = false, lock = false;
  for (const device of projected.devices) {
    const sourceId = device.id;
    if (device.type === 'garage' && !garage) { device.id = 'g-door'; garage = true; }
    if (device.type === 'lock' && !lock) { device.id = 'e-door'; lock = true; }
    deviceIds.set(device.id, sourceId);
  }
  // An absent garage is an unavailable reading, never an invented open door.
  // The original summary requires this shape even in homes without a garage.
  if (!garage) projected.devices.push({ id: 'g-door', room: '', type: 'garage', name: 'Garage not configured', state: 'closed', sample: true });
  Object.assign(data, projected);
  data._gid = () => `g-${crypto.randomUUID()}`;
  data._eid = () => `e-${crypto.randomUUID()}`;
  const photos = JSON.stringify(projected.photos.map((p) => [p.id, p.src]));
  if (photos !== photoGeneration) { photoGeneration = photos; }
  if (!started && document.readyState !== 'loading') app.start();
  if (started) {
    app.emit('data');
    // Wes caches every screen. Mark the visible one too, so a Realtime hint
    // replaces a displayed checklist instead of waiting for tab navigation.
    app.go(app.current || 'home', { rerender: true });
  }
  renderStatus();
}

app.img = (seed: string, width: number, height: number): string => {
  const photo = data.photos.find((p: any) => p.seed === seed);
  return photo?.src || (config ? '/sample-coast.svg' : originalImg(seed, width, height));
};
app.photoMeta = (photo: any): any => {
  if (!config || (photo.date && !photo.sample)) return originalPhotoMeta(photo);
  const caption = app.esc(photo.caption || 'Family photo');
  return { date: caption, monthYear: caption, kicker: photo.sample ? 'Sample artwork' : 'Your private photo', onThisDay: false, place: photo.place, from: data.family };
};
app.Slideshow.prototype.pick = function (): any {
  // A newly provisioned household may have one image. The original wall demo
  // assumes siblings for Pair/Collage; fall back to Cover without changing it.
  if (config && this._homehqGeneration !== photoGeneration) {
    this.queue = []; this.history = []; this._homehqGeneration = photoGeneration;
  }
  if (config && ((!['cover', 'polaroid'].includes(this.o.layout) && data.photos.length < 3) || (this.o.layout === 'pair' && !data.photos.some((p: any) => p.o === 'p')))) {
    const layout = this.o.layout; this.o.layout = 'cover';
    try { return originalPick.call(this); } finally { this.o.layout = layout; }
  }
  return originalPick.call(this);
};
app.Slideshow.prototype.start = function (): void {
  // The original Photos view keeps its slideshow between tab visits. Reset its
  // queued descriptors when private URLs or uploaded images actually change.
  if (config && this._homehqGeneration !== photoGeneration) { this.current = null; this.queue = []; this.history = []; }
  originalSlideStart.call(this);
};

function requireWritable(): HomeHQBackend {
  if (!backend || !snapshot || status !== 'live') throw new Error('Wait for your Supabase connection before saving.');
  if (saving) throw new Error('Finishing the previous change.');
  return backend;
}
async function save(work: (client: HomeHQBackend) => Promise<unknown>): Promise<void> {
  let acquired = false;
  try {
    const client = requireWritable(); saving = true; acquired = true;
    await work(client);
  } catch (error) {
    app.toast(app.esc(error instanceof Error ? error.message : String(error)), { tone: 'error' });
  } finally { if (acquired) saving = false; }
}
async function setDone(kind: 'chore' | 'shopping', id: string, value?: boolean): Promise<void> {
  await save(async (client) => {
    const row = (kind === 'chore' ? snapshot!.chores : snapshot!.shopping).find((item) => item.id === id)!;
    if (!row) throw new Error('This item has changed. Refresh the dashboard.');
    const previous = row.done, done = value ?? !previous;
    // Assigned stars stay with the assigned person; SQL separately records the
    // signed-in Auth actor. An Anyone chore credits the current family member.
    const by = kind === 'chore' && done ? (row as Chore).who === 'any' ? snapshot!.viewer?.person_id || null : (row as Chore).who : null;
    if (kind === 'chore' && done && !by) { edit('chores'); return; }
    const result = await client.setDone(kind, row, done, by);
    if (result === 'conflict') { app.toast('This item changed on another screen. The latest version is shown.'); return; }
    app.toast(`${app.esc(kind === 'chore' ? (row as Chore).title : (row as Shopping).name)} ${done ? 'done' : 'added back'}`, { icon: 'check', undo: () => { void setDone(kind, id, previous); } });
  });
}
async function addShopping(name: string): Promise<void> {
  await save(async (client) => {
    name = name.trim(); if (!name) return;
    const existing = snapshot!.shopping.find((g) => g.name.toLowerCase() === name.toLowerCase());
    if (existing) {
      if (existing.done) await client.setDone('shopping', existing, false, null);
      else await client.save('shopping', { ...existing, quantity: existing.quantity + 1 });
    } else {
      const sample = samples.catalog?.find(([title]) => title.toLowerCase() === name.toLowerCase());
      const selected = document.querySelector<HTMLElement>('.s-stores .is-on')?.dataset.store;
      const store = data.stores.find((s: any) => s.id === selected)?.sourceName || snapshot!.shopping[0]?.store || 'Grocer';
      await client.save('shopping', { id: `g-${crypto.randomUUID()}`, name, category: sample?.[1] || 'Other', store, quantity: 1, note: '', done: false, version: 0 });
    }
    app.toast('Saved to your household.', { icon: 'cart' });
  });
}
function edit(section: string, create = ''): void {
  window.location.assign(`/editor.html?section=${encodeURIComponent(section)}${create ? `&new=${encodeURIComponent(create)}` : ''}`);
}

if (config) {
  document.body.dataset.homehqLive = 'true';
  // No copied mock household is visible before authentication resolves.
  for (const key of ['people', 'events', 'chores', 'groceries', 'photos']) data[key] = [];
  app.now = () => snapshot ? householdDate(snapshot, Date.now() / 1000) : new Date();
  app.openDemo = () => edit('today');
  const originalToast = app.toast;
  app.toast = (html: string, options?: any) => { if (!html.includes('demo controls')) originalToast(html, options); };
  app.setDevice = (alias: string, patch: Record<string, unknown>) => {
    void save(async (client) => {
      const device = snapshot!.devices?.find((d) => d.id === deviceIds.get(alias));
      if (!device) throw new Error('This device is not configured.');
      const result = await client.setDevice(device, patch);
      if (result === 'conflict') app.toast('This device changed elsewhere. The latest state is shown.');
    });
  };
  app.openGarageSheet = () => {
    const device = snapshot?.devices?.find((d) => d.type === 'garage');
    if (!device) return;
    const opening = device.state === 'closed';
    app.sheet(`<div class="sheet-pad"><h2 class="serif">${opening ? 'Open' : 'Close'} the sample garage?</h2><p>This changes the demo state shared with your badge.</p><button class="btn btn--solid" data-homehq-garage>Confirm</button></div>`, { onMount: (box: HTMLElement, close: () => void) => {
      box.querySelector('[data-homehq-garage]')!.addEventListener('click', () => { close(); void save(async (client) => client.setDevice(device, { state: opening ? 'open' : 'closed' })); });
    } });
  };
  // Capture the original action before its closure mutates DATA. Persist desired
  // values with the existing version contract; failed writes never become local edits.
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const action = target?.closest<HTMLElement>('[data-ch], [data-check], [data-revive], [data-qty], [data-add], [data-clear], [data-alloff], [data-lockall]');
    if (!action) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (action.closest('#view-calendar')) { edit('calendar', 'event'); return; }
    if (action.dataset.ch) { void setDone('chore', action.dataset.ch); return; }
    if (action.dataset.check || action.dataset.revive) { void setDone('shopping', action.dataset.check || action.dataset.revive!, action.dataset.revive ? false : undefined); return; }
    if (action.dataset.qty) {
      void save(async (client) => { const row = snapshot!.shopping.find((g) => g.id === action.dataset.id)!; await client.save('shopping', { ...row, quantity: Math.max(1, row.quantity + Number(action.dataset.qty)) }); }); return;
    }
    if (action.hasAttribute('data-add')) { void addShopping(action.dataset.add || ''); return; }
    if (action.hasAttribute('data-clear')) { edit('shopping'); return; }
    void save(async (client) => {
      const devices = snapshot!.devices || [];
      for (const device of devices.filter((d) => action.hasAttribute('data-alloff') ? d.type === 'light' && d.on : d.type === 'lock')) {
        await client.setDevice(device, device.type === 'light' ? { on: false } : { locked: true });
      }
    });
  }, true);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || !(event.target instanceof HTMLInputElement) || !event.target.matches('.s-input')) return;
    event.preventDefault(); event.stopImmediatePropagation(); void addShopping(event.target.value);
  }, true);
  backend = new HomeHQBackend(config, applySnapshot, (nextStatus, error) => {
    status = nextStatus;
    if (status === 'signed-out') { snapshot = null; for (const key of ['people', 'events', 'chores', 'groceries', 'photos']) data[key] = []; }
    renderStatus(error);
  });
  void backend.start().catch((error) => { status = backend?.session ? 'reconnecting' : 'signed-out'; renderStatus(String(error.message || error)); });
  window.addEventListener('focus', () => { void backend?.refresh(); });
  window.addEventListener('pagehide', () => { void backend?.stop(); });
}
app.on('ready', () => { started = true; if (config) app.setTime(null); renderStatus(); });
renderStatus();
