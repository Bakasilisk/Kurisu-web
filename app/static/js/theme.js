// Manual light/dark override, layered on top of prefers-color-scheme.
//
// The *boot* half of this lives inline in base.html's <head>: it has to run
// before first paint, or the page flashes the OS theme before switching to
// the stored one. All this file does is wire the toggle button, persist the
// choice, and broadcast it — dashboard.js listens for "themechange" to
// recolour charts, which bake their colours in at construction time.
//
// No stored value means "follow the OS": the data-theme attribute stays off
// and style.css's @media (prefers-color-scheme: dark) block applies.
(function () {
  const STORAGE_KEY = "kurisu-theme";

  function activeTheme() {
    const explicit = document.documentElement.dataset.theme;
    if (explicit === "light" || explicit === "dark") return explicit;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  // Storage can throw (Safari private mode, cookies-blocked): the toggle
  // should still work for the current page even if the choice can't persist.
  function store(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* not persisted */
    }
  }

  function syncButtons(theme) {
    document.querySelectorAll(".theme-toggle").forEach((btn) => {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
    });
  }

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    store(theme);
    syncButtons(theme);
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  function init() {
    syncButtons(activeTheme());
    document.querySelectorAll(".theme-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        apply(activeTheme() === "dark" ? "light" : "dark");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
