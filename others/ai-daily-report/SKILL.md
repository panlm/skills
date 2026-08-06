---
name: ai-daily-report
description: Use when generating panlm's daily AI work report — the 00:30 cron task that summarizes the previous day's (Asia/Shanghai) agent activity from agentmemory and appends it to the monthly Feishu doc 工作日报-YYYYMM. Triggers on "AI日报", "生成日报", "工作日报", daily report cron.
---

# AI 每日工作日报

## Overview

定时任务：每天北京时间 00:30 运行，为 panlm 生成【前一天(Asia/Shanghai)整天】的 AI 工作日报。因为在 00:30 跑，报告日 = 昨天。

**取数、闸门、核对、写飞书全部由 `scripts/` 下的三个 python 脚本完成，不要手工做这些步骤。** 你的工作只有一件：**把脚本列出的记录写成中文 bullet**。

脚本化的原因：这个 skill 在三种环境跑(Mac claude / openclaw 调 claude -p / cron)，散文纪律的执行率随平台和模型状态漂移 —— 2026-08-03 漏 445 条、2026-08-05 漏 7 条、openclaw 版持续比本地版残缺，三次都是"文字要求被跳过"。脚本直连 agentmemory REST、闸门用退出码强制，跨平台结果一致。

```
scripts/fetch_activity.py   算窗口 + 分页取数 + dedup + facts 判空 + 时段分布 + 完整性闸门
scripts/check_coverage.py   逐条覆盖核对(每条实质记录都进了 bullet 吗) + 排除性结论查证
scripts/publish_feishu.py   备份旧段 + 删旧 + 倒序插入 + 回读校验
```

## When to Use

- 00:30 定时日报任务触发时
- panlm 要求"生成 AI 日报 / 工作日报"时
- 需要汇总某一天所有 agent(claude-code/opencode/codex 等)的活动时

## Step 0: 准备凭证

脚本只从环境变量读凭证，**仓库里不含任何 secret，也不要往脚本里写**。

| 变量 | 用途 | 取法 |
|---|---|---|
| `AGENTMEMORY_URL` | agentmemory 服务地址 | agentmemory 的本地 env 文件(见下) |
| `AGENTMEMORY_SECRET` | REST Bearer token | 同上 |
| `FEISHU_USER_TOKEN` | 飞书 docx user_access_token | 刷新脚本 + lark-mcp storageManager |
| `FEISHU_DOC_<YYYYMM>` | 当月日报文档的 document_id | 见下「文档 ID」 |

**agentmemory 两个变量**：agentmemory 的运行时配置目录下有个 env 文件(各机器位置不同，Mac 和 openclaw/EC2 实例各看自己的安装目录)。载入当前 shell：

```bash
set -a; . <agentmemory 配置目录>/.env; set +a
```

找不到那个文件就 `grep -rl AGENTMEMORY_SECRET` 扫 shell rc 和 agentmemory 配置目录。**不要把值 echo 出来。**

**飞书 token**：user_access_token 只有 2 小时有效期。先跑本机的 lark refresh 脚本刷新，再从 lark-mcp 的 storage 读出来 export：

```bash
node <lark 工具目录>/lark_refresh.mjs        # refresh_token 7 天有效，超期要重走 OAuth
export FEISHU_USER_TOKEN=$(node -e "
const {createRequire}=require('module');
const r=createRequire('<lark-mcp 安装路径>/node_modules/@larksuiteoapi/lark-mcp/');
const {storageManager}=r('<同上>/dist/auth/utils/storage-manager.js');
storageManager.loadStorageData().then(d=>process.stdout.write(Object.values(d.tokens)[0].token));")
```

刷完 **MCP 进程内存里还是旧 token**，所以 `lark-mcp` 工具仍会报 `Current user_access_token is invalid or expired` —— 不要反复重试 MCP，直接用上面的 REST 路径(`publish_feishu.py` 走的就是 REST)。

**文档 ID**：本 skill 是公开仓库，**不在这里写死任何 document_id**。按月存进本机环境变量，例如 `FEISHU_DOC_202608`，和上面的凭证放同一个 env 文件里(该文件已被 `.gitignore` 挡住)：

```bash
python3 scripts/publish_feishu.py --doc "$FEISHU_DOC_202608" ...
```

首次为某个月准备时，用飞书搜索按名字找 `工作日报-YYYYMM` 拿到 id 再存进去。当前 token scope **只有 docx 没有 drive**，`/drive/v1/files` 和文档搜索会报 99991679 —— 补 `drive:drive:readonly` scope 才能搜，或者从浏览器打开文档直接从 URL 里抄 id。

当月文档不存在时新建 `工作日报-YYYYMM`，首篇写 `# 工作日报 · YYYY年M月` + `---` 分割线 + 报告日段落，然后把新 id 存进环境变量。

`lark-cli-mcp-agentcore` 那条路要走 AgentCore Identity 浏览器授权，无头环境不可用，cron 里不要指望它。

## Step 1: 取数(跑脚本，不要手工枚举)

```bash
python3 scripts/fetch_activity.py --json /tmp/act.json
# 指定报告日: --date 2026-08-05
```

脚本输出窗口、N/M 计数、facts 判空、北京时段分布，以及**窗口内每条 observation 的清单**(带 `facts=` 条数)。

- **exit 0** → 闸门通过，往下走。
- **exit 2** → 闸门未通过，stderr 说明原因。**不准往下写日报**，按提示回去多拉几页或排查。
- **exit 3** → 配置/网络错误，先修凭证。

清单里 `facts>=1` 的每一条**都必须写进某条 bullet**。前面加 `×` 的是 `facts==0` 的真空心跳，可以合并到末条或忽略。

**不要用 `memory_export` / `recall` / `smart_search` 当取数源** —— 它们返回 curated memory(个位数条目)，不是当天原始活动。这两个只能用来补细节：`memory_lesson_recall` 查报告日新增经验、`memory_recall` 查某件事的上下文。

**不要用 `observationCount` 判断会话是否为空。** openclaw 的 agent_end hook 每 session 只写 1 条 observation，但那 1 条的 `facts` 里有 7-13 条事实，是完整对话摘要。脚本已经按 facts 判定并打好标记，照着清单走就行。

## Step 2: 写成中文日报(这一步是你的判断，脚本做不了)

写到一个 markdown 文件(如 `/tmp/daily-YYYY-MM-DD.md`)。

- 只用一个日期标题 `## YYYY-MM-DD 周X`(日期和周几都用脚本输出的，别手推)，**不要任何子标题**。
- 标题下直接 bullet 列表，每件事一条 bullet。
- 每条 bullet 固定两部分，按此顺序：**(1)** 一句加粗总结句放在开头；**(2)** 紧跟 2-3 句细节 —— 做了什么、过程/踩的坑、产出、文件保存路径。
  - 路径标清哪台机器(Mac `~/xxx`、EC2、basic-memory 哪个项目)。**查不到路径就不写，不要编造。**
  - 形状示例：

    ```markdown
    - **给 ai-daily-report skill 换了 bullet 输出格式。** 原来每条 3-5 句纯细节，读起来抓不到重点。改成开头一句加粗总结 + 2-3 句细节。改在 Mac ~/Documents/git/panlm-skills/others/ai-daily-report/SKILL.md。
    ```

- 不同项目/不同任务(如两个不同渗透测试、不同目标)**分开成不同 bullet**，不要糅成一句。
- 同一件事的连续步骤(如"读文件→改配置→提交")**合并成一条 bullet**，Step 3 的映射允许多条 observation 指向同一条。
- 不要"负责 Agent"、"时间段"字段。零碎小事合并成最后一条 bullet。不要单独的"统计""总结"段落。
- 细节从 observation 的 `facts` / `narrative` / `files` 里取。`facts` 多的记录(10+)通常是一整场调研或排障，值得单独成条。

### 排除性结论要当心

写"其余为空会话/心跳/无实质内容"「已计入前一天日报」这类句子前，先看脚本报的 `facts==0` 条数。**这个数是 0，该结论就是假的** —— 它把"没查到"写成了"本来没有"，是漏数最常见的掩盖方式。Step 3 会自动拦这种句子。

## Step 3: 覆盖核对(硬闸门，过不了不准写飞书)

写一个映射文件，把每条实质 observation 归到 bullet 序号：

```json
{"2026-08-05T08:48:46": 6, "2026-08-05T09:56:33": 7, "2026-08-05T10:01:07": 7}
```

key 用脚本清单里的 UTC timestamp 前 19 字符，value 是 bullet 序号(1-based)。多条归同一条是允许的。

```bash
python3 scripts/check_coverage.py \
  --activity /tmp/act.json --report /tmp/daily-YYYY-MM-DD.md --map /tmp/map.json \
  && touch /tmp/cov.ok
```

脚本会拦四类问题：
1. 有 `facts>=1` 的 observation 没归属到任何 bullet(**这就是 08-05 漏 7 条的那类**)；
2. 有 bullet 没有任何 observation 归属 —— 内容无出处，可能是编的；
3. 映射指向不存在的 bullet 序号，或 timestamp 不在本次取数结果里；
4. 排除性结论缺证据，或 `facts==0` 条数为 0 时还写"空会话"。

**exit 2 就是不准写飞书。** 回 Step 2 补 bullet，别改映射去糊弄 —— 映射对不上取数结果脚本也会报。

`/tmp/cov.ok` 这个标记文件是 Step 4 的前置，`check_coverage.py` 不通过就不会创建，`publish_feishu.py` 读不到它会直接拒绝执行。

## Step 4: 写入飞书

```bash
python3 scripts/publish_feishu.py \
  --report /tmp/daily-YYYY-MM-DD.md --doc "$FEISHU_DOC_202608" \
  --coverage-ok /tmp/cov.ok --backup /tmp/feishu-old-section.md
```

`--doc` 用 Step 0 存好的 `FEISHU_DOC_<YYYYMM>` 环境变量(YM 取脚本输出的报告日年月)，**不要把 id 明文写进命令、日报或任何提交物**。

脚本自动做：定位分割线 → 找同日旧段并备份 → 删旧段 → 在分割线后插入(实现倒序) → 回读校验标题和 bullet 条数。

- 先跑一次 `--dry-run` 看它打算删哪些、插到哪，确认无误再实跑。
- **exit 4** = 写入后回读校验失败，内容可能不完整，人工检查文档。
- doc_token 全程用完整 `document_id`，**不要用 … 省略**(脚本会拒绝，但别在别处这么写)。
- 只 insert 报告日一段，**绝不整篇 write 覆盖** —— 文档越来越长，整篇重写会撞输出上限被截断，导致写入 tool_use 根本没发出(2026-07-07 事故根因)。脚本只做 insert。

## Step 5: 完成后简短汇报

用正常中文完整句：报告日几个主要任务、飞书文档链接。

链接**只在给 panlm 的对话回复里给**(他要点开看)。**不要把它写进任何会提交进仓库的文件** —— 文档 URL 里就带着 document_id。

如果 Step 1 的 N/M 偏低但闸门放行了(脚本会打印"首页只返回 R 条"的证据)，汇报里**必须写明该证据 + 时段分布**，不要只说一句"当天活动少"。

## Common Mistakes

脚本已经强制的机械约束不再列(窗口计算、分页、dedup、facts 判空、覆盖核对、doc_token 完整性、只 insert 不覆盖)。剩下这些是脚本管不到、靠你判断的：

| 坑 | 后果 | 正确做法 |
|----|------|---------|
| 跳过脚本手工枚举 | 回到 08-03/08-05 的漏数老路，且三平台结果不一致 | 跑 `fetch_activity.py`，别手工调 timeline/sessions |
| 闸门 exit 2 了还往下写 | 拿残缺数据交差 | exit 2 = 停，按 stderr 提示排查 |
| 改映射去迎合 bullet | 映射对不上取数，脚本一样报错 | 回 Step 2 补 bullet |
| 编造文件路径 | 日报里的路径点不开 | `files` 字段里查得到才写 |
| 把不同项目糅成一句 | 读的人分不清是几件事 | 不同任务分开成条 |
| 写"空会话"却没看 facts==0 条数 | 把"没查到"写成"本来没有" | 先看脚本报的数，是 0 就删掉该结论 |
| `blocks_added>0` 就当写入成功 | 写了几个 block 也"成功" | 看 `publish_feishu.py` 的回读校验结果 |

## Red Flags — 停下重来

- "先 `memory_export` 看看有什么" → curated memory 不是当天活动，跑 `fetch_activity.py`
- "这几个 session 只有 1 条 observation，是心跳" → 看 facts 不看 count，脚本已标好
- "其余为空会话与心跳类记录，无实质内容" → 先看 `facts==0` 的条数，是 0 这句就是错的
- "闸门报了 exit 2，但我觉得当天确实活动少" → 闸门要的是证据不是感觉
- "脚本太麻烦，我手工枚举一遍更快" → 手工版已经漏过两次，且 openclaw 上更差
- "覆盖核对差几条无所谓，先发了" → 差的那几条就是日报的价值所在
- "应该写进去了" → 看 `publish_feishu.py` 的回读校验
