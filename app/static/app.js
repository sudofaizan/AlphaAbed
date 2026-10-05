async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  return r.json();
}

function fmtPnl(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function renderSignals(signals) {
  const el = document.getElementById("signalList");
  if (!signals.length) {
    el.innerHTML = "<p class='muted'>No signals in last fetch.</p>";
    return;
  }
  el.innerHTML = signals
    .map((s) => {
      const plan = s.trade_plan;
      const rr = plan
        ? `<div class="rr">R:R ${plan.reward_risk_ratio} · entry ${plan.entry} SL ${plan.sl} TP ${plan.tp} · risk ${plan.risk_points} pts</div>`
        : "";
      return `<article class="signal-item">
        <div><span class="kind">${s.kind}</span> · id ${s.message_id} · ${s.date}</div>
        <div>${s.summary}</div>
        ${rr}
        <pre>${escapeHtml(s.raw_text)}</pre>
      </article>`;
    })
    .join("");
}

function escapeHtml(t) {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function loadStatus() {
  const s = await api("/api/status");
  document.getElementById("todayPnl").textContent = fmtPnl(s.today_pnl);
  document.getElementById("equity").textContent = s.account_equity ?? "—";
  document.getElementById("lastPoll").textContent = s.last_poll_at ?? "—";
  document.getElementById("lastMsgId").textContent = s.last_message_id ?? "—";

  const tg = document.getElementById("tgStatus");
  tg.textContent = s.last_telegram_ok ? "OK" : s.last_telegram_error || "Unknown";
  tg.className = "badge " + (s.last_telegram_ok ? "ok" : "bad");

  const mt5 = document.getElementById("mt5Status");
  mt5.textContent = s.last_mt5_ok ? "OK" : "Check connection";
  mt5.className = "badge " + (s.last_mt5_ok ? "ok" : "bad");

  fillForm(s.config);
}

function fillForm(cfg) {
  const form = document.getElementById("cfgForm");
  for (const [k, v] of Object.entries(cfg)) {
    const input = form.elements.namedItem(k);
    if (!input) continue;
    if (input.type === "checkbox") input.checked = !!v;
    else input.value = v;
  }
  renderCurrentSettings(cfg);
}

function yn(v) {
  return v ? "Yes" : "No";
}

function maskKey(key) {
  if (!key) return "—";
  const s = String(key);
  if (s.length <= 4) return "****";
  return s.slice(0, 2) + "…" + s.slice(-2);
}

function renderCurrentSettings(cfg) {
  if (!cfg) return;
  const rows = [
    ["Telegram realtime", yn(cfg.telegram_realtime)],
    ["Poll interval (sec)", cfg.poll_interval_sec ?? "—"],
    ["Account refresh (sec)", cfg.account_refresh_sec ?? "—"],
    ["Auto-trade", yn(cfg.auto_trade)],
    ["MT5 URL", cfg.mt5_base_url ?? "—"],
    ["API key", maskKey(cfg.mt5_api_key)],
    ["Symbol", cfg.mt5_symbol ?? "—"],
    ["Lot size", cfg.volume ?? "—"],
    ["Order comment", cfg.mt5_trade_comment ?? "ABD"],
    ["Reward : risk (TP)", cfg.reward_risk_ratio ?? "—"],
    ["Use signal TP", yn(cfg.prefer_signal_tp)],
    ["Trade without SL", yn(cfg.allow_trade_without_sl)],
    ["Default SL points", cfg.default_sl_points ?? "—"],
    ["History fetch limit", cfg.telegram_fetch_limit ?? "—"],
  ];
  document.getElementById("currentSettings").innerHTML = rows
    .map(
      ([label, val]) =>
        `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(val))}</dd></div>`
    )
    .join("");
  const at = cfg.config_saved_at;
  document.getElementById("settingsSavedAt").textContent = at
    ? `Last saved (UTC): ${at}`
    : "Not saved yet — using defaults until you click Save settings.";
}

let toastTimer;
function showToast(message, type = "ok") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = "toast " + (type === "ok" ? "ok" : "err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4500);
}

document.getElementById("cfgForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const body = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") body[el.name] = el.checked;
    else if (el.type === "number") body[el.name] = Number(el.value);
    else body[el.name] = el.value;
  }
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const r = await api("/api/config", { method: "PUT", body: JSON.stringify(body) });
    if (r.ok !== false && r.config) {
      fillForm(r.config);
      renderCurrentSettings(r.config);
      showToast(r.message || "Settings saved successfully.", "ok");
    } else {
      showToast("Could not save settings.", "err");
    }
    await loadStatus();
  } catch (err) {
    showToast("Save failed — check connection.", "err");
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btnTestTg").addEventListener("click", async () => {
  const r = await api("/api/test/telegram", { method: "POST" });
  alert(r.ok ? `OK: ${r.title}\nLatest id: ${r.latest_message_id}\n${r.preview}` : `Failed: ${r.error}`);
  loadStatus();
});

function showTestResult(r) {
  const el = document.getElementById("testTradeResult");
  el.textContent = JSON.stringify(r, null, 2);
}

async function runTestTrade(path, confirmMsg) {
  if (!confirm(confirmMsg)) return;
  const r = await api(path, { method: "POST" });
  showTestResult(r);
  if (r.ok) {
    alert("OK — check MT5 terminal for position (comment ABD).");
  } else {
    alert("Failed:\n" + (r.error || JSON.stringify(r.result || r, null, 2)));
  }
  loadStatus();
}

document.getElementById("btnTestBuy").addEventListener("click", () =>
  runTestTrade("/api/test/trade/buy", "Open TEST market BUY 0.01 lot with SL/TP?")
);
document.getElementById("btnTestSell").addEventListener("click", () =>
  runTestTrade("/api/test/trade/sell", "Open TEST market SELL 0.01 lot with SL/TP?")
);
document.getElementById("btnTestCloseAll").addEventListener("click", () =>
  runTestTrade("/api/test/trade/close-all", "Close ALL open positions on this symbol/account?")
);

document.getElementById("btnTestMt5").addEventListener("click", async () => {
  const r = await api("/api/test/mt5", { method: "POST" });
  const msg = r.ok
    ? `OK\nBid: ${r.price?.bid} Ask: ${r.price?.ask}\nToday P/L: ${r.account?.today?.closed_pl}`
    : JSON.stringify(r, null, 2);
  alert(msg);
  loadStatus();
});

document.getElementById("btnRefreshSignals").addEventListener("click", async () => {
  const r = await api("/api/signals/refresh", { method: "POST" });
  if (!r.ok) {
    alert("Refresh failed: " + (r.error || "unknown"));
    return;
  }
  renderSignals(r.signals || []);
  alert(`Fetched ${r.fetched} messages → ${r.signal_count} signals`);
  loadStatus();
});

async function pollUi() {
  const hist = await api("/api/signals/history");
  renderSignals(hist.signals || []);
  const ev = await api("/api/events");
  const log = document.getElementById("eventLog");
  log.innerHTML = (ev.events || [])
    .slice(0, 20)
    .map((e) => `<li>[${e.kind}] ${escapeHtml(e.message || "")}</li>`)
    .join("");
  await loadStatus();
}

pollUi();
setInterval(pollUi, 8000);
