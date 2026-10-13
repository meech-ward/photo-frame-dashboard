import { afterEach, describe, expect, it, vi } from 'vitest';
import { escape, progress, upcoming, safeColor, localDateTime, wallTimeEpoch, greeting } from '../src/utils';
import { loadConfig, validateConfig } from '../src/backend';
import { seedDemo } from '../src/demo';
import fixture from '../src/demo-fixture.json';

describe('Home HQ boundaries', () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it('loads the build-time project without consulting legacy browser configuration', () => {
    vi.stubEnv('VITE_SUPABASE_URL', 'https://example.supabase.co');
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test');
    const getItem = vi.fn(() => { throw new Error('Browser configuration must not be read'); });
    vi.stubGlobal('localStorage', { getItem });
    expect(loadConfig()).toEqual({ url: 'https://example.supabase.co', key: 'sb_publishable_test' });
    expect(getItem).not.toHaveBeenCalled();
  });
  it('does not turn a legacy browser connection into project configuration', () => {
    vi.stubEnv('VITE_SUPABASE_URL', '');
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', '');
    const getItem = vi.fn(() => JSON.stringify({ url: 'https://old-project.supabase.co', key: 'sb_publishable_old' }));
    vi.stubGlobal('localStorage', { getItem });
    expect(loadConfig()).toBeNull();
    expect(getItem).not.toHaveBeenCalled();
  });
  it('reports incomplete environment configuration instead of silently opening a local demo', () => {
    vi.stubEnv('VITE_SUPABASE_URL', 'https://example.supabase.co');
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', '');
    expect(() => loadConfig()).toThrow();
    vi.stubEnv('VITE_SUPABASE_URL', '');
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test');
    expect(() => loadConfig()).toThrow();
  });
  it('renders household text as text even when a title contains markup', () => {
    expect(escape('<img src=x onerror="bad()">')).toBe('&lt;img src=x onerror=&quot;bad()&quot;&gt;');
    expect(safeColor('red;position:fixed')).toBe('#343C35');
  });
  it('refuses a server-secret key and unencrypted remote connections', () => {
    expect(() => validateConfig({ url: 'https://example.supabase.co', key: 'sb_secret_test' })).toThrow('server');
    expect(() => validateConfig({ url: 'http://example.com', key: 'sb_publishable_test' })).toThrow('HTTPS');
    expect(validateConfig({ url: 'http://127.0.0.1:54321/path', key: 'test-public' }).url).toBe('http://127.0.0.1:54321');
  });
  it('retains Wes’s named family and picks the Piano lesson afternoon example', () => {
    const snapshot = seedDemo();
    expect(snapshot.people.map((p) => p.name)).toEqual(['Wes', 'Claudia', 'Buzzsaw', 'Skidmark']);
    expect(upcoming(snapshot.events.filter((event) => !event.all_day), new Date(snapshot.server_time * 1000))[0].title).toBe('Piano lesson');
    expect(progress(snapshot.chores).done).toBeGreaterThan(0);
    expect(snapshot.weather.sample).toBe(true);
    expect(snapshot.devices).toEqual(fixture.devices);
    expect(snapshot.home_status.lights_on).toBe(3);
    expect(snapshot.photos).toHaveLength(fixture.photos.length);
  });
  it('handles empty chores without inventing a completed score', () => {
    expect(progress([])).toEqual({ done: 0, total: 0, percent: 0 });
  });
  it('keeps event editing in the home timezone across a daylight saving boundary', () => {
    const summer = wallTimeEpoch('2026-10-11T15:45', 'America/Toronto');
    const winter = wallTimeEpoch('2026-11-15T15:45', 'America/Toronto');
    expect(new Date(summer * 1000).toISOString()).toBe('2026-10-11T19:45:00.000Z');
    expect(new Date(winter * 1000).toISOString()).toBe('2026-11-15T20:45:00.000Z');
    expect(localDateTime(summer, 'America/Toronto')).toBe('2026-10-11T15:45');
    expect(() => wallTimeEpoch('2026-03-08T02:30', 'America/Toronto')).toThrow('does not exist');
  });
  it('greets the home morning while a browser elsewhere is still on yesterday afternoon', () => {
    const instant = new Date('2026-10-12T00:30:00Z');
    expect(greeting(instant, 'Asia/Tokyo')).toBe('morning');
    expect(greeting(instant, 'America/Los_Angeles')).toBe('afternoon');
    expect(greeting(instant, 'America/Toronto')).toBe('evening');
    expect(greeting(new Date('2026-10-11T15:00:00Z'), 'Asia/Tokyo')).toBe('morning');
  });
});
