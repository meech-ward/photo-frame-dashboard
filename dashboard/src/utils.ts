import type { Chore, Event } from './types';
export function escape(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!); }
export function safeColor(value: string): string { return /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#343C35'; }
export function asDate(value: string | number | Date): Date { return new Date(typeof value === 'number' ? value * 1000 : value); }
export function clock(value: string | number | Date, options: Intl.DateTimeFormatOptions = {}): string { return asDate(value).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', ...options }); }
export function greeting(value: string | number | Date, timeZone: string): 'morning' | 'afternoon' | 'evening' {
  // The owner's home and this browser can be on different calendar days. Use
  // the same IANA zone as the clock; h23 keeps midnight at 0 rather than 24.
  const hour = Number(new Intl.DateTimeFormat('en', { timeZone, hour: 'numeric', hourCycle: 'h23' }).formatToParts(asDate(value)).find((part) => part.type === 'hour')!.value);
  return hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
}
export function dayKey(value: string | number | Date, timeZone?: string): string { return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(asDate(value)); }
export function localDateTime(value: number, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(asDate(value));
  const get = (type: string) => parts.find((part) => part.type === type)!.value;
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}
export function wallTimeEpoch(value: string, timeZone: string): number {
  const [date, time] = value.split('T'); const [y, m, d] = date.split('-').map(Number); const [h, min] = time.split(':').map(Number);
  const wallUTC = Date.UTC(y, m - 1, d, h, min); let instant = wallUTC;
  // An IANA zone can change its offset within a calendar week. Derive its
  // offset at the event date rather than reusing today's server offset.
  for (let i = 0; i < 3; i++) {
    const rendered = localDateTime(instant / 1000, timeZone);
    const [rd, rt] = rendered.split('T'); const [ry, rm, rday] = rd.split('-').map(Number); const [rh, rmin] = rt.split(':').map(Number);
    const delta = wallUTC - Date.UTC(ry, rm - 1, rday, rh, rmin);
    if (!delta) return instant / 1000;
    instant += delta;
  }
  if (localDateTime(instant / 1000, timeZone) !== value) throw new Error('That local time does not exist because the clocks change. Choose another time.');
  return instant / 1000;
}
export function progress(rows: Chore[]): { done: number; total: number; percent: number } { const done = rows.filter((c) => c.done).length; return { done, total: rows.length, percent: rows.length ? Math.round(done / rows.length * 100) : 0 }; }
export function upcoming(events: Event[], now = new Date()): Event[] { return events.filter((event) => event.end * 1000 > now.getTime()).sort((a, b) => a.start - b.start); }
