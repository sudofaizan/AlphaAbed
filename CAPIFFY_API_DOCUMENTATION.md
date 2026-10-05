# Capiffy Trade API — Reference (AlphaAbed)

This documents **`https://api.capiffy.com`** as used by **AlphaAbed** (`app/capiffy/client.py`, `app/capiffy/auth.py`, `app/dual_trade.py`) and the related **[capicopy](https://github.com/sudofaizan/capicopy)** mirror (`automator.py`). Capiffy does not publish a full public OpenAPI spec; shapes below match the web app and our clients (auth refresh verified **2026-09**; market open **`/api/trade/open`** verified from browser **2026-10**).

**Related (not Capiffy):** AlphaFX MT5 REST API — see [`API_DOCUMENTATION.md`](API_DOCUMENTATION.md).

| Use case | How AlphaAbed calls Capiffy |
|----------|-----------------------------|
| Telegram auto-trade (market) | `POST /api/trade/open` in parallel with MT5 (`open_position`) |
| Dashboard test trades | Same; platform toggle MT5 / Capiffy / both |
| Pending mirror (capicopy only) | `POST/PATCH/DELETE /api/trade/order` — not used by AlphaAbed signals |

---

## Table of contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Request headers (all trade calls)](#request-headers-all-trade-calls)
4. [Endpoints](#endpoints)
   - [POST /api/auth/refresh](#post-apiauthrefresh)
   - [GET /api/trade/snapshot/{accountId}](#get-apitradessnapshotaccountid)
   - [POST /api/trade/open](#post-apitradeopen)
   - [POST /api/trade/order](#post-apitradeorder)
   - [GET /api/charts/symbols](#get-apichartssymbols)
   - [PATCH /api/trade/order/{orderId}](#patch-apitradeorderorderid)
   - [DELETE /api/trade/order/{orderId}](#delete-apitradeorderorderid)
   - [PATCH /api/trade/position/{positionId}](#patch-apitradepositionpositionid)
   - [DELETE /api/trade/position/{positionId}](#delete-apitradepositionpositionid)
5. [Order types & fields](#order-types--fields)
6. [Python client (this repo)](#python-client-this-repo)
7. [curl cheat sheet](#curl-cheat-sheet)
8. [MT5 mirror (how it uses the API)](#mt5-mirror-how-it-uses-the-api)
9. [Setup & tokens](#setup--tokens)
10. [Errors & troubleshooting](#errors--troubleshooting)

---

## Overview

| Item | Value |
|------|--------|
| **Base URL** | `https://api.capiffy.com` |
| **Web origin** | `https://capiffy.com` |
| **Account scope** | `accountId` on place + snapshot paths |
| **Token lifetime (typical)** | Access JWT ~**15 min**; refresh JWT ~**7 days** |
| **Bridge role** | Poll MT5 pendings → place/modify/cancel Capiffy orders; optional position SL/TP sync |

Capiffy is **not** the same server as your MT5 VPS API. The mirror runs on EC2 (or locally) and talks to **both**:

```text
MT5 VPS (:8080)  ──poll──►  automator.py  ──HTTPS──►  api.capiffy.com
```

---

## Authentication

Every **trade** request needs a valid **access token** (JWT). AlphaAbed stores tokens in **`data/capiffy_tokens.json`** (auto-updated on refresh) and loads secrets from **`.env`**.

### Credentials you need once (from browser login)

| Env variable | Source |
|--------------|--------|
| `CAPIFFY_ACCESS_TOKEN` | DevTools → request header `Authorization: Bearer …` |
| `CAPIFFY_REFRESH_TOKEN` | Cookie `refreshToken=…` on capiffy.com |
| `CAPIFFY_DEVICE_CID` | Header `x-device-cid` (must stay **fixed** — same as browser session) |
| `CAPIFFY_ACCOUNT_ID` | From place-order JSON or app UI (e.g. `cmtl3opa…`) |

**Important:** Use one consistent **`x-device-cid`** everywhere (`.env`, `tokens.json`, refresh, trade). Do not generate a random CID per request.

### Token refresh flow

1. Load access + refresh from `tokens.json` or `.env`.
2. If access expires within **120 seconds**, call refresh.
3. Save new tokens to `tokens.json`.

Manual test:

```bash
cd /path/to/AlphaAbed
python3 -c "from app.capiffy.auth import get_valid_tokens; t=get_valid_tokens(); print('access expires in', t.access_expires_in(), 's')"
```

Dashboard: **Test Capiffy connection** (`POST /api/test/capiffy`).

---

## Request headers (all trade calls)

| Header | Required | Value |
|--------|----------|--------|
| `Authorization` | yes | `Bearer <access_token>` |
| `Content-Type` | yes (JSON body) | `application/json` |
| `Accept` | yes | `application/json, text/plain, */*` |
| `x-device-cid` | strongly recommended | Same CID as browser |
| `Cookie` | recommended | `refreshToken=<refresh_jwt>` |
| `Origin` | yes (browser-like) | `https://capiffy.com` |
| `Referer` | yes (browser-like) | `https://capiffy.com/` |
| `User-Agent` | yes | Modern Chrome UA string |

The Python client sets these in `app.capiffy.client._request()`.

---

## Endpoints

### POST `/api/auth/refresh`

Obtain a new **access token** (and optionally rotated refresh token).

**Auth:** `refreshToken` cookie (not Bearer on access for this call).

**Body**

| Mode (`CAPIFFY_REFRESH_BODY`) | Body |
|-------------------------------|------|
| `empty` (default) | `{}` |
| `json` | `{"refreshToken":"<jwt>"}` |
| `none` | no body |

**Example curl**

```bash
export REFRESH="YOUR_REFRESH_JWT"
export DEVICE_CID="fe38920eec8f239d"

curl -sS -X POST "https://api.capiffy.com/api/auth/refresh" \
  -H "accept: application/json, text/plain, */*" \
  -H "content-type: application/json" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -d '{}'
```

**Response (shape varies):** JSON may include `accessToken` / `data.accessToken`; refresh may arrive in JSON or `Set-Cookie: refreshToken=…`.

**Errors:** HTTP **401** — refresh expired → log in again on capiffy.com and re-paste tokens.

---

### GET `/api/trade/snapshot/{accountId}`

**Single call for account state:** balance/equity metrics (when present), **open orders**, **open positions**.

This is how you **get account balance** and open risk in one round trip (exact balance field names depend on Capiffy’s JSON; the bridge reads `data.orders` and `data.positions`).

| Path param | Description |
|------------|-------------|
| `accountId` | Your Capiffy account id (`CAPIFFY_ACCOUNT_ID`) |

**Example curl**

```bash
export ACCESS="YOUR_ACCESS_JWT"
export ACCOUNT="cmtl3opaom6bnuqi0hoh8wd3d"
export DEVICE_CID="fe38920eec8f239d"
export REFRESH="YOUR_REFRESH_JWT"

curl -sS "https://api.capiffy.com/api/trade/snapshot/$ACCOUNT" \
  -H "accept: application/json, text/plain, */*" \
  -H "authorization: Bearer $ACCESS" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH"
```

**Response structure (used by bridge)**

```json
{
  "data": {
    "orders": [ { "id": "...", "symbol": "XAUUSD", "side": "BUY", "type": "LIMIT", "volume": 0.01, "price": 2650.0, "stopLoss": 2640.0, "takeProfit": 2660.0 } ],
    "positions": [ { "id": "...", "symbol": "XAUUSD", "side": "BUY", "volume": 0.01, "stopLoss": null, "takeProfit": null } ]
  }
}
```

Additional keys under `data` (e.g. balance, equity, margin) may exist — dump a live snapshot once:

```bash
python3 -c "from app.config_store import load_config; from app.capiffy.client import get_snapshot; import json; print(json.dumps(get_snapshot(cfg=load_config()), indent=2))"
```

**Python**

```python
from app.capiffy.client import get_snapshot, get_open_orders, get_open_positions

snap = get_snapshot(cfg=load_config())   # account from config or CAPIFFY_ACCOUNT_ID
orders = get_open_orders(cfg=cfg)
positions = get_open_positions(cfg=cfg)
```

---

### POST `/api/trade/open`

**Open a market position** — this is what the Capiffy **web app** uses when you click Buy/Sell at market (not a pending limit).

**Auth:** Same trade headers (Bearer + `x-device-cid` + `refreshToken` cookie).

**JSON body**

| Field | Required | Description |
|-------|----------|-------------|
| `accountId` | yes | Capiffy account id |
| `symbolTicker` | yes | e.g. `XAUUSD` |
| `side` | yes | `BUY` or `SELL` |
| `volume` | yes | Lot size |
| `stopLoss` | no | SL price (if API accepts on open) |
| `takeProfit` | no | TP price |

**Example (from DevTools)**

```bash
curl -sS -X POST "https://api.capiffy.com/api/trade/open" \
  -H "authorization: Bearer $ACCESS" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -d '{"accountId":"'"$ACCOUNT"'","symbolTicker":"XAUUSD","side":"SELL","volume":0.01}'
```

**Python (AlphaAbed)**

```python
from app.capiffy.client import open_position

open_position(symbol="XAUUSD", side="SELL", volume=0.01, stop_loss=2645.0, take_profit=2660.0, cfg=cfg)
```

**Note:** AlphaAbed **`place_order(..., order_type="MARKET")`** delegates to **`open_position()`** → this endpoint. Pending types still use `/api/trade/order` below.

---

### POST `/api/trade/order`

**Open a pending order** on Capiffy (limit/stop). Creates a Capiffy **order** waiting for price — used by **capicopy** when mirroring MT5 pendings, not for Abeid Telegram market signals.

**JSON body**

| Field | Required | Description |
|-------|----------|-------------|
| `accountId` | yes | Capiffy account id |
| `symbolTicker` | yes | e.g. `XAUUSD`, `EURUSD` (uppercase) |
| `side` | yes | `BUY` or `SELL` |
| `volume` | yes | Lot size (float) |
| `orderType` | yes | `LIMIT` or `STOP` |
| `price` | yes* | Limit/stop price (*required for pending types) |
| `stopLoss` | no | SL price |
| `takeProfit` | no | TP price |

**MT5 → Capiffy mapping (mirror)**

| MT5 pending type | `side` | `orderType` |
|------------------|--------|-------------|
| `buy_limit` | `BUY` | `LIMIT` |
| `sell_limit` | `SELL` | `LIMIT` |
| `buy_stop` | `BUY` | `STOP` |
| `sell_stop` | `SELL` | `STOP` |

Market `buy`/`sell` on MT5 are **not** mirrored as Capiffy pendings by default (automator skips non-pending types).

**Example — buy limit XAUUSD**

```bash
curl -sS -X POST "https://api.capiffy.com/api/trade/order" \
  -H "authorization: Bearer $ACCESS" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -d '{
    "accountId": "'"$ACCOUNT"'",
    "symbolTicker": "XAUUSD",
    "side": "BUY",
    "volume": 0.01,
    "orderType": "LIMIT",
    "price": 2650.50,
    "stopLoss": 2645.00,
    "takeProfit": 2660.00
  }'
```

**Response:** JSON with order id under `data.id` / `data.orderId` (see `extract_order_id()` in `app/capiffy/client.py`).

**Python**

```python
from app.capiffy.client import place_order

place_order(
    symbol="XAUUSD",
    side="BUY",
    volume=0.01,
    order_type="LIMIT",
    price=2650.50,
    stop_loss=2645.0,
    take_profit=2660.0,
)
```

**CLI**

```bash
python3 -c "from app.config_store import load_config; from app.capiffy.client import place_order; print(place_order(symbol='XAUUSD', side='BUY', volume=0.01, order_type='LIMIT', price=2650.50, cfg=load_config()))"
```

---

### PATCH `/api/trade/order/{orderId}`

**Modify a pending order** (price, SL, TP, volume).

**JSON body (send only fields you change)**

| Field | Type | Description |
|-------|------|-------------|
| `price` | float | New limit/stop price |
| `stopLoss` | float | New SL |
| `takeProfit` | float | New TP |
| `volume` | float | New size |

**Example**

```bash
export ORDER_ID="cap_order_uuid_here"

curl -sS -X PATCH "https://api.capiffy.com/api/trade/order/$ORDER_ID" \
  -H "authorization: Bearer $ACCESS" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -d '{"price": 2651.0, "stopLoss": 2646.0, "takeProfit": 2661.0}'
```

**Python**

```python
from app.capiffy.client import modify_order

modify_order(order_id, price=2651.0, stop_loss=2646.0, take_profit=2661.0)
```

**When mirror uses it:** MT5 pending `#ticket` changes price/SL/TP/volume → automator PATCHes the linked Capiffy order.

---

### DELETE `/api/trade/order/{orderId}`

**Cancel a pending order** (not the same as closing a filled position).

**Example**

```bash
curl -sS -X DELETE "https://api.capiffy.com/api/trade/order/$ORDER_ID" \
  -H "authorization: Bearer $ACCESS" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/"
```

**Python**

```python
from app.capiffy.client import cancel_order

cancel_order(order_id)
```

**When mirror uses it:** MT5 pending removed → Capiffy pending cancelled.

---

### PATCH `/api/trade/position/{positionId}`

**Modify SL/TP on an open trade (position)** after fill.

**JSON body**

| Field | Type | Description |
|-------|------|-------------|
| `stopLoss` | float | New SL price |
| `takeProfit` | float | New TP price |

At least one required.

**Example**

```bash
export POSITION_ID="cap_position_uuid_here"

curl -sS -X PATCH "https://api.capiffy.com/api/trade/position/$POSITION_ID" \
  -H "authorization: Bearer $ACCESS" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/" \
  -d '{"stopLoss": 2655.0, "takeProfit": 2670.0}'
```

**Python**

```python
from app.capiffy.client import modify_position

modify_position(position_id, stop_loss=2655.0, take_profit=2670.0)
```

**When mirror uses it:** `MIRROR_POSITIONS=true` — MT5 position SL/TP change → PATCH Capiffy position.

---

### DELETE `/api/trade/position/{positionId}`

**Close an open trade** at market (Capiffy-side close).

**Example**

```bash
curl -sS -X DELETE "https://api.capiffy.com/api/trade/position/$POSITION_ID" \
  -H "authorization: Bearer $ACCESS" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/"
```

**Python**

```python
from app.capiffy.client import close_position

close_position(position_id)
```

**When mirror uses it:** MT5 position closed → automator closes linked Capiffy position.

**Note:** If DELETE fails in your environment, capture the **working** request from Chrome DevTools (method, URL, headers) — Capiffy may add query flags or alternate routes in future app versions.

---

### GET `/api/charts/symbols`

**Public symbol list** for charts (no `Authorization` header required). Useful to confirm tickers (`XAUUSD`, etc.).

```bash
curl -sS "https://api.capiffy.com/api/charts/symbols" \
  -H "accept: */*" \
  -H "origin: https://capiffy.com" \
  -H "referer: https://capiffy.com/"
```

---

## Order types & fields

### Capiffy pending order object (snapshot / responses)

Fields the mirror compares:

| Field | Meaning |
|-------|---------|
| `id` | Capiffy order id (use in PATCH/DELETE paths) |
| `symbol` | Ticker (e.g. `XAUUSD`) |
| `side` | `BUY` / `SELL` |
| `type` | `LIMIT` / `STOP` |
| `volume` | Size |
| `price` | Order price |
| `stopLoss` | SL |
| `takeProfit` | TP |

### Capiffy position object

| Field | Meaning |
|-------|---------|
| `id` | Position id (PATCH/DELETE paths) |
| `symbol` / `symbolTicker` | Ticker |
| `side` | `BUY` / `SELL` |
| `volume` | Open size |
| `stopLoss` / `takeProfit` | Current SL/TP |

### Symbol mapping (MT5 → Capiffy)

Configured via `MIRROR_SYMBOL_MAP` JSON or defaults in `automator.py` (e.g. `XAUUSD.I#` → `XAUUSD`, `GOLD.I#` → `XAUUSD`).

---

## Python client (AlphaAbed)

Module: **`app/capiffy/client.py`**. Auth: **`app/capiffy/auth.py`**. Parallel MT5+Capiffy: **`app/dual_trade.py`**.

| Function | HTTP | Purpose |
|----------|------|---------|
| `get_valid_tokens()` (`auth`) | POST refresh | Ensure fresh access token |
| `get_snapshot(...)` | GET snapshot | Balance + orders + positions |
| `get_open_orders()` | GET snapshot | `data.orders` |
| `get_open_positions()` | GET snapshot | `data.positions` |
| `open_position(...)` | POST **open** | **Market** open (AlphaAbed default) |
| `place_order(...)` | POST open or order | `MARKET` → open; `LIMIT`/`STOP` → order |
| `modify_order(...)` | PATCH order | Change pending |
| `cancel_order(order_id)` | DELETE order | Cancel pending |
| `modify_position(...)` | PATCH position | Change SL/TP |
| `close_position(position_id)` | DELETE position | Close one trade |
| `close_all_symbol(symbol, cfg)` | DELETE × N | Close all positions for ticker |
| `extract_order_id(response)` | — | Parse id from place response |
| `test_capiffy_connection(cfg)` (`dual_trade`) | GET snapshot | Dashboard connection test |

All trade calls go through `_request()` which attaches Bearer + `x-device-cid` + refresh cookie.

---

## curl cheat sheet

Replace tokens from `.env` / `tokens.json`. Refresh access if you get **401**:

```bash
# 1) Refresh
curl -sS -X POST "https://api.capiffy.com/api/auth/refresh" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -d '{}' | jq .

# 2) Snapshot (balance + orders + positions)
curl -sS "https://api.capiffy.com/api/trade/snapshot/$ACCOUNT" \
  -H "authorization: Bearer $ACCESS" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" | jq .

# 3) Place limit buy
curl -sS -X POST "https://api.capiffy.com/api/trade/order" \
  -H "authorization: Bearer $ACCESS" \
  -H "content-type: application/json" \
  -H "x-device-cid: $DEVICE_CID" \
  -H "Cookie: refreshToken=$REFRESH" \
  -d '{"accountId":"'"$ACCOUNT"'","symbolTicker":"XAUUSD","side":"BUY","volume":0.01,"orderType":"LIMIT","price":2650,"stopLoss":2645,"takeProfit":2660}'
```

---

## MT5 mirror (how it uses the API)

**Process:** `automator.py` (see `run_automator.sh` / systemd `capiffy-mirror` on EC2).

| Step | MT5 VPS | Capiffy API |
|------|---------|-------------|
| Poll | `GET /getOrders`, `GET /getPositions` | — |
| New pending | — | `POST /api/trade/order` |
| Pending changed | — | `PATCH /api/trade/order/{id}` |
| Pending removed | — | `DELETE /api/trade/order/{id}` |
| Pending filled → position | Link by symbol/side/volume | — |
| Position SL/TP change | — | `PATCH /api/trade/position/{id}` |
| Position closed on MT5 | — | `DELETE /api/trade/position/{id}` |
| Background | — | Token refresh via `POST /api/auth/refresh` |

**Env (mirror)**

| Variable | Default | Meaning |
|----------|---------|---------|
| `MIRROR_POLL_SEC` | `5` | MT5 poll interval |
| `TOKEN_REFRESH_SEC` | `600` | Proactive token check |
| `MIRROR_POSITIONS` | `true` | Sync open position SL/TP + close |
| `MIRROR_MAGIC` | (all) | Only mirror this MT5 magic |
| `MIRROR_SYMBOL_MAP` | JSON | MT5 symbol → Capiffy ticker |
| `MIRROR_MISSING_GRACE` | `3` | Polls before treating Capiffy order as gone |

State file: `mirror_state.json` maps MT5 ticket → Capiffy order/position ids.

---

## Setup & tokens (AlphaAbed)

1. Copy `.env.example` → `.env`.
2. From DevTools on **`POST /api/trade/open`** or snapshot: paste `CAPIFFY_ACCESS_TOKEN`, `CAPIFFY_REFRESH_TOKEN`, `CAPIFFY_DEVICE_CID`, `CAPIFFY_ACCOUNT_ID`.
3. Dashboard → **Test Capiffy connection**.
4. Settings → enable Capiffy, set **Capiffy lot** (can differ from MT5 lot), symbol `XAUUSD`.
5. Test **BUY/SELL** with platform **Capiffy only** or **Both (parallel)** before enabling auto-trade.

**EC2:** Outbound **443** to `api.capiffy.com`; tokens live in `.env` + `data/capiffy_tokens.json` (gitignored via `data/`).

**Do not commit:** `.env`, `data/capiffy_tokens.json`.

**capicopy mirror (separate):** see [capicopy README](https://github.com/sudofaizan/capicopy) — `tokens.json`, `automator.py`, pending sync only.

---

## Errors & troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Capiffy HTTP 401` | Expired access | Restart app or force refresh via `get_valid_tokens(force_refresh=True)` |
| Refresh HTTP 401 | Expired refresh (~7d) | Re-login capiffy.com; update `.env` |
| `No account_id` | Missing `CAPIFFY_ACCOUNT_ID` | Set in `.env` / snapshot URL |
| SSL errors on Mac Python | Cert store | `CAPIFFY_SSL_VERIFY=false` in `.env` (dev only) |
| Close position DELETE fails | API change or wrong id | Copy working curl from DevTools |
| Duplicate Capiffy orders | Orphan pendings | Mirror cancels duplicates; check `mirror_state.json` |
| Wrong symbol on Capiffy | MT5 suffix | Set `MIRROR_SYMBOL_MAP` |

Runtime errors from the client look like:

```text
RuntimeError: Capiffy HTTP 400: {"message":"..."}
```

Always log full body on **4xx/5xx** when debugging new endpoints.

---

## Quick reference table

| Action | Method | Path |
|--------|--------|------|
| Refresh session | POST | `/api/auth/refresh` |
| Chart symbols (public) | GET | `/api/charts/symbols` |
| Account snapshot (balance, orders, positions) | GET | `/api/trade/snapshot/{accountId}` |
| **Open market position** | POST | **`/api/trade/open`** |
| Place pending order | POST | `/api/trade/order` |
| Modify pending | PATCH | `/api/trade/order/{orderId}` |
| Cancel pending | DELETE | `/api/trade/order/{orderId}` |
| Modify open trade SL/TP | PATCH | `/api/trade/position/{positionId}` |
| Close open trade | DELETE | `/api/trade/position/{positionId}` |

---

## Document history

| Date | Notes |
|------|-------|
| 2026-10-06 | Initial doc from capicopy client / automator |
| 2026-10-06 | AlphaAbed paths, `POST /api/trade/open`, `/api/charts/symbols`, dual-trade notes |
