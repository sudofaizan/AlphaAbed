"""Shared Telegram client helpers."""

import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession


def require_env(name: str) -> str:
    load_dotenv()
    value = os.getenv(name)
    if not value:
        print(f"Missing {name}. Copy .env.example to .env and fill it in.", file=sys.stderr)
        sys.exit(1)
    return value


def build_client() -> tuple[TelegramClient, int, str]:
    api_id = int(require_env("API_ID"))
    api_hash = require_env("API_HASH")
    session_string = os.getenv("SESSION_STRING", "").strip()
    if session_string:
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
    else:
        session_name = os.getenv("SESSION_NAME", "telegram_session")
        client = TelegramClient(session_name, api_id, api_hash)
    return client, api_id, api_hash
