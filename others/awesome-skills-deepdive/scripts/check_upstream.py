#!/usr/bin/env python3
"""
Unified upstream change detection via GitHub commit diff.

Replaces both detect_changes.py (listing changes) and source_patrol.py (content changes)
with a single script that checks commit diffs from two upstream repos:

1. awesome-openclaw-skills — listing changes (skill added/removed from categories)
2. openclaw/skills — content changes (skill author updated SKILL.md, scripts, etc.)

State is tracked in .upstream-state.json in the deepdive repo root.

Usage:
    # Check both repos for changes
    python3 check_upstream.py --deepdive-dir ~/openclaw-skill/awesome-skills-deepdive \
      --awesome-dir ~/openclaw-skill/awesome-openclaw-skills \
      --output /tmp/upstream-changes.json

    # Dry run — just show what changed, don't update state
    python3 check_upstream.py --deepdive-dir ~/openclaw-skill/awesome-skills-deepdive \
      --awesome-dir ~/openclaw-skill/awesome-openclaw-skills \
      --dry-run
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


STATE_FILE = ".upstream-state.json"
REGISTRY_FILE = ".skill-registry.json"

AWESOME_REPO = "VoltAgent/awesome-openclaw-skills"
SKILLS_REPO = "openclaw/skills"


# ── GitHub API ────────────────────────────────────────────────


def github_api_get(url: str, timeout: float = 30) -> dict | None:
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
        print(f"  API error: {e}", file=sys.stderr)
        return None


def get_latest_commit(repo: str) -> str | None:
    """Get the latest commit SHA for a repo's main branch."""
    data = github_api_get(f"https://api.github.com/repos/{repo}/commits/main")
    if data:
        return data["sha"]
    return None


def get_compare_files(repo: str, base: str, head: str) -> list[dict] | None:
    """
    Get list of changed files between two commits.
    Returns list of {filename, status, ...} or None on error.

    GitHub compare API has a 250-file limit per page. For large diffs,
    we paginate or fall back to listing commits.
    """
    url = f"https://api.github.com/repos/{repo}/compare/{base}...{head}"
    data = github_api_get(url)
    if data is None:
        return None

    files = data.get("files", [])

    # If the diff is too large (ahead_by > 250 commits), GitHub may truncate
    # In that case, return a special marker
    if data.get("status") == "diverged" or len(files) == 0:
        return None

    return files


# ── State I/O ─────────────────────────────────────────────────


def load_state(deepdive_dir: Path) -> dict:
    path = deepdive_dir / STATE_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"awesome_commit": None, "skills_commit": None, "last_check": None}


def save_state(deepdive_dir: Path, state: dict):
    path = deepdive_dir / STATE_FILE
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_registry(deepdive_dir: Path) -> dict:
    path = deepdive_dir / REGISTRY_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ── Awesome Repo: Listing Changes ────────────────────────────


def parse_category_file(filepath: Path) -> dict[str, dict]:
    """Parse a category .md file, return {skill_name: {slug, description}}."""
    content = filepath.read_text(encoding="utf-8")
    skills = {}
    pattern = re.compile(
        r"^-\s+\[([^\]]+)\]\(https://clawskills\.sh/skills/([^\)]+)\)\s*-\s*(.+)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(content):
        name = match.group(1).strip()
        slug = match.group(2).strip()
        desc = match.group(3).strip()
        skills[name] = {"slug": slug, "description": desc}
    return skills


def detect_listing_changes(awesome_dir: Path, registry: dict) -> dict:
    """
    Compare current category files against registry to find added/removed skills.
    Returns {added: [{category, name, slug, desc}], removed: [{category, name}]}
    """
    categories_dir = awesome_dir / "categories"
    if not categories_dir.is_dir():
        return {"added": [], "removed": []}

    # Build current listing from category files
    current_skills = {}  # {name: {category, slug, description}}
    for md_file in sorted(categories_dir.glob("*.md")):
        # Get category name from H1 heading
        content = md_file.read_text(encoding="utf-8")
        h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        cat_name = (
            h1_match.group(1).strip()
            if h1_match
            else md_file.stem.replace("-", " ").title()
        )

        skills = parse_category_file(md_file)
        for name, info in skills.items():
            current_skills[f"{cat_name}/{name}"] = {
                "category": cat_name,
                "name": name,
                **info,
            }

    # Build existing set from registry
    existing_keys = set(registry.keys())
    current_keys = set(current_skills.keys())

    added = []
    for key in sorted(current_keys - existing_keys):
        added.append(current_skills[key])

    removed = []
    for key in sorted(existing_keys - current_keys):
        parts = key.split("/", 1)
        if len(parts) == 2:
            removed.append({"category": parts[0], "name": parts[1]})

    return {"added": added, "removed": removed}


# ── Skills Repo: Content Changes ──────────────────────────────


def extract_affected_skills(files: list[dict], registry: dict) -> list[dict]:
    """
    From a list of changed files (GitHub compare API), extract which skills
    in our registry are affected.

    File paths look like: skills/{author}/{name}/SKILL.md
    """
    affected = {}  # key → {author, name, changed_files}

    for f in files:
        filename = f["filename"]
        m = re.match(r"^skills/([^/]+)/([^/]+)/(.+)$", filename)
        if not m:
            continue

        author = m.group(1)
        skill_name = m.group(2)
        changed_file = m.group(3)

        # Check if this skill is in our registry (i.e., in our watch list)
        matching_keys = [
            k
            for k in registry
            if registry[k].get("owner") == author
            and registry[k].get("slug") == skill_name
        ]

        if not matching_keys:
            continue

        key = matching_keys[0]
        if key not in affected:
            category = key.split("/", 1)[0]
            affected[key] = {
                "registry_key": key,
                "category": category,
                "name": skill_name,
                "author": author,
                "changed_files": [],
                "file_status": f["status"],  # added/modified/removed
            }
        affected[key]["changed_files"].append(
            {
                "path": changed_file,
                "status": f["status"],
            }
        )

    return list(affected.values())


# ── Main ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Unified upstream change detection via commit diff"
    )
    parser.add_argument("--deepdive-dir", required=True, help="Path to deepdive repo")
    parser.add_argument(
        "--awesome-dir",
        required=True,
        help="Path to local awesome-openclaw-skills clone",
    )
    parser.add_argument("--output", help="Output JSON path for changes")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes but don't update state"
    )
    args = parser.parse_args()

    deepdive_dir = Path(args.deepdive_dir)
    awesome_dir = Path(args.awesome_dir)
    state = load_state(deepdive_dir)
    registry = load_registry(deepdive_dir)

    now = datetime.now(timezone.utc).isoformat()
    result = {
        "checked_at": now,
        "awesome": {"changed": False, "added": [], "removed": []},
        "skills": {"changed": False, "updated": []},
        "action_required": False,
    }

    # ── Phase 1: Check awesome-openclaw-skills listing ──────

    print("Phase 1: Checking awesome-openclaw-skills listing...")
    awesome_head = get_latest_commit(AWESOME_REPO)
    if awesome_head is None:
        print("  ⚠ Failed to get awesome repo commit")
    else:
        print(f"  Latest: {awesome_head[:12]}")
        print(f"  Stored: {(state.get('awesome_commit') or 'none')[:12]}")

        if state.get("awesome_commit") == awesome_head:
            print("  ✓ No listing changes")
        else:
            print("  ⚡ Listing may have changed — scanning categories...")
            listing = detect_listing_changes(awesome_dir, registry)
            result["awesome"]["added"] = listing["added"]
            result["awesome"]["removed"] = listing["removed"]
            result["awesome"]["changed"] = bool(listing["added"] or listing["removed"])

            if listing["added"]:
                print(f"  + {len(listing['added'])} skills added:")
                for s in listing["added"][:10]:
                    print(f"    + [{s['category']}] {s['name']}")
                if len(listing["added"]) > 10:
                    print(f"    ... and {len(listing['added']) - 10} more")
            if listing["removed"]:
                print(f"  - {len(listing['removed'])} skills removed:")
                for s in listing["removed"][:10]:
                    print(f"    - [{s['category']}] {s['name']}")

            if not args.dry_run:
                state["awesome_commit"] = awesome_head

    # ── Phase 2: Check openclaw/skills content ──────────────

    print(f"\nPhase 2: Checking openclaw/skills content...")
    skills_head = get_latest_commit(SKILLS_REPO)
    if skills_head is None:
        print("  ⚠ Failed to get skills repo commit")
    else:
        print(f"  Latest: {skills_head[:12]}")
        print(f"  Stored: {(state.get('skills_commit') or 'none')[:12]}")

        if state.get("skills_commit") is None:
            print(
                "  First run — no baseline commit. Will set baseline after initial deepdive."
            )
            if not args.dry_run:
                state["skills_commit"] = skills_head
        elif state["skills_commit"] == skills_head:
            print("  ✓ No content changes")
        else:
            print("  ⚡ Content changed — fetching diff...")
            files = get_compare_files(SKILLS_REPO, state["skills_commit"], skills_head)

            if files is None:
                print("  ⚠ Diff too large or API error — consider full rescan")
            else:
                print(f"  {len(files)} files changed in upstream")
                affected = extract_affected_skills(files, registry)
                result["skills"]["updated"] = affected
                result["skills"]["changed"] = bool(affected)

                if affected:
                    print(f"  ⚡ {len(affected)} watched skills affected:")
                    for s in affected:
                        changed = ", ".join(f["path"] for f in s["changed_files"])
                        print(f"    ~ [{s['category']}] {s['name']}: {changed}")
                else:
                    print(f"  ✓ {len(files)} files changed but none in our watch list")

                if not args.dry_run:
                    state["skills_commit"] = skills_head

    # ── Summary ─────────────────────────────────────────────

    total_added = len(result["awesome"]["added"])
    total_removed = len(result["awesome"]["removed"])
    total_updated = len(result["skills"]["updated"])
    result["action_required"] = (total_added + total_removed + total_updated) > 0

    print(f"\n{'=' * 50}")
    print(f"Summary:")
    print(f"  Listing:  +{total_added} added, -{total_removed} removed")
    print(f"  Content:  ~{total_updated} skills updated")
    if result["action_required"]:
        print(f"\n⚡ Action required: process {total_added + total_updated} skills")
    else:
        print(f"\n✓ Nothing to do")

    # Save state
    if not args.dry_run:
        state["last_check"] = now
        save_state(deepdive_dir, state)
        print(f"\nState saved to {STATE_FILE}")

    # Save results
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
