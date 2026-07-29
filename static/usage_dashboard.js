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
      <td>${item.endpoint || "-"}</td>
      <td>${item.method || "-"}</td>
      <td>${item.city || "-"}</td>
      <td>${item.routeId || "-"}</td>
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
      <td>${item.city || "-"}</td>
      <td>${item.routeId || "-"}</td>
      <td>${item.lineName || "-"}</td>
      <td>${item.direction || "-"}</td>
      <td>${formatNumber(item.eventCount)}</td>
      <td>${formatNumber(item.totalBoardings)}</td>
      <td>${item.averageOccupancy == null ? "-" : formatNumber(item.averageOccupancy, 1)}</td>
    </tr>
  `).join("");
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

    refreshKpis(applicationSummary, lineSummary);
    fillApplicationTable(applicationSummary);
    fillUtilizationTable(lineSummary);
    renderApplicationTimeline(applicationTimeline);
    renderEndpointsChart(applicationSummary);
    renderUtilizationTimeline(lineTimeline);
    renderRoutesChart(lineSummary);
    renderCityBreakdownChart(applicationSummary);
    renderMethodBreakdownChart(applicationSummary);

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