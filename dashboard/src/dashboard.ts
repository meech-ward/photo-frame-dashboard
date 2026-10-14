import "../js/main.js";
import "./dashboard.css";
import { HomeHQBackend, loadConfig, type LiveStatus } from "./backend";
import {
  householdDate,
  projectSnapshot,
  type OriginalSamples,
} from "./dashboard-data";
import { wallTimeEpoch } from "./utils";
import type { Snapshot, Chore, Shopping, Config } from "./types";

declare global {
  interface Window {
    App: any;
    DATA: any;
  }
}
const app = window.App;
const data = window.DATA;
const samples: OriginalSamples = JSON.parse(JSON.stringify(data));
let config: Config | null = null;
let configurationError = "";
try {
  config = loadConfig();
} catch (error) {
  configurationError = error instanceof Error ? error.message : String(error);
}
const gate = document.querySelector<HTMLDivElement>("#homehq-gate")!;
const gateMessage = document.querySelector<HTMLParagraphElement>(
  "#homehq-gate-message",
)!;
const statusLabel = document.querySelector<HTMLSpanElement>("#homehq-status")!;
let snapshot: Snapshot | null = null;
let backend: HomeHQBackend | null = null;
let status: LiveStatus = "connecting";
let saving = false;
const deviceIds = new Map<string, string>();

function renderStatus(error = ""): void {
  gate.hidden = !configurationError && (!config || !!snapshot);
  document.querySelector<HTMLElement>("#stage")!.style.visibility = gate.hidden
    ? ""
    : "hidden";
  const name = snapshot?.people.find(
    (p) => p.id === snapshot?.viewer?.person_id,
  )?.name;
  statusLabel.textContent = configurationError
    ? "App configuration error"
    : !config
      ? "Original prototype · local only"
      : status === "signed-out"
        ? "Sign in"
        : status === "live"
          ? `Live sync${name ? ` · ${name}` : ""}`
          : snapshot
            ? "Reconnecting"
            : "Connecting";
  gateMessage.textContent =
    configurationError ||
    error ||
    (status === "signed-out"
      ? "Sign in with your family account to load your household."
      : "Connecting to your household.");
  statusLabel.title = error;
}

function applySnapshot(next: Snapshot): void {
  snapshot = next;
  const projected = projectSnapshot(next, samples, Date.now() / 1000);
  deviceIds.clear();
  // The original security summary addresses its first garage and lock by ID.
  // Alias only presentation; writes use the household's actual row IDs.
  let garage = false,
    lock = false;
  for (const device of projected.devices) {
    const sourceId = device.id;
    if (device.type === "garage" && !garage) {
      device.id = "g-door";
      garage = true;
    }
    if (device.type === "lock" && !lock) {
      device.id = "e-door";
      lock = true;
    }
    deviceIds.set(device.id, sourceId);
  }
  if (!garage)
    projected.devices.push({
      id: "g-door",
      room: "",
      type: "garage",
      name: "Garage not configured",
      state: "closed",
      sample: true,
    });
  Object.assign(data, projected);
  data._gid = () => `g-${crypto.randomUUID()}`;
  data._eid = () => `e-${crypto.randomUUID()}`;
  if (!app.started && document.readyState !== "loading") app.start();
  if (app.started) {
    app.emit("data");
    app.go(app.current || "home", { rerender: true });
  }
  renderStatus();
}

async function save(
  work: (client: HomeHQBackend) => Promise<unknown>,
): Promise<boolean> {
  if (!backend || !snapshot || status !== "live" || saving) {
    app.toast(
      saving
        ? "Finishing the previous change."
        : "Wait for your Supabase connection before saving.",
    );
    return false;
  }
  saving = true;
  try {
    await work(backend);
    return true;
  } catch (error) {
    app.toast(app.esc(error instanceof Error ? error.message : String(error)), {
      tone: "error",
    });
    return false;
  } finally {
    saving = false;
  }
}
async function setDone(
  kind: "chore" | "shopping",
  id: string,
  done: boolean,
): Promise<void> {
  await save(async (client) => {
    const row = (kind === "chore" ? snapshot!.chores : snapshot!.shopping).find(
      (item) => item.id === id,
    );
    if (!row) throw new Error("This item has changed. Refresh the dashboard.");
    const previous = row.done;
    const by =
      kind === "chore" && done
        ? (row as Chore).who === "any"
          ? snapshot!.viewer?.person_id || null
          : (row as Chore).who
        : null;
    if (kind === "chore" && done && !by)
      throw new Error(
        "Link your account to a family member in Settings first.",
      );
    if ((await client.setDone(kind, row, done, by)) === "conflict") {
      app.toast(
        "This item changed on another screen. The latest version is shown.",
      );
      return;
    }
    app.toast(
      `${app.esc(kind === "chore" ? (row as Chore).title : (row as Shopping).name)} ${done ? "done" : "added back"}`,
      {
        icon: "check",
        undo: () => {
          void setDone(kind, id, previous);
        },
      },
    );
  });
}

if (config || configurationError) {
  document.body.dataset.homehqLive = "true";
  for (const key of ["people", "events", "chores", "groceries", "photos"])
    data[key] = [];
  // This is the only integration seam. Native views call named actions directly;
  // the provider never replaces methods or intercepts unrelated DOM events.
  app.dataSource = {
    ready: () => !!snapshot && !configurationError,
    now: () =>
      snapshot ? householdDate(snapshot, Date.now() / 1000) : new Date(),
    setDone,
    addShopping: (name: string, selectedStore: string) =>
      save(async (client) => {
        name = name.trim();
        if (!name) return;
        const existing = snapshot!.shopping.find(
          (g) => g.name.toLowerCase() === name.toLowerCase(),
        );
        if (existing) {
          if (existing.done)
            await client.setDone("shopping", existing, false, null);
          else
            await client.save("shopping", {
              ...existing,
              quantity: existing.quantity + 1,
            });
        } else {
          const sample = samples.catalog?.find(
            ([title]) => title.toLowerCase() === name.toLowerCase(),
          );
          const store =
            data.stores.find((s: any) => s.id === selectedStore)?.sourceName ||
            snapshot!.shopping[0]?.store ||
            "Grocer";
          await client.save("shopping", {
            id: `g-${crypto.randomUUID()}`,
            name,
            category: sample?.[1] || "Other",
            store,
            quantity: 1,
            note: "",
            done: false,
            version: 0,
          });
        }
        app.toast("Saved to your household.", { icon: "cart" });
      }),
    quantityShopping: (id: string, quantity: number) =>
      save(async (client) => {
        const row = snapshot!.shopping.find((item) => item.id === id);
        if (!row) throw new Error("This item no longer exists.");
        await client.save("shopping", { ...row, quantity });
      }),
    clearShopping: (ids: string[]) =>
      save(async (client) => {
        for (const id of ids) await client.remove("shopping", id);
        app.toast("Checked items cleared.", { icon: "check" });
      }),
    saveEvent: (event: {
      id: string;
      title: string;
      start: Date;
      end: Date;
      people: string[];
    }) =>
      save(async (client) => {
        // The original form holds household wall time, not the browser timezone.
        const epoch = (d: Date) =>
          wallTimeEpoch(
            `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
            snapshot!.home.timezone,
          );
        await client.save("event", {
          ...event,
          start: epoch(event.start),
          end: epoch(event.end),
          loc: "",
          notes: "",
          travel: 0,
          all_day: false,
        });
        app.toast("Event saved to your household.", {
          icon: "calendar",
          undo: () => {
            void save((client) => client.remove("event", event.id));
          },
        });
      }),
    setDevice: (alias: string, patch: Record<string, unknown>) =>
      save(async (client) => {
        const device = snapshot!.devices?.find(
          (d) => d.id === deviceIds.get(alias),
        );
        if (!device) throw new Error("This device is not configured.");
        if ((await client.setDevice(device, patch)) === "conflict")
          app.toast(
            "This device changed elsewhere. The latest state is shown.",
          );
      }),
    bulkDevices: (kind: "lights" | "locks") =>
      save(async (client) => {
        for (const device of (snapshot!.devices || []).filter((d) =>
          kind === "lights" ? d.type === "light" && d.on : d.type === "lock",
        )) {
          await client.setDevice(
            device,
            kind === "lights" ? { on: false } : { locked: true },
          );
        }
      }),
  };
}
if (config) {
  backend = new HomeHQBackend(config, applySnapshot, (nextStatus, error) => {
    status = nextStatus;
    if (status === "signed-out") {
      snapshot = null;
      for (const key of ["people", "events", "chores", "groceries", "photos"])
        data[key] = [];
    }
    renderStatus(error);
  });
  void backend.start().catch((error) => {
    status = backend?.session ? "reconnecting" : "signed-out";
    renderStatus(String(error.message || error));
  });
  window.addEventListener("focus", () => {
    void backend?.refresh();
  });
  window.addEventListener("pagehide", () => {
    void backend?.stop();
  });
}
app.on("ready", renderStatus);
renderStatus();
