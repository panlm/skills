#!/usr/bin/env python3
"""Fetch an AWS blog post URL and print its readable body text (no HTML).

Keeps summarization input bounded: prefers <article>/<main>, strips script/
style/nav, collapses whitespace, trims to a char budget. Used by the
digest skills so Claude summarizes clean text, not raw HTML.

Usage: article_text.py <url> [--max-chars 8000]
Prints extracted text to stdout; exits 0 even on partial extraction, exits 2
(empty stdout) only when the fetch itself fails so the caller can fall back
to the API excerpt.
"""
import argparse
import re
import subprocess
import sys
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "svg", "form"}


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.in_main = False
        self.main_depth = 0
        self.chunks = []
        self.main_chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        if tag in ("article", "main"):
            self.in_main = True
            self.main_depth += 1

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag in ("article", "main") and self.main_depth:
            self.main_depth -= 1
            if self.main_depth == 0:
                self.in_main = False

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = data.strip()
        if not text:
            return
        self.chunks.append(text)
        if self.in_main:
            self.main_chunks.append(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-chars", type=int, default=8000)
    args = ap.parse_args()

    try:
        html = subprocess.run(
            ["curl", "-L", "--connect-timeout", "10", "--max-time", "45", "-sS",
             "-A", "Mozilla/5.0 (blog-digest)", args.url],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        sys.exit(2)
    if not html.strip():
        sys.exit(2)

    p = Extractor()
    try:
        p.feed(html)
    except Exception:
        pass
    parts = p.main_chunks if len(" ".join(p.main_chunks)) > 400 else p.chunks
    text = re.sub(r"\s+\n", "\n", " ".join(parts))
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if not text:
        sys.exit(2)
    print(text[:args.max_chars])


if __name__ == "__main__":
    main()
