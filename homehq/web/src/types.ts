export type Section = 'today' | 'calendar' | 'chores' | 'shopping' | 'photos' | 'home' | 'agents';
export type Kind = 'person' | 'event' | 'chore' | 'shopping' | 'photo';
export interface Person { id: string; name: string; color: string; status: string; home: boolean; eta?: number | null }
export interface Event { id: string; title: string; start: number; end: number; start_offset_minutes?: number; end_offset_minutes?: number; loc: string; notes: string; people: string[]; all_day: boolean; travel: number }
export interface Chore { id: string; title: string; who: string; routine: string; stars: number; done: boolean; done_by: string | null; completed_by_user_id?: string | null; created_by_user_id?: string | null; version: number }
export interface Shopping { id: string; name: string; category: string; quantity: number; store: string; note: string; done: boolean; completed_by_user_id?: string | null; created_by_user_id?: string | null; version: number }
export interface Photo { id: string; caption: string; place: string; path: string | null; jpeg_path?: string | null; asset: string | null; url?: string }
export interface Weather { temp: number; high: number; low: number; label: string; summary: string; sample: boolean }
export interface Device { id: string; name: string; room: string; type: 'light' | 'lock' | 'garage'; on?: boolean; locked?: boolean; state?: string; level?: number; version: number; sample: boolean }
export interface Agent { id: string; name: string; color: string; sample: boolean; meters: { label: string; used: number; reset_minutes: number }[]; week: number[] }
export interface Snapshot { schema_version: number; revision: number; server_time: number; home: { id?: string; title: string; timezone: string; utc_offset_minutes: number; demo: boolean }; viewer?: { user_id: string; person_id: string | null; is_owner: boolean }; members?: { user_id: string; person_id: string }[]; people: Person[]; events: Event[]; chores: Chore[]; shopping: Shopping[]; photos: Photo[]; weather: Weather; home_status: { temperature: number; lights_on: number; locked: boolean; sample: boolean }; agents: Agent[]; devices?: Device[] }
export type Editable = Person | Event | Chore | Shopping | Photo;
export interface Config { url: string; key: string }
