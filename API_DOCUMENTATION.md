# AlphaFX REST API — Detailed Reference

This document lists **every HTTP call** used in the AlphaFX stack. The primary live trading API is **`mt5_vps_api/server.py`** (Windows VPS, port **8080**). Chart bundle and auth live on separate services.

| Service | File / deploy | Default port | Auth |
|---------|----------------|--------------|------|
| **MT5 VPS Trade API** | `mt5_vps_api/server.py` | 8080 | `X-API-Key` |
| **Alpha Analyser (chart bundle)** | `mt5_vps_api/alpha_analyser_ec2/server.py` or `alpha-analyser/backend` | 8090 | `X-API-Key` and/or JWT |
| **Docker MT5 API** | `Docker_mt5/server.py` | 5000 | varies (often open on localhost) |
| **Public candles** | `https://alphafx.org/api/candles/...` | 443 | none |

**Example VPS base URL:** `http://15.135.71.95:8080`

```bash
export BASE="http://15.135.71.95:8080"
export KEY="alphafx"
export HDR=(-H "X-API-Key: $KEY")
```

---

## Conventions (MT5 VPS API)

### Authentication

- **Required on almost all routes:** header `X-API-Key: alphafx` (or query `?api_key=alphafx`).
- **Exceptions (no key):** `GET /health`, `GET /version`.
- **401:** `{"ok": false, "error": "unauthorized"}`

### MetaTrader 5

Routes that touch the terminal are marked **(MT5)**. If MT5 is not connected:

- **503:** `{"ok": false, "error": "mt5 not connected", "detail": "..."}`

### JSON bodies

Use `Content-Type: application/json`. Invalid or empty body is treated as `{}`.

### Timeframes

`M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M10`, `M12`, `M15`, `M20`, `M30`, `H1`, `H2`, `H3`, `H4`, `H6`, `H8`, `H12`, `D1`, `W1`, `MN1`

### Market / pending order types (`placeOrder`, schedules)

| `type` | Meaning |
|--------|---------|
| `buy` | Market buy |
| `sell` | Market sell |
| `buy_limit` | Pending buy limit |
| `sell_limit` | Pending sell limit |
| `buy_stop` | Pending buy stop |
| `sell_stop` | Pending sell stop |

Market orders may use **`sl` / `tp`** (price) or **`sl_points` / `tp_points`** (distance from entry). Pending orders require **`price`**.

---

# Part 1 — MT5 VPS Trade API (`server.py` v1.8.7)

## 1. `GET /health`

**Auth:** none · **MT5:** no

Liveness probe.

```bash
curl -sS "$BASE/health"
```

**Response**

```json
{"ok": true, "service": "mt5-vps-trade-api", "version": "1.8.7"}
```

---

## 2. `GET /version`

**Auth:** none · **MT5:** no

```bash
curl -sS "$BASE/version"
```

**Response**

```json
{"ok": true, "service": "mt5-vps-trade-api", "version": "1.8.7", "file": "server.py"}
```

---

## 3. `GET /getAccountHealth`

**Auth:** yes · **MT5:** no (uses MT5 account APIs internally)

Full account health: balance, equity, margin, drawdown, floating P/L, **today’s closed P/L** and deal count.

**Query:** none

```bash
curl -sS "${HDR[@]}" "$BASE/getAccountHealth"
```

**Useful fields**

| Field | Meaning |
|-------|---------|
| `today.closed_pl` | Realized P/L for the server’s “today” window |
| `today.deals_count` | Closed deals counted for today |
| `balance`, `equity`, `margin`, `free_margin` | Standard account metrics |

For full deal history by date range, use **`GET /getHistory`** (below).

---

## 4. `GET /getHistory` **(MT5)**

Recent account **deals** from MT5 history (closed trade legs by default).

| Query | Required | Default | Description |
|-------|----------|---------|-------------|
| `start` | no* | — | Range start: `YYYY-MM-DD`, `DD.MM.YYYY`, or ISO datetime |
| `end` | no* | — | Range end (date includes full day through 23:59:59) |
| `days` | no | `30` | Last N days if `start`/`end` omitted (max **366**) |
| `symbol` | no | all | Filter by symbol |
| `magic` | no | all | Filter by magic number |
| `closed_only` | no | `true` | If true, only **OUT** deals (typical closed-trade P/L) |
| `limit` | no | `5000` | Max rows returned (newest first); max **10000** |

\* Use **`start` + `end`** for an explicit range, or **`days`** alone for rolling window.

```bash
# Last 7 days, closed legs only
curl -sS "${HDR[@]}" "$BASE/getHistory?days=7"

# Calendar range
curl -sS "${HDR[@]}" \
  "$BASE/getHistory?start=2026-09-01&end=2026-10-03&symbol=XAUUSD.pr&limit=200"

# All deal rows (entries + exits)
curl -sS "${HDR[@]}" \
  "$BASE/getHistory?start=01.09.2026&end=03.10.2026&closed_only=false"
```

**Response (example)**

```json
{
  "ok": true,
  "from": "2026-09-01T00:00:00",
  "to": "2026-10-04T00:00:00",
  "count": 42,
  "truncated": false,
  "closed_only": true,
  "summary": {"profit": 120.5, "commission": -4.2, "swap": -1.1, "net": 115.2},
  "deals": [
    {
      "ticket": 999001,
      "order": 888001,
      "position_id": 777001,
      "time": "2026-10-02T14:30:00Z",
      "type": "sell",
      "entry": "out",
      "volume": 0.01,
      "price": 2650.12,
      "profit": 25.0,
      "net": 24.5,
      "symbol": "XAUUSD.pr",
      "magic": 78001,
      "comment": "API"
    }
  ]
}
```

---

## 5. `GET /getPrice` **(MT5)**

Live bid/ask for one symbol.

| Query | Required | Description |
|-------|----------|-------------|
| `symbol` | yes | e.g. `XAUUSD`, `XAUUSD.pr` |

```bash
curl -sS "${HDR[@]}" "$BASE/getPrice?symbol=XAUUSD.pr"
```

**Response (example)**

```json
{
  "ok": true,
  "symbol": "XAUUSD.pr",
  "bid": 2650.12,
  "ask": 2650.45,
  "last": 2650.30,
  "spread_points": 33.0,
  "spread": 0.33,
  "time": "2026-10-02T18:30:00Z",
  "digits": 2,
  "point": 0.01
}
```

---

## 5. `GET /getCandles` **(MT5)**

Historical OHLCV from MT5.

| Query | Required | Default | Limits |
|-------|----------|---------|--------|
| `symbol` | yes | — | |
| `timeframe` | no | `M5` | See timeframes list |
| `count` | no | `100` | **Max 5000** |

```bash
curl -sS "${HDR[@]}" \
  "$BASE/getCandles?symbol=XAUUSD.pr&timeframe=M5&count=500"
```

---

## 6. `GET /getUpcomingNews`

Forex Factory–style calendar (high-impact events).

| Query | Default | Description |
|-------|---------|-------------|
| `hours` | `72` | Lookahead 1–168 |
| `impact` | `High` | Impact filter |
| `currency` | `` | Comma-separated, e.g. `USD,EUR` |

```bash
curl -sS "${HDR[@]}" \
  "$BASE/getUpcomingNews?hours=48&impact=High&currency=USD"
```

**Errors:** **502** if feed unavailable (`calendar feed unavailable`).

---

## 7. `GET /newsAlerts/status`

**Auth:** yes

Returns state of the background “alert before news” worker.

```bash
curl -sS "${HDR[@]}" "$BASE/newsAlerts/status"
```

---

## 8. `POST /newsAlerts/start`

**Auth:** yes · **MT5:** no

Start Telegram alerts N minutes before high-impact news.

**Body**

| Field | Default | Description |
|-------|---------|-------------|
| `currency_filter` | `USD` | `USD` or `ALL` |
| `hours_ahead` | `72` | Calendar window |

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"currency_filter":"USD","hours_ahead":72}' \
  "$BASE/newsAlerts/start"
```

---

## 9. `POST /newsAlerts/stop`

**Auth:** yes

Stops news alert worker.

```bash
curl -sS -X POST "${HDR[@]}" "$BASE/newsAlerts/stop"
```

---

## 10. `GET /getAnalysis` **(MT5)**

Multi-timeframe trend, RSI, order blocks, zigzag, FVG — JSON for overlays (same engine family as Alpha Analyser).

| Query | Required | Default |
|-------|----------|---------|
| `symbol` | yes | — |
| `timeframe` | no | `M5` |
| `count` | no | `200` | clamped 50–5000 |

```bash
curl -sS "${HDR[@]}" \
  "$BASE/getAnalysis?symbol=XAUUSD.pr&timeframe=M15&count=300"
```

---

## 11. `GET /getTradeSuggestion` **(MT5)**

Suggested pending setup from analysis: side, entry, SL, TP, R:R.

| Query | Required | Default | Notes |
|-------|----------|---------|-------|
| `symbol` | yes | — | |
| `timeframe` | no | `M5` | |
| `count` | no | `200` | 50–5000 |
| `ob_time` | no | — | Pin to specific OB bar |
| `ob_type` | no | — | OB type filter |
| `risky` | no | false | `1` / `true` / `yes` |

```bash
curl -sS "${HDR[@]}" \
  "$BASE/getTradeSuggestion?symbol=XAUUSD.pr&timeframe=M5&risky=false"
```

---

## 12. `POST /placeOrder` **(MT5)**

Single market or pending order.

**Body**

| Field | Required | Notes |
|-------|----------|-------|
| `symbol` | yes | |
| `type` | no | default `buy` |
| `volume` | no | default `0.01` |
| `price` | pending | Required for limit/stop |
| `sl`, `tp` | no | Prices |
| `sl_points`, `tp_points` | no | Alternative to sl/tp |
| `magic` | no | default from server `DEFAULT_MAGIC` |
| `comment` | no | default `API` |
| `deviation` | no | default `50` |
| `watch` | no | If true, register **suggestion watch** |
| `watch_meta` | with `watch` | `ob_time`, `ob_type`, `chart_timeframe`, `count` |

**Market buy**

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","type":"buy","volume":0.01,"sl_points":500,"tp_points":1000,"magic":9001}' \
  "$BASE/placeOrder"
```

**Buy limit with suggestion watch**

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{
    "symbol":"XAUUSD.pr","type":"buy_limit","volume":0.01,"price":2645.0,
    "sl":2640,"tp":2660,"watch":true,
    "watch_meta":{"ob_time":"2026-10-02T12:00:00Z","ob_type":"bullish","chart_timeframe":"M5","count":200}
  }' \
  "$BASE/placeOrder"
```

---

## 13. `POST /placeTrades` **(MT5)**

Batch of orders; same fields per element as `placeOrder`.

**Body:** `{ "trades": [ { ... }, { ... } ] }`

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"trades":[{"symbol":"XAUUSD.pr","type":"buy","volume":0.01}]}' \
  "$BASE/placeTrades"
```

**Response:** `placed`, `total`, `results[]` per index.

---

## 14. `GET /getPositions` **(MT5)**

Open positions.

| Query | Description |
|-------|-------------|
| `ticket` | Single position |
| `symbol` | Filter by symbol |
| `magic` | Filter after fetch |

```bash
curl -sS "${HDR[@]}" "$BASE/getPositions?symbol=XAUUSD.pr&magic=78001"
```

**Response:** `count`, `total_profit`, `positions[]`.

---

## 15. `GET /getOrders` **(MT5)**

Pending orders (limits/stops).

Same query params as `getPositions`: `ticket`, `symbol`, `magic`.

```bash
curl -sS "${HDR[@]}" "$BASE/getOrders?symbol=XAUUSD.pr"
```

---

## 16. `POST /closePositions` **(MT5)**

Close one or many positions (not named `closePosition` on this server).

**Body**

| Field | Description |
|-------|-------------|
| `ticket` | Close one ticket |
| `symbol` | Close all on symbol |
| `magic` | Filter |
| `volume` | Partial close size |
| `deviation` | default 50 |
| `comment` | default `API close` |

If no `ticket`/`symbol`, closes **all** open positions (after magic filter).

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"ticket":123456789}' \
  "$BASE/closePositions"
```

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001}' \
  "$BASE/closePositions"
```

---

## 17. `POST /modifyPosition` **(MT5)**

Change SL/TP on an open position.

**Body:** `ticket` **required**; then either prices or points:

| Field | Meaning |
|-------|---------|
| `sl`, `tp` | New prices |
| `sl_points`, `tp_points` | From entry; `-1` removes SL/TP |

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"ticket":123456789,"sl_points":400,"tp_points":800}' \
  "$BASE/modifyPosition"
```

---

## 18. `POST /trailPosition_MODE1` **(MT5)**

Register **mode 1** trailing stop on a ticket (server-managed poll loop).

**Body:** `ticket`, `trail_points` (or `step_points`)

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"ticket":123456789,"trail_points":200}' \
  "$BASE/trailPosition_MODE1"
```

---

## 19. `POST /trailPosition_MODE2` **(MT5)**

Register **mode 2** trailing (step-based).

**Body:** `ticket`, `step_points` (or `trail_points`)

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"ticket":123456789,"step_points":150}' \
  "$BASE/trailPosition_MODE2"
```

---

## 20. `POST /trail/stop`

Stop trailing job(s).

**Body:** `{ "ticket": 123 }` or omit `ticket` to stop **all** jobs.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"ticket":123456789}' \
  "$BASE/trail/stop"
```

---

## 21. `GET /trail/status`

List active trailing jobs.

```bash
curl -sS "${HDR[@]}" "$BASE/trail/status"
```

---

## 22. `POST /placeGrid` **(MT5)**

Deploy grid of pending orders around anchor.

**Body**

| Field | Default | Description |
|-------|---------|-------------|
| `symbol` | — | **required** |
| `lot` | `0.01` | Per order |
| `distance` | `100` | Spacing (points) |
| `initial_distance` | `200` | First level offset |
| `orders_quantity` | `50` | Max orders |
| `incremental` | `false` | Lot scaling |
| `magic` | `78001` | |
| `anchor` | auto | Center price |
| `tp_points`, `sl_points` | `0` | Per-order TP/SL |
| `max_floating_profit` | `0` | If &gt; 0, auto **gridGuard** |
| `basket_tp_profit` / `basket_tp` | `0` | If &gt; 0, auto **basketTp** job |
| `basket_sl_loss` / `basket_sl` | same as TP | Basket loss target (USD) |

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","lot":0.01,"distance":100,"orders_quantity":20,"magic":78001,"basket_tp_profit":50}' \
  "$BASE/placeGrid"
```

---

## 23. `POST /schedule/grid`

Schedule a future **placeGrid** (IST/timezone-aware).

**Body:** scheduling fields + all `placeGrid` params in same JSON:

| Scheduling | Description |
|------------|-------------|
| `date` | Date string |
| `time` | Time string |
| `timezone` | default `IST` |
| `offset_hours` | default `0` |
| `timeout_mmss` | default `00:00` |

Grid params (`symbol`, `lot`, …) are passed through in `payload`.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"date":"03.10.2026","time":"10:30:00","timezone":"IST","symbol":"XAUUSD.pr","lot":0.01,"distance":100}' \
  "$BASE/schedule/grid"
```

---

## 24. `POST /schedule/trade`

Schedule **market** buy/sell at IST time.

**Body:** `date`, `time`, `timezone`, `timeout_mmss`, plus `symbol`, `type` (`buy`/`sell`), `volume`, optional `sl_points`, `tp_points`, `magic`.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"date":"03.10.2026","time":"15:00:00","symbol":"XAUUSD.pr","type":"buy","volume":0.01,"sl_points":300,"tp_points":600}' \
  "$BASE/schedule/trade"
```

---

## 25. `GET /schedule/status`

List pending/completed scheduled jobs.

```bash
curl -sS "${HDR[@]}" "$BASE/schedule/status"
```

---

## 26. `POST /schedule/cancel`

Cancel scheduled job by id.

**Body:** `{ "id": "<schedule_uuid>" }`

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"id":"abc12345-6789-..."}' \
  "$BASE/schedule/cancel"
```

---

## 27. `POST /gridGuard/start` **(MT5)**

Monitor basket floating profit; when ≥ target, close all positions + cancel pendings.

**Body:** `symbol` (required), `magic` (default `78001`), `max_floating_profit` or `floating_profit` (USD, e.g. `2` = close at +$2)

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001,"max_floating_profit":25}' \
  "$BASE/gridGuard/start"
```

---

## 28. `POST /gridGuard/stop`

**Body:** optional `symbol` + `magic`; omit both to clear all guards.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001}' \
  "$BASE/gridGuard/stop"
```

---

## 29. `GET /gridGuard/status`

**Query:** optional `symbol`, `magic` — includes current basket `floating` when symbol given.

```bash
curl -sS "${HDR[@]}" "$BASE/gridGuard/status?symbol=XAUUSD.pr&magic=78001"
```

---

## 30. `POST /closeGridBasket` **(MT5)**

Manual basket exit: close positions + cancel pendings for symbol/magic; removes matching gridGuard and basketTp jobs.

**Body:** `symbol`, optional `magic`

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001}' \
  "$BASE/closeGridBasket"
```

---

## 31. `POST /basketTp/start` **(MT5)**

Background job: recalculate basket-wide TP/SL so combined P/L hits +target / −loss as new grid legs open.

**Body:** `symbol`, `magic`, `target_profit` (aliases: `basket_tp_profit`, `basket_tp`), optional `target_loss` (aliases: `basket_sl_loss`, `basket_sl`)

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001,"target_profit":50,"target_loss":50}' \
  "$BASE/basketTp/start"
```

---

## 32. `POST /basketTp/stop`

**Body:** optional `symbol` + `magic`; omit to remove all basket TP jobs.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001}' \
  "$BASE/basketTp/stop"
```

---

## 33. `GET /basketTp/status`

**Query:** optional `symbol`, `magic` — returns `jobs` and computed `levels` when configured.

```bash
curl -sS "${HDR[@]}" "$BASE/basketTp/status?symbol=XAUUSD.pr&magic=78001"
```

---

## 34. `POST /basketTp/apply` **(MT5)**

One-shot basket TP/SL apply (no background job).

**Body:** same as `basketTp/start`; `target_profit` must be &gt; 0.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","magic":78001,"target_profit":30}' \
  "$BASE/basketTp/apply"
```

---

## 35. `GET /suggestionWatch/status`

Lists OB maintenance jobs (auto cancel/update pendings when OB expires).

```bash
curl -sS "${HDR[@]}" "$BASE/suggestionWatch/status"
```

---

## 36. `POST /suggestionWatch/stop`

**Body:** `{ "ticket": 123 }` or `{ "all": true }` — stops watch only; does **not** cancel MT5 order.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"all":true}' \
  "$BASE/suggestionWatch/stop"
```

---

## 37. `GET /telegramAlerts/status`

Telegram OB signal worker state.

```bash
curl -sS "${HDR[@]}" "$BASE/telegramAlerts/status"
```

---

## 38. `POST /telegramAlerts/start` **(MT5)**

Candle-close monitoring → Telegram signals.

**Body:** `symbol` (default `XAUUSD`), `bar_count` (default `200`)

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","bar_count":200}' \
  "$BASE/telegramAlerts/start"
```

---

## 39. `POST /telegramAlerts/stop`

```bash
curl -sS -X POST "${HDR[@]}" "$BASE/telegramAlerts/stop"
```

---

## 40. `POST /telegramAlerts/test`

Send test message to configured Telegram channel.

```bash
curl -sS -X POST "${HDR[@]}" "$BASE/telegramAlerts/test"
```

---

## 41. `GET /autoTrade/status`

Auto-trade worker (M5+ candle-close OB → `placeOrder` with comment `alphafxauto`).

```bash
curl -sS "${HDR[@]}" "$BASE/autoTrade/status"
```

---

## 42. `POST /autoTrade/start` **(MT5)**

**Body**

| Field | Default |
|-------|---------|
| `symbol` | `XAUUSD` |
| `bar_count` | `200` |
| `lot_size` / `volume` | server default |
| `magic` | optional |

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD.pr","bar_count":200,"lot_size":0.01,"magic":202611}' \
  "$BASE/autoTrade/start"
```

---

## 43. `POST /autoTrade/stop`

Stops worker; does not close positions or cancel pendings.

```bash
curl -sS -X POST "${HDR[@]}" "$BASE/autoTrade/stop"
```

---

## 44. `POST /autoTrade/config`

Update `lot_size`, `magic`, `bar_count` while running.

```bash
curl -sS -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  -d '{"lot_size":0.02}' \
  "$BASE/autoTrade/config"
```

---

## MT5 VPS — Quick route table

| # | Method | Path | MT5 |
|---|--------|------|-----|
| 1 | GET | `/health` | |
| 2 | GET | `/version` | |
| 3 | GET | `/getAccountHealth` | |
| 4 | GET | `/getHistory` | ✓ |
| 5 | GET | `/getPrice` | ✓ |
| 6 | GET | `/getCandles` | ✓ |
| 7 | GET | `/getUpcomingNews` | |
| 8 | GET | `/newsAlerts/status` | |
| 9 | POST | `/newsAlerts/start` | |
| 10 | POST | `/newsAlerts/stop` | |
| 11 | GET | `/getAnalysis` | ✓ |
| 12 | GET | `/getTradeSuggestion` | ✓ |
| 13 | POST | `/placeOrder` | ✓ |
| 14 | POST | `/placeTrades` | ✓ |
| 15 | GET | `/getPositions` | ✓ |
| 16 | GET | `/getOrders` | ✓ |
| 17 | POST | `/closePositions` | ✓ |
| 18 | POST | `/modifyPosition` | ✓ |
| 19 | POST | `/trailPosition_MODE1` | ✓ |
| 20 | POST | `/trailPosition_MODE2` | ✓ |
| 21 | POST | `/trail/stop` | |
| 22 | GET | `/trail/status` | |
| 23 | POST | `/placeGrid` | ✓ |
| 24 | POST | `/schedule/grid` | |
| 25 | POST | `/schedule/trade` | |
| 26 | GET | `/schedule/status` | |
| 27 | POST | `/schedule/cancel` | |
| 28 | POST | `/gridGuard/start` | ✓ |
| 29 | POST | `/gridGuard/stop` | |
| 30 | GET | `/gridGuard/status` | |
| 31 | POST | `/closeGridBasket` | ✓ |
| 32 | POST | `/basketTp/start` | ✓ |
| 33 | POST | `/basketTp/stop` | |
| 34 | GET | `/basketTp/status` | |
| 35 | POST | `/basketTp/apply` | ✓ |
| 36 | GET | `/suggestionWatch/status` | |
| 37 | POST | `/suggestionWatch/stop` | |
| 38 | GET | `/telegramAlerts/status` | |
| 39 | POST | `/telegramAlerts/start` | ✓ |
| 40 | POST | `/telegramAlerts/stop` | |
| 41 | POST | `/telegramAlerts/test` | |
| 42 | GET | `/autoTrade/status` | |
| 43 | POST | `/autoTrade/start` | ✓ |
| 44 | POST | `/autoTrade/stop` | |
| 45 | POST | `/autoTrade/config` | |

**CORS:** `OPTIONS` on `/` and `/<path>` for browser clients.

---

# Part 2 — Alpha Analyser chart API

Full chart UI payload (candles + render layers + Elliott `point_labels`) is **`GET /getChartBundle`**, not on the Windows `:8080` server.

## `GET /getChartBundle` (Analyser backend)

**Deploy:** `mt5_vps_api/alpha_analyser_ec2/server.py` or production `alpha-analyser` backend (often **8090**).

**Auth:** `X-API-Key` (same secret as VPS unless configured otherwise).

| Query | Required | Default |
|-------|----------|---------|
| `symbol` | yes | — |
| `timeframe` | no | `M5` |
| `count` | no | `200` | 50–5000 |

```bash
export ANALYSER="http://127.0.0.1:8090"
curl -sS -H "X-API-Key: $KEY" \
  "$ANALYSER/getChartBundle?symbol=XAUUSD.pr&timeframe=M5&count=500"
```

**Includes (typical):** `candles`, structure/zigzag layers, `elliott_wave_markers`, `elliott_wave_point_labels`, `next_move_elliott_markers`, OB/FVG overlays.

## `GET /health` (Analyser EC2 helper)

```bash
curl -sS "$ANALYSER/health"
```

---

# Part 3 — Alpha Analyser auth API (`alpha-analyser/backend`)

Base path prefix: **`/api/auth`** and **`/api/admin`**. Uses **JWT/session**, not `X-API-Key`.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/auth/plans` | none | Subscription plans |
| GET | `/api/auth/payment-config` | none | USDT payment settings |
| POST | `/api/auth/quote` | none | Price quote |
| POST | `/api/auth/signup` | none | Register |
| POST | `/api/auth/subscribe` | user | Subscribe |
| POST | `/api/auth/verify-payment` | user | Verify on-chain payment |
| POST | `/api/auth/login` | none | Login → token |
| GET | `/api/auth/me` | user | Profile + subscription |
| POST | `/api/auth/logout` | user | Logout |
| GET | `/api/admin/users` | admin | List users |
| POST | `/api/admin/users` | admin | Create user |
| PATCH | `/api/admin/users/<id>` | admin | Update user |
| POST | `/api/admin/users/<id>/telegram/remove` | admin | Unlink Telegram |
| DELETE | `/api/admin/users/<id>` | admin | Delete user |
| GET | `/api/admin/telegram/health` | admin | Telegram bot health |
| GET | `/api/admin/tracking` | admin | Usage tracking |

**Login example**

```bash
curl -sS -X POST -H "Content-Type: application/json" \
  -d '{"email":"admin@alphafx.org","password":"YOUR_PASSWORD"}' \
  "http://127.0.0.1:8090/api/auth/login"
```

Use `Authorization: Bearer <token>` on protected routes.

---

# Part 4 — Docker MT5 API (`Docker_mt5/server.py` v2.1.0)

**Base:** `http://localhost:5000` (container). Full index at `GET /`.

### Connection

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/init` | Initialize MT5 |
| POST | `/api/shutdown` | Shutdown |
| GET | `/api/status` | Status |
| GET | `/api/version` | Version |

### Account & symbols

| GET | `/api/account` | Balance/equity |
| GET | `/api/symbols` | All symbols |
| GET | `/api/symbols/tradable?search=&limit=100` | Search tradable |
| GET | `/api/symbol/<symbol>` | Symbol info |
| POST | `/api/symbol/<symbol>/select` | Select in Market Watch |

### Prices & candles

| GET | `/api/price/<symbol>` | Bid/ask |
| GET | `/api/tick/<symbol>` | Last tick |
| GET | `/api/candles/<symbol>?timeframe=H1&count=100` | OHLCV |
| GET | `/api/rates/<symbol>` | Rates alias |

### Indicators (static & live)

| GET | `/api/indicator/rsi/<symbol>?period=14&timeframe=H1&count=100` | RSI |
| GET | `/api/indicator/ma/<symbol>?type=sma\|ema&period=14` | MA |
| GET | `/api/indicator/macd/<symbol>` | MACD |
| GET | `/api/indicator/bollinger/<symbol>` | Bollinger |
| GET | `/api/indicator/stochastic/<symbol>` | Stochastic |
| GET | `/api/indicator/atr/<symbol>` | ATR |
| GET | `/api/indicator/cci/<symbol>` | CCI |
| GET | `/api/indicator/williams/<symbol>` | Williams %R |
| GET | `/api/indicator/momentum/<symbol>` | Momentum |
| GET | `/api/live/all/<symbol>` | Bundle of live indicators |

### Trading

| POST | `/api/trade/open` | Open market |
| POST | `/api/trade/close` | Close position |
| POST | `/api/trade/close_all` | Close all |
| POST | `/api/trade/modify` | Modify SL/TP |
| POST | `/api/trade/pending` | Pending order |
| POST | `/api/order/cancel` | Cancel order |
| POST | `/api/order/cancel/<ticket>` | Cancel by ticket |
| GET | `/api/positions` | Open positions |
| GET | `/api/orders` | Pending orders |

### Trade history (use this when VPS has no history route)

| Method | Path | Parameters |
|--------|------|------------|
| GET | `/api/history/deals` | `days=30`, optional `symbol` |
| GET | `/api/history/orders` | `days=30` |
| POST | `/api/history/sync` | Force broker history sync |
| GET | `/history` | Legacy GUI: `start`, `end`, `symbol` (closed trades) |

**Deals example**

```bash
export DOCKER="http://localhost:5000"
curl -sS "$DOCKER/api/history/deals?days=30&symbol=XAUUSD"
```

**Legacy history (closed trades only)**

```bash
curl -sS "$DOCKER/history?start=2026-09-01&end=2026-10-01&symbol=XAUUSD"
```

### SMC & trend

| GET | `/api/trend/<symbol>` | Trend summary |
| GET | `/api/smc/<symbol>` | SMC v1 |
| GET | `/api/smc/v2/<symbol>` | SMC v2 |
| GET | `/api/smc/reverse/<symbol>` | Reverse setup |

### Trailing & watchdog

| POST | `/api/trailing/set` | Start trailing |
| POST | `/api/trailing/disable` | Stop |
| GET | `/api/trailing/status` | Status |
| POST | `/api/trailing/apply` | Apply once |
| POST | `/api/watchdog/start` | Price watchdog |
| POST | `/api/watchdog/stop` | |
| GET | `/api/watchdog/status` | |

### Utilities

| POST | `/api/calc/margin` | `{symbol, volume, type}` |
| POST | `/api/calc/profit` | Profit calc |
| GET | `/api/market/book/<symbol>` | DOM if available |

---

# Part 5 — Public candle API

No auth. Root symbols (e.g. `XAUUSD`, not `XAUUSD.pr`).

```bash
curl -sS "https://alphafx.org/api/candles/XAUUSD?timeframe=H1&count=5000"
```

| Param | Notes |
|-------|-------|
| `timeframe` | e.g. `M5`, `H1` |
| `count` | **Max 99,999** (100,000+ returns HTTP 400) |

---

# Part 6 — Trade history on Windows VPS

| Need | Where |
|------|--------|
| Date-range deals / closed trades | **`GET /getHistory`** on port **8080** (this server) |
| Today realized P/L only | `GET /getAccountHealth` → `today.closed_pl` |
| Open exposure | `GET /getPositions`, `GET /getOrders` |
| Docker / Linux MT5 container | `GET /api/history/deals` on port **5000** |
| Multi-account bridge | `GET /history?account=` with `X-Trade-Api-Key` if deployed |

---

## Document history

| Date | Notes |
|------|-------|
| 2026-10-03 | Full pass aligned to `mt5_vps_api/server.py` routes 1–44 |
| 2026-10-03 | Added `GET /getHistory` (v1.8.8) |
