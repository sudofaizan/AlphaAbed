#!/usr/bin/env python3
"""One-time interactive login; prints SESSION_STRING for headless servers."""

import asyncio
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

from telegram_util import require_env


async def main() -> None:
    api_id = int(require_env("API_ID"))
    api_hash = require_env("API_HASH")
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()
    if not await client.is_user_authorized():
        print("Complete Telegram login in this terminal.", file=sys.stderr)
        await client.start()
    session_string = client.session.save()
    print("\nAdd this line to .env on your EC2 instance:\n")
    print(f"SESSION_STRING={session_string}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
