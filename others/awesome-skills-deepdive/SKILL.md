---
name: awesome-skills-deepdive
description: >
  Deep dive analysis of the awesome-openclaw-skills repository. Forks and clones the upstream
  repo, then systematically fetches every skill's SKILL.md source from GitHub, runs a 10-category
  security audit on each, and generates a Chinese README summary — all organized by category in a
  dedicated deepdive repo that syncs to GitHub. Dispatches parallel subagents per category for speed.
  Use when the user wants to: (1) analyze or audit skills from the awesome-openclaw-skills repo,
  (2) deep dive into a specific category of community skills, (3) fetch and review SKILL.md source
  for any ClawHub skill, (4) run security checks on community skills, (5) build a Chinese knowledge
  base of community skills. Triggers on keywords like "awesome skills", "deepdive skills",
  "audit community skills", "分析社区 skill", "审查 skill 安全性", "awesome openclaw".
---

# Awesome OpenClaw Skills — Deep Dive Analyzer

Systematically analyze the awesome-openclaw-skills repository: fork, fetch every skill's source,
run security audits, and generate Chinese README summaries organized by category.

## Prerequisites

- **GitHub CLI** (`gh`) — authenticated with `panlm` account
- **Git** — configured with push access to `panlm` GitHub repos
- **Python 3** — any `python3` on PATH (all scripts use stdlib only, no third-party packages)
- **Internet access** — to fetch SKILL.md files from `raw.githubusercontent.com`

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GITHUB_USER` | `panlm` | GitHub username for fork and deepdive repo |
| `UPSTREAM_REPO` | `VoltAgent/awesome-clawdbot-skills` | Upstream awesome skills repo |
| `LOCAL_BASE` | `~/openclaw-skill` | Local working directory |
| `UPSTREAM_LOCAL` | `${LOCAL_BASE}/awesome-openclaw-skills` | Local clone of the forked upstream repo |
| `DEEPDIVE_REPO` | `awesome-skills-deepdive` | Name of the deepdive output repo |
| `DEEPDIVE_LOCAL` | `${LOCAL_BASE}/awesome-skills-deepdive` | Local clone of the deepdive repo |

## Workflow

### Step 1: Setup Repos (Run Once)

Fork the upstream repo and create the deepdive repo. Skip if already done.

```bash
# 1a. Fork upstream to panlm account (idempotent)
gh repo fork ${UPSTREAM_REPO} --clone=false --remote=false

# 1b. Clone the fork locally
cd ${LOCAL_BASE}
if [ ! -d awesome-openclaw-skills/.git ]; then
  gh repo clone ${GITHUB_USER}/awesome-openclaw-skills
fi

# 1c. Create deepdive repo if it doesn't exist
gh repo create ${GITHUB_USER}/${DEEPDIVE_REPO} --public --description "Deep dive analysis of awesome-openclaw-skills" || true

# 1d. Clone deepdive repo locally
if [ ! -d ${DEEPDIVE_REPO}/.git ]; then
  gh repo clone ${GITHUB_USER}/${DEEPDIVE_REPO}
  cd ${DEEPDIVE_REPO}
  echo "# Awesome OpenClaw Skills — Deep Dive" > README.md
  git add README.md && git commit -m "init" && git push
fi
```

### Step 2: Sync Upstream

Pull latest changes from the upstream repo.

```bash
cd ${UPSTREAM_LOCAL}
git remote add upstream https://github.com/${UPSTREAM_REPO}.git 2>/dev/null || true
git fetch upstream
git merge upstream/main --no-edit
git push origin main
```

### Step 3: Parse Categories

Read the `categories/` directory to get the list of all category files. Each `.md` file
is one category. Parse each file to extract the skill list.

**Category file format** (each line is a skill entry):

```
- [skill-name](https://clawskills.sh/skills/{slug}) - Description text.
```

**Slug to GitHub path mapping:**

The slug format is `{author}-{skill-name}`. However, the `-` delimiter is ambiguous
(both author and skill-name can contain hyphens). Use this resolution strategy:

1. Fetch `https://clawskills.sh/skills/{slug}` page
2. Look for the "View on GitHub" link which contains the exact path:
   `https://github.com/openclaw/skills/tree/main/skills/{author}/{skill-name}`
3. Extract `{author}` and `{skill-name}` from that URL
4. Construct raw SKILL.md URL:
   `https://raw.githubusercontent.com/openclaw/skills/main/skills/{author}/{skill-name}/SKILL.md`

**Fallback strategy** (if ClawSkills page is unavailable):
- Split slug on first `-`: `{first-segment}` = author guess, rest = skill-name guess
- Try fetching the raw SKILL.md URL
- If 404, try splitting on second `-`, third `-`, etc.

Run `scripts/parse_category.py` to parse all categories:

```bash
python3 scripts/parse_category.py \
  --categories-dir ${UPSTREAM_LOCAL}/categories \
  --output /tmp/skill-manifest.json
```

Output: a JSON manifest mapping category → list of skills with their slugs.

### Step 4: Dispatch Subagents per Category

For each category, dispatch a subagent (via Task tool with `subagent_type: "general"`)
to process all skills in that category. Run 5-6 categories in parallel per batch.

**Each subagent receives these instructions:**

```
Process category: "{category_name}"
Skills to process: [list of {slug, name, description} objects]

For each skill:
1. Fetch the ClawHub page at https://clawskills.sh/skills/{slug} using WebFetch
2. From the page content, extract:
   a. The GitHub URL (pattern: https://github.com/openclaw/skills/tree/main/skills/{author}/{skill-name})
   b. The VirusTotal security status ("Benign" or "Suspicious")
   c. The OpenClaw security status ("Benign" or "Suspicious")
3. Fetch the ENTIRE skill directory (not just SKILL.md) using scripts/fetch_skill.py:
   python3 scripts/fetch_skill.py \
     --author {author} --name {skill-name} \
     --output-dir ${DEEPDIVE_LOCAL}/{category_name}/{skill-name}
   This downloads SKILL.md, _meta.json, and all bundled resources (references/,
   scripts/, assets/, etc.) via the GitHub API. If the fetch fails, log and skip.
4. Read version info from the fetched _meta.json (for Source Patrol tracking)
5. Determine security audit approach (see Step 5 below)
   - Note: the security audit should cover ALL downloaded files, not just SKILL.md.
     Scripts (*.py, *.sh) and config files are especially important to check.
6. Generate a Chinese README.md summary (see references/readme-template.md)
   - Include a "Bundled Resources" section listing all extra files and their purpose
7. Save the generated README.md:
   - ${DEEPDIVE_LOCAL}/{category_name}/{skill-name}/README.md
   (SKILL.md and other files are already saved by fetch_skill.py in step 3)
8. Record metadata to the skill registry (see below)
```

**Skill directory structure in deepdive repo:**

A skill with bundled resources will look like this:

```
${DEEPDIVE_LOCAL}/{category}/{skill-name}/
├── README.md              ← generated by this skill (Chinese summary + security audit)
├── SKILL.md               ← fetched from source
├── references/            ← fetched from source (if exists)
│   ├── guide.md
│   └── examples.md
├── scripts/               ← fetched from source (if exists)
│   └── helper.py
└── assets/                ← fetched from source (if exists)
    └── template.md
```

**Recording skill metadata to registry:**

After processing each skill, the subagent must append an entry to the skill registry
file at `${DEEPDIVE_LOCAL}/.skill-registry.json`. The key is `{category}/{skill-name}`
and the value contains all metadata needed for future Source Patrol checks:

```json
{
  "Apple Apps & Services/apple-notes": {
    "owner": "steipete",
    "slug": "apple-notes",
    "displayName": "Apple Notes",
    "version": "1.0.0",
    "publishedAt": 1767545294031,
    "commit": "https://github.com/clawdbot/skills/commit/304c7cae...",
    "history": [],
    "clawskills_url": "https://clawskills.sh/skills/steipete-apple-notes",
    "vt_status": "Benign",
    "oc_status": "Benign",
    "files": ["SKILL.md", "_meta.json"],
    "fetched_at": "2026-03-22T08:00:00+00:00"
  },
  "Coding Agents & IDEs/system-architect": {
    "owner": "1999azzar",
    "slug": "system-architect",
    "displayName": "System Architect",
    "version": "1.0.0",
    "publishedAt": 1770939015246,
    "commit": "https://github.com/openclaw/skills/commit/762d0d89...",
    "history": [],
    "clawskills_url": "https://clawskills.sh/skills/1999azzar-system-architect",
    "vt_status": "Benign",
    "oc_status": "Benign",
    "files": ["SKILL.md", "_meta.json",
              "assets/templates/ARCHITECTURE.md", "assets/templates/README.md",
              "references/js-ts-standards.md", "references/python-standards.md",
              "references/scaffolding.md", "references/security-checklist.md"],
    "fetched_at": "2026-03-22T08:00:00+00:00"
  }
}
```

The registry entry extends the upstream `_meta.json` fields (`owner`, `slug`,
`displayName`, `version`, `publishedAt`, `commit`, `history`) with our own tracking
fields (`clawskills_url`, `vt_status`, `oc_status`, `files`, `fetched_at`).

This means Source Patrol can later compare `version` + `publishedAt` against the
remote `_meta.json` to detect updates — no need for ETag or full content comparison.

**Slug resolution fallback** (if ClawSkills page is unavailable):

Use `scripts/resolve_slug.py` which tries splitting the slug at each hyphen position
from left to right, checking each candidate against the GitHub raw URL until one returns
HTTP 200. In this case, security status defaults to "Unknown" and the full 10-category
audit is performed.

### Step 5: Security Audit (Tiered)

Security auditing uses a **tiered approach** to avoid redundant work:

#### Tier 1: Trust ClawHub (fast path)

If **both** VirusTotal and OpenClaw report **"Benign"** on the ClawHub page:
- **Skip** the full 10-category manual audit
- Record the ClawHub security status in the README as-is
- Set overall rating to "🟢 ClawHub Verified (Benign)"

This is the expected path for the majority of skills. ClawHub already runs VirusTotal
scanning and OpenClaw's own security review on every published skill.

#### Tier 2: Full manual audit (suspicious or unknown)

Trigger the full 10-category audit from `references/security-checklist.md` when **any**
of these conditions are true:
- VirusTotal reports **"Suspicious"** (or anything other than "Benign")
- OpenClaw reports **"Suspicious"** (or anything other than "Benign")
- The ClawHub page could not be fetched (security status = "Unknown")
- The skill has **0 downloads and 0 installs** (brand new, unvetted)

The full audit covers 10 categories (SEC-01 through SEC-10):
1. Arbitrary Command Execution
2. Network Exfiltration
3. Credential Harvesting
4. Supply Chain Risk
5. File System Manipulation
6. Prompt Injection
7. Scope Creep
8. Persistence Mechanisms
9. Reconnaissance
10. Obfuscation

Each category is rated: 🟢 Pass / 🟡 Warn / 🔴 Danger

Overall rating follows the rules in `references/security-checklist.md`:
- Safe / Low / Medium / High / Critical

### Step 6: Generate Chinese README

For each skill, generate a Chinese README.md. This is the **core value-add** of the
deepdive — a well-written Chinese summary that saves readers from parsing raw English docs.

**The subagent MUST read the fetched skill files** and produce a quality summary.
Do NOT just copy raw fragments. The README must be an independently readable Chinese document.

#### Step 6.0: Determine source material

Check if the fetched skill directory contains an **original README.md** from the
upstream repo (not our generated one — the one fetched by `fetch_skill.py`).

**Path A: Original README.md exists** (e.g., `agentic-devops`, `kube-medic`)

When the upstream skill already has a README.md, use it as the **primary source**:
1. Read the original README.md — it's usually a well-structured human-readable doc
   with Features, Quick Start, Usage, etc.
2. Translate and summarize its content into Chinese
3. Rename the original to `ORIGINAL_README.md` to preserve it
4. Generate our README.md based on the translated content + security info

The original README is typically better than SKILL.md for summarization because:
- Authors write READMEs for humans, SKILL.md for AI agents
- READMEs have clear feature lists, usage examples, and prerequisites
- The structure maps directly to our template sections

**Path B: No original README.md** (only SKILL.md)

Fall back to reading and summarizing SKILL.md (the existing logic below).

#### Required sections and how to generate each:

**1. 标题和描述** — Translate the skill's name and description into a natural Chinese
sentence. Source: original README.md title/intro paragraph (Path A) or SKILL.md
frontmatter `description` field (Path B).
- Good: `> 生产级 DevOps 工具包：Docker 管理、进程监控、日志分析和健康检查`
- Bad: `> Production-grade agent DevOps toolkit` (untranslated English)

**2. 功能概述** — Extract and translate the 3-8 most important capabilities:
- **Path A**: Translate the "Features" or key sections from original README.md
- **Path B**: Read the ENTIRE SKILL.md body and summarize
Each bullet should be a concise Chinese sentence, not a raw copy.
- Good: `- Docker 操作：容器状态查看、日志追踪（支持模式匹配）、健康检查、Compose 服务状态`
- Bad: `- **Docker Operations** — Container status, log tailing...` (raw English copy)

**3. 使用场景** — Write 1-3 concrete scenarios in Chinese. REQUIRED, do not skip.
- **Path A**: Derive from README.md's "Quick Start" or "Usage" sections
- **Path B**: Derive from SKILL.md content
- Example: `- 生产环境容器故障排查：一条命令获取全系统诊断报告`

**4. 依赖和前提条件** — Extract required tools, API keys, platform requirements. REQUIRED.
- **Path A**: Often clearly listed in README.md's "Requirements" or "Installation" section
- **Path B**: Extract from SKILL.md
If no special dependencies, write "无特殊依赖".

**5. 包含文件** — List all files fetched by `fetch_skill.py`. Note which files are
from the original repo (SKILL.md, README.md, scripts/, references/) vs generated by us.

**6. 安全状态** — Apply the tiered logic from Step 5:
- If both VT and OC are "Benign" → Tier 1 template (simple status table)
- Otherwise → Tier 2 template (full 10-category audit table)

See `references/readme-template.md` for the exact markdown format.

#### File naming when original README exists:

```
${DEEPDIVE_LOCAL}/{category}/{skill-name}/
├── README.md              ← OUR generated Chinese README (always this name)
├── ORIGINAL_README.md     ← renamed from the upstream README.md (preserved)
├── SKILL.md               ← from upstream (unchanged)
├── _meta.json             ← from upstream (unchanged)
└── ...                    ← other upstream files (unchanged)
```

#### Quality checklist for each README:

- [ ] Description is in Chinese (not English copy-paste)
- [ ] 功能概述 has 3-8 Chinese bullet points summarizing key capabilities
- [ ] 使用场景 section exists with 1-3 concrete scenarios
- [ ] 依赖和前提条件 section exists
- [ ] Security status correctly reflects ClawHub VT/OC verdicts
- [ ] No raw English fragments copied verbatim
- [ ] If original README.md existed, it is preserved as ORIGINAL_README.md

### Step 6.5: Generate Category Summary README

After all skills in a category are processed, generate (or update) a `README.md`
at the category directory level. This README is a summary table of all skills in
that category.

**Path:** `${DEEPDIVE_LOCAL}/{category_name}/README.md`

**Template:**

```markdown
# {category_name}

> 共 {N} 个 skill | 最后更新: {YYYY-MM-DD}

| Skill | 描述 | 作者 | 版本 | 安全状态 | 文件数 |
|---|---|---|---|---|---|
| [{skill-name}](./{skill-name}/) | {中文一句话描述} | {owner} | {version} | {security_emoji} | {file_count} |
| ... | ... | ... | ... | ... | ... |
```

**Column definitions:**

| 列 | 来源 | 说明 |
|---|---|---|
| Skill | 目录名，链接到子目录 | 点击可进入 skill 详情 |
| 描述 | 从该 skill 的 README.md 第一行 `>` blockquote 提取 | 中文一句话描述 |
| 作者 | `.skill-registry.json` 中的 `owner` 字段 | |
| 版本 | `.skill-registry.json` 中的 `version` 字段 | |
| 安全状态 | 基于 VT/OC 状态 | 🟢 Benign / 🟡 Suspicious / ⚪ Unknown |
| 文件数 | `.skill-registry.json` 中 `files` 数组长度 | 反映 skill 复杂度 |

**Security emoji mapping:**
- VT=Benign 且 OC=Benign → `🟢`
- VT 或 OC 为 Suspicious → `🟡`
- 状态未知 → `⚪`

**How to generate:**

The subagent processing a category should, after finishing all skills, scan the
category directory and `.skill-registry.json` to build the table. Pseudocode:

```python
# Collect data for all skills in this category
rows = []
for skill_dir in sorted(category_dir.iterdir()):
    if not skill_dir.is_dir():
        continue
    key = f"{category_name}/{skill_dir.name}"
    meta = registry.get(key, {})

    # Read description from skill's README.md first line blockquote
    readme = skill_dir / "README.md"
    desc = ""
    if readme.exists():
        for line in readme.read_text().splitlines():
            if line.startswith("> "):
                desc = line[2:].strip()
                break

    # Security emoji
    vt = meta.get("vt_status", "Unknown")
    oc = meta.get("oc_status", "Unknown")
    if vt == "Benign" and oc == "Benign":
        sec = "🟢"
    elif "Suspicious" in (vt, oc):
        sec = "🟡"
    else:
        sec = "⚪"

    rows.append({
        "name": skill_dir.name,
        "desc": desc,
        "owner": meta.get("owner", "?"),
        "version": meta.get("version", "?"),
        "security": sec,
        "files": len(meta.get("files", [])),
    })

# Write category README.md
```

**When to regenerate:**

This category README must be regenerated whenever:
- A new skill is added to the category (initial deepdive or incremental add)
- A skill is updated (Source Patrol detected version change)
- A skill is removed from the category (incremental remove)

In all three cases, rebuild the entire table for the affected category from the
current directory contents + registry data.

### Step 7: Commit and Push

After all subagents complete:

```bash
cd ${DEEPDIVE_LOCAL}
git add -A
git commit -m "deepdive: update $(date +%Y-%m-%d) — processed $(find . -name SKILL.md | wc -l) skills"
git push origin main
```

### Step 8: Generate Summary Report

Update the deepdive repo's root `README.md` with:
- Total skills analyzed per category
- Security risk distribution (how many Safe/Low/Medium/High/Critical)
- List of High/Critical risk skills (if any) for manual review
- Last update timestamp

## Incremental Runs (Unified Change Detection)

After the initial full run, subsequent runs use `scripts/check_upstream.py` to detect
changes from **both** upstream repos in a single pass:

- **awesome-openclaw-skills** — listing changes (skill added/removed from categories)
- **openclaw/skills** — content changes (skill author updated SKILL.md, scripts, etc.)

### State Tracking

State is stored in `${DEEPDIVE_LOCAL}/.upstream-state.json`:

```json
{
  "awesome_commit": "9f72a5acb960...",
  "skills_commit": "b8f5f94fb539...",
  "last_check": "2026-03-23T08:00:00+00:00"
}
```

### Unified Flow

```
check_upstream.py
  ↓
Phase 1: GET awesome-openclaw-skills latest commit
  ├── same as awesome_commit → listing unchanged, skip
  └── different → scan category files against registry
      ├── added skills   → need first-time deepdive
      └── removed skills → archive or delete
  ↓
Phase 2: GET openclaw/skills latest commit
  ├── same as skills_commit → content unchanged, skip
  └── different → GitHub Compare API: diff old..new
      ↓
      Filter changed files through our watch list (.skill-registry.json)
      ↓
      Only skills in our registry are processed, others ignored
      ↓
      updated skills → need re-fetch + re-audit + regenerate README
  ↓
Dispatch subagents for affected skills (Step 4/5/6/6.5)
  ↓
Write CHANGELOG → Commit → Push
  ↓
Update .upstream-state.json with new commit SHAs
```

### Usage

```bash
# Check for changes (both repos)
python3 scripts/check_upstream.py \
  --deepdive-dir ${DEEPDIVE_LOCAL} \
  --awesome-dir ${UPSTREAM_LOCAL} \
  --output /tmp/upstream-changes.json

# Dry run — show changes without updating state
python3 scripts/check_upstream.py \
  --deepdive-dir ${DEEPDIVE_LOCAL} \
  --awesome-dir ${UPSTREAM_LOCAL} \
  --dry-run
```

### Output Format

The output JSON groups changes by type:

```json
{
  "checked_at": "2026-03-23T08:00:00+00:00",
  "awesome": {
    "changed": true,
    "added": [{"category": "DevOps & Cloud", "name": "new-skill", "slug": "..."}],
    "removed": [{"category": "Gaming", "name": "old-skill"}]
  },
  "skills": {
    "changed": true,
    "updated": [
      {
        "category": "DevOps & Cloud",
        "name": "kube-medic",
        "author": "tkuehnl",
        "changed_files": [
          {"path": "SKILL.md", "status": "modified"},
          {"path": "scripts/diagnose.py", "status": "modified"}
        ]
      }
    ]
  },
  "action_required": true
}
```

### Processing Changes

When `action_required` is true, dispatch subagents to handle each type:

**Added skills** (from `awesome.added`):
- Full first-time processing: fetch entire skill dir → ClawHub check → generate README
- Same as Step 4/5/6/6.5 for initial deepdive

**Updated skills** (from `skills.updated`):
- Re-fetch entire skill directory using `scripts/fetch_skill.py`
- Re-check ClawHub security status
- Regenerate skill README (Step 6) and category README (Step 6.5)
- Update `.skill-registry.json` from new `_meta.json`

**Removed skills** (from `awesome.removed`):
- Delete the skill directory from deepdive repo, or move to `_archived/`
- Remove entry from `.skill-registry.json`
- Regenerate category README (Step 6.5) for the affected category

### Changelog

Every incremental run appends to `${DEEPDIVE_LOCAL}/CHANGELOG.md`:

```markdown
## {YYYY-MM-DD}

### Added ({count})
- [{category}] {skill-name} — {one-line description}

### Updated ({count})
- [{category}] {skill-name} — changed: {list of changed files}

### Removed ({count})
- [{category}] {skill-name}
```

### When Nothing Changed

If both repos have the same commit as stored in `.upstream-state.json`:
- Skip all processing
- Do NOT create an empty commit
- Log "Nothing to do" and exit

## Error Handling

- **SKILL.md fetch fails (404/timeout)**: Log to `${DEEPDIVE_LOCAL}/_errors.log`, skip skill
- **ClawSkills page unavailable**: Use fallback slug resolution strategy
- **Subagent timeout**: Retry the category once, then log and continue
- **Git push conflict**: Pull and rebase before retry

## Important Notes

- Respect GitHub rate limits: add 0.5s delay between raw file fetches within each subagent
- The skill registry has 5000+ skills — a full run may take significant time
- For ClawHub Benign skills, trust the platform's VirusTotal + OpenClaw verdict and skip manual audit
- Only run the full 10-category manual audit on Suspicious/Unknown skills to save time
- Output all user-facing text in Chinese (中文)
