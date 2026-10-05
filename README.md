# AlphaAbed — Telegram channel watcher

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

### Daemon: new messages (local test)

```bash
python watch_channel.py
```

### Headless session (for EC2)

On a machine where you can enter the Telegram login code:

```bash
python login_session.py
```

Copy the printed `SESSION_STRING=...` into `.env` on the server.

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

## Security

Do not commit `.env`, `*.session`, or session strings.
