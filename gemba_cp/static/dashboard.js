const state = {
  dimension: "unit",
  year: "",
  month: "",
  unit: "",
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

function buildChart(containerId, title, subtitle, legendLabel, legendTarget, items, mode = "higher-better") {
  const wrap = document.getElementById(containerId);
  wrap.innerHTML = "";

  if (!items.length) {
    wrap.innerHTML = `
      <div class="rounded-[1.75rem] bg-surface-container-lowest p-8 shadow-[0px_20px_40px_rgba(25,28,29,0.05)]">
        <div class="text-sm text-on-surface-variant">Chưa có dữ liệu.</div>
      </div>
    `;
    return;
  }

  // Dùng cùng 1 maxScale cho cả bar lẫn target line: khi actual = target thì bar đụng đúng đỉnh đường line
  const targetVal = Number(items[0]?.target || 0);
  const maxActual = Math.max(...items.map((i) => Number(i.actual || 0)), 0);
  const maxScale = Math.max(maxActual, targetVal, 0.01);
  const linePercent = Math.min(99, (targetVal / maxScale) * 100);

  const chart = document.createElement("section");
  chart.className = "rounded-2xl bg-white p-6 shadow-[0px_20px_40px_rgba(25,28,29,0.05)] overflow-hidden";

  chart.innerHTML = `
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="inline-flex items-center rounded-xl bg-[#0056d2] px-4 py-2 font-manrope text-sm font-extrabold tracking-tight text-white">${safeText(title)}</div>
        <div class="mt-1.5 text-[10px] uppercase tracking-widest text-on-surface-variant">${safeText(subtitle)}</div>
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
    // Cùng công thức (actual / maxScale * 100) như đường line → khi actual = target thì đỉnh bar chạm đúng đường
    const pct = Number(item.actual) > 0 ? Math.max(2, (Number(item.actual) / maxScale) * 100) : 0;
    const tone = chartTone(item.actual, item.target, mode);

    const bar = document.createElement("div");
    bar.className = "relative flex-1 h-full mx-1" + (items.length <= 6 ? " max-w-[3.5rem]" : " max-w-[2.5rem]");
    const tooltip = `${item.unit}: ${item.actual_label}`;
    bar.innerHTML = `
      <div
        class="absolute bottom-0 inset-x-0 h-full rounded-lg bg-surface-container-low cursor-help"
        title="${safeAttr(tooltip)}"
      ></div>
      <div
        class="absolute bottom-0 inset-x-0 ${tone} rounded-lg transition-all duration-500 cursor-help"
        style="height:${pct}%"
        title="${safeAttr(tooltip)}"
      ></div>
      <div
        class="pointer-events-none absolute inset-x-1 bottom-1 rounded-md bg-white/90 px-1 py-0.5 text-center text-[10px] font-semibold text-on-surface shadow-sm"
      >
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

const LOWER_BETTER_KEYS = new Set(["ncr", "ncr_ratio", "ncr_rate", "defect_ratio", "defect_rate"]);

function kpiTone(card) {
  if (!card.value && card.value !== 0) return { text: "text-on-surface", dot: "bg-slate-300" };
  const v = Number(card.value);
  const t = Number(card.target);
  const isLowerBetter = card.mode === "lower-better" || LOWER_BETTER_KEYS.has(card.key);
  const good = isLowerBetter ? v <= t : v >= t;
  return good
    ? { text: "text-emerald-600", dot: "bg-emerald-400" }
    : { text: "text-rose-600", dot: "bg-rose-400" };
}

function renderCards(cards) {
  const wrap = document.getElementById("kpiCards");
  wrap.innerHTML = "";

  cards.forEach((card) => {
    const tone = kpiTone(card);
    const node = document.createElement("article");
    node.className = "rounded-2xl bg-white p-6 shadow-[0px_20px_40px_rgba(25,28,29,0.05)] flex flex-col justify-between h-44";
    node.innerHTML = `
      <div class="flex items-start justify-between gap-2">
        <span class="text-[10px] font-black tracking-widest uppercase text-on-surface-variant leading-snug">${safeText(card.label)}</span>
        <span class="mt-0.5 flex h-2 w-2 flex-none rounded-full ${tone.dot}"></span>
      </div>
      <div class="font-manrope text-4xl font-bold ${tone.text}">${safeText(card.formatted_value)}</div>
      <div class="flex items-center justify-between border-t border-slate-100 pt-3">
        <span class="text-xs text-on-surface-variant">Mục tiêu</span>
        <span class="text-sm font-bold text-on-surface">${safeText(card.target_label)}</span>
      </div>
    `;
    wrap.appendChild(node);
  });
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.dimension) params.set("dimension", state.dimension);
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

  // (lastSync display removed — no UI element)
}

async function loadDashboard() {
  const query = buildQuery();
  const overview = await fetchJson(`/api/dashboard/overview${query ? `?${query}` : ""}`);

  renderCards(overview.cards);
  buildChart(
    "ncrChart",
    "1. Tỷ lệ Gemba Plan không đạt (NCR)",
    state.dimension === "month" ? "Theo tháng" : "Theo đơn vị",
    "Tỷ lệ GB không đạt (NCR)",
    "Mục tiêu: 5%",
    overview.ncr_by_unit,
    "lower-better",
  );
  buildChart(
    "onTimeChart",
    "2. Tỷ lệ thực hiện Gemba đúng kế hoạch",
    state.dimension === "month" ? "Theo tháng" : "Theo đơn vị",
    "%Thực hiện GB đúng kế hoạch",
    "Mục tiêu: 100%",
    overview.on_time_by_unit,
    "higher-better",
  );
  buildChart(
    "capChart",
    "3. Tỷ lệ hoàn thành HĐKP",
    state.dimension === "month" ? "Theo tháng" : "Theo đơn vị",
    "Tỉ lệ đóng CAP",
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

function setDimension(dimension) {
  state.dimension = dimension;
  const monthButton = document.getElementById("dimensionMonth");
  const unitButton = document.getElementById("dimensionUnit");
  const unitFilterWrap = document.getElementById("unitFilterWrap");

  const activeClasses = ["bg-white", "text-primary", "shadow-[0px_8px_20px_rgba(25,28,29,0.1)]"];
  const inactiveClasses = ["bg-white/10", "text-white"];

  [monthButton, unitButton].forEach((button) => {
    button.classList.remove(...activeClasses, ...inactiveClasses);
    button.classList.add(...inactiveClasses);
  });

  const activeButton = dimension === "month" ? monthButton : unitButton;
  activeButton.classList.remove(...inactiveClasses);
  activeButton.classList.add(...activeClasses);

  if (dimension === "unit") {
    unitFilterWrap.classList.remove("hidden");
  } else {
    unitFilterWrap.classList.add("hidden");
    document.getElementById("unitFilter").value = "";
    state.unit = "";
  }

  loadDashboard().catch(console.error);
}

async function syncSheet() {
  const button = document.getElementById("syncButton");
  const icon = document.getElementById("syncIcon");
  button.disabled = true;
  button.classList.add("opacity-70");
  if (icon) icon.style.animation = "spin 0.8s linear infinite";
  try {
    await fetchJson("/api/admin/sync-sheet", { method: "POST" });
    await loadMeta();
    await loadDashboard();
  } finally {
    button.disabled = false;
    button.classList.remove("opacity-70");
    if (icon) icon.style.animation = "";
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  await loadMeta();
  await loadDashboard();
  document.getElementById("yearFilter").addEventListener("change", applyFilters);
  document.getElementById("monthFilter").addEventListener("change", applyFilters);
  document.getElementById("unitFilter").addEventListener("change", applyFilters);
  document.getElementById("syncButton").addEventListener("click", syncSheet);
  document.getElementById("dimensionMonth").addEventListener("click", () => setDimension("month"));
  document.getElementById("dimensionUnit").addEventListener("click", () => setDimension("unit"));
  setDimension("unit");
});
