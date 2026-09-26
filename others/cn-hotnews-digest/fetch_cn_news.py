#!/usr/bin/env python3
"""Fetch real-time hot lists from 10 Chinese news platforms via `npx newsnow`.

Each platform returns its current hot-search / newsflash list (title + url).
Output: JSON grouped by pretty platform name, for a scannable hot-list digest.

Usage:
  fetch_cn_news.py [--limit 10] [--sources weibo,zhihu,...]

Package: pinned to `newsnow@1.1.1` (npm, github.com/sorrycc/newsnow) for
reproducibility — a small standalone scraping CLI, not the ourongxing/newsnow
web app.

Source-id note (verified 2026-09-26): the original Hermes config used
`36kr-quick` and `cls-telegraph`, but both are broken upstream — 36kr newsflash
HTML scraping now hits anti-bot socket resets, and cls's telegraph endpoint
returns 404 (removed). Swapped to the working JSON-API variants `36kr-renqi`
(36氪人气/热门文章) and `cls-hot` (财联社热门). Semantically close for a
hot-list digest, not identical to newsflashes; revert if you specifically need
realtime newsflashes and upstream gets fixed.

Portable timeout: uses subprocess timeout (macOS has no `timeout` binary), so
one hung platform can't stall the run. Requires Node + `npx` (newsnow is
auto-fetched by `npx -y` on first use; needs network).
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import OrderedDict

NEWSNOW_PKG = "newsnow@1.1.1"

# id -> display name (order = digest order)
PLATFORMS = OrderedDict([
    ("toutiao", "今日头条热搜"),
    ("weibo", "微博热搜"),
    ("zhihu", "知乎热榜"),
    ("36kr-renqi", "36氪人气"),
    ("wallstreetcn-quick", "华尔街见闻快讯"),
    ("cls-hot", "财联社热门"),
    ("thepaper", "澎湃新闻"),
    ("ithome", "IT之家"),
    ("hackernews", "Hacker News"),
    ("jin10", "金十数据"),
])

# Strip invisible unicode that trips content/injection scanners downstream.
_INVISIBLE_RE = re.compile(
    r'[​‌‍⁠﻿­‎‏‪-‮]')


def clean(s):
    return _INVISIBLE_RE.sub('', s or '').strip()


def fetch(source_id, limit):
    try:
        out = subprocess.run(
            ["npx", "-y", NEWSNOW_PKG, source_id, "--json", "--limit", str(limit)],
            capture_output=True, text=True, timeout=45,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[cn-news] timeout: {source_id}\n")
        return []
    if not out.stdout.strip():
        sys.stderr.write(f"[cn-news] no output: {source_id} (exit {out.returncode})\n")
        return []
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(f"[cn-news] bad json: {source_id}\n")
        return []
    # newsnow reports a broken adapter as {"error": "...", "code": "FETCH_ERROR"},
    # NOT as an empty item list — so skip on missing `items`, not on count==0.
    if not isinstance(data, dict) or "items" not in data:
        err = data.get("error") if isinstance(data, dict) else None
        sys.stderr.write(f"[cn-news] source error: {source_id}: {err}\n")
        return []
    items = []
    for it in data.get("items", []):
        title = clean(it.get("title") or it.get("id"))
        url = it.get("url") or it.get("mobileUrl")
        if title and url:
            items.append({"title": title, "url": url})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--sources", help="comma list of platform ids (default: all 10)")
    args = ap.parse_args()

    ids = args.sources.split(",") if args.sources else list(PLATFORMS)
    result = OrderedDict()
    for sid in ids:
        pretty = PLATFORMS.get(sid, sid)
        items = fetch(sid, args.limit)
        if items:
            result[pretty] = items
        sys.stderr.write(f"[cn-news] {pretty}: {len(items)}\n")

    out = {
        "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "platforms": result,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
