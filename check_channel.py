#!/usr/bin/env python3
"""Fetch recent messages from a Telegram channel you can access."""

import argparse
import asyncio
import os
import sys
from datetime import timezone

from telethon.errors import ChannelInvalidError, ChannelPrivateError, UsernameInvalidError

from telegram_util import build_client, require_env


def message_body(msg) -> str:
    text = (msg.message or "").strip()
    if not text and msg.media:
        text = f"[media: {type(msg.media).__name__}]"
    if not text:
        text = "[empty]"
    return text


def format_message(msg, *, full: bool = False) -> str:
    when = msg.date.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = message_body(msg)
    if not full:
        preview = text.replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:197] + "..."
        text = preview
    return f"{when} | id={msg.id}\n{text}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch recent Telegram channel messages.")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=int(os.getenv("LIMIT", "20")),
        help="Number of messages (default: LIMIT env or 20)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=os.getenv("OUTPUT", ""),
        help="Write full messages to this file (e.g. msg.txt)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    channel = require_env("CHANNEL")
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
        header = f"Channel: {title} ({channel})\nLast {args.limit} messages:\n"

        lines: list[str] = []
        count = 0
        async for message in client.iter_messages(entity, limit=args.limit):
            lines.append(format_message(message, full=bool(args.output)))
            count += 1

        if count == 0:
            body = "(no messages found)\n"
        else:
            body = "\n---\n\n".join(lines) + "\n"

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(header)
                f.write("\n")
                f.write(body)
            print(f"Wrote {count} message(s) to {args.output}")
        else:
            print(header, end="")
            print(body, end="")


if __name__ == "__main__":
    asyncio.run(main())
