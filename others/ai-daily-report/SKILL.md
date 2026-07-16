---
name: ai-daily-report
description: Use when generating panlm's daily AI work report — the 00:30 cron task that summarizes the previous day's (Asia/Shanghai) agent activity from agentmemory and appends it to the monthly Feishu doc 工作日报-YYYYMM. Triggers on "AI日报", "生成日报", "工作日报", daily report cron.
---

# AI 每日工作日报

## Overview

定时任务：每天北京时间 00:30 运行，为 panlm 生成【前一天(Asia/Shanghai)整天】的 AI 工作日报。因为在 00:30 跑，报告日 = 昨天。核心动作：算准时间窗口 → 逐 session 枚举窗口内全部 agent 活动 → 写成中文日报 → 只 insert 到当月飞书文档 → 简短汇报。

## When to Use

- 00:30 定时日报任务触发时
- panlm 要求"生成 AI 日报 / 工作日报"时
- 需要汇总某一天所有 agent(claude-code/opencode/codex 等)的活动时

## Step 0: 先算准时间窗口(关键)

agentmemory 没有按时间范围查的接口，必须自己算窗口再过滤。用 exec 跑，不要手算：

```bash
D=$(TZ=Asia/Shanghai date -d 'yesterday' +%Y-%m-%d)               # 报告日 = 昨天(北京)
DOW=$(TZ=Asia/Shanghai date -d "$D" +%u)                          # 星期几(1=周一)
YM=$(TZ=Asia/Shanghai date -d "$D" +%Y%m)                         # 年月, 用于飞书文档名
START=$(date -u -d "$D 00:00:00 +0800" +%Y-%m-%dT%H:%M:%SZ)       # 报告日00:00(北京)→UTC
END=$(date -u -d "$D 00:00:00 +0800 +1 day" +%Y-%m-%dT%H:%M:%SZ)  # 次日00:00(北京)→UTC
echo "报告日 $D DOW=$DOW YM=$YM START=$START END=$END"
```

窗口 = `[START, END)`，正好报告日北京时区完整一天(0点到24点)。不漏早晨，不混入运行当天凌晨。

## Step 1: 枚举窗口内全部 agent 活动

**不要用 project 过滤。** 任务分散在多 project(openclaw1/devops-agent-cn-bridge/panlm 等)和多机器(EC2 + Mac 上的 claude-code)。project 过滤会漏掉 Mac 上的 claude-code session，必须覆盖窗口内【全部 agent/project】。

session 枚举是唯一可信的全貌来源，不能只靠一次 timeline 或相关度搜索：

- **a.** `memory_timeline(anchor=START, before=0, after=1000)` 打底。anchor 传【完整 ISO UTC 时间戳(带 Z)】。
- **b.** timeline 返回可能因【输出体积】被截断(只显头尾、中间省略)，跟"条数是否到 1000"无关——几百条也可能被截。只要看到输出被截断/省略，就分页(anchor 往后挪、缩小 before/after)多拉几轮，直到 `[START,END)` 全覆盖。**不能只靠条数判断是否漏。**
- **c.** 用 `memory_sessions` 列出所有 session，挑窗口内有活动的，【逐个 session】核对：对每个用 `smart_search`(带该 session 关键词)或把 timeline anchor 挪到该 session 时间点展开，确认活动都被纳入。relevance 搜索(recall/smart_search)只返回代表性记录、会整条漏 session，【只能】补细节，不能替代逐 session 枚举。
- **d.** 所有 entries 按 `observation.timestamp` 过滤，只留 `[START, END)` 内的；早于 START 或不早于 END(运行当天)的一律丢弃。

补充：`memory_recall`/`memory_smart_search` 按不同主题多捞几轮补关键任务详情；`memory_lesson_recall` 查报告日新增经验。查路径时 file_write/file_read/command_run 类 observation 常带绝对路径，尽量提取。

## Step 2: 写成中文日报

- 只用一个日期标题 `## YYYY-MM-DD 周X`（日期用报告日 D，周几用 DOW 换算，别手推），**不要任何子标题(不要 ### )**。
- 标题下直接 bullet 列表，每件事一条 bullet。
- 每条 bullet 用 3-5 句：做了什么、过程/踩的坑、产出、文件保存路径(查得到才写)。路径标清哪台机器(如 Mac `~/xxx`、EC2、basic-memory 哪个项目)。查不到路径就不写，**不要编造**。
- 不同项目/不同任务(如两个不同渗透测试、不同 pentestId/目标)【分开成不同 bullet】，不要糅成一句。
- 不要"负责 Agent"、"时间段"字段。零碎小事合并成最后一条 bullet。不要单独的"统计""总结"段落。

## Step 3: 写入飞书月度文档(纪律点 2：只 insert 报告日一段)

目标文档：当月一篇 `工作日报-YM`(YM=报告日年月如 202607)，倒序，最新在最上。

**固定用 insert 只插报告日一段，禁止整篇 write 覆盖。** 文档会越来越长，整篇重写会让单次输出体积过大、超模型输出上限(stopReason=length)被截断，导致写入工具调用根本没发出、日报写不进去——这是 2026-07-07 那次失败的根因。

- **a.** `feishu_drive(action=list)` 在根目录找 `工作日报-YM` 的 docx。doc_token 全程用完整 `document_id`，不要用 … 省略，否则 400。
- **b.** 若【已存在】：
  - `feishu_doc(action=list_blocks)` 拿 block 结构，找那条【分割线 divider(block_type=22)】的 block_id。
  - 若文档里已有报告日这段(`## YYYY-MM-DD ...` 标题)，先把旧段落(标题及其下所有 bullet)用 `feishu_doc(action=delete_block)` 逐块删掉，再重插；没有就直接插。
  - `feishu_doc(action=insert, after_block_id=<分割线 block_id>, content=<报告日这一段 markdown>)`。报告日段插在分割线之后、更早旧日期之前，实现倒序。
- **c.** 若【不存在】：`feishu_doc(action=create, title='工作日报-YM')` 新建，再 `feishu_doc(action=write)` 只写 `# 工作日报 · YYYY年M月` + `---` + 报告日段落(首篇小，write 没问题)。权限没自动加就 `feishu_perm` 给 用户 加 edit。
- **d.** 【写入自检·必须】insert/write 返回后确认 success 且 `blocks_added>0`(或 write 成功)；没成功必须重试或明确报错。**绝不允许在没写成功的情况下进入 Step 4 谎报完成。**

## Step 4: 完成后简短汇报

用正常中文完整句：报告日几个主要任务、飞书文档链接。如果窗口内 agentmemory 没有任何活动记录，就写"报告日无 AI 活动记录"并说明。

## Common Mistakes

| 坑 | 后果 | 正确做法 |
|----|------|---------|
| 手算 UTC 窗口 | 时区算错，漏/混入活动 | 跑 Step 0 的 date 命令 |
| 用 project 过滤 | 漏 Mac 上 claude-code session | 逐 session 枚举全 project |
| 只信一次 timeline | 输出被体积截断，漏中间记录 | 分页多拉 + memory_sessions 逐个核对 |
| 整篇 write 覆盖飞书 | 输出超 length 上限被截、写入失败(2026-07-07 根因) | 只 insert 报告日一段到 divider 之后 |
| doc_token 用 … 省略 | 飞书返回 400 | 全程用完整 document_id |
| 没自检就报完成 | 谎报，日报实际没写进去 | 确认 success + blocks_added>0 再汇报 |

## Red Flags — 停下重来

- "手算一下 UTC 就行" → 跑命令
- "timeline 拉了一次够了" → 逐 session 核对
- "整篇重写更干净" → 只 insert 一段
- "应该写进去了" → 看返回的 success/blocks_added
