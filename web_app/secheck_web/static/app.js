/* SEC-Check Web App front end. No build step, no framework.
 *
 * Talks only to the Web App API (/webapp/v1). Enum values (materiality,
 * severity, urgency, claim state) are read from /openapi.json at startup, so
 * changing them in the spec changes the dropdowns without editing this file.
 *
 * data-testid attributes mark the elements the browser tests (ui_tests/) use.
 * Keep them when changing the markup so the tests keep finding things.
 */
"use strict";

const BASE = "/webapp/v1";
const state = { user: null, session: null, teams: [], users: [], enums: {}, logOpenFor: null, pendingNotice: null, firstRender: true };
const $ = (sel, root = document) => root.querySelector(sel);
const $main = $("#main");
const $notice = $("#notice");
const $announcer = $("#announcer");

// ------------------------------------------------------------------ utilities
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function label(value) {
  if (!value) return "—";
  const s = String(value).replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
function store(key, value) {
  try { value === undefined ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (_) { /* storage unavailable */ }
}
function recall(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function options(values, selected, blank) {
  const opts = blank !== undefined ? [`<option value="">${esc(blank)}</option>`] : [];
  return opts.concat(values.map(v => `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(label(v))}</option>`)).join("");
}
function teamChecks(name, checked = []) {
  return `<div class="checks">${state.teams.map(t =>
    `<label><input type="checkbox" name="${name}" value="${esc(t)}" data-testid="team-${esc(t)}"${checked.includes(t) ? " checked" : ""}> ${esc(t)}</label>`).join("")}</div>`;
}
/** Read a form into an object: drops empty strings, collects checkbox groups into arrays. */
function formData(form, arrays = []) {
  const out = {};
  for (const name of arrays) out[name] = [];
  for (const [key, value] of new FormData(form).entries()) {
    if (arrays.includes(key)) out[key].push(value);
    else if (value !== "") out[key] = value;
  }
  return out;
}
const weakId = ticketId => String(ticketId).split("_").slice(0, 2).join("_");

// ------------------------------------------------------------------ API + notices
async function api(method, path, body) {
  const headers = { "Accept": "application/json" };
  if (state.user) headers["X-User"] = state.user;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw Object.assign(new Error("The Web App is not reachable."), { data: { Error: "UPSTREAM_UNAVAILABLE", Message: "The Web App server is not reachable. Is run.py still running?" } });
  }
  const data = await res.json().catch(() => ({ Error: "UPSTREAM_UNAVAILABLE", Message: `Unexpected response (HTTP ${res.status}).` }));
  if (!res.ok) throw Object.assign(new Error(data.Message || "Request failed"), { data, status: res.status });
  return data;
}

function showNotice(kind, html) {
  $notice.className = `notice ${kind}`;
  $notice.innerHTML = html;
  $notice.hidden = false;
  if (kind === "error") $notice.focus();
}
function ok(message) { showNotice("ok", esc(message)); }
function fail(err) {
  const d = (err && err.data) || {};
  let html = `<span class="code">${esc(d.Error || "Error")}</span>${esc(d.Message || (err && err.message) || "Something went wrong.")}`;
  if (Array.isArray(d.Completed_Steps)) {
    html += `<div class="steps">Core API calls completed before this failed: ${d.Completed_Steps.length ? esc(d.Completed_Steps.join(", ")) : "none"}.</div>`;
  }
  showNotice("error", html);
}
function clearNotice() { $notice.hidden = true; }

/** Tell screen readers about a change that has no visible notice. */
function announce(message) {
  $announcer.textContent = "";
  setTimeout(() => { $announcer.textContent = message; }, 50);
}

/** Call when a view has rendered: sets the page title and, except on first load, moves focus
 *  to the view's <h1> so keyboard and screen-reader users land on the new content. */
function settle(title) {
  document.title = `${title} – SEC-Check`;
  $main.removeAttribute("aria-busy");
  if (state.firstRender) { state.firstRender = false; return; }
  const heading = $("h1", $main);
  if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus(); }
}

/** Wire a form: disable while submitting, report errors, run onDone on success. */
function onSubmit(form, handler) {
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const buttons = form.querySelectorAll("button");
    buttons.forEach(b => (b.disabled = true));
    try { await handler(form); } catch (err) { fail(err); } finally { buttons.forEach(b => (b.disabled = false)); }
  });
}

// ------------------------------------------------------------------ startup
async function init() {
  try {
    const spec = await fetch("/openapi.json").then(r => r.json());
    const s = spec.components.schemas;
    state.enums = {
      Materiality: s.Materiality_type.enum,
      Severity: s.Severity_type.enum,
      Urgency: s.Urgency_type.enum,
      Claim: s.Ticket_claim_type.enum,
    };
  } catch (e) {
    state.enums = { Materiality: ["MATERIAL", "IMMATERIAL", "UNDECIDED"], Severity: ["HIGH", "MEDIUM", "LOW", "UNDECIDED", "RESOLVED"], Urgency: ["URGENT", "NOT_URGENT", "UNDECIDED", "RESOLVED"], Claim: ["CLAIMED", "UNCLAIMED"] };
  }
  const select = $("#user-select");
  try {
    state.users = (await api("GET", "/dev/users")).Users;
  } catch (e) { state.users = []; }
  select.innerHTML = `<option value="">Choose a user</option>` +
    state.users.map(u => `<option value="${esc(u.User)}">${esc(u.User)} (${esc(u.Teams.join(", "))})</option>`).join("");
  select.addEventListener("change", async () => { await signIn(select.value); route(); });
  const saved = recall("secheck_user");
  if (saved && state.users.some(u => u.User === saved)) { select.value = saved; await signIn(saved); }
  checkHealth();
  window.addEventListener("hashchange", route);
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => clampText(document), 150); });
  route();
}

async function signIn(name) {
  state.user = name || null;
  state.session = null;
  store("secheck_user", name || undefined);
  // Cookie lets the API docs page (/docs) make signed-in requests too.
  document.cookie = name ? `secheck_session=${encodeURIComponent(name)}; path=/; SameSite=Strict`
                         : "secheck_session=; path=/; max-age=0";
  if (!name) return;
  try {
    state.session = await api("GET", "/session");
    state.teams = (await api("GET", "/teams")).Teams;
  } catch (e) { fail(e); }
}

async function checkHealth() {
  const el = $("#core-status");
  try {
    const h = await api("GET", "/health");
    el.textContent = h.Core_API_Reachable ? `Core API connected (${h.Core_API_URL})` : `Core API problem: ${h.Core_API_Detail}`;
  } catch (e) { el.textContent = "Web App health check failed."; }
}

// ------------------------------------------------------------------ routing
function route() {
  clearNotice();
  $main.setAttribute("aria-busy", "true");
  // A message set just before navigating (e.g. "Incident created") is shown on the new page.
  if (state.pendingNotice) { ok(state.pendingNotice); state.pendingNotice = null; }
  const parts = (location.hash || "#/incidents").replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const page = parts[0] || "incidents";
  document.querySelectorAll("[data-nav]").forEach(a => a.toggleAttribute("aria-current", false));
  const nav = $(`[data-nav="${page}"]`);
  if (nav) nav.setAttribute("aria-current", "page");
  if (!state.user) return viewSignIn();
  if (page === "incidents" && parts[1]) return viewIncident(parts[1]);
  if (page === "queue") return viewQueue();
  if (page === "dependencies") return viewDependencies();
  return viewIncidents();
}

function viewSignIn() {
  $main.innerHTML = `<div class="empty" data-testid="signin-prompt"><h1>Choose who you are</h1>
    <p>Pick a user in the top bar to start. Sign-in is a development stand-in until the team chooses an authentication method.</p></div>`;
  settle("Sign in");
}

// ------------------------------------------------------------------ incidents list + intake
/* Long descriptions show their first 3 lines (CSS .clamp). Where the text is cut,
   add a "Show more" button that expands it in place. data-no-toggle = clamp only. */
function clampText(root) {
  root.querySelectorAll(".clamp").forEach(el => {
    if (el.hasAttribute("data-no-toggle") || el.classList.contains("expanded")) return;
    const next = el.nextElementSibling;
    if (next && next.classList.contains("more-toggle")) return;
    if (el.scrollHeight <= el.clientHeight + 1) return;  // fits in 3 lines
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "more-toggle";
    btn.textContent = "Show more";
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", ev => {
      ev.stopPropagation();
      const open = el.classList.toggle("expanded");
      btn.textContent = open ? "Show less" : "Show more";
      btn.setAttribute("aria-expanded", String(open));
    });
    el.after(btn);
  });
}

async function viewIncidents() {
  $main.innerHTML = `
    <div class="page-head"><h1>Incidents</h1><button class="primary" id="new-btn" data-testid="new-incident" aria-expanded="false">Report an incident</button></div>
    <section class="panel" id="intake" hidden>
      <h2>Report an incident</h2>
      <form id="intake-form" data-testid="intake-form">
        <label>What happened? <textarea name="Description" maxlength="5000" required data-testid="intake-description"></textarea></label>
        <div class="row">
          <label>Third-party dependency <select name="Dependency_Name" id="dep-select" data-testid="intake-dependency"><option value="">None</option></select></label>
          <label>Discovered at <span class="hint">Leave blank to use now</span><input type="datetime-local" name="Timestamp" data-testid="intake-timestamp"></label>
          <label>Incident ID <span class="hint">Leave blank to generate one</span><input name="Incident_ID" inputmode="numeric" pattern="[0-9]+" data-testid="intake-id"></label>
        </div>
        <div class="row">
          <label>Materiality <select name="Materiality" data-testid="intake-materiality">${options(state.enums.Materiality, "UNDECIDED")}</select></label>
          <label>Severity <select name="Severity" data-testid="intake-severity">${options(state.enums.Severity, "UNDECIDED")}</select></label>
          <label>Urgency <select name="Urgency" data-testid="intake-urgency">${options(state.enums.Urgency, "UNDECIDED")}</select></label>
        </div>
        <div class="actions"><button class="primary" data-testid="intake-submit">Create incident</button><button type="button" id="cancel-intake" data-testid="intake-cancel">Cancel</button></div>
      </form>
    </section>
    <form class="inline-form" id="open-form" data-testid="open-form">
      <label>Open an incident by ID <input name="id" inputmode="numeric" pattern="[0-9]+" required data-testid="open-id"></label>
      <button data-testid="open-submit">Open</button>
    </form>
    <section id="list" data-testid="incident-list"><p class="muted">Loading incidents…</p></section>`;

  settle("Incidents");
  const intake = $("#intake"), newBtn = $("#new-btn");
  const toggle = show => { intake.hidden = !show; newBtn.setAttribute("aria-expanded", String(show)); if (show) $("textarea", intake).focus(); };
  newBtn.addEventListener("click", () => toggle(intake.hidden));
  $("#cancel-intake").addEventListener("click", () => toggle(false));
  onSubmit($("#open-form"), f => { location.hash = `#/incidents/${encodeURIComponent(f.id.value.trim())}`; });
  onSubmit($("#intake-form"), async f => {
    const body = formData(f);
    if (body.Timestamp) body.Timestamp = new Date(body.Timestamp).toISOString();
    const created = await api("POST", "/incidents", body);
    state.pendingNotice = `Incident ${created.Incident_ID} created.`;
    location.hash = `#/incidents/${created.Incident_ID}`;
  });

  api("GET", "/dependencies").then(d => {
    $("#dep-select").innerHTML = `<option value="">None</option>` + d.Dependencies.map(n => `<option>${esc(n)}</option>`).join("");
  }).catch(() => {
    $("#dep-select").outerHTML = `<input name="Dependency_Name" placeholder="Dependency name">`;
  });

  const list = $("#list");
  list.setAttribute("aria-busy", "true");
  try {
    const data = await api("GET", "/incidents?page_size=100");
    list.removeAttribute("aria-busy");
    if (!data.Incidents.length) {
      list.innerHTML = `<div class="empty" data-testid="incidents-empty"><p>No incidents yet.</p><p>Use “Report an incident” to log the first one.</p></div>`;
      return;
    }
    list.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>Incident</th><th>Description</th><th>Materiality</th><th>Severity</th><th>Urgency</th><th>Discovered</th></tr></thead>
      <tbody>${data.Incidents.map(i => `
        <tr class="link" data-id="${esc(i.Incident_ID)}" data-testid="incident-row">
          <td class="num"><a href="#/incidents/${encodeURIComponent(i.Incident_ID)}" data-testid="incident-link">${esc(i.Incident_ID)}</a></td>
          <td class="desc"><div class="clamp" data-no-toggle>${esc(i.Description)}</div></td>
          <td class="state state-${esc(i.Materiality)}">${esc(label(i.Materiality))}</td>
          <td>${esc(label(i.Severity))}</td><td>${esc(label(i.Urgency))}</td>
          <td>${esc(fmtTime(i.Timestamp))}</td>
        </tr>`).join("")}</tbody></table></div>`;
    // The ID is a real link (keyboard and screen readers); clicking anywhere on the row also opens it.
    list.querySelectorAll("tr.link").forEach(tr => {
      tr.addEventListener("click", ev => { if (!ev.target.closest("a")) location.hash = `#/incidents/${tr.dataset.id}`; });
    });
  } catch (err) {
    list.removeAttribute("aria-busy");
    list.innerHTML = `<div class="empty"><p>The incident list isn't available: ${esc(err.data?.Message || err.message)}</p>
      <p>The Core API has no list operation yet (gap G-5). Open an incident by ID above.</p></div>`;
  }
}

// ------------------------------------------------------------------ incident detail
const BAND_WORD = { MATERIAL: "Material", IMMATERIAL: "Immaterial", UNDECIDED: "Materiality undecided" };

async function viewIncident(id) {
  $main.innerHTML = `<p class="muted">Loading incident ${esc(id)}…</p>`;
  let inc, tk;
  try {
    [inc, tk] = await Promise.all([api("GET", `/incidents/${encodeURIComponent(id)}`), api("GET", `/incidents/${encodeURIComponent(id)}/tickets?expand=true`)]);
  } catch (err) {
    $main.innerHTML = `<div class="empty"><h1>Incident ${esc(id)} could not be loaded</h1><p><a href="#/incidents">Back to incidents</a></p></div>`;
    settle("Incident not found");
    return fail(err);
  }
  const tickets = tk.Tickets || [];
  const canDecide = !state.session || state.session.Can_Decide;
  const myTeams = (state.session && state.session.Teams) || [];
  const material = inc.Materiality === "MATERIAL";
  const m = inc.Materiality in BAND_WORD ? inc.Materiality : "UNDECIDED";

  $main.innerHTML = `
    <p><a href="#/incidents" data-testid="back-to-incidents">All incidents</a></p>
    <h1 class="sr-only" data-testid="incident-heading">Incident ${esc(inc.Incident_ID)}: ${esc(BAND_WORD[m] || label(inc.Materiality))}</h1>
    <section class="band band-${m}" aria-label="Materiality determination" data-testid="incident-band">
      <div class="band-state" data-testid="incident-materiality">${esc(BAND_WORD[m] || label(inc.Materiality))}</div>
      <dl class="band-facts">
        <div><dt>Incident</dt><dd class="num" data-testid="incident-id">${esc(inc.Incident_ID)}</dd></div>
        <div><dt>Discovered</dt><dd>${esc(fmtTime(inc.Timestamp))}</dd></div>
        <div><dt>Severity</dt><dd data-testid="incident-severity">${esc(label(inc.Severity))}</dd></div>
        <div><dt>Urgency</dt><dd data-testid="incident-urgency">${esc(label(inc.Urgency))}</dd></div>
        <div><dt>Dependency</dt><dd data-testid="incident-dependency">${esc(inc.Dependency_Name || "None")}</dd></div>
      </dl>
    </section>
    <div class="cols">
      <div>
        <section class="panel">
          <h2>What happened</h2>
          <p class="clamp" data-testid="incident-description">${esc(inc.Description)}</p>
          <details><summary data-testid="edit-toggle">Edit details</summary>
            <form id="edit-form" data-testid="edit-form">
              <label>Description <textarea name="Description" maxlength="5000" required data-testid="edit-description">${esc(inc.Description)}</textarea></label>
              <label>Dependency <span class="hint">Leave blank for none</span><input name="Dependency_Name" value="${esc(inc.Dependency_Name || "")}" data-testid="edit-dependency"></label>
              <button class="primary" data-testid="edit-submit">Save details</button>
            </form>
          </details>
        </section>
        <section class="panel">
          <h2>Tickets</h2>
          ${tickets.length ? `<ol class="timeline" data-testid="ticket-list">${tickets.map(t => ticketItem(t, myTeams)).join("")}</ol>` : `<p class="muted" data-testid="tickets-empty">No tickets yet.</p>`}
        </section>
        <section class="panel">
          <h2>Log a ticket</h2>
          <form id="ticket-form" data-testid="ticket-form">
            <label>Details <textarea name="Description" maxlength="5000" required data-testid="ticket-description"></textarea></label>
            <div class="row">
              <label>Severity <select name="Ticket_severity" data-testid="ticket-severity">${options(state.enums.Severity, "", "Not set")}</select></label>
              <label>Urgency <select name="Ticket_urgency" data-testid="ticket-urgency">${options(state.enums.Urgency, "", "Not set")}</select></label>
            </div>
            <fieldset><legend>Assign to teams</legend>${teamChecks("Team_list")}</fieldset>
            <label class="checks"><input type="checkbox" name="Notify" value="yes" checked data-testid="ticket-notify"> Notify the assigned teams</label>
            <button class="primary" data-testid="ticket-submit">Log ticket</button>
          </form>
        </section>
        <section class="panel" id="form8k-panel" data-testid="form-8k" hidden></section>
      </div>
      <aside>
        <section class="panel">
          <h2>Record a decision</h2>
          ${canDecide ? "" : `<p class="muted">Your teams can't record decisions on this deployment.</p>`}
          <form id="decision-form" data-testid="decision-form">
            <label>Materiality <select name="Materiality" data-testid="decision-materiality">${options(state.enums.Materiality, inc.Materiality)}</select></label>
            <label>Severity <select name="Severity" data-testid="decision-severity">${options(state.enums.Severity, inc.Severity)}</select></label>
            <label>Urgency <select name="Urgency" data-testid="decision-urgency">${options(state.enums.Urgency, inc.Urgency)}</select></label>
            <label>Reason for this decision <span class="hint">Kept in the permanent log</span><textarea name="Rationale" maxlength="4000" required data-testid="decision-rationale"></textarea></label>
            <button class="primary" data-testid="decision-submit"${canDecide ? "" : " disabled"}>Record decision</button>
          </form>
        </section>
        <section class="panel">
          <h2>Form 8-K</h2>
          ${material ? `<p>Gather this incident's information by the parts of Item 1.05.</p>` : `<p class="muted">Available once the incident is marked material.</p>`}
          <button id="open-8k" data-testid="open-8k"${material ? "" : " disabled"}>Open 8-K view</button>
        </section>
      </aside>
    </div>
    <section class="panel full-log-panel">
      <details id="full-log" data-testid="full-log"${state.logOpenFor === inc.Incident_ID ? " open" : ""}>
        <summary data-testid="full-log-toggle">Full log (${tk.Ticket_ID_List.length} entries)</summary>
        <p class="muted">Every recorded version of every ticket, oldest first. Updating a ticket adds a new version; earlier versions stay here.</p>
        <div id="log-entries" data-testid="log-entries"><p class="muted">Loading entries…</p></div>
      </details>
    </section>`;

  settle(`Incident ${inc.Incident_ID}`);
  onSubmit($("#edit-form"), async f => {
    const body = formData(f);
    body.Dependency_Name = f.Dependency_Name.value.trim();
    if (body.Description === inc.Description) delete body.Description;
    if (body.Dependency_Name === (inc.Dependency_Name || "")) delete body.Dependency_Name;
    if (!Object.keys(body).length) return ok("Nothing changed.");
    await api("PATCH", `/incidents/${inc.Incident_ID}`, body);
    await viewIncident(id); ok("Details saved.");
  });
  onSubmit($("#decision-form"), async f => {
    const body = formData(f);
    const r = await api("PUT", `/incidents/${inc.Incident_ID}/decision`, body);
    await viewIncident(id);
    ok(`Decision recorded${r.Notified_Teams.length ? `; notified ${r.Notified_Teams.join(", ")}` : ""}.`);
  });
  onSubmit($("#ticket-form"), async f => {
    const body = formData(f, ["Team_list"]);
    body.Notify = f.Notify.checked;
    const r = await api("POST", `/incidents/${inc.Incident_ID}/tickets`, body);
    await viewIncident(id);
    ok(`Ticket ${r.Ticket_ID} logged${r.Notified_Teams.length ? `; notified ${r.Notified_Teams.join(", ")}` : ""}.`);
  });
  $("#open-8k").addEventListener("click", () => show8k(inc.Incident_ID).catch(fail));
  clampText($main);
  const fullLog = $("#full-log");
  const loadLog = () => showLogEntries(inc.Incident_ID);
  fullLog.addEventListener("toggle", () => {
    state.logOpenFor = fullLog.open ? inc.Incident_ID : null;
    if (fullLog.open) loadLog();
  });
  if (fullLog.open) loadLog();

  document.querySelectorAll("form[data-claim]").forEach(f => onSubmit(f, async () => {
    const r = await api("POST", `/tickets/${f.dataset.claim}/claim`, { Team_Name: f.Team_Name.value });
    await viewIncident(id); ok(`${r.Status} ${r.Ticket_Number} for ${f.Team_Name.value}.`);
  }));
  document.querySelectorAll("form[data-notify]").forEach(f => onSubmit(f, async () => {
    const teams = formData(f, ["Team_Names"]).Team_Names;
    await api("POST", `/tickets/${f.dataset.notify}/notify`, { Team_Names: teams });
    ok(`Notified ${teams.join(", ")} about ${f.dataset.notify}.`);
  }));
  document.querySelectorAll("form[data-edit]").forEach(f => onSubmit(f, async () => {
    const body = formData(f, ["Team_list"]);
    const r = await api("PATCH", `/incidents/${inc.Incident_ID}/tickets/${f.dataset.edit}`, body);
    await viewIncident(id); ok(`Saved as new version ${r.Ticket_ID}.`);
  }));
}

const ENTRY_KIND = { INTAKE: "Incident created", EDIT: "Details edited", DECISION: "Decision recorded" };

function entryKind(e) {
  if (!e.Details_Available) return e.Version > 1 ? `Ticket update, version ${e.Version}` : "Ticket";
  if (ENTRY_KIND[e.Entry_Type]) return ENTRY_KIND[e.Entry_Type];
  return e.Version > 1 ? `Ticket update, version ${e.Version}` : "New ticket";
}

async function showLogEntries(id) {
  const box = $("#log-entries");
  if (!box) return;
  try {
    const data = await api("GET", `/incidents/${encodeURIComponent(id)}/log/entries`);
    if (!data.Entries.length) { box.innerHTML = `<p class="muted">No log entries yet.</p>`; return; }
    box.innerHTML = `<div class="table-wrap"><table class="log-table">
      <thead><tr><th>#</th><th>Entry</th><th>Recorded</th><th>Details</th><th>Severity</th><th>Urgency</th><th>Teams</th></tr></thead>
      <tbody>${data.Entries.map((e, i) => `<tr class="${e.Entry_Type && e.Entry_Type !== "TICKET" ? "audit" : ""}" data-testid="log-entry" data-ticket-id="${esc(e.Ticket_ID)}">
        <td class="num">${i + 1}</td>
        <td><span class="num">${esc(e.Ticket_ID)}</span><br><span class="muted">${esc(entryKind(e))}</span></td>
        <td class="when">${esc(fmtTime(e.Timestamp))}</td>
        ${e.Details_Available
          ? `<td class="desc"><div class="clamp">${esc(e.Ticket_Description)}</div></td><td>${esc(label(e.ticket_severity))}</td><td>${esc(label(e.ticket_urgency))}</td><td>${esc((e.Team_List || []).join(", ") || "None")}</td>`
          : `<td colspan="4" class="muted">The Core API did not return this earlier version (it can only look up the latest version of a ticket).</td>`}
      </tr>`).join("")}</tbody></table></div>`;
    clampText(box);
  } catch (err) {
    box.innerHTML = `<p class="muted">The log entries could not be loaded: ${esc(err.data?.Message || err.message)}</p>`;
  }
}

function ticketItem(t, myTeams) {
  const number = weakId(t.Ticket_ID);
  const isAudit = /^(INTAKE|EDIT):|^DECISION by /.test(t.Ticket_Description || "");
  const claimed = t.Ticket_Claim === "CLAIMED";
  const claimTeams = myTeams.filter(x => state.teams.includes(x));
  return `<li class="ticket${isAudit ? " audit" : ""}" data-testid="ticket" data-ticket-id="${esc(t.Ticket_ID)}" data-ticket-number="${esc(number)}">
    <div class="ticket-head"><strong class="num">${esc(t.Ticket_ID)}</strong><span>${esc(fmtTime(t.Timestamp))}</span></div>
    <div class="ticket-body clamp" data-testid="ticket-body">${esc(t.Ticket_Description)}</div>
    ${isAudit ? "" : `<div class="meta">
      <span class="tag" data-testid="ticket-severity-tag">Severity: ${esc(label(t.ticket_severity))}</span>
      <span class="tag" data-testid="ticket-urgency-tag">Urgency: ${esc(label(t.ticket_urgency))}</span>
      ${(t.Team_List || []).map(x => `<span class="tag">${esc(x)}</span>`).join("")}
      ${t.Ticket_Claim ? `<span class="tag ${claimed ? "claimed" : "unclaimed"}" data-testid="ticket-claim">${claimed ? `Claimed${t.Claimed_By ? ` by ${esc(t.Claimed_By)}` : ""}` : "Unclaimed"}</span>` : ""}
    </div>
    <div class="actions">
      ${!claimed && claimTeams.length ? `<form class="inline-form" data-claim="${esc(number)}" data-testid="claim-form" style="margin:0">
        <select name="Team_Name" aria-label="Claim for team" data-testid="claim-team">${claimTeams.map(x => `<option>${esc(x)}</option>`).join("")}</select>
        <button data-testid="claim-submit">Claim</button></form>` : ""}
    </div>
    <details><summary data-testid="notify-toggle">Notify teams</summary>
      <form data-notify="${esc(number)}" data-testid="notify-form">${teamChecks("Team_Names")}<button data-testid="notify-submit">Notify teams</button></form>
    </details>
    <details><summary data-testid="update-toggle">Update ticket</summary>
      <form data-edit="${esc(number)}" data-testid="update-form">
        <label>Details <textarea name="Description" maxlength="5000" required data-testid="update-description">${esc(t.Ticket_Description)}</textarea></label>
        <div class="row">
          <label>Severity <select name="Ticket_severity" data-testid="update-severity">${options(state.enums.Severity, t.ticket_severity)}</select></label>
          <label>Urgency <select name="Ticket_urgency" data-testid="update-urgency">${options(state.enums.Urgency, t.ticket_urgency)}</select></label>
        </div>
        <fieldset><legend>Teams</legend>${teamChecks("Team_list", t.Team_List || [])}</fieldset>
        <button class="primary" data-testid="update-submit">Save new version</button>
      </form>
    </details>`}
  </li>`;
}

async function show8k(id) {
  const v = await api("GET", `/incidents/${encodeURIComponent(id)}/form-8k`);
  const item = v.Item_1_05;
  const panel = $("#form8k-panel");
  panel.hidden = false;
  panel.innerHTML = `
    <div class="page-head"><h2>Form 8-K, Item 1.05</h2><button id="copy-8k" data-testid="copy-8k">Copy as text</button></div>
    <p class="muted">A summary to help prepare the filing. It is not filed or completed automatically.</p>
    <div class="form8k">
      <section data-testid="8k-nature"><h3>Nature</h3><p class="clamp">${esc(item.Nature)}</p></section>
      <section data-testid="8k-scope"><h3>Scope</h3><dl>
        <dt>Severity</dt><dd>${esc(label(item.Scope.Severity))}</dd>
        <dt>Dependency</dt><dd>${esc(item.Scope.Dependency_Name || "None")}</dd>
        <dt>Teams involved</dt><dd>${esc((item.Scope.Teams_Involved || []).join(", ") || "None")}</dd></dl></section>
      <section data-testid="8k-timing"><h3>Timing</h3><dl>
        <dt>Discovered</dt><dd>${esc(fmtTime(item.Timing.Discovered_At))}</dd>
        <dt>Determined material</dt><dd>${esc(fmtTime(item.Timing.Determined_At))}</dd></dl>
        <ol>${item.Timing.Events.map(e => `<li><span class="num">${esc(e.Ticket_ID)}</span>, ${esc(fmtTime(e.Timestamp))}: ${esc(e.Summary)}</li>`).join("")}</ol></section>
      <section data-testid="8k-impact"><h3>Material impact</h3><p class="clamp">${esc(item.Material_Impact || "No rationale recorded.")}</p></section>
      <section data-testid="8k-filing"><h3>Filing</h3><dl>
        <dt>Determined at</dt><dd>${esc(fmtTime(v.Filing.Determined_At))}</dd>
        <dt>Filing deadline</dt><dd>${v.Filing.Filing_Deadline ? esc(fmtTime(v.Filing.Filing_Deadline)) : "Not provided by the Core API yet (four business days after determination)"}</dd></dl></section>
    </div>`;
  clampText(panel);
  const heading = $("h2", panel);   // move keyboard and screen-reader users to the view that just opened
  heading.setAttribute("tabindex", "-1");
  heading.focus({ preventScroll: true });
  $("#copy-8k").addEventListener("click", async () => {
    const text = [
      `Form 8-K Item 1.05 summary, incident ${v.Incident_ID}`,
      `Nature: ${item.Nature}`,
      `Scope: severity ${item.Scope.Severity}; dependency ${item.Scope.Dependency_Name || "none"}; teams ${(item.Scope.Teams_Involved || []).join(", ")}`,
      `Timing: discovered ${item.Timing.Discovered_At || "unknown"}; determined material ${item.Timing.Determined_At || "unknown"}`,
      ...item.Timing.Events.map(e => `  - ${e.Ticket_ID} ${e.Timestamp || ""}: ${e.Summary}`),
      `Material impact: ${item.Material_Impact}`,
      `Source tickets: ${v.Source_Tickets.join(", ")}`,
    ].join("\n");
    try { await navigator.clipboard.writeText(text); ok("8-K summary copied."); }
    catch (_) { fail({ data: { Error: "Copy failed", Message: "The browser blocked clipboard access." } }); }
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------------ team queue
async function viewQueue() {
  const mine = (state.session && state.session.Teams) || [];
  const ordered = mine.concat(state.teams.filter(t => !mine.includes(t)));
  const team = recall("secheck_queue_team") || ordered[0] || "";
  $main.innerHTML = `
    <div class="page-head"><h1>Team queue</h1></div>
    <form class="inline-form" id="queue-form" data-testid="queue-form">
      <label>Team <select name="team" data-testid="queue-team">${ordered.map(t => `<option${t === team ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
      <label>Show <select name="claim" data-testid="queue-claim">${options(state.enums.Claim, "UNCLAIMED")}</select></label>
      <button data-testid="queue-submit">Show tickets</button>
    </form>
    <section id="queue" data-testid="queue"></section>`;
  settle("Team queue");
  const form = $("#queue-form");
  const load = async () => {
    const t = form.team.value, c = form.claim.value;
    store("secheck_queue_team", t);
    const out = $("#queue");
    out.innerHTML = `<p class="muted">Loading…</p>`;
    out.setAttribute("aria-busy", "true");
    try {
      const q = await api("GET", `/queue?team=${encodeURIComponent(t)}&claim=${encodeURIComponent(c)}`);
      out.removeAttribute("aria-busy");
      if (!q.Tickets.length) {
        out.innerHTML = `<div class="empty" data-testid="queue-empty"><p>No ${esc(label(c).toLowerCase())} tickets for ${esc(t)}.</p></div>`;
        return;
      }
      const canClaim = mine.includes(t);
      out.innerHTML = `<div class="table-wrap"><table>
        <thead><tr><th>Ticket</th><th>Details</th><th>Severity</th><th>Urgency</th><th>Notified</th><th></th></tr></thead>
        <tbody>${q.Tickets.map(x => `<tr data-testid="queue-row" data-ticket-number="${esc(x.Ticket_number)}">
          <td class="num"><a href="#/incidents/${esc(x.Incident_ID)}">${esc(x.Ticket_number)}</a></td>
          <td class="desc"><div class="clamp" data-no-toggle>${esc(x.Ticket_Description)}</div></td>
          <td>${esc(label(x.ticket_severity))}</td><td>${esc(label(x.ticket_urgency))}</td>
          <td>${esc(fmtTime(x.Notified_At))}</td>
          <td>${x.Ticket_Claim === "CLAIMED" ? `Claimed by ${esc(x.Claimed_By || "a team")}`
            : canClaim ? `<button data-claim="${esc(x.Ticket_number)}" data-testid="queue-claim-button">Claim for ${esc(t)}</button>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>`;
      out.querySelectorAll("button[data-claim]").forEach(b => b.addEventListener("click", async () => {
        b.disabled = true;
        try { await api("POST", `/tickets/${b.dataset.claim}/claim`, { Team_Name: t }); ok(`Claimed ${b.dataset.claim} for ${t}.`); await load(); }
        catch (err) { b.disabled = false; fail(err); }
      }));
    } catch (err) {
      out.removeAttribute("aria-busy");
      out.innerHTML = `<div class="empty"><p>The team queue isn't available: ${esc(err.data?.Message || err.message)}</p></div>`;
    }
  };
  onSubmit(form, load);
  if (team) load();
}

// ------------------------------------------------------------------ dependencies
async function viewDependencies() {
  $main.innerHTML = `
    <div class="page-head"><h1>Dependencies</h1></div>
    <p class="muted">Third-party services the company relies on. Incidents can be linked to one of these.</p>
    <div class="cols">
      <section class="panel" id="dep-list" data-testid="dependency-list"><p class="muted">Loading…</p></section>
      <aside>
        <section class="panel"><h2>Add a dependency</h2>
          <form id="dep-add" data-testid="dep-add-form"><label>Name <input name="dp_name" required data-testid="dep-add-name"></label><button class="primary" data-testid="dep-add-submit">Add dependency</button></form>
        </section>
        <section class="panel"><h2>Check a dependency</h2>
          <form id="dep-check" data-testid="dep-check-form"><label>Name <input name="dp_name" required data-testid="dep-check-name"></label><button data-testid="dep-check-submit">Check</button></form>
          <p id="dep-check-result" class="muted" data-testid="dep-check-result"></p>
        </section>
      </aside>
    </div>`;
  settle("Dependencies");
  const loadList = async () => {
    const el = $("#dep-list");
    try {
      const d = await api("GET", "/dependencies");
      el.innerHTML = `<h2>Registered</h2>` + (d.Dependencies.length
        ? `<table><tbody>${d.Dependencies.map(n => `<tr data-testid="dependency-row" data-name="${esc(n)}"><td>${esc(n)}</td><td style="text-align:right"><button class="danger" data-remove="${esc(n)}" data-testid="dependency-remove">Remove</button></td></tr>`).join("")}</tbody></table>`
        : `<p class="muted" data-testid="dependencies-empty">None yet. Add the first one on the right.</p>`);
      el.querySelectorAll("button[data-remove]").forEach(b => b.addEventListener("click", async () => {
        if (b.dataset.armed !== "1") {
          b.dataset.armed = "1"; b.textContent = "Confirm remove";
          announce(`Press Confirm remove to remove ${b.dataset.remove}.`);
          return;
        }
        try { await api("DELETE", `/dependencies/${encodeURIComponent(b.dataset.remove)}`); ok(`Removed ${b.dataset.remove}.`); await loadList(); }
        catch (err) { fail(err); }
      }));
    } catch (err) {
      el.innerHTML = `<h2>Registered</h2><p class="muted">The list isn't available: ${esc(err.data?.Message || err.message)}</p>`;
    }
  };
  onSubmit($("#dep-add"), async f => {
    const r = await api("POST", "/dependencies", { dp_name: f.dp_name.value.trim() });
    f.reset(); ok(`${r.dp_name}: ${r.status}.`); await loadList();
  });
  onSubmit($("#dep-check"), async f => {
    const r = await api("GET", `/dependencies/${encodeURIComponent(f.dp_name.value.trim())}`);
    $("#dep-check-result").textContent = `${r.dp_name}: ${r.status}.`;
  });
  loadList();
}

init();
