# 第二轮真实运行反馈：设计与裁定

**日期：** 2026-09-04
**基点：** `8b55f0d`（master）
**分支：** `skill-run2-findings`

## 来源

两个 agent runtime 用同一份 skill（27 个源文件逐字节相同）跑了同一个账号的
`ap-northeast-1` + `us-west-2`，30 天窗口，UTC+8，两个 `sizing_profile` 各一份报告，
`allow_stop_recommendations=no`。各自写了改进建议；另有第三方对两边**原始数据**的独立比对。

原始报告在仓库外（含账号 ID 与资源 ID，不得入库）。本文件是脱敏后的结论，
资源一律写成 `<msk-cluster>` / `<rds-nonburst>` 这类占位符。

## 上一轮已验证成功（本轮不得改坏）

第三方比对给出的关键事实：

| 项 | 结果 |
|---|---|
| skill 源文件 | 27/27 逐字节一致 |
| inventory | 两 region 各 16/16 一致 |
| CloudWatch 时间序列 | 140/140 与 348/348 逐点一致 |
| 价目 / offerings / specs / 分类映射 | 一致 |
| **东京 conservative 路线一** | 两边同为 **$407.02**，差额 $0.00 |
| **东京 aggressive 路线一** | 两边同为 **$496.05**，差额 $0.00 |

**判断核心的跨 runtime 一致性已经达成。** 这是上一轮 C4（按 `service` 分派）、
C5（`sizing_profile` 必填）、`Stat=Sum` 三项修复的直接结果。

美西残留的 $86.51 差额不是判据分歧，拆开是：一边整段漏报了 EKS（$70.08，
原始 inventory 里集群与节点都在），另一边把一个空序列 ALB 当可删除算进了合计（$16.43）。
两者都是本轮要修的规范缺口，不是判据缺陷。

## 裁定（Rulings）

动手前已核实的判断，避免执行时重新讨论。

### R1 ElastiCache 取价：两个陷阱独立存在，原记录是对的

一份报告主张 `cli-recipes.md` 把 `$0.054` 归因成 `ExtendedSupportYr1_Yr2` 是把
Valkey（$0.0544）误认了。**实测推翻这个主张**（`pricing:GetProducts`，
`us-west-2`，`cache.t3.medium`）：

```
$0.0540  USW2-ExtendedSupportYr1_Yr2-NodeUsage:cache.t3.medium  Redis      vcpu=null  mem=null
$0.1090  USW2-ExtendedSupportYr3-NodeUsage:cache.t3.medium      Redis      vcpu=null  mem=null
$0.0680  USW2-NodeUsage:cache.t3.medium                         Redis      vcpu=2     3.09 GiB
$0.0680  USW2-NodeUsage:cache.t3.medium                         Memcached  vcpu=2     3.09 GiB
$0.0544  USW2-NodeUsage:cache.t3.medium                         Valkey     vcpu=2     3.09 GiB
```

两者是不同的行、不同的问题：

- extended support 档确实是 $0.0540，`vcpu`/`memory` 为 `null`。现有过滤式
  `^[A-Z0-9]+-NodeUsage:` 已经挡住它——`ExtendedSupportYr1_Yr2` 含小写与下划线，
  匹配不上 `[A-Z0-9]+`。**该记录准确，不得删改。**
- Valkey 与 Redis / Memcached **共用同一个 usagetype**，三行都能过现有过滤、
  `vcpu`/`memory` 都有值。`unique_by(.t)` 随机取 ⇒ 对 Redis 集群低估 20%。
  **这是全新的、未记录过的陷阱。**

裁定：**新增** `cacheEngine` / `operation` 消歧，**保留**原 extended support 说明。

### R2 内存降幅上限：加，且承认它会移动回归基线

`core.py:213` 只对 vCPU 设降幅地板，`thresholds.json` 无内存对应键。
后果实测：一台 4 GiB 的 T 系列实例内存 p95 5.175% ⇒ 建议降到 1 GiB
（**4 倍**），`confidence=high`，两个 profile 都一样；而 conservative 的 vCPU
最多才降 2 倍。这个不对称在任何地方都没写出来。

裁定：加 `max_mem_reduction_ratio`，取值与 `max_reduction_ratio` 相同
（aggressive 3 / conservative 2）。理由不是新的：现有 vCPU 地板的依据是
「目标利用率管不了窗口外的周期与发布间隔内的尖峰」，**这个理由与指标种类无关**，
对内存同样成立。而且 CloudWatch agent 的 `mem_used_percent` 是
`mem_used / mem_total`、**不含可回收的 page cache**，会把内存 p95 系统性压低，
所以内存比 vCPU 更需要这道地板。

**此项会改变回归基线 $401.51 / $312.48。** 必须重算并记录新值与成因，
**不得为了让断言通过而调数字**。

### R3 托管采样守卫放 `dispatch()`，不放三个 evaluator

`dispatch()`（`core.py:547`）已存在且对未知 `service` 抛错，是唯一的托管入口。
守卫放这里只有一处，放三个函数里会有三份可漂移的副本。

### R4 `allow_stop_recommendations=no` 时 `stop_candidate` 留空

三态 `true`/`false`/`null` 没有一个能表达「因为关了所以没评估」。
实测两个 agent 给出两种不同的契约违反：一个填了违反枚举的字符串
（并把这一列排除在自己的自检之外），一个直接删列（40 列变 39 列）。

裁定：该列**留空**，报告正文写一句「桶 C 未评估（`allow_stop_recommendations=no`）」。
不加第四个枚举值，不把 `allow_stop_recommendations` 传进 `core.py`——
`core.py` 只做判断，「要不要看」是报告层的决定。

### R5 桶 B 合计口径：加第三条路线

命中 `idle` 的行，其 `nb_save_mo` 装的是「若须保持运行改为降配」的金额，
不是删除可省。实测最极端一行：删除省 $1,369.48，降配省 $98.55，**差 13.9 倍**，
而现有两条路线都只对 `nb_save_mo` 求和 ⇒ 该 region 桶 B 的 93% 不出现在报告里。

裁定：`report-template.md` 加第三条口径 `桶 B 合计 = Σ cur_cost_mo over bucket=="idle"`，
并明写桶互斥故桶 A 与桶 B 可相加、idle 行的 `nb_save_mo` 是替代方案不进合计。

### R6 快照不判年龄

`report-template.md` 的分节写了「超龄快照」，但 `thresholds.json` 无年龄阈值、
`core.py` 无快照判据。任何 agent 要么自己拍一个天数（违反阈值单一真值源），要么跳过。

裁定：改成「快照清单（仅事实陈述）」，并在 `thresholds.md` 写明本版本不判快照年龄
及原因——快照该不该删取决于 RPO 与合规要求，这个 skill 拿不到那些信息。
**不加阈值。**

### R7 分母范围写死为「全表求和」

裁定：`分母 = Σ cur_cost_mo`，且**范围内每个资源恰好贡献一行**，
无建议的用 `verdict=已合理配置` / `bucket=excluded` 照填 `cur_cost_mo`。
这样分母自动完整、不漏项。同时要求报告显式列出未包含项
（数据传输、NAT 数据处理费、ALB LCU、RDS/MSK 存储与备份、CloudWatch、
未关联公有 IPv4）。

聚合行（EKS 节点池这类一条建议作用于一组资源）**只带节省额、不带成本**，
成本记在成员行上，否则分母把成员算两遍。

## 范围

### 判据缺陷（会静默产出错误建议）

| # | 缺陷 | 实测证据 |
|---|---|---|
| J1 | 托管三判据无采样量守卫 | `<msk-cluster>` 仅 31 小时历史、biz-hours **14 点**（门限 168），`core.py` 照样输出 `downsize-candidate`。**两个 agent 都不得不在采集侧自己补这道守卫** |
| J2 | 非 burstable RDS 降配路径不可达 | `eval_rds` 无条件卡 `surplus_credits is None`，而 `db.m5.*` / `db.r6g.*` 结构性不发布信用指标 ⇒ 恒为 `metric-missing`。EC2 侧用 `spec["burst"]` 做了这个区分，RDS 侧漏了 |
| J3 | 已是最小规格仍输出 `downsize-candidate` | `kafka.t3.small` 是两 region 最便宜的 broker 机型（次便宜的贵 4.5 倍）⇒ **MSK 降配路径在任何账号都到不了**；报告却让客户提升 `EnhancedMonitoring` 再等一个窗口，做完也不会有建议 |
| J4 | 内存无降幅上限 | 见 R2 |
| J5 | `insufficient-data` 行没有成本字段 | 该分支在 `cur_cost_mo` 赋值之前就 return，实测漏掉两台合计 $286.67/mo，比例虚高 27.7% vs 23.2% |

### 契约与口径缺口（不同 agent 会各自发明）

| # | 缺口 |
|---|---|
| C1 | 桶 B 合计口径未定义（R5） |
| C2 | 分母范围未定义（R7） |
| C3 | `stop_candidate` 在 `allow_stop=no` 时无合法值（R4） |
| C4 | 托管服务节省额结构性不进合计——实测某 region 的 ElastiCache 候选合计 $148.92，占该 region 路线一的 9–13%，头条数字里没有 |
| C5 | 多 profile 输出互相覆盖：作用域目录无 profile 维度 |
| C6 | 聚合行 vs 成员行双计数无规则（R7 后半） |
| C7 | 采集侧自建行（EBS / NAT / ALB / EIP / 快照 / EKS）的字段填法无规范 |
| C8 | `nonburst` / `burst` 从规格对象到 CSV 单列的渲染规则未写 |
| C9 | `window_profile` 枚举无「全窗口」取值，但 VPC 闲置判据用的就是全窗口 |
| C10 | 资源级互斥漏 `state=available`：未挂载卷会同时出删除行与 `gp2→gp3` 行，两个动作互斥却都进合计 |

### 采集配方缺陷（照文档逐字执行会失败）

| # | 缺陷 |
|---|---|
| P1 | `cli-recipes.md §2.2` 的内存与磁盘模板未传 `--arg idprefix`，而 `mdq-dims.jq` 裸引用 `$idprefix` ⇒ **jq 编译期错误**。同一文件的参数表还把它写成「默认 "d"」，实现里没有任何默认值 |
| P2 | `§7.3 ①` 断言 `solver-in.json` 行数等于 `ec2.json` 行数，与 `§4` 要求「EKS 节点必须与独立 EC2 分开处理」冲突 ⇒ **照文档跑必然 FAIL**；`§1.1` 标题写「三个派生清单」，实际需要四个 |
| P3 | ALB 取价加了 `operation` 限定后仍返回三条 usagetype，`-TS-` 档只有正确价的 **26%**；`§5.1` 的示例命令依赖一个来源未定义的 `${P}` |
| P4 | NAT 的 usagetype 形态逐 region 不同（`APN1-NatGateway-Hours` vs `USW2-RegionalNatGateway-Hours`），不得用它反推 region 价目前缀——拼出的串不存在时 pricing API **返回空且不报错** |
| P5 | ElastiCache 取价缺 `cacheEngine` 消歧（R1） |
| P6 | ALB 闲置判据只看 `RequestCount`，实测出现第三种情形：`RequestCount` 序列**不存在**而 `ActiveConnectionCount` max 非零 ⇒ 实际活跃。零 HTTP 请求 ≠ 零连接 |
| P7 | `list-metrics` 只回最近 2 周有数据的指标，`get-metric-data` 覆盖整窗口。实测某 ALB `list-metrics` 回 0 而 `get-metric-data` 有 500 个非零点。`§2.0 ④` 把 `list-metrics` 当交叉核对手段，必须补这条时间窗差异 |

> **⚠️ 2026-09-04 补注：上表三条的量与机制在执行中被重测推翻，出厂文件已按实测值改，本表按"当时的认识"原样保留。**
>
> 上面这些描述来自两份源报告(它们本身也是 agent 的测量)。执行任务时重测,三处不符:
>
> - **P3** —— `-TS-` 档不是"正确价的 26%",实测是 **22.2%–28.0%(3.6–4.5 倍)**。
> - **P7** —— 那台 ALB 不是 500 个非零点,实测是 **250 个**。
> - **P4 的机制说错了,不只是数字。** 本表说"NAT 的 usagetype 形态逐 region 不同",
>   实测**两种形态在每个查过的 region 都存在**、靠 `operation` 区分、价格相同。
>   真正不可反推的是 **region 前缀本身**:`eu-west-1` → `EU-`、`ca-central-1` → `CAN1-`,
>   而 `us-east-1` 在同一 region 内同时有裸前缀和 `USE1-`。结论(不得反推前缀)不变,
>   理由变了。
>
> 现行值见 `aws-rightsizing/references/cli-recipes.md` 与 `SKILL.md`——三处纠正
> 各自落在多个出厂位置且已核一致。**不要从本表取数当现行值。**
>
> 保留而不改写的理由:本文件是设计记录,它的价值在于记下"当时依据什么做了决定"。
> 改掉论证等于抹掉记录;但一个会被当成现行值引用的数字必须带撤回标记——
> 本项目已经吃过一次亏,一个作废数字被人从过期文档里重新推导出来当现行值用。

### 文档卫生

| # | 缺陷 |
|---|---|
| D1 | `mdq-msk.jq` 头部注释禁止「由 brokers 计数生成 1..N」，实现做的正是这件事（`range(1; brokers+1)`）。两次运行的 broker ID 恰好连续所以没暴露；ID 不连续时会静默取空 |
| D2 | 「超龄快照」列进报告分节但无阈值（R6） |
| D3 | 硬编码的机型数写成断言式「实测机型数」，实测已漂移（某 region 1154 → 1198）。应标为参考值，并区分哪些数字会漂移、哪些稳定 |
| D4 | `agg.jq` 的 `pct` 是最近秩、不插值，统计口径未写 |
| D5 | `metrics-catalog.md` 对 `mem_used_percent` 只写「已实测」，未写它是 `mem_used / mem_total`、不含可回收 page cache、偏紧方向 |
| D6 | skill 自带的只读自检 grep 会命中 `aws eks update-kubeconfig` 与 `aws configure get` 两个假阳性 ⇒ **`CLEAN` 永远打不出来** |

## 不在本轮范围

- 未覆盖形态：Aurora provisioned、PostgreSQL/Oracle/SQL Server RDS、Single-AZ RDS、
  只读副本、Memcached/Valkey/Serverless ElastiCache、Fargate、Karpenter、HPA、NLB、中国区。
  本轮所有改动对这些形态未经验证，不得声称已验证。
- 桶 C（`stop_candidate`）的真实机队验证：两次运行都是 `allow_stop=no`，
  六个分档字段在真实数据上仍未产出过值。R4 只解决契约表达，不解决管路。
- 让 `core.py` 对托管服务做完整选型（C4 的方案一）。本轮走方案二：报告层单列小计
  并明写头条不含它。完整选型需要托管侧价目阶梯进 `core.py`，是独立一轮的事。
