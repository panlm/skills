#!/usr/bin/env python3
"""Scan subscribed blogs and print UNREAD articles from the last N days.

Wraps `blogwatcher-cli` (a local tool with its own subscription database):
  blogwatcher-cli scan            -> refresh feeds
  blogwatcher-cli articles --all  -> list all known articles ([new]/[read])
  blogwatcher-cli read <id>       -> mark one article read (ONE id per call)

Only UNREAD ([new]) articles inside the date window are emitted, plus a
machine-readable `IDS_TO_MARK_READ:` line. Marking-read is intentionally NOT
done here — the delivery step marks an id read only after the summary is
actually delivered, so a failed delivery doesn't silently drop an article.

Dependency: `blogwatcher-cli` on PATH + its subscription DB. This is NOT
portable; it must run on the host where blogwatcher-cli is installed and its
subscriptions were migrated.

Date parsing keeps two production fixes:
- window is computed from today (not hardcoded), so new posts actually surface;
- HTML-scraped blogs put the date inside the title line ("Sep 18, 2026"),
  with the month sometimes glued to preceding text, so no leading boundary.

Usage: scan_unread.py [--days 3]
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

os.environ["PATH"] = os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", "")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def article_date(block):
    """Return YYYY-MM-DD for an article block, or None."""
    m = re.search(r"Published:\s*(\d{4}-\d{2}-\d{2})", block)
    if m:
        return m.group(1)
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
                  r"(\d{1,2}),\s*(\d{4})", block.split("\n")[0])
    if m and m.group(1) in MONTHS:
        return "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(1)], int(m.group(2)))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="today + previous N-1 days")
    ap.add_argument("--unsafe-client", action="store_true",
                    help="pass through to blogwatcher-cli; needed only when the host's "
                         "outbound HTTP proxy is a loopback address (blogwatcher's SSRF "
                         "guard otherwise refuses to connect to a 127.0.0.1 proxy)")
    args = ap.parse_args()
    extra = ["--unsafe-client"] if args.unsafe_client else []

    if not _has("blogwatcher-cli"):
        sys.exit("ERROR: blogwatcher-cli not found on PATH. This skill needs it "
                 "plus a migrated subscription DB; run on the openclaw host.")

    scan = subprocess.run(["blogwatcher-cli", "scan", *extra], capture_output=True, text=True)
    print("=== SCAN RESULT ===")
    print(scan.stdout)

    res = subprocess.run(["blogwatcher-cli", "articles", "--all", *extra],
                         capture_output=True, text=True)

    now = datetime.now()
    window = {(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(args.days)}

    articles, current = [], []
    for line in res.stdout.split("\n"):
        if line.strip().startswith("[") and "]" in line:
            if current:
                articles.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        articles.append("\n".join(current))

    print("=== UNREAD ARTICLES (window: %s) ===" % ", ".join(sorted(window, reverse=True)))
    selected = []
    for article in articles:
        if article_date(article) not in window:
            continue
        if "[read]" in article.split("\n")[0]:
            continue
        aid = re.match(r"\s*\[(\d+)\]", article)
        if aid:
            selected.append(aid.group(1))
        print(article)
        print()

    if not selected:
        print("No new unread articles in the last %d days." % args.days)
    else:
        print("\nTotal: %d unread articles in the last %d days" % (len(selected), args.days))
        print("IDS_TO_MARK_READ: " + " ".join(selected))


def _has(cmd):
    from shutil import which
    return which(cmd) is not None


if __name__ == "__main__":
    main()
