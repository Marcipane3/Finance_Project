/* Portfolio Cockpit — client-side app.
 *
 * Loads the PUBLIC research payload (data/latest.json) produced by build_site.py
 * and renders both tracks. Personal holdings are PRIVATE: they live only in
 * localStorage under HOLDINGS_KEY and are never sent anywhere.
 */
"use strict";

const HOLDINGS_KEY = "cockpit.holdings.v1";
const state = { data: null, tab: "overview" };

// ── boot ──────────────────────────────────────────────────────────────────
async function boot() {
  try {
    const res = await fetch(`data/latest.json?t=${Date.now()}`);
    state.data = await res.json();
  } catch (e) {
    document.getElementById("loading").textContent =
      "Could not load data/latest.json — run `python build_site.py` first.";
    return;
  }
  renderChrome();
  wireTabs();
  render();
}

function renderChrome() {
  const d = state.data;
  const gen = new Date(d.generated_at);
  document.getElementById("generated").textContent =
    `updated ${gen.toLocaleString()} · ${d.currency} base`;
  document.getElementById("foot-built").textContent =
    `data ${d.generated_at.slice(0, 10)}`;
  const fx = d.fx || {};
  document.getElementById("fxstrip").innerHTML = [
    ["USD→EUR", fx.usd_eur], ["GBP→EUR", fx.gbp_eur],
    ["DKK→EUR", fx.dkk_eur], ["JPY→EUR", fx.jpy_eur],
  ].filter(([, v]) => v != null)
   .map(([k, v]) => `${k} <b>${(+v).toFixed(k === "JPY→EUR" || k === "DKK→EUR" ? 4 : 3)}</b>`)
   .join("");

  // stop-loss dot on the Fast Ideas tab
  const sl = d.track_b && d.track_b.stop_loss ? d.track_b.stop_loss.status : "no_position";
  const dot = document.getElementById("b-dot");
  dot.className = "dot " + (sl === "breached" ? "breach" : sl === "no_position" ? "none" : "");
}

function wireTabs() {
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.onclick = () => {
      state.tab = b.dataset.tab;
      document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      render();
    };
  });
}

function render() {
  const app = document.getElementById("app");
  const views = {
    overview: viewOverview, trackb: viewTrackB, tracka: viewTrackA,
    record: viewRecord, holdings: viewHoldings,
  };
  app.innerHTML = (views[state.tab] || viewOverview)();
  if (state.tab === "holdings") wireHoldings();
}

// ── overview ─────────────────────────────────────────────────────────────
function viewOverview() {
  const d = state.data;
  const b = d.track_b, a = d.track_a;
  const h = loadHoldings();
  const sleeveVal = h.reduce((s, x) => s + (x.eur || 0), 0);

  const cards = [];
  if (b && b.pick) {
    const rec = b.pick.recommendation || {};
    cards.push(kpi("Fast Ideas — current pick", b.pick.ticker || "—",
      `${b.pick.name || ""} · ${rec.action || ""}`));
  }
  if (b && b.stop_loss) {
    const sl = b.stop_loss;
    cards.push(kpi("Stop-loss", badge(sl.status, sl.status),
      sl.status === "breached" ? "exit to cash" :
      sl.status === "safe" ? `${pct(sl.pnl_pct)} vs entry` : "no open position", true));
  }
  if (a) {
    cards.push(kpi("Core — A1 E[return]", pct(a.a1 && a.a1.expected_return),
      a.a1 ? `CVaR ${pct(a.a1.cvar)} · ${a.n_eligible} eligible` : ""));
  }
  cards.push(kpi("My tracked positions", h.length ? `€${fmt(sleeveVal)}` : "—",
    h.length ? `${h.length} position(s) · private` : "add in My Holdings", true));

  return `
    <p class="section-title">Snapshot</p>
    <div class="grid">${cards.join("")}</div>
    ${b && b.pick ? heroPick(b) : ""}
    <p class="section-title">How this works</p>
    <div class="card">
      <p>This cockpit is a <b>static site</b> rebuilt by GitHub Actions: a monthly job runs both
      pipelines and commits a fresh pick + Core recommendation; a daily job checks the stop-loss.</p>
      <p style="color:var(--muted)">Everything you see here is research only — no money figures are stored on the server.
      Enter your real positions under <b>My Holdings</b>; they persist in your browser and never leave this device.</p>
    </div>`;
}

function heroPick(b) {
  const p = b.pick, rec = p.recommendation || {};
  return `
    <div class="card pick-hero">
      <div>
        <div class="tk">${p.ticker || "—"}</div>
        <div class="nm">${p.name || ""} ${p.sector ? "· " + p.sector : ""}</div>
      </div>
      <div style="text-align:center">
        <div class="px">${p.price_usd != null ? "$" + fmt(p.price_usd) : "—"}</div>
        <div class="nm">${rec.stop_price != null ? "stop $" + fmt(rec.stop_price) : ""}</div>
      </div>
      <div>${badge(rec.action, rec.action)}</div>
    </div>`;
}

// ── Track B ─────────────────────────────────────────────────────────────────
function viewTrackB() {
  const b = state.data.track_b;
  if (!b) return emptyView("No Fast Ideas report yet.");
  const lb = (b.leaderboard || []).map((r) => `
    <tr class="${r.rank === 1 ? "top" : ""}">
      <td class="rank">${r.rank}</td>
      <td class="tk">${r.ticker}</td>
      <td>${r.name || ""}</td>
      <td class="num">${num(r.score)}</td>
      <td class="num">${r.forward_pe != null ? num(r.forward_pe) + "×" : "—"}</td>
      <td class="num ${cls(r.revenue_growth)}">${pct(r.revenue_growth)}</td>
      <td class="num ${cls(r.earnings_growth)}">${pct(r.earnings_growth)}</td>
      <td class="num ${cls(r.analyst_upside)}">${pct(r.analyst_upside)}</td>
      <td class="num">${num(r.rsi_14)}</td>
      <td class="num ${cls(r.momentum_12_1)}">${pct(r.momentum_12_1)}</td>
    </tr>`).join("");

  return `
    ${heroPick(b)}
    <p class="section-title">Candidate leaderboard · ${b.as_of || ""}</p>
    <div class="card" style="overflow-x:auto">
      <table>
        <thead><tr>
          <th></th><th>Ticker</th><th>Name</th><th>Score</th><th>Fwd P/E</th>
          <th>Rev Gr</th><th>EPS Gr</th><th>Upside</th><th>RSI</th><th>Mom 12m</th>
        </tr></thead>
        <tbody>${lb}</tbody>
      </table>
    </div>
    ${b.report_md ? `<p class="section-title">Full thesis</p><div class="report">${md(b.report_md)}</div>` : ""}`;
}

// ── Track A ─────────────────────────────────────────────────────────────────
function viewTrackA() {
  const a = state.data.track_a;
  if (!a) return emptyView("No Core recommendation yet. Run `track_a/run.py --mode live`.");
  return `
    <p class="section-title">Core (Synapse) · ${a.as_of || ""}</p>
    <div class="grid">
      ${kpi("F-Score eligible", a.n_eligible ?? "—", `threshold ≥ ${a.effective_threshold ?? "?"}`)}
      ${kpi("A1 E[return]", pct(a.a1 && a.a1.expected_return), `CVaR ${pct(a.a1 && a.a1.cvar)}`)}
      ${kpi("A1 trade cost", a.a1 ? "€" + fmt(a.a1.tc_eur) : "—", a.a1 ? a.a1.status : "")}
    </div>
    ${aTable("A1 — Full Rebalance", a.a1)}
    ${aTable("A2 — Capital Deployment (buy-only)", a.a2)}
    ${a.report_md ? `<p class="section-title">Full recommendation</p><div class="report">${md(a.report_md)}</div>` : ""}`;
}

function aTable(title, sec) {
  if (!sec || !(sec.positions || []).length) return "";
  const rows = sec.positions.map((p) => `
    <tr><td class="tk">${p.ticker}</td><td class="num">${pct(p.weight)}</td>
        <td class="num">€${fmt(p.approx_eur)}</td></tr>`).join("");
  return `
    <p class="section-title">${title}</p>
    <div class="card">
      <table><thead><tr><th>Ticker</th><th>Weight</th><th>≈ EUR</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div>`;
}

// ── Track record (NL-4) ───────────────────────────────────────────────────
function viewRecord() {
  const rec = state.data.track_record || [];
  if (!rec.length) return emptyView("No picks logged yet — the record grows one pick per month.");
  const rows = rec.slice().reverse().map((r) => `
    <tr>
      <td class="tk">${r.ticker}</td><td>${r.name || ""}</td><td>${r.pick_date || ""}</td>
      <td class="num ${cls(r.return_pct)}">${r.return_pct != null ? pct(r.return_pct) : "open"}</td>
      <td class="num ${cls(r.benchmark_return_pct)}">${r.benchmark_return_pct != null ? pct(r.benchmark_return_pct) : "—"}</td>
      <td>${r.status}</td>
    </tr>`).join("");
  return `
    <p class="section-title">Pick performance vs benchmark</p>
    <div class="card" style="overflow-x:auto">
      <table><thead><tr><th>Ticker</th><th>Name</th><th>Pick date</th>
        <th>Return</th><th>Benchmark</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p style="color:var(--muted);font-size:12px;margin-top:14px">Realized returns vs ${rec[0].benchmark || "benchmark"} are
      filled in by the monthly job once each pick has price history. This is the learning loop.</p>
    </div>`;
}

// ── Holdings (localStorage only) ─────────────────────────────────────────────
function viewHoldings() {
  const h = loadHoldings();
  const prices = priceMap();
  let total = 0, totalCost = 0;
  const rows = h.map((x, i) => {
    const last = prices[x.ticker];
    const cost = x.eur || 0;
    const nowVal = (last && x.entry && x.eur) ? cost * (last / x.entry) : null;
    if (nowVal != null) { total += nowVal; } else { total += cost; }
    totalCost += cost;
    const pnl = nowVal != null ? (nowVal - cost) / cost : null;
    return `<tr>
      <td class="tk">${x.ticker}</td>
      <td class="num">€${fmt(cost)}</td>
      <td class="num">${x.entry != null ? num(x.entry) : "—"}</td>
      <td class="num">${last != null ? num(last) : "—"}</td>
      <td class="num ${cls(pnl)}">${pnl != null ? pct(pnl) : "—"}</td>
      <td><button class="btn danger" data-del="${i}">remove</button></td>
    </tr>`;
  }).join("");
  const totPnl = totalCost ? (total - totalCost) / totalCost : null;

  return `
    <div class="priv-note">🔒 Private &amp; local. These numbers are stored only in this browser
      (localStorage). They are never committed to git or uploaded. Use Export to back up.</div>
    <p class="section-title">My positions</p>
    <div class="hform">
      <input id="h-ticker" placeholder="Ticker (e.g. WDC)" />
      <input id="h-eur" type="number" placeholder="€ invested" />
      <input id="h-entry" type="number" placeholder="entry price (native)" />
      <input id="h-date" type="date" />
      <button class="btn" id="h-add">Add</button>
    </div>
    <div class="card" style="overflow-x:auto">
      <table><thead><tr><th>Ticker</th><th>€ invested</th><th>Entry</th>
        <th>Last (research)</th><th>P&amp;L</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="6" style="color:var(--muted)">No positions yet.</td></tr>`}</tbody>
      </table>
      ${h.length ? `<p style="margin-top:14px">Tracked value ≈ <b>€${fmt(total)}</b>
        <span class="${cls(totPnl)}">(${totPnl != null ? pct(totPnl) : "—"})</span></p>` : ""}
    </div>
    <div class="io-row">
      <button class="btn ghost" id="h-export">Export JSON</button>
      <button class="btn ghost" id="h-import">Import JSON</button>
      <input type="file" id="h-file" accept="application/json" style="display:none" />
    </div>
    <p style="color:var(--muted);font-size:12px;margin-top:10px">"Last (research)" reuses the
      research snapshot price where available — it is not a live quote. Entry price is in the
      stock's native currency; P&amp;L is price-ratio based.</p>`;
}

function wireHoldings() {
  const $ = (id) => document.getElementById(id);
  $("h-add").onclick = () => {
    const t = ($("h-ticker").value || "").trim().toUpperCase();
    if (!t) return;
    const h = loadHoldings();
    h.push({
      ticker: t,
      eur: parseFloat($("h-eur").value) || 0,
      entry: parseFloat($("h-entry").value) || null,
      date: $("h-date").value || null,
    });
    saveHoldings(h); render();
  };
  document.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = () => { const h = loadHoldings(); h.splice(+b.dataset.del, 1); saveHoldings(h); render(); };
  });
  $("h-export").onclick = () => {
    const blob = new Blob([JSON.stringify(loadHoldings(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "cockpit-holdings.json"; a.click();
  };
  $("h-import").onclick = () => $("h-file").click();
  $("h-file").onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { try { saveHoldings(JSON.parse(r.result)); render(); } catch { alert("Invalid JSON"); } };
    r.readAsText(f);
  };
}

function loadHoldings() {
  try { return JSON.parse(localStorage.getItem(HOLDINGS_KEY)) || []; }
  catch { return []; }
}
function saveHoldings(h) { localStorage.setItem(HOLDINGS_KEY, JSON.stringify(h)); }

/** Build {ticker: price} from research data so holdings can show a P&L overlay. */
function priceMap() {
  const m = {};
  const b = state.data.track_b;
  if (b && b.pick && b.pick.ticker && b.pick.price_usd != null) m[b.pick.ticker] = b.pick.price_usd;
  return m;
}

// ── helpers ─────────────────────────────────────────────────────────────────
function kpi(label, value, note, isHtml) {
  return `<div class="card kpi"><div class="label">${label}</div>
    <div class="value">${isHtml ? value : esc(value)}</div>
    <div class="note">${note || ""}</div></div>`;
}
function badge(cls, text) { return `<span class="badge ${cls || ""}">${esc(text || "—")}</span>`; }
function emptyView(msg) { return `<div class="card" style="color:var(--muted)">${esc(msg)}</div>`; }
function md(s) { return window.marked ? marked.parse(s) : `<pre>${esc(s)}</pre>`; }

function pct(v) { return v == null || isNaN(v) ? "—" : (v * 100).toFixed(1) + "%"; }
function num(v) { return v == null || isNaN(v) ? "—" : (+v).toFixed(2); }
function fmt(v) { return v == null || isNaN(v) ? "—" : (+v).toLocaleString(undefined, { maximumFractionDigits: 2 }); }
function cls(v) { return v == null || isNaN(v) ? "" : v >= 0 ? "pos" : "neg"; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

boot();
