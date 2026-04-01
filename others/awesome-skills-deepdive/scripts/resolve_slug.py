#!/usr/bin/env python3
"""
Resolve a ClawHub slug to a GitHub raw SKILL.md URL.

The slug format is "{author}-{skill-name}" but both parts can contain hyphens,
so we try multiple split positions and check which one returns HTTP 200.

Usage:
    python resolve_slug.py olivieralter-alter-actions
    python resolve_slug.py --manifest /tmp/skill-manifest.json --output /tmp/resolved-manifest.json
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


RAW_BASE = "https://raw.githubusercontent.com/openclaw/skills/main/skills"


def try_resolve(author: str, skill_name: str) -> str | None:
    """Try fetching SKILL.md for a given author/skill-name split. Return URL if 200."""
    url = f"{RAW_BASE}/{author}/{skill_name}/SKILL.md"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return url
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        pass
    return None


def resolve_slug(slug: str) -> dict:
    """
    Resolve a slug to author, skill-name, and raw SKILL.md URL.

    Strategy: try splitting the slug at each hyphen position from left to right.
    The first split that returns HTTP 200 wins.
    """
    parts = slug.split("-")
    if len(parts) < 2:
        return {"slug": slug, "resolved": False, "error": "no hyphen in slug"}

    for i in range(1, len(parts)):
        author = "-".join(parts[:i])
        skill_name = "-".join(parts[i:])
        url = try_resolve(author, skill_name)
        if url:
            return {
                "slug": slug,
                "resolved": True,
                "author": author,
                "skill_name": skill_name,
                "raw_url": url,
                "github_url": f"https://github.com/openclaw/skills/tree/main/skills/{author}/{skill_name}",
            }

    return {"slug": slug, "resolved": False, "error": "no valid split found"}


def resolve_manifest(manifest_path: str, output_path: str, delay: float = 0.3):
    """Resolve all slugs in a manifest file."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    total = manifest["total_skills"]
    resolved_count = 0
    failed_count = 0
    idx = 0

    for category in manifest["categories"]:
        for skill in category["skills"]:
            idx += 1
            slug = skill["slug"]
            result = resolve_slug(slug)
            skill.update(result)

            if result["resolved"]:
                resolved_count += 1
                status = "OK"
            else:
                failed_count += 1
                status = f"FAIL: {result.get('error', 'unknown')}"

            print(f"  [{idx:>4}/{total}] {slug} → {status}")
            time.sleep(delay)  # Rate limit

    manifest["resolved_count"] = resolved_count
    manifest["failed_count"] = failed_count

    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nResolved: {resolved_count}/{total}, Failed: {failed_count}")
    print(f"Saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Resolve ClawHub slugs to GitHub URLs")
    parser.add_argument("slug", nargs="?", help="Single slug to resolve")
    parser.add_argument("--manifest", help="Manifest JSON to resolve all slugs")
    parser.add_argument("--output", help="Output path for resolved manifest")
    parser.add_argument(
        "--delay", type=float, default=0.3, help="Delay between requests (seconds)"
    )
    args = parser.parse_args()

    if args.slug:
        result = resolve_slug(args.slug)
        print(json.dumps(result, indent=2))
    elif args.manifest and args.output:
        resolve_manifest(args.manifest, args.output, args.delay)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
