---
name: ai-daily-report
description: Use when generating panlm's daily AI work report — the 00:30 cron task that summarizes the previous day's (Asia/Shanghai) agent activity from agentmemory and appends it to the monthly Feishu doc 工作日报-YYYYMM. Triggers on "AI日报", "生成日报", "工作日报", daily report cron.
---

# AI 每日工作日报

## Overview

定时任务：每天北京时间 00:30 运行，为 panlm 生成【前一天(Asia/Shanghai)整天】的 AI 工作日报。因为在 00:30 跑，报告日 = 昨天。核心动作：算准时间窗口 → 逐 session 枚举窗口内全部 agent 活动 → 写成中文日报 → 只 insert 到当月飞书文档 → 简短汇报。

**取数主源只有一个：timeline 分页 + `memory_sessions` 逐 session 枚举。** `memory_export`/`recall`/`smart_search` 返回 curated memory(个位数条目)，只能补细节，用它当主源必然漏掉绝大部分活动 —— 详见 Step 1 纪律点 1。

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

**上面是 GNU date(EC2/Linux)。在 Mac 上 `date -d` 不存在**(BSD date)，会直接报错。Mac 上用 python 算，别去凑 `date -v` 的写法：

```bash
python3 -c "
from datetime import datetime,timedelta,timezone
sh=timezone(timedelta(hours=8))
d=(datetime.now(sh)-timedelta(days=1)).date()
start=datetime(d.year,d.month,d.day,tzinfo=sh); end=start+timedelta(days=1)
print('D',d,'DOW',start.isoweekday(),'YM',d.strftime('%Y%m'))
print('START',start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
print('END',end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
"
```

## Step 1: 枚举窗口内全部 agent 活动

**不要用 project 过滤。** 任务分散在多 project(openclaw1/devops-agent-cn-bridge/panlm 等)和多机器(EC2 + Mac 上的 claude-code)。project 过滤会漏掉 Mac 上的 claude-code session，必须覆盖窗口内【全部 agent/project】。

### 纪律点 1(最高优先)：禁止用 curated memory 当主取数源

**`memory_export` / `memory_recall` / `memory_smart_search` 返回的是 curated memory** —— 只含【显式 `memory_save` 过的几条】+ 系统 consolidate 提炼的少数高分条目，**不是当天原始活动**。它们【只能补细节】，**绝不能替代 timeline + session 枚举**。

真实活动躺在 raw observation 里(自动 hook 捕获，从没手动 save 过)，只有 timeline 分页 + `memory_sessions` 逐个核对才看得见。数量级差别是【一位数 vs 几百条】：2026-08-03 那次 cron 就是只跑了 `memory_export` 拿到 4 条 curated memory 就写日报，漏掉窗口内 449 条 observation / 8 个 session 里的 workshop 部署、EBS CSI IRSA、ArgoCD CRD、MySQL 8.4 升级、AgentCore 双 agent 部署等全部内容 —— 而且写入自检还"通过"了。

### 枚举步骤

session 枚举是唯一可信的全貌来源，不能只靠一次 timeline 或相关度搜索：

- **a.** `memory_timeline(anchor=START, before=0, after=400)` 打底。anchor 传【完整 ISO UTC 时间戳(带 Z)】。
- **b.** timeline 返回可能因【输出体积】被截断(只显头尾、中间省略，或整个 response 被落盘)，跟"条数是否到上限"无关——几百条就会被截。**必须分页拉到覆盖 END 之后**：取本页最后一条的 timestamp 当下一页 anchor，重复直到某页最大 timestamp `>= END`。**不能只靠条数判断是否漏。**
- **c.** 输出体积大时(几百 KB)不要在上下文里肉眼过滤，**落盘后用 python 按 id 去重 + 按 timestamp 过滤**，再打印精简清单(timestamp/sessionId/type/title)。
- **d.** 用 `memory_sessions` 列出所有 session，挑窗口内有活动的，【逐个 session】核对。注意 `memory_sessions` 里有【残缺记录】(缺 `startedAt`/`endedAt` 字段)，直接排序会 KeyError，过滤时要 `.get()` 兜底。
- **e.** 所有 entries 按 `observation.timestamp` 过滤，只留 `[START, END)` 内的；早于 START 或不早于 END(运行当天)的一律丢弃。

### 纪律点 1b：取数完整性闸门(枚举完必须报数)

枚举结束后**必须显式报出两个数**：窗口内 **session 数 N** 和 **observation 数 M**，并和 `memory_sessions` 的结果交叉核对。

- `M < 50` 或 `N < 3` → **视为取数可疑，不准往下写**。回到 b/d 重新分页多拉几轮、确认 timeline 覆盖到 END 之后，而不是接受这个结果直接生成日报。
- 若确认当天真的活动很少(比如休假)，在 Step 4 汇报里明确写出"窗口内仅 N 个 session / M 条 observation，已二次确认无遗漏"。

补充：`memory_lesson_recall` 查报告日新增经验(这是补细节，不是主源)。查路径时 file_write/file_read/command_run 类 observation 常带绝对路径，尽量提取。

## Step 2: 写成中文日报

- 只用一个日期标题 `## YYYY-MM-DD 周X`（日期用报告日 D，周几用 DOW 换算，别手推），**不要任何子标题(不要 ### )**。
- 标题下直接 bullet 列表，每件事一条 bullet。
- 每条 bullet 的形状固定两部分，按此顺序：**(1)** 一句加粗总结句放在 bullet 最开头；**(2)** 紧跟 2-3 句细节：做了什么、过程/踩的坑、产出、文件保存路径(查得到才写)。
  - 路径标清哪台机器(如 Mac `~/xxx`、EC2、basic-memory 哪个项目)。查不到路径就不写，**不要编造**。
  - 形状示例：

    ```markdown
    - **给 ai-daily-report skill 换了 bullet 输出格式。** 原来每条 3-5 句纯细节，读起来抓不到重点。改成开头一句加粗总结 + 2-3 句细节。改在 Mac ~/Documents/git/panlm-skills/others/ai-daily-report/SKILL.md。
    ```

- 不同项目/不同任务(如两个不同渗透测试、不同 pentestId/目标)【分开成不同 bullet】，不要糅成一句。
- 不要"负责 Agent"、"时间段"字段。零碎小事合并成最后一条 bullet。不要单独的"统计""总结"段落。

## Step 3: 写入飞书月度文档(纪律点 2：只 insert 报告日一段)

目标文档：当月一篇 `工作日报-YM`(YM=报告日年月如 202607)，倒序，最新在最上。

**固定用 insert 只插报告日一段，禁止整篇 write 覆盖。** 文档会越来越长，整篇重写会让单次输出体积过大、超模型输出上限(stopReason=length)被截断，导致写入工具调用根本没发出、日报写不进去——这是 2026-07-07 那次失败的根因。

- **a.** `feishu_drive(action=list)` 在根目录找 `工作日报-YM` 的 docx。doc_token 全程用完整 `document_id`，不要用 … 省略，否则 400。

  **已知 doc_token**(省得每次搜；确认过属于 panlm 本人)：`202608 = SU8ndWh1PoMfONxLu5CcjgZEnMc`、`202607 = UxLZdrKVyod4pBxyRSScZKh4nHd`。

- **a2 授权失效兜底(Mac 上常见)**：`lark-mcp` 的 user_access_token 有效期只有 2 小时，报 `Current user_access_token is invalid or expired` 时按顺序处理：
  1. 跑 `node ~/.config/lark-daily/lark_refresh.mjs` 用 refresh_token 换新 token(refresh_token 7 天有效，超期只能重新 OAuth)。
  2. **刷完 MCP 进程内存里还是旧 token**，`lark-mcp` 工具仍会报错。此时不要反复重试，直接绕过 MCP 走 REST：从 `@larksuiteoapi/lark-mcp` 的 `storageManager` 读 token，自己 `fetch` 打 `https://open.feishu.cn/open-apis/docx/v1/...`(参考 `~/.config/lark-daily/feishu_fetch.mjs` 的读 token 写法)。
  3. 当前 user token 的 scope **只有 docx 没有 drive**，所以 `/drive/v1/files` 和文档搜索都会报 99991679，只能用已知 doc_token 直接操作。要修就补 `drive:drive:readonly` scope。
  4. `lark-cli-mcp-agentcore` 那条路要走 AgentCore Identity 浏览器授权，无头环境下不可用，不要在 cron 里指望它。
- **b.** 若【已存在】：
  - `feishu_doc(action=list_blocks)` 拿 block 结构，找那条【分割线 divider(block_type=22)】的 block_id。
  - 若文档里已有报告日这段(`## YYYY-MM-DD ...` 标题)，先把旧段落(标题及其下所有 bullet)用 `feishu_doc(action=delete_block)` 逐块删掉，再重插；没有就直接插。
  - `feishu_doc(action=insert, after_block_id=<分割线 block_id>, content=<报告日这一段 markdown>)`。报告日段插在分割线之后、更早旧日期之前，实现倒序。
- **c.** 若【不存在】：`feishu_doc(action=create, title='工作日报-YM')` 新建，再 `feishu_doc(action=write)` 只写 `# 工作日报 · YYYY年M月` + `---` + 报告日段落(首篇小，write 没问题)。权限没自动加就 `feishu_perm` 给 用户 加 edit。
- **d.** 【写入自检·必须】两层都要过，缺一层都不算完成：
  - **d1 写入成功**：insert/write 返回 success 且 `blocks_added > 0`(或 write 成功)。没成功必须重试或明确报错。
  - **d2 内容完整**：`blocks_added` 必须 **≥ bullet 数 + 1**(标题)，且和 Step 1 报的 session 数 N 交叉核对 —— **每个有实质活动的 session 至少对应 1 条 bullet**(纯心跳/空会话除外)。对不上说明 Step 1 取数漏了或 bullet 合并过度，回 Step 1 重查，别拿少的那版交差。
  - **`blocks_added>0` 单独不构成完成信号**。2026-08-03 那次写了 3 个 block 就 success 通过自检，实际漏了 8 个 session 里的绝大部分内容 —— 3 条和 12 条在旧自检眼里一样"成功"。
  - **绝不允许在没写成功、或内容明显不全的情况下进入 Step 4 谎报完成。**

## Step 4: 完成后简短汇报

用正常中文完整句：报告日几个主要任务、飞书文档链接。如果窗口内 agentmemory 没有任何活动记录，就写"报告日无 AI 活动记录"并说明。

## Common Mistakes

| 坑 | 后果 | 正确做法 |
|----|------|---------|
| 用 `memory_export`/`recall` 当主取数源 | **只拿到 curated memory 的个位数条目，漏掉几百条 raw observation(2026-08-03 根因：4 条 vs 449 条)** | timeline 分页 + memory_sessions 逐个枚举；curated 只补细节 |
| 枚举完不报 N/M 数量 | 取数悄悄降级也没人发现，日报缺一大半 | 报出 session 数 N + observation 数 M，`M<50` 或 `N<3` 就重查 |
| 手算 UTC 窗口 | 时区算错，漏/混入活动 | 跑 Step 0 的 date 命令 |
| 用 project 过滤 | 漏 Mac 上 claude-code session | 逐 session 枚举全 project |
| 只信一次 timeline | 输出被体积截断，漏中间记录 | 分页拉到覆盖 END 之后 + memory_sessions 逐个核对 |
| 几百 KB timeline 在上下文里肉眼过滤 | 漏记录、烧光输出预算 | 落盘后用 python 去重+过滤，只打印精简清单 |
| `memory_sessions` 结果直接排序 | 残缺记录缺 startedAt 字段导致 KeyError | 用 `.get()` 兜底过滤 |
| 整篇 write 覆盖飞书 | 输出超 length 上限被截、写入失败(2026-07-07 根因) | 只 insert 报告日一段到 divider 之后 |
| doc_token 用 … 省略 | 飞书返回 400 | 全程用完整 document_id |
| 只查 `blocks_added>0` 就报完成 | 写了 3 个 block 也"成功"，实际漏 8 个 session(2026-08-03) | 加 d2：`blocks_added ≥ bullet 数+1` 且与 session 数 N 交叉核对 |
| 报告日段已存在就跳过 | 沿用旧的残缺版本，不补全 | 比对本次枚举结果，更全就删旧段重插(旧内容先备份) |

## Red Flags — 停下重来

- "先 `memory_export` 看看有什么" → **这是 2026-08-03 漏掉 445 条记录的起点**。curated memory 不是当天活动，回 Step 1 走 timeline 枚举
- "昨天好像没什么事，就这几条" → 报出 N/M，`M<50` 就是取数漏了，不是当天真闲
- "手算一下 UTC 就行" → 跑命令
- "timeline 拉了一次够了" → 分页拉到覆盖 END 之后 + 逐 session 核对
- "输出太大，我挑几条看看" → 落盘 + python 过滤，别抽样
- "整篇重写更干净" → 只 insert 一段
- "应该写进去了" → 看返回的 success/blocks_added，且过 d2 完整性核对
- "报告日已经有内容了，跳过" → 比对完整度，缺就删旧段重插
