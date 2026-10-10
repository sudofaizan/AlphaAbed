function formatMessageDateIST(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).formatToParts(d);
  const get = (type) => parts.find((p) => p.type === type)?.value ?? "";
  const ampm = get("dayPeriod").toUpperCase();
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")} ${ampm} IST`;
}

function fmtPnl(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function renderExecutionFoot(execution) {
  if (!execution) return "";
  const tags = execution.tags || [];
  const errors = execution.errors || [];
  if (!tags.length && !errors.length) return "";

  const tagHtml = tags
    .map((t) => {
      const cls =
        t.status === "success"
          ? "tag-ok"
          : t.status === "failed"
            ? "tag-fail"
            : t.status === "skipped"
              ? "tag-skipped"
              : "tag-na";
      const title = t.detail ? ` title="${escapeHtml(t.detail)}"` : "";
      const suffix =
        t.status === "success"
          ? " ✓"
          : t.status === "failed"
            ? " ✗"
            : t.status === "skipped"
              ? " ⊘"
              : "";
      return `<span class="exec-tag ${cls}"${title}>${escapeHtml(t.label)}${suffix}</span>`;
    })
    .join("");

  const errHtml = errors.length
    ? `<div class="exec-errors">${errors.map((e) => escapeHtml(e)).join("<br/>")}</div>`
    : "";

  return `<div class="signal-foot">${errHtml}<div class="exec-tags">${tagHtml}</div></div>`;
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
      const foot = renderExecutionFoot(s.execution);
      const src = s.source === "whatsapp" ? "WA" : "TG";
      return `<article class="signal-item">
        <div><span class="kind">${s.kind}</span> · ${src} · id ${escapeHtml(String(s.message_id))} · ${escapeHtml(s.date_ist || formatMessageDateIST(s.date))}</div>
        <div>${s.summary}</div>
        ${rr}
        <pre>${escapeHtml(s.raw_text)}</pre>
        ${foot}
      </article>`;
    })
    .join("");
}

function setStatusCard(badgeId, lastOkId, ok, offLabel, errorText, lastOkIst) {
  const badge = document.getElementById(badgeId);
  const lastEl = document.getElementById(lastOkId);
  if (lastEl) lastEl.textContent = lastOkIst || "—";
  if (!badge) return;
  if (ok === null || ok === undefined) {
    badge.textContent = offLabel || "Off";
    badge.className = "badge";
    return;
  }
  if (ok) {
    badge.textContent = "OK";
    badge.className = "badge ok";
  } else {
    badge.textContent = errorText || "Failed";
    badge.className = "badge bad";
    badge.title = errorText || "";
  }
}

async function loadStatus() {
  const s = await api("/api/status");
  document.getElementById("todayPnl").textContent = fmtPnl(s.today_pnl);
  document.getElementById("equity").textContent = s.account_equity ?? "—";
  document.getElementById("lastPoll").textContent =
    s.last_poll_at_ist || formatMessageDateIST(s.last_poll_at);
  document.getElementById("lastMsgId").textContent = s.last_message_id ?? "—";

  const tgOn = s.config && s.config.telegram_enabled !== false;
  setStatusCard(
    "tgStatus",
    "tgLastOk",
    tgOn ? s.last_telegram_ok : null,
    "Off",
    s.last_telegram_error || "Check",
    tgOn ? s.last_telegram_ok_at_ist : null
  );
  setStatusCard(
    "mt5Status",
    "mt5LastOk",
    s.last_mt5_ok,
    null,
    s.last_mt5_error || "Check",
    s.last_mt5_ok_at_ist
  );
  const capEnabled = s.config && s.config.capiffy_enabled;
  setStatusCard(
    "capiffyStatus",
    "capiffyLastOk",
    capEnabled ? s.last_capiffy_ok : null,
    "Off",
    s.last_capiffy_error || "Check",
    capEnabled ? s.last_capiffy_ok_at_ist : null
  );
  const waOn =
    s.config &&
    s.config.whatsapp_enabled &&
    (s.config.whatsapp_messages_url || "").trim();
  setStatusCard(
    "waStatus",
    "waLastOk",
    waOn ? s.last_whatsapp_ok : null,
    "Off",
    s.last_whatsapp_error || "Check",
    waOn ? s.last_whatsapp_ok_at_ist : null
  );
  const waMid = document.getElementById("waLastMsgId");
  if (waMid) waMid.textContent = s.last_whatsapp_message_id || "—";

  updateNewsBlackoutBanner(s);
}

function updateNewsBlackoutBanner(s) {
  const el = document.getElementById("newsBlackoutBanner");
  if (!el) return;
  if (s.capiffy_blackout_active && s.capiffy_blackout_reason) {
    el.textContent = "⚠ " + s.capiffy_blackout_reason;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
    el.textContent = "";
  }
}

function renderNews(data) {
  const list = document.getElementById("newsList");
  const at = document.getElementById("newsFetchedAt");
  if (at) at.textContent = data.fetched_at_ist || data.fetched_at || "—";
  if (!list) return;
  if (!data.ok && data.error) {
    list.innerHTML = `<li class="muted">News error: ${escapeHtml(data.error)}</li>`;
    return;
  }
  const events = data.events || [];
  if (!events.length) {
    list.innerHTML =
      "<li class='muted'>No upcoming USD calendar events in the next lookahead window. Try Refresh or widen hours in Settings.</li>";
    return;
  }
  const impactIcon = (imp) =>
    imp === "High" ? "📕" : imp === "Medium" ? "🟠" : imp === "Low" ? "🟡" : "📅";
  list.innerHTML = events
    .map((e) => {
      const mins = e.minutes_until != null ? `${e.minutes_until}m` : "—";
      const fp = [e.forecast, e.previous].filter((x) => x && x !== "—").join(" / ");
      const imp = e.impact || "—";
      const meta = fp
        ? `${escapeHtml(imp)} · F/P: ${escapeHtml(fp)} · in ${mins}`
        : `${escapeHtml(imp)} · in ${mins}`;
      const past = e.is_past ? " news-past" : "";
      return `<li class="${past}">
        <span class="news-time">${escapeHtml(e.time_ist || e.time || "—")}</span>
        <span class="news-title">${impactIcon(imp)} ${escapeHtml(e.currency || "USD")} ${escapeHtml(e.title || "")}</span>
        <span class="news-meta">${meta}</span>
      </li>`;
    })
    .join("");
}

async function loadNews() {
  const data = await api("/api/news");
  renderNews(data);
  updateNewsBlackoutBanner(data);
}

document.getElementById("btnTestTg").addEventListener("click", async () => {
  const r = await api("/api/test/telegram", { method: "POST" });
  alert(r.ok ? `OK: ${r.title}\nLatest id: ${r.latest_message_id}\n${r.preview}` : `Failed: ${r.error}`);
  loadStatus();
});

document.getElementById("btnTestWa")?.addEventListener("click", async () => {
  const r = await api("/api/test/whatsapp", { method: "POST" });
  alert(
    r.ok
      ? `OK: ${r.channel}\nMessages: ${r.count}\nLatest id: ${r.latest_message_id}\n${r.preview}`
      : `Failed: ${r.error}`
  );
  loadStatus();
});

function showTestResult(r) {
  const el = document.getElementById("testTradeResult");
  el.textContent = JSON.stringify(r, null, 2);
}

function selectedTestPlatform() {
  const el = document.querySelector('input[name="testPlatform"]:checked');
  return el ? el.value : "mt5";
}

async function runTestTrade(path, confirmMsg) {
  if (!confirm(confirmMsg)) return;
  const platform = selectedTestPlatform();
  const q = `?platform=${encodeURIComponent(platform)}`;
  const r = await api(path + q, { method: "POST" });
  showTestResult(r);
  if (r.ok) {
    alert(`OK (${platform}) — check MT5 and/or Capiffy for the position.`);
  } else {
    alert("Failed:\n" + (r.error || JSON.stringify(r.result || r, null, 2)));
  }
  loadStatus();
}

document.getElementById("btnTestBuy").addEventListener("click", () => {
  const p = selectedTestPlatform();
  runTestTrade("/api/test/trade/buy", `Open TEST market BUY on ${p}?`);
});
document.getElementById("btnTestSell").addEventListener("click", () => {
  const p = selectedTestPlatform();
  runTestTrade("/api/test/trade/sell", `Open TEST market SELL on ${p}?`);
});
document.getElementById("btnTestCloseAll").addEventListener("click", () => {
  const p = selectedTestPlatform();
  runTestTrade("/api/test/trade/close-all", `Close ALL positions on ${p}?`);
});

document.getElementById("btnTestCapiffy").addEventListener("click", async () => {
  const r = await api("/api/test/capiffy", { method: "POST" });
  showTestResult(r);
  const msg = r.ok
    ? `Capiffy OK\nAccount: ${r.account_id}\nBalance: ${r.balance}\nOpen positions: ${r.open_positions}\nToken expires in: ${r.access_expires_in}s`
    : `Failed: ${r.error}`;
  alert(msg);
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

document.getElementById("btnRefreshNews").addEventListener("click", async () => {
  const r = await api("/api/news/refresh", { method: "POST" });
  renderNews(r);
  updateNewsBlackoutBanner(r);
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
  await loadNews();
}

let dashboardStarted = false;
function startDashboard() {
  if (dashboardStarted) return;
  dashboardStarted = true;
  pollUi();
  setInterval(pollUi, 8000);
}

window.addEventListener("xaubeast:unlocked", startDashboard);
