#!/usr/bin/env python3
"""Daemon: log new messages from a Telegram channel in real time."""

import asyncio
import logging
import os
import sys
from datetime import timezone

from telethon import events
from telethon.errors import ChannelInvalidError, ChannelPrivateError, UsernameInvalidError

from telegram_util import build_client, require_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("alphaabed")


def format_message(msg) -> str:
    when = msg.date.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (msg.message or "").strip()
    if not text and msg.media:
        text = f"[media: {type(msg.media).__name__}]"
    if not text:
        text = "[empty]"
    return f"{when} | id={msg.id} | {text}"


async def main() -> None:
    channel = require_env("CHANNEL")
    client, _, _ = build_client()

    await client.start()
    if not await client.is_user_authorized():
        log.error(
            "Not logged in. On EC2 run: ./venv/bin/python login_session.py "
            "(or set SESSION_STRING in .env)."
        )
        sys.exit(1)

    try:
        entity = await client.get_entity(channel)
    except (UsernameInvalidError, ChannelInvalidError, ValueError) as e:
        log.error("Could not resolve channel %r: %s", channel, e)
        sys.exit(1)
    except ChannelPrivateError:
        log.error("Channel is private or account is not a member.")
        sys.exit(1)

    title = getattr(entity, "title", channel)
    log.info("Watching channel: %s (%s)", title, channel)

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        log.info("New message: %s", format_message(event.message))

    poll_seconds = int(os.getenv("POLL_HEARTBEAT_SECONDS", "0"))
    if poll_seconds > 0:

        async def heartbeat():
            while True:
                await asyncio.sleep(poll_seconds)
                log.info("alive — still watching %s", channel)

        asyncio.create_task(heartbeat())

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
