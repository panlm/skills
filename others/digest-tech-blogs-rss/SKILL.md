---
name: digest-tech-blogs-rss
description: Use when generating a daily digest of top tech blogs — the ~92 engineering/AI blog RSS feeds from the "HN Popularity Contest" OPML (compiled by Evan Schwartz, popularized by Karpathy's "return to RSS"), pulling the last 24h of posts, grouped by source blog, one hyperlinked bullet per post with a short Chinese summary. Triggers include "tech blog digest", "技术博客精选", "Karpathy blogs", "RSS daily digest", or a scheduled daily tech-blog roundup run by an agent (e.g. openclaw).
---

# Tech Blogs RSS Digest

## Overview

Produce a categorized digest of posts published in the **last 24 hours** across ~92 hand-picked technical/AI blogs — the "HN Popularity Contest 2025" list compiled by Evan Schwartz and popularized by Karpathy's "return to RSS" (simonwillison, antirez, rachelbythebay, gwern, dwarkesh, krebsonsecurity, …). A zero-dependency Node fetcher pulls and parses every feed concurrently; you (the agent) write each post's 3-5 sentence Chinese summary from the article.

Core principle: **the fetch is scripted; the summaries are yours, in Chinese.** Titles, blog names, and links stay in their original language.

## Quick Reference

All files live in this skill's directory (`<skill>/`).

| File | Purpose |
|---|---|
| `fetch-rss.mjs` | Node 18+ zero-dep fetcher. `node fetch-rss.mjs --hours 24 --sources <skill>/sources.json` → JSON array of articles, newest first. |
| `sources.json` | The ~92 feeds (`name`, `xmlUrl`, `htmlUrl`). Canonical source = Evan Schwartz's "HN Popularity Contest" OPML ([gist](https://gist.github.com/emschwartz/e6d2bf860ccc367fe37ff953ba6de66b)); re-import if a newer (e.g. 2026) edition appears. Edit to add/remove blogs. |
| `article_text.py` | `article_text.py <url>` → clean body text (no HTML). Exit 2 = fetch failed. |

Dependency: **Node.js 18+** (`node -v`). No npm install needed.

## Procedure

1. **Fetch.** Run `node <skill>/fetch-rss.mjs --hours 24 --sources <skill>/sources.json 2>/dev/null`. Output is a JSON array; each item has `title`, `link`, `summary` (≤500 chars from the feed), `date` (ISO), `source` (blog name), `sourceUrl`. Already sorted newest-first. Some feeds fail silently — that's expected, the array still returns.

2. **Empty?** If the array is empty, output `过去 24 小时这些技术博客没有新文章。` and still save the file (step 5). Stop.

3. **Summarize each post — write the summary in Chinese (中文).** For each article, base the summary on its `summary` field. If that field is thin (< ~200 chars) or unclear, run `python3 <skill>/article_text.py "<link>"` and read the body. Write **3-5 句中文** per post:
   - 这篇讲什么、核心观点或结论是什么。
   - 关键技术/数据/论据(专有名词、产品名保留英文原名)。
   - 对读者的价值:值不值得点开、适合谁。
   - 中立、有信息量,不要"作者认为…"这类空话,不要编造。
   - `article_text.py` 失败或正文太薄时,就用 feed 的 `summary` 概括,并在末尾加 ` _(from feed summary)_`。

4. **Assemble**, grouped by `source` blog (a blog with posts becomes a `##` section; posts newest-first inside). Title is the hyperlink — never print a bare URL.

   ```markdown
   # Tech Blogs Digest — {date} (last 24h)

   _{N} posts from {M} blogs_

   ## {source blog name}
   - **[{title}]({link})** — {3-5 句中文总结}
     _{date}_
   ```

5. **Save and print.** Write to `/tmp/tech-blogs-digest-{today}.md` **and** print it as the response.

## Common Mistakes

- **Fake topic categories.** `sources.json` has no topic taxonomy — group by `source` blog, don't invent "AI / Security / Systems" buckets.
- **Summarizing only from the title.** Use the `summary` field; fetch the body when it's thin. A title is not a summary.
- **Dropping the hyperlink.** Every title must be `[title](link)`.
- **Translating titles/blog names.** Only the summary is Chinese; keep titles and source names original.
- **Widening the window silently.** Default is 24h. If the user wants more, pass `--hours N` and say so in the header.
