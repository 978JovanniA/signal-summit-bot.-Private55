#!/usr/bin/env python3
"""
Signal Summit Weekly — options-trading newsletter bot.

Every run:
  1. Asks Claude (with live web search) to research the upcoming trading week
     and draft a Discord-ready newsletter in Signal Summit's house style.
  2. Splits the draft into <=2000-character chunks (Discord's hard limit).
  3. Posts each chunk to the configured Discord webhook, in order.

Required environment variables (set as GitHub Actions secrets — see SETUP.md):
  ANTHROPIC_API_KEY   - from console.anthropic.com
  DISCORD_WEBHOOK_URL - from your Discord channel's Integrations > Webhooks
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

import anthropic

DISCORD_MAX_LEN = 2000

SYSTEM_PROMPT = """You write "Signal Summit Weekly," a Sunday newsletter for a small, \
active Discord community of options traders (~25 members, a mix of new and \
experienced). The tone is direct, scannable, and written for someone who trades \
for a living — not investment advice, no hype, no filler.

Structure every newsletter like this:
1. A one-line header: "SIGNAL SUMMIT WEEKLY — <date range>" plus a one-line \
disclaimer that this isn't financial advice.
2. "THE BIG PICTURE" — 2-4 sentences on what happened last week (Fed, rates, \
major indices, yields) and why it matters for this week's options positioning.
3. Any single standout macro/political event worth flagging (e.g. a summit, an \
election, an OPEC meeting) if genuinely relevant this week — otherwise skip this.
4. "THE WEEK" — a day-by-day rundown (Mon-Fri, all times ET) of the economic data \
releases, Fed speakers, and notable earnings reports, using real, current, \
correctly-dated information you find via web search. Do NOT guess dates or times \
you can't verify — omit anything you're not confident about rather than inventing \
a plausible-sounding number.
5. "SETUPS ON OUR RADAR" — 3-5 bullets naming specific tickers or sectors worth \
watching this week and briefly why (earnings reaction, gap risk, rate-sensitivity, \
etc.), framed as things to watch, never as trade recommendations.
6. A short closing line inviting the community to post their own setups.

Formatting rules:
- Plain Discord markdown only: **bold**, ## headers, bullet points (•), emoji \
sparingly for section headers (📰 🌎 📅 🎯 💡).
- No markdown tables (Discord renders them poorly).
- Keep the whole thing tight — this is a chat post, not a report. Target roughly \
1500-3000 characters total.
- Never state a date, price, or figure you are not reasonably confident is \
accurate as of the search results you retrieved. If sources conflict or a date is \
ambiguous, leave that item out rather than guess.
- Output ONLY the newsletter text, ready to paste into Discord as-is. No preamble, \
no "Here's the newsletter," no meta-commentary.
"""


def generate_newsletter() -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 8,
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    "Research the upcoming trading week (the week starting this "
                    "coming Monday) and write this week's Signal Summit Weekly "
                    "newsletter. Use web search to confirm real dates, times, "
                    "earnings reports, and economic data releases — today's date "
                    "is whatever the search results indicate; ground everything "
                    "in that."
                ),
            }
        ],
    )

    # Concatenate all text blocks from the final assistant turn (search results
    # and intermediate tool calls are handled server-side by the API for the
    # web_search tool, so response.content holds the final text blocks).
    text_parts = [block.text for block in response.content if block.type == "text"]
    newsletter = "\n".join(text_parts).strip()

    if not newsletter:
        raise RuntimeError("Model returned no text content — aborting post.")

    return newsletter


def split_for_discord(text: str, limit: int = DISCORD_MAX_LEN) -> list[str]:
    """Split text into Discord-safe chunks, breaking on blank lines where possible."""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        # Prefer to break at the last blank line before the limit.
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def post_to_discord(webhook_url: str, content: str) -> None:
    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook returned {e.code}: {body}") from e


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    print("Generating newsletter...")
    newsletter = generate_newsletter()
    print(f"Generated {len(newsletter)} characters.")

    chunks = split_for_discord(newsletter)
    print(f"Posting in {len(chunks)} message(s)...")

    for i, chunk in enumerate(chunks, start=1):
        post_to_discord(webhook_url, chunk)
        print(f"  Posted chunk {i}/{len(chunks)}.")
        if i < len(chunks):
            time.sleep(1)  # be polite to Discord's rate limit between chunks

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
