# awesome-skills-deepdive — Skill 能力总结

## 一句话概述

自动化分析 awesome-openclaw-skills 仓库中 5000+ 社区 skill：抓取源码、安全审计、生成中文摘要，并通过 GitHub commit diff 持续追踪上游变更。

## 解决什么问题

awesome-openclaw-skills 收录了 5000+ 社区贡献的 skill，但：
- 全英文，没有中文资料
- 数量太多，无法逐个评估
- 安全性未知，部分 skill 可能有风险
- 作者随时更新，但无人跟踪

本 skill 自动完成这些工作，输出到 `panlm/awesome-skills-deepdive` GitHub repo。

## 三个 repo 的关系

```
① openclaw/skills           ← skill 实际代码存放地 (5000+ skill 的 monorepo)
   ↑ 被引用
② awesome-openclaw-skills    ← 社区精选列表 (category/*.md 存链接，做"筛选器")
   → fork 到 panlm/awesome-openclaw-skills
   ↓ 我们分析
③ panlm/awesome-skills-deepdive  ← 我们的输出 (中文摘要 + 安全审计)
```

## 核心能力

### 1. 全量抓取 (首次运行)

```
upstream repo → parse 30 categories → dispatch subagent per category →
fetch 完整 skill 目录 (SKILL.md + _meta.json + scripts/ + references/ + ...) →
安全审计 → 生成中文 README → 生成 Category 汇总表 → commit & push
```

- 解析 30 个 category 文件，提取 5128 个 skill 的 slug
- 按 category 并行派发 subagent (每批 5-6 个)
- 通过 GitHub API 递归下载 skill 完整目录，不只是 SKILL.md
- 如果上游 skill 自带 README.md，保存为 `ORIGINAL_README.md` 并优先用它翻译

### 2. 中文 README 生成 (每个 skill)

每个 skill 生成一份中文 README.md，包含：

| 章节 | 来源 |
|---|---|
| 标题和中文描述 | 翻译自 README.md (优先) 或 SKILL.md frontmatter |
| 功能概述 (3-8 条) | 从 README/SKILL.md 提取并翻译 |
| 使用场景 (1-3 条) | 基于内容总结 |
| 依赖和前提条件 | 提取 CLI 工具、API key、平台要求等 |
| 包含文件列表 | 来自 fetch_skill.py 的文件清单 |
| 安全状态 | 分层审计结果 (见下方) |

**双路径策略**：
- **Path A**: 上游有 README.md → 以它为主要来源翻译总结 (质量更高)
- **Path B**: 仅有 SKILL.md → 从中提取内容翻译总结

### 3. Category 汇总表 (每个 category)

每个 category 目录下生成 README.md，用 markdown 表格汇总所有 skill：

| 列 | 说明 |
|---|---|
| Skill | 链接到 skill 子目录 |
| 描述 | 中文一句话描述 |
| 作者 | owner |
| 版本 | version |
| 安全状态 | 🟢 Benign / 🟡 Suspicious / ⚪ Unknown |
| 文件数 | 反映 skill 复杂度 |

当 category 下有 skill 新增/更新/删除时，自动重新生成该 category 的汇总表。

### 4. 分层安全审计

| 层级 | 触发条件 | 做什么 |
|---|---|---|
| **Tier 1** | ClawHub VirusTotal=Benign 且 OpenClaw=Benign | 跳过详细审计，直接标记 🟢 |
| **Tier 2** | VT 或 OC 为 Suspicious / 状态未知 / 零下载 | 执行 10 项安全检查 (SEC-01~SEC-10) |

10 项安全检查：命令执行 / 数据外泄 / 凭证获取 / 供应链 / 文件篡改 / Prompt 注入 / 越权 / 持久化 / 信息采集 / 混淆

### 5. 统一变更追踪 (check_upstream.py)

合并了原来的两条独立管线为一次运行：

```
check_upstream.py
  ↓
Phase 1: GET awesome-openclaw-skills 最新 commit
  ├── 相同 → 列表没变
  └── 不同 → 扫描 category 文件，找出 added/removed skill
  ↓
Phase 2: GET openclaw/skills 最新 commit
  ├── 相同 → 内容没变
  └── 不同 → GitHub Compare API 获取 diff
      → 过滤：只保留"关注列表"中的 skill (awesome 列表筛选出来的)
      → 输出受影响的 skill 及其变更文件列表
  ↓
处理变更 → 更新 README + Category 汇总表 → Commit → Push
```

**状态追踪**：`.upstream-state.json` 记录两个 repo 的 last commit SHA

**核心设计**：
- awesome 列表做"筛选器"— 决定哪些 skill 值得关注
- openclaw/skills 做"更新源"— 追踪关注列表中 skill 的实际内容变更
- 一次 GitHub Compare API 调用替代原来 5000+ 次 _meta.json fetch

## 文件结构

```
~/.openclaw/skills/awesome-skills-deepdive/
├── SKILL.md                          # 完整工作流指令
├── scripts/
│   ├── parse_category.py             # 解析 category .md → JSON manifest
│   ├── resolve_slug.py               # ClawHub slug → GitHub author/name
│   ├── fetch_skill.py                # 递归下载完整 skill 目录 (含 README 重命名)
│   └── check_upstream.py             # 统一变更检测 (commit diff)
└── references/
    ├── security-checklist.md          # 10 项安全审计检查清单
    └── readme-template.md             # 中文 README 模板 (Tier 1 + Tier 2)
```

## 输出 repo 结构

```
panlm/awesome-skills-deepdive/
├── .skill-registry.json              # 全局 skill 元数据
├── .upstream-state.json              # 两个上游 repo 的 commit SHA
├── CHANGELOG.md                      # 变更日志
├── README.md                         # 总览报告
├── Apple Apps & Services/
│   ├── README.md                     # ← Category 汇总表 (md table)
│   └── apple-notes/
│       ├── README.md                 # 中文摘要 + 安全审计
│       ├── SKILL.md                  # 上游原文
│       └── _meta.json
├── DevOps & Cloud/
│   ├── README.md                     # ← Category 汇总表
│   └── agentic-devops/
│       ├── README.md                 # 中文摘要
│       ├── ORIGINAL_README.md        # 上游自带 README (保留)
│       ├── SKILL.md
│       ├── _meta.json
│       └── devops.py
└── ... (30 categories)
```

## 触发方式

```
# 首次全量运行
帮我 deepdive awesome openclaw skills

# 检查更新 (统一流程)
检查 awesome skills 有没有更新

# 针对特定 category
帮我分析 DevOps & Cloud 类别下的社区 skill

# 安全审查
审查 awesome skills 的安全性
```

## 依赖

- `gh` CLI (已认证)
- `git` (有 push 权限)
- `python3` (仅标准库，无第三方包)
- 网络访问 (GitHub API + raw.githubusercontent.com + clawskills.sh)
