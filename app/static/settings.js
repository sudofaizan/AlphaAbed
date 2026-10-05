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
    ["MT5 lot", cfg.volume ?? "—"],
    ["Auto-trade MT5", yn(cfg.trade_mt5 !== false)],
    ["Capiffy enabled", yn(cfg.capiffy_enabled)],
    ["Auto-trade Capiffy", yn(cfg.trade_capiffy)],
    ["Capiffy lot", cfg.capiffy_volume ?? "—"],
    ["Capiffy symbol", cfg.capiffy_symbol ?? "—"],
    ["Capiffy account id", cfg.capiffy_account_id || "(from .env)"],
    ["News calendar", yn(cfg.news_calendar_enabled !== false)],
    ["Capiffy news blackout", yn(cfg.capiffy_news_blackout !== false)],
    [
      "Capiffy blackout ±min",
      `${cfg.capiffy_news_minutes_before ?? 30} / ${cfg.capiffy_news_minutes_after ?? 30}`,
    ],
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
    : "Not saved yet — click Save settings.";
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

let toastTimer;
function showToast(message, type = "ok") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = "toast " + (type === "ok" ? "ok" : "err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4500);
}

async function loadSettingsPage() {
  const cfg = await api("/api/config");
  fillForm(cfg);
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
  const prevLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 15000);
    const r = await fetch("/api/config", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-XAUBeast-Token": getToken() || "",
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    }).then((res) => res.json());
    clearTimeout(t);
    if (r.ok !== false && r.config) {
      fillForm(r.config);
      showToast(r.message || "Settings saved successfully.", "ok");
    } else {
      showToast("Could not save settings.", "err");
    }
  } catch (err) {
    showToast(
      err.name === "AbortError" ? "Save timed out — try again." : "Save failed.",
      "err"
    );
  } finally {
    btn.disabled = false;
    btn.textContent = prevLabel;
  }
});

window.addEventListener("xaubeast:unlocked", () => loadSettingsPage());
