// Message-export card on moderation.html. Not loaded by dashboard.js (that's
// Chart.js machinery for the overview page, absent here) — this is its own
// small poller/starter, in the same fetch/error/retry idiom dashboard.js uses
// for its chart boxes (see showBoxError there).
(function () {
  const POLL_MS = 3000;

  function humanBytes(n) {
    if (!n) return "0 B";
    let size = n;
    const units = ["B", "KB", "MB", "GB"];
    for (let i = 0; i < units.length; i++) {
      if (size < 1024 || units[i] === "GB") {
        return units[i] === "B" ? `${Math.round(size)} B` : `${size.toFixed(1)} ${units[i]}`;
      }
      size /= 1024;
    }
    return `${size.toFixed(1)} GB`;
  }

  function minutesUntil(iso) {
    if (!iso) return null;
    const ms = new Date(iso).getTime() - Date.now();
    return Math.max(0, Math.round(ms / 60000));
  }

  function initExport(gid) {
    const section = document.getElementById("export");
    const statusEl = document.getElementById("export-status");
    const actionsEl = section.querySelector(".export-actions");
    const startBtn = document.getElementById("export-start");
    const sel = document.getElementById("export-weeks");
    let pollTimer = null;
    // Tracks the last state we rendered, so a running->idle transition
    // (mid-poll) can be told apart from a page load that starts idle — the
    // former means the bot lost the job (restart), the latter is normal.
    let previousState = statusEl.dataset.state || "idle";

    function clearStatus() {
      while (statusEl.firstChild) statusEl.removeChild(statusEl.firstChild);
    }

    function badge(text, variant) {
      const span = document.createElement("span");
      span.className = `badge badge-${variant}`;
      span.textContent = text;
      return span;
    }

    function para(text) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = text;
      return p;
    }

    function setDownloadLink(show) {
      let link = document.getElementById("export-download");
      if (show) {
        if (!link) {
          link = document.createElement("a");
          link.className = "button";
          link.id = "export-download";
          link.href = `/guild/${gid}/export.csv`;
          link.textContent = "Download CSV";
          actionsEl.appendChild(link);
        }
      } else if (link) {
        link.remove();
      }
    }

    // Rebuilds #export-status from a job doc (or the {"state": "idle"} /
    // {"state": "unavailable"} shorthand) for every state. Never uses
    // innerHTML with server/API-derived text — textContent and DOM building
    // only, per the same rule dashboard.js follows for chart error text.
    function render(job) {
      const state = (job && job.state) || "unavailable";
      statusEl.dataset.state = state;
      clearStatus();
      if (state === "idle") {
        statusEl.appendChild(badge("Idle", "neutral"));
        statusEl.appendChild(para("No export has been run recently."));
      } else if (state === "running") {
        const weeks = job.weeks || 4;
        if (sel) sel.value = String(weeks);
        statusEl.appendChild(badge("Running", "neutral"));
        statusEl.appendChild(para(
          `${weeks}-week scan: ${job.sources_scanned || 0} sources scanned, ${job.sources_skipped || 0} skipped, ` +
          `${(job.messages || 0).toLocaleString()} messages so far…`
        ));
      } else if (state === "done") {
        statusEl.appendChild(badge("Done", "good"));
        const mins = minutesUntil(job.expires_at);
        const expiry = mins === null ? "" : mins > 0 ? ` — expires in ${mins} min` : " — expiring now";
        statusEl.appendChild(para(
          `${job.weeks || 4}-week scan: ${(job.messages || 0).toLocaleString()} messages, ${humanBytes(job.bytes)}${expiry}.`
        ));
      } else if (state === "error") {
        statusEl.appendChild(badge("Error", "critical"));
        statusEl.appendChild(para(job.error || "The export failed."));
      } else if (state === "interrupted") {
        statusEl.appendChild(badge("Interrupted", "critical"));
        statusEl.appendChild(para("The export was interrupted (bot restarted?) — start again."));
      } else {
        statusEl.appendChild(badge("Unavailable", "critical"));
        statusEl.appendChild(para("The export service is unavailable right now."));
      }
      startBtn.disabled = state === "running" || state === "unavailable";
      if (sel) sel.disabled = startBtn.disabled;
      setDownloadLink(state === "done");
      previousState = state === "interrupted" ? "idle" : state;
    }

    function renderMessage(variant, text) {
      clearStatus();
      statusEl.appendChild(badge(variant === "critical" ? "Error" : "Notice", variant));
      statusEl.appendChild(para(text));
    }

    function renderFetchError(retry) {
      clearStatus();
      statusEl.appendChild(badge("Error", "critical"));
      statusEl.appendChild(para("Couldn't reach the export service."));
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "button";
      btn.textContent = "Retry";
      btn.addEventListener("click", retry);
      statusEl.appendChild(btn);
      startBtn.disabled = false;
      if (sel) sel.disabled = false;
    }

    function schedulePoll() {
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = setTimeout(fetchStatus, POLL_MS);
    }

    async function fetchStatus() {
      let resp;
      try {
        resp = await fetch(`/guild/${gid}/data/export`);
      } catch (e) {
        renderFetchError(fetchStatus);
        return;
      }
      let job;
      try {
        job = await resp.json();
      } catch (e) {
        renderFetchError(fetchStatus);
        return;
      }
      // Lost-job detection: we were polling a running job, and it's simply
      // gone (not "error") — the bot restarted mid-export and forgot it.
      if (previousState === "running" && job.state === "idle") {
        render({ state: "interrupted" });
        return;
      }
      render(job);
      if (job.state === "running") schedulePoll();
    }

    async function start() {
      startBtn.disabled = true;
      if (sel) sel.disabled = true;
      let resp;
      try {
        resp = await fetch(`/guild/${gid}/data/export`, {
          method: "POST",
          headers: { "X-Requested-With": "fetch", "Content-Type": "application/json" },
          body: JSON.stringify({ weeks: sel ? Number(sel.value) : undefined }),
        });
      } catch (e) {
        renderFetchError(start);
        return;
      }
      const contentType = resp.headers.get("content-type") || "";
      if (resp.redirected || !contentType.includes("application/json")) {
        renderMessage("critical", "Session expired — reload the page.");
        return;
      }
      let data;
      try {
        data = await resp.json();
      } catch (e) {
        renderFetchError(start);
        return;
      }
      if (resp.status === 202) {
        render(data);
        if (data.state === "running") schedulePoll();
        return;
      }
      if (resp.status === 409) {
        // The returned job carries the *running* job's weeks, not the one
        // just requested — call that out instead of letting the selection
        // silently appear to revert.
        const runningJob = data.job || { state: "running" };
        render(runningJob);
        const weeks = runningJob.weeks || 4;
        statusEl.appendChild(para(
          `An export was already running — ${weeks} week${weeks === 1 ? "" : "s"} — your selection wasn't started.`
        ));
        schedulePoll();
        return;
      }
      if (resp.status === 403) {
        const msg = data.error === "export disabled"
          ? "Exports are disabled in this server."
          : "You're not permitted to export this server.";
        renderMessage("critical", msg);
        startBtn.disabled = false;
        if (sel) sel.disabled = false;
        return;
      }
      if (resp.status === 503) {
        render({ state: "unavailable" });
        return;
      }
      renderMessage("critical", (data && data.error) || "Couldn't start the export.");
      startBtn.disabled = false;
      if (sel) sel.disabled = false;
    }

    startBtn.addEventListener("click", start);
    if (previousState === "running") schedulePoll();
  }

  window.initExport = initExport;
})();
