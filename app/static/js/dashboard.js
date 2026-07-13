// Colors follow the dataviz skill's reference palette (see style.css's :root
// tokens, which this reads at render time so it tracks the active theme).
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function isDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function formatVoiceSeconds() {
  document.querySelectorAll("[data-seconds]").forEach((el) => {
    const s = parseInt(el.dataset.seconds, 10) || 0;
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    el.textContent = h ? `${h}h ${m}m` : `${m}m`;
  });
}

const charts = {};

function destroyChart(key) {
  if (charts[key]) {
    charts[key].destroy();
    delete charts[key];
  }
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`request failed: ${resp.status}`);
  return resp.json();
}

function chartTextOptions() {
  return {
    color: cssVar("--text-secondary"),
    grid: { color: cssVar("--border") },
  };
}

// Single-series bar charts get no legend (the box title already names the
// series) — per the dataviz skill, a legend box is only added at >=2 series.
function renderBarChart(canvasId, key, labels, data, label, colors) {
  destroyChart(key);
  const ctx = document.getElementById(canvasId).getContext("2d");
  const axis = chartTextOptions();
  charts[key] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label, data, backgroundColor: colors || cssVar("--series-1"), borderRadius: 4 }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: axis.color }, grid: { display: false } },
        y: { ticks: { color: axis.color }, grid: { color: axis.grid.color } },
      },
    },
  });
}

function renderGrowthChart(growth) {
  destroyChart("growth");
  const ctx = document.getElementById("chart-growth").getContext("2d");
  const axis = chartTextOptions();
  const netColor = growth.net >= 0 ? cssVar("--good") : cssVar("--critical");
  charts.growth = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["Joins", "Leaves", "Net"],
      datasets: [{
        label: "Members",
        data: [growth.joins, -growth.leaves, growth.net],
        backgroundColor: [cssVar("--series-1"), cssVar("--series-6"), netColor],
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: axis.color }, grid: { display: false } },
        y: { ticks: { color: axis.color }, grid: { color: axis.grid.color } },
      },
    },
  });
}

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerp(a, b, t) {
  return Math.round(a + (b - a) * t);
}

// Piecewise-linear interpolation across the sequential ramp defined in
// style.css (--seq-0..--seq-5) — low->high per the active theme's direction.
function sequentialColor(t) {
  const ramp = [0, 1, 2, 3, 4, 5].map((i) => hexToRgb(cssVar(`--seq-${i}`)));
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (ramp.length - 1);
  const i0 = Math.floor(scaled);
  const i1 = Math.min(ramp.length - 1, i0 + 1);
  const localT = scaled - i0;
  const c0 = ramp[i0];
  const c1 = ramp[i1];
  const rgb = [0, 1, 2].map((i) => lerp(c0[i], c1[i], localT));
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function renderHeatmap(container, grid, weekdayLabels) {
  const vmax = Math.max(1, ...grid.flat());
  let html = "<table class='heatmap'><thead><tr><th></th>";
  for (let h = 0; h < 24; h++) html += `<th>${h}</th>`;
  html += "</tr></thead><tbody>";
  for (let wd = 0; wd < 7; wd++) {
    html += `<tr><th>${weekdayLabels[wd]}</th>`;
    for (let h = 0; h < 24; h++) {
      const v = grid[wd][h];
      const color = sequentialColor(v / vmax);
      html += `<td style="background:${color}" title="${weekdayLabels[wd]} ${h}:00 — ${v} messages"></td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  container.innerHTML = html;
}

async function loadDashboardData(gid, period) {
  const [top, channels, voice, growth, activity] = await Promise.all([
    fetchJSON(`/guild/${gid}/data/top?period=${period}`),
    fetchJSON(`/guild/${gid}/data/channels?period=${period}`),
    fetchJSON(`/guild/${gid}/data/voice?period=${period}`),
    fetchJSON(`/guild/${gid}/data/growth?period=${period}`),
    fetchJSON(`/guild/${gid}/data/activity?period=${period}`),
  ]);

  const topN = top.entries.slice(0, 10);
  renderBarChart("chart-top", "top", topN.map((e) => e.user.name), topN.map((e) => e.count), "Messages");

  const chN = channels.entries.slice(0, 10);
  renderBarChart("chart-channels", "channels", chN.map((e) => e.channel.name), chN.map((e) => e.count), "Messages");

  const voiceN = voice.entries.slice(0, 10);
  renderBarChart(
    "chart-voice", "voice", voiceN.map((e) => e.user.name), voiceN.map((e) => Math.round(e.seconds / 60)), "Minutes"
  );

  renderGrowthChart(growth);
  renderHeatmap(document.getElementById("activity-heatmap"), activity.grid, activity.weekday_labels);
}

function initDashboard(gid) {
  formatVoiceSeconds();
  const select = document.getElementById("period-select");
  const load = () => loadDashboardData(gid, select.value);
  select.addEventListener("change", load);
  load();
}
