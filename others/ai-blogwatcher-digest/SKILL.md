---
name: ai-blogwatcher-digest
description: Use when generating a digest of newly published AI/tech blog articles tracked by blogwatcher — the unread posts from the last few days across subscribed blogs, each read in full and given a detailed Chinese summary, grouped by blog. Triggers include "AI博客精选", "blogwatcher digest", "每日AI博客", "unread blog articles", or a scheduled AI-blog roundup run by an agent (e.g. openclaw). Requires blogwatcher-cli.
---

# AI Blogwatcher Digest

## Overview

Summarize the **unread** articles that `blogwatcher-cli` has tracked across subscribed blogs in the last few days, reading each article in full and writing a detailed Chinese summary. Unlike the RSS/hot-list skills, this source has per-article read state, so a run reports only genuinely new posts.

Core principle: **read the article, write a substantial Chinese summary** — enough that the reader gets ~80% of the article's value without opening it. Marking articles read is the delivery step's job, not this skill's.

> ⚠️ **Dependency / portability:** needs `blogwatcher-cli` on PATH **and** its subscription database. It does NOT run on a machine without both. Verify on the openclaw host, not a fresh laptop.
>
> - **Tool:** [`JulienTant/blogwatcher-cli`](https://github.com/JulienTant/blogwatcher-cli) (Go, MIT; a fork of `Hyaxia/blogwatcher`). Not on npm/PyPI.
> - **Install:** `go install github.com/JulienTant/blogwatcher-cli/cmd/blogwatcher-cli@latest`, or Docker `ghcr.io/julientant/blogwatcher-cli`, or a prebuilt binary from GitHub Releases.
> - **Subscription DB:** subscriptions + per-article read/unread state live only in a local SQLite file at `~/.blogwatcher-cli/blogwatcher-cli.db` (override with `--db` or `$BLOGWATCHER_DB`). To keep history, copy that `.db` from the original host to the same path on the new one. To take only the subscriptions (losing read state + article ids), re-import via `blogwatcher-cli import <feeds.opml>`.

## Quick Reference

| File | Purpose |
|---|---|
| `scan_unread.py [--days 3] [--unsafe-client]` | Runs `blogwatcher-cli scan` + `articles --all`, prints unread article blocks in the window + a final `IDS_TO_MARK_READ:` line. |

Pass `--unsafe-client` **only** if the host routes outbound traffic through a loopback proxy (e.g. `HTTPS_PROXY=http://localhost:PORT`): blogwatcher's SSRF guard refuses to connect to a `127.0.0.1` proxy otherwise, and every feed fetch fails. Hosts with a normal (non-loopback) egress path must NOT pass it.
| `article_text.py <url>` | Fetch one article → clean body text (no HTML). Exit 2 = fetch failed. |

## Procedure

1. **Scan.** Run `python3 <skill>/scan_unread.py --days 3`. It prints unread article blocks (each starts with `[id]`, and carries a title, date, and link) and, if any, a trailing `IDS_TO_MARK_READ: <id> <id> …` line. If it errors that `blogwatcher-cli` is missing, stop and report — the host isn't set up.

2. **Empty?** If it prints `No new unread articles`, output `今日无新文章更新。` and still save the file (step 5). Stop.

3. **Read + summarize each — in Chinese (中文).** Cap at the 10 most important if there are more. For each unread article, run `python3 <skill>/article_text.py "<link>"` and read the body. If it can't be fetched, mark it `无法访问` and skip. Write per article:
   - **核心观点**:一句话提炼最关键的结论或发现。
   - **详细摘要**:6-10 句展开——解决什么问题/讨论什么、核心论点与论据、关键数据/实验结果/技术细节、方法或实现、作者结论与建议。
   - **关键词**:3-5 个标签。
   - 专有名词/产品名保留英文原名;有信息量,不空泛,不编造。

4. **Assemble**, grouped by blog (`##` per blog). Title is the hyperlink.

   ```markdown
   # AI 博客精选 — {today}

   _{N} 篇新文章_

   ## {blog name}
   - **[{title}]({link})**
     - 核心观点：…
     - 详细摘要：…（6-10 句）
     - 关键词：…
   ```

   At the end, include an HTML comment with the ids so the delivery step can mark them read after real delivery:
   `<!-- IDS_TO_MARK_READ: 1982 2003 -->`

5. **Save and print.** Write to `/tmp/ai-blogwatcher-digest-{today}.md` **and** print it.

## Common Mistakes

- **Marking articles read here.** Don't. `blogwatcher-cli read <id>` runs in the delivery step, only after the summary is actually delivered — otherwise a failed delivery silently drops the article. This skill only *emits* the ids.
- **Thin summaries.** The bar is 6-10 substantive sentences per article, not a one-liner. Read the body.
- **Batch-marking / multiple ids per call.** `blogwatcher-cli read` takes ONE id per call (delivery-side concern, but noted).
- **Summarizing read articles.** `scan_unread.py` already filters to `[new]` in-window; don't re-add `[read]` ones.
