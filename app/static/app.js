const state = {
  options: null,
  applications: [],
  sortKey: localStorage.getItem("sortKey") || "date_applied",
  sortDir: localStorage.getItem("sortDir") || "desc",
  currentDetailId: null,
  attachmentPreviewUrl: null,
};

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

function chartColor(label) {
  const key = String(label || "").toLowerCase();
  if (key.includes("in progress")) return "#238636";
  if (key.includes("screening")) return "#276ef1";
  if (key.includes("1st interview") || key.includes("2nd interview") || key === "interview") return "#276ef1";
  if (key.includes("rejection post interview")) return "#7f1d1d";
  if (key === "rejection" || key.includes("rejection")) return "#f87171";
  if (key.includes("ghost")) return "#111827";
  if (key.includes("offer")) return "#a16207";
  if (key.includes("withdrawn")) return "#64748b";
  if (key.includes("0-7")) return "#238636";
  if (key.includes("8-14")) return "#276ef1";
  if (key.includes("15-20")) return "#f59e0b";
  if (key.includes("21+")) return "#111827";
  return "#8b5cf6";
}

function showView(name) {
  if (name !== "detail") state.currentDetailId = null;
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === name));
  $$("nav button[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  if (name === "dashboard") loadDashboard();
  if (name === "list") loadApplications();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function fitBadge(value) {
  if (!value) return "";
  const score = Number(value);
  const cls = score >= 4.5 ? "fit-good" : score >= 3 ? "fit-warn" : "fit-bad";
  return `<span class="fit-badge ${cls}">${score.toFixed(score % 1 ? 1 : 0)}</span>`;
}

function renderKpis(kpis, ageing = []) {
  const breakdown = kpis.interview_breakdown || {};
  const labels = [
    ["Total applications", kpis.total, "", "total"],
    ["Active applications", kpis.active, "", "active"],
    ["Pipeline ageing", kpis.active, renderPipelineAgeing(ageing), "ageing"],
    ["Interviews", kpis.interviews, renderInterviewBreakdown(breakdown), "interview"],
    ["Rejections", kpis.rejections, "", "bad"],
    ["Ghosted", kpis.ghosted, "", "ghost"],
    ["Offers", kpis.offers, "", "offer"],
    ["Withdrawn by me", kpis.withdrawn, "", "neutral"],
    ["Closed outcomes", kpis.closed_outcomes, "", "closed"],
    ["Meaningful contact", pct(kpis.meaningful_contact_rate), "", "contact"],
    ["Weighted score", `${kpis.weighted_pipeline_score} (${kpis.pipeline_health_label})`, "", "score"],
    ["Avg days active", kpis.average_days_active, "", "days"],
  ];
  $("#kpis").innerHTML = labels.map(([label, value, detail, tone]) => `
    <div class="kpi kpi-${tone}">
      <span>${label}</span>
      <strong>${value}</strong>
      ${detail || ""}
    </div>
  `).join("");
}

function renderPipelineAgeing(ageing) {
  const rows = (ageing || []).filter((row) => Number(row.value) > 0);
  const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0);
  if (!total) return `<p class="kpi-note">No active roles</p>`;
  return `
    <div class="ageing-mini">
      ${rows.map((row) => {
        const value = Number(row.value || 0);
        const width = Math.max(5, value / total * 100);
        return `
          <div class="ageing-mini-row">
            <span>${escapeHtml(row.label)}</span>
            <div class="ageing-mini-track"><div class="ageing-mini-fill ${ageingClass(row.label)}" style="width:${width}%"></div></div>
            <strong>${value}</strong>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function ageingClass(label) {
  const key = String(label || "");
  if (key.includes("0-7")) return "fresh";
  if (key.includes("8-14")) return "mid";
  if (key.includes("15-20")) return "warn";
  return "stale";
}

function renderInterviewBreakdown(breakdown) {
  const rows = [
    ["Screening", breakdown.screening],
    ["Stage 1", breakdown.stage_1],
    ["Stage 2", breakdown.stage_2],
    ["Stage 3", breakdown.stage_3],
  ];
  return `<dl class="kpi-breakdown">${rows.map(([label, value]) => `<div><dt>${label}</dt><dd>${value || 0}</dd></div>`).join("")}</dl>`;
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

function renderWeeklyColumnChart(selector, rows) {
  const series = [
    ["applications", "Applications"],
    ["rejections", "Rejections"],
    ["ghosted", "Ghosted"],
    ["interviews", "Interviews"],
  ];
  const maxValue = Math.max(
    30,
    ...rows.flatMap((row) => series.map(([key]) => Number(row[key]) || 0)),
    ...rows.map((row) => row.target || 0)
  );
  const yMax = Math.ceil(maxValue / 5) * 5;
  const ticks = [yMax, Math.round(yMax * 0.5), 0];
  const target = rows[0]?.target;
  const targetLabel = rows[0]?.target_label || (target ? `Target ${target}/wk` : "");
  const targetNote = rows[0]?.target_note || "";
  const targetBottom = target ? `${Math.max(0, Math.min(100, (target / yMax) * 100))}%` : "";

  const bars = rows.map((row) => {
    const groupBars = series.map(([key, label]) => {
      const value = Number(row[key]) || 0;
      const height = value ? Math.max(3, (value / yMax) * 100) : 0;
      return `
        <div class="column-series-bar ${key}" title="${label}: ${value}" style="height:${height}%">
          ${value ? `<span>${value}</span>` : ""}
        </div>
      `;
    }).join("");
    return `
      <div class="column-item">
        <div class="column-bar-group">${groupBars}</div>
      </div>
    `;
  }).join("");

  const labels = rows.map((row) => `<div class="column-date">${row.week.slice(5)}</div>`).join("");
  const legend = series.map(([key, label]) => `
    <span class="column-legend-item"><span class="legend-swatch ${key}"></span>${label}</span>
  `).join("");

  $(selector).innerHTML = `
    <div class="column-chart">
      <div class="column-legend">${legend}${target ? `<span class="target-badge" title="${escapeHtml(targetNote)}">${escapeHtml(targetLabel)}</span>` : ""}</div>
      <div class="y-axis">${ticks.map((tick) => `<span>${tick}</span>`).join("")}</div>
      <div class="column-stage">
        ${target ? `<div class="target-rule" style="bottom:${targetBottom}"></div>` : ""}
        ${bars}
      </div>
      <div class="column-labels">${labels}</div>
    </div>
  `;
}

function piePath(cx, cy, radius, start, end) {
  const startX = cx + radius * Math.cos(start);
  const startY = cy + radius * Math.sin(start);
  const endX = cx + radius * Math.cos(end);
  const endY = cy + radius * Math.sin(end);
  const largeArc = end - start > Math.PI ? 1 : 0;
  return `M ${cx} ${cy} L ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} 1 ${endX} ${endY} Z`;
}

function renderPieChart(selector, rows, options = {}) {
  const filtered = rows.filter((row) => Number(row.value) > 0);
  const total = filtered.reduce((sum, row) => sum + Number(row.value), 0);
  if (!total) {
    $(selector).innerHTML = `<p class="muted">No data yet.</p>`;
    return;
  }

  let angle = -Math.PI / 2;
  const slices = filtered.map((row, index) => {
    const value = Number(row.value);
    const next = angle + (value / total) * Math.PI * 2;
    const path = piePath(90, 90, 78, angle, next);
    angle = next;
    return `<path d="${path}" fill="${chartColor(row.label)}"></path>`;
  }).join("");

  const legend = filtered.map((row) => {
    const value = Number(row.value);
    const displayValue = options.percent ? pct(value) : value;
    const share = pct((value / total) * 100);
    return `
      <div class="pie-legend-row">
        <span class="legend-swatch" style="background:${chartColor(row.label)}"></span>
        <span>${row.label}</span>
        <strong>${displayValue}</strong>
        <small>${share}</small>
      </div>
    `;
  }).join("");

  $(selector).innerHTML = `
    <div class="pie-chart">
      <svg viewBox="0 0 180 180" role="img" aria-label="${options.label || "Pie chart"}">${slices}</svg>
      <div class="pie-legend">${legend}</div>
    </div>
  `;
}

function renderFunnel(rows) {
  const max = Math.max(1, ...rows.map((row) => Number(row.count) || 0));
  return `
    <div class="funnel-list">
      ${rows.map((row) => `
        <div class="funnel-row">
          <div>
            <strong>${escapeHtml(row.label)}</strong>
            <span>${row.count} · ${pct(row.percent_total)} of total${row.conversion === null ? "" : ` · ${pct(row.conversion)} from previous`}</span>
          </div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, row.count / max * 100)}%"></div></div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderPipelineScore(score) {
  return `
    <div class="score-card">
      <strong>${score.score}</strong>
      <span>${escapeHtml(score.label)}</span>
      <p>${escapeHtml(score.explanation)}</p>
    </div>
  `;
}

function renderConversionMetrics(metrics) {
  const rows = [
    ["Applications → Contact", metrics.applications_to_contact_rate],
    ["Contact → Interview", metrics.contact_to_interview_rate],
    ["Interview → Offer", metrics.interview_to_offer_rate],
  ];
  return rows.map(([label, value]) => `
    <div class="conversion-card">
      <span>${escapeHtml(label)}</span>
      <strong>${pct(value)}</strong>
    </div>
  `).join("");
}

function renderOfferForecast(forecast) {
  return `
    <div class="forecast-summary">
      <div><span>30 days</span><strong>${pct(forecast.chance_30)}</strong></div>
      <div><span>60 days</span><strong>${pct(forecast.chance_60)}</strong></div>
    </div>
    <p class="muted">Confidence: ${escapeHtml(forecast.confidence)} · Active interviews: ${forecast.active_interviews} · Recruiter contact: ${forecast.recruiter_contact_active} · High-fit active: ${forecast.high_fit_active} · Medium-fit active: ${forecast.medium_fit_active}</p>
    ${forecast.warning ? `<p class="muted warning-note">${escapeHtml(forecast.warning)}</p>` : ""}
    <p class="muted">${escapeHtml(forecast.assumptions)}</p>
  `;
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  renderKpis(data.kpis, data.ageing);
  renderWeeklyColumnChart("#weeklyChart", data.weekly);
  $("#interviewFunnel").innerHTML = renderFunnel(data.interview_funnel);
  $("#conversionMetrics").innerHTML = renderConversionMetrics(data.conversion_metrics);
  $("#pipelineScore").innerHTML = renderPipelineScore(data.pipeline_score);
  $("#offerForecast").innerHTML = renderOfferForecast(data.offer_forecast);
  renderBars("#outcomeTimingChart", data.outcome_timing);
  renderBars("#rejectionReasonsChart", data.rejection_reasons);
  $("#roleQualityNote").textContent = data.role_quality_note || "";
  $("#roleQualityRows").innerHTML = data.role_quality.map((row) => `
    <tr>
      <td>${escapeHtml(row.label)}</td>
      <td>${row.applications}</td>
      <td>${row.active}</td>
      <td>${row.interviews}</td>
      <td>${row.rejections}</td>
      <td>${row.ghosted}</td>
      <td>${pct(row.interview_rate)}</td>
      <td>${pct(row.ghosting_rate)}</td>
    </tr>
  `).join("");

  $("#bestRoute").textContent = data.best_route
    ? `Highest current traction: ${data.best_route.label} (${pct(data.best_route.traction)}). ${data.best_route.confidence}; avoid over-reading small samples.`
    : "No CV route performance data yet.";

  $("#cvRouteRows").innerHTML = performanceRows(data.cv_routes, "label");

  $("#sourceRows").innerHTML = performanceRows(data.sources, "label");
  $("#roleTypeRows").innerHTML = performanceRows(data.role_types, "label");

  $("#followupRows").innerHTML = data.priority_followups.map((row) => `
    <tr>
      <td>${row.company}</td>
      <td><button class="link-button" onclick="editApplication(${row.id})">${row.role_title}</button></td>
      <td>${row.days_active}</td>
      <td>${row.days_since_last_activity}</td>
      <td>${statusPill(row.status)}</td>
      <td>${row.fit_score || ""}</td>
      <td>${row.suggested_action}</td>
    </tr>
  `).join("");
}

async function refreshAfterMutation(id = null) {
  await loadDashboard();
  await loadApplications();
  if (state.currentDetailId && (!id || Number(state.currentDetailId) === Number(id))) {
    const current = state.currentDetailId;
    const app = await api(`/api/applications/${current}`);
    $("#roleDetail").innerHTML = renderRoleDetail(app);
  }
}

function performanceRows(rows, labelKey) {
  return rows.map((row) => `
    <tr>
      <td>${escapeHtml(row[labelKey])}</td>
      <td>${row.applications}</td>
      <td>${fitBadge(row.avg_fit)}</td>
      <td>${row.interviews}</td>
      <td>${row.rejections}</td>
      <td>${row.ghosted}</td>
      <td>${row.active}</td>
      <td>${pct(row.interview_rate)}</td>
      <td>${pct(row.traction)}</td>
      <td>${escapeHtml(row.confidence)}</td>
    </tr>
  `).join("");
}

function statusPill(status, suggested = "") {
  const label = suggested || status || "";
  let cls = "";
  if (label.includes("Ghost")) cls = "ghost";
  if (label.includes("Offer")) cls = "good";
  if (label.includes("Interview") || label.includes("Screening")) cls = "warn";
  if (label.includes("Withdrawn")) cls = "neutral";
  return `<span class="status-pill ${cls}">${label}</span>`;
}

async function loadApplications() {
  const params = new URLSearchParams();
  if ($("#search").value) params.set("q", $("#search").value);
  if ($("#statusFilter").value) params.set("status", $("#statusFilter").value);
  if ($("#routeFilter").value) params.set("cv_route", $("#routeFilter").value);
  localStorage.setItem("filters", JSON.stringify({
    q: $("#search").value,
    status: $("#statusFilter").value,
    cv_route: $("#routeFilter").value,
  }));
  state.applications = await api(`/api/applications?${params}`);
  sortApplications();
  $("#applicationRows").innerHTML = state.applications.map((app) => `
    <tr onclick="if (!event.target.closest('button')) openRoleDetail(${app.id})">
      <td><button class="link-button" onclick="openRoleDetail(${app.id})">${escapeHtml(app.company)}</button></td>
      <td><button class="link-button" onclick="openRoleDetail(${app.id})">${escapeHtml(app.role_title)}</button></td>
      <td>${statusPill(app.status)}</td>
      <td>${app.date_applied}</td>
      <td>${app.days_active}</td>
      <td>${app.days_since_last_contact}</td>
      <td>${escapeHtml(app.cv_route || "")}</td>
      <td>${fitBadge(app.fit_score)}</td>
      <td>${escapeHtml(app.source || "")}</td>
      <td>${app.effective_status && app.effective_status !== app.status ? statusPill(app.effective_status) : ""}</td>
      <td>${escapeHtml(app.next_action || "")}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="row-action" onclick="editApplication(${app.id})">Edit</button>
          <button type="button" class="row-action" onclick="openRejectModal(${app.id})">Reject</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function sortApplications() {
  const key = state.sortKey;
  const dir = state.sortDir === "asc" ? 1 : -1;
  state.applications.sort((a, b) => {
    const av = a[key] ?? "";
    const bv = b[key] ?? "";
    if (typeof av === "number" || typeof bv === "number") return (Number(av || 0) - Number(bv || 0)) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

async function quickAction(id, action) {
  await api(`/api/applications/${id}/action`, { method: "POST", body: JSON.stringify({ action }) });
  await refreshAfterMutation(id);
}

async function quickFollowup(id) {
  const action = prompt("Follow-up action", "Follow up");
  if (!action) return;
  const due_date = prompt("Follow-up date (YYYY-MM-DD)", new Date().toISOString().slice(0, 10));
  await api(`/api/applications/${id}/followups`, { method: "POST", body: JSON.stringify({ action, due_date }) });
  await refreshAfterMutation(id);
}

async function openRejectModal(id) {
  const app = await api(`/api/applications/${id}`);
  const form = $("#rejectForm");
  form.elements.id.value = id;
  form.elements.rejection_reason.value = app.rejection_reason || "Not recorded";
  form.elements.rejection_email.value = app.rejection_email || "";
  $("#rejectModalTitle").textContent = `Reject ${app.company} - ${app.role_title}`;
  $("#rejectModal").classList.remove("hidden");
}

function closeRejectModal() {
  $("#rejectModal").classList.add("hidden");
  $("#rejectForm").reset();
}

async function saveRejection(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const current = await api(`/api/applications/${id}`);
  const payload = {
    ...current,
    status: "Rejection",
    rejection_reason: form.elements.rejection_reason.value.trim(),
    rejection_email: form.elements.rejection_email.value.trim(),
    last_contact_date: new Date().toISOString().slice(0, 10),
    outcome_date: new Date().toISOString().slice(0, 10),
  };
  if (!payload.rejection_reason) {
    alert("Choose a rejection reason before saving.");
    return;
  }
  try {
    await api(`/api/applications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    closeRejectModal();
    await refreshAfterMutation(id);
  } catch (error) {
    alert(`Save failed: ${error.message}`);
  }
}

async function openRoleDetail(id) {
  const app = await api(`/api/applications/${id}`);
  state.currentDetailId = id;
  $("#roleDetail").innerHTML = renderRoleDetail(app);
  showView("detail");
}

function renderRoleDetail(app) {
  const attachments = mergedAttachments(app);
  return `
    <div class="detail-header panel">
      <div>
        <button type="button" onclick="showView('list')">Back</button>
        <h2>${escapeHtml(app.company)} - ${escapeHtml(app.role_title)}</h2>
        <p class="muted">${statusPill(app.status)} ${fitBadge(app.fit_score)} ${app.effective_status && app.effective_status !== app.status ? statusPill(app.effective_status) : ""}</p>
      </div>
      <div class="form-actions">
        <button type="button" onclick="editApplication(${app.id})">Edit</button>
        <button type="button" onclick="quickAction(${app.id}, 'ghosted')">Mark Ghosted</button>
        <button type="button" onclick="quickAction(${app.id}, 'rejected')">Mark Rejected</button>
        <button type="button" onclick="quickAction(${app.id}, 'withdrawn')">Mark Withdrawn</button>
      </div>
    </div>
    <div class="detail-layout">
      <section class="panel"><h2>Summary</h2>${infoRows([
        ["Status", app.status],
        ["Effective status", app.effective_status],
        ["Interview stage reached", app.reached_interview_stage || app.interview_stage],
        ["Effective ghosted date", app.effective_ghosted_date],
        ["CV used", app.cv_route],
        ["Role type", app.role_type],
        ["Source", app.source],
        ["Date applied", app.date_applied],
        ["Days active", app.days_active],
        ["Days since last contact", app.days_since_last_contact],
        ["Ageing bucket", app.ageing_bucket],
        ["Next action", app.next_action],
        ["Follow-up date", app.follow_up_date],
        ["Tags", app.tags],
      ])}</section>
      <section class="panel"><h2>Contact & terms</h2>${infoRows([
        ["Recruiter/contact", app.recruiter_name],
        ["Email", app.contact_email],
        ["Phone", app.contact_phone],
        ["Salary", app.salary],
        ["Location", app.location],
        ["Work mode", app.work_mode],
        ["Travel", app.travel_requirement],
        ["Contract flagged", app.contract_flag ? "Yes" : "No"],
        ["Job URL", app.job_url],
      ])}</section>
      <section class="panel"><h2>Job description</h2><pre>${escapeHtml(app.job_description || "")}</pre></section>
      <section class="panel"><h2>Notes</h2><pre>${escapeHtml(app.notes || "")}</pre></section>
      <section class="panel"><h2>Cover letter/message</h2><pre>${escapeHtml(app.cover_letter || "")}</pre></section>
      <section class="panel"><h2>Rejection</h2>${infoRows([
        ["Reason", app.rejection_reason],
      ])}<pre>${escapeHtml(app.rejection_email || "")}</pre></section>
      <section class="panel"><h2>Withdrawn by me</h2><pre>${escapeHtml(app.withdrawal_reason || "")}</pre></section>
      <section class="panel"><h2>Timeline/history</h2>${timelineList(app.timeline)}</section>
      <section class="panel"><h2>Interview history</h2>${interviewList(app.interviews)}${interviewForm(app.id)}</section>
      <section class="panel"><h2>Follow-up history</h2>${followupList(app.followups)}${followupForm(app.id)}</section>
      <section class="panel"><h2>Attachments/documents</h2>${attachmentList(attachments)}${attachmentForm(app.id)}</section>
    </div>
  `;
}

function mergedAttachments(app) {
  const seen = new Set();
  const items = [
    ...String(app.attachment_links || "").split("\n").filter(Boolean).map((path) => ({ label: "File reference", path })),
    ...(app.attachments || []),
  ];
  return items.filter((item) => {
    const key = cleanAttachmentPath(item.path);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function infoRows(rows) {
  return `<dl class="info-list">${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || "")}</dd>`).join("")}</dl>`;
}

function timelineList(items) {
  return `<ol class="timeline">${(items || []).map((item) => `<li><strong>${escapeHtml(item.event_date)}</strong> ${escapeHtml(item.event_type)}<br><span>${escapeHtml(item.details || "")}</span></li>`).join("") || "<li>No history yet.</li>"}</ol>`;
}

function interviewList(items) {
  return `<div class="stack">${(items || []).map((item) => `<article class="mini-card"><strong>${escapeHtml(item.stage_name)}</strong><span>${escapeHtml(item.scheduled_at || "")}</span><p>${escapeHtml(item.outcome || "")}</p><p>${escapeHtml(item.feedback || "")}</p></article>`).join("") || "<p class='muted'>No interviews recorded.</p>"}</div>`;
}

function followupList(items) {
  return `<div class="stack">${(items || []).map((item) => `<article class="mini-card"><strong>${escapeHtml(item.due_date || "")}</strong><p>${escapeHtml(item.action || "")}</p><p>${escapeHtml(item.notes || "")}</p></article>`).join("") || "<p class='muted'>No follow-ups recorded.</p>"}</div>`;
}

function attachmentList(items) {
  return `<div class="stack">${items.map((item) => attachmentCard(item)).join("") || "<p class='muted'>No documents linked.</p>"}</div>`;
}

function cleanAttachmentPath(path) {
  return String(path || "").trim().replace(/^['"]|['"]$/g, "");
}

function attachmentKind(path, kind = "") {
  const explicit = String(kind || "").toLowerCase();
  const name = cleanAttachmentPath(path).toLowerCase();
  if (explicit.includes("pdf") || name.endsWith(".pdf")) return "pdf";
  if (explicit.includes("image") || /\.(png|jpe?g|gif|webp|bmp|svg)$/.test(name)) return "image";
  if (explicit.includes("text") || /\.(txt|md|csv|json|log|rtf)$/.test(name)) return "text";
  return "";
}

function attachmentCard(item) {
  const path = cleanAttachmentPath(item.path);
  const encoded = encodeURIComponent(path);
  const encodedLabel = encodeURIComponent(item.label || "Document");
  const canPreview = Boolean(attachmentKind(path, item.kind));
  return `
    <article class="mini-card attachment-card">
      <div class="attachment-heading">
        <strong>${escapeHtml(item.label || "Document")}</strong>
        <span>${escapeHtml(item.kind || attachmentKind(path, item.kind) || "File")}</span>
      </div>
      <p class="attachment-path">${escapeHtml(path)}</p>
      ${item.notes ? `<p>${escapeHtml(item.notes)}</p>` : ""}
      <div class="attachment-actions">
        ${canPreview ? `<button type="button" onclick="previewAttachment('${encoded}', '${encodedLabel}')">Preview</button>` : ""}
        <button type="button" onclick="openAttachmentNative('${encoded}')">Open in app</button>
        <button type="button" onclick="copyAttachmentPath('${encoded}')">Copy path</button>
      </div>
    </article>
  `;
}

async function previewAttachment(encodedPath, label) {
  const path = decodeURIComponent(encodedPath);
  const title = decodeURIComponent(label || "Document");
  const kind = attachmentKind(path);
  const url = `/api/attachments/preview?path=${encodedPath}`;
  $("#attachmentPreviewTitle").textContent = title || "Document preview";
  $("#attachmentPreviewPath").textContent = path;
  const body = $("#attachmentPreviewBody");
  body.innerHTML = `<p class="muted preview-loading">Loading preview...</p>`;
  $("#attachmentPreviewModal").classList.remove("hidden");
  if (state.attachmentPreviewUrl) URL.revokeObjectURL(state.attachmentPreviewUrl);
  state.attachmentPreviewUrl = null;
  let previewUrl = "";
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(await response.text());
    previewUrl = URL.createObjectURL(await response.blob());
    state.attachmentPreviewUrl = previewUrl;
  } catch (error) {
    closeAttachmentPreview();
    await openAttachmentNative(encodedPath);
    return;
  }
  if (kind === "image") {
    body.innerHTML = `<img class="attachment-preview-image" src="${previewUrl}" alt="${escapeHtml(title || "Attachment")}">`;
  } else if (kind === "pdf" || kind === "text") {
    body.innerHTML = `<iframe class="attachment-preview-frame" src="${previewUrl}" title="${escapeHtml(title || "Attachment preview")}"></iframe>`;
  } else {
    body.innerHTML = `<p class="muted">Preview is not available for this file type.</p>`;
  }
  $("#attachmentPreviewModal").classList.remove("hidden");
}

function closeAttachmentPreview() {
  $("#attachmentPreviewModal").classList.add("hidden");
  $("#attachmentPreviewBody").innerHTML = "";
  if (state.attachmentPreviewUrl) URL.revokeObjectURL(state.attachmentPreviewUrl);
  state.attachmentPreviewUrl = null;
}

async function openAttachmentNative(encodedPath) {
  try {
    await api("/api/attachments/open", { method: "POST", body: JSON.stringify({ path: decodeURIComponent(encodedPath) }) });
  } catch (error) {
    alert(`Could not open attachment: ${error.message}`);
  }
}

async function copyAttachmentPath(encodedPath) {
  const path = decodeURIComponent(encodedPath);
  try {
    await navigator.clipboard.writeText(path);
  } catch (error) {
    prompt("Copy attachment path", path);
  }
}

function interviewForm(id) {
  const stageOptions = (state.options?.interview_stages || ["", "Screening", "Stage 1", "Stage 2", "Stage 3"])
    .filter(Boolean)
    .map((item) => `<option>${escapeHtml(item)}</option>`)
    .join("");
  return `<form class="inline-form" onsubmit="saveInterview(event, ${id})"><select name="stage_name" required>${stageOptions}</select><input name="scheduled_at" type="datetime-local"><input name="interviewer_names" placeholder="Interviewers"><input name="interviewer_emails" placeholder="Emails"><input name="meeting_link" placeholder="Meeting link/location"><textarea name="prep_notes" placeholder="Preparation notes"></textarea><textarea name="questions_asked" placeholder="Questions asked"></textarea><textarea name="feedback" placeholder="Feedback"></textarea><input name="outcome" placeholder="Outcome"><label>Follow-up sent <input name="follow_up_sent" type="checkbox"></label><button type="submit">Add interview</button></form>`;
}

function followupForm(id) {
  return `<form class="inline-form" onsubmit="saveFollowup(event, ${id})"><input name="due_date" type="date"><input name="action" placeholder="Follow-up action" required><textarea name="notes" placeholder="Notes"></textarea><label>Completed <input name="completed" type="checkbox"></label><button type="submit">Add follow-up</button></form>`;
}

function attachmentForm(id) {
  return `<form class="inline-form" onsubmit="saveAttachment(event, ${id})"><input name="label" placeholder="Label"><input name="file" type="file"><input name="path" placeholder="Local file path or reference"><input name="kind" placeholder="Type"><textarea name="notes" placeholder="Notes"></textarea><button type="submit">Add document</button></form>`;
}

async function saveInterview(event, id) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.follow_up_sent = form.elements.follow_up_sent.checked;
  await api(`/api/applications/${id}/interviews`, { method: "POST", body: JSON.stringify(payload) });
  await refreshAfterMutation(id);
}

async function saveFollowup(event, id) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.completed = form.elements.completed.checked;
  await api(`/api/applications/${id}/followups`, { method: "POST", body: JSON.stringify(payload) });
  await refreshAfterMutation(id);
}

async function saveAttachment(event, id) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  const file = form.elements.file.files[0];
  delete payload.file;
  if (file) {
    payload.file_name = file.name;
    payload.kind = payload.kind || file.type;
    payload.file_content = await fileToDataUrl(file);
    if (!payload.label) payload.label = file.name;
  }
  if (!file && !payload.path) {
    alert("Choose a file or enter a local path before adding a document.");
    return;
  }
  try {
    await api(`/api/applications/${id}/attachments`, { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    await refreshAfterMutation(id);
  } catch (error) {
    alert(`Document could not be attached: ${error.message}`);
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function editApplication(id) {
  const app = await api(`/api/applications/${id}`);
  if (!app) return;
  const form = $("#editApplicationForm");
  Object.entries(app).forEach(([key, value]) => {
    const field = form.elements[key];
    if (!field) return;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value || "";
  });
  $("#editModalTitle").textContent = `Edit ${app.company} - ${app.role_title}`;
  $("#editModal").classList.remove("hidden");
}

function payloadFromForm(form) {
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.recruiter_led = form.elements.recruiter_led.checked;
  payload.contract_flag = form.elements.contract_flag.checked;
  return payload;
}

async function saveApplication(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = payloadFromForm(form);
  if (!payload.company || !payload.role_title || !payload.date_applied) {
    alert("Company, role title and date applied are required.");
    return;
  }
  const id = form.elements.id.value;
  try {
    if (id) await api(`/api/applications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/applications", { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    form.elements.date_applied.valueAsDate = new Date();
    await refreshAfterMutation(id || null);
    showView("list");
  } catch (error) {
    alert(`Save failed: ${error.message}`);
  }
}

async function saveEditedApplication(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = payloadFromForm(form);
  if (!payload.company || !payload.role_title || !payload.date_applied) {
    alert("Company, role title and date applied are required.");
    return;
  }
  const id = form.elements.id.value;
  try {
    await api(`/api/applications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    closeEditModal();
    await refreshAfterMutation(id);
  } catch (error) {
    alert(`Save failed: ${error.message}`);
  }
}

function closeEditModal() {
  $("#editModal").classList.add("hidden");
  $("#editApplicationForm").reset();
}

async function loadOptions() {
  state.options = await api("/api/options");
  const statusOptions = state.options.statuses.map((item) => `<option>${item}</option>`).join("");
  const interviewStageOptions = state.options.interview_stages.map((item) => `<option>${item}</option>`).join("");
  const routeOptions = state.options.cv_routes.map((item) => `<option>${item}</option>`).join("");
  const roleTypeOptions = state.options.role_types.map((item) => `<option>${item}</option>`).join("");
  const sourceOptions = state.options.sources.map((item) => `<option>${item}</option>`).join("");
  const workModeOptions = state.options.work_modes.map((item) => `<option>${item}</option>`).join("");
  const travelOptions = state.options.travel_requirements.map((item) => `<option>${item}</option>`).join("");
  const rejectionReasonOptions = state.options.rejection_reasons.map((item) => `<option>${item}</option>`).join("");
  $("#statusFilter").innerHTML += statusOptions;
  $("#routeFilter").innerHTML += routeOptions;
  $("#applicationForm").elements.status.innerHTML = statusOptions;
  $("#applicationForm").elements.interview_stage.innerHTML = interviewStageOptions;
  $("#applicationForm").elements.cv_route.innerHTML = `<option></option>${routeOptions}`;
  $("#applicationForm").elements.role_type.innerHTML = `<option></option>${roleTypeOptions}`;
  $("#applicationForm").elements.source.innerHTML = `<option></option>${sourceOptions}`;
  $("#applicationForm").elements.work_mode.innerHTML = `<option></option>${workModeOptions}`;
  $("#applicationForm").elements.travel_requirement.innerHTML = `<option></option>${travelOptions}`;
  $("#applicationForm").elements.rejection_reason.innerHTML = `<option></option>${rejectionReasonOptions}`;
  $("#rejectForm").elements.rejection_reason.innerHTML = rejectionReasonOptions;
  $("#applicationForm").elements.date_applied.valueAsDate = new Date();
  $("#editApplicationForm").innerHTML = $("#applicationForm").innerHTML;
  $("#editApplicationForm").querySelector('button[type="submit"]').textContent = "Save changes";
  const resetButton = $("#editApplicationForm").querySelector("#resetForm");
  resetButton.id = "cancelEdit";
  resetButton.textContent = "Cancel";
}

function initEvents() {
  $$("nav button[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  $("#darkModeToggle").addEventListener("click", toggleDarkMode);
  $("#applicationForm").addEventListener("submit", saveApplication);
  $("#editApplicationForm").addEventListener("submit", saveEditedApplication);
  $("#closeEditModal").addEventListener("click", closeEditModal);
  $("#editModal").addEventListener("click", (event) => {
    if (event.target.id === "editModal") closeEditModal();
  });
  $("#rejectForm").addEventListener("submit", saveRejection);
  $("#closeRejectModal").addEventListener("click", closeRejectModal);
  $("#cancelReject").addEventListener("click", closeRejectModal);
  $("#rejectModal").addEventListener("click", (event) => {
    if (event.target.id === "rejectModal") closeRejectModal();
  });
  $("#attachmentPreviewModal").addEventListener("click", (event) => {
    if (event.target.id === "attachmentPreviewModal") closeAttachmentPreview();
  });
  $("#cancelEdit").addEventListener("click", closeEditModal);
  $("#resetForm").addEventListener("click", () => {
    $("#applicationForm").reset();
    $("#applicationForm").elements.date_applied.valueAsDate = new Date();
  });
  ["search", "statusFilter", "routeFilter"].forEach((id) => $(`#${id}`).addEventListener("input", loadApplications));
  $$("#list th[data-sort]").forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    else {
      state.sortKey = key;
      state.sortDir = "asc";
    }
    localStorage.setItem("sortKey", state.sortKey);
    localStorage.setItem("sortDir", state.sortDir);
    sortApplications();
    loadApplications();
  }));
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      event.preventDefault();
      showView("list");
      $("#search").focus();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") {
      event.preventDefault();
      showView("form");
    }
    if (event.key === "Escape" && !$("#attachmentPreviewModal").classList.contains("hidden")) {
      closeAttachmentPreview();
    }
  });
  $("#clearFilters").addEventListener("click", () => {
    $("#search").value = "";
    $("#statusFilter").value = "";
    $("#routeFilter").value = "";
    loadApplications();
  });
}

function restorePreferences() {
  if (localStorage.getItem("darkMode") === "1") document.body.classList.add("dark");
  const filters = JSON.parse(localStorage.getItem("filters") || "{}");
  $("#search").value = filters.q || "";
  $("#statusFilter").value = filters.status || "";
  $("#routeFilter").value = filters.cv_route || "";
}

function toggleDarkMode() {
  document.body.classList.toggle("dark");
  localStorage.setItem("darkMode", document.body.classList.contains("dark") ? "1" : "0");
}

loadOptions().then(() => {
  restorePreferences();
  initEvents();
  loadDashboard();
});
