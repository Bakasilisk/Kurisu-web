// Colors follow the dataviz skill's reference palette (see style.css's :root
// tokens, which this reads at render time so it tracks the active theme).
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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

// Last successful payload per box, plus the box list it came from. Charts
// read their colours from CSS custom properties at *construction* time, so a
// theme switch would otherwise leave light-mode axes on a dark page. Keeping
// the data lets initDashboard re-render straight from cache on "themechange"
// — no refetch, and no loading skeleton flashing over a chart that's already
// on screen.
const lastData = {};
let currentBoxes = [];

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
// `hrefs` (optional, one per bar) makes each bar a link: click navigates,
// hover shows the pointer. Charts are canvas, so this is a convenience on
// top of a real <a> list, never the only way in.
function renderBarChart(canvasId, key, labels, data, label, colors, hrefs) {
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
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: axis.color }, grid: { display: false } },
        y: { ticks: { color: axis.color }, grid: { color: axis.grid.color } },
      },
      onClick: hrefs ? (evt, els) => {
        if (els.length && hrefs[els[0].index]) window.location.href = hrefs[els[0].index];
      } : undefined,
      onHover: hrefs ? (evt, els) => {
        evt.native.target.style.cursor = els.length ? "pointer" : "default";
      } : undefined,
    },
  });
}

// "2026-09-10" -> UTC midnight Date. Parsed by hand so the local timezone
// can never shift a bucket onto the neighbouring day.
function parseDay(day) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function dayKey(date) {
  return date.toISOString().slice(0, 10);
}

// The bot's series endpoints return only buckets that have data. Fill the
// gaps with zeros from `start` (or the first bucket, when the period is
// "all" and start is null) through today, one step per day or per week —
// week keys are Mondays on both sides, so stepping 7 days from a Monday
// lands on the next bucket key exactly. Returns {labels, values: {k: [...]}}.
function fillSeries(series, bucket, start, valueKeys) {
  const byDay = new Map(series.map((p) => [p.day, p]));
  const values = Object.fromEntries(valueKeys.map((k) => [k, []]));
  const labels = [];
  const first = start || (series.length ? series[0].day : null);
  if (!first) return { labels, values };
  const step = bucket === "week" ? 7 : 1;
  const now = new Date();
  let end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const last = series.length ? parseDay(series[series.length - 1].day) : null;
  if (last && last > end) end = last;
  for (let d = parseDay(first); d <= end; d = new Date(d.getTime() + step * 86400000)) {
    const key = dayKey(d);
    const point = byDay.get(key);
    labels.push(key);
    valueKeys.forEach((k) => values[k].push(point ? point[k] || 0 : 0));
  }
  return { labels, values };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDay(key, withYear) {
  const d = parseDay(key);
  const base = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  return withYear ? `${base} ${d.getUTCFullYear()}` : base;
}

// Time-series line chart. `datasets` items are
// {label, data, color: "--series-1", axis: "y" | "y1", dashed}; colours are
// token *names*, resolved here at render time so a theme switch re-render
// picks up the new palette. A second axis ("y1") is drawn on the right only
// when some dataset asks for it, and the legend only appears at >=2 series.
// `bucket` only shapes the tooltip title ("Week of …").
function renderLineChart(canvasId, key, labels, datasets, bucket) {
  destroyChart(key);
  const ctx = document.getElementById(canvasId).getContext("2d");
  const axis = chartTextOptions();
  const spansYears = labels.length > 1 && labels[0].slice(0, 4) !== labels[labels.length - 1].slice(0, 4);
  const dense = labels.length > 60;
  const scales = {
    x: {
      ticks: {
        color: axis.color,
        maxRotation: 0,
        autoSkip: true,
        autoSkipPadding: 16,
        maxTicksLimit: 8,
        callback: (value, index) => shortDay(labels[index], spansYears),
      },
      grid: { display: false },
    },
    y: { beginAtZero: true, ticks: { color: axis.color, precision: 0 }, grid: { color: axis.grid.color } },
  };
  if (datasets.some((d) => d.axis === "y1")) {
    scales.y1 = {
      position: "right",
      beginAtZero: true,
      ticks: { color: axis.color },
      grid: { display: false },
    };
  }
  charts[key] = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map((d) => {
        const color = cssVar(d.color);
        return {
          label: d.label,
          data: d.data,
          yAxisID: d.axis || "y",
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          borderDash: d.dashed ? [6, 4] : [],
          pointRadius: dense ? 0 : 2,
          pointHoverRadius: 4,
          // monotone: smooth, but never overshoots below a zero bucket
          cubicInterpolationMode: "monotone",
        };
      }),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: datasets.length > 1,
          labels: { color: axis.color, boxWidth: 12, boxHeight: 2 },
        },
        tooltip: {
          callbacks: {
            title: (items) => (bucket === "week" ? "Week of " : "") + shortDay(labels[items[0].dataIndex], true),
          },
        },
      },
      scales,
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
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: axis.color }, grid: { display: false } },
        y: { ticks: { color: axis.color }, grid: { color: axis.grid.color } },
      },
    },
  });
  const caption = document.getElementById("growth-caption");
  if (caption) caption.textContent = `${growth.messages.toLocaleString()} messages this period`;
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

function renderHeatmap(container, activity) {
  const grid = activity.grid;
  const weekdayLabels = activity.weekday_labels;
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

  const caption = document.getElementById("activity-caption");
  if (caption) {
    // Peak fields are 0 (not null) when there's no activity — gate on total.
    caption.textContent = activity.total
      ? `Peak: ${weekdayLabels[activity.peak_weekday]} ${String(activity.peak_hour).padStart(2, "0")}:00 · ${activity.total.toLocaleString()} messages`
      : "No activity in this period";
  }
}

// Ranked lists are truncated server-side (the bot API's `limit` param) so a
// large guild doesn't ship its full member list just to draw a 10-bar chart.
const TOP_N = 10;

// One entry per independently-loadable dashboard box: which DOM box holds
// it, how to fetch it, and how to render a successful response. Driving
// Promise.allSettled off this list (rather than one big Promise.all) means
// one dead endpoint leaves the other boxes' charts intact instead of
// blanking all four — see plan item 4.
function dashboardBoxes(gid, period) {
  return [
    {
      key: "top",
      box: document.getElementById("chart-top").closest(".chart-box"),
      fetch: () => fetchJSON(`/guild/${gid}/data/top?period=${period}&limit=${TOP_N}`),
      render: (data) => {
        const entries = data.entries;
        renderBarChart("chart-top", "top", entries.map((e) => e.user.name), entries.map((e) => e.count), "Messages");
      },
    },
    {
      key: "channels",
      box: document.getElementById("chart-channels").closest(".chart-box"),
      fetch: () => fetchJSON(`/guild/${gid}/data/channels?period=${period}&limit=${TOP_N}`),
      render: (data) => {
        const entries = data.entries;
        const hrefs = entries.map((e) => `/guild/${gid}/channel/${e.channel.id}`);
        renderBarChart(
          "chart-channels", "channels", entries.map((e) => e.channel.name), entries.map((e) => e.count), "Messages", null, hrefs
        );
        renderChannelLinks(document.getElementById("channel-links"), entries, hrefs);
      },
    },
    {
      key: "voice",
      box: document.getElementById("chart-voice").closest(".chart-box"),
      fetch: () => fetchJSON(`/guild/${gid}/data/voice?period=${period}&limit=${TOP_N}`),
      render: (data) => {
        const entries = data.entries;
        renderBarChart(
          "chart-voice", "voice", entries.map((e) => e.user.name), entries.map((e) => Math.round(e.seconds / 60)), "Minutes"
        );
      },
    },
    {
      key: "growth",
      box: document.getElementById("chart-growth").closest(".chart-box"),
      fetch: () => fetchJSON(`/guild/${gid}/data/growth?period=${period}`),
      render: (data) => renderGrowthChart(data),
    },
    {
      key: "activity",
      box: document.getElementById("activity-heatmap").closest(".activity"),
      fetch: () => fetchJSON(`/guild/${gid}/data/activity?period=${period}`),
      render: (data) => renderHeatmap(document.getElementById("activity-heatmap"), data),
    },
  ];
}

// The real way into a channel page from the dashboard: one <a> per bar,
// under the chart. (Bar clicks also navigate, but a canvas isn't
// keyboard-reachable.) Built with DOM calls, not innerHTML — channel names
// come from Discord and aren't ours to trust.
function renderChannelLinks(list, entries, hrefs) {
  if (!list) return;
  list.replaceChildren(...entries.map((e, i) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = hrefs[i];
    a.textContent = `#${e.channel.name}`;
    li.appendChild(a);
    return li;
  }));
}

function clearBoxState(box) {
  box.classList.remove("is-loading");
  const err = box.querySelector(".chart-error");
  if (err) err.remove();
}

function showBoxError(box, entry) {
  clearBoxState(box);
  const err = document.createElement("div");
  err.className = "chart-error";
  err.innerHTML = `<p>Couldn't load this chart.</p><button type="button" class="button chart-retry">Retry</button>`;
  err.querySelector(".chart-retry").addEventListener("click", () => loadOne(entry));
  box.appendChild(err);
}

async function loadOne(entry) {
  entry.box.classList.add("is-loading");
  const existingErr = entry.box.querySelector(".chart-error");
  if (existingErr) existingErr.remove();
  try {
    const data = await entry.fetch();
    clearBoxState(entry.box);
    lastData[entry.key] = data;
    entry.render(data);
  } catch (e) {
    showBoxError(entry.box, entry);
  }
}

// Load a set of boxes in parallel, disabling the select that drives them
// while they're in flight. Each page has exactly one runner (one select ->
// one box list), because currentBoxes is what the theme re-render walks.
async function runBoxes(boxes, select) {
  if (select) select.disabled = true;
  currentBoxes = boxes;
  const results = await Promise.allSettled(boxes.map((entry) => loadOne(entry)));
  if (select) select.disabled = false;
  return results;
}

async function loadDashboardData(gid, period) {
  return runBoxes(dashboardBoxes(gid, period), document.getElementById("period-select"));
}

// Re-draw every box that has cached data, so charts pick up the new theme's
// tokens. Boxes still loading or showing an error are skipped — they'll read
// the current tokens when they next render anyway.
function rerenderForTheme() {
  currentBoxes.forEach((entry) => {
    if (entry.key in lastData) entry.render(lastData[entry.key]);
  });
}

function initDashboard(gid) {
  formatVoiceSeconds();
  const select = document.getElementById("period-select");
  const load = () => loadDashboardData(gid, select.value);
  select.addEventListener("change", load);
  load();
}

// Several boxes fed by one payload (the channel page's three charts) share
// one request per load. A failure clears the memo so a box's Retry button
// actually refetches instead of replaying the rejected promise.
function sharedFetch(url) {
  let pending = null;
  return () => {
    if (!pending) pending = fetchJSON(url).catch((e) => { pending = null; throw e; });
    return pending;
  };
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function bucketCaption(data) {
  return data.bucket === "week" ? "Weekly totals, weeks starting Monday" : "Daily totals";
}

function channelBoxes(gid, cid, period) {
  const fetchDetail = sharedFetch(`/guild/${gid}/data/channel/${cid}?period=${period}&limit=${TOP_N}`);
  return [
    {
      key: "channel-series",
      box: document.getElementById("chart-channel-series").closest(".chart-box"),
      fetch: fetchDetail,
      render: (data) => {
        const filled = fillSeries(data.series, data.bucket, data.start, ["count"]);
        renderLineChart("chart-channel-series", "channel-series", filled.labels, [
          { label: "Messages", data: filled.values.count, color: "--series-1" },
        ], data.bucket);
        const caption = document.getElementById("channel-series-caption");
        if (caption) caption.textContent = `${bucketCaption(data)} · ${data.totals.messages.toLocaleString()} messages`;
      },
    },
    {
      key: "channel-top",
      box: document.getElementById("chart-channel-top").closest(".chart-box"),
      fetch: fetchDetail,
      render: (data) => {
        const top = data.top;
        renderBarChart(
          "chart-channel-top", "channel-top", top.map((e) => e.user.name), top.map((e) => e.count), "Messages", null,
          top.map((e) => `/guild/${gid}/member/${e.user.id}`)
        );
      },
    },
    {
      key: "channel-weekdays",
      box: document.getElementById("chart-channel-weekdays").closest(".chart-box"),
      fetch: fetchDetail,
      render: (data) => renderBarChart("chart-channel-weekdays", "channel-weekdays", WEEKDAYS, data.weekdays, "Messages"),
    },
  ];
}

function initChannelPage(gid, cid) {
  const select = document.getElementById("period-select");
  const load = () => runBoxes(channelBoxes(gid, cid, select.value), select);
  select.addEventListener("change", load);
  load();
}

// Member activity over time (member.html and me.html). `url` is the page's
// own proxy route — /guild/{id}/data/member/{uid}/series for an admin,
// /me/{id}/data/series for the self-view, whose uid the server takes from
// the session. Messages on the left axis, voice hours dashed on the right.
function initProfileSeries(url) {
  const select = document.getElementById("profile-series-period");
  const box = document.getElementById("chart-profile-series").closest(".chart-box");
  const load = () => runBoxes([{
    key: "profile-series",
    box,
    fetch: () => fetchJSON(`${url}?period=${select.value}`),
    render: (data) => {
      const filled = fillSeries(data.series, data.bucket, data.start, ["messages", "voice_seconds"]);
      renderLineChart("chart-profile-series", "profile-series", filled.labels, [
        { label: "Messages", data: filled.values.messages, color: "--series-1" },
        {
          label: "Voice (hours)",
          data: filled.values.voice_seconds.map((s) => Math.round(s / 360) / 10),
          color: "--series-6",
          axis: "y1",
          dashed: true,
        },
      ], data.bucket);
      const caption = document.getElementById("profile-series-caption");
      if (caption) caption.textContent = bucketCaption(data);
    },
  }], select);
  select.addEventListener("change", load);
  load();
}

// Module level, not inside an init function: every chart page re-renders
// from cache on a theme switch, through whichever runner it has.
document.addEventListener("themechange", rerenderForTheme);
