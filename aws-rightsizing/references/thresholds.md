# 阈值表（唯一真值来源，运行时不可放宽）

**数值在 `references/thresholds.json`，本文件不复述。** 本文件记载的是阈值的**含义、理由与实测边界案例**，不是配置值本身。

## solver 阈值：两个预设，按风险偏好选，不按环境

| 键 | 含义 | 两预设 |
|---|---|---|
| `target_cpu_p95` | 降配后 CPU 持续 p95 应达到的水位 | 不同，conservative 留更多余量 |
| `ceiling_cpu_max` | 降配后 CPU 峰值不得越过的上限 | 不同，conservative 留更多余量 |
| `target_mem_p95` | 降配后内存持续 p95 应达到的水位 | 不同，conservative 留更多余量 |
| `ceiling_mem_max` | 降配后内存峰值不得越过的上限 | 不同，conservative 留更多余量 |
| `burstable_baseline_headroom` | burstable 候选须保留的基线余量比例 | 同值 |
| **`max_reduction_ratio`** | 单次降配的 vCPU 降幅上限 | 不同，conservative 更严 |
| **`max_mem_reduction_ratio`** | 单次降配的**内存**降幅上限 | 不同，conservative 更严 |

**取值一律读 `references/thresholds.json` 的对应 profile。** 本文件不写数字——
写了就会与 JSON 各自漂移，`tests/test_no_duplicated_constants.py` 会按
「键名与其值同行出现」阻断这类复述。

前四项含义是**降配之后**该资源应达到的利用率，不是"低于多少才降配"的触发门槛。
是否降配是算法副产品：算出的 required 等于当前规格则无建议。

**预设按风险偏好命名，不按 prod/non-prod。** 原因：skill 无法验证环境类型，
而 operator 直接知道自己能接受多激进；且实测原 prod/non-prod 两列产出**完全相同**
——`ceil()` 在小 vCPU 数下把两档差异吞掉了，
`ceil(4×52.9/85)` 与 `ceil(4×52.9/75)` 都等于 3。用环境命名会承诺一个不存在的保护。

两预设的真实差距，**由仓库内的回归 fixture 产出**
（`tests/fixtures/regression-fleet.json`，13 台真实 EC2 脱敏后，
由 `tests/test_regression_fleet.py` 逐值断言）：

| 预设 | downsize 条数 | 路线一 Σ`nb_save_mo` | 路线二 Σmax(nb,b) | 判不了 |
|---|---|---|---|---|
| aggressive | 13 | **$527.15** | $668.85 | 0 条（两台低样本走降档，`confidence=low`） |
| conservative | 12 | **$373.00** | $492.72 | 0 条（1 条 `已合理配置`） |

复现：`python3 tests/test_regression_fleet.py`。四条口径（含这两条路线）的定义与
各自的作用域见 `report-template.md` 的「汇总口径」；`SKILL.md` 的同名小节只列禁止项。
**不得把这两列相加**，且这两列都是 `over bucket == "downsize"` 的和——
本 fixture 恰好没有 `bucket=idle` 的行，所以全表求和与带作用域求和在这张表上同值，
换一支机队就不同了。

> **路线二这一列早先写的是 $551.97 与 $413.22，已撤回。** 那是加
> `max_mem_reduction_ratio` 内存降幅地板**之前**的值：地板拦下了两台
> 4 GiB → 1 GiB（4x）的 burstable 候选，改选 4 GiB → 2 GiB，两个 profile
> 各少 $17.96。**路线一两列一分未变**——路线一只取 non-burstable，而没有
> 任何 non-burstable 候选超过内存降幅上限。旧值不是另一次测量，是同一支
> 机队在没有内存地板时的产出；它现在由 `test_regression_fleet.py` 的
> `MEM_FLOOR_OFF_ROUTE2` 断言锚定（把上限放到无穷大即复现），
> 所以仍然可复现，但**不再是当前基线**。

> **早先版本在这张表里写的是 13 条 / $527.15 与 12 条 / $373.00，那组数字不可复现，
> 不要拿来引用。** 来源是一份仓库外的 fixture，它把每台资源的 `cpu_n` 填成
> **720**——那是 30 天窗口的**全窗口**点数（`biz + off + weekend == WINDOW_DAYS × 24`），
> 而 `cpu_n` 的定义是 **biz-hours 档**的点数，是全窗口的子集，不可能等于全集。
> 口径填错的直接后果是采样量守卫恒不触发：13 台全部产出建议，包含两台窗口内新建、
> biz-hours 只有 154 与 55 个点、p95 根本没有统计意义的实例。
> 把 `cpu_n` 换回真实的 biz-hours 点数，那两台当时落 `insufficient-data`，
> 于是 13→11 条、$527.15→$401.51。**旧数字不是"另一次测量"，是同一次测量算错了口径。**
>
> **⚠️ 2026-09-09 起 $527.15 又是现值了，但成因完全不同。** 采样量从「拒绝线」
> 改成「置信度分档线」后，那两台低样本实例**照常产出建议**（`confidence=low`），
> 13 台又全部进降配 ⇒ 路线一回到 $527.15。
> 两次得到同一个数，一次是**守卫失效**（`cpu_n` 口径填错，那两台被当成满窗口、
> `confidence=high`），一次是**守卫改成分档**（口径正确，那两台明确标 `low`
> 并在 `blockers` 里写出样本量）。
> **判别式是 `confidence`**：现在那两台必须是 `low`，当年是 `high`。
> 逐条对账见 `tests/test_regression_fleet.py` 的基线迁移注释。

## `max_reduction_ratio`：真正的峰值护栏

单次降配的 vCPU 降幅上限。`required_vcpu` 之外再加一道地板：

```
floor_vcpu = ceil(cur_vcpu / max_reduction_ratio)
候选必须满足 vcpu >= floor_vcpu
```

**为什么需要它——目标利用率覆盖不了两类风险：**

1. **<5 分钟的尖峰不可见。** EC2 basic monitoring 每 5 分钟发布一次
   `CPUUtilization`，且该值已是 hypervisor 对这 5 分钟的**平均**。
   一次 30 秒的 100% 尖峰在数据里只显示约 10%。
2. **30 天窗口看不到月度/季度周期**（月结批处理、季度对账）。

目标利用率只能保证"按**已测到**的负载不越界"。窗口错过周期性峰值时，
一台 4C 砍到 1C 就是 4 倍不够用。降幅上限是对此的直接约束。

**这道护栏的依据是上面两条推理，不是某次实测的省钱差额。**

实测数字有一段来回，记在这里免得再兜一圈：

- 采样量还是拒绝线时，在回归 fixture 上解除 `max_reduction_ratio`
  **一毫米都不动**（仍是 11 条 / $401.51，实际最大降幅 2x）——因为唯一会被它
  拦下的那台资源正是两台 `insufficient-data` 之一（`c7g.xlarge`，biz-hours
  只有 154 点）。所以当时的结论是：**护栏的"实测证据"来自一台本该被排除的资源**，
  那组数字只证明了口径填错时会发生什么。
- **2026-09-09 采样量改成置信度分档后，那台资源不再被排除，这段证据于是复活：**
  解除护栏 ⇒ aggressive **13 条 / $555.03 / 实际最大降幅 4x**
  （路线二 $687.53；conservative $400.88 / $511.40）。
  被拦下的正是那台 4C → 1C 的 `c7g.xlarge`。

**但引用它时必须带上一句**：贡献这个差额的那一行 `confidence=low`
（biz-hours 154 点 < `min_biz_hours_points`）。护栏的正当性仍然来自上面两条
推理——恰恰是「低样本的 p95 更不可信」让降幅上限在这类行上比在满窗口行上
更必要，而不是靠这 $27.88 的差额。

**注意 `period` 不是峰值损失的来源。** 实测 6 台，请求 period=3600 与 period=60
得到的 `Maximum` **完全相同（低估系数 1.0x）**——`Maximum` 取的是周期内已发布点
的最大值，不做平均，所以 period 选多大都不丢峰值。损失发生在**发布环节**。
（此处曾错误记载为"85% 是给 period 采样粒度留的补偿"，已更正。）

`ceiling_*` 留余量的真实理由是上述发布间隔平均 + 未见周期 + 增长余量，
而非 period 粒度。

## `max_mem_reduction_ratio`：同一道护栏的内存侧

内存降幅上限，与 vCPU 那道同构：

```
floor_gib = ceil(cur_gib / max_mem_reduction_ratio)
候选必须满足 gib >= floor_gib
```

**取值与 `max_reduction_ratio` 相同，理由不是新的。** 上一节那两条推理
——发布间隔内的尖峰不可见、30 天窗口看不到月度/季度周期——**与指标种类无关**。
一台内存 p95 很低的机器同样可能在月结批处理里把内存吃满，而窗口正好没覆盖那次。
既然依据同源，就没有理由给内存另定一个数。

**而内存比 vCPU 更需要它。** CloudWatch agent 的 `mem_used_percent` 是
`mem_used / mem_total`，**不含可回收的 page cache**——页缓存被算进"未使用"。
可是那部分缓存对 I/O 密集型负载是有实际价值的：换到内存只剩一半的机型上，
缓存命中率下降、磁盘 I/O 上升，而这件事在降配**前**的 `mem_used_percent`
里完全看不见。于是内存 p95 被系统性压低，据它反推的 `required_gib` 偏小。
vCPU 侧没有这个对应的偏差源。

**这道护栏的由来是一次实测缺陷：** 一台 4 GiB 的 T 系列实例内存 p95 5.175%，
被建议降到 1 GiB——4 倍降幅、`confidence=high`，**两个预设给出完全相同的建议**，
而同一个 conservative 预设允许的 vCPU 降幅要小得多
（具体倍数见 `thresholds.json`，本文件不复述）。
这个不对称此前在代码、阈值表、文档三处都没有出现过：
`passes_common` 只给 vCPU 设了地板，内存没有任何比例约束。

**注意 `ceil()` 会在小内存规格上吞掉两个预设的差别，边界是可以写死的。**
两个预设的 `floor_gib` 相同，当且仅当

```
cur_gib ∈ (0, 2] ∪ (3, 4]
```

在 AWS 实际在售的内存规格里，落进这个区间的恰好是 **nano 的 512 MiB、
micro 的 1 GiB、small 的 2 GiB、medium/large 的 4 GiB** 这四档；
**8 GiB 是两个预设开始分道的第一档**（`floor_gib` 一个取 3、一个取 4）。
所以回归 fixture 上（受影响的两台都是 4 GiB）这道地板对 aggressive 与
conservative 拦下的是同样两条候选、代价也相同。

这与 `ceiling_*` 在小 vCPU 数上的同一现象同源（见上文预设命名那段），
不是配置写错——但要说清楚它的范围：**在 4 GiB 及以下，"更保守的预设"
这句承诺在内存这一维上兑现不了**，8 GiB 起才兑现。
反过来的情形不存在：conservative 的 `floor_gib` 永远不会低于 aggressive 的。

代价（回归 fixture 实测，`tests/fixtures/regression-fleet.json`）：路线二两个预设
各少 **$17.96**——两台 4 GiB 的 burstable 候选从 `t3a.micro`(2C/1G) 换成
`t3a.small`(2C/2G)。**路线一一分未变**，因为超限的都是 burstable 候选，
而路线一只取 non-burstable。

## 内存定档规则：完全按实测利用率，不设绝对下限

**已决策（2026-09-03）：不设内存绝对下限。**

| 情形 | 处理 |
|---|---|
| 有内存利用率数据 | `required_gib` 完全按实测反推，不设地板值 |
| 无内存利用率数据 | `required_gib = cur_gib`（**内存不动**），confidence 上限 `medium`，标注"内存需求按当前规格保守保留" |

理由：设一个"非生产 ≥2 GiB / 生产 ≥4 GiB"之类的绝对下限，是在没有该实例真实
内存画像的情况下替它做假设。有数据时应当信数据；没数据时正确动作是**不动内存**，
而不是拍一个下限。后者会同时产生两类错误——对小实例过度保护、对大实例仍然放行。

**"不设绝对下限"与 `max_mem_reduction_ratio` 不矛盾，两者管的不是同一件事。**

| | 绝对下限（**不设**） | 降幅上限（**设**，`max_mem_reduction_ratio`） |
|---|---|---|
| 形式 | "内存不得低于 N GiB" | "内存不得低于当前的 1/N" |
| 作用位置 | 会改 `required_gib` 的算法 | 只在 `passes_common` 过滤候选，`required_gib` 照算 |
| 为什么这样选 | 拍一个 N 是替实例假设它的绝对内存需求，而 skill 不知道 | 按当前规格成比例，不假设任何绝对量；约束的是"一次动多大"，不是"至少要多少" |

即 `required_gib` 仍然完全按实测反推、仍然可能算出很小的值；变的只是
**候选池里低于 `floor_gib` 的机型不再被选中**。差别在于后者不需要知道
这台机器实际需要多少内存，只需要承认"窗口没测到的负载"这一风险与规格成比例。

实测边界案例（本机队的 i-EX-10）：`c5.large`(2C/4G) 内存实测 p95 5.6%
（约 0.22 GiB），反推 `required_gib = 1`。**加内存降幅地板之前**，burstable
候选落到 `t3a.micro`(2C/1G)——4 倍降幅，与上一节那台 T 系列实例是同一个形状。
现在这条被 `floor_gib` 拦下，改选 `t3a.small`(2C/2G)。
`required_gib = 1` 这个反推**没有变**，变的是不再允许一次砍到那个位置。
**执行方仍须自行确认该实例的 OS 与 agent 常驻开销能容纳目标内存**——
报告已给出实测值与推算依据，判断权在执行方。

## 闲置判据（桶 B）

| 资源 | 条件 |
|---|---|
| EC2 | biz-hours 的 `p95_cpu` < `idle_cpu_p95` 且 `net_mb_day` < `idle_net_mb_day`（口径见下） |
| EC2 stopped | 状态为 stopped（其 EBS 卷仍计费） |
| EBS | `state=available`（未挂载） |
| EIP | 无 `AssociationId` 且无 `NetworkInterfaceId` |
| NAT | `ActiveConnectionCount` 全窗口恒 0（「全窗口」含覆盖度要求，见下） |
| ALB/NLB | 三态判定，**本表不复述条件**，见 `cli-recipes.md` §2.6 |

**快照不在这张表里，这是刻意的**——见下一节。

**为什么 ALB/NLB 那格只留指针。** 这张表的两列是「资源 → 条件」，装不下一个
3×3 的状态矩阵；硬塞就等于把矩阵复制第二份，而本文件的定位是**阈值**的唯一真值源
（见 `SKILL.md`），ALB/NLB 那条判据里**一个阈值都没有**——它是一台在「指标是否存在 /
取到多少点 / 值是多少」上跑的状态机。此前这一格写的是
「`RequestCount` 全窗口恒 0」，照字面读会把**序列根本不存在**也算作「恒 0」，
从而把一台其实一直有连接的 LB 报成可删除——上一轮真实运行就是这么错的。
判定矩阵、覆盖度门槛与可执行实现都在 `cli-recipes.md` §2.6，改判据只改那一处。
NAT 那格保持它的条件：NAT 是**单指标单状态**，一格装得下，且与 §2.6、`SKILL.md`、
`report-template.md` 的填法表三处一致。

**但「全窗口恒 0」里的「全窗口」是有覆盖度要求的，别只读成「恒 0」。**
零值序列必须覆盖整窗口（点数 = `WINDOW_DAYS × 24`）才算证据——一个 3 小时前
新建的 NAT 网关同样会给出「恒 0」，而这一行的动作是**删除**。
覆盖度门槛与 NAT/ALB 共用的可执行实现在 `cli-recipes.md` §2.6
（`quiet()`，两条路径同一份 jq）。**序列整条不存在也不是闲置**，是 `metric-missing`。

## 快照：本版本只列事实，不判年龄

**本版本不判快照年龄，`thresholds.json` 里也没有快照年龄键。**
`report-template.md` 第 4 节写的是「快照清单（仅事实陈述，本版本不判年龄）」：
列出快照、容量、创建日期、月额，`cur_cost_mo` 照填（分母要它），
`verdict` 与 `bucket` 都是 `excluded`、`action_type` 是 `none`
（见该文件的填法表），**不产出删除建议**。

**为什么不判：** 快照该不该删取决于 RPO 与合规/留存要求，而这两样都不在
本 skill 能读到的任何 API 里。同一个"很旧"的快照，可能是审计要求的留存副本，
也可能是早该清掉的垃圾；同一个"很新"的快照，可能是某个已删除卷唯一的恢复点。
年龄本身不携带这个信息，任何按天数切的判据都是拿一个看不见的前提冒充判据。

**推论：也不得把"源卷已删除"当成删除信号。** 那恰恰是快照可能是唯一剩余副本
的情形，越像"孤儿"越不能碰。

**因此禁止自造天数。** 想按年龄给建议的正确动作是：照常列出创建日期与月额，
在报告里写明"本 skill 不判快照年龄，需按贵方 RPO 与留存策略自行裁定"。
自己拍一个天数——哪怕只写在报告文字里——都违反「阈值以 `thresholds.json`
为唯一真值源」，且那个数字没有任何证据支撑。

## 桶 C 定时停机：判据与"不得自造判据"

**判据可以自动算，"能不能停"不能自动判。** 停机是否安全取决于 CloudWatch
**看不到**的信息：定时任务、被动监听的服务、依赖它的上游、维护窗口、
以及"低利用率"是否恰恰是该实例存在的理由（如冷备）。
所以判据的产出只是**候选**，永远不是建议——这条界线不因判据被代码化而移动。

因此桶 C 的产出**不是建议，而是候选清单 + 三档实测证据**，判断权交给执行方：

| 输出 | 内容 |
|---|---|
| 候选条件 | `off-hours` 与 `weekend` 两档**同时**满足：p95 CPU < `idle_cpu_p95` **且** 日均网络 < `idle_net_mb_day` **且** 该档 CPU 峰值 <= `stop_candidate_peak_cpu_max` |
| 必附证据 | 三档（biz / off / weekend）各自的 p95、max、采样点数 |
| 必附声明 | "本判据只能证明该窗口内**没有观察到活动**，不能证明停机安全。定时任务、被动监听、上游依赖、冷备用途均不可见。执行前须由业务负责人确认。" |
| 禁止 | **不得输出"建议停机"字样**，只写"停机候选，待确认" |

**判据由 `core.py` 的 `is_stop_candidate()` 实现，三个门限全部来自 `thresholds.json`。**
它返回**三态**，缺一不可：

| 返回 | 含义 | 报告怎么写 |
|---|---|---|
| `true` | 两档都过了三个门限 | 列进「停机候选，待确认」+ 三档证据 |
| `false` | 判过了，不是候选 | 不列 |
| `null` | **判不了**（缺 `off-hours`/`weekend` 输入，或 biz-hours 采样量不足） | 写进报告缺口：**"桶 C 未评估"**，不得写成"无候选" |

`false` 与 `null` 必须分开呈现。把「没评估」写成「不是候选」，报告读起来像
"已经查过、没有可停的"——这是本 skill 最忌的静默降级。

输入字段（`solver-in.json` 里逐资源给，组装式见 `cli-recipes.md` §7）：
`off_sus_cpu` / `off_peak_cpu` / `off_net_mb_day` 与
`weekend_sus_cpu` / `weekend_peak_cpu` / `weekend_net_mb_day`。
六个字段**任一缺失即 `null`**，不得当 0——0 是"零负载"，正是最像可停的信号。

`allow_stop_recommendations=no` 时该列**保留在 CSV 里但留空**，
**不得删列**，也不得填 `false`（`false` 是"判过了不是候选"，与"没判"不同）。
`core.py` 不知道这个运行时输入，所以它的输出里这一列永远有值，
留空是**采集/报告侧**做的事——但改的是那一格的内容，不是表的列数。

> **已撤回的写法（2026-09-04 起）：「整列不输出 …… 丢弃该列」。**
> 那是上一轮真实运行里两处**实测**契约违规之一（同一支机队的两份
> `findings.csv` 一份 40 列、一份 39 列，列数变化会破坏下游校验）。
> 本文件是唯一还写着删列的地方，另三处（`SKILL.md` 两处、
> `report-template.md` 的「`stop_candidate` 的四种情形」）一直写的是保留留空。
> 列集的唯一真值源是 `report-template.md` 的 `csv-columns` 块，
> 任何运行时输入都不得改变它。

`stop_candidate_peak_cpu_max` **两个预设取同一个值**，和 `idle_*` 三个键一样：
桶 C 的产出是候选清单而不是变更建议，风险偏好落在"要不要执行"上，不落在门限上；
而且本 skill 没有测量过两档不同门限的效果，凭空分成两个值等于承诺一个未验证的差别。

**明确禁止自造判据。** 若执行者认为上表不足以判断，正确动作是
**报"无候选"并写明本文件缺该判据**，附三档数据让人自己判；
**不得**自行发明一个阈值（如仅用 `off-hours CPU p95 < 5%`）然后据此产出停机建议——
仅凭 CPU 一个信号会把被动监听型服务全部误判为可停。

`allow_stop_recommendations=no` 时整个桶 C 不产出，连候选清单也不出。

### 桶 B 网络口径：biz-hours 外推 ≠ 全时段

本 skill 早期版本的 `net_mb_day` 是**取 `bucket == "biz-hours"` 的 Average 再乘一个系数
外推全天**，语义是"biz-hours 速率外推全天"，不是全时段真值。

实测差异：某实例 biz 外推 **53.11 MB/日**，全窗口 `Stat=Sum` 真值 **71.62 MB/日**，
差 **26%**——该实例 off-hours 更繁忙（备份类）。而闲置门限 `idle_net_mb_day` 很小，
26% 的口径差足以翻转判定。

**闲置判据应看全时段**：一台夜间跑批的机器不是闲置资源。因此**只认一种口径**：
`net_mb_day` = **全窗口（三档全算）`Stat=Sum` 逐小时相加 ÷ 窗口天数**。
零换算假设，不需要任何外推系数。组装式见 `cli-recipes.md` §7，
采集侧须按 §2.1 对 `NetworkIn`/`NetworkOut` 显式采 `Stat=Sum`。

**biz 外推不再作为可选口径。** 两种口径都"可选"的结果是两个 agent 在同一机队上
得出不同的桶 B 清单，而桶 B 产出的是删除类建议——本 skill 后果最重的一类。
判据的输入口径必须唯一。

## 服务专有覆盖

| 服务 | 参数 | 值 | 依据 |
|---|---|---|---|
| MSK | `msk_target_cpu_p95` | 两预设同值，且低于通用的 `target_cpu_p95` | AWS 建议 broker CPU 不长期高位，须留缓冲 |
| MSK | 降配前置 | `KafkaDataLogsDiskUsed` max < `msk_disk_used_max` | **0–100 刻度**（实测 0.02 与 0.353） |
| MSK | 降配前置 | `RequestHandlerAvgIdlePercent` > `msk_handler_idle_min` | **0–1 刻度**（实测 0.999–1.002），不是 0–100 |
| MSK | 阻断 | `UnderReplicatedPartitions` > 0 | |
| MSK | **前置不可评估** | `EnhancedMonitoring = DEFAULT` | 该档**不发布** `RequestHandlerAvgIdlePercent`（实测），CPU/磁盘/URP 反而都有。前置条件算不出 ⇒ 不产出降配建议。**报告缺口「提到 `PER_BROKER` 再等一个窗口」只在同形态下确实存在更便宜候选机型时才写**——`core.py` 的 `eval_msk` 先查 `cheaper_candidate_exists`，为假则直接「已合理配置」、不再要求任何前置指标（实测 `kafka.t3.small` 就是这种情况，补指标也不会有建议）。本表不复述判据顺序，见 `core.py` |
| MSK | 不产出 | 减 broker 数建议 | 需 partition 重分配，属架构级操作 |
| RDS | 降配前置 | `DBLoad` p95 < `rds_dbload_ratio` × vCPU | 需 Performance Insights；未开则该实例只能用 `CPUUtilization` 替代，confidence 降 medium |
| RDS | 阻断 | `DBLoad` p95 >= vCPU 数 | CPU 已是瓶颈 |
| RDS | 阻断 | `FreeableMemory` **最小值** < 实例内存的 `rds_freeable_mem_floor_pct`% | 降配会 OOM。**必须采 `Stat=Minimum`**——空闲内存越多越安全，用 `Maximum` 或 `Average` 的 p95 是取错方向，会把危险实例判成安全 |
| RDS | **阻断（独立否决）** | `CPUSurplusCreditsCharged` **单小时最大** > 0（采 `Maximum`；与"窗口累计 > 0"等价） | 仅 `db.t*`。**优先级高于 `DBLoad`**：实测某 `db.t4g.medium` 的 `DBLoad` p95 = 0.547 < 0.5×2vCPU ⇒ 前置"满足"，但 `CPUCreditBalance` 最小值 = 0（上限 576）、`CPUSurplusCreditsCharged` **单小时最大** = 730.6 ⇒ 规格已不足，是**升配**候选。只看 `DBLoad` 会给出错误的降配建议 |
| RDS | 阻断 | `CPUCreditBalance` **最小值** == 0 | 同上，信用触底。须采 `Stat=Minimum` |
| RDS | 排除 | `db.serverless` | Aurora Serverless v2 按 ACU 伸缩，无固定规格 |
| Redis | 阻断 | `Evictions` **单小时最大** > 0（采 `Maximum`；与"窗口累计 > 0"等价） | 内存已不足，降配更糟 |
| Redis | 阻断 | `ReplicationLag` max >= `redis_repl_lag_max_s` 秒 | |
| Redis | 内存口径 | `required_gib_usable = mem_gib × (1 − reserved) × db_mem_used_pct_max / 100` | `DatabaseMemoryUsagePercentage` 是 **maxmemory**（= 节点内存 × (1 − reserved)）的百分比，**不是节点内存的百分比**，所以是**乘** `(1 − reserved)` 而不是除。`reserved` 缺省取 `reserved_memory_pct_default`。写成除会得到节点总内存口径，与键名 `usable` 矛盾，并把需求量放大约 1.33 倍 |
| Redis | 不产出 | 减副本 / 减 shard 建议 | 降低可用性等级 / 需数据重分布 |

## burstable 选项专有

每个降配建议同时给 non-burstable 与 burstable 两个候选，由人工选择
（生产通常取 non-burstable）。**skill 不代替人工做这个选择，两列一律都出。**

| 参数 | 值 |
|---|---|
| `burstable_baseline_headroom` | 见 `thresholds.json`；含义是候选的基线容量须留出的余量比例 |
| 抑制 burstable 选项 | 当前已是 T 系列 且 `CPUSurplusCreditsCharged` 窗口内 > 0 |
| burstable 规格上限 | `burstable_max_vcpu` / `burstable_max_gib`（两个架构取值一致，实测） |
| `baseline_pct` 缺失时 | 标 `baseline-unknown` 不产出，**禁止用记忆值代替** |

候选族随当前架构而变：`x86_64` → t3 / t3a；`arm64` → t4g。

**`t2` 不是候选族。** 它在 `legacy-families.json` 的排除清单里，
`core.py` 的 `passes_common` 在 legacy 过滤那一步就把整族剔掉了——
写进候选族清单会让读者以为能推出 `t2.*`，而实现永远不会产出。
（`instance-specs.md` 的同一张表同步更正。）

**当前状态：`baseline-pct.json` 已填满 28 个型号并经运行时实测交叉验证，
burstable 选项正常产出。**（本行原写"全部为 UNKNOWN"，与
`instance-specs.md` 的完整表及 `baseline-pct.json` 的实际内容不符，2026-09-03 更正。）

运行时交叉验证结果（信用上限 = `vcpu × baseline_pct × 1440`，见 `instance-specs.md`）：

| 实测对象 | `CPUCreditBalance` 上限实测 | 表值反推 | 结论 |
|---|---|---|---|
| `cache.t3.medium`（ElastiCache） | 576 | `2 × 0.20 × 1440 = 576` | 吻合 |
| `cache.t4g.micro`（ElastiCache） | 288 | `2 × 0.10 × 1440 = 288` | 吻合 |
| `db.t4g.medium`（RDS） | 576 | `2 × 0.20 × 1440 = 576` | 吻合 |

该自校验**不需要额外 API 调用**（信用指标本就在采集范围内），
每次跑都应顺手核一遍，用来发现表过期。

## CPU 信用余额触底

键：`credit_balance_floor_pct`（两个 profile 同值 —— 「信用是否耗尽」是事实而非
风险偏好，与 `rds_freeable_mem_floor_pct` / `redis_repl_lag_max_s` 同样处理）。

**语义**：余额下限占**窗口内观测到的最大余额**的百分比。低于它即判触底 ⇒
`upsize-candidate`（当前规格已不足）。输入取 `CPUCreditBalance` / `Minimum` /
**`full-window`** 档的 `min` 与 `max` —— 下限型指标必须取 `full-window`，
`biz-hours` 会漏掉夜间批处理耗尽信用的低点（同 `freeable_mem_min_gib` 的坑）。

**为什么分母是「观测最大余额」而不是「信用上限」**：上限 =
`vcpu × baseline_pct × 1440`，而 **RDS 的 baseline 百分比不在本 skill 的静态资产
里** —— `baseline-pct.json` 只覆盖 EC2 机型。用观测最大值自归一化，EC2 与 RDS
共用一套算法，且不需要引入第二张静态表。代价是：若实例整窗口都处于饿死状态，
观测最大值本身就低，比值会偏高 —— 所以 `max == 0` 单独兜住（恒为 0 = 彻底耗尽），
这同时也是除零的守卫。

**选值依据**（实测两支机队，`123456789012` / `ap-east-1`）：

| 状态 | 余额下限占观测最大值 | 样本 |
|---|---|---|
| 触底 | **0.00% – 0.14%** | 1 台 t3.xlarge（0.00）+ 2 台 RDS（0.14 / 0.12） |
| 健康 | **85.07% – 99.91%** | 3 台 t3.medium + 2 台 db.t4g.* |

中间**没有任何观测点**，所以取值不敏感。数值只在 `thresholds.json`。

**为什么不判 `min == 0`**：`Minimum` 是逐小时最小值，真实耗尽时通常落到 0 但
不保证 —— 实测那两台 RDS 的最小值是 0.79 / 0.70。把判据建在「恰好等于 0」上，
会让余额在 0.3 附近徘徊的饿死实例逃掉，而那正是本判据要抓的一类。

## 排除机型族

`g*` / `p*` / `inf*` / `trn*`：受限资源是加速器，默认 CloudWatch 无利用率指标，
不产出任何降配建议，报告中单列。

## 指标刻度与统计口径（易错项）

### 同一 namespace 内刻度不统一，必须逐指标确认

实测 `AWS/Kafka`：

| 指标 | 刻度 | 实测值 |
|---|---|---|
| `KafkaDataLogsDiskUsed` | 0–100（百分数） | 0.352 |
| `RequestHandlerAvgIdlePercent` | **0–1（比例）** | 0.998–1.002 |
| `MemoryUsed` | 字节 | 1.14e9 |

判据写成 `> 70%` 而指标是 0–1 刻度，会导致该判据**永远不成立**，
降配建议被静默吞掉。新增指标时必须先跑一次实测确认刻度。

**这张表里的刻度是稳定事实，不是观测值。** 0–1 与 0–100 是指标的发布口径，
不随 AWS 上新机型或调价而变。上表右列的实测值会随集群负载变，
但**刻度本身该当断言用**——把它当"参考值"就会有人跳过刻度确认，
那正是这道坑的成因。（观测值与稳定事实的分类见 `cli-recipes.md §0.1`。）

### 报告里的 p95 是最近秩、不插值

`agg.jq` 的 `pct(p)`：排序后取下标 `floor((n-1) × p)`，**取的是真实存在的那个
数据点，不在两点之间插值**。所以报告里的持续 p95 一定是窗口内某个小时桶真的
出现过的值，不是算出来的中间数。客户是照着这个数直接动手的，口径必须写明。

三个直接后果：

- **相对线性插值口径，本口径系统性偏低。** `floor` 只会往下取，
  插值结果永远 >= 最近秩结果。实测（直接跑 `agg.jq` 的 `pct` 定义，
  输入 `1..n`）：n=20 时 `floor(19 × 0.95) = 18` ⇒ 取升序第 19 个
  （= 第 2 大）；插值口径要算到 `19 × 0.95 = 18.05` 的位置，落在第 19 与
  第 20 之间，比本口径高。方向上这让 p95 偏小、定档偏紧，
  与 `mem_used_percent` 的偏差同向叠加（见 `max_mem_reduction_ratio` 那节），
  这也是那道相对护栏要存在的一部分理由。
- **p95 永远取不到最大值**（除 n=1）：`floor((n-1) × p) = n-1` 只在 `n = 1` 成立。
  所以峰值判据必须另用 `max` 列，不能指望"p95 已经接近峰值"。
  实测同一组：满窗口 biz-hours（n=242）p95 取升序第 229 个 = **第 14 大**；
  n=13（MSK 那个短历史集群）取第 12 个 = **第 2 大**。
- **样本极小时 p95 会退化成最小值**：实测 n=2 ⇒ 下标 `floor(1 × 0.95) = 0`，
  取的是两点里**较小**的那个。这个方向是最激进的。
  `pct` 自己不拦它，`min_biz_hours_points` 也**不再**拦它——2026-09-09 起
  那道门限是置信度分档线而不是拒绝线，这类行会带 `confidence=low` 出建议。
  拦它的是三样东西合起来：`max_reduction_ratio` 与
  `max_mem_reduction_ratio` 两道相对降幅地板（无论样本多小都封住降幅），
  加上 `blockers` 里写明的样本量让人能复核。
  **只有 `cpu_n` 为 0 或缺失才 `insufficient-data`**（那是「无」不是「少」）。

**换算成别的工具会对不上，这不是缺陷。** numpy 的 `percentile` 默认线性插值、
CloudWatch 控制台的 p95 也不是这个口径。拿别处的 p95 跟本报告对，
差一点属正常；要复现本报告的数，用 `agg.jq`。

### 复合指标必须用 CloudWatch metric math，不能分别聚合再相加

MSK 的 CPU 判据是 `CpuUser + CpuSystem`。**两个序列各自的 p95 之和不等于和的 p95。**
正确做法是在 `GetMetricData` 里用 `Expression: "m1+m2"` 逐点相加，再做时段聚合；
被加数用 `ReturnData: false` 避免多余传输。

实测对比（broker1，biz-hours）：

| 做法 | 持续 p95 | 峰值 max |
|---|---|---|
| metric math（正确） | 5.45 | 41.82 |
| 分别算 p95 再相加（错误） | 5.495 | 41.817 |

本例差距仅 0.8%，因为两个序列峰值恰好同时出现——这是运气，不是通例。
序列峰值错开时误差会显著放大。

### 最小采样量：置信度分档线（不是拒绝线）

`biz-hours` 档有效数据点数少于 `min_biz_hours_points` 时，**照常产出降配建议**，
但 `confidence` 降到 `low`，并在 `blockers` 里写明实际点数与占门限比例。
只有点数为 `0` 或缺失才标 `insufficient-data`——那是「无」不是「少」，
p95 无从计算。

**这一分档只作用于降配路径。** `is_idle`（动作是删除）与 `is_stop_candidate`
（动作是停机）保持硬门限：可回滚的动作允许低置信度产出，不可回滚的不允许。

改这一条的理由：旧写法在门限之下整段短路，**连否决项一起压掉**。实测
一个 prod 命名的 MSK 集群的 `UnderReplicatedPartitions=27` 与一个 Redis 复制组的
`ReplicationLag=23.88s` 都因此没出现在报告里，报告只写了「点数不足」——
而否决项读的是 `max`，拿采样量去挡它没有依据。

采集窗口按业务本地午夜对齐后（`cli-recipes.md` §2.0 ①），满窗口资源的点数是
**可精确预测的整数**：`biz-hours = 工作日数 × 11`、`off-hours = 工作日数 × 13`、
`weekend = 周末天数 × 24`，三者之和 = `WINDOW_DAYS × 24`。
实测 30 天窗口（22 工作日 + 8 周末日）：`242 / 286 / 192`，合计 720，闭合。

低于预期值说明该资源在窗口内并非全程存在（新建 / 曾停机），属正常。
**但若某资源三档之和不等于 `WINDOW_DAYS × 24` 而该资源确实全程存在，
是采集缺陷**（分页拼接丢数据或窗口未对齐），须查而不是标 `insufficient-data`。

实测触发案例：某 MSK 集群指标仅约 26 小时历史 ⇒ biz-hours 只有 **13–15 个点**；
两台新建 EC2 ⇒ **154 点**（19 天）与 **54 点**（6 天）。

## `rds_storage_days_floor`：存储耐久度门限（两档同值）

外推口径：`速率 = (FreeStorageSpace/Average 窗口首点 − 末点) / 窗口天数`，
`剩余天数 = 末点 / 速率`。速率 ≤ 0 时不外推（否则会算出负天数）。

**两个 profile 同值**，且这不是遗漏：它是运维安全边界而非利用率策略 ——
「多久之后磁盘会满」与「你愿意把 CPU 压到多紧」无关。取值的依据是 RDS storage autoscaling 从触发到扩容完成需要一个变更窗口，
加上一个业务周期的观察期；比这更短会让告警和变更挤在同一周。
（具体数值只在 `thresholds.json` 里 —— 这条 lint 正是为此存在。）

**即使同值也必须在两个 profile 都写。** `load_thresholds` 按 profile 取键，
少写一个会在另一档抛 `KeyError`（这是刻意的：`.get()` 兜底会让判据静默消失）。

## ElastiCache 内存轴：为什么不用 `max_mem_reduction_ratio`

候选须满足的可用内存下限 = `已用可用内存 / (target_mem_p95 / 100)`，
形式与 EC2 侧 `_required` 的内存项逐字一致，**不新增阈值**。

那道降幅地板在这条阶梯上**结构性不可满足**：

| 相邻两档 | 内存比值 |
|---|---:|
| `cache.t4g.micro` → `cache.t4g.small` | 2.74 |
| `cache.t4g.small` → `cache.t4g.medium` | 2.26 |
| `cache.t4g.medium` → `cache.m6g.large` | 2.07 |

相邻比值**全部大于 conservative 的 `max_mem_reduction_ratio`**，
于是从 `cache.m6g.large`（6.38 GiB）往下要求候选 ≥ 3.19 GiB，
而下一档 `cache.t4g.medium` 只有 3.09 GiB —— 差 3%，永久挡死。实测按比值地板筛，conservative 下 11 个复制组**全部**选不出目标、
合计 $0，且失败原因会被写成「装不下」而真正的约束是降幅地板。

地板的立论（`mem_used_percent` 不含可回收 page cache、会压低内存 p95）
在这里也不成立：`DatabaseMemoryUsagePercentage` 是相对 `maxmemory` 的权威
利用率，没有那个盲区。**CPU 侧的 `max_reduction_ratio` 保留** ——
vCPU 阶梯是干净的 2 倍，比值表达等价于档数。

## 候选机型族过滤

三道过滤叠加。**不使用任何 `currentGeneration` 字段**（理由见下）。

**过滤顺序不可调换**：先剔 legacy 族，再在剩余机型池内允许跨分类，
最后校验 region 可用性。否则跨分类会把 a1 / i3 这类最便宜的老机型拉进来。
完整年代证据见 `references/legacy-families.md`。

### 1. legacy 族清单（策展清单，非推导事实）

`references/legacy-families.json`。**必须标明这是人工策展的策略清单**，
不是从某个权威接口推导出来的完整集合。逐条出处：

| 族 | 出处 | 价格证据 |
|---|---|---|
| c1 c3 c4 d2 i2 m1 m2 m3 m4 r3 r4 t1 | AWS Previous Generation 页面解析所得 | m4 仅比 m6i 贵 4%，价格过滤拦不住，清单必需 |
| **a1** | 策展补充（Graviton1, 2018） | **同规格组最便宜，比 m6g.large 便宜 35%，不拦必被选中** |
| **i3** | 策展补充（2017） | **比 i4i.large 便宜 10%，不拦必被选中** |
| t2 | 策展补充（2014） | 比 t3 贵 12%、比 t4g 贵 41%，价格过滤已能排除，列入仅为保险 |
| x1 cc2 cg1 cr1 hs1 g2 g3 p2 | 策展补充 | 未逐一验证价格 |

**已知局限**：清单可能不完整。漏掉的老族若单价低于当代族，会被选为候选。
补救方向是定期用 AWS Previous Generation 页面复核，或改为按机型用途分类 +
明确的允许族白名单（维护成本更高）。

### 2. 机型用途分类（来自 pricing API 的 `instanceFamily`）

候选分类必须属于 `General purpose` / `Compute optimized` / `Memory optimized`，
或与当前机型分类相同（后者让专用机型能在同类内降配）。

排除：`Storage optimized`、`GPU instance`、`FPGA Instances`、
`Machine Learning ASIC Instances`、`Media Accelerator Instances`、`Micro instances`。

实测依据：`i3en.large` 曾被选为 `m5.xlarge` 的降配目标——它是 Storage optimized、
带本地 NVMe，单价 $0.266/hr **高于**被替换的 $0.248/hr。根因是缺用途分类。

**允许跨这三个分类，这是刻意设计而非疏漏。** 分类本质编码 vCPU:内存 比例
（Compute 1:2 / General 1:4 / Memory 1:8）。当实测比例偏离当前族的比例时，
跨分类才是正解：

> `m6g.large`（2C/8G，1:4）实测持续 CPU 不到 1%。留在 General purpose 内
> 为拿到 8 GiB 就得保留 2 vCPU，等于无法降配；跨到 Memory optimized 的
> `r6g.medium`（1C/8G）省 $27.89/mo。回归 fixture 里两台都走了这条路。

量化（回归 fixture，aggressive，`tests/fixtures/regression-fleet.json`）：

| | 条数 | 节省 |
|---|---|---|
| 跨分类推荐 | 9 | **$467.69/mo（占 89%）** |
| 同分类推荐 | 2 | $59.46/mo |
| 若强制同分类 | 4 | $86.61/mo（**丢掉 84% 的节省**） |

（**这张表改过三轮，三个版本的数字都留在这里。**
① 最早：9 条 / $495.57 / 占 89% 与 8 条 / $86.61 / 丢 84%，外加一条
`c7g.xlarge → r6g.medium 省 $88.40/mo` 的例子 —— 出自 `cpu_n=720` 的失效 fixture，
那份 fixture 让采样量守卫从不触发。
② 2026-09-04 用真实 biz-hours 点数重测：7 条 / $342.05 / 占 85% 与 4 条 / 丢 78%，
因为那台 `c7g.xlarge` 与另一台落进了 `insufficient-data`。
③ 2026-09-09 采样量改成置信度分档后，那两台不再被拒绝、改带 `confidence=low`
出建议，于是条数与占比回到 9 条 / 89%，但金额是 $467.69 而不是最早的 $495.57
—— 差额来自 2026-09-04 加的内存降幅地板。
**条数与占比回到旧值不等于旧 fixture 的错误回来了**，判别式是那两台的
`confidence` 必须为 `low`；完整对账见 `tests/test_regression_fleet.py` 的
`EXPECTED` 上方注释。）

报告必须显式标出分类变更，供人工复核。

### 3. 排除 `*-flex` 族

flex 族可持续 CPU 低于标称（约 40% 基线可突发），但
`BurstablePerformanceSupported` 报 `false`，会被误当满容量机型。

### 为什么两个 `currentGeneration` 字段都不能用

| 来源 | 对关键型号的判定 | 结论 |
|---|---|---|
| `describe-instance-types.CurrentGeneration` | m6i=false, r6i=false, c5/m5/r5=false；t2=true, i3=true, x1=true | 语义与代次无关。用它会排除主流当代族、放进 2014 年的族 |
| pricing API `currentGeneration` | **m4=Yes, c4=Yes**, t2=Yes, i3=Yes；仅 a1=No | 过于宽松，m4/c4 是 2015 年机型 |

两者对 1145 个共同型号有 **80 处判定不一致**。

`describe-instance-types` 的该字段**不随 region 变化**（ap-northeast-1 vs
us-east-1，1145 个共同型号 0 处不一致，族内取值亦统一），
所以它的不可靠是全局性的，不是地域数据差异。

### region 依赖性实测

| 项 | 是否随 region 变 | 处理 |
|---|---|---|
| `CurrentGeneration` | 否（0/1145 不一致） | 不使用该字段 |
| legacy 族清单 | 否（全局策略） | 静态清单 |
| 用途分类 `instanceFamily` | 否（产品属性） | 可缓存 |
| **可用机型集合** | **是**（观测值 @2026-09-04：东京 1198 / 弗吉尼亚 1371，182 个仅弗吉尼亚有；个数是 A 类、会漂移，见 `cli-recipes.md §0.1`） | **必须按 region 现查** |
| **价格** | **是**（东京溢价 117–131%） | **必须按 region 现查** |

价格的**相对关系跨 region 稳定**：a1 在两个 region 都是同组最便宜，
i3 在两个 region 都比 i4i 便宜。因此 legacy 清单在每个 region 都是必需的，
不是东京特有现象。

### 4. 加速计算族

`g*` / `p*` / `inf*` / `trn*` 作为**当前机型**时直接排除出桶 A：
受限资源是加速器，默认 CloudWatch 无利用率指标。
