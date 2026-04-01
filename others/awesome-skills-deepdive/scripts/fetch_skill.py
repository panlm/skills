#!/usr/bin/env python3
"""
Fetch an entire skill directory (SKILL.md + all bundled resources) from GitHub.

Uses the GitHub API to recursively list the skill directory, then downloads
all files including _meta.json. The _meta.json from the upstream repo is the
source of truth for version, author, and publish timestamp.

Usage:
    # Fetch a single skill by author/name
    python fetch_skill.py --author steipete --name apple-notes \
      --output-dir /path/to/deepdive/category/apple-notes

    # Fetch by slug (auto-resolves author/name via _meta.json)
    python fetch_skill.py --slug steipete-apple-notes \
      --output-dir /path/to/deepdive/category/apple-notes
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


GITHUB_API_BASE = "https://api.github.com/repos/openclaw/skills/contents/skills"
RAW_BASE = "https://raw.githubusercontent.com/openclaw/skills/main/skills"


def github_api_get(url: str, timeout: float = 15) -> dict | list | None:
    """GET a GitHub API endpoint, return parsed JSON or None on failure."""
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        import os

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            req.add_header("Authorization", f"token {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  API error for {url}: {e}", file=sys.stderr)
        return None


def fetch_raw_file(url: str, timeout: float = 15) -> tuple[bytes | None, dict]:
    """
    Fetch a raw file from GitHub. Returns (content_bytes, headers_dict).
    """
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            headers = {"etag": resp.headers.get("ETag")}
            return content, headers
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"  Fetch error for {url}: {e}", file=sys.stderr)
        return None, {}


def resolve_slug(slug: str) -> tuple[str, str] | None:
    """
    Resolve a ClawHub slug to (author, skill_name) by trying split positions.
    """
    parts = slug.split("-")
    for i in range(1, len(parts)):
        author = "-".join(parts[:i])
        name = "-".join(parts[i:])
        url = f"{RAW_BASE}/{author}/{name}/SKILL.md"
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return author, name
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
    return None


def list_skill_directory(author: str, name: str) -> list[dict]:
    """
    Recursively list all files in a skill directory via GitHub API.
    Returns a flat list of {path, type, size, raw_url} dicts.
    """
    all_files = []

    def _walk(api_url: str, prefix: str = ""):
        data = github_api_get(api_url)
        if data is None:
            return
        for item in data:
            rel_path = f"{prefix}/{item['name']}" if prefix else item["name"]
            if item["type"] == "file":
                raw_url = f"{RAW_BASE}/{author}/{name}/{rel_path}"
                all_files.append(
                    {
                        "path": rel_path,
                        "type": "file",
                        "size": item.get("size", 0),
                        "raw_url": raw_url,
                    }
                )
            elif item["type"] == "dir":
                _walk(item["url"], rel_path)

    root_url = f"{GITHUB_API_BASE}/{author}/{name}"
    _walk(root_url)
    return all_files


def fetch_skill(author: str, name: str, output_dir: Path, delay: float = 0.3) -> dict:
    """
    Download entire skill directory to output_dir, including _meta.json.

    Returns a result dict containing:
    - meta: parsed _meta.json content (version, publishedAt, commit, history)
    - etag: ETag of SKILL.md
    - files: list of downloaded files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Listing {author}/{name} ...")
    files = list_skill_directory(author, name)

    if not files:
        return {
            "success": False,
            "error": "no files found or API error",
            "files": [],
            "meta": None,
        }

    result = {
        "success": True,
        "author": author,
        "skill_name": name,
        "etag": None,
        "meta": None,
        "has_original_readme": False,
        "files": [],
        "total_size": 0,
    }

    for f in files:
        # If upstream has a README.md, rename it to ORIGINAL_README.md
        # so it doesn't conflict with our generated Chinese README.md
        save_path = f["path"]
        if f["path"] == "README.md":
            save_path = "ORIGINAL_README.md"
            result["has_original_readme"] = True

        target_path = output_dir / save_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"  Fetching: {f['path']} ({f['size']} bytes)")
        content, headers = fetch_raw_file(f["raw_url"])

        if content is None:
            result["files"].append({"path": f["path"], "status": "failed"})
            time.sleep(delay)
            continue

        target_path.write_bytes(content)
        result["files"].append(
            {
                "path": save_path,
                "original_path": f["path"],
                "status": "ok",
                "size": len(content),
            }
        )
        result["total_size"] += len(content)

        # Capture ETag for SKILL.md
        if f["path"] == "SKILL.md" and headers.get("etag"):
            result["etag"] = headers["etag"]

        # Parse _meta.json
        if f["path"] == "_meta.json":
            try:
                result["meta"] = json.loads(content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        time.sleep(delay)

    downloaded = sum(1 for f in result["files"] if f["status"] == "ok")
    print(
        f"  Done: {downloaded}/{len(result['files'])} files, "
        f"{result['total_size']} bytes total"
    )

    if result["meta"]:
        m = result["meta"]
        ver = m.get("latest", {}).get("version", "?")
        history_count = len(m.get("history", []))
        print(f"  Meta: v{ver}, {history_count} prior versions")

    if result["has_original_readme"]:
        print(f"  Original README.md found → saved as ORIGINAL_README.md")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Fetch entire skill directory from GitHub"
    )
    parser.add_argument("--author", help="Skill author (GitHub username)")
    parser.add_argument("--name", help="Skill name")
    parser.add_argument("--slug", help="ClawHub slug (alternative to --author/--name)")
    parser.add_argument(
        "--output-dir", required=True, help="Local directory to save files"
    )
    parser.add_argument(
        "--delay", type=float, default=0.3, help="Delay between file fetches"
    )
    args = parser.parse_args()

    # Resolve author/name
    if args.slug and not (args.author and args.name):
        resolved = resolve_slug(args.slug)
        if resolved is None:
            print(f"Error: could not resolve slug '{args.slug}'", file=sys.stderr)
            sys.exit(1)
        author, name = resolved
    elif args.author and args.name:
        author, name = args.author, args.name
    else:
        parser.error("Provide either --slug or both --author and --name")
        sys.exit(1)

    result = fetch_skill(
        author=author,
        name=name,
        output_dir=Path(args.output_dir),
        delay=args.delay,
    )

    if not result["success"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    # Output as JSON for piping / subagent consumption
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
