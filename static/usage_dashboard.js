const tokenStorageKey = "meubusao.admin.token";
const loginPath = "/admin/login";

const chartPalette = {
  gold: "#b97822",
  coral: "#cc5f45",
  teal: "#166a72",
  ink: "#24384e",
  sand: "#e7c893"
};

let charts = {};
let dashboardData = {
  application: [],
  utilization: []
};

const pivotDefinitions = {
  application: {
    fields: [
      { key: "city", label: "Ville", type: "dimension" },
      { key: "routeId", label: "Route", type: "dimension" },
      { key: "endpoint", label: "Endpoint", type: "dimension" },
      { key: "method", label: "Méthode", type: "dimension" },
      { key: "requestCount", label: "Requêtes", type: "metric" },
      { key: "errorCount", label: "Erreurs", type: "metric" },
      { key: "successCount", label: "Succès", type: "metric" },
      { key: "averageDurationMs", label: "Durée moyenne (ms)", type: "metric" }
    ],
    defaults: { rows: ["routeId"], columns: ["city"], value: ["requestCount"] }
  },
  utilization: {
    fields: [
      { key: "city", label: "Ville", type: "dimension" },
      { key: "routeId", label: "Route", type: "dimension" },
      { key: "lineName", label: "Ligne", type: "dimension" },
      { key: "direction", label: "Direction", type: "dimension" },
      { key: "eventCount", label: "Événements", type: "metric" },
      { key: "totalBoardings", label: "Montées", type: "metric" },
      { key: "totalAlightings", label: "Descentes", type: "metric" },
      { key: "averageOccupancy", label: "Occupation moyenne", type: "metric" },
      { key: "averageOccupancyRate", label: "Taux d’occupation", type: "metric" }
    ],
    defaults: { rows: ["lineName"], columns: ["city"], value: ["totalBoardings"] }
  }
};

let pivotState = { dataset: "application", rows: [], columns: [], value: [] };

function getStoredToken() {
  return window.localStorage.getItem(tokenStorageKey) || "";
}

function setStoredToken(token) {
  window.localStorage.setItem(tokenStorageKey, token);
}

function clearStoredToken() {
  window.localStorage.removeItem(tokenStorageKey);
}

function redirectToLogin() {
  const next = encodeURIComponent(window.location.pathname);
  window.location.href = `${loginPath}?next=${next}`;
}

function buildQueryString(formData) {
  const query = new URLSearchParams();

  for (const [key, value] of formData.entries()) {
    if (value) {
      query.set(key, value);
    }
  }

  const text = query.toString();
  return text ? `?${text}` : "";
}

function getQueryStringFromFilters() {
  const form = document.getElementById("filtersForm");
  return buildQueryString(new FormData(form));
}

function setMessage(message, type = "") {
  const node = document.getElementById("dashboardMessage");
  node.textContent = message || "";
  node.className = "status-line";
  if (type) {
    node.classList.add(`is-${type}`);
  }
}

async function fetchJson(url, token) {
  const response = await fetch(url, {
    headers: {
      token
    }
  });

  const data = await response.json().catch(() => ({}));

  if (response.status === 403) {
    clearStoredToken();
    redirectToLogin();
    throw new Error("Session expiree. Veuillez vous reconnecter.");
  }

  if (!response.ok) {
    throw new Error(data.message || `Request failed with status ${response.status}`);
  }

  return data;
}

async function downloadFile(url, token, fallbackFilename) {
  const response = await fetch(url, {
    headers: {
      token
    }
  });

  if (response.status === 403) {
    clearStoredToken();
    redirectToLogin();
    throw new Error("Session expiree. Veuillez vous reconnecter.");
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.message || `Request failed with status ${response.status}`);
  }

  const contentDisposition = response.headers.get("Content-Disposition") || "";
  const filenameMatch = contentDisposition.match(/filename=\"?([^\";]+)\"?/i);
  const filename = filenameMatch && filenameMatch[1] ? filenameMatch[1] : fallbackFilename;

  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

function formatNumber(value, fractionDigits = 0) {
  const numericValue = Number(value || 0);
  return new Intl.NumberFormat("fr-FR", {
    maximumFractionDigits: fractionDigits,
    minimumFractionDigits: fractionDigits
  }).format(numericValue);
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toChartLabels(items) {
  return items.map((item) => {
    const date = new Date(item.bucket);
    if (Number.isNaN(date.getTime())) {
      return item.bucket;
    }

    return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  });
}

function upsertChart(chartId, config) {
  if (charts[chartId]) {
    charts[chartId].destroy();
  }

  const context = document.getElementById(chartId);
  charts[chartId] = new Chart(context, config);
}

function renderApplicationTimeline(timeline) {
  upsertChart("applicationTimelineChart", {
    type: "line",
    data: {
      labels: toChartLabels(timeline),
      datasets: [
        {
          label: "Requêtes",
          data: timeline.map((item) => item.requestCount),
          borderColor: chartPalette.ink,
          backgroundColor: "rgba(36, 56, 78, 0.12)",
          tension: 0.3,
          fill: true
        },
        {
          label: "Erreurs",
          data: timeline.map((item) => item.errorCount),
          borderColor: chartPalette.coral,
          backgroundColor: "rgba(204, 95, 69, 0.1)",
          tension: 0.3,
          fill: true
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

function renderEndpointsChart(summary) {
  const topItems = summary.slice(0, 6);
  upsertChart("topEndpointsChart", {
    type: "bar",
    data: {
      labels: topItems.map((item) => item.endpoint || "n/a"),
      datasets: [
        {
          label: "Requêtes",
          data: topItems.map((item) => item.requestCount),
          backgroundColor: [chartPalette.gold, chartPalette.coral, chartPalette.teal, chartPalette.ink, chartPalette.sand, "#8c6f5c"]
        }
      ]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      }
    }
  });
}

function renderUtilizationTimeline(timeline) {
  upsertChart("utilizationTimelineChart", {
    type: "line",
    data: {
      labels: toChartLabels(timeline),
      datasets: [
        {
          label: "Boardings",
          data: timeline.map((item) => item.totalBoardings),
          borderColor: chartPalette.teal,
          backgroundColor: "rgba(22, 106, 114, 0.14)",
          fill: true,
          tension: 0.35
        },
        {
          label: "Alightings",
          data: timeline.map((item) => item.totalAlightings),
          borderColor: chartPalette.gold,
          backgroundColor: "rgba(185, 120, 34, 0.12)",
          fill: true,
          tension: 0.35
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

function renderRoutesChart(summary) {
  const topItems = summary.slice(0, 6);
  upsertChart("topRoutesChart", {
    type: "doughnut",
    data: {
      labels: topItems.map((item) => item.lineName || item.routeId || "n/a"),
      datasets: [
        {
          data: topItems.map((item) => item.totalBoardings),
          backgroundColor: [chartPalette.teal, chartPalette.gold, chartPalette.coral, chartPalette.ink, chartPalette.sand, "#68717a"]
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

function aggregateByField(summary, fieldName) {
  const grouped = new Map();

  summary.forEach((item) => {
    const key = item[fieldName] || "n/a";
    const current = grouped.get(key) || 0;
    grouped.set(key, current + Number(item.requestCount || 0));
  });

  return Array.from(grouped.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
}

function renderCityBreakdownChart(summary) {
  const cityData = aggregateByField(summary, "city");

  upsertChart("cityBreakdownChart", {
    type: "bar",
    data: {
      labels: cityData.map((item) => item.label),
      datasets: [
        {
          label: "Requetes",
          data: cityData.map((item) => item.value),
          backgroundColor: [chartPalette.ink, chartPalette.teal, chartPalette.gold, chartPalette.coral, chartPalette.sand, "#8c6f5c", "#68717a", "#7f5134"]
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      }
    }
  });
}

function renderMethodBreakdownChart(summary) {
  const methodData = aggregateByField(summary, "method");

  upsertChart("methodBreakdownChart", {
    type: "pie",
    data: {
      labels: methodData.map((item) => item.label),
      datasets: [
        {
          data: methodData.map((item) => item.value),
          backgroundColor: [chartPalette.teal, chartPalette.gold, chartPalette.coral, chartPalette.ink, chartPalette.sand, "#8c6f5c"]
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

function fillApplicationTable(summary) {
  const body = document.getElementById("applicationUsageTableBody");
  body.innerHTML = summary.map((item) => `
    <tr>
      <td>${escapeHtml(item.endpoint || "-")}</td>
      <td>${escapeHtml(item.method || "-")}</td>
      <td>${escapeHtml(item.city || "-")}</td>
      <td>${escapeHtml(item.routeId || "-")}</td>
      <td>${formatNumber(item.requestCount)}</td>
      <td>${formatNumber(item.errorCount)}</td>
      <td>${item.averageDurationMs == null ? "-" : `${formatNumber(item.averageDurationMs, 1)} ms`}</td>
    </tr>
  `).join("");
}

function fillUtilizationTable(summary) {
  const body = document.getElementById("lineUtilizationTableBody");
  body.innerHTML = summary.map((item) => `
    <tr>
      <td>${escapeHtml(item.city || "-")}</td>
      <td>${escapeHtml(item.routeId || "-")}</td>
      <td>${escapeHtml(item.lineName || "-")}</td>
      <td>${escapeHtml(item.direction || "-")}</td>
      <td>${formatNumber(item.eventCount)}</td>
      <td>${formatNumber(item.totalBoardings)}</td>
      <td>${item.averageOccupancy == null ? "-" : formatNumber(item.averageOccupancy, 1)}</td>
    </tr>
  `).join("");
}

function getConsultedRoutes(summary) {
  const routes = new Map();

  summary.forEach((item) => {
    if (!item.routeId) {
      return;
    }

    const key = `${item.city || "n/a"}\u0000${item.routeId}`;
    const route = routes.get(key) || {
      city: item.city || "n/a",
      routeId: item.routeId,
      requestCount: 0,
      errorCount: 0,
      endpoints: new Map()
    };
    const requests = Number(item.requestCount || 0);
    route.requestCount += requests;
    route.errorCount += Number(item.errorCount || 0);
    route.endpoints.set(item.endpoint || "n/a", (route.endpoints.get(item.endpoint || "n/a") || 0) + requests);
    routes.set(key, route);
  });

  return Array.from(routes.values())
    .map((route) => ({
      ...route,
      topEndpoint: Array.from(route.endpoints.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] || "n/a"
    }))
    .sort((a, b) => b.requestCount - a.requestCount);
}

function renderConsultedRoutes(summary) {
  const routes = getConsultedRoutes(summary);
  const chartItems = routes.slice(0, 10);
  const chartNode = document.getElementById("consultedRoutesChart");

  if (chartItems.length && chartNode) {
    upsertChart("consultedRoutesChart", {
      type: "bar",
      data: {
        labels: chartItems.map((item) => `${item.routeId} · ${item.city}`),
        datasets: [
          {
            label: "Requêtes",
            data: chartItems.map((item) => item.requestCount),
            backgroundColor: chartPalette.teal,
            borderRadius: 8
          },
          {
            label: "Erreurs",
            data: chartItems.map((item) => item.errorCount),
            backgroundColor: chartPalette.coral,
            borderRadius: 8
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: { x: { beginAtZero: true } }
      }
    });
  } else if (charts.consultedRoutesChart) {
    charts.consultedRoutesChart.destroy();
    delete charts.consultedRoutesChart;
  }

  const body = document.getElementById("consultedRoutesTableBody");
  body.innerHTML = routes.length
    ? routes.slice(0, 25).map((item, index) => `
      <tr>
        <td><span class="rank-badge">${index + 1}</span></td>
        <td>${escapeHtml(item.city)}</td>
        <td><strong>${escapeHtml(item.routeId)}</strong></td>
        <td>${formatNumber(item.requestCount)}</td>
        <td>${formatNumber(item.errorCount)}</td>
        <td>${escapeHtml(item.topEndpoint)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="6" class="pivot-empty">Aucune requête associée à une ligne pour ces filtres.</td></tr>';
}

function findPivotField(key) {
  return pivotDefinitions[pivotState.dataset].fields.find((field) => field.key === key);
}

function resetPivot() {
  const defaults = pivotDefinitions[pivotState.dataset].defaults;
  pivotState.rows = [...defaults.rows];
  pivotState.columns = [...defaults.columns];
  pivotState.value = [...defaults.value];
  renderPivotBuilder();
  renderPivotTable();
}

function assignPivotField(fieldKey, zone) {
  const field = findPivotField(fieldKey);
  if (!field || (zone === "value" && field.type !== "metric") || (zone !== "value" && field.type !== "dimension")) {
    const zoneNode = document.querySelector(`.pivot-zone[data-zone="${zone}"]`);
    zoneNode?.classList.add("is-invalid");
    window.setTimeout(() => zoneNode?.classList.remove("is-invalid"), 500);
    return;
  }

  ["rows", "columns", "value"].forEach((name) => {
    pivotState[name] = pivotState[name].filter((key) => key !== fieldKey);
  });

  if (zone === "columns" || zone === "value") {
    pivotState[zone] = [fieldKey];
  } else {
    pivotState.rows.push(fieldKey);
  }

  renderPivotBuilder();
  renderPivotTable();
}

function renderPivotBuilder() {
  const assigned = new Set([...pivotState.rows, ...pivotState.columns, ...pivotState.value]);
  const fieldsNode = document.getElementById("pivotFields");
  fieldsNode.innerHTML = pivotDefinitions[pivotState.dataset].fields
    .filter((field) => !assigned.has(field.key))
    .map((field) => `
      <button class="field-chip${field.type === "metric" ? " is-metric" : ""}" type="button"
        draggable="true" data-field="${escapeHtml(field.key)}" data-type="${field.type}"
        title="${field.type === "metric" ? "Glisser vers Valeur" : "Glisser vers Lignes ou Colonnes"}">
        ${escapeHtml(field.label)}
      </button>
    `).join("");

  ["rows", "columns", "value"].forEach((zone) => {
    const node = document.getElementById(`pivot${zone[0].toUpperCase()}${zone.slice(1)}`);
    node.innerHTML = pivotState[zone].map((key) => {
      const field = findPivotField(key);
      return `<span class="pivot-chip" draggable="true" data-field="${escapeHtml(key)}">
        ${escapeHtml(field?.label || key)}
        <button type="button" data-remove-field="${escapeHtml(key)}" aria-label="Retirer ${escapeHtml(field?.label || key)}">×</button>
      </span>`;
    }).join("");
  });
}

function aggregatePivotValues(values, aggregator) {
  const numbers = values.map(Number).filter(Number.isFinite);
  if (aggregator === "count") return values.length;
  if (!numbers.length) return 0;
  if (aggregator === "avg") return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
  if (aggregator === "max") return Math.max(...numbers);
  return numbers.reduce((sum, value) => sum + value, 0);
}

function renderPivotTable() {
  const table = document.getElementById("pivotTable");
  const valueKey = pivotState.value[0];
  if (!pivotState.rows.length || !valueKey) {
    table.innerHTML = '<tbody><tr><td class="pivot-empty">Ajoutez au moins un champ en Lignes et un indicateur en Valeur.</td></tr></tbody>';
    return;
  }

  const data = dashboardData[pivotState.dataset] || [];
  if (!data.length) {
    table.innerHTML = '<tbody><tr><td class="pivot-empty">Aucune donnée disponible pour les filtres actuels.</td></tr></tbody>';
    return;
  }

  const columnKey = pivotState.columns[0];
  const columns = columnKey
    ? [...new Set(data.map((item) => String(item[columnKey] || "Non renseigné")))].sort()
    : ["Total"];
  const groups = new Map();

  data.forEach((item) => {
    const rowParts = pivotState.rows.map((key) => String(item[key] || "Non renseigné"));
    const rowKey = JSON.stringify(rowParts);
    const column = columnKey ? String(item[columnKey] || "Non renseigné") : "Total";
    if (!groups.has(rowKey)) groups.set(rowKey, { rowParts, values: new Map() });
    const values = groups.get(rowKey).values;
    if (!values.has(column)) values.set(column, []);
    values.get(column).push(item[valueKey]);
  });

  const aggregator = document.getElementById("pivotAggregatorSelect").value;
  const rows = Array.from(groups.values()).sort((a, b) => a.rowParts.join(" ").localeCompare(b.rowParts.join(" "), "fr"));
  const rowLabel = pivotState.rows.map((key) => findPivotField(key)?.label || key).join(" / ");
  const fractionDigits = aggregator === "avg" ? 1 : 0;

  const showTotalColumn = Boolean(columnKey);
  table.innerHTML = `
    <thead><tr><th>${escapeHtml(rowLabel)}</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}${showTotalColumn ? "<th>Total</th>" : ""}</tr></thead>
    <tbody>
      ${rows.map((row) => {
        const cells = columns.map((column) => aggregatePivotValues(row.values.get(column) || [], aggregator));
        const total = aggregatePivotValues(Array.from(row.values.values()).flat(), aggregator);
        return `<tr><td>${row.rowParts.map(escapeHtml).join(" / ")}</td>${cells.map((value) => `<td>${formatNumber(value, fractionDigits)}</td>`).join("")}${showTotalColumn ? `<td><strong>${formatNumber(total, fractionDigits)}</strong></td>` : ""}</tr>`;
      }).join("")}
    </tbody>`;
}

function initializePivotInteractions() {
  const datasetSelect = document.getElementById("pivotDatasetSelect");
  datasetSelect.addEventListener("change", () => {
    pivotState.dataset = datasetSelect.value;
    resetPivot();
  });
  document.getElementById("pivotAggregatorSelect").addEventListener("change", renderPivotTable);
  document.getElementById("resetPivotButton").addEventListener("click", resetPivot);

  document.getElementById("pivotFields").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-field]");
    if (!chip) return;
    assignPivotField(chip.dataset.field, chip.dataset.type === "metric" ? "value" : "rows");
  });

  document.querySelector(".pivot-builder").addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-remove-field]");
    if (!removeButton) return;
    ["rows", "columns", "value"].forEach((zone) => {
      pivotState[zone] = pivotState[zone].filter((key) => key !== removeButton.dataset.removeField);
    });
    renderPivotBuilder();
    renderPivotTable();
  });

  document.querySelector(".pivot-builder").addEventListener("dragstart", (event) => {
    const chip = event.target.closest("[data-field]");
    if (!chip) return;
    event.dataTransfer.setData("text/plain", chip.dataset.field);
    event.dataTransfer.effectAllowed = "move";
  });

  document.querySelectorAll(".pivot-zone").forEach((zone) => {
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.classList.add("is-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-over");
      assignPivotField(event.dataTransfer.getData("text/plain"), zone.dataset.zone);
    });
  });

  resetPivot();
}

function refreshKpis(applicationSummary, utilizationSummary) {
  const totalRequests = applicationSummary.reduce((sum, item) => sum + Number(item.requestCount || 0), 0);
  const totalErrors = applicationSummary.reduce((sum, item) => sum + Number(item.errorCount || 0), 0);
  const totalBoardings = utilizationSummary.reduce((sum, item) => sum + Number(item.totalBoardings || 0), 0);
  const occupancyValues = utilizationSummary.map((item) => Number(item.averageOccupancy)).filter((value) => !Number.isNaN(value));
  const averageOccupancy = occupancyValues.length
    ? occupancyValues.reduce((sum, value) => sum + value, 0) / occupancyValues.length
    : 0;

  document.getElementById("totalRequestsKpi").textContent = formatNumber(totalRequests);
  document.getElementById("totalErrorsKpi").textContent = formatNumber(totalErrors);
  document.getElementById("totalBoardingsKpi").textContent = formatNumber(totalBoardings);
  document.getElementById("avgOccupancyKpi").textContent = formatNumber(averageOccupancy, 1);
}

async function loadDashboard() {
  const token = getStoredToken();
  if (!token) {
    setMessage("Renseignez un token API pour charger les graphiques.", "error");
    return;
  }

  const form = document.getElementById("filtersForm");
  const queryString = buildQueryString(new FormData(form));

  setMessage("Chargement des métriques...");

  try {
    const [applicationSummary, applicationTimeline, lineSummary, lineTimeline] = await Promise.all([
      fetchJson(`/logs/application-usage/summary${queryString}`, token),
      fetchJson(`/logs/application-usage/timeline${queryString}`, token),
      fetchJson(`/logs/line-utilization/summary${queryString}`, token),
      fetchJson(`/logs/line-utilization/timeline${queryString}`, token)
    ]);

    dashboardData = { application: applicationSummary, utilization: lineSummary };
    refreshKpis(applicationSummary, lineSummary);
    fillApplicationTable(applicationSummary);
    fillUtilizationTable(lineSummary);
    renderApplicationTimeline(applicationTimeline);
    renderEndpointsChart(applicationSummary);
    renderUtilizationTimeline(lineTimeline);
    renderRoutesChart(lineSummary);
    renderConsultedRoutes(applicationSummary);
    renderCityBreakdownChart(applicationSummary);
    renderMethodBreakdownChart(applicationSummary);
    renderPivotTable();

    setMessage("Données chargées.", "success");
  } catch (error) {
    setMessage(error.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("logoutButton").addEventListener("click", () => {
    clearStoredToken();
    redirectToLogin();
  });

  const token = getStoredToken();
  if (!token) {
    redirectToLogin();
    return;
  }

  document.getElementById("filtersForm").addEventListener("submit", (event) => {
    event.preventDefault();
    loadDashboard();
  });

  initializePivotInteractions();

  document.getElementById("exportApplicationCsvButton").addEventListener("click", async () => {
    const token = getStoredToken();
    if (!token) {
      setMessage("Enregistrez un token avant export.", "error");
      return;
    }

    try {
      setMessage("Export CSV usage en cours...");
      await downloadFile(`/logs/export/application-usage.csv${getQueryStringFromFilters()}`, token, "application_usage_export.csv");
      setMessage("CSV usage exporte.", "success");
    } catch (error) {
      setMessage(error.message, "error");
    }
  });

  document.getElementById("exportUtilizationCsvButton").addEventListener("click", async () => {
    const token = getStoredToken();
    if (!token) {
      setMessage("Enregistrez un token avant export.", "error");
      return;
    }

    try {
      setMessage("Export CSV frequentation en cours...");
      await downloadFile(`/logs/export/line-utilization.csv${getQueryStringFromFilters()}`, token, "line_utilization_export.csv");
      setMessage("CSV frequentation exporte.", "success");
    } catch (error) {
      setMessage(error.message, "error");
    }
  });

  document.getElementById("exportPdfButton").addEventListener("click", async () => {
    const token = getStoredToken();
    if (!token) {
      setMessage("Enregistrez un token avant export.", "error");
      return;
    }

    try {
      setMessage("Export PDF en cours...");
      await downloadFile(`/logs/export/dashboard.pdf${getQueryStringFromFilters()}`, token, "dashboard_export.pdf");
      setMessage("PDF exporte.", "success");
    } catch (error) {
      setMessage(error.message, "error");
    }
  });

  loadDashboard();
});
