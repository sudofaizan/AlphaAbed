#!/usr/bin/env python3
"""Fetch recent messages from a Telegram channel you can access."""

import asyncio
import os
import sys
from datetime import timezone

from telethon.errors import ChannelInvalidError, ChannelPrivateError, UsernameInvalidError

from telegram_util import build_client, require_env


def format_message(msg) -> str:
    when = msg.date.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (msg.message or "").strip()
    if not text and msg.media:
        text = f"[media: {type(msg.media).__name__}]"
    if not text:
        text = "[empty]"
    preview = text.replace("\n", " ")
    if len(preview) > 200:
        preview = preview[:197] + "..."
    return f"{when} | id={msg.id} | {preview}"


async def main() -> None:
    channel = require_env("CHANNEL")
    limit = int(os.getenv("LIMIT", "20"))
    client, _, _ = build_client()

    async with client:
        if not await client.is_user_authorized():
            print("First run: log in with your Telegram account (phone + code).")
            await client.start()
        else:
            await client.connect()

        try:
            entity = await client.get_entity(channel)
        except (UsernameInvalidError, ChannelInvalidError, ValueError) as e:
            print(f"Could not resolve channel {channel!r}: {e}", file=sys.stderr)
            sys.exit(1)
        except ChannelPrivateError:
            print(
                "Channel is private or you are not a member. Join it with this account first.",
                file=sys.stderr,
            )
            sys.exit(1)

        title = getattr(entity, "title", channel)
        print(f"Channel: {title} ({channel})\nLast {limit} messages:\n")

        count = 0
        async for message in client.iter_messages(entity, limit=limit):
            print(format_message(message))
            count += 1

        if count == 0:
            print("(no messages found)")


if __name__ == "__main__":
    asyncio.run(main())
