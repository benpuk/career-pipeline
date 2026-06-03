const state = { config: null, options: null, applications: [] };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function setStatus(message, tone = "muted") {
  const node = $("#appStatus");
  node.textContent = message || "";
  node.className = `app-status ${tone}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function showView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === name));
  $$("nav button").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  if (name === "dashboard") loadDashboard();
  if (name === "list") loadApplications();
}

async function loadConfig() {
  state.config = await api("/api/config");
  document.title = state.config.app.name;
  $("#appName").textContent = state.config.app.name;
  $("#appDescription").textContent = state.config.app.description;
  const exportLink = $("#csvExportLink");
  if (exportLink) exportLink.hidden = !state.config.features.enableCsvExport;
}

function emptyState(title, body, action = "") {
  return `
    <div class="empty-state">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(body)}</p>
      ${action}
    </div>
  `;
}

function renderKpis(kpis) {
  const labels = [
    ["Active applications", kpis.active],
    ["Interview progress", kpis.interviews],
    ["Response rate", pct(kpis.response_rate)],
    ["Interview conversion", pct(kpis.interview_conversion_rate)],
    ["Ghosting risk", kpis.ghosting_risk],
    ["Closed ghosted", kpis.ghosted],
    ["Rejections", kpis.rejections + kpis.post_interview_rejections],
    ["Offers", kpis.offers],
    ["This week", kpis.applications_this_week],
    ["Pipeline health", pct(kpis.pipeline_health)],
  ];
  $("#kpis").innerHTML = labels.map(([label, value]) => `<div class="kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function renderBars(selector, rows, labelKey = "label", valueKey = "value", options = {}) {
  const targetNode = $(selector);
  if (!rows.length) {
    targetNode.innerHTML = emptyState("No data yet", "Add applications to see this trend.");
    return;
  }
  const max = Math.max(1, ...rows.map((row) => Number(row[valueKey]) || 0), ...(options.targets || []));
  targetNode.innerHTML = rows.map((row) => {
    const value = Number(row[valueKey]) || 0;
    const target = row.target;
    return `
      <div class="bar-row">
        <div class="bar-label">${escapeHtml(row[labelKey])}</div>
        <div class="bar-track" aria-hidden="true">
          <div class="bar-fill" style="width:${Math.max(2, value / max * 100)}%"></div>
          ${target ? `<div class="bar-fill target" style="width:${Math.max(2, target / max * 100)}%; margin-top:-16px"></div>` : ""}
        </div>
        <div>${options.percent ? pct(value) : escapeHtml(value)}</div>
      </div>`;
  }).join("");
}

function tableRows(rows, cells, emptyTitle, emptyBody) {
  if (!rows.length) {
    return `<tr><td colspan="${cells.length}">${emptyState(emptyTitle, emptyBody)}</td></tr>`;
  }
  return rows.map((row) => `<tr>${cells.map((cell) => `<td>${cell(row)}</td>`).join("")}</tr>`).join("");
}

async function loadDashboard() {
  setStatus("Loading dashboard...");
  try {
    const data = await api("/api/dashboard");
    renderKpis(data.kpis);
    renderBars("#weeklyChart", data.weekly.map((row) => ({ label: row.week, value: row.applications, target: row.target })), "label", "value", { targets: [25] });
    renderBars("#forecastChart", data.forecast.map((row) => ({ label: row.outcome, value: row.percent })), "label", "value", { percent: true });
    renderBars("#statusChart", data.status_breakdown.filter((row) => row.value > 0));
    renderBars("#ageingChart", data.ageing.filter((row) => row.value > 0));

    $("#bestRoute").textContent = data.kpis.total
      ? `Strongest traction: ${data.best_route.route} (${pct(data.best_route.traction)} traction)`
      : "Add applications to compare pipeline traction by route.";

    $("#cvRouteRows").innerHTML = tableRows(data.cv_routes, [
      (row) => escapeHtml(row.route),
      (row) => escapeHtml(row.applications),
      (row) => escapeHtml(row.avg_fit),
      (row) => pct(row.interview_rate),
      (row) => pct(row.rejection_rate),
      (row) => pct(row.ghosting_rate),
      (row) => pct(row.traction),
    ], "No route data yet", "Add applications with a route to compare what is working.");

    $("#roleTypeRows").innerHTML = tableRows(data.role_types, [
      (row) => escapeHtml(row.role_type),
      (row) => escapeHtml(row.applications),
      (row) => escapeHtml(row.avg_fit),
      (row) => pct(row.interview_rate),
      (row) => pct(row.rejection_rate),
      (row) => pct(row.ghosting_rate),
      (row) => pct(row.traction),
    ], "No role type data yet", "Role type insights appear after applications are added.");

    $("#followupRows").innerHTML = tableRows(data.priority_followups, [
      (row) => escapeHtml(row.company),
      (row) => `<button type="button" class="link-button" onclick="openDetail(${row.id})">${escapeHtml(row.role_title)}</button>`,
      (row) => escapeHtml(row.days_active),
      (row) => statusPill(row.status),
      (row) => escapeHtml(row.fit_score || ""),
      (row) => escapeHtml(row.suggested_action),
    ], "No follow-ups due", "Follow-up prompts appear when active applications need attention.");
    setStatus("");
  } catch (error) {
    setStatus("Dashboard could not be loaded. Check the local server and try again.", "error");
  }
}

function statusPill(status) {
  const label = status || "";
  let cls = "neutral";
  if (label.includes("Ghost")) cls = "ghost";
  if (label.includes("Offer")) cls = "good";
  if (label.includes("Interview")) cls = "warn";
  if (label.includes("Rejected") || label.includes("Withdrawn")) cls = "closed";
  return `<span class="status-pill ${cls}">${escapeHtml(label)}</span>`;
}

async function loadApplications() {
  const params = new URLSearchParams();
  if ($("#search").value) params.set("q", $("#search").value);
  if ($("#statusFilter").value) params.set("status", $("#statusFilter").value);
  if ($("#routeFilter").value) params.set("cv_route", $("#routeFilter").value);
  setStatus("Loading applications...");
  try {
    state.applications = await api(`/api/applications?${params}`);
    $("#applicationRows").innerHTML = tableRows(state.applications, [
      (app) => escapeHtml(app.company),
      (app) => `<button type="button" class="link-button" onclick="openDetail(${app.id})">${escapeHtml(app.role_title)}</button>`,
      (app) => statusPill(app.status),
      (app) => escapeHtml(app.date_applied),
      (app) => escapeHtml(app.days_active),
      (app) => escapeHtml(app.cv_route || ""),
      (app) => escapeHtml(app.fit_score || ""),
      (app) => escapeHtml(app.location || ""),
      (app) => escapeHtml(app.salary || ""),
      (app) => escapeHtml(app.source || ""),
      (app) => app.ghosting_risk ? statusPill("Review ghosting") : "",
      (app) => escapeHtml(app.next_action || ""),
    ], "No applications yet", "Add your first role to start building a clear job-search pipeline.");
    setStatus("");
  } catch (error) {
    setStatus("Applications could not be loaded. Check the local server and try again.", "error");
  }
}

async function openDetail(id) {
  const app = await api(`/api/applications/${id}`);
  $("#detail").classList.remove("hidden");
  $("#detail").innerHTML = `
    <div class="form-actions">
      <button type="button" onclick="editApplication(${id})">Edit</button>
      <button type="button" onclick="$('#detail').classList.add('hidden')">Close</button>
    </div>
    <h2>${escapeHtml(app.role_title)} at ${escapeHtml(app.company)}</h2>
    <p class="muted">${escapeHtml(app.status)} · ${escapeHtml(app.cv_route || "No route")} · ${escapeHtml(app.days_active)} days active · ${app.ghosting_risk ? "Review for ghosting" : "No ghosting review needed"}</p>
    <div class="detail-grid">
      <div class="detail-block"><h2>Summary</h2><pre>${escapeHtml(summaryText(app))}</pre></div>
      <div class="detail-block"><h2>Contact</h2><pre>${escapeHtml(contactText(app))}</pre></div>
      <div class="detail-block"><h2>Role description</h2><pre>${escapeHtml(app.job_description || "")}</pre></div>
      <div class="detail-block"><h2>Notes</h2><pre>${escapeHtml(app.notes || "")}</pre></div>
      <div class="detail-block"><h2>Message sent</h2><pre>${escapeHtml(app.cover_letter || "")}</pre></div>
      <div class="detail-block"><h2>Timeline</h2><pre>${escapeHtml(app.timeline.map(item => `${item.event_date} - ${item.event_type}: ${item.details || ""}`).join("\\n"))}</pre></div>
      <div class="detail-block span-2"><h2>Interviews</h2><pre>${escapeHtml(app.interviews.map(interviewText).join("\\n\\n") || "No interviews recorded.")}</pre></div>
    </div>
  `;
}

function summaryText(app) {
  return [
    `Salary: ${app.salary || ""}`,
    `Location/work mode: ${app.location || ""} ${app.work_mode || ""}`,
    `Source: ${app.source || ""}`,
    `Role URL: ${app.job_url || ""}`,
    `Next action: ${app.next_action || ""}`,
    `Follow-up date: ${app.follow_up_date || ""}`,
    `Outcome date: ${app.outcome_date || ""}`,
    `Tags: ${app.tags || ""}`,
    `Contract flagged: ${app.contract_flag ? "Yes" : "No"}`,
  ].join("\\n");
}

function contactText(app) {
  return [
    `Contact: ${app.contact_name || ""}`,
    `Email: ${app.contact_email || ""}`,
    `Phone: ${app.contact_phone || ""}`,
    `Contact-led: ${app.contact_led ? "Yes" : "No"}`,
    `Last contact/update: ${app.last_contact_date || ""}`,
  ].join("\\n");
}

function interviewText(item) {
  return [
    `${item.stage_name} - ${item.scheduled_at || ""}`,
    `Interviewers: ${item.interviewer_names || ""}`,
    `Emails: ${item.interviewer_emails || ""}`,
    `Meeting: ${item.meeting_link || ""}`,
    `Prep: ${item.prep_notes || ""}`,
    `Questions: ${item.questions_asked || ""}`,
    `Feedback: ${item.feedback || ""}`,
    `Outcome: ${item.outcome || ""}`,
    `Follow-up sent: ${item.follow_up_sent ? "Yes" : "No"}`,
  ].join("\\n");
}

function editApplication(id) {
  const app = state.applications.find((item) => item.id === id);
  if (!app) return;
  showView("form");
  const form = $("#applicationForm");
  Object.entries(app).forEach(([key, value]) => {
    const field = form.elements[key];
    if (!field) return;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value || "";
  });
}

async function saveApplication(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.contact_led = form.elements.contact_led.checked;
  payload.contract_flag = form.elements.contract_flag.checked;
  const id = form.elements.id.value;
  setStatus("Saving application...");
  try {
    if (id) await api(`/api/applications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/applications", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    form.elements.date_applied.valueAsDate = new Date();
    showView("list");
    setStatus("Application saved.");
  } catch (error) {
    setStatus("Application could not be saved. Check required fields and try again.", "error");
  }
}

async function loadOptions() {
  state.options = await api("/api/options");
  const statusOptions = state.options.statuses.map((item) => `<option>${escapeHtml(item)}</option>`).join("");
  const routeOptions = state.options.cv_routes.map((item) => `<option>${escapeHtml(item)}</option>`).join("");
  $("#statusFilter").innerHTML += statusOptions;
  $("#routeFilter").innerHTML += routeOptions;
  $("#applicationForm").elements.status.innerHTML = statusOptions;
  $("#applicationForm").elements.cv_route.innerHTML = `<option></option>${routeOptions}`;
  $("#applicationForm").elements.date_applied.valueAsDate = new Date();
}

function initEvents() {
  $$("nav button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $("#applicationForm").addEventListener("submit", saveApplication);
  $("#resetForm").addEventListener("click", () => {
    $("#applicationForm").reset();
    $("#applicationForm").elements.date_applied.valueAsDate = new Date();
  });
  ["search", "statusFilter", "routeFilter"].forEach((id) => $(`#${id}`).addEventListener("input", loadApplications));
  $("#clearFilters").addEventListener("click", () => {
    $("#search").value = "";
    $("#statusFilter").value = "";
    $("#routeFilter").value = "";
    loadApplications();
  });
}

loadConfig().then(loadOptions).then(() => {
  initEvents();
  loadDashboard();
}).catch(() => {
  setStatus("Career Pipeline could not start. Check the local server and refresh.", "error");
});
