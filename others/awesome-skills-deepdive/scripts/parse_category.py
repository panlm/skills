#!/usr/bin/env python3
"""
Parse awesome-openclaw-skills category files and produce a JSON manifest.

Usage:
    python parse_category.py --categories-dir /path/to/categories --output /tmp/skill-manifest.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_category_file(filepath: Path) -> dict:
    """Parse a single category .md file and extract skill entries."""
    category_name = filepath.stem.replace("-", " ").title()
    # Restore common casing like "& Services", "& Cloud", etc.
    # The actual heading in the file is more accurate — try to extract it
    content = filepath.read_text(encoding="utf-8")

    # Try to get the real category name from the H1 heading
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        category_name = h1_match.group(1).strip()

    # Parse skill entries: - [name](url) - description
    skills = []
    pattern = re.compile(
        r"^-\s+\[([^\]]+)\]\((https://clawskills\.sh/skills/([^\)]+))\)\s*-\s*(.+)$",
        re.MULTILINE,
    )
    for match in pattern.finditer(content):
        name = match.group(1).strip()
        url = match.group(2).strip()
        slug = match.group(3).strip()
        description = match.group(4).strip()
        skills.append(
            {
                "name": name,
                "url": url,
                "slug": slug,
                "description": description,
            }
        )

    # Also handle GitHub-style links (some entries use github.com directly)
    gh_pattern = re.compile(
        r"^-\s+\[([^\]]+)\]\((https://github\.com/[^\)]+)\)\s*-\s*(.+)$",
        re.MULTILINE,
    )
    for match in gh_pattern.finditer(content):
        name = match.group(1).strip()
        url = match.group(2).strip()
        description = match.group(3).strip()
        # Extract slug from GitHub URL
        gh_match = re.search(r"/skills/([^/]+)/([^/]+)", url)
        if gh_match:
            slug = f"{gh_match.group(1)}-{gh_match.group(2)}"
        else:
            slug = name
        skills.append(
            {
                "name": name,
                "url": url,
                "slug": slug,
                "description": description,
                "source": "github",
            }
        )

    return {
        "category": category_name,
        "file": filepath.name,
        "count": len(skills),
        "skills": skills,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse awesome-openclaw-skills categories"
    )
    parser.add_argument(
        "--categories-dir", required=True, help="Path to categories/ directory"
    )
    parser.add_argument("--output", required=True, help="Output JSON manifest path")
    args = parser.parse_args()

    categories_dir = Path(args.categories_dir)
    if not categories_dir.is_dir():
        print(f"Error: {categories_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    manifest = {"categories": [], "total_skills": 0}

    for md_file in sorted(categories_dir.glob("*.md")):
        category_data = parse_category_file(md_file)
        manifest["categories"].append(category_data)
        manifest["total_skills"] += category_data["count"]
        print(f"  [{category_data['count']:>4}] {category_data['category']}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"\nTotal: {manifest['total_skills']} skills across {len(manifest['categories'])} categories"
    )
    print(f"Manifest saved to: {output_path}")


if __name__ == "__main__":
    main()
