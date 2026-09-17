# herdr 通道操作细节

只在已经按 SKILL.md 的「什么时候才动 herdr」判定要用 herdr、且拿到人的当次授权之后读这份。

## 斜杠命令分两类

- **一发即完成**（有回执、不开 UI）：`/mcp reconnect <server>`、`/mcp enable|disable <server>`。已实测 + 二进制侧确认走 inline 分支，不弹 modal，server 名精确匹配
- **会开交互 UI**（需要方向键/Esc）：不带参数的 `/mcp`、`/model`、`/config` 之类。送这类等于**把别人的 session 停在一个弹窗里**，提交完必须由 `send-keys` 收场。不确定属哪类就别送 —— 先在自己 session 里敲一遍看它开不开 UI

## `agent prompt` 的送达判定

```bash
herdr agent prompt <pane> '/mcp reconnect chrome-devtools'   # 不带 --wait
herdr agent read <pane> --source recent-unwrapped --lines 40
```

`--wait` 要求提交后 5s 内观测到 `working`，而本地斜杠命令不启动模型回合，必然返回 `agent_prompt_stalled` —— **那是假失败，输入其实已经送到了**（`herdr agent prompt --help` 写明：`blocked` 才是「拒绝提交、不发送任何输入」，`stalled` 发生在提交被接受之后）。

**算成功**：`agent read` 里看到你那行原文出现在提示符上方**且带回执**。`/mcp reconnect` 的回执是 `Successfully reconnected to <server>`（实测）或 `Couldn't reconnect "<server>"`。只看到原文躺在输入框里没回执 = 没提交成功。agent 状态会一直是 `idle`，**别拿状态当判据**。

`agent_prompted` 返回成功只代表输入送到了，**不代表对方做了** —— 和 `SendMessage` 的 success 同性质。

## 用 `send-keys` 驱动对方的交互 UI

`agent prompt` 送的是一整行文本 + Enter；弹窗里没有「一行文本」可提交，只能送按键。

### 第 0 步：先判它到底卡没卡

人报「卡住了」经常是「一轮跑了 12 分钟屏幕不动」。往 `working` 的 session 送 `esc` = 打断它的回合，净损害。

```bash
herdr agent read w19:p1 --source recent-unwrapped --lines 40   # 采样一
sleep 25
herdr agent read w19:p1 --source recent-unwrapped --lines 40   # 采样二
```

比三样：**spinner 的 elapsed 时间、token 计数、正文内容**。任一在变 = 在干活，别动它。

两条白送的旁证：

- `agent_status` 是 `blocked` 才是真有框（字段名是 **`agent_status`**，取 `status` 会拿到 `None`）
- footer 印着 `⏵⏵ bypass permissions on` 的 session **根本不会弹权限确认框**，整类可能性一刀砍掉

**别拿 `state_change_seq` 当活性判据** —— 它数状态跃迁不数进度，实测一个明明在推进的 session 两次采样都是 `38`。

**长得像框但不是框的**（对着它们按 esc 就是误操作）：长时 bash 底下的 `(ctrl+b to run in background)`、`(esc to interrupt)`、plan-mode 的 footer。

### 确认真有框之后

```bash
herdr agent read w19:p1 --source recent-unwrapped --lines 40   # 1. 看清框在问什么
herdr agent send-keys w19:p1 esc                               # 2. 送一个键
herdr agent read w19:p1 --source recent-unwrapped --lines 40   # 3. 读回确认，再决定下一个键
```

**一次一个键，每次读回确认。** 别连发一串赌它的状态机 —— 你看不到中间态，猜错就在对方历史里留下一串误操作。

**算成功**（按键没有回显也没有回执，只能看这两条）：框从可见区消失，且 `agent_status` 离开 `blocked`。

- 键名：只有 `esc`（规范写法，`escape` 也收）在 `--help` 里有背书。**`ctrl+c` 和 enter / 方向键 / tab 一样属未验证** —— 三处 help（`agent send-keys` / `pane send-keys` / `herdr --help`）都搜不到它。验一次就等于真按一次
- 可以一条命令连发多个键（`send-keys <目标> <键> <键> ...`），但见上条
- **先校验全部键名再写任何字节**：无效键名返回 `{"error":{"code":"invalid_key"}}`，什么都不发。所以拿一个胡编的键名探测是安全的
- 目标接 agent 名或 pane 坐标，和 `agent prompt` 一样
- `herdr pane send-keys` 是裸终端版：不要求那个 pane 里跑着可识别的 agent，也不做 agent 状态检查。只在确实要裸终端控制时用

## 跨 agent 厂商（codex / gemini / cursor …）

**`SendMessage` 只能到 Claude Code。** 它靠 `~/.claude/sessions/<pid>.json` + `/tmp/cc-socks/<pid>.sock`，别家 agent 两样都不写，在 `ListAgents` 里根本不存在。

**herdr 在终端层面工作，所以跨厂商。** `agent prompt` / `send-keys` / `read` / `wait` 对它支持的 24 种都能用：

```
pi, claude, codex, gemini, cursor, devin, agy, cline, omp, mastracode,
opencode, copilot, kimi, kiro, droid, amp, grok, hermes, kilo, qodercli,
qwen, letta, maki, muse
```

`herdr agent list` 里的 `agent` 字段就是 kind。三条不对称：

| | `SendMessage`（仅 claude） | `herdr agent prompt`（跨厂商） |
|---|---|---|
| 回话 | 对方主动回，回复落进你的对话 | **没有收件箱**。送完就完，答案只在它屏幕上，自己 `agent read` 捞 / `agent wait` 等 |
| 斜杠命令 | 送不了 | 能送，但**语法各家不同** —— `/mcp` 是 Claude Code 的，别家有自己一套 |
| 寻址 | `tokens.sname` | 非 claude 的 pane **没有 sname**（实测 codex pane：`sname=None`），只能用 `pane_id`。`roster.py` 把它标成 `—(无)` |

**双向都实测通过**（claude ↔ codex，2026-09-17）：

```bash
herdr agent prompt w1C:p1 '...'                                  # claude → codex，codex 收到并回答
herdr agent read   w1C:p1 --source recent-unwrapped --lines 40
```

反向也成立 —— codex 那边自己跑 `herdr agent prompt <claude 的 pane> '...'`，接收方答了，exit 0。所以这不是「claude 单方面驱动别家」，任何在 herdr pane 里能跑 shell 的 agent 都能双向用。

codex 的记录里一样有 `agent_session`（`source: "herdr:codex"` + UUID），herdr 对它的跟踪不比 claude 少，**缺的只有 sname**。

### 多轮会话

跨厂商也保上下文 —— 第二轮不用重述第一轮的内容，对方从自己的会话历史里取。实测（claude → codex，2026-09-17）：送「记住数字 47 和词 pangolin，只回 ack」得 `ack`，再送「刚才那个数字乘以 3，加上那个词的首字母大写」得 `141 Pangolin`。

代价是每一轮都要自己读屏捞答案（没有收件箱），所以一轮 = `prompt` + `sleep` + `read`。

## 捞长输出

`agent read` 读的是**屏幕**，不是 stdout。长输出上有两个独立的坑，**混起来会让你把解析失败误判成传输丢数据**。

### 流程：哨兵先行，一次抓全

**先算容量**：`read` 单次最多给 1000 行（见坑二），历史会话也占额度。想要的行数 ≥ ~900 就直接用下面「超过 ~900 行」那套分批法，别先发再发现装不下 —— 那是十几分钟的沉没成本。

```bash
herdr agent prompt <pane> '...输出 N 行...最后一行只写 SENTINEL-DONE'
sleep <够长>
herdr agent read <pane> --source recent-unwrapped --lines 60 | tail -5   # 1. 只看哨兵到没到
herdr agent read <pane> --source recent-unwrapped --lines 1000 > /tmp/cap # 2. 到了再一次抓全
head -1 /tmp/cap                                                         # 3. 首行是横幅=没截断
```

1. **让对方自己标结束** —— 要求输出末尾一行哨兵。`agent_status` 回 `idle` 不足以判完（它写着写着也可能是 idle 采样点），哨兵是唯一可靠的完成信号
2. **确认哨兵后再一次性抓全，别分段抓拼** —— 两次 `read` 之间屏幕会滚，拼接处会缺行或重行
3. **程序化校验完整性**，别肉眼扫。编号型载荷用 `comm` 对空缺、`uniq -d` 对重复：

```bash
comm -13 <(cut -d' ' -f1 /tmp/cap | sort -u) <(seq -w 1 40)   # 缺失编号
cut -d' ' -f1 /tmp/cap | sort | uniq -d                        # 重复编号
```

### 坑一：`• ` bullet 只在回答首行

codex 的回答第一行前面挂 `• `，后续行只有缩进：

```
• 01 | a7c39e1f      ← 首行带 bullet
  02 | 3f8b04d2      ← 后续只有缩进
```

所以 `grep -E '^[[:space:]]*[0-9]{2}'` 会**恰好漏掉第 1 行**。实测踩过：40 行抓到 39，缺的是 `01`，看着像「首行滚出缓冲」，其实是 regex 太挑剔。剥前缀再匹配：

```bash
herdr agent read <pane> --source recent-unwrapped --lines 200 \
  | sed -E 's/^[[:space:]]*(•[[:space:]]*)?//' \
  | grep -E '^[0-9]{2} \| [0-9a-f]{8}$'
```

**判别式**：怀疑丢行时，先 `grep -n` 去原始输出里找那一行在不在。在 = 解析问题；真不在 = 缓冲问题。别跳过这步直接下「传输不完整」的结论。

### 坑二：`--lines` 硬上限 1000 行，且没有翻页

**`--lines` 在 1000 处静默夹住。** 实测 `--lines 1001` / `1500` / `10000` 返回的内容和 `--lines 1000` 逐字一样。`--source` 换成 `recent` 也一样；`visible` / `detection` 更少，只给当前可见区（~58 行）。

**这是 herdr 源码里的硬编码**（v0.9.1 = 2026-09-16 的 latest，`master` 同）—— `src/app/api_helpers.rs:117`：

```rust
let line_limit = lines.map(|lines| lines.min(1000) as usize);
let recent_lines = line_limit.unwrap_or(80);   // ← 不给 --lines 时的默认 80 行
```

裸字面量，**无常量名、无配置项、clap 层无 range validator**，所以超限不报错只静默夹住。绕不过的三条理由：

- `agent read` 与 `pane read` **共用**这个函数（`app/api/agents.rs:231`、`app/api/panes.rs:1507`）→ 换命令没用
- 另外三处同样的 `min(1000)`：`server/headless.rs:2737,2774`、`server/alt_screen_read.rs:100` → headless 和 alt-screen 一致
- **API schema 里根本没有翻页字段**：`AgentReadParams` 只有 `target`/`source`/`lines`/`format`/`strip_ansi`。不是 CLI 没暴露，是协议层没这个概念

**数据没丢，是 API 不吐** —— `scrollback_limit_bytes` 默认 10MB（2000 行 ≈ 26KB，远没到），内容还在对方 pane 的 scrollback 里；引擎层也有能力全取（`pane.rs:4301` 用 `recent_unwrapped_text_snapshot(usize::MAX)` 断言取到整 2000 行），但那种无限调用**只出现在 `#[tokio::test]` 里**，外部触发不到。所以别浪费时间找「另一个能拿全的命令」，没有。

所以 `--lines` 不是「宁多勿少」，是**只在总量 < 1000 时才有余量可给**：

- 载荷前面还压着整段历史会话，都算在这 1000 行里。实测 40 行载荷落在第 78–118 行、500 行载荷落在第 130–629 行
- 实测 2000 行载荷：`--lines 4000` 只拿到 `1007`–`2000`，**0001–1006 永久丢失**

**判别式 —— 看返回的第一行**：

| 首行长什么样 | 含义 |
|---|---|
| 那家 agent 的启动横幅（codex 是 `╭──` + `OpenAI Codex (vX.Y.Z)`） | 够到 pane 开机那一刻，**没截断** |
| **半截正文**（实测 `1007 \| 28f9c4b5`） | **撞墙了**，前面的内容已经没了 |

### 超过 ~900 行：让对方分批，别指望自己拼

上面「流程」那节的「一次性抓全、别分段抓拼」只在**总量 < 1000 行**时成立 —— 那说的是「同一批输出不要分两次 `read` 去拼」（两次 read 之间屏幕会滚，拼接处缺行）。总量真的超了，唯一的出路在**发送侧**：

```bash
herdr agent prompt <pane> '输出第 1 批：0001–0600 行，末尾一行 SENTINEL-B1'
# 确认 SENTINEL-B1 → 立刻抓走这批
herdr agent prompt <pane> '继续第 2 批：0601–1200，末尾一行 SENTINEL-B2'
# 确认 SENTINEL-B2 → 立刻抓走
```

每批 ≤600 行（给历史留出余量），**每批抓完再让它发下一批**。批号写进哨兵，这样能确认自己抓的是哪一批。

### 实测容量

| 载荷 | 完整度 | 对方生成耗时 | 载荷在原始输出的位置 |
|---|---|---|---|
| 40 行 | 40/40 | ~25s | 78–118 |
| 500 行 | 500/500 | 147s（~3.4 行/s） | 130–629 |
| 2000 行 | **994/2000** ❌ | ~13min | 撞 1000 行墙，0001–1006 丢失 |

通道本身在容量内是可靠的：500 行 × 13 字符零丢失，编号无缺无重、hex 全唯一。2000 行的失败**不是传输错误，是 read 窗口装不下**——对方屏幕上确实写全了 2000 行。

**`sleep` 按对方的生成速率估，不是按你的耐心估。** 500 行等了 147s（38s 时才 157 行）。2000 行更反直觉：**前 4 分钟屏幕上一行都没有**（xhigh reasoning 阶段），8m43s 才到 1080 行，全程 ~13 分钟。「几分钟没动静」不等于卡住 —— 按 SKILL.md 的活性判据两次采样比 spinner elapsed，别急着送 esc。

设计载荷时就留好校验钩子（连续编号 + 固定宽度字段），比事后猜哪里断了便宜得多。
