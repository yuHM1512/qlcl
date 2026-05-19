const state = {
  dimension: "unit",
  kpiScope: "recent",
  year: "",
  month: "",
  unit: "",
};

const LOWER_BETTER_KEYS = new Set(["ncr", "ncr_ratio", "ncr_rate", "defect_ratio", "defect_rate", "ncr_ratio_4w"]);

const KPI_CARD_ICONS = {
  ncr_ratio_4w: `
    <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 12h4l2-5 4 10 2-5h4" />
      <path d="M7 4v2" />
      <path d="M17 18v2" />
    </svg>
  `,
  ncr_ratio: `
    <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 19h16" />
      <path d="M7 15l4-4 3 3 4-6" />
      <path d="M18 8h-3V5" />
    </svg>
  `,
  on_time_ratio: `
    <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v5l3 2" />
    </svg>
  `,
  cap_completion_ratio: `
    <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 7L9 18l-5-5" />
    </svg>
  `,
};

const KPI_CARD_NOTES = {
  on_time_ratio: "Đúng kế hoạch = Không quá 7 ngày kể từ ngày lập KH",
};

const CHART_NOTES = {
  onTimeChart: "Đúng kế hoạch = Không quá 7 ngày kể từ ngày lập KH",
};

function safeText(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function safeAttr(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function chartTone(value, target, mode = "higher-better") {
  if (mode === "lower-better") {
    return value <= target ? "bg-emerald-400" : "bg-rose-600";
  }
  return value >= target ? "bg-emerald-400" : "bg-rose-600";
}

function formatPercentValue(value, decimals = 1) {
  return `${(Number(value || 0) * 100).toFixed(decimals)}%`;
}

function buildChart(containerId, title, subtitle, legendLabel, legendTarget, items, mode = "higher-better") {
  const wrap = document.getElementById(containerId);
  wrap.innerHTML = "";
  const helperNote = CHART_NOTES[containerId];

  if (!items.length) {
    wrap.innerHTML = `
      <div class="rounded-[1.75rem] bg-surface-container-lowest p-8 shadow-[0px_20px_40px_rgba(25,28,29,0.05)]">
        <div class="text-sm text-on-surface-variant">Chưa có dữ liệu.</div>
      </div>
    `;
    return;
  }

  const targetVal = Number(items[0]?.target || 0);
  const maxActual = Math.max(...items.map((item) => Number(item.actual || 0)), 0);
  const maxScale = Math.max(maxActual, targetVal, 0.01);
  const linePercent = Math.min(99, (targetVal / maxScale) * 100);

  const chart = document.createElement("section");
  chart.className = "rounded-2xl bg-white p-6 shadow-[0px_20px_40px_rgba(25,28,29,0.05)] overflow-hidden";
  chart.innerHTML = `
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="inline-flex items-center rounded-xl bg-[#0056d2] px-4 py-2 font-manrope text-sm font-extrabold tracking-tight text-white">${safeText(title)}</div>
        <div class="mt-1.5 text-[10px] uppercase tracking-widest text-on-surface-variant">${safeText(subtitle)}</div>
        ${helperNote ? `<div class="mt-2 text-xs text-on-surface-variant">${safeText(helperNote)}</div>` : ""}
      </div>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
        <div class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
          <span class="h-2.5 w-2.5 -ml-1 rounded-full bg-rose-500"></span>
          <span>${safeText(legendLabel)}</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="inline-block w-5 border-t-2 border-amber-400"></span>
          <span>${safeText(legendTarget)}</span>
        </div>
      </div>
    </div>
    <div class="mt-4">
      <div class="relative h-44 border-b border-slate-100">
        <div
          class="absolute inset-x-0 z-20 cursor-help border-t-[3px] border-amber-400"
          style="bottom: ${linePercent}%"
          title="${safeAttr(legendTarget)}"
        >
          <span class="absolute right-0 -top-5 rounded bg-amber-400 px-2 py-0.5 text-[10px] font-bold text-white whitespace-nowrap">${safeText(legendTarget)}</span>
        </div>
        <div class="absolute inset-0 flex items-end justify-around px-2" id="${containerId}-bars"></div>
      </div>
      <div class="mt-2 flex justify-around px-2" id="${containerId}-labels"></div>
    </div>
  `;

  wrap.appendChild(chart);
  const barsEl = chart.querySelector(`#${containerId}-bars`);
  const labelsEl = chart.querySelector(`#${containerId}-labels`);

  items.forEach((item) => {
    const pct = Number(item.actual) > 0 ? Math.max(2, (Number(item.actual) / maxScale) * 100) : 0;
    const tone = chartTone(item.actual, item.target, mode);

    const bar = document.createElement("div");
    bar.className = `relative mx-1 h-full flex-1 ${items.length <= 6 ? "max-w-[3.5rem]" : "max-w-[2.5rem]"}`;
    const tooltip = `${item.unit}: ${item.actual_label}`;
    bar.innerHTML = `
      <div
        class="absolute inset-x-0 bottom-0 h-full cursor-help rounded-lg bg-surface-container-low"
        title="${safeAttr(tooltip)}"
      ></div>
      <div
        class="absolute inset-x-0 bottom-0 cursor-help rounded-lg ${tone} transition-all duration-500"
        style="height:${pct}%"
        title="${safeAttr(tooltip)}"
      ></div>
      <div class="pointer-events-none absolute inset-x-1 bottom-1 rounded-md bg-white/90 px-1 py-0.5 text-center text-[10px] font-semibold text-on-surface shadow-sm">
        ${safeText(item.actual_label)}
      </div>
    `;
    barsEl.appendChild(bar);

    const label = document.createElement("div");
    label.className = "flex-1 text-center text-[10px] uppercase tracking-wider text-on-surface-variant";
    label.textContent = item.unit;
    labelsEl.appendChild(label);
  });
}

function kpiTone(card) {
  if (!card.value && card.value !== 0) {
    return { text: "text-on-surface", dot: "bg-slate-300" };
  }
  const value = Number(card.value);
  const target = Number(card.target);
  const isLowerBetter = card.mode === "lower-better" || LOWER_BETTER_KEYS.has(card.key);
  const good = isLowerBetter ? value <= target : value >= target;
  return good
    ? { text: "text-emerald-600", dot: "bg-emerald-400" }
    : { text: "text-rose-600", dot: "bg-rose-400" };
}

function renderCards(cards) {
  const wrap = document.getElementById("kpiCards");
  wrap.innerHTML = "";

  cards.forEach((card) => {
    const tone = kpiTone(card);
    const iconMarkup = KPI_CARD_ICONS[card.key] || KPI_CARD_ICONS.ncr_ratio;
    const helperNote = KPI_CARD_NOTES[card.key];
    const node = document.createElement("article");
    node.className = "flex min-h-[14rem] flex-col justify-between rounded-[1.75rem] border border-white/70 bg-white p-6 shadow-[0px_20px_40px_rgba(25,28,29,0.05)]";
    node.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <span class="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#eef4ff] text-primary shadow-[0px_10px_24px_rgba(0,86,210,0.12)]">
            ${iconMarkup}
          </span>
          <span class="text-[10px] font-black uppercase leading-snug tracking-widest text-on-surface-variant">${safeText(card.label)}</span>
        </div>
        <span class="mt-1 flex h-2.5 w-2.5 flex-none rounded-full ${tone.dot}"></span>
      </div>
      <div class="mt-5 font-manrope text-4xl font-bold ${tone.text}">${safeText(card.formatted_value)}</div>
      ${helperNote ? `<div class="mt-3 text-sm leading-6 text-on-surface-variant">${safeText(helperNote)}</div>` : ""}
      <div class="mt-5 flex items-center justify-between border-t border-slate-100 pt-3">
        <span class="text-xs text-on-surface-variant">Mục tiêu</span>
        <span class="rounded-full bg-amber-500 px-3 py-1 text-sm font-bold text-white shadow-[0px_10px_24px_rgba(245,158,11,0.25)]">${safeText(card.target_label)}</span>
      </div>
    `;
    wrap.appendChild(node);
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.dimension) params.set("dimension", state.dimension);
  if (state.kpiScope) params.set("scope", state.kpiScope);
  if (state.year) params.set("year", state.year);
  if (state.month) params.set("month", state.month);
  if (state.unit) params.set("unit", state.unit);
  return params.toString();
}

async function loadMeta() {
  const meta = await fetchJson("/api/dashboard/meta");
  const yearSelect = document.getElementById("yearFilter");
  const monthSelect = document.getElementById("monthFilter");
  const unitSelect = document.getElementById("unitFilter");

  yearSelect.innerHTML = '<option value="">All</option>';
  monthSelect.innerHTML = '<option value="">All</option>';
  unitSelect.innerHTML = '<option value="">All</option>';

  meta.years.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    yearSelect.appendChild(option);
  });

  meta.months.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    monthSelect.appendChild(option);
  });

  meta.units.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    unitSelect.appendChild(option);
  });
}

async function loadDashboard() {
  const query = buildQuery();
  const overview = await fetchJson(`/api/dashboard/overview${query ? `?${query}` : ""}`);
  const subtitle = state.dimension === "month" ? "Theo tháng" : "Theo đơn vị";

  renderCards(overview.cards);
  buildChart(
    "ncrChart",
    "1. Tỷ lệ Gemba Plan không đạt (NCR)",
    subtitle,
    "Tỷ lệ GB không đạt (NCR)",
    "Mục tiêu: 5%",
    overview.ncr_by_unit.map((item) => ({
      ...item,
      actual_label: formatPercentValue(item.actual, 2),
      target_label: formatPercentValue(item.target, 2),
    })),
    "lower-better",
  );
  buildChart(
    "onTimeChart",
    "2. Tỷ lệ thực hiện Gemba đúng kế hoạch",
    subtitle,
    "%Thực hiện GB đúng kế hoạch",
    "Mục tiêu: 100%",
    overview.on_time_by_unit,
    "higher-better",
  );
  buildChart(
    "capChart",
    "3. Tỷ lệ hoàn thành HĐKP",
    subtitle,
    "Tỷ lệ đóng CAP",
    "Mục tiêu: 100%",
    overview.cap_completion_by_unit,
    "higher-better",
  );
}

async function applyFilters() {
  state.year = document.getElementById("yearFilter").value;
  state.month = document.getElementById("monthFilter").value;
  state.unit = document.getElementById("unitFilter").value;
  await loadDashboard();
}

function ensureUnitFilterVisible() {
  const unitFilterWrap = document.getElementById("unitFilterWrap");
  if (!unitFilterWrap) {
    return;
  }
  unitFilterWrap.classList.remove("hidden");
  unitFilterWrap.style.display = "block";
}

function setDimension(dimension) {
  state.dimension = dimension;
  const monthButton = document.getElementById("dimensionMonth");
  const unitButton = document.getElementById("dimensionUnit");

  const activeClasses = ["bg-white", "text-primary", "shadow-[0px_8px_20px_rgba(25,28,29,0.1)]"];
  const inactiveClasses = ["bg-white/10", "text-white"];

  [monthButton, unitButton].forEach((button) => {
    button.classList.remove(...activeClasses, ...inactiveClasses);
    button.classList.add(...inactiveClasses);
  });

  const activeButton = dimension === "month" ? monthButton : unitButton;
  activeButton.classList.remove(...inactiveClasses);
  activeButton.classList.add(...activeClasses);

  ensureUnitFilterVisible();
  loadDashboard().catch(console.error);
}

function setKpiScope(scope) {
  state.kpiScope = scope;
  const recentButton = document.getElementById("kpiScopeRecent");
  const allButton = document.getElementById("kpiScopeAll");
  const activeClasses = ["bg-white", "text-primary", "shadow-[0px_8px_20px_rgba(25,28,29,0.08)]"];
  const inactiveClasses = ["text-on-surface-variant"];

  [recentButton, allButton].forEach((button) => {
    button.classList.remove(...activeClasses, ...inactiveClasses);
    button.classList.add(...inactiveClasses);
  });

  const activeButton = scope === "recent" ? recentButton : allButton;
  activeButton.classList.remove(...inactiveClasses);
  activeButton.classList.add(...activeClasses);

  loadDashboard().catch(console.error);
}

async function syncSheet() {
  const button = document.getElementById("syncButton");
  const icon = document.getElementById("syncIcon");
  button.disabled = true;
  button.classList.add("opacity-70");
  if (icon) {
    icon.style.animation = "spin 0.8s linear infinite";
  }

  try {
    await fetchJson("/api/admin/sync-sheet", { method: "POST" });
    await loadMeta();
    await loadDashboard();
  } finally {
    button.disabled = false;
    button.classList.remove("opacity-70");
    if (icon) {
      icon.style.animation = "";
    }
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  ensureUnitFilterVisible();
  await loadMeta();
  document.getElementById("yearFilter").addEventListener("change", applyFilters);
  document.getElementById("monthFilter").addEventListener("change", applyFilters);
  document.getElementById("unitFilter").addEventListener("change", applyFilters);
  document.getElementById("syncButton").addEventListener("click", syncSheet);
  document.getElementById("dimensionMonth").addEventListener("click", () => setDimension("month"));
  document.getElementById("dimensionUnit").addEventListener("click", () => setDimension("unit"));
  document.getElementById("kpiScopeRecent").addEventListener("click", () => setKpiScope("recent"));
  document.getElementById("kpiScopeAll").addEventListener("click", () => setKpiScope("all"));
  setKpiScope("recent");
  setDimension("unit");
});
