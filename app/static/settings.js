function yn(v) {
  return v ? "Yes" : "No";
}

function maskKey(key) {
  if (!key) return "—";
  const s = String(key);
  if (s.length <= 4) return "****";
  return s.slice(0, 2) + "…" + s.slice(-2);
}

function newAccountId() {
  return "acc_" + Math.random().toString(36).slice(2, 10);
}

function collectMt5Accounts() {
  const cards = document.querySelectorAll(".mt5-account-card");
  const out = [];
  cards.forEach((card) => {
    const id = card.dataset.id || newAccountId();
    out.push({
      id,
      label: card.querySelector('[data-field="label"]')?.value?.trim() || "Account",
      enabled: card.querySelector('[data-field="enabled"]')?.checked !== false,
      base_url: card.querySelector('[data-field="base_url"]')?.value?.trim() || "",
      api_key: card.querySelector('[data-field="api_key"]')?.value?.trim() || "",
      symbol: card.querySelector('[data-field="symbol"]')?.value?.trim() || "XAUUSD.pr",
    });
  });
  return out.filter((a) => a.base_url && a.api_key);
}

function renderMt5Account(acc) {
  const id = acc.id || newAccountId();
  const wrap = document.createElement("div");
  wrap.className = "mt5-account-card";
  wrap.dataset.id = id;
  wrap.innerHTML = `
    <label>Label<input data-field="label" type="text" value="${escapeHtml(acc.label || "")}" /></label>
    <label>Base URL<input data-field="base_url" type="text" value="${escapeHtml(acc.base_url || "")}" placeholder="http://host:8080" /></label>
    <label>API key<input data-field="api_key" type="text" value="${escapeHtml(acc.api_key || "")}" /></label>
    <label>Symbol<input data-field="symbol" type="text" value="${escapeHtml(acc.symbol || "XAUUSD.pr")}" /></label>
    <label class="check"><input data-field="enabled" type="checkbox" ${acc.enabled !== false ? "checked" : ""} /> Enabled</label>
    <div class="mt5-account-actions">
      <button type="button" class="btn-neon btn-secondary btn-test-mt5">Test connection</button>
      <button type="button" class="btn-neon btn-secondary btn-remove-mt5">Remove</button>
      <span class="muted test-result"></span>
    </div>
  `;
  wrap.querySelector(".btn-remove-mt5").addEventListener("click", () => wrap.remove());
  wrap.querySelector(".btn-test-mt5").addEventListener("click", async () => {
    const status = wrap.querySelector(".test-result");
    status.textContent = "Testing…";
    const account = {
      id,
      label: wrap.querySelector('[data-field="label"]').value,
      enabled: wrap.querySelector('[data-field="enabled"]').checked,
      base_url: wrap.querySelector('[data-field="base_url"]').value.trim(),
      api_key: wrap.querySelector('[data-field="api_key"]').value.trim(),
      symbol: wrap.querySelector('[data-field="symbol"]').value.trim(),
    };
    try {
      const r = await api("/api/test/mt5/account", {
        method: "POST",
        body: JSON.stringify({ account }),
      });
      status.textContent = r.ok ? "OK" : r.error || "Failed";
      status.style.color = r.ok ? "var(--ok)" : "var(--bad)";
    } catch (e) {
      status.textContent = "Failed";
    }
  });
  return wrap;
}

function renderMt5AccountsList(accounts) {
  const list = document.getElementById("mt5AccountsList");
  list.innerHTML = "";
  const rows = accounts?.length ? accounts : [{ id: "default", label: "Primary", enabled: true, base_url: "", api_key: "", symbol: "XAUUSD.pr" }];
  rows.forEach((acc) => list.appendChild(renderMt5Account(acc)));
}

function renderCurrentSettings(cfg) {
  if (!cfg) return;
  const acctCount = (cfg.mt5_accounts || []).filter((a) => a.enabled !== false).length;
  const lotLine =
    (cfg.lot_mode || "fixed") === "risk_usd"
      ? `$${cfg.risk_usd ?? 30} risk (÷ SL pts)`
      : `Fixed ${cfg.volume ?? "—"}`;
  const rows = [
    ["Telegram realtime", yn(cfg.telegram_realtime)],
    ["Poll interval (sec)", cfg.poll_interval_sec ?? "—"],
    ["Account refresh (sec)", cfg.account_refresh_sec ?? "—"],
    ["Auto-trade", yn(cfg.auto_trade)],
    ["MT5 accounts (enabled)", acctCount],
    ["Lot sizing", lotLine],
    ["Capiffy lot (fixed mode)", cfg.capiffy_volume ?? "—"],
    ["Auto-trade MT5", yn(cfg.trade_mt5 !== false)],
    ["Capiffy enabled", yn(cfg.capiffy_enabled)],
    ["Auto-trade Capiffy", yn(cfg.trade_capiffy)],
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
    ["SL message unit", cfg.sl_message_unit ?? "auto"],
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
    else if (input.tagName === "SELECT") input.value = v ?? input.options[0]?.value;
    else input.value = v;
  }
  renderMt5AccountsList(cfg.mt5_accounts || []);
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

document.getElementById("btnAddMt5")?.addEventListener("click", () => {
  document.getElementById("mt5AccountsList").appendChild(
    renderMt5Account({ label: "New account", enabled: true, symbol: "XAUUSD.pr" })
  );
});

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
  body.mt5_accounts = collectMt5Accounts();
  if (!body.mt5_accounts.length) {
    showToast("Add at least one MT5 account with URL and API key.", "err");
    return;
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
