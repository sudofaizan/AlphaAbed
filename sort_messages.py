#!/usr/bin/env python3
"""Sort / filter channel messages — show only trade-related signals."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from telethon.errors import ChannelInvalidError, ChannelPrivateError, UsernameInvalidError

from signals.classify import classify_text, format_signal_line
from telegram_util import build_client, require_env

_BLOCK_RE = re.compile(
    r"^(?P<header>\d{4}-\d{2}-\d{2} .+ UTC \| id=(?P<id>\d+))\n(?P<body>.*?)(?=\n---|\Z)",
    re.S | re.M,
)


def load_blocks_from_file(path: str) -> list[tuple[int, str, str]]:
    text = open(path, encoding="utf-8").read()
    blocks: list[tuple[int, str, str]] = []
    for m in _BLOCK_RE.finditer(text):
        msg_id = int(m.group("id"))
        header = m.group("header")
        body = m.group("body").strip()
        blocks.append((msg_id, header, body))
    return blocks


def print_sorted(blocks: list[tuple[int, str, str]], *, kinds: set[str]) -> None:
    counts: dict[str, int] = {}
    for msg_id, header, body in blocks:
        parsed = classify_text(body)
        counts[parsed.kind] = counts.get(parsed.kind, 0) + 1
        if parsed.kind not in kinds:
            continue
        print(header)
        print(format_signal_line(parsed, msg_id))
        if parsed.kind not in ("open_signal", "close_all", "partial_close"):
            preview = body.replace("\n", " ")[:160]
            print(preview)
        print("---")
        print()

    print("Summary:", file=sys.stderr)
    for kind, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {kind}: {n}", file=sys.stderr)


async def fetch_blocks(limit: int) -> list[tuple[int, str, str]]:
    channel = require_env("CHANNEL")
    client, _, _ = build_client()
    blocks: list[tuple[int, str, str]] = []
    async with client:
        await client.connect()
        if not await client.is_user_authorized():
            print("Not logged in.", file=sys.stderr)
            sys.exit(1)
        try:
            entity = await client.get_entity(channel)
        except (UsernameInvalidError, ChannelInvalidError, ValueError) as e:
            print(f"Channel error: {e}", file=sys.stderr)
            sys.exit(1)
        except ChannelPrivateError:
            print("Not a channel member.", file=sys.stderr)
            sys.exit(1)

        async for message in client.iter_messages(entity, limit=limit):
            when = message.date.strftime("%Y-%m-%d %H:%M UTC")
            body = (message.message or "").strip()
            if not body and message.media:
                body = f"[media: {type(message.media).__name__}]"
            blocks.append((message.id, f"{when} | id={message.id}", body))
    return blocks


def main() -> None:
    parser = argparse.ArgumentParser(description="Sort Telegram messages by type.")
    parser.add_argument("file", nargs="?", help="msg.txt from check_channel.py")
    parser.add_argument("-n", "--limit", type=int, default=100, help="Fetch last N if no file")
    parser.add_argument(
        "--only",
        default="open_signal,close_all,partial_close,incomplete_signal,sl_fragment",
        help="Comma-separated kinds to print",
    )
    args = parser.parse_args()
    kinds = {k.strip() for k in args.only.split(",") if k.strip()}

    if args.file:
        blocks = load_blocks_from_file(args.file)
    else:
        blocks = asyncio.run(fetch_blocks(args.limit))

    print_sorted(blocks, kinds=kinds)


if __name__ == "__main__":
    main()
