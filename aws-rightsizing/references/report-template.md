# 报告模板与 findings.csv 规范

## 产出物布局

单一输出根，按「账号-region-日期」分目录，**交付物文件名带 `sizing_profile`**，
`raw/` 共用，**不同次运行不互相覆盖**：

```
report_output/<account>-<region>-<YYYYMMDD>/
  aws-rightsizing-report-<profile>.md   单文件报告，按服务分节
  findings-<profile>.csv                全量明细，一资源一行
  raw/                                  ← 采集与 profile 无关，故共用，不重复落盘
    inventory/*.json             各服务 describe 原始输出
    metrics/*.json               get-metric-data 原始输出
    metrics/summary-*.csv        聚合后 avg/p95/max × 三档时段
    specs/ec2-types.json         机型规格快照
    specs/od-keyed.json          按需价目快照（含 instanceFamily）
    specs/offerings.json         该 region 可用机型集合快照
```

两个交付物直接放在运行目录根下；`raw/` 是唯一子目录，界线就是「交付物 vs 可复算证据」。

作用域目录不可省。本 skill 的运行时输入含 `target_account` 与 `regions`，
且多账号场景明确靠换凭证重跑——若都写进同一个 `report/`，第二次运行会静默
覆盖第一次，连 `raw/` 的审计证据一起丢。

`sizing_profile` 与 `target_account` / `regions` 一样是运行时输入，
且两个预设在同一机队上的条数与总额都不同（见 `thresholds.md` 的预设对比表）——
文件名不带 profile 会让第二次运行静默覆盖第一次，而 `raw/` 是共用的，
**覆盖之后看不出发生过覆盖**：目录里的原始数据两次一模一样，没有任何异常信号。
反之，`raw/` 若按 profile 各存一份，同一份采集会被落盘两次，
几百个序列的原始 JSON 翻倍且两份必然逐字节相同——那是另一种「同一真值两处存」。

`raw/` 必须保留：报告结论可复算、可审计，且 agent 只读 summary 不读 raw，
几百台资源不会撑爆上下文。价目与规格也快照，否则日后无法复现当时的结论。

## 报告开头的强制声明（两段都不可省）

> 本报告基于资源利用率给出配置优化建议，金额一律为**公开按需（On-Demand）价目**
> 计算的理论值，**不含实际账单数据**。
>
> 因此：被 Reserved Instance 或 Savings Plan 覆盖的资源，降配后账单可能不立即
> 下降——折扣会转移到其他资源或在承诺期内搁置。报告中的节省金额是"若该资源按
> 按需价计费"的上限估算，实际财务收益需结合账单数据另行评估。

> 本报告的建议均为**同形态降配**：不改变架构形态、不改变 CPU 架构、不降低可用性
> 等级。Serverless 迁移、跨 CPU 架构迁移、Spot、副本或 AZ 数量削减均不在范围内。

> 作用域：账号 `<target_account>`，region `<regions>`，窗口 `<window_days>` 天，
> 定档预设 `<sizing_profile>`（含 `max_reduction_ratio` 与
> `max_mem_reduction_ratio`），
> 停机建议 `<allow_stop_recommendations>`，业务时区 `<business_timezone>`。
> 价目快照日期 `<price_snapshot_date>`。

第一段不写，客户会把"可降配"读成"可省钱"。第二段不写，客户会问为什么没提
Graviton 迁移和 Serverless。第三段不写，报告脱离上下文后无法判断适用范围。

## 报告分节

```
1. 摘要            总资源数 / 可降配数 / **四条口径的月省各一个数** / 各自占按需月额比例
2. 前置条件与数据缺口   preflight 结果，逐项写明缺什么、影响哪节、客户要开什么
3. EC2             桶 A 降配（双候选并列）+ 桶 B 闲置 + 桶 C 停机
4. EBS             gp2→gp3、未挂载卷、快照清单（仅事实陈述，本版本不判年龄）
5. RDS             桶 A / 阻断项 / 桶 F 存储过度预配
6. ElastiCache     桶 A / 阻断项
7. MSK             桶 A / 桶 D / 桶 F
8. EKS             桶 E request 调优 + 节点池建议
9. VPC             桶 B 闲置 NAT / EIP / LB
10. 排除清单        bucket=excluded 的全部资源，附原因
11. 托管服务候选小计  RDS / ElastiCache / MSK 的候选与月省，**不计入头条数字**
```

第 10 节按 **`bucket == "excluded"`** 筛，不按 `verdict` 筛——`verdict` 描述规格
判据的结论，`bucket` 才是归属。按 `verdict` 筛会把 `bucket=idle` 的闲置资源
同时列进排除清单，一个资源在报告里出现两次。该节可按原因分组给条数与金额小计，
不必逐行罗列，但 CSV 必须逐行。

摘要里的每个比例都必须注明分母是**按需理论月额**，不是实际账单。

**比例逐口径各算一个，四个并列。分子不是"所选口径"，是全部四条：**

```savings-ratios
路线一比例   = 路线一合计   ÷ 分母
路线二比例   = 路线二合计   ÷ 分母
桶 B 比例    = 桶 B 合计    ÷ 分母
采集侧比例   = 采集侧合计   ÷ 分母
```

（四条口径的定义与作用域见下方「汇总口径」，分母见「分母的范围」。
`SKILL.md` 的「价格口径」一节只讲分子分母都是按需理论值，不再写算式。）

**本报告不给单一的头条百分比，这是刻意的。** 任何一个单一数字都要求先在两条互斥的
降配路线之间选一条，而那是客户的决定（路线二要逐条确认可接受突发模型），不是本
skill 的决定。留一个"所选口径"的口子，两次运行就会各挑一条：同一支机队路线一与
路线二的合计差距是显著的（`thresholds.md` 的预设对比表就是这两列，逐值可查），
而百分比是报告里最显眼的数字，客户第一眼看的就是它。
这与本文件对托管服务小计的要求是同一条规则：**并列、各标口径、不相加。**

需要一个"总共能省多少"的说法时，唯一合法的写法是**把可相加的两条写成一个和并标明**
（例如「路线一 + 桶 B 合计」），不得省略口径名，也不得把互斥的两条降配路线相加。

分子分母**都是按需口径**。客户若已买 RI/SP，实际账单基数低于按需月额，
则同一笔绝对节省对应的实际百分比更高、而绝对金额更低（甚至为 0，若折扣只是
转移到别的资源）。两个口径不可混用，报告中只给按需口径并标注。

## 汇总口径

四条口径。**每条都带作用域，互斥关系必须在报告正文里写出来**，否则读者无从判断
能不能相加：

```totals-routes
路线一 = Σ nb_save_mo over bucket == "downsize"          （降配，一律取 non-burstable）
路线二 = Σ max(nb_save_mo, b_save_mo) over bucket == "downsize"  （降配，逐条取更省者）
桶 B 合计 = Σ cur_cost_mo over bucket == "idle"          （闲置资源移除后的全额）
采集侧合计 = Σ other_save_mo over bucket == "downsize"    （采集侧自建行的节省额）
```

- 路线一与路线二**互斥**，不得相加。
- 桶 A 与桶 B **互斥**（同一资源只进一个桶），故桶 B 合计**可以**与路线一或路线二相加。
- 命中 `idle` 的行，其 `nb_save_mo` 是「若须保持运行改为降配」的**替代方案**，
  **不进桶 B 合计**，也不进路线一/二 —— 否则同一资源被算两遍。
  这就是路线一/二写 `over bucket == "downsize"` 的原因：**不写作用域，
  这一列就会被当成全表求和**，而那正是本仓库已经犯过两次的错
  （`cli-recipes.md §6 ③` 修的就是它）。
- **采集侧合计与路线一/二按构造互斥**：没有任何一行同时带 `other_save_mo` 与
  `nb_save_mo`／`b_save_mo`（前者只在采集侧自建行上，后两者只由 `evaluate()` 产出），
  所以它**可以**与路线一或路线二相加；与桶 B 合计按 `bucket` 互斥，也可相加。

`over bucket == "downsize"`（本块的 allowlist）与 `over bucket != "idle"`
（`cli-recipes.md §6 ③` jq 里的 denylist）**在节省额列上等价**。两种写法都对，
不要以为它们是两个不同口径。

**但这个等价性有一个前提，它是被断言守住的、不是巧合：
`bucket == "excluded"` 的行不得带 `nb_save_mo` / `b_save_mo` / `other_save_mo`
中的任何一个。** 断言在 `tests/test_regression_fleet.py` 的
`test_excluded_rows_never_carry_savings`（判据行，真实机队上两种 excluded verdict
各覆盖）与 `tests/test_csv_contract.py` 的
`test_fill_table_covers_the_new_savings_column`（采集侧自建行，查填法表）。

前提一旦破了，两种写法立刻分叉：**allowlist 会漏掉那笔钱，denylist 会算进去**，
于是同一份原始数据出两个不同的头条数字。所以出现「既 `excluded` 又带金额」的行时，
正确动作是**先决定它到底属于哪个桶**，而不是改任何一侧的求和式。

报告给出的每个百分比都必须标明分子用的是哪一条口径；四条混用会得出无法复算的数字。

实测依据：某闲置实例删除可省 $1,369.48、降配可省 $98.55，**差 13.9 倍**；
只对 `nb_save_mo` 求和会让该 region 桶 B 的 93% 不出现在报告里——
这一列装的从来不是「删除可省」。

`SKILL.md` 的「汇总口径」只讲禁止项（不得按列相加），四条口径的定义在本节，
不在两处各写一份。

## 分母的范围

`分母 = Σ cur_cost_mo`（findings.csv 全表求和），且**范围内每个资源恰好贡献一行**。

- 无建议的资源照样出行：`verdict=已合理配置` 或 `bucket=excluded`，`cur_cost_mo` 照填。
- 已停止的 EC2 实例 `cur_cost_mo=0`（计算不计费），其成本落在所属卷那一行。
- 必须计入：EC2 running、EKS 节点、EBS 卷、快照、NAT 小时费、ALB 小时费、
  RDS 实例、ElastiCache 节点、MSK broker、EKS 控制面。
  **EKS 节点出的是 `service=eks` 的节点行**（见填法表），**不再另出一份
  `service=ec2` 的行**——两份就是把节点算两遍。ElastiCache 节点与 MSK broker
  没有成员行，成本记在集群/复制组那一行上，靠 `instance_count` 带节点数。
- 必须在报告里**显式声明为未包含**：数据传输、NAT 数据处理费、ALB LCU、
  RDS/MSK 存储与备份、CloudWatch、未关联的公有 IPv4（`price-unknown`）。

**任何进入作用域的运行时输入都必须出现在路径或文件名里。**

聚合行的成本落点（**唯一定义在此**，`SKILL.md`「聚合行与成员行」只定形状）：

- **该组另有成员行时**，聚合行 `cur_cost_mo` **留空**、只带节省额，成本记在成员行上
  ——否则分母把成员算两遍。本版本只有一例：EKS 节点池（成员＝各节点）。
- **该组没有成员行时**，那一行**就是**成本行，`cur_cost_mo` **照填**，
  用 `instance_count` 带成员数。本版本有两例：MSK 集群（`instance_count=brokers`）、
  ElastiCache 复制组／集群（`instance_count=节点数`）。
  **对这两类留空 `cur_cost_mo` 会让整个服务从分母里消失**——分母漏项比重复计数更
  难发现，因为报告里不会出现任何多余的行。

判断用哪一种**不看动作能不能单独执行**（单个 broker 的机型同样不能单独改），
只看**这组成员在本 skill 的 inventory 里是否各自已经是一行**：是则聚合行留空成本，
不是则该行照填成本。形状怎么选见 `SKILL.md`「聚合行与成员行」。

实测依据：`insufficient-data` 行此前在赋成本之前就 return，漏掉两台合计
$286.67/mo，节省比例从 23.2% 虚高到 27.7%。分母只要有一条"看情况填"的规则，
两次运行的百分比就不可比——所以这里写成「每个资源恰好一行」，不留裁量空间。

## 托管服务候选小计（不计入头条数字）

三条托管判据不产出 `nb_save_mo`（node type 的价格与规格映射在采集侧，
候选由人工在变更方案里定，见 `sample-solve.md` 末段）。因此它们的节省额
**结构性不在路线一/二里**：那两条口径都是对 `nb_save_mo` / `b_save_mo` 求和，
而托管服务行这两列恒空。

**也不许写进 `other_save_mo`。** 那一列是给采集侧**已确定目标**的变更用的
（`gp2→gp3` 的目标是 `gp3`，节点池的目标机型由 bin-packing 算出）；托管服务的目标
node type **本 skill 不选**，金额取决于人工在变更方案里挑哪一档。把一个待人工确认的
数字放进「采集侧合计」，等于让它进头条——那正是 C4 的裁定要避免的。
所以托管候选的月省只出现在本节，`other_save_mo` 留空。

报告必须单列本节，逐条给出：资源 ID、当前规格与单价、目标 node type 与单价、
月省、依据数值、`blockers`，并明写**「本节金额不计入第 1 节合计」**。

小计与头条的关系只有一种合法写法：与那四条口径**并列**，各自标口径；
不得相加，也不得把本节金额悄悄并进摘要的任何一个数字。

实测规模：某 region 6 个 ElastiCache 节点降一档合计 $148.92/mo，
占该 region 路线一的 9–13%（两个 profile 各一个值）——不单列就等于丢掉，
而它恰好是该 region 第二大的可优化项。

### findings.csv 字段

**契约以下方代码块为准，由 `tests/test_csv_contract.py` 双向校验：
`core.py` 输出的键必须都在此，此处非派生列也必须都被输出。**

```csv-columns
account, region, service, rid, resource_name, bucket, verdict,
cur, cur_vcpu, cur_gib, cur_cat, cur_usd, cur_cost_mo,
required_vcpu, required_gib, required_gib_usable,
nonburst, nb_cat, nb_save_mo, nb_delta_vcpu, nb_delta_gib,
burst, b_cat, b_save_mo, b_delta_vcpu, b_delta_gib, burst_na,
az, instance_count, metric_coverage, confidence, stop_candidate,
evidence_cpu_p95, evidence_cpu_max, evidence_mem_p95, evidence_mem_max,
sample_points, window_profile, blockers, action_type, other_save_mo
```

**`other_save_mo` 是采集侧自建行唯一的节省额列。** 它存在的原因：`nb_save_mo` /
`b_save_mo` 只由 `evaluate()` 产出，且各自背着 `nb_cat` / `nb_delta_*` 与一个目标机型；
`gp2→gp3` 或节点池减容的差价**没有**候选机型、没有分类、没有 delta，写进那两列就是
往一列可审计的数字里塞一个无从复核的数字，而回归基线正是定义在那一列上。
所以另起一列，规则：

- 采集侧自建行**只填 `other_save_mo`**，`nb_save_mo` / `b_save_mo` 一律留空。
- `core.py` 产出的行**只填 `nb_save_mo` / `b_save_mo`**，`other_save_mo` 一律留空
  （含托管判据行——理由见上一节）。
- 没有任何一行同时带两边 —— 这就是「采集侧合计」可与路线一/二相加的构造性理由。
- 只有两类行填它：`gp2→gp3` 与 EKS 节点池聚合行。**走移除路径的行一律留空**
  （钱已经以全额 `cur_cost_mo` 进桶 B 合计），逐格见填法表。
- 这一列由采集侧填，所以它在派生列清单里；`core.py` 永远不产出它，
  因此它**进不了回归基线的那两个求和式**——加这一列不动任何基线数字。

**来自 `core.py` 的字段**（名字即实现字段名，不得重命名。**采集侧不要再合成这些列**）：

| 列 | 由谁产出 |
|---|---|
| `rid`、`cur`、`verdict` | 四条判据都产出 |
| `service` | 托管判据自带；EC2 行由 `main()` 补齐。**每行都有** |
| `bucket` | `main()`。取值只有三个，见下方枚举 |
| `stop_candidate` | `main()` 调 `is_stop_candidate()`。**三态**，见下方枚举。托管服务行恒为 `null`（没有桶 C） |
| `blockers` | **字符串数组，每行都有**（`main()` 保证，无阻断项时为 `[]`）。三条托管判据填自己的阻断原因；EC2 命中 `idle` 时 `main()` 追加两条。采集侧要补（如 `insufficient-data`）就 append，**不要换成字符串** |
| `cur_vcpu`、`cur_gib`、`cur_cat`、`cur_usd`、`cur_cost_mo`、`required_vcpu`、`required_gib`、`nonburst`、`nb_cat`、`nb_save_mo`、`nb_delta_vcpu`、`nb_delta_gib`、`burst`、`b_cat`、`b_save_mo`、`b_delta_vcpu`、`b_delta_gib`、`burst_na`、`az`、`metric_coverage`、`confidence` | 仅 EC2 判据（`evaluate`） |
| `required_gib_usable` | 仅 `eval_elasticache` |

`nb_*` / `b_*` 的 `delta` 与 `cat` 只在该侧确实选出候选时出现；`confidence`
在判定提前短路（`insufficient-data` / `spec-unknown` / `price-unknown` /
`excluded` / `metric-missing`）时不出现。缺列按空处理，不得填 0。

**`nonburst` 与 `burst` 在 `core.py` 的输出里是机型规格对象，不是字符串。**
对象含 `t` / `vcpu` / `gib` / `mib` / `usd` / `arch` / `ebs` / `net` / `burst` / `store`
（实测取自一次真实运行的输出）。CSV 的 `nonburst` / `burst` 单列**取 `.t`**，
其余字段按需渲染进报告正文，不另开列。同行的 `nb_cat` / `nb_save_mo` /
`nb_delta_vcpu` / `nb_delta_gib`（`b_*` 同理）都是**顶层键**，
唯独机型字符串在嵌套对象里——直接把对象写进 CSV 会得到一格 JSON，
按 `,` 分列的下游全部错位。

**由采集侧补齐的派生列**（`tests/test_csv_contract.py` 的 DERIVED 集合就是这一行，
两处必须逐项一致，有断言校验）：`account`、`region`、`resource_name`、`instance_count`、
`evidence_cpu_p95`、`evidence_cpu_max`、`evidence_mem_p95`、`evidence_mem_max`、
`sample_points`、`window_profile`、`action_type`、`other_save_mo`。

`instance_count` 是输出列名，它对应的**输入**字段叫 `count`（见 `cli-recipes.md` §7）。
两个名字不同是历史遗留：`core.py` 用 `count` 乘 `cur_cost_mo` 与两个 `*_save_mo`，
把输入字段写成 `instance_count` 会被静默忽略、按 1 计算，从而**按分组规模低估节省额**。

### verdict 枚举（由 `core.py` 产出，不得自造）

```verdict-enum
downsize | 已合理配置 | insufficient-data | spec-unknown | price-unknown
metric-missing | excluded | downsize-candidate | upsize-candidate | blocked
```

`downsize-candidate` 与 `blocked` 来自托管服务判据（`eval_rds` /
`eval_elasticache` / `eval_msk`）。`upsize-candidate` 由 `eval_rds()` 与
`evaluate()` **两侧**产出：RDS 侧的依据是信用超额，EC2 侧的依据是**持续项**
反推的需求量超过当前规格（**不是峰值项**——峰值项是降配方向的安全约束，
拿它反推规格不足会把闲置的小机器判成不足）。
`upsize-candidate` 不是降配建议——它表示该资源规格**已不足**，
出现在报告里必须与降配建议分开呈现，否则会被误读成可优化项。

### 枚举值

`SKILL.md` 的交付前自检要校验 `bucket` / `action_type` / `confidence` /
`window_profile` / `service` 五列的合法性。**合法值以下方代码块为准**——它是
`tests/test_csv_contract.py` 实际解析的那一份，下面的表只解释语义。
**不得自造取值。**

```enum-values
bucket:          idle | downsize | excluded
confidence:      high | medium | low | (empty)
stop_candidate:  true | false | null | (empty)
window_profile:  biz-hours | off-hours | weekend | full-window | (empty)
action_type:     downsize | stop | schedule | delete | storage-type
                 | next-rebuild-only | request-tuning | none
service:         ec2 | ebs | rds | elasticache | msk | eks | vpc
```

`(empty)` 是**该格留空**，不是字符串 `"empty"`，也不是 `0`。

| 列 | 产出方 | 语义要点 |
|---|---|---|
| `verdict` | `core.py` | 上一节十个值。描述**规格判据**的结论，不描述归属 |
| `bucket` | `core.py` 的 `main()` | **只有三个值**。归属由它定，排除清单按它筛 |
| `confidence` | `core.py` 的 `evaluate()` | 三档：`high`（样本充足且有内存数据）／`medium`（样本充足、无内存数据）／`low`（`0 < cpu_n < min_biz_hours_points`，样本不足——此时**不再区分内存口径**，样本量的问题盖过它）。判定提前短路（`insufficient-data` / `spec-unknown` / `price-unknown` / `excluded` / `metric-missing`）时留空。**托管判据行留空**——上两档由 `evaluate()` 的「有无内存数据」决定，托管侧没有这个轴。**采集侧自建行一律留空**，填任何值都是自造 |
| `stop_candidate` | `core.py` 的 `is_stop_candidate()` + 报告层 | **四种情形**，见下方小节。`false` 与 `null` 与留空三者互不等价 |
| `window_profile` | 采集侧（`agg.jq` 的 `bucket()`） | 三档 + `full-window`（**全部点，不是三档的算术合并**——`n`/`max` 可合并但 `p95`/`mean` 不行，见 `agg.jq` 的注释；这正是该档存在的理由）。**定义：同行 `evidence_*` 取自哪一档**；该行没有指标证据（纯配置类判断）则留空。这个定义是机械的——`window_profile` 有值 ⟺ `evidence_*` 有值，反之亦然 |
| `action_type` | 采集侧 | 见下方语义表。一资源一行 ⇒ 一行只有一个动作 |
| `service` | `core.py`（`ec2`/`rds`/`elasticache`/`msk`）+ 采集侧（`ebs`/`eks`/`vpc`） | 报告分节的分组键。前四个同时是 `core.py` 的**分派键**，写错会抛错或走错判据 |

`window_profile` 加 `full-window` 的理由：NAT / ALB 的闲置判据取**全窗口
的 max**（见 `cli-recipes.md` §2.6），三档里任一档都不能代表它。
`n` 与 `max` 确实可以由三档合并得到（§2.6 的 `series()` 就是**排除 full-window 行后**
把三档相加）；但 `p95` / `mean` / `min` 不能——并集的 p95 不等于各档 p95 的 max，
这才是 `agg.jq` 要单独发一档的原因。**不要按「三档合并」去重建 full-window 的 p95。**
此前枚举只有三档，两个 agent 各自选了一档填进去，同一个闲置 NAT 在两份报告里
拿到不同的 `window_profile`，而这一列正是复核"依据取自哪段时间"的唯一线索。

**为什么定义成「`evidence_*` 取自哪一档」而不是「判据取自哪一档」：** 后者在两类行上
无解——NAT 判过了但结论是"活跃"（有证据、无建议），EKS 节点池的 bin-packing 是
配置比配置（有建议、无指标证据）。绑到 `evidence_*` 上则每一行都有唯一答案，
且「留空」只有一个含义：**这一行没有指标证据**。

**`action_type` 语义（一行一个动作，按下方优先级取最终建议的那个）：**

```action-type-priority
delete > stop > schedule > storage-type > downsize > request-tuning > next-rebuild-only > none
```

| 值 | 含义 |
|---|---|
| `delete` | 删除 / 释放资源（桶 B 闲置：未挂载卷、闲置 NAT / ALB、未关联 EIP） |
| `stop` | 停止但保留资源与数据（停机后仍收存储费，如 RDS 的"快照 + 删除"路径） |
| `schedule` | 桶 C 定时启停候选（`allow_stop_recommendations=yes` 时才可能出现） |
| `storage-type` | 只换存储类型、容量与挂载不变（`gp2→gp3`） |
| `downsize` | 换更小规格（EC2 / RDS / ElastiCache / MSK 的降配） |
| `request-tuning` | 桶 E：调 K8s pod 的 requests，不动任何 AWS 资源 |
| `next-rebuild-only` | 桶 F：只能在下次重建时收益（存储只能扩不能缩） |
| `none` | 本行无建议 |

优先级不可换序：一个资源若既是删除候选又是降配候选，两个动作**不能同时执行**，
按优先级取高者，被舍弃的那个降级写进 `blockers`（与桶优先级同一套做法）。

两条容易踩的边界：

- **`bucket` 只有三个值，采集侧自建的行也必须用这三个。** 报告分节里的
  「桶 C / 桶 D / 桶 E / 桶 F」是**章节名**，不是 `bucket` 列的取值；
  区分具体动作的是 `action_type`。给 `bucket` 写 `schedule`、`request-tuning`
  之类会让「按 bucket 分组求和」与 `core.py` 产出的行对不上。
- **托管服务行永不出现 `bucket=idle`。** 闲置判据读的 `sus_cpu` / `net_mb_day`
  只在 EC2 侧定义，拿它判托管服务会因指标缺失恒返回"不闲置"，
  把「没做闲置评估」伪装成「不闲置」。`main()` 因此对托管服务显式只映射
  `downsize-candidate → downsize`，其余（含 `upsize-candidate`）→ `excluded`。

### `stop_candidate` 的四种情形

`core.py` 无条件产出这一列，取值只有三态；**第四种情形由报告层产生**：

```stop-candidate-states
`stop_candidate`（桶 C）：
- `true`  —— 是候选
- `false` —— 判过了，不是候选
- `null`  —— **判不了**（缺分档输入或采样量不足）
- **留空** —— `allow_stop_recommendations=no`，本次未评估
```

上面这个块由 `tests/test_csv_contract.py` 逐条解析：**四条都必须在，删掉任何一条即红。**

`null` 与留空是两件事，不得混用：`null` 是「查了但判不了」，
留空是「按输入要求没查」。填 `false` 会让报告看起来像「已经查过、没有可停的」。

**因此 CSV 的渲染规则是：`null` 写成字面量 `null`，只有「未评估」才是真正的空格。**
把 JSON 的 `null` 渲染成空格，两态在 CSV 里就都是空的，这条区分只剩纸面。
本列是全表唯一需要这条规则的列——其余列的"缺失"只有一种含义，留空即可。

`allow_stop_recommendations=no` 时该列**保留在 CSV 里但留空**，
并在报告正文写一句「桶 C 未评估（`allow_stop_recommendations=no`）」。
该列不得从 CSV 删除 —— 列数变化会破坏下游校验。

`allow_stop_recommendations` **不传进 `core.py`**：`core.py` 只做判断，
「要不要看桶 C」是报告层的决定。所以 `core.py` 的输出里这一列永远有值
（EC2 行为三态之一，托管服务行恒 `null`，因为没有桶 C），
是报告层在写 CSV 时把它清空。

实测的两种契约违反（同一份 skill、两个 runtime 各发明一种）：一个填了违反枚举的
字符串并把这一列排除在自己的自检之外，另一个直接删列（当时是 40 列变 39 列）——
两份 `findings.csv` 因此连列数都不同，无法比对。
**那两个列数都是当时的历史值，不是现在的契约**：本轮契约已扩到 **41 列**，
唯一真值源是上方的 `csv-columns` 块（`tests/test_csv_contract.py` 双向校验）。
本文件别处不再出现列数——读到 40 就当可比对的现值，是这条记录本身埋的坑。

### 字段规则

- **一资源一行，两个候选列组并列。** 不得每资源两行——任何人对 `nb_save_mo`
  求和都会把可节省总额翻倍高估。
- `burst` 为空时 `burst_na` 必须给出具体原因，不得留空。`core.py` 产出的原因文本：
  `超 T 系列上限 <burstable_max_vcpu>C/<burstable_max_gib>G`（两个数由
  `thresholds.json` 插值，**报告里不要写死**）/ `峰值需 N vCPU 或无更便宜的合规 T 机型` /
  `CPUSurplusCreditsCharged>0，当前规格已不足` /
  `CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用` / `baseline-unknown`
- `cur_cat` 与 `nb_cat` / `b_cat` 必须都输出，供人工复核跨用途
  分类的推荐（跨分类贡献了绝大部分节省，是刻意允许的，但必须可见；**具体比例不在此复述**，逐轮实测值见 `thresholds.md` 的跨分类小节 —— 本文件此前写死 85%，那个数已随判据改动过两轮）。
- **`confidence` 为 `high` 或 `low`、且 `required_gib < cur_gib` 的行，报告正文必须附一句人工复核
  提示**，例如"内存降幅依据 `mem_used_percent`，该指标不含可回收 page cache，
  文件缓存密集型负载请人工复核"。`high` 只说明"有内存数据"，不说明内存需求
  被测准了——口径与偏差方向见 `metrics-catalog.md` 的 `mem_used_percent` 一节。
  这条提示不因 `sizing_profile` 而免（两个预设用的是同一个有偏指标）。
- 无 vCPU/内存概念的资源（EBS 卷、快照、EIP、NAT、LB、EKS 控制面）**规格与容量列
  一律留空**：`cur_vcpu`、`cur_gib`、`required_vcpu`、`required_gib`、
  `required_gib_usable`、`nonburst`、`burst`、`nb_*`、`b_*`、`burst_na`、`cur_cat`。
  这类行若有节省额（只有 `gp2→gp3`），走 `other_save_mo`，不碰 `nb_*` / `b_*`。
  **但 `cur_cost_mo` 必须填**——分母要它（见「分母的范围」）：NAT / LB /
  EKS 控制面按小时价 × `HOURS_PER_MONTH`，EBS 卷与快照按 GB-月价 × 容量。
  `cur_usd` 是**小时**单价，只对按小时计费的资源填；EBS 卷与快照留空，
  它们不按小时计价，硬填一个"折算小时价"就是造一个 API 里不存在的数。
  唯一例外是未关联 EIP：单价取不到，`cur_cost_mo` 也留空（见下方填法表）。
- **`sample_points` 是「同行 `window_profile` 那一档」的有效数据点数**，两列必须同档。
  底线是机械的：`window_profile` 记的是同行证据取自哪一档，`sample_points` 记的是
  那一档取到了多少点，**同一行的两个数不许来自两个窗口**。按档分两条分支：
  - `window_profile=biz-hours`（判据行、EKS 节点成员行）：低于 `min_biz_hours_points`
    时 `bucket=excluded`、`action_type=none`、`blockers` 追加一条 `insufficient-data`。
  - `window_profile=full-window`（NAT / ALB / NLB 行）：`sample_points` 填全窗口档的
    点数，而**判 `bucket=idle` 要求它等于全窗口应有点数**（`WINDOW_DAYS × 24`，
    即 `cli-recipes.md` §3 闭合不变式算出的 `total`）。不足即该序列没覆盖整窗口
    ⇒ **不得填 `bucket=idle`**，改按「需人工确认」出行（`bucket=excluded`、
    `action_type=none`、`blockers` 追加 `insufficient-data`），金额不计入桶 B 合计。
    判成「活跃」的行不受这条约束——它的结论来自 `max > 0`，点数不足只影响
    「没人用」这一侧的证据（实测有一台活跃 ALB 的 `RequestCount` 只有 250 点）。
    一行用到多条序列时（ALB 的 `RequestCount` + `ActiveConnectionCount`）取
    **存在的那几条里最小的点数**；序列不存在的不参与，两条都不存在则
    `sample_points` 留空并走 `metric-missing`。ALB/NLB 的完整判定见 `cli-recipes.md` §2.6。
  - 两档混用是**偏松**的比较，不是无害的口径差：全窗口的点数天然大于同一资源的
    `biz-hours` 点数，拿它去比 `min_biz_hours_points`，一台只存在了几天的 LB
    就通过了一道本意要求「窗口内全程存在」的守卫，而这一行的动作是**删除**。
- **`confidence=low` 的行必须在报告正文标注样本量。** `core.py` 已把
  「样本 N 点 < 门限（占 X%）」写进 `blockers`，报告不得省略该句——它是读者
  判断这条建议可信度的唯一线索。低样本行**照常给出建议**（样本少不等于
  不给建议），但它的 p95 统计意义弱，正文须提示缩短观察期后复评。
- **摘要的四条口径照常包含 `confidence=low` 的行，但必须另给一行 breakout：**
  「其中 `confidence=low` 贡献 $X（占该口径 Y%）」。低样本行进头条是刻意的，
  breakout 让读者知道成分而不必翻 CSV。
- **否决项的尖峰说明不得省略。** `blockers` 里形如「…持续值（p95）未越界，
  但窗口内曾达 N（单次尖峰…）」的句子是判据**刻意不否决**的那一类，
  报告须原样呈现：读者要能看出「这次维护事件我们看见了、并且判断它不构成阻断」，
  而不是看起来像没查过。
- 金额列一律标注为按需理论值，不得与账单金额混用。
- 报告须标注实例的 `Monitoring.State`。为 `disabled`（basic monitoring）时写明
  **每 5 分钟发布且该值已是 5 分钟平均，<5 分钟的尖峰不可见**，
  尖峰型负载建议先开 detailed monitoring 再评估。
- 价格按 `(机型, UsageOperation)` 复合键取得。同一机型 Linux 与
  Windows+SQL Ent 的按需价差达 7.79 倍（实测 m5.xlarge：$0.248 vs $1.932），
  只按机型取价会严重失真。`Placement.Tenancy` 非 `default` 的实例
  标 `price-unknown` 排除。
- 排序：`bucket` 分组，组内按 `nb_save_mo` 降序（non-burstable 是始终适用的
  保守选项；burstable 侧可能为空，不能用作主排序键）。

## 采集侧自建行的字段填法（逐资源类型，每格都是定值）

`core.py` 只判 EC2 / RDS / ElastiCache / MSK 四类。其余的行由采集侧自己建，
而枚举值全是围绕"机型判断"设计的，没有一处说过一条快照行该填什么——
**实测后果**：同一支机队两个 runtime 的报告在这些行上分歧最大，
一边整段漏了 EKS（$70.08），一边把一个空序列 ALB 当可删除算进合计（$16.43）。

先记住三个列的语义分工，表里每一格都是它的直接推论：

- `verdict` = **规格判据的结论**。没有规格概念的资源（卷、快照、NAT、LB、EIP、
  控制面）本版本不做规格判断 ⇒ 默认 `excluded`。这一组里只有一个例外，且在下面
  逐格理由里单独论证：未关联 EIP 取 `price-unknown`（判不了的是价格）。
  **`gp2→gp3` 也是卷，同样是 `excluded`** —— 换存储类型不需要任何利用率数据，
  不是规格判据的结论；这一行的可执行性由 `bucket=downsize` 承载。
- `bucket` = **归属**。`downsize`＝本行有可执行的优化建议（**不限于降配动作**）；
  `idle`＝资源闲置、走移除路径；`excluded`＝无建议或判不了。
- `action_type` = **动作种类**。

因此 `verdict=excluded` 与 `bucket=idle`／`bucket=downsize` **同时出现并不矛盾**：
前者说"没做规格判断"，后者说"这资源闲置该移除"或"这一行有可执行建议"。
把这两列当成同一件事的两种写法，是这些行上最常见的自造来源。
**摘要的「可降配数」按 `bucket=downsize` 数，不按 `verdict` 数**，
所以这两列谁承载可执行性必须写死——否则同一支机队的头条条数因人而异。

**表的读法（`tests/test_csv_contract.py` 按这条规则逐格校验）：** 枚举列的每一格是
`／` 分隔的候选，每个候选的**第一个反引号词就是取值**，后面括号里是它的条件；
不含反引号词的格必须写「留空」。`core.py` 产出 = 该列由判据填，采集侧不要合成。

**`sample_points` 那一列是个例外：它填的是「点数取自哪一档」，不是点数本身。**
点数逐资源不同，钉不住；能钉住、且本轮真的错过的，是**取自哪一档**——所以这一格的
值域与 `window_profile` 相同，并且**必须与同行 `window_profile` 逐字相同**
（`test_fill_table_sample_points_share_the_window_with_window_profile` 逐行查）。
这一列存在的全部理由：此前 `sample_points` 在上文被定义成 `biz-hours` 档的点数，
而 NAT / ALB 四行的 `window_profile` 钉在 `full-window`，同一行的两个钉住事实用了
两个窗口；填 `biz-hours` 的与填 `full-window` 的都能说自己对，而这四行的
`action_type` 是 `delete`。填法表此前没有这一列 ⇒ 逐格合法性断言看不见它。

| 资源类型 | `service` | `cur` | `verdict` | `bucket` | `action_type` | `confidence` | `sample_points` | `window_profile` | `cur_cost_mo` | `other_save_mo` |
|---|---|---|---|---|---|---|---|---|---|---|
| EC2 running（判据行，作对照） | `ec2` | 实例机型 | `core.py` 产出 | `core.py` 产出 | `schedule`（`stop_candidate=true` 时）／`downsize`（`verdict=downsize` 时）／否则 `none` | `core.py` 产出 | `biz-hours` | `biz-hours` | `core.py` 产出 | 留空 |
| EC2 running 且命中闲置 | `ec2` | 实例机型 | `core.py` 产出 | `idle`（`core.py`） | `delete` | `core.py` 产出 | `biz-hours` | `biz-hours` | `core.py` 产出 | 留空 |
| EC2 `state=stopped` | `ec2` | 实例机型 | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | `0` | 留空 |
| EBS 卷 `gp2` 且可转 `gp3` | `ebs` | `gp2` | `excluded` | `downsize` | `storage-type` | 留空 | 留空 | 留空 | 当前卷月额 | gp3 与 gp2 的月额差 |
| EBS 卷 `state=available` | `ebs` | 卷类型原文 | `excluded` | `idle` | `delete` | 留空 | 留空 | 留空 | 当前卷月额 | 留空 |
| EBS 卷挂在 `state=stopped` 实例上 | `ebs` | 卷类型原文 | `excluded` | `idle` | `delete` | 留空 | 留空 | 留空 | 当前卷月额 | 留空 |
| EBS 卷 其他（已是 `gp3` / 挂 running 实例） | `ebs` | 卷类型原文 | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | 当前卷月额 | 留空 |
| 快照 | `ebs` | `snapshot` | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | 快照存储月额 | 留空 |
| NAT 闲置 | `vpc` | `nat-gateway` | `excluded` | `idle` | `delete` | 留空 | `full-window` | `full-window` | 小时费月额 | 留空 |
| NAT 活跃 | `vpc` | `nat-gateway` | `excluded` | `excluded` | `none` | 留空 | `full-window` | `full-window` | 小时费月额 | 留空 |
| ALB / NLB 闲置 | `vpc` | `application`／`network` | `excluded` | `idle` | `delete` | 留空 | `full-window` | `full-window` | 小时费月额 | 留空 |
| ALB / NLB 活跃 | `vpc` | `application`／`network` | `excluded` | `excluded` | `none` | 留空 | `full-window` | `full-window` | 小时费月额 | 留空 |
| EIP 未关联 | `vpc` | `eip` | `price-unknown` | `idle` | `delete` | 留空 | 留空 | 留空 | 留空 | 留空 |
| EKS 节点池（聚合行） | `eks` | 节点池当前机型 | `downsize` | `downsize` | `downsize` | 留空 | 留空 | 留空 | **留空**（成本在成员行） | (当前节点数 − 理论节点数) × 单节点月额 |
| EKS 节点（成员行） | `eks` | 节点实例机型 | `excluded` | `excluded` | `none` | 留空 | `biz-hours` | `biz-hours` | 该节点月额 | 留空 |
| EKS 控制面 | `eks` | `control-plane` | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | 小时费月额 | 留空 |
| 桶 E pod request 调优 | `eks` | `pod-requests` | `downsize` | `downsize` | `request-tuning` | 留空 | 留空 | 留空 | 留空（非 AWS 资源） | **留空，不是 `0`** |
| RDS / ElastiCache / MSK（判据行，作对照） | `core.py` 产出 | `core.py` 产出 | `core.py` 产出 | `core.py` 产出 | `downsize`（`verdict=downsize-candidate` 时）／`next-rebuild-only`（唯一发现是存储过度预配时）／否则 `none` | 留空 | `biz-hours` | `biz-hours` | 采集侧填（见下） | 留空 |

逐格理由，只记那些两个 runtime 真的分歧过、或看起来反直觉的：

- **`cur` 的取值分两类。** 卷类型（`gp2`/`gp3`/`io1`/`io2`/`st1`/`sc1`/`standard`，
  七个值）与负载均衡器类型（`application`/`network`/`gateway`）是 **API 返回值原文**
  （实测 `aws ec2 describe-volumes` 与 `aws elbv2 describe-load-balancers` 的
  `Possible values`）；`snapshot` / `nat-gateway` / `eip` / `control-plane` /
  `pod-requests` 是**本契约自定的固定字面量**，没有对应 API 字段，照抄即可，不要改写。
- **`other_save_mo` 只出现在两行上。** `gp2→gp3`（存储类型差价）与 EKS 节点池聚合行
  （减节点的整机月额）。走移除路径的行（未挂载卷、闲置 NAT / ALB、未关联 EIP）
  **一律留空**：它们的钱已经以全额 `cur_cost_mo` 记进桶 B 合计，再填一次就是
  同一笔钱两个口径各算一遍。这也是「采集侧合计」限定 `bucket == "downsize"` 的原因。
- **桶 E request 调优行的 `other_save_mo` 是留空，不是 `0`。** 留空＝这一行不承载
  金额（钱记在节点池聚合行上）；`0` 会被读成「调完 request 一分钱不省」，
  而事实相反——它是节点数下降的前提条件。
- **EC2 判据行的 `action_type` 有三个分支，`schedule` 优先于 `downsize`。**
  一台实例可以既是桶 C 候选又是降配候选，但一行只能有一个动作，
  按优先级表取 `schedule`，降配方案降级进 `blockers`。
  `allow_stop_recommendations=no` 时 `stop_candidate` 留空，这个分支自然不触发——
  **但规则必须先写在这里**，否则第一次把该输入打开时两个 agent 又各自发明一次。
- **EIP 是 `price-unknown` 而不是 `excluded`。** 未关联公有 IPv4 的单价经 pricing API
  三条路都取不到（见 `cli-recipes.md`），所以"判不了的是价格，不是该不该释放"。
  `bucket` 仍是 `idle`（它确实闲置），但 `cur_cost_mo` 留空 ⇒ 它对桶 B 合计贡献 0，
  报告须在"未包含项"里点名。**不得用记忆里的单价顶替**。
- **`bucket=idle` 优先于 `verdict` 决定的归属。** 这不是新规则，是 `core.py` 的
  既有行为：`main()` 先查 `is_idle()`，再才按 `verdict` 落桶，所以一台
  `price-unknown` 的闲置实例也进 `idle`。采集侧自建行沿用同一优先级。
- **NAT / ALB 活跃行的 `window_profile` 照填 `full-window`。** 判据跑过了、
  结论是"活跃"，这一列记的是**依据取自哪段时间**，不是"有没有建议"。
  留空会让"判过了是活跃"与"没判"看起来一样。
- **空序列的 ALB 不等于可删除。** 实测出现过 `RequestCount` 序列**不存在**而
  `ActiveConnectionCount` max 非零 ⇒ 实际活跃。零 HTTP 请求 ≠ 零连接。
  **判据本身不在本文件**：三态矩阵、覆盖度门槛与可执行实现都在
  `cli-recipes.md` §2.6，本文件只管状态定下来之后这一行怎么填。
  这里只留「为什么需要两个指标」这条理由，**不复述条件**——同一条判据此前在五个文件
  各有一份、互不相同，其中两份照字面读会把活跃 LB 报成可删除。
- **EKS 节点成员行的 `window_profile` 是 `biz-hours`，而聚合行留空。** 不矛盾：
  本列记的是同行 `evidence_*` 取自哪一档。成员行带节点自身的 biz-hours 利用率
  （节点池结论的旁证，必须可见），聚合行的依据是 bin-packing 的配置比配置、
  没有指标证据，所以留空。**两行的 `evidence_*` 与 `window_profile` 同时有或同时无。**
- **一个节点池含多个机型时，按机型各出一条聚合行。** 托管 nodegroup 的
  `instanceTypes` 可以有多个，而 bin-packing 的目标机型也是按机型给的，
  所以 `cur` 恒是**一个**机型字符串，不写 `mixed` 之类的合成值——
  合成值没法反查单价，节省额就无法复算。
- **EKS 节点不进 `solver-in.json`。** 节点行 `service=eks`、不走 `core.py`：
  托管 nodegroup 的机型只能整池改，**单个节点无法单独降配**，逐节点出降配建议
  等于给出不可执行的动作，且与节点池聚合行的节省额重复计数。
  节点级结论只出现在聚合行上。
  （采集侧与本条一致：`cli-recipes.md §7.2` 的主循环喂 `ec2-standalone.json`、
  `§7.3 ①` 也按它比对行数，两份文件都不再拿 `ec2.json` 当 solver 的分母。
  **节点不进 solver ≠ 节点不进分母**——节点行由 `§4` 另行产出。）
- **桶 E 的 request 调优行不带金额。** 调 requests 本身不改任何 AWS 资源；
  钱是通过"节点数减少"落地的，那笔节省记在节点池聚合行上。
  两处都记 = 同一笔钱算两遍。
- **托管服务行的 `cur_cost_mo` 也要采集侧填。** 三条托管判据不产出成本列
  （实测：一次真实运行里 `eval_rds` / `eval_msk` 只回 `rid` / `service` / `cur` /
  `verdict` / `blockers` / `stop_candidate` / `bucket`，`eval_elasticache` 多一个
  `required_gib_usable`）。`core.py` 的 `HOURS_PER_MONTH` 换算只发生在 EC2 路径上，
  所以托管行按「单价 × 节点数/broker 数 × `HOURS_PER_MONTH`」自己算，
  节点数同时写进 `instance_count`。不填 ⇒ 分母漏掉整个托管服务。
- **`0` 与留空不同。** 已停止实例的 `cur_cost_mo` 是**确定的 `0`**（计算不计费），
  EIP 的 `cur_cost_mo` 是**留空**（价格未知）。前者进分母贡献 0，
  后者根本不在分母里、必须在"未包含项"列出。两者写成同一个值会让
  "已知为零"与"不知道"不可区分。

## 每条建议的可执行性要求

输出边界是纯只读报告，不给变更命令。因此每条必须精确到 devops 能直接判断、
无需回头询问：

资源 ID、当前规格与单价、反推出的需求量、两个候选及各自单价与节省、
依据数值（持续 p95 / 峰值 max / 采样点数 / 时段档）、阻断条件、confidence、
以及**分类是否跨越**。
