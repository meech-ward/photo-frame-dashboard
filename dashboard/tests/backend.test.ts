import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from '../src/demo-fixture.json';
import { HomeHQBackend } from '../src/backend';
import type { Snapshot } from '../src/types';

const mocks = vi.hoisted(() => ({ createClient: vi.fn() }));
vi.mock('@supabase/supabase-js', () => ({ createClient: mocks.createClient }));
const homeId = '11111111-1111-4111-8111-111111111111';
const memberId = '22222222-2222-4222-8222-222222222222';
const config = { url: 'https://test.supabase.co', key: 'sb_publishable_test' };

function setup(existingHome = true) {
  const snapshot = structuredClone(fixture) as Snapshot;
  snapshot.home.id = homeId;
  snapshot.photos = Array.from({ length: 21 }, (_, i) => ({
    id: `p${i}`, caption: '', place: '', asset: null,
    path: `${homeId}/${i}.png`, jpeg_path: `${homeId}/${i}.jpg`, web_path: `${homeId}/${i}-web.jpg`,
  }));
  const session = { user: { id: memberId }, access_token: 'test-access' };
  const signedUrl = vi.fn(async (path: string) => ({ data: { signedUrl: `https://photos.test/${path}` }, error: null }));
  const homeQuery = { select: vi.fn().mockReturnThis(), limit: vi.fn().mockReturnThis(), maybeSingle: vi.fn(async () => ({ data: existingHome ? { owner_id: homeId } : null, error: null })) };
  const channel = { on: vi.fn().mockReturnThis(), subscribe: vi.fn(function (callback: (status: string) => void) { callback('SUBSCRIBED'); return channel; }) };
  const client = {
    auth: { getSession: vi.fn(async () => ({ data: { session }, error: null })), onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })), stopAutoRefresh: vi.fn(), signInWithPassword: vi.fn(async () => ({ data: { session }, error: null })) },
    realtime: { setAuth: vi.fn() },
    rpc: vi.fn(async (name: string) => ({ data: name === 'homehq_web_snapshot' ? structuredClone(snapshot) : {}, error: null })),
    from: vi.fn(() => homeQuery),
    storage: { from: vi.fn(() => ({ createSignedUrl: signedUrl })) },
    channel: vi.fn(() => channel), removeChannel: vi.fn(),
  };
  mocks.createClient.mockReturnValue(client);
  const receive = vi.fn();
  const backend = new HomeHQBackend(config, receive, vi.fn());
  return { backend, client, snapshot, receive, signedUrl };
}

afterEach(() => vi.clearAllMocks());

describe('browser household reads', () => {
  it('restores a member login with 21 photos without invoking a bounded device RPC', async () => {
    const { backend, client, receive } = setup();
    await backend.start();
    expect(client.from).toHaveBeenCalledWith('homehq_homes');
    expect(client.rpc.mock.calls.every(([name]) => name === 'homehq_web_snapshot')).toBe(true);
    expect(receive.mock.lastCall![0].photos).toHaveLength(21);
    expect(client.channel).toHaveBeenCalledWith(`homehq:${homeId}`, { config: { private: true } });
    await backend.stop();
  });

  it('seeds only when no household is visible to the authenticated account', async () => {
    const { backend, client } = setup(false);
    await backend.start();
    expect(client.rpc).toHaveBeenCalledWith('homehq_seed_demo', { p_replace: false });
    expect(client.rpc).toHaveBeenCalledWith('homehq_web_snapshot');
    await backend.stop();
  });

  it('prefers web photos while retaining JPEG and PNG fallback for existing uploads', async () => {
    const { backend, snapshot, signedUrl } = setup();
    delete snapshot.photos[1].web_path;
    delete snapshot.photos[2].web_path;
    delete snapshot.photos[2].jpeg_path;
    await backend.start();
    expect(signedUrl).toHaveBeenCalledWith(`${homeId}/0-web.jpg`, 3600);
    expect(signedUrl).toHaveBeenCalledWith(`${homeId}/1.jpg`, 3600);
    expect(signedUrl).toHaveBeenCalledWith(`${homeId}/2.png`, 3600);
    expect(signedUrl).not.toHaveBeenCalledWith(`${homeId}/0.jpg`, 3600);
    await backend.stop();
  });
});
