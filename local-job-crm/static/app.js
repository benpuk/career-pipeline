const state = { config: null, options: null, applications: [] };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function showView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === name));
  $$("nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
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

function renderKpis(kpis) {
  const labels = [
    ["Total applications", kpis.total],
    ["Active applications", kpis.active],
    ["Interviews", kpis.interviews],
    ["Rejections", kpis.rejections],
    ["Ghosted", kpis.ghosted],
    ["Post-interview rejections", kpis.post_interview_rejections],
    ["Offers", kpis.offers],
    ["Applications this week", kpis.applications_this_week],
    ["Average days active", kpis.average_days_active],
    ["Pipeline health", pct(kpis.pipeline_health)],
  ];
  $("#kpis").innerHTML = labels.map(([label, value]) => `<div class="kpi"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderBars(selector, rows, labelKey = "label", valueKey = "value", options = {}) {
  const max = Math.max(1, ...rows.map((row) => Number(row[valueKey]) || 0), ...(options.targets || []));
  $(selector).innerHTML = rows.map((row) => {
    const value = Number(row[valueKey]) || 0;
    const target = row.target;
    return `
      <div class="bar-row">
        <div class="bar-label">${row[labelKey]}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${Math.max(2, value / max * 100)}%"></div>
          ${target ? `<div class="bar-fill target" style="width:${Math.max(2, target / max * 100)}%; margin-top:-16px"></div>` : ""}
        </div>
        <div>${options.percent ? pct(value) : value}</div>
      </div>`;
  }).join("");
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  renderKpis(data.kpis);
  renderBars("#weeklyChart", data.weekly.map((row) => ({ label: row.week, value: row.applications, target: row.target })), "label", "value", { targets: [25] });
  renderBars("#forecastChart", data.forecast.map((row) => ({ label: row.outcome, value: row.percent, expected: row.expected })), "label", "value", { percent: true });
  renderBars("#statusChart", data.status_breakdown);
  renderBars("#ageingChart", data.ageing);

  $("#bestRoute").textContent = data.best_route
    ? `Strongest traction: ${data.best_route.route} (${pct(data.best_route.traction)} traction)`
    : "No CV route performance data yet.";

  $("#cvRouteRows").innerHTML = data.cv_routes.map((row) => `
    <tr>
      <td>${row.route}</td>
      <td>${row.applications}</td>
      <td>${row.avg_fit}</td>
      <td>${pct(row.interview_rate)}</td>
      <td>${pct(row.rejection_rate)}</td>
      <td>${pct(row.ghosting_rate)}</td>
      <td>${pct(row.traction)}</td>
    </tr>
  `).join("");

  $("#roleTypeRows").innerHTML = data.role_types.map((row) => `
    <tr>
      <td>${row.role_type}</td>
      <td>${row.applications}</td>
      <td>${row.avg_fit}</td>
      <td>${pct(row.interview_rate)}</td>
      <td>${pct(row.rejection_rate)}</td>
      <td>${pct(row.ghosting_rate)}</td>
      <td>${pct(row.traction)}</td>
    </tr>
  `).join("");

  $("#followupRows").innerHTML = data.priority_followups.map((row) => `
    <tr>
      <td>${row.company}</td>
      <td><button class="link-button" onclick="openDetail(${row.id})">${row.role_title}</button></td>
      <td>${row.days_active}</td>
      <td>${statusPill(row.status)}</td>
      <td>${row.fit_score || ""}</td>
      <td>${row.suggested_action}</td>
    </tr>
  `).join("");
}

function statusPill(status, suggested = "") {
  const label = suggested || status || "";
  let cls = "";
  if (label.includes("Ghost")) cls = "ghost";
  if (label.includes("Offer")) cls = "good";
  if (label.includes("Interview") || label.includes("Screening")) cls = "warn";
  return `<span class="status-pill ${cls}">${label}</span>`;
}

async function loadApplications() {
  const params = new URLSearchParams();
  if ($("#search").value) params.set("q", $("#search").value);
  if ($("#statusFilter").value) params.set("status", $("#statusFilter").value);
  if ($("#routeFilter").value) params.set("cv_route", $("#routeFilter").value);
  state.applications = await api(`/api/applications?${params}`);
  $("#applicationRows").innerHTML = state.applications.map((app) => `
    <tr onclick="openDetail(${app.id})">
      <td>${app.company}</td>
      <td>${app.role_title}</td>
      <td>${statusPill(app.status)}</td>
      <td>${app.date_applied}</td>
      <td>${app.days_active}</td>
      <td>${app.cv_route || ""}</td>
      <td>${app.fit_score || ""}</td>
      <td>${app.location || ""}</td>
      <td>${app.salary || ""}</td>
      <td>${app.source || ""}</td>
      <td>${app.ghosting_risk ? statusPill("Review ghosting") : app.suggested_status ? statusPill(app.suggested_status) : ""}</td>
      <td>${app.next_action || ""}</td>
    </tr>
  `).join("");
}

async function openDetail(id) {
  const app = await api(`/api/applications/${id}`);
  $("#detail").classList.remove("hidden");
  $("#detail").innerHTML = `
    <div class="form-actions">
      <button onclick="editApplication(${id})">Edit</button>
      <button onclick="$('#detail').classList.add('hidden')">Close</button>
    </div>
    <h2>${app.role_title} at ${app.company}</h2>
    <p class="muted">${app.status} · ${app.cv_route || "No CV route"} · ${app.days_active} days active · ${app.ghosting_risk ? "Review for ghosting" : "No ghosting review needed"}</p>
    <div class="detail-grid">
      <div class="detail-block"><h2>Summary</h2><pre>${summaryText(app)}</pre></div>
      <div class="detail-block"><h2>Contact details</h2><pre>${contactText(app)}</pre></div>
      <div class="detail-block"><h2>Job description</h2><pre>${app.job_description || ""}</pre></div>
      <div class="detail-block"><h2>Application notes</h2><pre>${app.notes || ""}</pre></div>
      <div class="detail-block"><h2>Cover letter/message</h2><pre>${app.cover_letter || ""}</pre></div>
      <div class="detail-block"><h2>Timeline</h2><pre>${app.timeline.map(item => `${item.event_date} - ${item.event_type}: ${item.details || ""}`).join("\\n")}</pre></div>
      <div class="detail-block span-2"><h2>Interviews</h2><pre>${app.interviews.map(interviewText).join("\\n\\n") || "No interviews recorded."}</pre></div>
    </div>
  `;
}

function summaryText(app) {
  return [
    `Salary: ${app.salary || ""}`,
    `Location/work mode: ${app.location || ""} ${app.work_mode || ""}`,
    `Source: ${app.source || ""}`,
    `Job URL: ${app.job_url || ""}`,
    `Next action: ${app.next_action || ""}`,
    `Follow-up date: ${app.follow_up_date || ""}`,
    `Outcome date: ${app.outcome_date || ""}`,
    `Tags: ${app.tags || ""}`,
    `Contract flagged: ${app.contract_flag ? "Yes" : "No"}`,
  ].join("\\n");
}

function contactText(app) {
  return [
    `Recruiter/contact: ${app.recruiter_name || ""}`,
    `Email: ${app.contact_email || ""}`,
    `Phone: ${app.contact_phone || ""}`,
    `Recruiter-led: ${app.recruiter_led ? "Yes" : "No"}`,
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
  payload.recruiter_led = form.elements.recruiter_led.checked;
  payload.contract_flag = form.elements.contract_flag.checked;
  const id = form.elements.id.value;
  if (id) await api(`/api/applications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  else await api("/api/applications", { method: "POST", body: JSON.stringify(payload) });
  form.reset();
  form.elements.date_applied.valueAsDate = new Date();
  showView("list");
}

async function loadOptions() {
  state.options = await api("/api/options");
  const statusOptions = state.options.statuses.map((item) => `<option>${item}</option>`).join("");
  const routeOptions = state.options.cv_routes.map((item) => `<option>${item}</option>`).join("");
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
});
