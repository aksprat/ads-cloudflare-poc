const $ = (sel) => document.querySelector(sel);
const nf = new Intl.NumberFormat("en-US");
const compact = (v) => {
  const n = Number(v) || 0;
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 2) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 1 : 2) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "k";
  return nf.format(n);
};

const LABELS = {
  browser: "Browsers",
  sdk_infra: "SDKs / infra",
  http_lib: "HTTP libraries",
  ai_client: "AI / MCP clients",
  crawler: "Crawlers",
  other: "Other",
  empty: "Empty UA",
};

const COLORS = {
  browser: "var(--c1)",
  sdk_infra: "var(--c2)",
  http_lib: "var(--c3)",
  ai_client: "var(--c4)",
  crawler: "var(--c5)",
};

// Critical panels first, then the rest. Browser concurrency is capped below.
const SECTIONS = [
  { key: "coverage", path: "/api/coverage", render: renderCoverage },
  { key: "overview", path: "/api/overview", render: renderOverview },
  { key: "top_hosts", path: "/api/top-hosts", render: renderHosts },
  { key: "api_errors", path: "/api/api-errors", render: renderApiErrors },
  { key: "mcp", path: "/api/mcp", render: renderMcp },
  { key: "hourly", path: "/api/hourly", render: renderHourly },
  { key: "regions", path: "/api/regions", render: renderRegions },
  { key: "colo_latency", path: "/api/colo-latency", render: renderColo },
  { key: "otlp", path: "/api/otlp", render: renderOtlp },
  { key: "page_cost", path: "/api/page-cost", render: renderCost },
  { key: "reliability", path: "/api/reliability", render: renderReliability },
];

const MAX_PARALLEL = 4;

async function mapPool(items, limit, worker) {
  const q = [...items];
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (q.length) {
      const item = q.shift();
      await worker(item);
    }
  });
  await Promise.all(runners);
}

function setStatus(msg, kind) {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status" + (kind ? " " + kind : "");
}

function setLoadState(state, label) {
  const el = $("#loadState");
  const text = $("#loadLabel");
  if (!el || !text) return;
  if (state === "idle") {
    el.hidden = true;
    el.dataset.state = "idle";
    text.textContent = "";
    return;
  }
  el.hidden = false;
  el.dataset.state = state;
  text.textContent = label || "";
}

function bars(el, rows, labelKey, valueKey) {
  if (!rows.length) {
    el.innerHTML = "<p class='lead'>No rows.</p>";
    return;
  }
  const max = Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 1);
  el.innerHTML = rows
    .map((r) => {
      const label = LABELS[r[labelKey]] || r[labelKey];
      const v = Number(r[valueKey]) || 0;
      const pct = (100 * v) / max;
      return `<div class="bar-row"><span>${label}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><span class="n">${compact(v)}</span></div>`;
    })
    .join("");
}

function table(el, columns, rows) {
  if (!rows.length) {
    el.innerHTML = "<p class='lead'>No rows for this window.</p>";
    return;
  }
  const head = columns.map((c) => `<th class="${c.numeric ? "n" : ""}">${c.label}</th>`).join("");
  const body = rows
    .map((r) => {
      const cells = columns
        .map((c) => {
          let v = r[c.key];
          if (c.fmt === "compact") v = compact(v);
          else if (c.fmt === "pct") v = (Number(v) || 0).toFixed(2) + "%";
          else if (c.fmt === "num") v = nf.format(Number(v) || 0);
          return `<td class="${c.numeric ? "n" : ""}">${v ?? "—"}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function kpis(el, items) {
  el.innerHTML = items
    .map((i) => `<div class="kpi"><div class="v">${i.value}</div><div class="l">${i.label}</div></div>`)
    .join("");
}

function hourlyChart(el, leg, rows) {
  const keys = ["browser", "sdk_infra", "http_lib", "ai_client", "crawler"];
  if (!rows.length) {
    el.innerHTML = "";
    leg.innerHTML = "";
    return;
  }
  const max = Math.max(
    ...rows.map((r) => keys.reduce((s, k) => s + (Number(r[k]) || 0), 0)),
    1
  );
  el.innerHTML = rows
    .map((r) => {
      const segs = keys
        .map((k) => {
          const v = Number(r[k]) || 0;
          const h = (100 * v) / max;
          return `<div class="seg" title="${LABELS[k]}: ${compact(v)}" style="height:${h}%;background:${COLORS[k]}"></div>`;
        })
        .join("");
      return `<div class="col">${segs}</div>`;
    })
    .join("");
  leg.innerHTML = keys
    .map((k) => `<span><i style="background:${COLORS[k]}"></i>${LABELS[k]}</span>`)
    .join("");
}

function renderCoverage(data) {
  const cov = (data.rows || [])[0] || {};
  kpis($("#ingestKpis"), [
    { label: "Rows scanned", value: compact(cov.rows) },
    { label: "First edge ts", value: (cov.t_min || "—").toString().replace("T", " ").slice(0, 19) },
    { label: "Last edge ts", value: (cov.t_max || "—").toString().replace("T", " ").slice(0, 19) },
    { label: "Mode", value: data.sample ? "sample" : "full" },
    { label: "Cache", value: data.cache || "—" },
    { label: "ADS ms", value: compact(data.elapsed_ms) },
  ]);
}

function renderOverview(data) {
  bars($("#classBars"), data.rows || [], "client_class", "requests");
}

function renderHourly(data) {
  hourlyChart($("#hourlyChart"), $("#hourlyLeg"), data.rows || []);
}

function renderHosts(data) {
  table(
    $("#hostsTable"),
    [
      { key: "host", label: "Host" },
      { key: "requests", label: "Requests", numeric: true, fmt: "compact" },
      { key: "s5xx", label: "5xx", numeric: true, fmt: "compact" },
      { key: "avg_ttfb_ms", label: "Avg TTFB ms", numeric: true, fmt: "num" },
    ],
    data.rows || []
  );
}

function renderApiErrors(data) {
  table(
    $("#apiErrors"),
    [
      { key: "status", label: "Status" },
      { key: "endpoint", label: "Endpoint" },
      { key: "requests", label: "Requests", numeric: true, fmt: "compact" },
    ],
    data.rows || []
  );
}

function renderMcp(data) {
  table(
    $("#mcpTable"),
    [
      { key: "client", label: "Client" },
      { key: "requests", label: "Requests", numeric: true, fmt: "compact" },
      { key: "distinct_ips", label: "IPs≈", numeric: true, fmt: "num" },
      { key: "ok", label: "2xx", numeric: true, fmt: "compact" },
      { key: "challenge_401", label: "401", numeric: true, fmt: "compact" },
      { key: "not_found", label: "404", numeric: true, fmt: "compact" },
    ],
    data.rows || []
  );
}

function renderRegions(data) {
  bars($("#regionBars"), data.rows || [], "name", "requests");
}

function renderColo(data) {
  table(
    $("#coloTable"),
    [
      { key: "colo", label: "Colo" },
      { key: "host", label: "Host" },
      { key: "requests", label: "Requests", numeric: true, fmt: "compact" },
      { key: "p50_ttfb_ms", label: "p50 ms", numeric: true, fmt: "num" },
      { key: "p95_ttfb_ms", label: "p95 ms", numeric: true, fmt: "num" },
    ],
    (data.rows || []).slice(0, 20)
  );
}

function renderOtlp(data) {
  table(
    $("#otlpTable"),
    [
      { key: "region", label: "OTLP region" },
      { key: "requests", label: "Requests", numeric: true, fmt: "compact" },
      { key: "non_200", label: "Non-200", numeric: true, fmt: "compact" },
      { key: "avg_ttfb_ms", label: "Avg TTFB", numeric: true, fmt: "num" },
      { key: "p95_ttfb_ms", label: "p95 TTFB", numeric: true, fmt: "num" },
    ],
    data.rows || []
  );
}

function renderCost(data) {
  table(
    $("#costTable"),
    [
      { key: "client_type", label: "Client" },
      { key: "views", label: "Views", numeric: true, fmt: "compact" },
      { key: "kb_per_view", label: "KB / view", numeric: true, fmt: "num" },
      { key: "origin_ms_per_view", label: "Origin ms", numeric: true, fmt: "num" },
      { key: "cache_missish_pct", label: "Bypass-ish %", numeric: true, fmt: "pct" },
    ],
    data.rows || []
  );
}

function renderReliability(data) {
  table(
    $("#relTable"),
    [
      { key: "host", label: "Host" },
      { key: "s5xx", label: "5xx", numeric: true, fmt: "compact" },
      { key: "security_events", label: "Block/challenge", numeric: true, fmt: "compact" },
    ],
    data.rows || []
  );
}

async function loadProgressive() {
  const start = $("#start").value.trim();
  const end = $("#end").value.trim();
  const sample = $("#sample").checked;
  const btn = $("#loadBtn");
  btn.disabled = true;
  const t0 = performance.now();
  let done = 0;
  let failed = 0;
  setLoadState("loading", `Loading 0/${SECTIONS.length}…`);
  setStatus(
    `Loading panels (max ${MAX_PARALLEL} Quack queries at a time, ${sample ? "fast sample" : "full scan"})…`
  );

  const qs = new URLSearchParams({ start, end, sample: String(sample) });

  await mapPool(SECTIONS, MAX_PARALLEL, async (sec) => {
    try {
      const res = await fetch(sec.path + "?" + qs.toString());
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail?.message || data.detail || res.statusText);
      sec.render(data);
    } catch (e) {
      failed += 1;
      console.error(sec.key, e);
    } finally {
      done += 1;
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      setLoadState("loading", `Loading ${done}/${SECTIONS.length}…`);
      setStatus(
        `Loaded ${done}/${SECTIONS.length} panels in ${secs}s` +
          (failed ? ` · ${failed} failed` : "") +
          ` · ${sample ? "sample" : "full"} · ${start} → ${end}`,
        failed ? "err" : "ok"
      );
    }
  });

  const secs = ((performance.now() - t0) / 1000).toFixed(1);
  if (failed) {
    setLoadState(
      "error",
      `${SECTIONS.length - failed}/${SECTIONS.length} loaded · ${failed} failed · ${secs}s`
    );
  } else {
    setLoadState("done", `Loaded ${SECTIONS.length}/${SECTIONS.length} · ${secs}s`);
  }
  btn.disabled = false;
}

$("#controls").addEventListener("submit", (e) => {
  e.preventDefault();
  loadProgressive();
});

document.querySelectorAll("[data-preset]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.preset === "minute") {
      $("#start").value = "2026-11-10 14:30:00 UTC";
      $("#end").value = "2026-11-10 14:31:00 UTC";
      $("#sample").checked = false; // already one minute
    } else if (btn.dataset.preset === "hour") {
      $("#start").value = "2026-11-10 14:00:00 UTC";
      $("#end").value = "2026-11-10 15:00:00 UTC";
      $("#sample").checked = true;
    } else {
      $("#start").value = "2026-11-10 00:00:00 UTC";
      $("#end").value = "2026-11-11 00:00:00 UTC";
      $("#sample").checked = true;
    }
  });
});

fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    if (!h.token_configured) setStatus("ADS_QUACK_TOKEN is not configured on the server.", "err");
  })
  .catch(() => {});
