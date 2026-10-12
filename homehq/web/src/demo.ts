import fixture from './demo-fixture.json';
import type { Snapshot, Kind, Editable } from './types';
const KEY = 'homehq.demo.v1';
export function seedDemo(): Snapshot {
  const snapshot = structuredClone(fixture) as Snapshot;
  // The labelled demo clock preserves Wes's recognizable afternoon scenario.
  // Live mode uses server time instead, so this never changes a real calendar.
  const afternoon = new Date(); afternoon.setHours(15, 18, 0, 0);
  const shift = Math.floor(afternoon.getTime() / 1000) - snapshot.server_time;
  snapshot.server_time += shift;
  snapshot.events.forEach((event) => { event.start += shift; event.end += shift; });
  snapshot.photos = snapshot.photos.map((photo, i) => ({ ...photo, url: i % 2 ? '/sample-mountain.svg' : '/sample-coast.svg' }));
  return snapshot;
}
export function loadDemo(): Snapshot {
  try { const data = localStorage.getItem(KEY); if (data) return JSON.parse(data) as Snapshot; } catch { /* Storage denial still permits an in-memory demo. */ }
  return seedDemo();
}
export function persistDemo(snapshot: Snapshot): void { localStorage.setItem(KEY, JSON.stringify(snapshot)); }
export function resetDemo(): Snapshot { const snapshot = seedDemo(); persistDemo(snapshot); return snapshot; }
export function collection(kind: Kind): 'people' | 'events' | 'chores' | 'shopping' | 'photos' {
  return ({ person: 'people', event: 'events', chore: 'chores', shopping: 'shopping', photo: 'photos' } as const)[kind];
}
export function saveDemo(snapshot: Snapshot, kind: Kind, item: Editable): Snapshot {
  const copy = structuredClone(snapshot); const rows = copy[collection(kind)] as Editable[];
  const i = rows.findIndex((row) => row.id === item.id);
  if (i < 0) rows.push(item); else rows[i] = item;
  copy.revision++; return copy;
}
