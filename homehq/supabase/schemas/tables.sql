-- owner_id remains the stable household key so adding individual logins does
-- not move existing rows, invalidate queued item IDs or rename photo objects.
create table public.homehq_homes (
  owner_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
  title text not null default 'Home HQ' check (char_length(title) between 1 and 60),
  timezone text not null default 'America/Toronto' check (char_length(timezone) between 1 and 80),
  demo boolean not null default true,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now()
);

create table public.homehq_people (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  id text not null check (id ~ '^[a-z0-9_-]{1,64}$'),
  name text not null check (char_length(name) between 1 and 40),
  color text not null check (color ~ '^#[0-9A-Fa-f]{6}$'),
  home boolean not null default true,
  status text not null default 'Home' check (char_length(status) <= 80),
  eta integer check (eta between 0 and 1440),
  sort_order integer not null default 0,
  primary key (owner_id, id)
);

-- One ordinary Auth account belongs to one home/person in this small demo.
-- Only the owner-authorized link RPC writes this mapping; JWT user_metadata
-- and badge configuration are preferences, never membership credentials.
create table public.homehq_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  owner_id uuid not null references public.homehq_homes(owner_id) on delete cascade,
  person_id text not null,
  unique (owner_id, person_id),
  -- Shared person editing must not indirectly unlink somebody's Auth account.
  -- Home/Auth deletion still cascades through their own membership foreign keys.
  foreign key (owner_id, person_id) references public.homehq_people(owner_id, id)
);

create table public.homehq_events (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  id text not null check (id ~ '^[a-z0-9_-]{1,64}$'),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  title text not null check (char_length(title) between 1 and 100),
  travel integer not null default 0 check (travel between 0 and 1440),
  loc text not null default '' check (char_length(loc) <= 120),
  notes text not null default '' check (char_length(notes) <= 240),
  all_day boolean not null default false,
  primary key (owner_id, id),
  check (ends_at >= starts_at)
);
create index homehq_events_owner_time on public.homehq_events(owner_id, starts_at);

create table public.homehq_event_people (
  owner_id uuid not null default auth.uid(),
  event_id text not null,
  person_id text not null,
  primary key (owner_id, event_id, person_id),
  foreign key (owner_id, event_id) references public.homehq_events(owner_id, id) on delete cascade,
  foreign key (owner_id, person_id) references public.homehq_people(owner_id, id) on delete cascade
);
create index homehq_event_people_person on public.homehq_event_people(owner_id, person_id);

create table public.homehq_checklist (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  kind text not null check (kind in ('chore', 'shopping')),
  id text not null check (id ~ '^[a-z0-9_-]{1,64}$'),
  title text not null check (char_length(title) between 1 and 100),
  person_id text,
  routine text check (routine in ('morning', 'after', 'evening')),
  stars integer not null default 0 check (stars between 0 and 99),
  category text not null default '' check (char_length(category) <= 40),
  store text not null default '' check (char_length(store) <= 40),
  quantity integer not null default 1 check (quantity between 1 and 999),
  note text not null default '' check (char_length(note) <= 160),
  done boolean not null default false,
  done_by text,
  created_by_user_id uuid references auth.users(id) on delete set null,
  completed_by_user_id uuid references auth.users(id) on delete set null,
  version bigint not null default 1 check (version > 0),
  sort_order integer not null default 0,
  primary key (owner_id, kind, id),
  foreign key (owner_id, person_id) references public.homehq_people(owner_id, id),
  foreign key (owner_id, done_by) references public.homehq_people(owner_id, id),
  check ((kind = 'chore' and routine is not null)
    or (kind = 'shopping' and person_id is null and routine is null and stars = 0 and done_by is null)),
  check (kind <> 'chore' or (not done and done_by is null)
    or (done and done_by is not null and (person_id is null or done_by = person_id)))
);
create index homehq_checklist_person on public.homehq_checklist(owner_id, person_id);
create index homehq_checklist_done_by on public.homehq_checklist(owner_id, done_by);
create index homehq_checklist_creator on public.homehq_checklist(created_by_user_id);
create index homehq_checklist_completer on public.homehq_checklist(completed_by_user_id);

-- Weather and agent usage are bounded display documents, not provider credentials
-- or code interpreted on a badge. Their source stays visibly marked as a sample.
create table public.homehq_cards (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  section text not null check (section in ('weather', 'home_status', 'agents')),
  data jsonb not null check (octet_length(data::text) <= 8192),
  updated_at timestamptz not null default now(),
  primary key (owner_id, section),
  check (case when section = 'agents' then
    case when jsonb_typeof(data) = 'array' then jsonb_array_length(data) <= 8 else false end
    else jsonb_typeof(data) = 'object' end)
);

create table public.homehq_devices (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  id text not null check (id ~ '^[a-z0-9_-]{1,64}$'),
  name text not null check (char_length(name) between 1 and 40),
  room text not null check (char_length(room) between 1 and 40),
  type text not null check (type in ('light', 'lock', 'garage')),
  on_state boolean,
  level integer check (level between 0 and 100),
  locked boolean,
  garage_state text check (garage_state in ('open', 'closed')),
  version bigint not null default 1 check (version > 0),
  sort_order integer not null default 0,
  primary key (owner_id, id),
  check ((type = 'light' and on_state is not null and level is not null and locked is null and garage_state is null)
    or (type = 'lock' and locked is not null and on_state is null and level is null and garage_state is null)
    or (type = 'garage' and garage_state is not null and on_state is null and level is null and locked is null))
);

create table public.homehq_photos (
  owner_id uuid not null default auth.uid() references public.homehq_homes(owner_id) on delete cascade,
  id text not null check (id ~ '^[a-z0-9_-]{1,64}$'),
  path text,
  -- Keep the PNG for older clients and the Chromatic's streaming PNG decoder;
  -- a Tufty can fetch the much smaller JPEG without changing that wire field.
  jpeg_path text,
  asset text not null default 'assets/photo-coast.png' check (asset ~ '^assets/[a-z0-9_-]+\.png$'),
  caption text not null default '' check (char_length(caption) <= 60),
  place text not null default '' check (char_length(place) <= 80),
  sort_order integer not null default 0,
  primary key (owner_id, id),
  -- Content-addressed PNGs make caching safe without mutable remote filenames.
  check (path is null or path ~ ('^' || owner_id::text || '/[0-9a-f]{64}\.png$')),
  constraint homehq_photos_jpeg_path_check check (jpeg_path is null or (path is not null
    and jpeg_path ~ ('^' || owner_id::text || '/[0-9a-f]{64}\.jpg$')))
);
