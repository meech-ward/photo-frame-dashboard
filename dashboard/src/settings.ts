import "./settings.css";
import { HomeHQBackend, loadConfig, type LiveStatus } from "./backend";
import {
  escape as e,
  safeColor,
  localDateTime as formatLocalDateTime,
  wallTimeEpoch,
} from "./utils";
import type {
  Snapshot,
  Kind,
  Editable,
  Person,
  Event,
  Chore,
  Shopping,
  Photo,
} from "./types";

const app = document.querySelector<HTMLDivElement>("#app")!;
const sheet = document.querySelector<HTMLDialogElement>("#sheet")!;
const toast = document.querySelector<HTMLDivElement>("#toast")!;
let snapshot: Snapshot;
let live: HomeHQBackend | null = null;
let liveLoaded = false;
let status: LiveStatus = "connecting";
let fault = "";
let configurationError = "";
let configured = false;
let toastTimer: ReturnType<typeof setTimeout>;
const collection = (kind: Kind) =>
  (
    ({
      person: "people",
      event: "events",
      chore: "chores",
      shopping: "shopping",
      photo: "photos",
    }) as const
  )[kind];
const zone = () => snapshot.home.timezone;
const now = () => new Date();
const localDateTime = (value: number) => formatLocalDateTime(value, zone());
const routine = "after";
function field(
  label: string,
  name: string,
  value = "",
  extra = "",
  type = "text",
): string {
  return `<label>${label}<input name="${name}" type="${type}" value="${e(value)}" ${extra}></label>`;
}
function avatar(p: Person, size = 32): string {
  return `<span class="avatar" style="--person:${safeColor(p.color)};width:${size}px;height:${size}px">${e(p.name.slice(0, 1))}</span>`;
}
function person(id: string): Person | undefined {
  return snapshot.people.find((p) => p.id === id);
}
function openSheet(body: string): void {
  sheet.innerHTML = `<button class="sheet-close" data-close aria-label="Close dialog">×</button><div class="sheet-pad">${body}</div>`;
  if (!sheet.open) sheet.showModal();
}
function closeSheet(): void {
  sheet.close();
  sheet.innerHTML = "";
}
function notify(message: string): void {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 5500);
}
function requireWritable(): void {
  if (!live?.session)
    throw new Error("Sign in to save changes to your household.");
  if (!liveLoaded || status !== "live")
    throw new Error("Wait for the Supabase connection before saving changes.");
}
function row(kind: Kind, item: Editable, label: string): string {
  return `<li><span>${e(label)}</span><button class="button" data-edit="${kind}" data-id="${e(item.id)}">Edit ${kind === "person" ? e(label) : kind === "photo" ? "photo caption" : kind}</button></li>`;
}
function render(): void {
  const signedIn = !!live?.session;
  const ready = signedIn && liveLoaded;
  const statusLabel =
    status === "live"
      ? "Live sync"
      : status === "signed-out"
        ? "Sign in"
        : liveLoaded
          ? "Reconnecting"
          : "Connecting";
  app.innerHTML = `<header><a href="/">← Dashboard</a><span id="settings-status" role="status">${configured ? statusLabel : "Local prototype"}</span></header><h1 class="serif">Household settings</h1><p class="lead">Accounts, family members and photos for your shared dashboard.</p>
    ${configurationError ? `<p role="alert">${e(configurationError)}</p>` : !configured ? "<p>This is the local prototype. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY in .env.local to connect a household.</p>" : `<section><h2>Your account</h2>${signedIn ? `<p>${e(live!.session!.user.email || "")}</p><button class="button" data-signout>Sign out</button>` : '<button class="button solid" data-settings>Sign in</button>'}${fault ? `<p role="alert">${e(fault)}</p><button class="button" data-refresh>Try again</button>` : ""}</section>`}
    ${
      ready
        ? `<section><div class="section-head"><h2>Family</h2><button class="button" data-new="person">Add a person</button></div><ul>${snapshot.people.map((p) => row("person", p, p.name)).join("")}</ul>${memberLogins()}</section>
    <section><div class="section-head"><h2>Photos</h2><button class="button solid" data-upload>Add photo</button></div><p>The dashboard keeps a large image. Smaller copies fit your badge and Chromatic.</p><div class="photo-grid">${snapshot.photos.map((p) => `<figure><img src="${e(p.url || "/sample-coast.svg")}" alt="${e(p.place || p.caption || "Family photo")}"><figcaption>${e(p.caption || "Family photo")}</figcaption><button class="button" data-edit="photo" data-id="${e(p.id)}">Edit photo caption</button></figure>`).join("")}</div></section>
    <section><h2>Household details</h2><p>Use the dashboard for everyday checklists and adding events. Manage descriptions and assignments here.</p>
    <details><summary>Chores</summary><button class="button" data-new="chore">Add chore</button><ul>${snapshot.chores.map((x) => row("chore", x, x.title)).join("")}</ul></details>
    <details><summary>Shopping details</summary><ul>${snapshot.shopping.map((x) => row("shopping", x, x.name)).join("")}</ul></details>
    <details><summary>Event details</summary><ul>${snapshot.events.map((x) => row("event", x, x.title)).join("")}</ul></details></section>`
        : ""
    }`;
}
function peopleOptions(selected = "any"): string {
  return `<option value="any" ${selected === "any" ? "selected" : ""}>Anyone</option>${snapshot.people.map((p) => `<option value="${e(p.id)}" ${selected === p.id ? "selected" : ""}>${e(p.name)}</option>`).join("")}`;
}

function edit(kind: Kind, id?: string): void {
  const current = id
    ? (snapshot[collection(kind)] as Editable[]).find((item) => item.id === id)
    : undefined;
  const titles = {
    person: "Meet the family.",
    event: "Make a little plan.",
    chore: "One little thing.",
    shopping: "Add something good.",
    photo: "A little memory.",
  };
  let body = "";
  if (kind === "person") {
    const p = current as Person | undefined;
    body =
      field(
        "Name",
        "name",
        p?.name || "",
        'required maxlength="40" autocomplete="off"',
      ) +
      '<div class="form-row">' +
      field("Their colour", "color", p?.color || "#2D5BFF", "", "color") +
      `<label>At home<select name="home"><option value="true" ${p?.home !== false ? "selected" : ""}>At home</option><option value="false" ${p?.home === false ? "selected" : ""}>Away</option></select></label></div>` +
      field("Status", "status", p?.status || "Home", 'maxlength="80"') +
      field(
        "ETA in minutes (optional)",
        "eta",
        p?.eta?.toString() || "",
        'min="0" max="1440"',
        "number",
      );
  } else if (kind === "event") {
    const event = current as Event | undefined;
    const start = event?.start || Math.floor(now().getTime() / 1000);
    body =
      field(
        "Event title",
        "title",
        event?.title || "",
        'required maxlength="100"',
      ) +
      `<div class="form-row">${field("Starts", "start", localDateTime(start), "required", "datetime-local")}${field("Ends", "end", localDateTime(event?.end || start + 3600), "required", "datetime-local")}</div><div class="form-row">${field("Location", "loc", event?.loc || "", 'maxlength="120"')}${field("Travel minutes", "travel", String(event?.travel || 0), 'min="0" max="1440" required', "number")}</div><label>Who’s going?<select name="people" multiple size="4">${snapshot.people.map((p) => `<option value="${e(p.id)}" ${event?.people.includes(p.id) ? "selected" : ""}>${e(p.name)}</option>`).join("")}</select><small>Choose one or more people. On a computer, use Command or Ctrl to select several.</small></label><label class="checkbox-label"><input name="all_day" type="checkbox" ${event?.all_day ? "checked" : ""}>All-day event</label><label>Notes<textarea name="notes" maxlength="240">${e(event?.notes || "")}</textarea></label>`;
  } else if (kind === "chore") {
    const chore = current as Chore | undefined;
    body =
      field("Chore", "title", chore?.title || "", 'required maxlength="100"') +
      `<div class="form-row"><label>For<select name="who" ${chore?.done ? "disabled" : ""}>${peopleOptions(chore?.who)}</select>${chore?.done ? "<small>Undo completion before reassigning.</small>" : ""}</label><label>Routine<select name="routine">${[
        ["morning", "Morning"],
        ["after", "After school"],
        ["evening", "Evening"],
      ]
        .map(
          ([value, name]) =>
            `<option value="${value}" ${(chore?.routine || routine) === value ? "selected" : ""}>${name}</option>`,
        )
        .join("")}</select></label></div>` +
      field(
        "Stars",
        "stars",
        String(chore?.stars ?? 1),
        'min="0" max="99"',
        "number",
      );
  } else if (kind === "shopping") {
    const item = current as Shopping | undefined;
    body =
      field("Item", "name", item?.name || "", 'required maxlength="100"') +
      `<div class="form-row">${field("Category", "category", item?.category || "Produce", 'maxlength="40"')}${field("Quantity", "quantity", String(item?.quantity || 1), 'required min="1" max="999"', "number")}</div>` +
      field("Store", "store", item?.store || "FreshCo", 'maxlength="40"') +
      field("Note", "note", item?.note || "", 'maxlength="160"');
  } else {
    const photo = current as Photo | undefined;
    body =
      field("Caption", "caption", photo?.caption || "", 'maxlength="60"') +
      field("Place", "place", photo?.place || "", 'maxlength="80"');
  }
  openSheet(
    `<div class="label">${id ? "Edit" : "Add"} ${kind === "person" ? "person" : kind}</div><h2 id="sheet-title" class="sheet-title">${titles[kind]}</h2><form class="form-stack" data-save="${kind}" data-id="${e(id || "")}">${body}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancel</button><button class="button solid" type="submit">Save ${kind === "shopping" ? "item" : kind}</button></div>${id ? `<button type="button" class="delete-link" data-delete="${kind}" data-id="${e(id)}">Remove ${kind === "shopping" ? "item" : kind}</button>` : ""}</form>`,
  );
}

async function submitEdit(form: HTMLFormElement): Promise<void> {
  requireWritable();
  const kind = form.dataset.save as Kind;
  const values = new FormData(form);
  const id = form.dataset.id || `${kind.slice(0, 1)}_${crypto.randomUUID()}`;
  const old = (snapshot[collection(kind)] as Editable[]).find(
    (item) => item.id === id,
  );
  let item: Editable;
  if (kind === "person")
    item = {
      id,
      name: String(values.get("name")).trim(),
      color: String(values.get("color")),
      home: values.get("home") === "true",
      status: String(values.get("status")),
      eta: values.get("eta") ? Number(values.get("eta")) : null,
    };
  else if (kind === "event") {
    const start = wallTimeEpoch(String(values.get("start")), zone());
    const end = wallTimeEpoch(String(values.get("end")), zone());
    if (end < start) throw new Error("The end must be at or after the start.");
    const people = values.getAll("people").map(String);
    if (!people.length) throw new Error("Choose at least one person.");
    item = {
      id,
      title: String(values.get("title")).trim(),
      start,
      end,
      people,
      loc: String(values.get("loc")),
      notes: String(values.get("notes")),
      travel: Number(values.get("travel")),
      all_day: values.has("all_day"),
    };
  } else if (kind === "chore")
    item = {
      id,
      title: String(values.get("title")).trim(),
      who: String(values.get("who") || (old as Chore)?.who || "any"),
      routine: String(values.get("routine")),
      stars: Number(values.get("stars")),
      done: (old as Chore)?.done || false,
      done_by: (old as Chore)?.done_by || null,
      version: (old as Chore)?.version || 1,
    };
  else if (kind === "shopping")
    item = {
      id,
      name: String(values.get("name")).trim(),
      category: String(values.get("category")),
      quantity: Number(values.get("quantity")),
      store: String(values.get("store")),
      note: String(values.get("note")),
      done: (old as Shopping)?.done || false,
      version: (old as Shopping)?.version || 1,
    };
  else
    item = {
      ...(old as Photo),
      id,
      caption: String(values.get("caption")),
      place: String(values.get("place")),
    };
  await live!.save(kind, item);
  closeSheet();
  notify("Saved to your household.");
}

function memberLogins(): string {
  const members = snapshot.members || [];
  return `<div class="section-rule"></div><div class="label">One home, your own login</div><h3>Member logins</h3><div class="member-logins">${snapshot.people.map((p) => `<div class="member-login-row">${avatar(p, 32)}<b>${e(p.name)}</b><small>${members.some((m) => m.person_id === p.id) ? "Login linked" : "No login yet"}</small></div>`).join("")}</div>${snapshot.viewer?.is_owner ? `<form class="form-stack" data-member><p class="connection-detail">Create a login for a family member, or link an existing account by leaving the password blank. You stay signed in.</p><label>Family member<select name="person_id">${snapshot.people.map((p) => `<option value="${e(p.id)}">${e(p.name)}</option>`).join("")}</select></label>${field("Member email", "email", "", 'required autocomplete="off"', "email")}${field("New account password (optional)", "password", "", 'minlength="8" autocomplete="new-password"', "password")}<p class="form-error" role="alert"></p><button class="button solid" type="submit">Set up member login</button></form>` : '<p class="connection-detail">The household owner sets up these logins. Sign in with yours on any badge or browser.</p>'}`;
}
function settings(): void {
  openSheet(
    `<h2 id="sheet-title">Sign in</h2><form class="form-stack" data-auth>${field("Email", "email", "", 'required autocomplete="email"', "email")}${field("Password", "password", "", 'required minlength="8" autocomplete="current-password"', "password")}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button solid" type="submit" name="action" value="signin">Sign in</button><button class="button" type="submit" name="action" value="signup">Create account</button></div><small>To join an existing household, ask its owner to set up your member login first.</small></form>`,
  );
}
function uploadDialog(): void {
  openSheet(
    `<h2 id="sheet-title">Add a family photo</h2><p>Keep the full composition on your dashboard, with smaller copies prepared for your devices.</p><form class="form-stack" data-photo-upload><label>Photo<input name="file" type="file" accept="image/jpeg,image/png,image/webp" required></label>${field("Caption", "caption", "", 'maxlength="60"')}${field("Place", "place", "", 'maxlength="80"')}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancel</button><button class="button solid" type="submit">Add photo</button></div></form>`,
  );
}
async function submitUpload(form: HTMLFormElement): Promise<void> {
  requireWritable();
  const values = new FormData(form),
    file = values.get("file") as File;
  if (!file?.size) throw new Error("Choose a photo first.");
  const sample = snapshot.photos.find((p) => !p.path);
  const photo: Photo = {
    id: sample?.id || `p_${crypto.randomUUID()}`,
    caption:
      String(values.get("caption")) ||
      file.name.replace(/\.[^.]+$/, "").slice(0, 60),
    place: String(values.get("place")),
    path: null,
    asset: null,
  };
  await live!.uploadPhoto(photo, file);
  closeSheet();
  notify("Photo added to your household.");
}
async function configure(): Promise<void> {
  let config;
  try {
    config = loadConfig();
  } catch (error) {
    configurationError = String((error as Error).message);
    render();
    return;
  }
  configured = !!config;
  if (!config) {
    render();
    return;
  }
  live = new HomeHQBackend(
    config,
    (next) => {
      snapshot = next;
      liveLoaded = true;
      fault = "";
      render();
    },
    (next, error) => {
      status = next;
      if (error) fault = error;
      if (next === "signed-out") {
        liveLoaded = false;
      }
      render();
    },
  );
  try {
    await live.start();
  } catch (error) {
    fault = (error as Error).message;
    status = live.session ? "reconnecting" : "signed-out";
    render();
  }
}
async function action(target: HTMLElement): Promise<void> {
  if (target.hasAttribute("data-close")) {
    closeSheet();
    return;
  }
  if (target.hasAttribute("data-settings")) {
    settings();
    return;
  }
  if (target.hasAttribute("data-refresh")) {
    fault = "";
    if (!live) await configure();
    else await live.start();
    return;
  }
  if (target.hasAttribute("data-signout")) {
    await live?.signOut();
    closeSheet();
    notify("Signed out of this browser. Your badges stay connected.");
    return;
  }
  requireWritable();
  if (target.dataset.new) edit(target.dataset.new as Kind);
  else if (target.dataset.edit)
    edit(target.dataset.edit as Kind, target.dataset.id);
  else if (target.hasAttribute("data-upload")) uploadDialog();
  else if (target.dataset.delete)
    openSheet(
      `<h2 id="sheet-title">Remove ${e(target.dataset.delete)}?</h2><p>This removes the item from your shared household.</p><div class="form-actions"><button class="button" data-close>Cancel</button><button class="button danger" data-confirm-delete="${e(target.dataset.delete)}" data-id="${e(target.dataset.id || "")}">Remove</button></div>`,
    );
  else if (target.dataset.confirmDelete) {
    const kind = target.dataset.confirmDelete as Kind,
      id = target.dataset.id!;
    if (
      kind === "person" &&
      (snapshot.events.some((x) => x.people.includes(id)) ||
        snapshot.chores.some((x) => x.who === id || x.done_by === id))
    )
      throw new Error(
        "This person still has events or chores. Reassign or remove those first.",
      );
    await live!.remove(kind, id);
    closeSheet();
    notify("Removed from your household.");
  }
}
function showError(error: unknown, form?: HTMLFormElement): void {
  const message = error instanceof Error ? error.message : String(error);
  const field =
    form?.querySelector(".form-error") ||
    (sheet.open && sheet.querySelector(".form-error"));
  if (field) field.textContent = message;
  else notify(message);
}
document.addEventListener("click", (event) => {
  const target = (event.target as Element).closest<HTMLButtonElement>("button");
  if (!target || (target.type === "submit" && target.form)) return;
  void action(target).catch(showError);
});
document.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target as HTMLFormElement;
  const submitter = (event as SubmitEvent)
    .submitter as HTMLButtonElement | null;
  const buttons = [
    ...form.querySelectorAll<HTMLButtonElement>('button[type="submit"]'),
  ];
  buttons.forEach((b) => (b.disabled = true));
  void (async () => {
    if (form.dataset.save) await submitEdit(form);
    else if (form.hasAttribute("data-photo-upload")) await submitUpload(form);
    else if (form.hasAttribute("data-auth")) {
      const values = new FormData(form);
      if (submitter?.value === "signup") {
        const active = await live!.signUp(
          String(values.get("email")),
          String(values.get("password")),
        );
        if (!active) {
          closeSheet();
          notify("Check your email to finish creating your account.");
          return;
        }
      } else
        await live!.signIn(
          String(values.get("email")),
          String(values.get("password")),
        );
      closeSheet();
      notify("Signed in to your household.");
    } else if (form.hasAttribute("data-member")) {
      requireWritable();
      const values = new FormData(form);
      const password = String(values.get("password") || "");
      // Do not leave another person's password in the owner browser after a request.
      (form.elements.namedItem("password") as HTMLInputElement).value = "";
      const confirmation = await live!.linkMember(
        String(values.get("email")),
        String(values.get("person_id")),
        password,
      );
      notify(
        confirmation
          ? "Login linked. Confirm the email, then sign in on the badge."
          : "Login linked. This member can sign in on their badge.",
      );
    }
  })()
    .catch((error) => showError(error, form))
    .finally(() => buttons.forEach((b) => (b.disabled = false)));
});
sheet.addEventListener("cancel", () => {
  sheet.innerHTML = "";
});
window.addEventListener("focus", () => {
  void live?.refresh();
});
window.addEventListener("pagehide", () => {
  void live?.stop();
});
void configure();
