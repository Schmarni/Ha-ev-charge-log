/*
 * EV Charge Log – form card
 * Log, edit and delete charging sessions outside evcc.
 *
 *   type: custom:ev-charge-log-card
 *   title: Ladevorgang unterwegs   # optional
 *   show_list: true                # optional, default true
 *   list_limit: 10                 # optional, default 10
 *   default_charge_type: DC        # optional, AC | DC
 *   config_entry_id: abc123        # optional, fixes the car when several are set up
 */

const CARD_VERSION = "0.5.0";
const DOMAIN = "ev_charge_log";

const I18N = {
  de: {
    title: "Ladevorgang unterwegs",
    location: "Ort",
    energy: "Energie",
    cost: "Kosten",
    price: "Preis pro kWh",
    type: "Ladeart",
    duration: "Ladedauer",
    waiting: "Wartezeit",
    date: "Datum & Uhrzeit",
    odometer: "Kilometerstand",
    odometer_hint: "leer = von evcc",
    note: "Notiz",
    more: "Weitere Angaben",
    save: "Speichern",
    update: "Änderungen speichern",
    cancel: "Abbrechen",
    saved: "Ladevorgang gespeichert",
    updated: "Ladevorgang geändert",
    deleted: "Ladevorgang gelöscht",
    confirm_delete: "Diesen Ladevorgang wirklich löschen?",
    list: "Erfasste Ladungen unterwegs",
    empty: "Noch keine Ladungen unterwegs erfasst.",
    required: "Bitte Ort, Energie und Kosten angeben.",
    editing: "Bearbeiten",
    min: "min",
    show_all: "Alle anzeigen",
    show_less: "Weniger anzeigen",
    error: "Fehler",
    vehicle: "Fahrzeug",
    start: "Ladevorgang starten",
    stop: "Beenden",
    abort: "Timer verwerfen",
    running: "Lädt seit",
    started: "Lade-Timer gestartet",
    stopped: "Ladedauer übernommen – jetzt kWh und Kosten eintragen",
    confirm_abort: "Laufenden Timer verwerfen?",
  },
  en: {
    title: "Public charging",
    location: "Location",
    energy: "Energy",
    cost: "Cost",
    price: "Price per kWh",
    type: "Charge type",
    duration: "Charging time",
    waiting: "Waiting time",
    date: "Date & time",
    odometer: "Odometer",
    odometer_hint: "empty = from evcc",
    note: "Note",
    more: "More details",
    save: "Save",
    update: "Save changes",
    cancel: "Cancel",
    saved: "Charging session saved",
    updated: "Charging session updated",
    deleted: "Charging session deleted",
    confirm_delete: "Really delete this charging session?",
    list: "Logged public sessions",
    empty: "No public charging sessions logged yet.",
    required: "Please enter location, energy and cost.",
    editing: "Editing",
    min: "min",
    show_all: "Show all",
    show_less: "Show less",
    error: "Error",
    vehicle: "Vehicle",
    start: "Start charging",
    stop: "Stop",
    abort: "Discard timer",
    running: "Charging for",
    started: "Charging timer started",
    stopped: "Charging time taken over – now enter kWh and cost",
    confirm_abort: "Discard the running timer?",
  },
};

const pad = (n) => String(n).padStart(2, "0");
const toLocalInput = (d) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class EvChargeLogCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sessions = [];
    this._odometer = null;
    this._editing = null;
    this._expanded = false;
    this._showAll = false;
    this._busy = false;
    this._loaded = false;
    this._entries = [];
    this._entryId = null;
  }

  static getStubConfig() {
    return { show_list: true, list_limit: 10 };
  }

  setConfig(config) {
    this._config = { show_list: true, list_limit: 10, default_charge_type: "DC", ...config };
    if (this._hass) this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._render();
      this._load();
      return;
    }
    const active = this._findActive();
    const key = active ? `${active.start}|${active.location || ""}` : "";
    if (key !== this._activeKey) {
      if (active && !this._editing && !this._dateTouched) {
        const el = this.shadowRoot.getElementById("date");
        if (el) el.value = toLocalInput(new Date(active.start));
      }
      this._render();
    }
  }

  connectedCallback() {
    this._tick = setInterval(() => this._updateTimer(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
  }

  _findActive() {
    if (!this._hass) return null;
    const entry = this._config.config_entry_id || this._entryId;
    for (const st of Object.values(this._hass.states)) {
      if (!st.entity_id.startsWith("binary_sensor.")) continue;
      const a = st.attributes || {};
      if (!("config_entry_id" in a) || !("start" in a)) continue;
      if (entry && a.config_entry_id !== entry) continue;
      return st.state === "on" && a.start ? { start: a.start, location: a.location } : null;
    }
    return null;
  }

  _elapsed(start) {
    const sec = Math.max(0, Math.floor((Date.now() - new Date(start).getTime()) / 1000));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return `${h}:${pad(m)}:${pad(s)}`;
  }

  _updateTimer() {
    const el = this.shadowRoot?.getElementById("elapsed");
    if (el && this._active) el.textContent = this._elapsed(this._active.start);
  }

  async _startTimer() {
    try {
      const location = this._val("location");
      await this._callService("start_timer", location ? { location } : {});
      this._toast(this._t.started);
    } catch (err) {
      this._showError(`${this._t.error}: ${err?.message || err}`);
    }
  }

  async _stopTimer() {
    try {
      const res = await this._callService("stop_timer", {}, true);
      const timer = res?.timer || {};
      this._editing = null;
      this._prefill = {
        location: this._val("location") || timer.location || "",
        date: timer.start ? toLocalInput(new Date(timer.start)) : toLocalInput(new Date()),
        duration: timer.duration ?? "",
      };
      this._clearForm = true;
      this._expanded = true;
      this._toast(this._t.stopped);
      this._render();
      this.shadowRoot.getElementById(this._prefill?.location ? "energy" : "location")?.focus();
    } catch (err) {
      this._showError(`${this._t.error}: ${err?.message || err}`);
    }
  }

  async _abortTimer() {
    if (!window.confirm(this._t.confirm_abort)) return;
    try {
      await this._callService("cancel_timer", {});
    } catch (err) {
      this._showError(`${this._t.error}: ${err?.message || err}`);
    }
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").split("-")[0];
    return I18N[lang] || I18N.en;
  }

  get _lang() {
    return this._hass?.locale?.language || this._hass?.language || "de";
  }

  _num(v, digits = 2) {
    return Number(v).toLocaleString(this._lang, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  async _callService(service, data, withResponse = false) {
    const entry = this._config.config_entry_id || this._entryId;
    const service_data = entry ? { ...data, config_entry_id: entry } : data;
    const msg = { type: "call_service", domain: DOMAIN, service, service_data };
    if (withResponse) msg.return_response = true;
    const res = await this._hass.connection.sendMessagePromise(msg);
    return res?.response;
  }

  async _loadEntries() {
    if (this._config.config_entry_id) return;
    try {
      this._entries = (await collectEvChargeLogEntities(this._hass)).map((g) => g.entry);
      if (!this._entries.length) {
        const entries = await this._hass.callWS({ type: "config_entries/get", domain: DOMAIN });
        this._entries = (entries || []).filter((e) => e.state === "loaded");
      }
      if (!this._entryId && this._entries.length) this._entryId = this._entries[0].entry_id;
    } catch (err) {
      this._entries = [];
    }
  }

  async _load() {
    if (!this._entries.length) await this._loadEntries();
    try {
      const res = await this._callService("list_sessions", {}, true);
      this._sessions = (res?.sessions || []).filter((s) => s.source === "manual");
      this._odometer = res?.odometer ?? null;
      this._loaded = true;
    } catch (err) {
      this._error = err?.message || String(err);
    }
    this._render();
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  _val(id) {
    const el = this.shadowRoot.getElementById(id);
    return el ? el.value.trim() : "";
  }

  _collect() {
    const data = {
      location: this._val("location"),
      energy: parseFloat(this._val("energy").replace(",", ".")),
      cost: parseFloat(this._val("cost").replace(",", ".")),
    };
    if (!data.location || !(data.energy > 0) || !(data.cost >= 0)) return null;
    const type = this.shadowRoot.querySelector(".seg button.active")?.dataset.value;
    if (type) data.charge_type = type;
    const opt = { duration: "duration", waiting: "waiting_time", odometer: "odometer" };
    for (const [id, key] of Object.entries(opt)) {
      const v = this._val(id).replace(",", ".");
      if (v !== "" && !isNaN(parseFloat(v))) data[key] = parseFloat(v);
    }
    const date = this._val("date");
    if (date) data.date = `${date.replace("T", " ")}:00`;
    const note = this._val("note");
    if (note) data.note = note;
    return data;
  }

  async _save() {
    if (this._busy) return;
    const data = this._collect();
    if (!data) {
      this._showError(this._t.required);
      return;
    }
    this._busy = true;
    this._render(true);
    try {
      if (this._editing) {
        await this._callService("update_session", { session_id: this._editing.id, ...data });
        this._toast(this._t.updated);
      } else {
        // a running timer belongs to this session: take start + duration over, then stop it
        const running = this._findActive();
        if (running) {
          const start = new Date(running.start);
          if (data.duration == null) data.duration = Math.max(1, Math.round((Date.now() - start.getTime()) / 60000));
          if (!this._dateTouched) data.date = `${toLocalInput(start).replace("T", " ")}:00`;
        }
        await this._callService("add_session", data);
        if (running) await this._callService("cancel_timer", {});
        this._toast(this._t.saved);
      }
      this._editing = null;
      this._expanded = false;
      this._clearForm = true;
      await this._load();
    } catch (err) {
      this._showError(`${this._t.error}: ${err?.message || err}`);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _delete(id) {
    if (!window.confirm(this._t.confirm_delete)) return;
    try {
      await this._callService("delete_session", { session_id: id });
      this._toast(this._t.deleted);
      if (this._editing?.id === id) this._editing = null;
      await this._load();
    } catch (err) {
      this._showError(`${this._t.error}: ${err?.message || err}`);
    }
  }

  _edit(id) {
    this._editing = this._sessions.find((s) => s.id === id) || null;
    this._expanded = true;
    this._render();
    this.shadowRoot.getElementById("location")?.focus();
    this.shadowRoot.querySelector("ha-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  _cancel() {
    this._editing = null;
    this._clearForm = true;
    this._render();
  }

  _showError(msg) {
    const el = this.shadowRoot.getElementById("error");
    if (el) {
      el.textContent = msg;
      el.hidden = false;
    }
  }

  _updatePrice() {
    const e = parseFloat(this._val("energy").replace(",", "."));
    const c = parseFloat(this._val("cost").replace(",", "."));
    const out = this.shadowRoot.getElementById("price");
    if (out) out.textContent = e > 0 && c >= 0 ? `${this._num(c / e, 3)} €/kWh` : "–";
  }

  _formValues() {
    // keep what the user typed across re-renders
    if (this._clearForm || !this.shadowRoot.getElementById("location")) {
      this._clearForm = false;
      const s = this._editing;
      if (s) {
        const dec = (1.5).toLocaleString(this._lang).charAt(1);
        const n = (x) => (x == null ? "" : String(x).replace(".", dec));
        return {
          location: s.location ?? "",
          energy: n(s.energy),
          cost: n(s.cost),
          type: s.charge_type || "",
          duration: s.duration ?? "",
          waiting: s.waiting_time ?? "",
          date: s.start ? toLocalInput(new Date(s.start)) : "",
          odometer: s.odometer ?? "",
          note: s.note ?? "",
        };
      }
      const running = this._findActive();
      this._dateTouched = false;
      const base = {
        location: running?.location || "", energy: "", cost: "", type: this._config.default_charge_type || "",
        duration: "", waiting: "", date: toLocalInput(running ? new Date(running.start) : new Date()),
        odometer: "", note: "",
      };
      const prefill = this._prefill;
      this._prefill = null;
      return prefill ? { ...base, ...prefill } : base;
    }
    const v = {};
    for (const id of ["location", "energy", "cost", "duration", "waiting", "date", "odometer", "note"]) v[id] = this._val(id);
    v.type = this.shadowRoot.querySelector(".seg button.active")?.dataset.value || "";
    if (this._editing && this._editingRendered !== this._editing.id) {
      this._editingRendered = this._editing.id;
      this._clearForm = true;
      return this._formValues();
    }
    return v;
  }

  _render(keepValues = false) {
    if (!this._config || !this._hass) return;
    const t = this._t;
    const v = this._formValues();
    if (this._editing) this._editingRendered = this._editing.id;
    else this._editingRendered = null;

    this._active = this._findActive();
    this._activeKey = this._active ? `${this._active.start}|${this._active.location || ""}` : "";
    const timerBlock = this._active
      ? `<div class="timer running">
           <div class="timer-info">
             <span class="pulse"></span>
             <div><div class="timer-label">${t.running}${this._active.location ? ` · ${esc(this._active.location)}` : ""}</div>
             <div class="timer-value" id="elapsed">${this._elapsed(this._active.start)}</div></div>
           </div>
           <button class="btn stop" id="stoptimer">■ ${t.stop}</button>
           <button class="icon" id="aborttimer" title="${t.abort}">✕</button>
         </div>`
      : (this._editing ? "" : `<button class="btn outline" id="starttimer">▶ ${t.start}</button>`);

    const locations = [...new Set(this._sessions.map((s) => s.location).filter(Boolean))];
    const sorted = [...this._sessions].sort((a, b) => (b.start || "").localeCompare(a.start || ""));
    const limit = this._showAll ? sorted.length : this._config.list_limit;
    const list = sorted.slice(0, limit);

    const row = (s) => {
      const d = s.start ? new Date(s.start) : null;
      const date = d ? d.toLocaleDateString(this._lang, { day: "2-digit", month: "2-digit", year: "2-digit" }) : "";
      const ppk = s.energy ? s.cost / s.energy : null;
      return `
        <div class="row ${this._editing?.id === s.id ? "editing" : ""}">
          <div class="row-main">
            <div class="row-title">${esc(s.location)}${s.charge_type ? `<span class="chip">${esc(s.charge_type)}</span>` : ""}</div>
            <div class="row-sub">${date} · ${this._num(s.energy, 1)} kWh · ${this._num(s.cost)} €${ppk != null ? ` · ${this._num(ppk, 3)} €/kWh` : ""}${s.waiting_time ? ` · ⏳ ${s.waiting_time} ${t.min}` : ""}</div>
          </div>
          <button class="icon" data-edit="${esc(s.id)}" title="${t.editing}">✎</button>
          <button class="icon danger" data-del="${esc(s.id)}" title="✕">🗑</button>
        </div>`;
    };

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { display: block; padding: 16px; }
        .head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
        .head .ic { font-size: 22px; }
        .head h2 { flex: 1; margin: 0; font-size: 18px; font-weight: 500; color: var(--primary-text-color); }
        .badge { font-size: 12px; padding: 2px 8px; border-radius: 10px; background: var(--warning-color, #ff9800); color: #fff; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .full { grid-column: 1 / -1; }
        label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--secondary-text-color); }
        .inp { position: relative; display: flex; align-items: center; }
        .vehicle { margin-bottom: 12px; }
        .btn.outline { width: 100%; margin-bottom: 14px; background: transparent; color: var(--primary-color);
                       border: 1px solid var(--primary-color); }
        .timer { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; padding: 10px 12px;
                 border-radius: 12px; background: rgba(var(--rgb-success-color, 76,175,80), .15);
                 border: 1px solid var(--success-color, #4caf50); }
        .timer-info { flex: 1; display: flex; align-items: center; gap: 10px; min-width: 0; }
        .timer-label { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .timer-value { font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--success-color, #4caf50);
                 animation: pulse 1.6s infinite; flex: 0 0 auto; }
        @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(76,175,80,.6); } 70% { box-shadow: 0 0 0 10px rgba(76,175,80,0); } 100% { box-shadow: 0 0 0 0 rgba(76,175,80,0); } }
        .btn.stop { flex: 0 0 auto; padding: 10px 14px; background: var(--error-color, #db4437); }
        input, textarea, select {
          width: 100%; box-sizing: border-box; font: inherit; font-size: 16px;
          padding: 10px 12px; border-radius: 8px;
          border: 1px solid var(--divider-color, #ccc);
          background: var(--secondary-background-color, transparent);
          color: var(--primary-text-color);
        }
        input:focus, textarea:focus { outline: none; border-color: var(--primary-color); }
        .unit { position: absolute; right: 12px; color: var(--secondary-text-color); font-size: 14px; pointer-events: none; }
        .inp input { padding-right: 48px; }
        .price { display: flex; justify-content: space-between; align-items: center; font-size: 13px;
                 color: var(--secondary-text-color); padding: 2px 2px 0; }
        .price b { color: var(--primary-text-color); font-weight: 500; }
        .seg { display: flex; border: 1px solid var(--divider-color, #ccc); border-radius: 8px; overflow: hidden; }
        .seg button { flex: 1; padding: 10px; border: 0; background: transparent; color: var(--primary-text-color); font: inherit; cursor: pointer; }
        .seg button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .toggle { background: none; border: 0; color: var(--primary-color); font: inherit; font-size: 14px; padding: 4px 0; cursor: pointer; text-align: left; }
        .actions { display: flex; gap: 8px; margin-top: 14px; }
        .btn { flex: 1; padding: 12px; border: 0; border-radius: 10px; font: inherit; font-size: 15px; font-weight: 500; cursor: pointer;
               background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .btn.secondary { flex: 0 0 auto; background: var(--secondary-background-color); color: var(--primary-text-color); }
        .btn[disabled] { opacity: .6; cursor: default; }
        .error { color: var(--error-color, #db4437); font-size: 13px; margin-top: 8px; }
        .list { margin-top: 18px; border-top: 1px solid var(--divider-color, #ddd); padding-top: 12px; }
        .list h3 { margin: 0 0 8px; font-size: 14px; font-weight: 500; color: var(--secondary-text-color); }
        .row { display: flex; align-items: center; gap: 4px; padding: 8px 4px; border-radius: 8px; }
        .row + .row { border-top: 1px solid var(--divider-color, #eee); }
        .row.editing { background: rgba(var(--rgb-primary-color, 3,169,244), .12); }
        .row-main { flex: 1; min-width: 0; }
        .row-title { font-size: 15px; color: var(--primary-text-color); display: flex; align-items: center; gap: 6px; }
        .row-sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .chip { font-size: 10px; padding: 1px 6px; border-radius: 6px; background: var(--secondary-background-color); color: var(--secondary-text-color); }
        .icon { background: none; border: 0; font-size: 18px; padding: 6px 8px; cursor: pointer; color: var(--secondary-text-color); border-radius: 8px; }
        .icon:hover { background: var(--secondary-background-color); }
        .empty { font-size: 13px; color: var(--secondary-text-color); }
        .more-link { margin-top: 6px; }
      </style>
      <ha-card>
        <div class="head">
          <span class="ic">⚡</span>
          <h2>${esc(this._config.title || t.title)}</h2>
          ${this._editing ? `<span class="badge">${t.editing}</span>` : ""}
        </div>
        ${timerBlock}
        ${this._entries.length > 1 && !this._config.config_entry_id ? `
        <label class="full vehicle">${t.vehicle}
          <select id="entry">${this._entries.map((e) => `<option value="${esc(e.entry_id)}" ${e.entry_id === this._entryId ? "selected" : ""}>${esc(e.title)}</option>`).join("")}</select>
        </label>` : ""}
        <div class="grid">
          <label class="full">${t.location}
            <input id="location" list="locs" autocomplete="off" value="${esc(v.location)}" placeholder="z. B. Lidl Pirna">
            <datalist id="locs">${locations.map((l) => `<option value="${esc(l)}">`).join("")}</datalist>
          </label>
          <label>${t.energy}
            <div class="inp"><input id="energy" inputmode="decimal" value="${esc(v.energy)}"><span class="unit">kWh</span></div>
          </label>
          <label>${t.cost}
            <div class="inp"><input id="cost" inputmode="decimal" value="${esc(v.cost)}"><span class="unit">€</span></div>
          </label>
          <div class="price full"><span>${t.price}</span><b id="price">–</b></div>
          <label class="full">${t.type}
            <div class="seg">
              ${["AC", "DC"].map((x) => `<button type="button" data-value="${x}" class="${v.type === x ? "active" : ""}">${x}</button>`).join("")}
            </div>
          </label>
          <label class="full">${t.date}
            <input id="date" type="datetime-local" value="${esc(v.date)}">
          </label>
          <button type="button" class="toggle full" id="toggle">${this._expanded ? "▾" : "▸"} ${t.more}</button>
          ${this._expanded ? `
          <label>${t.duration}
            <div class="inp"><input id="duration" inputmode="numeric" value="${esc(v.duration)}"><span class="unit">${t.min}</span></div>
          </label>
          <label>${t.waiting}
            <div class="inp"><input id="waiting" inputmode="numeric" value="${esc(v.waiting)}"><span class="unit">${t.min}</span></div>
          </label>
          <label class="full">${t.odometer}
            <div class="inp"><input id="odometer" inputmode="numeric" value="${esc(v.odometer)}" placeholder="${this._odometer ? `${Math.round(this._odometer)} (${t.odometer_hint})` : t.odometer_hint}"><span class="unit">km</span></div>
          </label>
          <label class="full">${t.note}
            <textarea id="note" rows="2">${esc(v.note)}</textarea>
          </label>` : `
          <input id="duration" type="hidden" value="${esc(v.duration)}">
          <input id="waiting" type="hidden" value="${esc(v.waiting)}">
          <input id="odometer" type="hidden" value="${esc(v.odometer)}">
          <input id="note" type="hidden" value="${esc(v.note)}">`}
        </div>
        <div id="error" class="error" ${this._error ? "" : "hidden"}>${esc(this._error || "")}</div>
        <div class="actions">
          ${this._editing ? `<button class="btn secondary" id="cancel">${t.cancel}</button>` : ""}
          <button class="btn" id="save" ${this._busy ? "disabled" : ""}>${this._editing ? t.update : t.save}</button>
        </div>
        ${this._config.show_list ? `
        <div class="list">
          <h3>${t.list} (${this._sessions.length})</h3>
          ${list.length ? list.map(row).join("") : `<div class="empty">${this._loaded ? t.empty : "…"}</div>`}
          ${sorted.length > this._config.list_limit ? `<button class="toggle more-link" id="showall">${this._showAll ? t.show_less : `${t.show_all} (${sorted.length})`}</button>` : ""}
        </div>` : ""}
      </ha-card>`;
    this._error = null;

    const root = this.shadowRoot;
    root.getElementById("save").addEventListener("click", () => this._save());
    root.getElementById("starttimer")?.addEventListener("click", () => this._startTimer());
    root.getElementById("stoptimer")?.addEventListener("click", () => this._stopTimer());
    root.getElementById("aborttimer")?.addEventListener("click", () => this._abortTimer());
    root.getElementById("entry")?.addEventListener("change", (ev) => {
      this._entryId = ev.target.value;
      this._editing = null;
      this._clearForm = true;
      this._load();
    });
    root.getElementById("cancel")?.addEventListener("click", () => this._cancel());
    root.getElementById("toggle").addEventListener("click", () => {
      this._expanded = !this._expanded;
      this._render();
    });
    root.getElementById("showall")?.addEventListener("click", () => {
      this._showAll = !this._showAll;
      this._render();
    });
    root.querySelectorAll(".seg button").forEach((b) =>
      b.addEventListener("click", () => {
        const wasActive = b.classList.contains("active");
        root.querySelectorAll(".seg button").forEach((x) => x.classList.remove("active"));
        if (!wasActive) b.classList.add("active");
      })
    );
    for (const id of ["energy", "cost"]) root.getElementById(id).addEventListener("input", () => this._updatePrice());
    root.getElementById("date").addEventListener("input", () => { this._dateTouched = true; });
    root.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => this._edit(b.dataset.edit)));
    root.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => this._delete(b.dataset.del)));
    this._updatePrice();
  }
}

if (!customElements.get("ev-charge-log-card")) {
  customElements.define("ev-charge-log-card", EvChargeLogCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ev-charge-log-card",
    name: "EV Charge Log",
    description: "Ladevorgänge unterwegs erfassen, bearbeiten und löschen",
    preview: false,
  });
  console.info(`%c EV-CHARGE-LOG-CARD %c ${CARD_VERSION} `, "color:#fff;background:#03a9f4", "color:#03a9f4");
}

/*
 * Dashboard strategy: builds a complete EV Charge Log dashboard from the
 * integration's entities (any language, any vehicle name, one tab per car).
 *
 *   strategy:
 *     type: custom:ev-charge-log
 */
const STRAT_I18N = {
  de: {
    vs: "{car} vs. Verbrenner", savings: "Ersparnis gesamt", per100: "Strom / 100 km", fuelPer100: "{fuel} / 100 km",
    costTotal: "Strom gesamt", fuelCost: "{fuel} wäre", distance: "Strecke", consumption: "Ø Verbrauch",
    price: "Ø Strompreis", sessions: "Ladevorgänge", wltp: "Verbrauch ggü. WLTP", range: "Reale Reichweite",
    month: "Diesen Monat", year: "Dieses Jahr", saved: "Ersparnis", cost: "Kosten", energy: "Energie",
    homeVsAway: "Daheim vs. unterwegs", eHome: "Energie daheim", eAway: "Energie unterwegs", cHome: "Kosten daheim",
    cAway: "Kosten unterwegs", pHome: "Ø Preis daheim", pAway: "Ø Preis unterwegs", tAway: "Ladezeit unterwegs",
    wAway: "Wartezeit unterwegs", env: "Umwelt", co2Saved: "CO₂-Ersparnis", co2Ev: "CO₂ E-Auto",
    co2Fuel: "CO₂ {fuel} wäre", solar: "Solaranteil daheim", monthly: "Monatsübersicht", recent: "Letzte Ladevorgänge",
    diesel: "Diesel", petrol: "Benzin", title: "EV-Ladebuch", empty: "Keine EV-Charge-Log-Einträge gefunden.",
    mCols: "| Monat | km | kWh | davon unterwegs | Kosten | {fuel} wäre | Ersparnis | kWh/100 km |",
    rCols: "| | Datum | Ort | kWh | Kosten | €/kWh | km | ☀️ |",
    legend: "🏠 = daheim (evcc) · ⚡ = unterwegs",
    months: "['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']",
  },
  en: {
    vs: "{car} vs. fuel car", savings: "Total savings", per100: "Electricity / 100 km", fuelPer100: "{fuel} / 100 km",
    costTotal: "Electricity total", fuelCost: "{fuel} would be", distance: "Distance", consumption: "Ø consumption",
    price: "Ø price", sessions: "Charging sessions", wltp: "Consumption vs. WLTP", range: "Real range",
    month: "This month", year: "This year", saved: "Savings", cost: "Cost", energy: "Energy",
    homeVsAway: "Home vs. public", eHome: "Energy at home", eAway: "Energy public", cHome: "Cost at home",
    cAway: "Cost public", pHome: "Ø price at home", pAway: "Ø price public", tAway: "Charging time public",
    wAway: "Waiting time public", env: "Environment", co2Saved: "CO₂ savings", co2Ev: "CO₂ electric car",
    co2Fuel: "CO₂ {fuel} would be", solar: "Solar share at home", monthly: "Monthly overview", recent: "Recent charging sessions",
    diesel: "Diesel", petrol: "Petrol", title: "EV Charge Log", empty: "No EV Charge Log entries found.",
    mCols: "| Month | km | kWh | public | Cost | {fuel} | Savings | kWh/100 km |",
    rCols: "| | Date | Location | kWh | Cost | €/kWh | km | ☀️ |",
    legend: "🏠 = home (evcc) · ⚡ = public",
    months: "['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']",
  },
};

const fmt = (s, vars) => s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");

function buildEvChargeLogView(hass, entry, ids, lang) {
  const T = STRAT_I18N[lang] || STRAT_I18N.en;
  const fuelFactor = hass.states[ids.co2_fuel]?.attributes?.kg_co2_per_litre;
  const fuel = fuelFactor && fuelFactor < 2.5 ? T.petrol : T.diesel;
  const v = { car: entry.title, fuel };
  const tile = (key, name, icon, columns = 6, color) =>
    ids[key]
      ? { type: "tile", entity: ids[key], name: fmt(name, v), icon: `mdi:${icon}`, grid_options: { columns }, ...(color ? { color } : {}) }
      : null;
  const head = (text, icon) => ({ type: "heading", heading: fmt(text, v), icon: `mdi:${icon}`, grid_options: { columns: "full" } });

  const stats = [
    head(T.vs, "piggy-bank-outline"),
    tile("savings", T.savings, "piggy-bank", 12, "green"),
    tile("cost_per_100km", T.per100, "cash"),
    tile("fuel_cost_per_100km", T.fuelPer100, "cash-remove"),
    tile("cost_total", T.costTotal, "lightning-bolt"),
    tile("fuel_cost", T.fuelCost, "gas-station", 6, "red"),
    tile("distance", T.distance, "map-marker-distance"),
    tile("consumption", T.consumption, "speedometer"),
    tile("price_avg", T.price, "currency-eur"),
    tile("sessions_total", T.sessions, "counter"),
    tile("wltp_deviation", T.wltp, "chart-bell-curve-cumulative"),
    tile("range_estimate", T.range, "map-marker-distance"),
    head(T.month, "calendar-month"),
    tile("savings_month", T.saved, "piggy-bank", 6, "green"),
    tile("cost_month", T.cost, "cash"),
    tile("energy_month", T.energy, "lightning-bolt"),
    tile("distance_month", T.distance, "map-marker-distance"),
    head(T.year, "calendar"),
    tile("savings_year", T.saved, "piggy-bank", 6, "green"),
    tile("cost_year", T.cost, "cash"),
    tile("energy_year", T.energy, "lightning-bolt"),
    head(T.homeVsAway, "home-lightning-bolt"),
    tile("energy_home", T.eHome, "home-lightning-bolt"),
    tile("energy_external", T.eAway, "ev-station"),
    tile("cost_home", T.cHome, "home"),
    tile("cost_external", T.cAway, "ev-station"),
    tile("price_avg_home", T.pHome, "currency-eur"),
    tile("price_avg_external", T.pAway, "currency-eur"),
    tile("charging_time_external", T.tAway, "timer-outline"),
    tile("waiting_time", T.wAway, "timer-sand"),
    head(T.env, "leaf"),
    tile("co2_savings", T.co2Saved, "leaf", 6, "green"),
    tile("co2_ev", T.co2Ev, "molecule-co2"),
    tile("co2_fuel", T.co2Fuel, "molecule-co2", 6, "red"),
    tile("solar_share_home", T.solar, "solar-power", 6, "amber"),
  ].filter(Boolean);

  const num = (expr, d) => `'%.${d}f' | format(${expr}) | replace('.', ',')`;
  const sections = [
    { type: "grid", column_span: 2, cards: stats },
    { type: "grid", cards: [{ type: "custom:ev-charge-log-card", config_entry_id: entry.entry_id, show_list: true, list_limit: 8 }] },
  ];
  if (ids.monthly_overview) {
    sections.push({
      type: "grid", column_span: 3,
      cards: [
        head(T.monthly, "table"),
        {
          type: "markdown", grid_options: { columns: "full" },
          content:
            `${fmt(T.mCols, v)}\n|:--|--:|--:|--:|--:|--:|--:|--:|\n` +
            `{% set mn = ${T.months} -%}\n` +
            `{% for m in (state_attr('${ids.monthly_overview}','months') or []) | reverse -%}\n` +
            `{% set p = m.month.split('-') -%}\n` +
            `| **{{ mn[p[1]|int - 1] }} {{ p[0] }}** | {{ m.km if m.km is not none else '–' }} | {{ ${num("m.energy", 1)} }} | {{ ${num("m.energy_external", 1)} }} | {{ ${num("m.cost", 2)} }} € | {{ (${num("m.fuel_cost", 2)}) ~ ' €' if m.fuel_cost is not none else '–' }} | **{{ (${num("m.savings", 2)}) ~ ' €' if m.savings is not none else '–' }}** | {{ (${num("m.consumption", 1)}) if m.consumption is not none else '–' }} |\n` +
            `{% endfor %}`,
        },
      ],
    });
  }
  if (ids.last_session) {
    sections.push({
      type: "grid", column_span: 3,
      cards: [
        head(T.recent, "history"),
        {
          type: "markdown", grid_options: { columns: "full" },
          content:
            `${T.rCols}\n|:-:|:--|:--|--:|--:|--:|--:|--:|\n` +
            `{% for s in (state_attr('${ids.last_session}','sessions') or [])[:15] -%}\n` +
            `{% set d = as_datetime(s.date) -%}\n` +
            `| {{ '🏠' if s.source == 'evcc' else '⚡' }} | {{ d.strftime('%d.%m.%y %H:%M') }} | {{ s.location }} | {{ ${num("s.energy", 1)} }} | {{ (${num("s.cost", 2)}) ~ ' €' if s.cost is not none else '–' }} | {{ (${num("s.price_per_kwh", 3)}) if s.price_per_kwh is not none else '–' }} | {{ s.odometer | int if s.odometer else '–' }} | {{ (s.solar_percentage | round(0) | int) ~ ' %' if s.solar_percentage is not none else '' }} |\n` +
            `{% endfor %}\n${T.legend}`,
        },
      ],
    });
  }
  return { title: entry.title, path: entry.entry_id.toLowerCase().slice(-8), icon: "mdi:ev-station", type: "sections", max_columns: 3, sections };
}

async function collectEvChargeLogEntities(hass) {
  // hass.entities / hass.devices work for non-admin users too (no registry WS calls)
  const groups = {};
  for (const ent of Object.values(hass.entities || {})) {
    if (ent.platform !== DOMAIN || !ent.translation_key || ent.hidden) continue;
    const device = hass.devices?.[ent.device_id];
    const entryId = device?.config_entries?.[0];
    if (!entryId) continue;
    const g = (groups[entryId] ||= {
      entry: { entry_id: entryId, title: device.name_by_user || device.name || "EV" },
      ids: {},
    });
    g.ids[ent.translation_key] = ent.entity_id;
  }
  return Object.values(groups).sort((a, b) => a.entry.title.localeCompare(b.entry.title));
}

class EvChargeLogDashboardStrategy {
  static async generate(config, hass) {
    const lang = (hass.locale?.language || hass.language || "en").split("-")[0];
    const T = STRAT_I18N[lang] || STRAT_I18N.en;
    const items = await collectEvChargeLogEntities(hass);
    if (!items.length) {
      return { title: T.title, views: [{ title: T.title, cards: [{ type: "markdown", content: T.empty }] }] };
    }
    return { title: T.title, views: items.map(({ entry, ids }) => buildEvChargeLogView(hass, entry, ids, lang)) };
  }
}

class EvChargeLogViewStrategy {
  static async generate(config, hass) {
    const lang = (hass.locale?.language || hass.language || "en").split("-")[0];
    const items = await collectEvChargeLogEntities(hass);
    const item = items.find((i) => i.entry.entry_id === config.config_entry_id) || items[0];
    if (!item) return { cards: [{ type: "markdown", content: (STRAT_I18N[lang] || STRAT_I18N.en).empty }] };
    const { title, path, icon, ...view } = buildEvChargeLogView(hass, item.entry, item.ids, lang);
    return view;
  }
}

if (!customElements.get("ll-strategy-dashboard-ev-charge-log")) {
  customElements.define("ll-strategy-dashboard-ev-charge-log", class extends HTMLElement {});
  customElements.get("ll-strategy-dashboard-ev-charge-log").generate = EvChargeLogDashboardStrategy.generate;
  customElements.define("ll-strategy-view-ev-charge-log", class extends HTMLElement {});
  customElements.get("ll-strategy-view-ev-charge-log").generate = EvChargeLogViewStrategy.generate;
  window.customStrategies = window.customStrategies || [];
  window.customStrategies.push({
    type: "ev-charge-log",
    strategyType: "dashboard",
    name: "EV Charge Log",
    description: "Ladebuch mit Kosten, Verbrauch und Verbrenner-Vergleich – automatisch für alle Fahrzeuge",
    documentationURL: "https://github.com/Schmarni/Ha-ev-charge-log",
  });
}
