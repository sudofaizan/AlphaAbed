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
  await api("/api/config", { method: "PUT", body: JSON.stringify(body) });
  await loadStatus();
  alert("Settings saved.");
});

document.getElementById("btnTestTg").addEventListener("click", async () => {
  const r = await api("/api/test/telegram", { method: "POST" });
  alert(r.ok ? `OK: ${r.title}\nLatest id: ${r.latest_message_id}\n${r.preview}` : `Failed: ${r.error}`);
  loadStatus();
});

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
