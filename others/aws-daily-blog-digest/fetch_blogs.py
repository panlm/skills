#!/usr/bin/env python3
"""Fetch AWS blog posts published during a single UTC day, grouped by category.

Data source: the AWS content-directory JSON API that powers aws.amazon.com/blogs/
  https://aws.amazon.com/api/dirs/items/search?item.directoryId=blog-posts&...
It returns EVERY channel in one feed, sorted by createdDate desc, with pagination
(size + page, 0-indexed) and metadata.totalHits. No auth, no JS rendering.

Category is parsed from the post link path /blogs/<slug>/ — the most reliable
signal (the dropdown channel names are not a single clean tag in the API).

Usage:
  fetch_blogs.py                 # previous UTC day (default)
  fetch_blogs.py --date 2026-09-25
  fetch_blogs.py --locale en_US  # default en_US; pass "" for all languages

Output: JSON to stdout ->
  {"date": "2026-09-25", "count": N,
   "categories": {"<Pretty Name>": [ {title, link, excerpt, authors, created, slug}... ]}}

Respects the no-WebFetch rule: all network I/O is curl with a hard timeout.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from collections import OrderedDict

API = "https://aws.amazon.com/api/dirs/items/search"
SIZE = 100
MAX_PAGES = 40  # guard; a single day never needs this many at size=100

# Slug -> display name overrides where Title-Case is wrong or an acronym is used.
# Anything not listed falls back to Title Case of the slug.
NAME_OVERRIDES = {
    "aws": "AWS News",
    "aws-cloud-financial-management": "AWS Cloud Financial Management",
    "machine-learning": "Artificial Intelligence",
    "mt": "AWS Cloud Operations",
    "devops": "DevOps & Developer Productivity",
    "database": "Database",
    "big-data": "Big Data",
    "hpc": "HPC",
    "iot": "Internet of Things",
    "apn": "AWS Partner Network",
    "awsmarketplace": "AWS Marketplace",
    "opensource": "Open Source",
    "gametech": "AWS for Games",
    "media": "Media & Entertainment",
    "networking-and-content-delivery": "Networking & Content Delivery",
    "publicsector": "Public Sector",
    "security": "Security",
    "storage": "Storage",
    "compute": "Compute",
    "containers": "Containers",
    "architecture": "Architecture",
    "developer": "Developer Tools",
    "mobile": "Front-End Web & Mobile",
    "quantum-computing": "Quantum Computing",
    "spatial": "Spatial Computing",
    "training-and-certification": "Training & Certification",
    "startups": "Startups",
    "enterprise-strategy": "Enterprise Strategy",
    "supply-chain": "Supply Chain",
    "smb": "Small & Medium Business",
    "industries": "Industries",
    "robotics": "Robotics",
    "messaging-and-targeting": "Messaging & Targeting",
    "business-intelligence": "Business Intelligence",
    "business-productivity": "Business Productivity",
    "contact-center": "Contact Center",
    "modernizing-with-aws": "Modernizing with AWS",
    "migration-and-modernization": "Migration & Modernization",
}

ACRONYMS = {"aws", "hpc", "iot", "apn", "smb", "ml", "ai", "sql", "db"}


def pretty(slug: str) -> str:
    if slug in NAME_OVERRIDES:
        return NAME_OVERRIDES[slug]
    words = [w.upper() if w in ACRONYMS else w.capitalize() for w in slug.split("-")]
    return " ".join(words)


def curl_json(url: str) -> dict:
    out = subprocess.run(
        ["curl", "-L", "--connect-timeout", "10", "--max-time", "60", "-sS",
         "-H", "Accept: application/json", url],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def category_of(link: str) -> str:
    m = re.search(r"/blogs/([^/]+)/", link or "")
    return m.group(1) if m else "unknown"


def fetch_day(day: dt.date, locale: str) -> dict:
    start = f"{day.isoformat()}T00:00:00Z"
    end = f"{(day + dt.timedelta(days=1)).isoformat()}T00:00:00Z"
    collected = []
    for page in range(MAX_PAGES):
        url = (f"{API}?item.directoryId=blog-posts"
               f"&sort_by=item.additionalFields.createdDate&sort_order=desc"
               f"&size={SIZE}&page={page}")
        if locale:
            url += f"&item.locale={locale}"
        data = curl_json(url)
        items = data.get("items", [])
        if not items:
            break
        stop = False
        for it in items:
            f = it["item"]["additionalFields"]
            created = f.get("createdDate")
            if not created:
                continue
            if created < start:      # desc-sorted: everything after is older -> stop
                stop = True
                break
            if created >= end:       # today / future -> skip, keep paging back
                continue
            collected.append({
                "created": created,
                "slug": category_of(f.get("link")),
                "title": (f.get("title") or "").strip(),
                "link": f.get("link"),
                "authors": f.get("contributors"),
                "excerpt": (f.get("postExcerpt") or "").strip(),
            })
        if stop:
            break

    # group by pretty category name, sorted; posts within a category oldest->newest
    groups = OrderedDict()
    for post in sorted(collected, key=lambda p: (pretty(p["slug"]), p["created"])):
        groups.setdefault(pretty(post["slug"]), []).append(post)
    return {"date": day.isoformat(), "count": len(collected), "categories": groups}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="UTC day YYYY-MM-DD (default: previous UTC day)")
    ap.add_argument("--locale", default="en_US",
                    help='item.locale filter (default en_US; "" = all languages)')
    args = ap.parse_args()

    if args.date:
        day = dt.date.fromisoformat(args.date)
    else:
        day = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)

    result = fetch_day(day, args.locale)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
