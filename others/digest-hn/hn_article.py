#!/usr/bin/env python3
"""Resolve ONE Hacker News item to its real article and print it for summarizing.

The newsnow `hackernews` source returns HN *discussion* URLs
(https://news.ycombinator.com/item?id=<id>), not the story's external link. This
helper takes an HN id (or such a URL), looks up the real target via the public
HN Firebase API, fetches + strips the article body, and prints a compact block.

Usage:
  hn_article.py <hn_id | hn_item_url> [--max-chars 2000]

Output to stdout:
  TITLE: ...
  SCORE: ...
  URL:   ...            (external article; "(self post)" for Ask/Show HN)
  ---
  <clean body text>     OR  NOTE: <why unavailable> (blocked / no content)

Used one-at-a-time by the digest-hn skill so each summary streams out as its
article is fetched — never batch-fetch everything first.
"""
import argparse
import html
import re
import subprocess
import sys


def curl(url, t=20):
    try:
        return subprocess.run(
            ["curl", "-L", "--connect-timeout", "8", "--max-time", str(t), "-sS",
             "-A", "Mozilla/5.0 (news-digest)", url],
            capture_output=True, text=True).stdout
    except Exception:
        return ""


def strip_html(h):
    h = re.sub(r'(?is)<(script|style|nav|header|footer|svg|form|noscript).*?</\1>', ' ', h)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'(?s)<[^>]+>', ' ', h))).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", help="HN item id or news.ycombinator.com/item?id=<id> URL")
    ap.add_argument("--max-chars", type=int, default=2000)
    args = ap.parse_args()

    m = re.search(r"(\d{5,})", args.ref)
    if not m:
        sys.exit(f"NOTE: cannot parse HN id from {args.ref!r}")
    hid = m.group(1)

    import json
    raw = curl(f"https://hacker-news.firebaseio.com/v0/item/{hid}.json")
    try:
        item = json.loads(raw or "{}")
    except json.JSONDecodeError:
        item = {}
    title = item.get("title") or "(unknown title)"
    url = item.get("url")
    text = item.get("text")
    score = item.get("score")

    print(f"TITLE: {title}")
    print(f"SCORE: {score}")
    print(f"URL:   {url or '(self post)'}")
    print("---")

    if url:
        body = strip_html(curl(url))
        if not body or "unusual traffic" in body or "Enable JavaScript and cookies" in body:
            print(f"NOTE: article body not retrievable (blocked/empty): {url}")
        else:
            print(body[:args.max_chars])
    elif text:
        print(strip_html(text)[:args.max_chars])
    else:
        print("NOTE: no external URL and no self-post text; summarize from the title.")


if __name__ == "__main__":
    main()
