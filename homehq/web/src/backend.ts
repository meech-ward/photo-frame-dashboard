import { createClient, type SupabaseClient, type Session, type RealtimeChannel } from '@supabase/supabase-js';
import type { Config, Snapshot, Kind, Editable, Chore, Shopping, Device, Event, Photo } from './types';
import { coalescePNGIDAT, MAX_BADGE_PNG_BYTES } from './badge-png';

export function validateConfig(config: Config): Config {
  const url = new URL(config.url.trim());
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) throw new Error('Use an HTTPS project URL, or a local Supabase URL.');
  const key = config.key.trim();
  if (!key || key.startsWith('sb_secret_')) throw new Error('Use the publishable key. A secret key must stay on the server.');
  if (key.split('.').length === 3) {
    try {
      const claims = JSON.parse(atob(key.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      if (claims.role === 'service_role') throw new Error('A service-role key must stay on the server.');
    } catch (error) { if (error instanceof Error && error.message.includes('service-role')) throw error; }
  }
  return { url: url.origin, key };
}
export function loadConfig(): Config | null {
  const url = import.meta.env.VITE_SUPABASE_URL?.trim();
  const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim();
  if (!url && !key) return null;
  if (!url || !key) throw new Error('Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY in .env.local, then restart Vite.');
  // The deployed build chooses its project. Browser state must never redirect
  // a configured application to a different backend on another device.
  return validateConfig({ url, key });
}
export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'signed-out';

export class HomeHQBackend {
  readonly client: SupabaseClient;
  session: Session | null = null;
  private channel: RealtimeChannel | null = null;
  private pendingRefresh = false;
  private refreshing = false;
  private active = true;
  private lastSnapshot: Snapshot | null = null;
  private unsubscribeAuth: (() => void) | null = null;
  private connectingUser: string | null = null;
  private authGeneration = 0;

  constructor(config: Config, private onSnapshot: (snapshot: Snapshot) => void, private onStatus: (status: LiveStatus, error?: string) => void) {
    this.client = createClient(config.url, config.key, {
      auth: { storageKey: `homehq.auth.${new URL(config.url).host}`, persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }

  async start(): Promise<void> {
    if (!this.unsubscribeAuth) {
      // Register before the initial read: an expired session can reject that
      // read, but a later sign-in must still refresh this same client's channel.
      const { data: listener } = this.client.auth.onAuthStateChange((_event, session) => {
        // Supabase's Auth callback runs under an internal lock. Deferring network
        // calls avoids waiting for the lock held by the callback itself.
        setTimeout(() => { if (this.active) void this.acceptSession(session).catch((e) => this.onStatus('reconnecting', String(e.message || e))); }, 0);
      });
      this.unsubscribeAuth = () => listener.subscription.unsubscribe();
    }
    const { data, error } = await this.client.auth.getSession();
    if (error) throw error;
    await this.acceptSession(data.session);
  }

  async signIn(email: string, password: string): Promise<void> {
    const { data, error } = await this.client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    await this.acceptSession(data.session);
  }
  async signUp(email: string, password: string): Promise<boolean> {
    const { data, error } = await this.client.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
    if (error) throw error;
    if (data.session) await this.acceptSession(data.session);
    return !!data.session;
  }
  async signOut(): Promise<void> {
    // Badges have independent sessions for this owner. Global logout would
    // revoke their refresh tokens when someone signs out of the web editor.
    const { error } = await this.client.auth.signOut({ scope: 'local' }); if (error) throw error;
  }

  get homeId(): string | null { return this.lastSnapshot?.home.id || this.session?.user.id || null; }

  async linkMember(email: string, personId: string, password = ''): Promise<boolean> {
    if (!this.session || !this.lastSnapshot?.viewer?.is_owner) throw new Error('The household owner sets up member logins.');
    let needsConfirmation = false;
    if (password) {
      // Signing up through the owner's client would replace their active Auth
      // session. A temporary client creates a normal account without switching
      // the editor or storing another person's credentials in this browser.
      const config = loadConfig();
      if (!config) throw new Error('Connect your project first.');
      const signup = createClient(config.url, config.key, { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false, storageKey: `homehq.signup.${crypto.randomUUID()}` } });
      try {
        const { data, error } = await signup.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
        if (error) throw error;
        if (data.user?.identities?.length === 0) throw new Error('This account already exists. Leave the password blank to link it.');
        needsConfirmation = !data.session;
      } finally {
        await signup.auth.signOut({ scope: 'local' });
        await signup.auth.stopAutoRefresh();
      }
    }
    const { error } = await this.client.rpc('homehq_link_member', { p_email: email.trim(), p_person_id: personId });
    if (error) throw error;
    await this.refresh();
    return needsConfirmation;
  }

  private async acceptSession(session: Session | null): Promise<void> {
    if (!this.active) return;
    const previous = this.session?.user.id;
    this.session = session;
    if (previous !== session?.user.id) { this.authGeneration++; this.lastSnapshot = null; this.connectingUser = null; }
    if (!session) { await this.dropChannel(); this.onStatus('signed-out'); return; }
    await this.client.realtime.setAuth(session.access_token);
    // Token refresh updates authorization on the existing socket. It should
    // never recreate a healthy subscription or pay another TLS connection.
    if (previous === session.user.id && this.channel) return;
    if (this.connectingUser === session.user.id) return;
    const generation = this.authGeneration;
    this.connectingUser = session.user.id;
    try {
    await this.dropChannel();
    this.onStatus('connecting');
    const { error } = await this.client.rpc('homehq_seed_demo', { p_replace: false });
    if (error) throw error;
    // A member's Auth UUID differs from the household UUID. Resolve the home
    // before joining so every family account receives the same invalidations.
    await this.refresh();
    if (!this.active || generation !== this.authGeneration || !this.lastSnapshot) return;
    this.channel = this.client.channel(`homehq:${this.homeId}`, { config: { private: true } })
      .on('broadcast', { event: 'changed' }, () => { void this.refresh(); })
      .subscribe((status) => {
        if (!this.active) return;
        if (status === 'SUBSCRIBED') {
          this.onStatus('live');
          // Broadcast is a fast invalidation hint. Durable rows recover any
          // edits missed while offline, including every successful rejoin.
          void this.refresh();
        } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
          this.onStatus('reconnecting');
        }
      });
    await this.refresh();
    } finally { if (generation === this.authGeneration) this.connectingUser = null; }
  }

  async refresh(): Promise<void> {
    if (!this.active || !this.session) return;
    this.pendingRefresh = true;
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      // Hints that arrive during a read request one more snapshot. Dropping that
      // final hint would leave the UI stale until a later, unrelated change.
      while (this.pendingRefresh && this.active && this.session) {
        this.pendingRefresh = false;
        const owner: string = this.session.user.id;
        const { data, error } = await this.client.rpc('homehq_snapshot');
        if (error) throw error;
        if (!data || data.schema_version !== 1) throw new Error('This project needs the Home HQ version 1 database setup.');
        const snapshot = data as Snapshot;
        for (let i = 0; i < snapshot.photos.length; i++) {
          const photo = snapshot.photos[i];
          if (photo.path && photo.path.startsWith(`${snapshot.home.id || owner}/`)) {
            const result = await this.client.storage.from('homehq-photos').createSignedUrl(photo.path, 3600);
            if (result.error) throw result.error;
            photo.url = result.data.signedUrl;
          } else photo.url = i % 2 ? '/sample-mountain.svg' : '/sample-coast.svg';
        }
        if (this.active && this.session?.user.id === owner) { this.lastSnapshot = snapshot; this.onSnapshot(snapshot); }
      }
    } catch (error) {
      // PostgREST errors are plain objects; String(error) hides the reason that
      // the owner needs to see while the project connection is recovering.
      const message = error && typeof error === 'object' && 'message' in error ? String(error.message) : String(error);
      this.onStatus('reconnecting', message);
    }
    finally { this.refreshing = false; }
  }

  async setDone(kind: 'chore' | 'shopping', item: Chore | Shopping, done: boolean, doneBy: string | null): Promise<'saved' | 'conflict'> {
    const { data, error } = await this.client.rpc('homehq_set_done', {
      p_kind: kind, p_id: item.id, p_done: done, p_version: item.version, p_done_by: doneBy,
    });
    if (error) throw error;
    await this.refresh();
    return data.status;
  }
  async setDevice(device: Device, state: Record<string, unknown>): Promise<'saved' | 'conflict'> {
    const { data, error } = await this.client.rpc('homehq_set_device', { p_id: device.id, p_state: state, p_version: device.version });
    if (error) throw error;
    await this.refresh(); return data.status;
  }

  async save(kind: Kind, item: Editable): Promise<void> {
    const owner_id = this.homeId;
    if (!owner_id) throw new Error('Sign in before saving to your project.');
    if (kind === 'event') {
      const event = item as Event;
      const { error } = await this.client.rpc('homehq_save_event', {
        p_id: event.id, p_title: event.title, p_start: event.start, p_end: event.end,
        p_people: event.people, p_loc: event.loc, p_notes: event.notes, p_travel: event.travel, p_all_day: event.all_day,
      });
      if (error) throw error;
    } else {
      const tables = { person: 'homehq_people', chore: 'homehq_checklist', shopping: 'homehq_checklist', photo: 'homehq_photos' };
      let row: Record<string, unknown>;
      if (kind === 'chore') {
        const chore = item as Chore;
        row = { owner_id, kind, id: chore.id, title: chore.title, person_id: chore.who === 'any' ? null : chore.who, routine: chore.routine, stars: chore.stars };
      } else if (kind === 'shopping') {
        const shopping = item as Shopping;
        row = { owner_id, kind, id: shopping.id, title: shopping.name, category: shopping.category, store: shopping.store, quantity: shopping.quantity, note: shopping.note };
      } else if (kind === 'photo') {
        const photo = item as Photo;
        row = { owner_id, id: photo.id, caption: photo.caption, place: photo.place, path: photo.path, asset: photo.asset || 'assets/photo-coast.png' };
      } else row = { ...item, owner_id };
      // Existing-row metadata edits must leave completion/version state alone.
      // An upsert could apply insertion defaults to an existing checklist row.
      const rows = this.lastSnapshot?.[{ person: 'people', chore: 'chores', shopping: 'shopping', photo: 'photos' }[kind] as 'people' | 'chores' | 'shopping' | 'photos'];
      const existing = rows?.some((entry) => entry.id === item.id);
      let request = existing ? this.client.from(tables[kind]).update(row).eq('owner_id', owner_id).eq('id', item.id) : this.client.from(tables[kind]).insert(row);
      if (existing && (kind === 'chore' || kind === 'shopping')) request = request.eq('kind', kind);
      const { error } = await request;
      if (error) throw error;
    }
    await this.refresh();
  }

  async remove(kind: Kind, id: string): Promise<void> {
    const table = { person: 'homehq_people', event: 'homehq_events', chore: 'homehq_checklist', shopping: 'homehq_checklist', photo: 'homehq_photos' }[kind];
    let query = this.client.from(table).delete().eq('owner_id', this.homeId!).eq('id', id);
    if (kind === 'chore' || kind === 'shopping') query = query.eq('kind', kind);
    const { error } = await query;
    if (error) throw error; await this.refresh();
  }
  async uploadPhoto(photo: Photo, file: File): Promise<void> {
    const blob = await badgePNG(file);
    const bytes = await blob.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const hash = [...new Uint8Array(digest)].map((n) => n.toString(16).padStart(2, '0')).join('');
    const path = `${this.homeId!}/${hash}.png`;
    const { error } = await this.client.storage.from('homehq-photos').upload(path, blob, { contentType: 'image/png', upsert: true });
    if (error) throw error;
    await this.save('photo', { ...photo, path });
  }
  private async dropChannel(): Promise<void> { if (this.channel) { await this.client.removeChannel(this.channel); this.channel = null; } }
  async stop(): Promise<void> { this.active = false; this.unsubscribeAuth?.(); await this.dropChannel(); await this.client.auth.stopAutoRefresh(); }
}

export { MAX_BADGE_PNG_BYTES } from './badge-png';

export async function badgePNG(file: File): Promise<Blob> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Choose a JPEG, PNG or WebP photo.');
  if (file.size > 20 * 1024 * 1024) throw new Error('Choose a photo smaller than 20 MB.');
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
    const context = canvas.getContext('2d'); if (!context) throw new Error('Your browser cannot prepare this photo.');
    // Crop before scaling. A fixed 4:3 PNG bounds badge decode memory and
    // removes source EXIF/GPS metadata; the uploaded original is never stored.
    const ratio = Math.max(320 / bitmap.width, 240 / bitmap.height);
    context.fillStyle = '#f2eee6'; context.fillRect(0, 0, 320, 240);
    context.drawImage(bitmap, (320 - bitmap.width * ratio) / 2, (240 - bitmap.height * ratio) / 2, bitmap.width * ratio, bitmap.height * ratio);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Could not prepare the photo.')), 'image/png'));
    if (blob.size > MAX_BADGE_PNG_BYTES) throw new Error('The prepared photo is too large for the badge. Choose a simpler image.');
    return new Blob([coalescePNGIDAT(new Uint8Array(await blob.arrayBuffer()))], { type: 'image/png' });
  } finally { bitmap.close(); }
}
