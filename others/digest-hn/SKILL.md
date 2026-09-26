---
name: digest-hn
description: Use when the user wants a Hacker News top-N digest with a short summary per story — "HN top 10", "HN 热榜摘要", "summarize Hacker News", "今天 HN 有什么". Fetches the HN hottest list via the newsnow MCP server, then reads each linked article and writes a 3-5 sentence Chinese summary, streaming one story at a time.
---

# Hacker News Digest (streaming)

## Overview

Produce a Hacker News top-N digest where each story gets a 3-5 sentence Chinese summary based on its actual article. The list comes from the **newsnow MCP** server; the summaries are yours.

Core principle: **process one story at a time and emit its summary before fetching the next** — so the user sees results stream in, not a batch dumped at the end. Keep the list in newsnow's order (HN front-page hotness); do not re-sort.

## Quick Reference

| Piece | Use |
|---|---|
| `mcp__newsnow__get_hottest_latest_news` | MCP tool. Call `id="hackernews", count=N` → markdown list of `[title](https://news.ycombinator.com/item?id=<id>)` in HN front-page order. |
| `hn_article.py <id\|url>` | Resolve ONE HN item to its real article (via HN Firebase API) and print title/score/url/body. Handles self-posts (Ask/Show HN) and blocked pages. |

Prereq: the `newsnow` MCP server is configured (points at a NewsNow instance). If the tool isn't available, say so — don't fall back to scraping silently.

## Procedure

1. **Get the list.** Call `mcp__newsnow__get_hottest_latest_news` with `id="hackernews"` and `count=N` (default 10). This is HN front-page order — **keep it as-is, do not re-sort by points.**

2. **Then loop ONE story at a time — this is the whole point.** For each item in order, do all of a–c before touching the next item:
   - **a. Fetch its article:** extract the HN id from the item URL, run `python3 <skill>/hn_article.py <id>`, read the returned body.
   - **b. Summarize in Chinese:** write **3-5 句中文** — 这篇讲什么、核心结论/亮点、对读者的价值。专有名词/产品名保留英文。中立、有信息量、不编造。If the helper prints a `NOTE:` (blocked or no body), summarize from the title and append ` _(未取到正文)_`.
   - **c. Emit that one bullet now**, then move to the next item:
     ```markdown
     ## {n}. [{title}](https://news.ycombinator.com/item?id=<id>) · {score}p
     {3-5 句中文}
     ```

   **Do NOT fetch all N articles first and dump the summaries together.** Fetch → summarize → output, per story, so each lands as soon as it's ready. (Your text streams live between tool calls; batching the fetches is what makes the user wait.)

3. **No file.** Stream to the conversation only — do not save to /tmp (unlike the other digest skills). Start with a one-line header noting the order is HN front-page hotness (time-decayed), not a points ranking.

## Common Mistakes

- **Batch-fetching then dumping.** Fetching all articles in one script and writing every summary at the end defeats the skill. One story per fetch→summarize→emit cycle.
- **Re-sorting by points.** Keep newsnow's front-page order. Points (`extra.info` / `score`) are shown, not the sort key — HN front-page rank is time-decayed, so a high-point old story sits lower on purpose.
- **Summarizing the HN discussion page.** The newsnow URL is the HN comments page; `hn_article.py` resolves the real external article — summarize that, not the thread.
- **Writing a summary from the title alone** when the body was available. Read the fetched body; use the title only when the helper reports the page was blocked/empty.
- **Guessing when newsnow is down.** If the MCP tool errors, report it; don't silently scrape HN yourself.
