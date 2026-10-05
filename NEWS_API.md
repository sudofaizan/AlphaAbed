# Red-folder news API (`getUpcomingNews`)

How **high-impact (red folder)** economic calendar events work in the AlphaFX MT5 VPS stack, including the **deploy_web** dashboard.

---

## How deploy_web gets red-folder news

The dashboard is static HTML/JS: [`deploy_web/index.html`](deploy_web/index.html). It does **not** scrape Forex Factory in the browser. All calendar data comes from your **MT5 VPS API** (`server.py`).

### Flow

```text
Forex Factory JSON feed (server-side)
        │
        ▼
  server.py caches raw calendar (NEWS_CACHE_TTL, default 5 min)
        │
        ▼
  build_upcoming_news() filters impact=High → "red folder"
        │
        ▼
  GET /getUpcomingNews  (X-API-Key)
        │
        ▼
  deploy_web fetchUpcomingNews() → renderUpcomingNews()
```

### What the UI calls

On **Connect**, the app runs:

```javascript
fetchUpcomingNews();
scheduleNewsRefresh();  // every 5 minutes
```

Request (from `fetchUpcomingNews`):

```http
GET /getUpcomingNews?hours=72&impact=High&currency=USD
```

| UI control | Effect |
|------------|--------|
| **USD only** checkbox (`togNewsUsd`) | Adds `&currency=USD` when checked; omits currency when unchecked (all currencies) |
| **Refresh** | Calls `fetchUpcomingNews()` again |
| **Notify 5m before** | `POST /newsAlerts/start` with `{ currency_filter: "USD"|"ALL", hours_ahead: 72 }` — server-side Telegram worker, not browser |
| **Stop notify** | `POST /newsAlerts/stop` |

Red folder in the UI is the 📕 icon; every row returned uses **`impact=High`** in the query, which matches Forex Factory **High** impact (red folder on FF).

### Rendering

Each event shows:

- Currency (`e.currency`)
- Title (`e.title`)
- Forecast / Previous (`e.forecast`, `e.previous`)
- Local time from ISO `e.time`
- Countdown from `e.minutes_until` (highlights **NOW** in red when imminent)

Empty state: *"No high-impact (red folder) news in the next 72h."*

---

## Data source (server)

| Setting | Default | Meaning |
|---------|---------|---------|
| `NEWS_CALENDAR_URL` | `https://nfs.faireconomy.media/ff_calendar_thisweek.json` | Weekly FF-style JSON array |
| `NEWS_CACHE_TTL` | `300` | Seconds to reuse cached raw feed |

Raw feed items (fields used by the server):

| Feed field | Usage |
|------------|--------|
| `impact` | Must match query `impact` (default **`High`**, case-insensitive) |
| `country` | Treated as **currency** code (e.g. `USD`, `EUR`) in API output |
| `date` | ISO datetime → UTC, window filter |
| `title` | Event name |
| `forecast`, `previous` | Shown in UI (default `—` if missing) |

**MT5 is not required** for news endpoints (no `@require_mt5` on `getUpcomingNews`).

---

## API: `GET /getUpcomingNews`

**Auth:** `X-API-Key: alphafx` (or `?api_key=`)

**Purpose:** List upcoming **high-impact** calendar events (red folder) within a time window.

### Query parameters

| Param | Default | Range / notes |
|-------|---------|----------------|
| `hours` | `72` | `1`–`168` — how far ahead from now (UTC) |
| `impact` | `High` | Use **`High`** for red folder; compared case-insensitively to feed `impact` |
| `currency` | *(all)* | Optional comma-separated filter, e.g. `USD` or `USD,EUR` |

Events more than **30 minutes in the past** are dropped. Events after `now + hours` are dropped.

### Example — same as deploy_web (USD red folder, 72h)

```bash
export BASE="http://15.135.71.95:8080"
export KEY="alphafx"

curl -sS -H "X-API-Key: $KEY" \
  "$BASE/getUpcomingNews?hours=72&impact=High&currency=USD"
```

### Example — all currencies, 48h

```bash
curl -sS -H "X-API-Key: $KEY" \
  "$BASE/getUpcomingNews?hours=48&impact=High"
```

### Example — multiple currencies

```bash
curl -sS -H "X-API-Key: $KEY" \
  "$BASE/getUpcomingNews?hours=72&impact=High&currency=USD,EUR,GBP"
```

### Success response (`200`)

```json
{
  "ok": true,
  "source": "forex_factory",
  "impact_filter": "High",
  "hours_ahead": 72,
  "count": 2,
  "events": [
    {
      "event_id": "USD|2026-10-06T12:30:00+00:00|Non-Farm Payrolls",
      "title": "Non-Farm Payrolls",
      "currency": "USD",
      "country": "USD",
      "impact": "High",
      "time": "2026-10-06T12:30:00Z",
      "forecast": "180K",
      "previous": "175K",
      "minutes_until": 240,
      "is_imminent": false,
      "is_past": false
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `event_id` | Stable id for Telegram dedup (`currency|time|title`) |
| `minutes_until` | Minutes until event (UTC-based) |
| `is_imminent` | `true` if between 5 minutes **before** and 30 minutes **after** |
| `is_past` | `true` if more than 5 minutes after event time |

Events are sorted by `time` ascending.

### Error responses

| HTTP | Body | When |
|------|------|------|
| `401` | `{"ok":false,"error":"unauthorized"}` | Missing/wrong API key |
| `502` | `{"ok":false,"error":"calendar feed unavailable","source":"forex_factory"}` | Feed fetch failed and cache empty |
| `502` | `{"ok":false,"error":"<message>"}` | Exception in `build_upcoming_news` |

---

## Related: Telegram news alerts (optional)

These are used by deploy_web **Notify 5m before**; they reuse the same calendar builder.

### `GET /newsAlerts/status`

```bash
curl -sS -H "X-API-Key: $KEY" "$BASE/newsAlerts/status"
```

### `POST /newsAlerts/start`

```bash
curl -sS -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"currency_filter":"USD","hours_ahead":72}' \
  "$BASE/newsAlerts/start"
```

| Body field | Values |
|------------|--------|
| `currency_filter` | `USD` or `ALL` |
| `hours_ahead` | Same window as UI (default 72) |

Server polls every `NEWS_ALERT_POLL_MS` (default 30s) and sends Telegram **5 minutes before** each High-impact event (`NEWS_ALERT_MINUTES_BEFORE`, default 5). Requires Telegram configured on the VPS like other alert features.

### `POST /newsAlerts/stop`

```bash
curl -sS -X POST -H "X-API-Key: $KEY" "$BASE/newsAlerts/stop"
```

---

## Override feed URL (VPS)

On the Windows server, set env before starting `server.py`:

```text
NEWS_CALENDAR_URL=https://nfs.faireconomy.media/ff_calendar_thisweek.json
NEWS_CACHE_TTL=300
```

Use only trusted calendar URLs; the server fetches JSON over HTTPS and parses it server-side.

---

## Quick reference

| Goal | Call |
|------|------|
| Red folder list (USD, 72h) | `GET /getUpcomingNews?hours=72&impact=High&currency=USD` |
| All currencies | Omit `currency` |
| Dashboard behavior | Same query + refresh every 5 min |
| Pre-news Telegram | `POST /newsAlerts/start` |

See also: [`API_DOCUMENTATION.md`](API_DOCUMENTATION.md) sections 6–8.
