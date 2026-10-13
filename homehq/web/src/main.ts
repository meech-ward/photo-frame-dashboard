import './style.css';
import { HomeHQBackend, badgePNG, loadConfig, type LiveStatus } from './backend';
import { loadDemo, persistDemo, resetDemo, saveDemo, collection } from './demo';
import { icon } from './icons';
import { escape as e, safeColor, clock as formatClock, dayKey as formatDayKey, localDateTime as formatLocalDateTime, wallTimeEpoch, progress, upcoming, greeting } from './utils';
import type { Snapshot, Section, Kind, Editable, Person, Event, Chore, Shopping, Photo, Device } from './types';

const app = document.querySelector<HTMLDivElement>('#app')!;
const sheet = document.querySelector<HTMLDialogElement>('#sheet')!;
const toast = document.querySelector<HTMLDivElement>('#toast')!;
const sections: Section[] = ['today', 'calendar', 'chores', 'shopping', 'photos', 'home', 'agents'];
const names: Record<Section, string> = { today: 'Today', calendar: 'Calendar', chores: 'Chores', shopping: 'Shopping', photos: 'Photos', home: 'Home', agents: 'Agents' };
let snapshot = loadDemo();
const entry = new URLSearchParams(window.location.search);
let section: Section = (['today', 'calendar', 'chores', 'shopping', 'photos', 'home', 'agents'] as string[]).includes(entry.get('section') || '') ? entry.get('section') as Section : 'today';
// A configured project is the source of truth. A stale browser demo preference
// must never divert edits into local storage while the badge reads Supabase.
let configurationError = '';
let demo = false;
try { demo = !loadConfig(); }
catch (error) { configurationError = error instanceof Error ? error.message : String(error); }
let liveLoaded = false;
let live: HomeHQBackend | null = null;
let status: LiveStatus = demo ? 'signed-out' : 'connecting';
let fault = '';
let filter = 'all';
let viewerId: string | null = null;
let routine = 'after';
let store = 'all';
let photoIndex = 0;
let calendarOffset = 0;
let ambient = false;
let toastTimer: ReturnType<typeof setTimeout>;
let undo: (() => Promise<void>) | null = null;
const boot = Date.now();

function now(): Date { return demo ? new Date(snapshot.server_time * 1000 + Date.now() - boot) : new Date(); }
function zone(): string { return demo ? Intl.DateTimeFormat().resolvedOptions().timeZone : snapshot.home.timezone; }
function clock(value: string | number | Date): string { return formatClock(value, { timeZone: zone() }); }
function dayKey(value: string | number | Date): string { return formatDayKey(value, zone()); }
function localDateTime(value: number): string { return formatLocalDateTime(value, zone()); }
function dateText(date: Date, options: Intl.DateTimeFormatOptions): string { return date.toLocaleDateString(undefined, { timeZone: zone(), ...options }); }
function person(id: string): Person | undefined { return snapshot.people.find((p) => p.id === id); }
function avatar(p: Person, size?: number): string { return `<span class="avatar ${p.home ? '' : 'away'}" style="--person:${safeColor(p.color)};${size ? `width:${size}px;height:${size}px;` : ''}">${e(p.name.slice(0, 1))}</span>`; }
function eventColor(event: Event): string { return safeColor(person(event.people[0])?.color || '#343c35'); }
function eventPeople(event: Event): string { return event.people.length >= snapshot.people.length ? 'Everyone' : event.people.map((id) => person(id)?.name || id).join(' + '); }
function field(label: string, name: string, value = '', extra = '', type = 'text'): string { return `<label>${label}<input name="${name}" type="${type}" value="${e(value)}" ${extra}></label>`; }
function intro(title: string, subtitle: string, action = ''): string { return `<div class="intro"><div><h1>${title}</h1><p>${subtitle}</p></div>${action}</div>`; }
function add(kind: Kind, text: string): string { return `<button class="button solid" data-new="${kind}">${icon('plus', 15)}${text}</button>`; }
function badgeSample(sample: boolean): string { return sample ? '<span class="sample">Sample</span>' : ''; }
function samplePhoto(photo: Photo): boolean { return !photo.path && !photo.url?.startsWith('data:'); }

function render(): void {
  const ready = !configurationError && (demo || liveLoaded);
  const connected = status === 'live' && liveLoaded;
  const connectionLabel = demo ? 'Offline demo' : status === 'signed-out' ? 'Sign in' : connected ? 'Live sync' : liveLoaded ? 'Reconnecting' : 'Connecting';
  // The fixture cannot stand in for a missing Auth session or snapshot: its
  // editable rows would look like the household while saving nowhere useful.
  const content = configurationError ? intro('App configuration needs attention.', configurationError) : ready ? ({ today: todayView, calendar: calendarView, chores: choresView, shopping: shoppingView, photos: photosView, home: homeView, agents: agentsView })[section]()
    : intro(status === 'signed-out' ? 'Sign in to your home.' : 'Connecting to your home.',
      status === 'signed-out' ? 'Sign in with your own family account. Your household stays in Supabase.' : 'Loading your household from Supabase.')
      + `<button class="button solid" data-settings>${status === 'signed-out' ? 'Sign in' : 'Account settings'}</button>`;
  app.innerHTML = `<aside class="rail"><button class="monogram" data-go="today" aria-label="Home HQ, Today">h.</button><nav aria-label="Sections">${sections.map((key) => `<button class="nav-item ${section === key ? 'active' : ''}" data-go="${key}" ${section === key ? 'aria-current="page"' : ''}>${icon(key, 23)}<span>${names[key]}</span></button>`).join('')}</nav><div class="rail-bottom"><div class="rail-rule"></div><button data-settings aria-label="Settings">${icon('settings', 20)}</button><div class="rail-date">${now().toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<br>${now().getFullYear()}</div></div></aside>
    <div class="shell"><header class="masthead"><div class="brand serif">Home HQ <i>A little home headquarters.</i></div><div class="masthead-right"><button class="connection ${demo ? 'demo' : connected ? '' : 'reconnecting'}" data-settings><span class="status-dot"></span>${connectionLabel}</button><button class="settings-button" data-settings aria-label="Account settings">${icon('settings', 15)}<span>Account</span></button></div></header>
    ${fault ? `<div class="status-error" role="alert">${e(fault)}<button data-refresh>Try again</button></div>` : ''}
    <main id="main" tabindex="-1" aria-label="${names[section]}">${content}</main>
    <footer class="page-footer"><span><a href="/">Back to dashboard</a> · Household editor for <a href="https://github.com/wesbos/photo-frame-dashboard" target="_blank" rel="noreferrer">Wes Bos’s Home HQ</a>.</span><span>${demo ? 'Changes stay in this browser. Sample clock & providers.' : liveLoaded ? `${snapshot.viewer?.person_id ? `Signed in as ${e(person(snapshot.viewer.person_id)?.name || 'family member')} · ` : ''}Shared household · ${snapshot.home.timezone} · Revision ${snapshot.revision}` : `Your Supabase project · ${status === 'signed-out' ? 'Sign in to load your household.' : 'Loading your household.'}`}</span></footer></div>
    ${ambient && ready ? ambientView() : ''}`;
}

function todayView(): string {
  const today = now();
  const future = upcoming(snapshot.events.filter((event) => !event.all_day), today);
  const next = future[0];
  const minutes = next ? Math.max(0, Math.round((next.start * 1000 - today.getTime()) / 60_000)) : 0;
  const happening = !!next && next.start * 1000 <= today.getTime();
  const leave = next ? minutes - next.travel : 0;
  const timeParts = new Intl.DateTimeFormat(undefined, { timeZone: zone(), hour: 'numeric', minute: '2-digit' }).formatToParts(today);
  const time = timeParts.filter((p) => p.type !== 'dayPeriod').map((p) => p.value).join('').trim();
  const period = timeParts.find((p) => p.type === 'dayPeriod')?.value || '';
  const chores = progress(snapshot.chores);
  const hero = next ? `<button class="hero" data-edit="event" data-id="${e(next.id)}"><div class="label">${happening ? 'Happening now' : 'Next up'} · ${e(eventPeople(next))}</div><div class="hero-title serif">${e(next.title)}</div><div class="hero-meta">${clock(next.start)} – ${clock(next.end)}<br>${e(next.loc)}</div><div class="hero-count num">${happening ? Math.max(1, Math.round((next.end * 1000 - today.getTime()) / 60_000)) : minutes < 100 ? minutes : clock(next.start).split(' ')[0]}<small>${happening ? 'minutes left' : minutes < 100 ? 'minutes to go' : 'starts at'}</small></div><div class="hero-bottom"><span class="pill">${happening ? 'Enjoy the moment.' : next.travel ? leave <= 0 ? 'Time to leave' : `Leave in ${leave} min · ${next.travel} min drive` : 'You have everything you need.'}</span><span class="hero-arrow">${icon('arrow', 19)}</span></div></button>` : `<button class="hero" data-go="calendar"><span class="label">All caught up</span><div class="hero-title serif">Enjoy<br>the quiet.</div><div class="hero-bottom"><span class="pill">Nothing else scheduled</span><span class="hero-arrow">${icon('arrow', 19)}</span></div></button>`;
  return `<div class="today-top"><div class="clock-box"><div class="eyebrow"><span class="little-line"></span>Good ${greeting(today, zone())}, home.</div><div class="big-clock num">${time}<span>${period}</span></div><div class="full-date"><b>${dateText(today, { weekday: 'long' })}</b>, ${dateText(today, { month: 'long', day: 'numeric' })}</div>${demo ? '<div class="demo-clock">Wes’s afternoon example · Demo clock</div>' : ''}<div class="weather-strip">${icon('cloud', 39)}<span class="num">${snapshot.weather.temp}°</span><div class="weather-copy"><b>${e(snapshot.weather.label)} ${badgeSample(snapshot.weather.sample)}</b><p>H ${snapshot.weather.high}° · L ${snapshot.weather.low}° &nbsp; ${e(snapshot.weather.summary)}</p></div></div></div>${hero}</div>
    <div class="block-heading"><h2>Everyone’s afternoon</h2><button class="text-button" data-family>Edit the family ${icon('plus', 13)}</button></div>
    <div class="family-lanes">${snapshot.people.map((p) => {
      const events = future.filter((event) => event.people.includes(p.id) && dayKey(event.start) === dayKey(today)).slice(0, 3);
      return `<div class="family-lane" style="--person:${safeColor(p.color)}"><button class="person-header" data-edit="person" data-id="${e(p.id)}">${avatar(p)}<span><b>${e(p.name)}</b><small>${e(p.home ? 'Home' : p.status)}${p.eta ? ` · ${p.eta} min` : ''}</small></span></button><div class="lane-events">${events.map((event) => `<button class="lane-event" data-edit="event" data-id="${e(event.id)}"><time>${clock(event.start).replace(/\s?[AP]M/, '')}</time><span>${e(event.title)}</span></button>`).join('') || '<p class="empty-lane"><i>Free</i> for<br>the rest of today.</p>'}</div></div>`;
    }).join('')}</div>
    <div class="today-bottom"><button class="small-card chore-summary" data-go="chores"><span class="progress-ring" style="--progress:${chores.percent}%"><span>${chores.done}/${chores.total}</span></span><span><span class="label">Little wins</span><h3>Team effort.</h3><p>${chores.total - chores.done} chores left · We’ve got this.</p></span></button><button class="small-card home-mini" data-go="home"><span><span class="label">Home, sweet home ${badgeSample(snapshot.home_status.sample)}</span><h3>All settled.</h3><p>${snapshot.home_status.lights_on} lights on · ${snapshot.home_status.locked ? 'Doors locked' : 'Door unlocked'}</p></span><span class="num">${snapshot.home_status.temperature}°</span></button><button class="small-card photo-mini" data-ambient><img src="${e(snapshot.photos[0]?.url || '/sample-coast.svg')}" alt="Sample coast artwork"><span class="photo-copy"><span class="label">Take a breath</span><h3>A little perspective.</h3><p>Open photo mode ${icon('arrow', 12)}</p></span></button></div>`;
}

function familyFilters(): string { return `<div class="filters"><button class="filter ${filter === 'all' ? 'on' : ''}" data-filter="all">Everyone</button>${snapshot.people.map((p) => `<button class="filter ${filter === p.id ? 'on' : ''}" style="--person:${safeColor(p.color)}" data-filter="${e(p.id)}"><span class="dot"></span>${e(p.name)}</button>`).join('')}</div>`; }
function calendarView(): string {
  return intro('Room for everything.', 'Seven days ahead, with everyone in the picture.', add('event', 'Add event')) + familyFilters() + `<div class="block-heading"><h2>${calendarOffset === 0 ? 'Today & the next two days' : 'A little further ahead'}</h2><div class="calendar-actions"><button class="icon-button" data-calendar-step="-3" ${calendarOffset === 0 ? 'disabled' : ''} aria-label="Previous days"><span style="transform:rotate(180deg);display:flex">${icon('chevron', 15)}</span></button><button class="icon-button" data-calendar-step="3" ${calendarOffset >= 6 ? 'disabled' : ''} aria-label="Next days">${icon('chevron', 15)}</button></div></div><div class="calendar-grid">${[0, 1, 2].map((n) => calendarOffset + n).filter((offset) => offset < 7).map((offset) => {
    const date = new Date(now().getTime() + offset * 86_400_000);
    const events = snapshot.events.filter((event) => (event.all_day ? dayKey(event.start) <= dayKey(date) && dayKey(event.end) > dayKey(date) : dayKey(event.start) === dayKey(date)) && (filter === 'all' || event.people.includes(filter))).sort((a, b) => a.start - b.start);
    return `<section class="day-column"><div class="day-head"><b>${offset === 0 ? 'Today' : offset === 1 ? 'Tomorrow' : dateText(date, { weekday: 'long' })}</b><span class="num">${dateText(date, { day: 'numeric' })}</span></div>${events.map((event) => `<button class="calendar-event" style="--person:${eventColor(event)}" data-edit="event" data-id="${e(event.id)}"><time>${event.all_day ? 'All day' : `${clock(event.start)} – ${clock(event.end)}`}</time><b>${e(event.title)}</b><span>${e(eventPeople(event))}${event.loc ? ` · ${e(event.loc)}` : ''}</span></button>`).join('') || '<p class="empty">A little breathing room.</p>'}</section>`;
  }).join('')}</div>`;
}
function checkRow(kind: 'chore' | 'shopping', item: Chore | Shopping, color: string): string {
  const title = kind === 'chore' ? (item as Chore).title : (item as Shopping).name;
  const completedMember = snapshot.members?.find((member) => member.user_id === item.completed_by_user_id)?.person_id;
  const completion = item.done && (completedMember || (kind === 'chore' && (item as Chore).done_by));
  const detail = kind === 'shopping' ? `${(item as Shopping).quantity} · ${e((item as Shopping).store)}${(item as Shopping).note ? ` · ${e((item as Shopping).note)}` : ''}${completion ? ` · Done by ${e(person(String(completion))?.name || '')}` : ''}` : completion ? `Done by ${e(person(String(completion))?.name || '')}` : '';
  return `<div class="check-row ${item.done ? 'done' : ''}" style="--person:${safeColor(color)}"><button class="check-main" data-complete="${kind}" data-id="${e(item.id)}" role="checkbox" aria-checked="${item.done}" aria-label="${e(title)}"><span class="check-circle">${item.done ? icon('check', 14) : ''}</span><span class="row-copy"><b>${e(title)}</b>${detail ? `<small>${detail}</small>` : ''}</span>${kind === 'chore' && (item as Chore).stars ? `<span class="stars">${'✦'.repeat(Math.min(3, (item as Chore).stars))}</span>` : ''}</button><button class="row-edit" data-edit="${kind}" data-id="${e(item.id)}" aria-label="Edit ${e(title)}">Edit</button></div>`;
}
function choresView(): string {
  const groups = [...(filter === 'all' ? snapshot.people : snapshot.people.filter((p) => p.id === filter)), { id: 'any', name: 'Team effort', color: '#315342', home: true, status: 'Anyone can help' }];
  return intro('Little wins add up.', 'One tick at a time. Changes reach the badge live.', add('chore', 'Add chore')) + `<div class="filters">${[['morning', 'Morning'], ['after', 'After school'], ['evening', 'Evening']].map(([id, label]) => `<button class="filter ${routine === id ? 'on' : ''}" data-routine="${id}">${label}</button>`).join('')}</div>` + familyFilters() + `<div class="chores-grid">${groups.map((p) => {
    const chores = snapshot.chores.filter((c) => c.who === p.id && c.routine === routine);
    const score = progress(chores);
    return `<section class="chore-panel" style="--person:${safeColor(p.color)}"><div class="person-header">${avatar(p, 41)}<span><b>${e(p.name)}</b><small>${score.done} of ${score.total} done</small></span><span class="score">${chores.filter((c) => c.done).reduce((n, c) => n + c.stars, 0)} ✦ earned</span></div>${chores.map((c) => checkRow('chore', c, p.color)).join('') || '<p class="empty">All clear for this routine.</p>'}</section>`;
  }).join('')}</div>`;
}
function shoppingView(): string {
  const items = snapshot.shopping.filter((s) => store === 'all' || s.store === store);
  const categories = [...new Set(items.map((s) => s.category))];
  const left = items.filter((s) => !s.done).length;
  return intro('Bring home the good stuff.', 'A shared list. A happier grocery run.', add('shopping', 'Add item')) + `<div class="filters">${['all', ...new Set(snapshot.shopping.map((s) => s.store))].map((id) => `<button class="filter ${store === id ? 'on' : ''}" data-store="${e(id)}">${id === 'all' ? 'All stores' : e(id)}</button>`).join('')}</div><div class="shopping-layout"><div class="shopping-groups">${categories.map((category) => `<section class="shopping-group"><h2>${e(category || 'Other')}</h2>${items.filter((s) => s.category === category).map((s) => checkRow('shopping', s, '#315342')).join('')}</section>`).join('') || '<p class="empty">The list is empty. Add something delicious.</p>'}</div><aside class="shopping-note">${icon('leaf', 34)}<h2 class="serif">A little less<br>“did we get…?”</h2><p>Everyone sees the same list.<br>Tick it here. See it on the badge.</p><div class="num">${left}<span style="font-size:13px;letter-spacing:0;margin-left:10px">left to grab</span></div><p>Completed something by accident?<br>Tap it again, or use Undo.</p><button class="button" data-new="shopping">${icon('plus', 15)}Add to the list</button></aside></div>`;
}
function photosView(): string {
  return intro('The moments in between.', 'Your photos, prepared for a little 320 × 240 screen.', `<button class="button solid" data-upload>${icon('upload', 15)}Add photo</button>`) + `<p class="sample-note">${snapshot.photos.some(samplePhoto) ? 'Bundled illustrations stand in for the example photos. ' : ''}${demo ? 'Demo uploads stay in this browser.' : 'Your uploads stay in your private project.'} The editor crops them to the badge’s 4:3 screen.</p><div class="photo-grid">${snapshot.photos.map((photo, i) => `<article class="photo-tile"><button data-photo="${i}" class="full" aria-label="View ${e(photo.caption)}"><img src="${e(photo.url || '/sample-coast.svg')}" alt="${e(photo.place || photo.caption)}"></button><div class="photo-caption"><div><b>${e(photo.place || photo.caption || 'A little memory')}</b><p>${e(photo.caption)} ${samplePhoto(photo) ? '· Sample artwork' : ''}</p></div><button class="icon-button" data-edit="photo" data-id="${e(photo.id)}" aria-label="Edit photo caption">${icon('photos', 17)}</button></div></article>`).join('') || `<div class="photo-empty"><h2>Make yourself at home.</h2><button class="button" data-upload>${icon('upload', 16)}Add your first photo</button></div>`}</div>`;
}
function homeView(): string {
  return intro('Home, sweet home.', 'A calm place to see how the house is doing.') + '<p class="sample-note">Sample home controls. Try the switches: state is shared with your badge, but no physical lights, locks or doors are connected.</p>' + `<div class="home-layout"><section class="climate-card"><div class="label">Inside, it’s just right ${badgeSample(true)}</div><div class="num">${snapshot.home_status.temperature}°</div><p>Comfortable at home · Sample temperature</p></section><section class="home-summary"><div class="label">A little peace of mind ${badgeSample(true)}</div><h2 class="serif">${snapshot.home_status.locked ? 'All tucked in.' : 'The door is unlocked.'}</h2><p class="sample-note">${snapshot.home_status.lights_on} lights on.<br>Changes sync across your screens.</p></section></div><div class="device-grid">${(snapshot.devices || []).map((device) => {
    const on = device.type === 'light' ? !!device.on : device.type === 'lock' ? !!device.locked : device.state === 'closed';
    const label = device.type === 'light' ? device.on ? `On · ${device.level}%` : 'Off' : device.type === 'lock' ? device.locked ? 'Locked' : 'Unlocked' : device.state === 'closed' ? 'Closed' : 'Open';
    return `<button class="device ${on ? 'on' : ''}" data-device="${e(device.id)}" aria-label="${e(device.name)}, ${label}"><span class="device-icon">${icon(device.type === 'light' ? 'light' : 'lock', 27)}</span><span class="toggle"></span><b>${e(device.name)}</b><p>${e(device.room)} · ${label}</p>${badgeSample(true)}</button>`;
  }).join('')}</div>`;
}
function agentsView(): string {
  return intro('A little help behind the scenes.', 'Usage at a glance, with room for the next good idea.') + '<p class="sample-note">These are Wes’s sample usage cards. No provider accounts or billing feeds are connected.</p>' + `<div class="agents-grid">${snapshot.agents.map((agent) => `<article class="agent" style="--person:${safeColor(agent.color)}"><div class="agent-head"><span class="agent-logo">${e(agent.name.slice(0, 1))}</span><h2>${e(agent.name)}</h2>${badgeSample(agent.sample)}</div>${agent.meters.map((meter) => `<div class="agent-meter"><div class="agent-meter-top"><span>${e(meter.label)}</span><b>${meter.used}<small>%</small></b></div><div class="meter" role="meter" aria-label="${e(meter.label)} used" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${meter.used}"><span style="width:${Math.max(0, Math.min(100, meter.used))}%"></span></div><p>Resets in ${meter.reset_minutes < 120 ? `${meter.reset_minutes} minutes` : `${Math.round(meter.reset_minutes / 60)} hours`}</p></div>`).join('')}<div class="sparkline" aria-label="Sample usage over seven days">${agent.week.map((amount) => `<span style="height:${Math.max(7, amount / Math.max(...agent.week) * 69)}px" title="${amount}"></span>`).join('')}</div><div class="spark-days">${['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((s) => `<span>${s}</span>`).join('')}</div><p class="agent-week">Past seven days · Sample usage</p></article>`).join('')}</div>`;
}
function ambientView(): string {
  const photo = snapshot.photos[photoIndex % Math.max(1, snapshot.photos.length)];
  return `<div class="ambient"><img src="${e(photo?.url || '/sample-coast.svg')}" alt="${e(photo?.place || 'Sample coast artwork')}"><div class="ambient-copy"><div class="num">${clock(now())}</div><div class="serif">${e(photo?.place || 'A little perspective.')}</div><div class="label">${photo && !samplePhoto(photo) ? 'Your private photo' : 'Sample artwork'}${demo ? ' · Demo clock' : ''}</div></div><button class="button" data-end-ambient>${icon('close', 16)}Back to Home HQ</button></div>`;
}

function openSheet(body: string): void { sheet.innerHTML = `<button class="icon-button sheet-close" data-close aria-label="Close dialog">${icon('close', 17)}</button><div class="sheet-pad">${body}</div>`; sheet.showModal(); }
function closeSheet(): void { sheet.close(); }
function notify(message: string, undoAction?: () => Promise<void>): void {
  clearTimeout(toastTimer); undo = undoAction || null;
  toast.innerHTML = `<span>${e(message)}</span>${undo ? '<button data-undo>Undo</button>' : ''}`; toast.classList.add('show');
  toastTimer = setTimeout(() => { toast.classList.remove('show'); undo = null; }, 7000);
}
function commitDemo(next: Snapshot): void {
  if (!demo) throw new Error('This household is saved in Supabase.');
  snapshot = next; try { persistDemo(snapshot); } catch { notify('Saved for this visit. Browser storage is unavailable.'); }
  render();
}
function requireWritable(): void {
  // A dialog or Undo can outlive Auth/network state. Gate its eventual save,
  // too, so recovery never turns an intended cloud edit into a local change.
  if (demo) return;
  if (!live?.session) throw new Error('Sign in to save changes to your household.');
  if (!liveLoaded || status !== 'live') throw new Error('Wait for the Supabase connection before saving changes.');
}
function peopleOptions(selected = 'any'): string { return `<option value="any" ${selected === 'any' ? 'selected' : ''}>Anyone</option>${snapshot.people.map((p) => `<option value="${e(p.id)}" ${selected === p.id ? 'selected' : ''}>${e(p.name)}</option>`).join('')}`; }

function edit(kind: Kind, id?: string): void {
  const current = id ? (snapshot[collection(kind)] as Editable[]).find((item) => item.id === id) : undefined;
  const titles = { person: 'Meet the family.', event: 'Make a little plan.', chore: 'One little thing.', shopping: 'Add something good.', photo: 'A little memory.' };
  let body = '';
  if (kind === 'person') {
    const p = current as Person | undefined;
    body = field('Name', 'name', p?.name || '', 'required maxlength="40" autocomplete="off"') + '<div class="form-row">' + field('Their colour', 'color', p?.color || '#2D5BFF', '', 'color') + `<label>At home<select name="home"><option value="true" ${p?.home !== false ? 'selected' : ''}>At home</option><option value="false" ${p?.home === false ? 'selected' : ''}>Away</option></select></label></div>` + field('Status', 'status', p?.status || 'Home', 'maxlength="80"') + field('ETA in minutes (optional)', 'eta', p?.eta?.toString() || '', 'min="0" max="1440"', 'number');
  } else if (kind === 'event') {
    const event = current as Event | undefined;
    const start = event?.start || Math.floor(now().getTime() / 1000);
    body = field('Event title', 'title', event?.title || '', 'required maxlength="100"') + `<div class="form-row">${field('Starts', 'start', localDateTime(start), 'required', 'datetime-local')}${field('Ends', 'end', localDateTime(event?.end || start + 3600), 'required', 'datetime-local')}</div><div class="form-row">${field('Location', 'loc', event?.loc || '', 'maxlength="120"')}${field('Travel minutes', 'travel', String(event?.travel || 0), 'min="0" max="1440" required', 'number')}</div><label>Who’s going?<select name="people" multiple size="4">${snapshot.people.map((p) => `<option value="${e(p.id)}" ${event?.people.includes(p.id) ? 'selected' : ''}>${e(p.name)}</option>`).join('')}</select><small>Choose one or more people. On a computer, use Command or Ctrl to select several.</small></label><label class="checkbox-label"><input name="all_day" type="checkbox" ${event?.all_day ? 'checked' : ''}>All-day event</label><label>Notes<textarea name="notes" maxlength="240">${e(event?.notes || '')}</textarea></label>`;
  } else if (kind === 'chore') {
    const chore = current as Chore | undefined;
    body = field('Chore', 'title', chore?.title || '', 'required maxlength="100"') + `<div class="form-row"><label>For<select name="who" ${chore?.done ? 'disabled' : ''}>${peopleOptions(chore?.who)}</select>${chore?.done ? '<small>Undo completion before reassigning.</small>' : ''}</label><label>Routine<select name="routine">${[['morning', 'Morning'], ['after', 'After school'], ['evening', 'Evening']].map(([value, name]) => `<option value="${value}" ${(chore?.routine || routine) === value ? 'selected' : ''}>${name}</option>`).join('')}</select></label></div>` + field('Stars', 'stars', String(chore?.stars ?? 1), 'min="0" max="99"', 'number');
  } else if (kind === 'shopping') {
    const item = current as Shopping | undefined;
    body = field('Item', 'name', item?.name || '', 'required maxlength="100"') + `<div class="form-row">${field('Category', 'category', item?.category || 'Produce', 'maxlength="40"')}${field('Quantity', 'quantity', String(item?.quantity || 1), 'required min="1" max="999"', 'number')}</div>` + field('Store', 'store', item?.store || 'FreshCo', 'maxlength="40"') + field('Note', 'note', item?.note || '', 'maxlength="160"');
  } else {
    const photo = current as Photo | undefined;
    body = field('Caption', 'caption', photo?.caption || '', 'maxlength="60"') + field('Place', 'place', photo?.place || '', 'maxlength="80"');
  }
  openSheet(`<div class="label">${id ? 'Edit' : 'Add'} ${kind === 'person' ? 'person' : kind}</div><h2 id="sheet-title" class="sheet-title">${titles[kind]}</h2><form class="form-stack" data-save="${kind}" data-id="${e(id || '')}">${body}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancel</button><button class="button solid" type="submit">Save ${kind === 'shopping' ? 'item' : kind}</button></div>${id ? `<button type="button" class="delete-link" data-delete="${kind}" data-id="${e(id)}">Remove ${kind === 'shopping' ? 'item' : kind}</button>` : ''}</form>`);
}

async function submitEdit(form: HTMLFormElement): Promise<void> {
  requireWritable();
  const kind = form.dataset.save as Kind; const values = new FormData(form);
  const id = form.dataset.id || `${kind.slice(0, 1)}_${crypto.randomUUID()}`;
  const old = (snapshot[collection(kind)] as Editable[]).find((item) => item.id === id);
  let item: Editable;
  if (kind === 'person') item = { id, name: String(values.get('name')).trim(), color: String(values.get('color')), home: values.get('home') === 'true', status: String(values.get('status')), eta: values.get('eta') ? Number(values.get('eta')) : null };
  else if (kind === 'event') {
    const start = wallTimeEpoch(String(values.get('start')), zone()); const end = wallTimeEpoch(String(values.get('end')), zone());
    if (end < start) throw new Error('The end must be at or after the start.');
    const people = values.getAll('people').map(String); if (!people.length) throw new Error('Choose at least one person.');
    item = { id, title: String(values.get('title')).trim(), start, end, people, loc: String(values.get('loc')), notes: String(values.get('notes')), travel: Number(values.get('travel')), all_day: values.has('all_day') };
  } else if (kind === 'chore') item = { id, title: String(values.get('title')).trim(), who: String(values.get('who') || (old as Chore)?.who || 'any'), routine: String(values.get('routine')), stars: Number(values.get('stars')), done: (old as Chore)?.done || false, done_by: (old as Chore)?.done_by || null, version: (old as Chore)?.version || 1 };
  else if (kind === 'shopping') item = { id, name: String(values.get('name')).trim(), category: String(values.get('category')), quantity: Number(values.get('quantity')), store: String(values.get('store')), note: String(values.get('note')), done: (old as Shopping)?.done || false, version: (old as Shopping)?.version || 1 };
  else item = { ...(old as Photo), id, caption: String(values.get('caption')), place: String(values.get('place')) };
  if (demo) commitDemo(saveDemo(snapshot, kind, item)); else await live!.save(kind, item);
  closeSheet(); notify('A little update, saved.');
}

async function setDone(kind: 'chore' | 'shopping', id: string, done?: boolean, doneBy?: string | null): Promise<void> {
  requireWritable();
  const rows = kind === 'chore' ? snapshot.chores : snapshot.shopping;
  const item = rows.find((row) => row.id === id)!;
  const desired = done ?? !item.done;
  const previous = structuredClone(item);
  if (!demo && kind === 'chore' && desired && (item as Chore).who === 'any' && !doneBy) doneBy = snapshot.viewer?.person_id;
  if (kind === 'chore' && desired && (item as Chore).who === 'any' && !doneBy) {
    openSheet(`<div class="label">Team effort</div><h2 id="sheet-title" class="sheet-title">Who gets the little win?</h2><p class="sheet-intro">${e((item as Chore).title)}</p><div class="choice-grid">${snapshot.people.map((p) => `<button class="person-choice" data-credit="${e(p.id)}" data-id="${e(id)}">${avatar(p)}${e(p.name)}</button>`).join('')}</div>`); return;
  }
  const actor = kind === 'chore' && desired ? doneBy || (item as Chore).who : null;
  if (demo) {
    const updated = { ...item, done: desired, version: item.version + 1, ...(kind === 'chore' ? { done_by: actor } : {}) } as Editable;
    commitDemo(saveDemo(snapshot, kind, updated));
  } else {
    const result = await live!.setDone(kind, item, desired, actor);
    if (result === 'conflict') { notify('Someone changed this first. The latest state is here.'); return; }
  }
  closeSheet();
  notify(desired ? 'One little win. Nicely done.' : 'Back on the list.', async () => { await setDone(kind, id, previous.done, kind === 'chore' ? (previous as Chore).done_by : null); });
}

function settings(): void {
  const signedIn = !!live?.session;
  openSheet(`<div class="label">Home HQ</div><h2 id="sheet-title" class="sheet-title">${signedIn ? 'Your account' : 'Sign in'}</h2>
    ${configurationError ? `<p class="sheet-intro">${e(configurationError)}</p>` : demo ? `<p class="sheet-intro">This preview uses example data.</p><button class="button" data-reset>Reset demo</button>` : signedIn ? `<p class="account-email">${e(live!.session!.user.email)}</p><p class="connection-detail">${snapshot.viewer?.person_id ? `Signed in as ${e(person(snapshot.viewer.person_id)?.name || 'family member')}. ` : ''}Everyone in your household shares this dashboard.</p><div class="settings-actions"><button class="button" data-signout>Sign out</button></div>${liveLoaded ? memberLogins() : ''}` : `<p class="sheet-intro">Sign in to your household.</p><form class="form-stack" data-auth>${field('Email', 'email', '', 'required autocomplete="email"', 'email')}${field('Password', 'password', '', 'required minlength="8" autocomplete="current-password"', 'password')}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button solid" type="submit" name="action" value="signin">Sign in</button><button class="button" type="submit" name="action" value="signup">Create account</button></div><small>To join an existing household, ask its owner to set up your member login first.</small></form>`}`);
}

function memberLogins(): string {
  const members = snapshot.members || [];
  return `<div class="section-rule"></div><div class="label">One home, your own login</div><h3>Member logins</h3><div class="member-logins">${snapshot.people.map((p) => `<div class="member-login-row">${avatar(p, 32)}<b>${e(p.name)}</b><small>${members.some((m) => m.person_id === p.id) ? 'Login linked' : 'No login yet'}</small></div>`).join('')}</div>${snapshot.viewer?.is_owner ? `<form class="form-stack" data-member><p class="connection-detail">Create a login for a family member, or link an existing account by leaving the password blank. You stay signed in.</p><label>Family member<select name="person_id">${snapshot.people.map((p) => `<option value="${e(p.id)}">${e(p.name)}</option>`).join('')}</select></label>${field('Member email', 'email', '', 'required autocomplete="off"', 'email')}${field('New account password (optional)', 'password', '', 'minlength="8" autocomplete="new-password"', 'password')}<p class="form-error" role="alert"></p><button class="button solid" type="submit">Set up member login</button></form>` : '<p class="connection-detail">The household owner sets up these logins. Sign in with yours on any badge or browser.</p>'}`;
}
function familySheet(): void {
  openSheet(`<div class="label">Your people</div><h2 id="sheet-title" class="sheet-title">Everyone belongs here.</h2><p class="sheet-intro">A colour, a name, and a little room for each person’s day.</p><div class="choice-grid">${snapshot.people.map((p) => `<button class="person-choice" data-edit="person" data-id="${e(p.id)}">${avatar(p)}${e(p.name)}</button>`).join('')}</div><button class="button solid full" style="margin-top:18px" data-new="person">${icon('plus', 15)}Add a person</button>`);
}

async function configure(): Promise<void> {
  const config = loadConfig(); demo = !config; if (!config) return;
  await live?.stop();
  liveLoaded = false; ambient = false; status = 'connecting'; fault = ''; render();
  const backend = new HomeHQBackend(config, (next) => {
    if (live !== backend || demo) return;
    const nextViewer = next.viewer?.user_id || backend.session?.user.id || null;
    if (viewerId !== nextViewer) {
      // Selection and Undo belong to the signed-in person; retaining them
      // across account changes can apply a previous user's intended action.
      filter = next.viewer?.person_id || 'all'; undo = null; ambient = false;
      viewerId = nextViewer;
    }
    snapshot = next; liveLoaded = true; fault = ''; render();
  }, (nextStatus, error) => {
    if (live !== backend) return;
    status = nextStatus;
    if (error && !demo) fault = error;
    if (nextStatus === 'signed-out') { liveLoaded = false; ambient = false; undo = null; viewerId = null; filter = 'all'; }
    render();
  });
  live = backend;
  try { await backend.start(); }
  catch (error) {
    // A failed session restore needs login, not an editable local imitation of
    // the home. The project choice survives and Try again can restore Auth.
    if (live === backend) { status = backend.session ? 'reconnecting' : 'signed-out'; fault = error && typeof error === 'object' && 'message' in error ? String(error.message) : String(error); render(); }
    throw error;
  }
}

function uploadDialog(): void {
  openSheet(`<div class="label">Your photos</div><h2 id="sheet-title" class="sheet-title">A little more you.</h2><p class="sheet-intro">Choose a photo. We’ll crop the centre to fit your little screen.</p><form class="form-stack" data-photo-upload><label>Photo<input name="file" type="file" accept="image/jpeg,image/png,image/webp" required></label>${field('Caption', 'caption', '', 'maxlength="60" placeholder="A day to remember"')}${field('Place', 'place', '', 'maxlength="80" placeholder="Somewhere special"')}<small>${demo ? 'Demo uploads stay in this browser.' : 'Only the prepared images go to your private Storage bucket.'}</small><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancel</button><button class="button solid" type="submit">Add photo</button></div></form>`);
}
async function submitUpload(form: HTMLFormElement): Promise<void> {
  requireWritable();
  const values = new FormData(form); const file = values.get('file') as File;
  if (!file?.size) throw new Error('Choose a photo first.');
  const existingSample = snapshot.photos.find((photo) => !photo.path && !photo.url?.startsWith('data:'));
  const photo: Photo = { id: existingSample?.id || `p_${crypto.randomUUID()}`, caption: String(values.get('caption')) || file.name.replace(/\.[^.]+$/, '').slice(0, 60), place: String(values.get('place')), path: null, asset: 'assets/photo-coast.png' };
  if (demo) {
    const blob = await badgePNG(file);
    photo.url = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(blob); });
    commitDemo(saveDemo(snapshot, 'photo', photo));
  } else await live!.uploadPhoto(photo, file);
  closeSheet(); notify('A little memory, ready for the badge.');
}

async function changeDevice(id: string, confirmed = false): Promise<void> {
  requireWritable();
  const device = snapshot.devices!.find((d) => d.id === id)!;
  const state = device.type === 'light' ? { on: !device.on } : device.type === 'lock' ? { locked: !device.locked } : { state: device.state === 'closed' ? 'open' : 'closed' };
  if (device.type !== 'light' && !confirmed) {
    const verb = device.type === 'lock' ? device.locked ? 'Unlock' : 'Lock' : device.state === 'closed' ? 'Open' : 'Close';
    openSheet(`<div class="label">Sample control</div><h2 id="sheet-title" class="sheet-title">${verb} the ${e(device.name.toLowerCase())}?</h2><p class="confirm-copy">This updates the sample home state on your screens. No physical door or lock is connected.</p><div class="form-actions"><button class="button" data-close>Cancel</button><button class="button solid" data-confirm-device="${e(id)}">${verb} sample ${device.type === 'lock' ? 'lock' : 'garage'}</button></div>`); return;
  }
  if (demo) {
    const next = structuredClone(snapshot); Object.assign(next.devices!.find((d) => d.id === id)!, state, { version: device.version + 1 }); next.revision++;
    next.home_status.lights_on = next.devices!.filter((d) => d.type === 'light' && d.on).length;
    next.home_status.locked = next.devices!.filter((d) => d.type === 'lock').every((d) => d.locked);
    commitDemo(next);
  } else if (await live!.setDevice(device, state) === 'conflict') { notify('Someone changed this first. The latest state is here.'); return; }
  closeSheet(); notify('Sample home state, updated.');
}

async function action(target: HTMLElement): Promise<void> {
  if (target.matches('[data-new],[data-edit],[data-family],[data-complete],[data-credit],[data-upload],[data-device],[data-confirm-device],[data-delete],[data-confirm-delete],[data-undo]')) requireWritable();
  if (target.hasAttribute('data-close')) closeSheet();
  else if (target.dataset.go) { section = target.dataset.go as Section; render(); window.scrollTo({ top: 0 }); }
  else if (target.dataset.filter) { filter = target.dataset.filter; render(); }
  else if (target.dataset.routine) { routine = target.dataset.routine; render(); }
  else if (target.dataset.store) { store = target.dataset.store; render(); }
  else if (target.hasAttribute('data-settings')) settings();
  else if (target.hasAttribute('data-family')) familySheet();
  else if (target.dataset.calendarStep) { calendarOffset = Math.max(0, Math.min(6, calendarOffset + Number(target.dataset.calendarStep))); render(); }
  else if (target.dataset.new) edit(target.dataset.new as Kind);
  else if (target.dataset.edit) edit(target.dataset.edit as Kind, target.dataset.id);
  else if (target.dataset.complete) await setDone(target.dataset.complete as 'chore' | 'shopping', target.dataset.id!);
  else if (target.dataset.credit) await setDone('chore', target.dataset.id!, true, target.dataset.credit);
  else if (target.hasAttribute('data-refresh')) { fault = ''; render(); if (!live) await configure(); else if (!live.session || !liveLoaded) await live.start(); else await live.refresh(); }
  else if (target.hasAttribute('data-reset') && demo) { snapshot = resetDemo(); fault = ''; closeSheet(); render(); notify('The original example is back.'); }
  else if (target.hasAttribute('data-signout')) { await live?.signOut(); liveLoaded = false; status = 'signed-out'; closeSheet(); render(); notify('Signed out of this browser. Your badge stays connected.'); }
  else if (target.hasAttribute('data-upload')) uploadDialog();
  else if (target.dataset.photo) { photoIndex = Number(target.dataset.photo); ambient = true; render(); }
  else if (target.hasAttribute('data-ambient')) { ambient = true; render(); }
  else if (target.hasAttribute('data-end-ambient')) { ambient = false; render(); }
  else if (target.dataset.device) await changeDevice(target.dataset.device);
  else if (target.dataset.confirmDevice) await changeDevice(target.dataset.confirmDevice, true);
  else if (target.hasAttribute('data-undo') && undo) { const fn = undo; undo = null; await fn(); }
  else if (target.dataset.delete) {
    const kind = target.dataset.delete as Kind; const id = target.dataset.id!;
    openSheet(`<div class="label">Remove ${kind}</div><h2 id="sheet-title" class="sheet-title">Make a little room?</h2><p class="confirm-copy">Remove this ${kind === 'shopping' ? 'item' : kind} from your ${demo ? 'demo' : 'project'}?</p><div class="form-actions"><button class="button" data-close>Cancel</button><button class="button danger" data-confirm-delete="${kind}" data-id="${e(id)}">Remove</button></div>`);
  } else if (target.dataset.confirmDelete) {
    const kind = target.dataset.confirmDelete as Kind; const id = target.dataset.id!;
    if (kind === 'person' && (snapshot.events.some((event) => event.people.includes(id)) || snapshot.chores.some((chore) => chore.who === id || chore.done_by === id))) throw new Error('This person still has events or chores. Reassign or remove those first.');
    if (demo) { const next = structuredClone(snapshot); (next[collection(kind)] as Editable[]) = (next[collection(kind)] as Editable[]).filter((row) => row.id !== id); next.revision++; commitDemo(next); }
    else await live!.remove(kind, id);
    closeSheet(); notify('Removed. A little breathing room.');
  }
}

document.addEventListener('click', (event) => {
  const target = (event.target as Element).closest<HTMLButtonElement>('button'); if (!target || (target.type === 'submit' && target.form)) return;
  void action(target).catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    const field = sheet.open && sheet.querySelector('.form-error'); if (field) field.textContent = message; else notify(message);
  });
});
document.addEventListener('submit', (event) => {
  const form = event.target as HTMLFormElement; event.preventDefault();
  const button = (event as SubmitEvent).submitter as HTMLButtonElement | null;
  const submitButtons = [...form.querySelectorAll<HTMLButtonElement>('button[type="submit"]')]; submitButtons.forEach((b) => b.disabled = true);
  const work = async (): Promise<void> => {
    if (form.dataset.save) await submitEdit(form);
    else if (form.hasAttribute('data-auth')) {
      const data = new FormData(form); if (!live) await configure();
      if (button?.value === 'signup') {
        const active = await live!.signUp(String(data.get('email')), String(data.get('password')));
        if (!active) { status = 'signed-out'; render(); notify('Check your email to finish creating your account.'); closeSheet(); return; }
      } else await live!.signIn(String(data.get('email')), String(data.get('password')));
      closeSheet(); notify('Welcome home. Your project is connected.');
    } else if (form.hasAttribute('data-member')) {
      requireWritable();
      const values = new FormData(form);
      const password = String(values.get('password') || '');
      // The account form must not keep another member's password after a
      // request, including a failed signup/link that needs a later retry.
      const input = form.elements.namedItem('password') as HTMLInputElement;
      input.value = '';
      const confirm = await live!.linkMember(String(values.get('email')), String(values.get('person_id')), password);
      settings(); notify(confirm ? 'Login linked. Confirm the email, then sign in on the badge.' : 'Login linked. This member can sign in on their badge.');
    } else if (form.hasAttribute('data-photo-upload')) await submitUpload(form);
  };
  void work().catch((error) => { const field = form.querySelector('.form-error'); if (field) field.textContent = error instanceof Error ? error.message : String(error); }).finally(() => submitButtons.forEach((b) => b.disabled = false));
});
sheet.addEventListener('click', (event) => { if (event.target === sheet) { const rect = sheet.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeSheet(); } });
window.addEventListener('focus', () => { if (!demo) void live?.refresh(); });
window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && ambient) { ambient = false; render(); } });
setInterval(() => { if (ambient && snapshot.photos.length) photoIndex = (photoIndex + 1) % snapshot.photos.length; if (!sheet.open) render(); }, 60_000);
render();
void configure().then(() => {
  if (entry.has('settings')) settings();
  const kind = entry.get('new') as Kind;
  if ((demo || (liveLoaded && status === 'live')) && ['person', 'event', 'chore', 'shopping', 'photo'].includes(kind)) edit(kind);
}).catch((error) => notify(`Connection needs attention: ${error.message}`));
