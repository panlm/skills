# 中文 README 模板

每个 skill 的中文 README.md 按以下模板生成。所有内容必须为中文。

根据安全审计的分层策略，README 有 **两种变体**：
- **Tier 1 (ClawHub Benign)**: 简化版安全信息，不展开 10 项检查
- **Tier 2 (需要人工审计)**: 完整的 10 项安全审计表格

---

## 模板 A: Tier 1 — ClawHub 已验证为 Benign

当 VirusTotal 和 OpenClaw 均报告 "Benign" 时使用此模板。

```markdown
# {skill_name}

> {一句话中文描述，翻译自原始 description}

## 基本信息

| 项目 | 内容 |
|---|---|
| **名称** | {skill_name} |
| **作者** | {author} |
| **ClawHub** | {clawskills_url} |
| **GitHub** | {github_url} |
| **安全评级** | 🟢 ClawHub Verified (Benign) |

## 功能概述

{从 SKILL.md 提取的功能要点，翻译为中文，3-8 个要点}

- 功能点 1
- 功能点 2
- ...

## 使用场景

{什么时候应该使用这个 skill，1-3 个典型场景}

## 依赖和前提条件

{从 SKILL.md 中提取的依赖项}

- 依赖 1
- 依赖 2
- ...

如果无特殊依赖，写"无特殊依赖"。

## 安全状态

| 来源 | 评级 |
|---|---|
| VirusTotal | 🟢 Benign |
| OpenClaw | 🟢 Benign |

> ClawHub 安全扫描已通过，跳过详细审计。

---

> 本文档由 awesome-skills-deepdive skill 自动生成，仅供参考。
> 生成时间: {timestamp}
```

---

## 模板 B: Tier 2 — 需要完整安全审计

当以下任一条件成立时使用此模板：
- VirusTotal 或 OpenClaw 报告 "Suspicious"（或非 "Benign"）
- ClawHub 页面无法访问（安全状态未知）
- Skill 下载量和安装量均为 0（全新未审核）

```markdown
# {skill_name}

> {一句话中文描述，翻译自原始 description}

## 基本信息

| 项目 | 内容 |
|---|---|
| **名称** | {skill_name} |
| **作者** | {author} |
| **ClawHub** | {clawskills_url} |
| **GitHub** | {github_url} |
| **安全评级** | {risk_emoji} {risk_level} |

## 功能概述

{从 SKILL.md 提取的功能要点，翻译为中文，3-8 个要点}

- 功能点 1
- 功能点 2
- ...

## 使用场景

{什么时候应该使用这个 skill，1-3 个典型场景}

## 依赖和前提条件

{从 SKILL.md 中提取的依赖项}

- 依赖 1
- 依赖 2
- ...

如果无特殊依赖，写"无特殊依赖"。

## 安全状态 (ClawHub)

| 来源 | 评级 |
|---|---|
| VirusTotal | {vt_emoji} {vt_status} |
| OpenClaw | {oc_emoji} {oc_status} |

> ⚠️ ClawHub 安全扫描未通过或状态未知，已执行完整安全审计。

## 详细安全审计

| 检查项 | 评级 | 发现 |
|---|---|---|
| SEC-01 命令执行 | {emoji} {rating} | {finding} |
| SEC-02 数据外泄 | {emoji} {rating} | {finding} |
| SEC-03 凭证获取 | {emoji} {rating} | {finding} |
| SEC-04 供应链风险 | {emoji} {rating} | {finding} |
| SEC-05 文件系统篡改 | {emoji} {rating} | {finding} |
| SEC-06 Prompt 注入 | {emoji} {rating} | {finding} |
| SEC-07 越权操作 | {emoji} {rating} | {finding} |
| SEC-08 持久化机制 | {emoji} {rating} | {finding} |
| SEC-09 信息采集 | {emoji} {rating} | {finding} |
| SEC-10 混淆/反分析 | {emoji} {rating} | {finding} |

**综合评级: {risk_emoji} {risk_level}**

**风险摘要:** {一句话中文风险总结}

---

> 本文档由 awesome-skills-deepdive skill 自动生成，仅供参考。
> 安全审计基于 SKILL.md 静态分析，不代表运行时行为。
> 生成时间: {timestamp}
```

---

## Emoji 映射

| 评级 | Emoji |
|---|---|
| Benign | 🟢 |
| Suspicious | 🟡 |
| Unknown | ⚪ |
| 通过 (Pass) | 🟢 |
| 警告 (Warn) | 🟡 |
| 危险 (Danger) | 🔴 |
| ClawHub Verified (Benign) | 🟢 |
| Safe (安全) | 🟢 |
| Low (低风险) | 🟢 |
| Medium (中风险) | 🟡 |
| High (高风险) | 🔴 |
| Critical (严重) | 🔴 |

## 审计触发条件速查

| 条件 | 使用模板 | 是否执行 10 项审计 |
|---|---|---|
| VT=Benign + OC=Benign | 模板 A | 否 |
| VT=Suspicious 或 OC=Suspicious | 模板 B | 是 |
| ClawHub 页面无法访问 | 模板 B | 是 |
| 下载量=0 且 安装量=0 | 模板 B | 是 |

## 注意事项

- 所有文字输出为中文
- 功能概述应简明扼要，每条不超过一行
- 安全审计的"发现"列应具体描述观察到的内容，不要只写"无"
  - 好例子: "仅使用 `memo` CLI 操作本地 Notes.app，无 shell 管道"
  - 坏例子: "无"
- 如果 SKILL.md 获取失败，README 中注明"原始 SKILL.md 获取失败"并仅保留基本信息
- ClawHub 页面中的下载量和安装量可从页面文本中提取，格式如 "20.8k downloads" / "969 installs"
