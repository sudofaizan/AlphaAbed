# XAUBeast — ALPHAFX

Telegram channel watcher & trading dashboard (repo folder: AlphaAbed).

Python tools to read and watch **one Telegram channel** with your account ([Telethon](https://docs.telethon.dev/)).

Repo: [github.com/sudofaizan/AlphaAbed](https://github.com/sudofaizan/AlphaAbed)

## Prerequisites

1. [my.telegram.org/apps](https://my.telegram.org/apps) → **api_id** and **api_hash**
2. Your Telegram account must **join** the channel (or be admin)

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env
```

### One-shot: last N messages

```bash
python check_channel.py
```

Last **5** messages into **msg.txt** (EC2):

```bash
chmod +x fetch_msg.sh
./fetch_msg.sh 5 msg.txt
cat msg.txt
```

Or directly:

```bash
./venv/bin/python check_channel.py -n 5 -o msg.txt
```

### Daemon: new messages (local test)

```bash
python watch_channel.py
```

### Headless session (for EC2)

Amazon Linux has **`python3`**, not `python`. From the repo directory:

```bash
cp .env.example .env   # set API_ID and API_HASH first
chmod +x login.sh
./login.sh
```

Or, if `venv` already exists:

```bash
./venv/bin/python login_session.py
```

Copy the printed `SESSION_STRING=...` into `.env`, then run `./deploy_ec2.sh`.

## Web dashboard (port 80 on EC2)

After deploy, open **`http://YOUR_EC2_IP/`** (allow **TCP 80** in the EC2 security group).

The UI includes:

- Poll interval, MT5 URL (`http://15.135.71.95:8080`), API key (`alphafx`), symbol (`XAUUSD.pr`), **0.1 lot**
- **Reward:risk** for TP (default **1:2**) when the message has no TP
- **Test Telegram** / **Test MT5** buttons
- **Today P/L** from `GET /getAccountHealth`
- **Signal history** — last 100 messages, **signals only** (no VIP spam)
- **Auto-trade** toggle (off by default)

Local dev:

```bash
./run_web.sh   # http://localhost:8000
```

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for AlphaFX endpoints used: `/getPrice`, `/placeOrder`, `/closePositions`, `/getAccountHealth`.

## Deploy on Amazon Linux (EC2)

After SSH to the instance:

```bash
git clone https://github.com/sudofaizan/AlphaAbed.git
cd AlphaAbed
cp .env.example .env
nano .env   # API_ID, API_HASH, CHANNEL, SESSION_STRING
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

The script installs Python deps, registers **systemd** service `alphaabed`, and starts the watcher daemon.

```bash
sudo systemctl status alphaabed
sudo journalctl -u alphaabed -f
```

Re-deploy after `git pull`:

```bash
./deploy_ec2.sh
```

Optional: run as a specific user (default: user running the script):

```bash
SERVICE_USER=ec2-user ./deploy_ec2.sh
```

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `API_ID` | yes | Telegram app id |
| `API_HASH` | yes | Telegram app hash |
| `CHANNEL` | yes | `@name` or `-100…` id |
| `SESSION_STRING` | EC2 | From `login_session.py` |
| `LIMIT` | no | Messages for `check_channel.py` (default 20) |
| `POLL_HEARTBEAT_SECONDS` | no | Daemon heartbeat in logs (default 300, `0` disables) |

## Sort signals vs noise

From `msg.txt`:

```bash
./venv/bin/python sort_messages.py msg.txt
```

Trade-related only (default kinds):

```bash
./venv/bin/python sort_messages.py msg.txt --only open_signal,close_all,partial_close,incomplete_signal,sl_fragment
```

Live fetch + sort:

```bash
./venv/bin/python sort_messages.py -n 100
```

**Kinds:** `open_signal` (BUY/SELL + SL), `close_all` (“Closing all.”), `partial_close`, `incomplete_signal` / `sl_fragment` (e.g. entry then next message `SL 4134`), `promo`, `commentary`.

## MT5 API (optional)

When a classified message is actionable, the daemon can POST JSON to your backend.

| Env | Default | Meaning |
|-----|---------|---------|
| `MT5_AUTO_TRADE` | `false` | Call API on signals |
| `MT5_DRY_RUN` | `true` | Log only, no HTTP |
| `MT5_API_URL` | `http://127.0.0.1:8080` | Base URL |

**Open order body** (`POST` `{MT5_OPEN_PATH}`):

```json
{
  "action": "open",
  "side": "sell",
  "symbol": "XAUUSD",
  "entry": 4147,
  "entry_min": null,
  "entry_max": null,
  "sl": 4155,
  "tp": null,
  "market": false,
  "source": "telegram",
  "source_message_id": 1500
}
```

**Close all** (`POST` `{MT5_CLOSE_PATH}`): `{"action":"close_all","source_message_id":1502}`

Set `MT5_DRY_RUN=false` and `MT5_AUTO_TRADE=true` only after your API matches this shape (or tell us your API schema to adapt).

## Security

Do not commit `.env`, `*.session`, or session strings.
