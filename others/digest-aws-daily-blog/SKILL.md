---
name: digest-aws-daily-blog
description: Use when generating a daily digest/roundup of AWS blog posts — the previous UTC day's full published blog list across all AWS channels, grouped by category, one hyperlinked bullet per post with a short summary. Triggers include "AWS blog digest", "daily AWS blogs", "yesterday's AWS blog posts", or a scheduled daily AWS blog roundup run by an agent (e.g. openclaw).
---

# AWS Daily Blog Digest

## Overview

Produce a categorized digest of every AWS blog post published during **one UTC day** (default: the previous UTC day). Data comes from the AWS content-directory JSON API that powers `aws.amazon.com/blogs/` — one endpoint returns all channels, sorted by publish date, no auth, no JS rendering. Two helper scripts handle the deterministic parts; you (the agent) write each post's 3-5 sentence summary by reading the actual article.

Core principle: **the fetch is scripted and exact; the summaries are yours.** The summary is what makes this worth more than an RSS reader — read the body, don't parrot the marketing excerpt.

## Quick Reference

Both scripts live in this skill's directory (`<skill>/`).

| Script | Purpose |
|---|---|
| `fetch_blogs.py [--date YYYY-MM-DD] [--locale en_US]` | List posts for one UTC day, grouped by category, as JSON. Default date = previous UTC day. |
| `article_text.py <url> [--max-chars 8000]` | Fetch one post and print clean body text (no HTML). Exit 2 = fetch failed → fall back to the API excerpt. |

Defaults: English only (`en_US`); pass `--locale ""` for all languages.

## Procedure

1. **Fetch the list.** Run `python3 <skill>/fetch_blogs.py` (add `--date` only if the user names a specific day). Parse the JSON: `date`, `count`, `categories` (an ordered map of *Category Name → [posts]*, each post has `title`, `link`, `authors`, `excerpt`, `created`).

2. **Empty day?** If `count == 0`, the output is just: `No AWS blog posts were published on {date} (UTC).` Still save the file (step 5). Stop.

3. **Summarize each post — write the summary in Chinese (中文).** For every post, run `python3 <skill>/article_text.py "<link>"` and read the returned body. Write **3-5 句中文** that let a reader decide in seconds whether to open it. Only the summary text is Chinese — titles, category names, author names, service names, and all structure stay English.
   - 讲清这篇到底在说什么、发布或更新了什么。
   - 涉及的具体 AWS 服务 / 功能（服务名保留英文原名，如 Amazon S3、AWS Fargate）。
   - 面向谁、解决什么具体问题。
   - 中立、技术、信息密度高。不要"本文介绍…"这类套话，不要营销形容词（powerful / seamless），不要编造事实。
   - If `article_text.py` exits non-zero or returns thin text, summarize from the API `excerpt` and append ` _(from excerpt)_` so the gap is visible.

4. **Assemble the digest** in category order from the JSON (posts within a category are already oldest→newest). One bullet per post, title hyperlinked to the original:

   ```markdown
   # AWS Blog Digest — {date} (UTC)

   _{count} posts across {N} categories_

   ## {Category Name}
   - **[{title}]({link})** — {3-5 句中文总结}
     _{authors}_
   ```

   The bold title **is** the hyperlink (`[title](link)`) — never print the raw URL as visible text.

5. **Save and print.** Write the markdown to `/tmp/aws-blog-digest-{date}.md` **and** print it as the response. The saved file is the durable artifact; the printed copy is what the daily runner captures.

## Common Mistakes

- **Summarizing from the excerpt by default.** The API `excerpt` is one marketing sentence. Always fetch the body first; excerpt is the fallback only.
- **Wrong day / timezone.** The window is a full UTC calendar day, computed by the script from `createdDate` (UTC). Don't second-guess it with local time.
- **Dropping the hyperlink.** Every title must link to its `link`. That's the point of a bullet.
- **Reformatting categories.** Use the category names and order the script emits; don't re-bucket posts yourself.
- **Padding to hit 5 sentences.** 3 tight sentences beat 5 padded ones. Density over length.
