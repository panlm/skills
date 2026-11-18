# hc（herdr-core）通道细节

权威说明是 `hc --skill`、`hc <命令> --help` 和 `herdr-app --skill`；本文件只记跨 session 发消息时要用到的那几条，以及本机实测。版本以 `hc --version` 为准，有出入时以 `--help` 为准。

## 地址

- terminal 地址：`t7`、terminal 的名字，或者 `machine/t7`（远端机器，见 `hc machine ls`）。
- 你自己：`$HC_TERMINAL_ID`。
- `herdr-app ls` 里的 `pane`（`p…` 长串）只给 `herdr-app do pane.*` 用，`hc` 命令不认它。

## 送话：`hc send`

```bash
hc send <t> '<text>'              # 粘贴进去再按 Enter
hc send --wait <t> '<text>'       # 再等这次 send 开始的那一轮结束
hc send --if idle <t> '<text>'    # 只在它正好 idle 时才打字
```

- 对方 `blocked`（停在对话框上）时不打字；`--force` 会照打，可能替人回答那个对话框。**不要用 `--force`**，先 `hc read <t>` 看清它卡在什么上，告诉人。
- 会等人没打完的草稿，最长 60 秒（`draft_wait` 可配）。
- `--wait` 的结果：
  - `reason: timeout`（默认 180 秒）：到点报到，不是失败，再等一次；
  - `not_started`：它还没开始这一轮，先读屏再决定；
  - `reason: message`：有消息到了你这里，它会作为你的下一条输入出现，不是要 `hc read` 去取的输出。
- 不要盲目重发：失败的 send 也可能已经送到了，先读。
- 你用 `hc send` 发给别人的话，到那边会被包成 `<hc from="<你的 terminal> …" reach="hc send <你的 terminal> when done or stuck">…</hc>`。对方回复会作为你的下一条输入进来。
- 目标是 Claude Code 时，能用 `SendMessage` 就别用 `hc send`：那边有收件箱、会回你。

## 按键：`hc keys`

```bash
hc keys <t> esc
hc keys <t> down enter
hc keys <t> ctrl+c
```

键名：`enter`、`esc`、`tab`、`up`、`down`、`ctrl+c`、`alt+x`、`f5`、单个字母……

- **没有任何联锁**，能替人在权限确认框上按同意。只在人明确要求收拾某个弹窗时用，一次一个键，每按一次读一次屏确认。

## 停掉当前一轮：`hc interrupt`

`hc interrupt <t>`：按下它的停止键，并报告发生了什么。只停这一轮，不杀进程。

## 读屏：`hc read`

```bash
hc read <t>                  # 只读可见屏幕（--lines 默认 0）
hc read --lines 100 <t>      # 屏幕上方再加 100 行历史
```

- 对方是 `working`、`blocked` 或 `error` 时，历史读取只立刻返回当前屏幕，标为不完整，`why` 写着那个状态，不会往它的屏幕发滚动输入。
- 读历史可能会把全屏程序滚一下再还原。

## 等：`hc wait`

```bash
hc wait <t>                    # 等它不再 working（普通程序没有 agent 状态，通常等到它退出）
hc wait <t> --output 'READY'   # 等它打印出 READY
```

**别用 sleep 或轮询去等 hc 管的东西。** 返回 `reason: timeout` 时再等一次。

## 看状态（不打扰对方）

```bash
hc ls --json          # 每个 terminal 的 address、agent、cwd、status、turn、where
hc get <t> --json     # 一个 terminal：foreground（argv、pid）、status、turn、labels（herdr.space、herdr.tab）
herdr-app ls          # 窗口里的 space → tab → terminal（顺序就是屏幕顺序）
herdr-app status      # 当前 space、tab、focused_pane、agent（人在看哪个）
```

- `status` 会出现 `idle`、`working`、`done`、`blocked`、`error`，也可能是空的（没有 agent 状态的普通程序）。
- 判断对方「接手了没有」：`status` 从 `idle` 变成 `working`、`turn` 往上走。

## 远端机器

```bash
hc machine ls --json                     # 挂了哪些机器、是不是 connected
hc exec --on <机器> hc ls --json         # 那台机器上的 terminal（不开 terminal，只读）
hc read <机器>/t3                        # 之后的命令都用带机器名的完整地址
hc send --wait <机器>/t3 '<text>'
```

- `hc ls` 只列本机的 terminal，`machines` 字段只给机器名和状态，所以要用 `hc exec --on` 才看得到远端的 terminal。
- 机器状态是 `needs_login` 时，`hc machine login <名字>` 要人自己在终端里跑。
- 远端的 Claude Code 不在本机 `ListAgents` 里，只能走 `hc send`，🔴 的授权门槛照旧，而且这是在另一台主机上替人打字。

## 本机实测（2026-11-18）

- herdr-app 0.1.x + herdr-core，窗口的 layout 是 transformers。
- 同一个 tab「~ / api」里有两个 terminal：`t5`（自己）和 `t6`。`herdr-app ls` 的先后和人说的「左、右」一致。
- `t6` 的 foreground 是一个 `claude` 包装脚本，真正登记在 `~/.claude/sessions/` 里的是它下面第二层的 claude 进程，name 是 `alice-90`。只往下一层找会漏掉，roster 按整棵子孙树找。
- 旧 herdr 同时还在跑（`herdr agent list` 能列出 `w19:p1`、`w20:p3`），两套后端的 session 互不重叠。
- 两套后端挂的是同一台远端机器：hc 那边 `connected`，远端 hc 0.1.21；旧 herdr 那边 endpoint 为 `enabled`。两边远端当时都是空的（`hc exec --on vps hc ls --json` 的 terminals 是 `[]`，`ssh vps 'herdr agent list'` 的 agents 是 `[]`）。
