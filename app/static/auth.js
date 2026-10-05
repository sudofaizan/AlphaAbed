/** Session unlock for XAUBeast dashboard (token in sessionStorage). */

const XB_TOKEN_KEY = "xb_session_token";

function getToken() {
  return sessionStorage.getItem(XB_TOKEN_KEY);
}

function setToken(token) {
  if (token) sessionStorage.setItem(XB_TOKEN_KEY, token);
  else sessionStorage.removeItem(XB_TOKEN_KEY);
}

function showLogin(show) {
  const gate = document.getElementById("loginGate");
  const app = document.getElementById("appShell");
  if (gate) gate.classList.toggle("hidden", !show);
  if (app) app.classList.toggle("hidden", show);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers["X-XAUBeast-Token"] = token;
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401) {
    setToken(null);
    showLogin(true);
    throw new Error("Session expired — unlock again.");
  }
  return r.json();
}

async function verifySession() {
  const token = getToken();
  if (!token) {
    showLogin(true);
    return false;
  }
  try {
    const r = await fetch("/api/session", {
      headers: { "X-XAUBeast-Token": token },
    });
    if (!r.ok) {
      setToken(null);
      showLogin(true);
      return false;
    }
    showLogin(false);
    window.dispatchEvent(new CustomEvent("xaubeast:unlocked"));
    return true;
  } catch {
    showLogin(true);
    return false;
  }
}

function initLoginForm() {
  const form = document.getElementById("loginForm");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = document.getElementById("loginPassword")?.value || "";
    const err = document.getElementById("loginError");
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pw }),
      }).then((res) => res.json());
      if (r.ok && r.token) {
        setToken(r.token);
        if (err) err.textContent = "";
        showLogin(false);
        window.dispatchEvent(new CustomEvent("xaubeast:unlocked"));
      } else {
        if (err) err.textContent = r.error || "Access denied";
      }
    } catch {
      if (err) err.textContent = "Connection failed";
    }
  });

  const logout = document.getElementById("btnLogout");
  if (logout) {
    logout.addEventListener("click", async () => {
      try {
        await api("/api/logout", { method: "POST" });
      } catch {
        /* ignore */
      }
      setToken(null);
      showLogin(true);
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initLoginForm();
  verifySession();
});
