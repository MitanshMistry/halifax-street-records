(() => {
  const body = document.body;
  const districtPattern = /^[0-9]+$/;
  const storageKey = "hrmRoadRecordsDistrict";

  function showDistrictError(message) {
    const status = document.getElementById("district-status");
    if (status) status.textContent = message;
  }

  function saveDistrict(value) {
    try {
      if (value === "all") localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, value);
    } catch (error) {
      console.warn("District preference could not be saved in this browser.", error);
    }
  }

  function routeFor(value) {
    const basePath = body.dataset.basePath || "";
    return value === "all" ? `${basePath}index.html?district=all` : `${basePath}district-${value}/`;
  }

  async function fetchPage(url) {
    const response = await fetch(url, { headers: { Accept: "text/html" } });
    if (!response.ok) throw new Error(`Could not load the district page (HTTP ${response.status}).`);
    const markup = await response.text();
    const next = new DOMParser().parseFromString(markup, "text/html");
    const nextMain = next.querySelector("#main");
    if (!nextMain || !next.querySelector(".site-header") || !next.querySelector(".site-footer")) {
      throw new Error("The requested district page is incomplete.");
    }
    return next;
  }

  async function navigateDistrict(value, replaceHistory) {
    const status = document.getElementById("district-status");
    if (status) status.textContent = "Loading district summary…";
    const destination = routeFor(value);
    try {
      const next = await fetchPage(destination);
      const nextMain = next.querySelector("#main");
      document.querySelector(".site-header").replaceWith(next.querySelector(".site-header"));
      document.querySelector("#main").replaceWith(nextMain);
      document.querySelector(".site-footer").replaceWith(next.querySelector(".site-footer"));
      const nextBanner = next.querySelector("#stale-banner");
      const currentBanner = document.querySelector("#stale-banner");
      if (nextBanner && currentBanner) currentBanner.replaceWith(nextBanner);
      document.title = next.title;
      const description = document.querySelector('meta[name="description"]');
      const nextDescription = next.querySelector('meta[name="description"]');
      if (description && nextDescription) description.content = nextDescription.content;
      body.dataset.basePath = next.body.dataset.basePath || "";
      body.dataset.selectedDistrict = next.body.dataset.selectedDistrict || "all";
      saveDistrict(value);
      if (replaceHistory) history.replaceState({ district: value }, "", destination);
      else history.pushState({ district: value }, "", destination);
      window.scrollTo(0, 0);
      initialize();
    } catch (error) {
      console.error("Could not change the selected district.", error);
      showDistrictError("We couldn’t load that district. Please try again or choose a district link below.");
    }
  }

  function configurePicker() {
    const picker = document.getElementById("district-picker");
    if (!picker) return;
    picker.disabled = false;
    const submit = document.getElementById("district-submit");
    if (submit) {
      submit.disabled = false;
      submit.hidden = false;
    }
  }

  function configureStaleBanner() {
    const banner = document.getElementById("stale-banner");
    const pullDate = body.dataset.pullDate;
    if (!banner || !pullDate) return;
    const parsed = Date.parse(`${pullDate}T00:00:00Z`);
    if (!Number.isFinite(parsed)) {
      console.error("The published HRM data date is invalid.");
      banner.hidden = false;
      banner.textContent = "The HRM data date could not be read. Check About the estimates before relying on these numbers.";
      return;
    }
    const ageDays = Math.floor((Date.now() - parsed) / 86400000);
    const staleDays = Number(body.dataset.staleDays || 180);
    banner.hidden = ageDays <= staleDays;
  }

  function configureShare() {
    const share = document.getElementById("share-link");
    if (share && navigator.share) share.hidden = false;
  }

  function configureDistrictQuery() {
    const picker = document.getElementById("district-picker");
    const currentDistrict = body.dataset.selectedDistrict || "all";
    if (currentDistrict !== "all") {
      if (picker) picker.value = currentDistrict;
      saveDistrict(currentDistrict);
      return;
    }
    const requested = new URLSearchParams(location.search).get("district");
    if (requested === "all") {
      saveDistrict("all");
      if (picker) picker.value = "all";
      return;
    }
    const saved = requested || (() => {
      try {
        return localStorage.getItem(storageKey);
      } catch (error) {
        console.warn("District preference could not be read in this browser.", error);
        return null;
      }
    })();
    if (saved && districtPattern.test(saved) && picker && [...picker.options].some(option => option.value === saved)) {
      if (picker.value !== saved || !body.dataset.selectedDistrict || body.dataset.selectedDistrict === "all") {
        navigateDistrict(saved, true);
      } else {
        picker.value = saved;
      }
    }
  }

  function initialize() {
    body.classList.remove("no-js");
    body.classList.add("js");
    configurePicker();
    configureStaleBanner();
    configureShare();
    configureDistrictQuery();
  }

  document.addEventListener("submit", event => {
    if (event.target.id === "district-form") {
      event.preventDefault();
      const value = document.getElementById("district-picker").value;
      if (value === "all" || districtPattern.test(value)) navigateDistrict(value, false);
      else showDistrictError("Choose a district from the list.");
    }
    if (event.target.id === "compare-form") {
      event.preventDefault();
      const input = document.getElementById("days-waiting");
      const result = document.getElementById("compare-result");
      const value = Number(input.value);
      if (!Number.isSafeInteger(value) || value < 0 || value > 3650) {
        result.textContent = "Enter a whole number from 0 to 3,650.";
        input.focus();
        return;
      }
      const days = document.querySelector(".answer-data")?.dataset.halfDays;
      result.textContent = days
        ? `You entered ${value} ${value === 1 ? "day" : "days"}; HRM had recorded a close date for about half of past reports within ${days} ${days === "1" ? "day" : "days"}, but this does not predict yours.`
        : `You entered ${value} ${value === 1 ? "day" : "days"}; these records cannot say when yours will close.`;
    }
  });

  document.addEventListener("click", async event => {
    const trend = event.target.closest("[data-trend]");
    if (trend) {
      const selected = trend.dataset.trend;
      document.querySelectorAll("[data-trend]").forEach(button => {
        const active = button.dataset.trend === selected;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      document.querySelectorAll("[data-trend-view]").forEach(view => {
        view.classList.toggle("is-active", view.dataset.trendView === selected);
      });
      return;
    }

    const copy = event.target.closest("#copy-link");
    const share = event.target.closest("#share-link");
    const status = document.getElementById("share-status");
    if (copy) {
      try {
        await navigator.clipboard.writeText(location.href);
        if (status) status.textContent = "Link copied.";
      } catch (error) {
        console.error("Could not copy the page link.", error);
        if (status) status.textContent = "Could not copy the link. Copy the page address from your browser.";
      }
    } else if (share && navigator.share) {
      try {
        await navigator.share({ title: document.title, url: location.href });
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error("Could not share the page.", error);
          if (status) status.textContent = "Could not open the share sheet.";
        }
      }
    }
  });

  window.addEventListener("popstate", () => {
    const match = location.pathname.match(/district-([0-9]+)\/?$/);
    const value = match ? match[1] : "all";
    navigateDistrict(value, true);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
