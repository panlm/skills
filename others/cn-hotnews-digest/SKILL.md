---
name: cn-hotnews-digest
description: Use when generating a daily digest of Chinese news hot lists — real-time trending topics and newsflashes from 10 platforms (Weibo, Zhihu, Toutiao, 36Kr, Wallstreetcn, Cailianshe, ThePaper, IT之家, Hacker News, Jin10), grouped by platform, one linked bullet per topic. Triggers include "中文热点", "热搜简报", "cn news digest", "微博/知乎热榜", or a scheduled daily hot-list roundup run by an agent (e.g. openclaw).
---

# CN Hot-News Digest

## Overview

Produce a scannable digest of the **current** hot-search / newsflash lists from 10 Chinese platforms. A fetch script pulls each platform's top items (title + link) via `npx newsnow`; you (the agent) assemble them grouped by platform, and may add a one-line Chinese gloss where a topic is cryptic.

Core principle: **these are hot-search topics, not articles** — so the unit is a linked topic bullet, not a 3-5 sentence article summary. Faithfully list what's trending; don't fabricate detail the source doesn't have.

## Quick Reference

| File | Purpose |
|---|---|
| `fetch_cn_news.py [--limit 10] [--sources a,b]` | Fetch all 10 platforms (or a subset) → JSON `{fetched_at, platforms: {平台名: [{title,url}]}}`. |

Platforms: 今日头条热搜 · 微博热搜 · 知乎热榜 · 36氪快讯 · 华尔街见闻快讯 · 财联社电报 · 澎湃新闻 · IT之家 · Hacker News · 金十数据.

Dependency: **Node + npx** (newsnow auto-fetched by `npx -y`; needs network). Per-platform timeout is built in — a slow platform is skipped, not fatal.

## Procedure

1. **Fetch.** Run `python3 <skill>/fetch_cn_news.py 2>/dev/null`. Parse the JSON: `fetched_at`, `platforms` (ordered map of *平台名 → [{title, url}]*). A platform that failed/timed out is simply absent.

2. **Empty?** If `platforms` is empty, output `暂时拉不到中文热点(平台或网络异常)。` and still save the file (step 4). Stop.

3. **Assemble**, one `##` section per platform in the JSON's order, one bullet per topic. Title is the hyperlink — never print a bare URL. Keep the topic titles verbatim (they are Chinese already). Optionally add ` — {一句中文点评}` **only** when a title is cryptic and a short gloss genuinely helps a reader; otherwise leave the bullet as just the linked title. Do not pad every item.

   ```markdown
   # 中文热点简报 — {fetched_at date}

   _{总条目数} 条 · {平台数} 个平台_

   ## 微博热搜
   - [{topic title}]({url})
   - [{topic title}]({url}) — {可选一句中文点评}

   ## 知乎热榜
   - [{topic title}]({url})
   ```

4. **Save and print.** Write to `/tmp/cn-hotnews-digest-{today}.md` **and** print it as the response.

## Common Mistakes

- **Writing 3-5 sentence summaries per item.** These are hot-search topics — a bullet is a linked title, plus at most one gloss line. 100 mini-essays is wrong.
- **Reordering or merging platforms.** Keep the script's platform order and sections.
- **Dropping the link or rewriting the title.** Titles are verbatim Chinese; wrap each as `[title](url)`.
- **Failing loud on a missing platform.** A timed-out platform is expected — just omit it; don't abort the digest.
