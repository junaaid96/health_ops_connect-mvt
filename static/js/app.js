/* HealthOPS Connect — small progressive-enhancement helpers. */
(function () {
  "use strict";

  const HealthOps = {
    toggleTheme() {
      const dark = document.documentElement.classList.toggle("dark");
      try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) {}
      document.dispatchEvent(new CustomEvent("themechange", { detail: { dark } }));
    },

    /** Live countdown text like "in 2 h 15 min" for elements with data-countdown="<iso>". */
    tickCountdowns() {
      document.querySelectorAll("[data-countdown]").forEach((el) => {
        const target = new Date(el.dataset.countdown).getTime();
        const diff = Math.round((target - Date.now()) / 60000);
        let text;
        if (diff <= 0 && diff > -30) text = "now";
        else if (diff <= -30) text = "earlier today";
        else if (diff < 60) text = `in ${diff} min`;
        else if (diff < 60 * 24) text = `in ${Math.floor(diff / 60)} h ${diff % 60} min`;
        else { const d = Math.round(diff / 1440); text = `in ${d} day${d === 1 ? "" : "s"}`; }
        el.textContent = text;
      });
    },
  };

  window.HealthOps = HealthOps;

  document.addEventListener("DOMContentLoaded", () => {
    HealthOps.tickCountdowns();
    setInterval(HealthOps.tickCountdowns, 30000);
  });
  document.addEventListener("htmx:afterSwap", () => HealthOps.tickCountdowns());

  // Session expired / server error during an htmx request: fall back to a full reload
  // so the user sees the login page or error page instead of a half-swapped fragment.
  document.addEventListener("htmx:responseError", (event) => {
    if ([401, 403].includes(event.detail.xhr.status)) window.location.reload();
  });
})();
