# 指标目录

核实日期：2026-09-03 · 验证 region ap-northeast-1 与 us-west-2

**2026-09-04 第一轮全文复核：没有一条结论被推翻**（漂移的只有若干计数值，
已就地标成观测值，A/B 分类见 `cli-recipes.md §0.1`）。逐项结果见文末
「2026-09-04 复核记录」——**「全部仍成立」本身也记进去了**，
这样下一个人不必重跑就知道哪些查过、什么时候查的。

**同日第二轮复核推翻了两条**，都已就地改掉并留了撤回说明：
ELB 小节的「`RequestCount` 全窗口恒 0 或序列不存在 ⇒ 闲置」、
EC2 小节的「`Stat=Average` 再乘换算系数」。
**这一条本身就是那轮复核的教训**：第一轮问的是「这些数字还对不对」，
而这两条错在**规则被本轮的其他改动取代了**——数字没漂，结论过期。
两个问题不一样，只问前者会漏掉后者。改这份文件的人两个都要问一遍。

每个指标标注它喂给 solver 的哪个输入：

```
cpu_sustained = 小时级 Average 序列取 p95      cpu_peak = 小时级 Maximum 序列取 max
mem_sustained / mem_peak 同理
blocker       = 只用于阻断判断，不参与 solver
floor         = 下限型判据，须显式采 Stat=Minimum（见 cli-recipes.md §2.0 ⑤）
```

**不取 CloudWatch 的 `p95` stat**——它是每小时内的 p95，跨小时聚合无意义。
每指标默认只取 `Average` 与 `Maximum`，两类例外（规则在 `cli-recipes.md §2.0 ⑤`）：
`floor` 类**额外加** `Minimum`；**计数类（Sum 语义）只取 `Sum`**，
`Average`/`Maximum` 都不取——EC2 的 `NetworkIn`/`NetworkOut`/`EBSRead|WriteBytes`
与 ALB 的 `RequestCount`/`ActiveConnectionCount` 属于这一类。

## namespace 实测存量

**这张表的数字全是 A 类观测值**（`观测值 @2026-09-04`，见 `cli-recipes.md §0.1`）：
指标条数随资源增减与新指标发布而变，**对不上属正常**。有判据意义的只是
「是 0 还是非 0」——那决定某个服务能不能评估，那一列才是要当断言看的。

| namespace | ap-northeast-1 | us-west-2 | 状态 |
|---|---|---|---|
| AWS/EC2 | 239 | 383 | 可用 |
| AWS/EBS | 212 | 282 | 可用（us-west-2 本次首次单独计数） |
| AWS/Kafka | 263 | 157 | 可用 |
| AWS/ApplicationELB | 262 | 432（2026-09-03 为 411） | 可用 |
| AWS/NATGateway | 32 | 62 | 可用 |
| CWAgent | 14 | 36 | 可用（含内存与磁盘，但覆盖率极低，见下） |
| AWS/RDS | 0 | 325 | **us-west-2 已实测** |
| AWS/ElastiCache | 0 | 1036（2026-09-03 为 500） | **us-west-2 已实测** |
| AWS/NetworkELB | 0 | 0 | 两个 region 均无 NLB ⇒ **仍未实测** |
| ContainerInsights | 0 | **0** | us-west-2 有 EKS 集群但该 namespace 为空，pod 级分析不可得 |

**ElastiCache 那格一天翻了一倍，而资源一个没变**（复核确认仍是同一个 6 节点复制组
＋一个单节点）。所以指标条数**不能当资源规模的代理**：它还随 AWS 给该 namespace
新增指标、以及维度组合增多而涨。想知道有多少资源就去 `describe-*`，不要数指标。

## EC2 — `AWS/EC2`，维度 `InstanceId`

| 指标 | stat | solver 输入 | 状态 |
|---|---|---|---|
| CPUUtilization | Average, Maximum | cpu_sustained, cpu_peak | 已实测 |
| NetworkIn | **Sum**（只取 Sum，见下） | 闲置判据 `net_mb_day` | 已实测 |
| NetworkOut | **Sum**（只取 Sum） | 闲置判据 `net_mb_day` | 已实测 |
| EBSReadBytes | **Sum**（只取 Sum） | EBS 带宽约束 `ebs_need` | 已实测 |
| EBSWriteBytes | **Sum**（只取 Sum） | EBS 带宽约束 `ebs_need` | 已实测 |
| CPUCreditBalance | Average, **Minimum** | blocker / floor（是否触底） | 已实测 |
| CPUCreditUsage | **计数类**，Average, Maximum ⚠️ | blocker（burstable）。⚠️ = 计数类配非 Sum stat，**目前无判据消费**，同 MSK 侧那行 | 已实测 |
| CPUSurplusCreditBalance | Maximum | blocker（burstable） | 已实测 |
| CPUSurplusCreditsCharged | Maximum | blocker（**当前机型已是 T 系列**且 >0 ⇒ 抑制 burstable 选项）；**仅 `t*` 发布**，非 burstable 缺失属「不适用」不是「缺失」，判据不走 fail-closed | 已实测 |

`CPUUtilization` 在 T 机型上同样按完整 vCPU 百分比计量，所以
`cur_vcpu × sus_cpu%` 是有效的绝对持续消耗量，与 baseline 无关。

**`NetworkIn` / `NetworkOut` / `EBSRead|WriteBytes` 是按发布粒度累计的量，不是速率——
所以它们只取 `Stat=Sum`，`Average` / `Maximum` 都不取。** Σ Sum 就是窗口内总字节数，
换算只剩除以窗口长度这一步，没有任何依赖发布粒度的系数。口径与实测依据在
`cli-recipes.md` §7.1（采集模板在 §2.1 ⑤），**本文件不复述算式**。

> **已撤回的写法（2026-09-04 起）：`Stat=Average` 再乘一个换算系数。**
> 本文件此前教的是「乘 `86400/300 = 288`，不是乘 24」。那个系数取决于
> **SampleCount 而不是发布粒度**，本 skill 在它上面连续写错三次
> （×24 → ×288 → ×1440），**每一次都标着「实测」**。×24 低估 12 倍、×288 低估 5 倍。
> 而闲置门限 `idle_net_mb_day` 本来就很小、这一行的动作是**删除**——
> 换算系数只要错一次，有流量的实例就被报成可删除（实测 11 台被误判）。
> 整类错误靠改采 `Sum` 消掉，不是靠把系数改对。
> 留着这段是因为「标了实测的数字也可能是错的」本身是这份文档要传的教训。

信用指标只在 `t*` 实例类上存在；对非 T 实例请求会得到空序列（真实缺失，非 bug）。
因此 T 系列须单独一批采集，避免空序列噪音掩盖真正的维度错误。

## EC2 内存与磁盘 — `CWAgent`

**维度组合必须从 `list-metrics` 原样搬，不能硬编码。**

实测发现同一账号内**不同实例的维度集不一致**（观测值 @2026-09-04：
**两种形态今天都还在**，`mem_used_percent` 在 us-west-2 同时以下面两种维度集发布）：

| 实测到的维度组合 | 说明 |
|---|---|
| `[ImageId, InstanceId, InstanceType]` | agent 配了 `append_dimensions` 的常见形态 |
| `[InstanceId]` | 同账号另一台实例只发布这一个维度 |

维度集取决于 agent 的 `append_dimensions` 配置，**逐实例而异**。
按固定三维度拼会让只发布 `InstanceId` 的实例返回空序列。
用 `references/mdq-dims.jq` 从 `list-metrics` 回包原样搬。

**复核这条时有个陷阱，值得单独写下来。** 想确认「是否还存在单维度实例」，
**不能**把所有维度名摊平去看：

```bash
# 错的：摊平成维度名的并集，[InstanceId] 那条被三维度那条完全掩盖，
# 结果看起来像"单维度形态已消失"——一个假阴性。
aws cloudwatch list-metrics --region $R --namespace CWAgent \
  --metric-name mem_used_percent --query 'Metrics[].Dimensions[].Name' \
  --output json | jq -c 'unique'
# => ["ImageId","InstanceId","InstanceType"]     ← 看不出还有单维度的

# 对的：逐条保留各自的维度集
aws cloudwatch list-metrics --region $R --namespace CWAgent \
  --metric-name mem_used_percent --output json \
  | jq -c '.Metrics[] | [.Dimensions[].Name] | sort'
# => ["InstanceId"]                              ← 还在
# => ["ImageId","InstanceId","InstanceType"]
```

两条命令都实跑过。**这个错法会让人以为本节已过期从而删掉这条规则**，
而规则一旦删掉，那台单维度实例就会静默返回空序列。

| 指标 | solver 输入 | 状态 |
|---|---|---|
| mem_used_percent | mem_sustained, mem_peak | 已实测，口径见下（**不是"内存占用率"的直觉含义**） |
| disk_used_percent | EBS 容量过大判据 | 已实测（维度还含 `device`/`fstype`/`path`，一个实例多条） |

**覆盖率实测极低**（观测值 @2026-09-04，两次测量**一模一样**）：
`mem_used_percent` 在 ap-northeast-1 覆盖 2/13 台、
us-west-2 覆盖 2/18 台；`disk_used_percent` 合计只覆盖 3/31 台。
后果是绝大多数实例 `required_gib = cur_gib`（内存不动）、`confidence` 上限 `medium`，
且**卷容量是否过大完全判不了**。这是缺口不是缺陷，必须写进报告第 2 节。

### `mem_used_percent` 的口径：`mem_used / mem_total`，**不含可回收的 page cache**

这是 CloudWatch agent `mem` 插件的算法，不是 OS 报的"内存压力"。
刻度 0–100（实测 `Unit=Percent`；两 region 各取一台覆盖到的实例，
最近一个小时桶 avg 分别为 5.03 与 4.71）。

**口径和偏差都是实测出来的，不是照文档抄的。** us-west-2 有一台实例把
`mem` 插件的全套指标都发了（`mem_total` / `mem_used` / `mem_free` /
`mem_available` / `mem_used_percent`），可以直接对账。同一小时桶的 Average：

| 量 | 值 |
|---|---|
| `mem_total` | 8,112,578,560 B（7.56 GiB） |
| `mem_used` | 1,339,179,417.6 B |
| `mem_free` | 5,010,021,376 B |
| `mem_available` | 6,337,631,300 B |
| `mem_used_percent` | 16.50744 |

三条结论：

1. **公式坐实**：`mem_used / mem_total × 100 = 16.50744`，与发布的
   `mem_used_percent` **逐位相同**。
2. **页缓存既不在 `used` 也不在 `free`**：`mem_used + mem_free` 比 `mem_total`
   少 **1.64 GiB**，那部分就是 buffers + cache。其中可回收的
   （`mem_available − mem_free`）是 **1.24 GiB = 整机内存的 16.4%**。
3. **偏差量级**：真正没在存东西的比例是 `(total − free)/total = 38.24%`，
   而指标报的是 **16.51%**——同一时刻**差 21.74 个百分点**。
   这台机器并不是数据库或构建机，差距已经这么大。

**页缓存被算进"未使用"。** 于是对重度依赖文件缓存的负载——数据库、构建机、
日志处理、任何靠 page cache 挡住磁盘 I/O 的服务——这个指标会把内存需求
**系统性低估**，据它反推的 `required_gib` 偏小、定档偏紧。关键在于：
缓存收益的丧失只在降配**之后**才表现出来（命中率下降、磁盘 I/O 上升），
降配**前**的 `mem_used_percent` 里完全看不见，所以这不是"多采一个窗口"能补的。
`agg.jq` 的 p95 口径（最近秩、不插值）**同向**再压低一点，两者叠加，
见 `thresholds.md`「报告里的 p95 是最近秩、不插值」。

**对策是相对护栏 `max_mem_reduction_ratio`**，不是给内存设绝对下限。
完整推理与边界（含 `ceil()` 在小内存规格上吞掉两预设差别的区间）在
`thresholds.md` 的 `max_mem_reduction_ratio` 那节，本文件不复述。

**报告层还有一条要求**：`confidence=high` 的内存降幅行必须附人工复核提示。
规范写在 `report-template.md` 的「字段规则」，那里是唯一真值源。

## EBS — `AWS/EBS`，维度 `VolumeId`

**本表四行目前没有任何判据消费**（见下方「谁在消费这张表」），所以 stat 列写的是
「要问哪个问题就取哪个 stat」，不是某条判据的既定要求。

| 指标 | 类别 | stat（按你要问的问题选） | 用途 |
|---|---|---|---|
| VolumeReadOps | 计数类 | 窗口总操作数 ⇒ `Sum`；每发布间隔的操作数 ⇒ `Average`/`Maximum`，**须同时写明除以发布间隔** | 尚无消费者（不是闲置判据，见下） |
| VolumeWriteOps | 计数类 | 同上 | 尚无消费者（不是闲置判据，见下） |
| VolumeReadBytes | 计数类 | **`Sum`**（窗口总字节／平均吞吐，零换算假设）；要**峰值**吞吐才取 `Maximum`，**且须除以发布间隔**才是 MB/s | 吞吐参考 |
| VolumeWriteBytes | 计数类 | 同上 | 吞吐参考 |

**这四行都是计数类（每发布间隔的累计量），所以 stat 必须带着「回答哪个问题」一起写。**
`Maximum` 在计数类上**不是错的，是没有标注**——「单个发布间隔内的最大计数」本身是个
有意义的量（除以发布间隔就是峰值速率），但不写那一步除法就退化成一个无单位的数，
而**无标注的每间隔计数正是本轮撤回的那类**（见 EC2 小节的撤回块）。
所以：要窗口总量或平均速率就取 `Sum`（零换算）；要峰值速率就取 `Maximum` 并写明
「÷ 发布间隔」。两种都对，含糊不对。

**`ReadIOPS`/`WriteIOPS`（RDS 小节）与 `BytesUsedForCache`（ElastiCache 小节）不属这一类**，
不要顺手一起改：前者名字里就带 per second、本身已是速率；后者是瞬时驻留字节（gauge），
跨小时求和得到一个没有指代的数。

**谁在消费这张表：目前一个都没有。** 卷容量是否过大需 `CWAgent disk_used_percent`。
而**EBS 的闲置判据不读任何指标**——`thresholds.md` 定义的是 `state=available`（未挂载）
与「挂在 `state=stopped` 实例上」，两条都是配置判断。
本表此前把 `Volume*Ops` 的用途写成「闲置卷判据」、并写「纯 `AWS/EBS` 只能判闲置」，
那是**断言了一个不存在的消费者**，会让读这两行的人以为它们是承重的。
真要新增「低 IOPS 卷」这类判据，先回到上面那段把 stat 与问题定下来，
别沿用本表的 `Average` 默认值。

## MSK — `AWS/Kafka`，维度 `Cluster Name` + `Broker ID`（**名字带空格**）

已实测两个集群，覆盖 `EnhancedMonitoring` 的 `DEFAULT` 与
`PER_TOPIC_PER_PARTITION` 两档。

（**stat 列必须在这里出现，哪怕实现在 `mdq-msk.jq`。** 这张表原来没有 stat 列，
于是对"计数类有没有配错 stat"的全文扫描**整张表不可见**——扫的人会得到一个假的干净。
类别列同理：它是判断 stat 对不对的前提。）

| 指标 | 类别 | stat（实现在 `mdq-msk.jq`） | solver 输入 | `DEFAULT` 下可用 | 刻度（实测） |
|---|---|---|---|---|---|
| CpuUser + CpuSystem（metric math 逐点相加） | gauge | Average, Maximum | cpu_sustained, cpu_peak | ✅ | 0–100 |
| KafkaDataLogsDiskUsed | gauge | Average, Maximum | 降配前置 max < `msk_disk_used_max` | ✅ | **0–100**（实测 0.02 与 0.353） |
| MemoryUsed | gauge | Average, Maximum | mem 参考 | ✅ | 字节（实测 1.1–1.6e9） |
| BytesInPerSec / BytesOutPerSec | **速率**（名字里就带 per second） | Average, Maximum | 负载画像 | ✅ | B/s |
| UnderReplicatedPartitions | gauge | Average, Maximum | blocker，>0 禁止降配 | ✅ | 计数 |
| **RequestHandlerAvgIdlePercent** | gauge | Average, Maximum | 降配前置 > `msk_handler_idle_min` | ❌ **不发布** | **0–1**（实测 0.999–1.002） |
| CPUCreditBalance | gauge（余额） | Average, Maximum | blocker（broker 为 T 机型时出现） | ✅ | — |
| CPUCreditUsage | **计数类** | Average, Maximum ⚠️ | blocker（同上） | ✅ | — |

`CPUCreditUsage` 那行的 ⚠️ 是**已知的计数类配非 Sum stat**，与 EC2 侧同一行同因：
**目前没有任何判据消费它**，所以不改；真要用它必须先按 EBS 小节那段把
「问哪个问题、取哪个 stat」定下来。`BytesInPerSec` 已是速率，`Sum` 对它无意义。

**原文档写的"前提 `EnhancedMonitoring >= PER_BROKER`"过严。** 实测 `DEFAULT` 下
per-broker 的 CPU / 磁盘 / URP / 内存 / 吞吐全都有，**唯一缺的是
`RequestHandlerAvgIdlePercent`**。该指标是降配前置条件，缺失 ⇒ 不产出降配建议。

**但"提升 `EnhancedMonitoring` 再等一个窗口"这条缺口不是无条件写的。**
`core.py` 先查同形态下**有没有更便宜的候选机型**（`cheaper_candidate_exists`）：
没有则直接判「已合理配置」，**不再要求任何前置指标**。实测
`kafka.t3.small` 是两个 region 最便宜的 broker 机型（次便宜的贵约 4.5 倍），
对它写这条缺口等于让客户为一条不可能存在的建议改配置、白等一个窗口。
判据顺序见 `core.py` 的 `eval_msk`，字段契约见 `sample-solve.md`。

同 namespace 内刻度不统一（`KafkaDataLogsDiskUsed` 0–100 vs
`RequestHandlerAvgIdlePercent` 0–1）。判据刻度写错会让它**永不成立、建议被静默吞掉**。

## RDS — `AWS/RDS`，维度 `DBInstanceIdentifier`

**已于 2026-09-03 在 us-west-2 首次实测**：2 个 MySQL 8.0 Multi-AZ 实例
（一个 `db.t4g.*` burstable、一个 `db.m5.*`）+ 1 个 Aurora PostgreSQL
`db.serverless`（按规则排除）。指标名与维度名与文档一致。

| 指标 | stat | 用途 | 状态 |
|---|---|---|---|
| DBLoad | Average, Maximum | **第一判据** cpu_sustained | 已实测（**仅 PI 已开的实例有**） |
| CPUUtilization | Average, Maximum | 次级判据 / PI 未开时的替代 | 已实测 |
| FreeableMemory | Average, Maximum, **Minimum** | mem 反推 + **floor 阻断** | 已实测 |
| FreeStorageSpace | Average, **Minimum** | 存储过配判据（桶 F） | 已实测 |
| CPUCreditBalance | Average, **Minimum** | blocker（`db.t*` 是否触底） | 已实测 |
| CPUSurplusCreditsCharged | Maximum | **blocker，>0 = 规格已不足**；**仅 `db.t*` 发布**，非 burstable 缺失属"不适用"不是"缺失" | 已实测 |
| DatabaseConnections | Average, Maximum | 负载画像 | 已实测 |
| ReadIOPS / WriteIOPS | Average, Maximum | 存储画像 | 已实测 |

三条实测得到的判据修正：

1. **`FreeableMemory` 必须取 `Minimum`。** 阻断判据是"窗口最小值 < 实例内存 15%"。
   空闲内存越多越安全，用 `Maximum` 或 `Average` 的 p95 是**取错方向**，
   会把危险实例判成安全。
2. **`CPUSurplusCreditsCharged > 0` 是独立否决项，优先级高于 `DBLoad`。**
   实测某 `db.t4g.medium`：`DBLoad` p95 = 0.547 < `0.5 × 2 vCPU` ⇒ 降配前置**满足**，
   但 `CPUCreditBalance` 窗口最小值 = **0**（上限 576）、
   `CPUSurplusCreditsCharged` **窗口内单小时最大 = 730.6** ⇒ 当前规格已不足，是**升配**候选。
   （**这个数的单位是"单小时最大"不是"窗口累计"**：该指标采的是 `Maximum`，
   见本文件 RDS 表那一行。判据是 `> 0`，计数类在 max 上 > 0 与在 sum 上 > 0 等价，
   所以否决项照样成立、方向也安全——错的只是标注。此前三处文件都写成「窗口累计」。）
   只看 `DBLoad` 会给出错误的降配建议。
3. **只用 `DBInstanceIdentifier` 单维度。** 该 namespace 还发布 `DatabaseClass` /
   `EngineName` / `DBClusterIdentifier` / `Role` 等聚合维度，混用会重复计数。

**仍未实测**：Aurora provisioned、PostgreSQL / Oracle / SQL Server 引擎、
Single-AZ 部署、只读副本。指标名预期相同但未验证。

## ElastiCache — `AWS/ElastiCache`，维度 `CacheClusterId`

**已于 2026-09-03 在 us-west-2 首次实测**：一个 Redis 7.1 复制组
（2 shard × 3 node，`cache.t3.medium`）+ 一个单节点 `cache.t4g.micro`。
指标名与维度名与文档一致。

| 指标 | stat | 用途 | 刻度（实测） |
|---|---|---|---|
| **EngineCPUUtilization** | Average, Maximum | cpu_sustained, cpu_peak | **0–100**（实测 max 0.40–0.45） |
| DatabaseMemoryUsagePercentage | Average, Maximum | mem_sustained, mem_peak | **0–100**（实测 max 0.436–0.445） |
| BytesUsedForCache | Average, Maximum | 数据量绝对值 | 字节（实测 max ≈ 10.9 MB） |
| Evictions | **计数类**，Maximum | blocker，**单小时最大 > 0** 即禁止降配（判据是 `> 0`，与窗口累计 > 0 等价）。⚠️ `sample-solve.md` 的字段名叫 `evictions_sum`，那是**历史命名**，采的是 `Maximum` | 计数（实测 0） |
| ReplicationLag | Maximum | blocker，max >= 1s | **秒**（实测 0–0.009） |
| CPUCreditBalance | Average, **Minimum** | blocker（`cache.t*` 是否触底） | — |
| CurrConnections / CurrItems | Average, Maximum（gauge，瞬时值） | 负载画像 | 计数 |

- **必须用 `EngineCPUUtilization`，不得用 `CPUUtilization`。** 后者含后台线程，
  恒高于前者，会系统性误判成"负载不低不能降"。
  **「高估几倍」是 A 类观测值，方向才是断言**——两次测量差得很远：

  | 测量 | `EngineCPUUtilization` max | `CPUUtilization` max | 倍数 |
  |---|---|---|---|
  | 2026-09-03 | 0.37–0.45% | 9.15–18.78% | 约 40× |
  | 2026-09-04（同一批节点） | 0.30–0.42% | 3.16–3.57% | 约 9× |

  倍数取决于后台线程当时在干什么，**不要把它当成一个可引用的常数**；
  可引用的是「`CPUUtilization` 恒偏高、不可用于定档」。两次测量里
  `EngineCPUUtilization` 都稳定在 1% 以下，倍数的变化全来自分母那一侧。
- **只用 `CacheClusterId` 单维度。** 该 namespace 同时发布
  `{CacheClusterId, CacheNodeId}`、`{ReplicationGroupId}`、
  `{NodeGroupId, ReplicationGroupId}`、`{Role, ReplicationGroupId}` 等组合；
  混用会重复计数，且 `Role=Primary/Replica` 的聚合序列无法映射回具体节点。
- **`CPUCreditBalance` 上限可反推 baseline，与 `baseline-pct.json` 吻合**：
  `cache.t3.medium` 实测上限 **576** = `2 × 0.20 × 1440`；
  `cache.t4g.micro` 实测 **288** = `2 × 0.10 × 1440`。
  可作为该静态表未过期的运行时交叉验证。

**仍未实测**：Memcached、Valkey、ElastiCache Serverless、非集群模式（单 shard）。

## VPC — NAT / ALB / NLB

**ALB 与 NLB 必须分开查，指标不通用。** 用 `describe-load-balancers` 的 `Type`
字段先分流（`application` / `network`），不要把两类混在一个查询里。

| LB 类型 | namespace | 闲置判据要采的指标（`Stat=Sum`） | 状态 |
|---|---|---|---|
| ALB | `AWS/ApplicationELB` | `RequestCount` **+** `ActiveConnectionCount`，判定见 `cli-recipes.md` §2.6 | 已实测 |
| **NLB** | **`AWS/NetworkELB`** | 见下表，判定同样按 `cli-recipes.md` §2.6 替换两列 | **未实测（本账号 8 region 无 NLB）** |

**本文件只记「采哪个指标、取哪个 stat、刻度是什么」，不记闲置判定。**
ALB/NLB 的闲置是**两个指标的三态组合**，且零值序列必须覆盖整窗口才算证据——
判定矩阵与可执行实现只在 `cli-recipes.md` §2.6 一处。此前本文件写过
「`RequestCount` 全窗口恒 0 **或序列不存在** ⇒ 闲置」并标了「已实测」，
那句话照字面执行就会把一台**其实一直有连接**的 LB 报成可删除（上一轮真实运行的错）。

NLB 闲置判据指标（取自官方 CloudWatch 指标文档，2026-09-04）：

| 指标 | stat | 单指标含义（**不是**闲置判定） |
|---|---|---|
| `NewFlowCount` | Sum | 覆盖整窗口且恒 0 ⇒ 该指标侧无新连接 |
| `ProcessedBytes` | Sum | 覆盖整窗口且恒 0 ⇒ 该指标侧无流量 |
| `ActiveFlowCount` | Maximum | 覆盖整窗口且恒 0 ⇒ 该指标侧无活动连接 |
| `ConsumedLCUs` | Sum | 参考计费维度 |

**「覆盖整窗口」不可省。** 只覆盖几小时的全 0 序列什么都没证明（新建 / 曾停机 /
发布中断都长这样）。上表每一行都只是**一个指标的一侧**，闲置要两个指标一起判，
组合规则见 `cli-recipes.md` §2.6（NLB 用 `ProcessedBytes` / `ActiveFlowCount`
替换该节矩阵的两列）。

**必须用不带协议后缀的总量指标。** 文档里同时存在 `_TCP` / `_TLS` / `_UDP` / `_QUIC`
变体（如 `ProcessedBytes_TCP`）；只查某一个协议会把其他协议的流量漏掉，
从而把有流量的 NLB 判成闲置。

**NLB 没有 `RequestCount`。** 若沿用 ALB 的查询，NLB 会因"零请求"被一律误判为闲置
——而 NLB 是 L4，本就不计 request。

**未实测说明**：全 region 扫描 NLB 数量均为 0，无法实测。上表 NLB 指标名取自文档，
首次在有 NLB 的环境运行时
**preflight 必须先 `list-metrics --namespace AWS/NetworkELB` 校验指标名**。

扫描结果（**NLB=0 是断言，ALB 个数是观测值**）：

| 日期 | 扫描 region 数 | ALB 合计 | NLB 合计 |
|---|---|---|---|
| 2026-09-03 | 8 | 12 | **0** |
| 2026-09-04 | 17（本账号全部已启用 region） | 18 | **0** |

即「本账号没有 NLB」这条在更大的扫描面上仍成立，所以"未实测"的结论没变；
变的只是 ALB 个数。复现命令：

```bash
for R in $(aws ec2 describe-regions --query 'Regions[].RegionName' --output text); do
  aws elbv2 describe-load-balancers --region $R --query 'LoadBalancers[].Type' --output json
done | jq -s 'flatten | group_by(.) | map({(.[0]): length}) | add'
# 实测输出：{"application": 18}
```

**注意输出里没有 `"network": 0` 这一项**——`group_by` 只会给出现过的取值建键，
NLB 为 0 表现为**键不存在**。别把它读成命令没跑成。

### NAT — `AWS/NATGateway` 维度 `NatGatewayId`

| 指标 | stat | 用途 | 状态 |
|---|---|---|---|
| ActiveConnectionCount | **Maximum**（真瞬时连接数，实测 max 541） | 全窗口恒 0 ⇒ 闲置（NAT 是单指标单状态；覆盖度门槛见 `cli-recipes.md` §2.6） | 已实测 |
| BytesOutToDestination / BytesInFromDestination | 计数类 ⇒ **`Sum`** | 流量画像（第二阶段成本用）。NAT 数据处理**按处理总字节计费**，成本消费者要的就是窗口总和，没有竞争读法 | 已实测 |

**`ActiveConnectionCount` 在 NAT 与 ALB 上不是同一种量。** NAT 的是真瞬时连接数
（实测 `Maximum` max = 541），判据取 `Maximum`；ALB 的是计数类、`Maximum` 恒 0 或 1
没有判别力，判据取 `Sum`。同名不同义，两处都写死了 stat，别互相套用。

### ELB 的维度处理（ALB / NLB 共用）

| 指标 | stat | 用途 | 状态 |
|---|---|---|---|
| RequestCount (ALB) | 计数类 ⇒ **`Sum`** | 闲置判定的**两个必需指标之一**，判定见 `cli-recipes.md` §2.6 | 已实测 |
| ActiveConnectionCount (ALB) | **实测表现为计数类 ⇒ `Sum`**（见下方警告，**不得按文档改**） | 闲置判定的另一个**必需**指标（不是辅证），判定见 `cli-recipes.md` §2.6 | 已实测 |

> **⚠️ 不要按 AWS 文档「纠正」上面那行的 stat。这一行是实测归类，不是文档归类。**
> `ActiveConnectionCount` 的官方描述是"并发 TCP 连接数"，读起来是 gauge，
> 而它在 `AWS/NATGateway` 上**确实是** gauge（实测 `Maximum` max = 541）。
> 但在 `AWS/ApplicationELB` 上本仓库实测它表现为**每间隔计数**：
> `Maximum` 在全部 4 个 LB 上**恒等于 0.0**——包括每小时上万请求的那台，
> 而同一台的 `Sum` 是 1035（原始数据见 `cli-recipes.md` §2.6 的三 stat 对比表）。
> **凭文档把这一行改成 `Average, Maximum` 会让三态判定静默塌回二态**，
> 也就是把本仓库花两轮修掉的那个缺陷原样装回去（活跃 LB 被报成可删除）。
> 要改这一行，先在有 ALB 的 region 重新采一次三个 stat 并贴出数据；
> **只有实测能推翻实测。** 同名不同义的另一半见上一小节 NAT 那段。

（本小节此前挂在上面那个 NAT 标题下：表里混着两行 ALB，后面整段讲的又全是 ELB
的维度处理，按标题检索 ALB 的人会整段错过。）

**ELB 的维度值不是 ARN 全串**，是 ARN 中 `loadbalancer/` 之后的部分，
形如 `app/<name>/<hash>`。

**必须只带 `LoadBalancer` 单维度。** 实测同一 ALB 的 `RequestCount` 有 4 种组合：
`{LoadBalancer}`、`{LoadBalancer, AvailabilityZone}`、`{LoadBalancer, TargetGroup}`、
`{LoadBalancer, TargetGroup, AvailabilityZone}`。带后两类会按目标组/可用区拆成多条，
判闲置时重复计数。

**`RequestCount` 的「没数据」有两种表现，但两种都不单独等于闲置。**
实测（2026-09-04，两个 region、6 台 ALB、30 天窗口 `Stat=Sum`）：
两台 ALB（分属两个 region）各返回 720 个点、值全为 0；另一台**整条序列不存在**
（零请求 ⇒ 指标从未发布）
——而**后者其实一直有连接**（`ActiveConnectionCount` max 84），并不闲置。
此前这里把"整条序列不存在"直接写成「另一个闲置 ALB」，那就是上一轮把活跃 LB
报成可删除的那句话。序列不存在时须按 `cli-recipes.md` §2.0 ④ 用 `list-metrics`
与"模板写错"区分开，再按 §2.6 的三态矩阵与另一个指标合起来判。

**NLB (`AWS/NetworkELB`) 仍未实测** —— 两个验证 region 均无 NLB。

## EKS

**节点级已于 2026-09-03 在 us-west-2 首次实测**（1 个 1.31 集群、1 个托管 nodegroup、
5 节点 / 71 pod）。数据源不是 CloudWatch 而是 `kubectl` + `eks describe-*`。

| 分析项 | 数据源 | 状态 |
|---|---|---|
| 节点可分配量 / 机型 / 所属 nodegroup | `kubectl get nodes` | 已实测 |
| pod request（**须走 `core.pod_requests()`**，不得自己 sum 容器） | `kubectl get pods -o json` 原始输出 | 已实测（有 6 容器的 pod，取 `[0]` 会严重低估；逐容器求和也仍低估——调度口径是 `max(Σ 普通容器, 各 init 容器最大值) + pod overhead`） |
| DaemonSet vs 业务 pod 区分 | pod 的 `ownerReferences[0].kind` | 已实测（DaemonSet request 是每节点固定开销，混算会高估所需节点数） |
| bin-packing 理论最少节点数 | 上述三项 | 已实测（5 节点 → 理论 4） |
| 节点归属识别 | EC2 标签 `eks:nodegroup-name` / `karpenter.sh/nodepool` | 已实测（不识别会对节点单机出降配建议，是错的） |
| 未调度 pod | `.spec.nodeName == null` | 已实测（本例 0） |
| **pod 级历史 CPU/内存 p95** | `ContainerInsights` namespace | ❌ **不可得**，见下 |
| HPA `minReplicas` 过高 | `kubectl get hpa` | 集群内 **0 个 HPA** ⇒ **未实测** |
| Fargate request 超配 | `eks list-fargate-profiles` | **0 个 profile** ⇒ **未实测** |
| Karpenter NodePool 建议 | `karpenter.sh/nodepool` 标签 | **0 个节点** ⇒ **未实测** |

**`ContainerInsights` 命名空间为 0，即便集群里装了
`amazon-cloudwatch-observability` addon 与 `cloudwatch-agent` DaemonSet。**
不能用"agent 装了"推断"指标有"，必须 `list-metrics` 实证。

`kubectl top nodes/pods` 需要 metrics-server 且**只有瞬时值**，不能当定档依据。
实测该集群节点 CPU 预订率 70–94%、瞬时实际使用率仅 3–5%，
**request 超配约 20–25 倍**，但没有历史序列就给不出每个 workload 的目标 request 值。
此时只出节点级结论（减节点数），并在报告缺口标注 pod 级不可得。

## stat × 指标类别 收尾扫描（2026-09-04）

**为什么把它写进文件：** 上一轮修完计数类 stat 之后又漏了三行，原因是扫描靠"读一遍"
而不是靠一个可复核的分类。**下一次扫这份文件，是拿本表逐行对，不是重新推导一遍。**
本表记的是**类别**（CloudWatch 语义，属 `cli-recipes.md §0.1` 的 B 类稳定事实）；
**该采哪个 stat 仍以各节表格里那一列为准**，本表不是采集依据。

**方法（可重复）：**

```bash
# 列出本文件所有声明了 stat 的表格行，逐行对下表
grep -nE '^\|' references/metrics-catalog.md | grep -E '\b(Sum|Average|Maximum|Minimum)\b'
```

1. 判类别：**计数类** = 每个发布间隔的累计计数（名字常是 `*Bytes` / `*Count` /
   `*Ops` / `*Charged` / `*Usage`）；**gauge** = 瞬时值或余额；**速率** = 名字里已带
   per second。**名字会骗人**——ALB 的 `ActiveConnectionCount` 读起来是 gauge，
   实测是计数类（见 ELB 小节的 ⚠️ 警告）。**只有实测能推翻实测。**
2. 计数类 ⇒ 要窗口总量／平均速率取 `Sum`（零换算）；要峰值速率取 `Maximum`
   **并写明「÷ 发布间隔」**。`Maximum` 在计数类上不是错的，**是没有标注**，
   而无标注的每间隔计数正是本轮撤回的那一类。
3. gauge ⇒ `Average` + `Maximum`；下限型判据额外加 `Minimum`。速率 ⇒ 原样，`Sum` 无意义。
4. **没有 stat 列或类别列的表 = 扫不到 = 假的干净。** 补列，别跳过。

| 指标 | 类别 | 现声明 stat | 结论 |
|---|---|---|---|
| EC2 `CPUUtilization` | gauge | Average, Maximum | ✅ |
| EC2 `NetworkIn` / `NetworkOut` / `EBSRead\|WriteBytes` | 计数类 | Sum | ✅ 本轮改正 |
| EC2 `CPUCreditBalance` | gauge（余额） | Average, Minimum | ✅ 下限型判据要 Minimum |
| EC2 `CPUCreditUsage` | **计数类** | Average, Maximum | ⚠️ 无判据消费，见该行 |
| EC2 `CPUSurplusCreditBalance` | gauge（余额） | Maximum | ✅ 无判据消费 |
| EC2 / RDS `CPUSurplusCreditsCharged` | **计数类** | Maximum | ⚠️ 判据是 `> 0`，max 与 sum 等价 ⇒ 安全；标注已由「窗口累计」改为「单小时最大」 |
| EBS `VolumeRead\|WriteOps` / `VolumeRead\|WriteBytes` | 计数类 | 按问题选（见该表） | ✅ 本轮改正；**无判据消费**，用途列的假消费者已删 |
| MSK `CpuUser+CpuSystem` / `KafkaDataLogsDiskUsed` / `MemoryUsed` / `UnderReplicatedPartitions` / `RequestHandlerAvgIdlePercent` / `CPUCreditBalance` | gauge | Average, Maximum | ✅ |
| MSK `BytesInPerSec` / `BytesOutPerSec` | **速率** | Average, Maximum | ✅ **不要动**，`Sum` 无意义 |
| MSK `CPUCreditUsage` | **计数类** | Average, Maximum | ⚠️ 同 EC2 那行，无判据消费 |
| RDS `DBLoad` / `CPUUtilization` / `DatabaseConnections` | gauge | Average, Maximum | ✅ |
| RDS `FreeableMemory` / `FreeStorageSpace` / `CPUCreditBalance` | gauge | 含 Minimum | ✅ 下限型判据 |
| RDS `ReadIOPS` / `WriteIOPS` | **速率** | Average, Maximum | ✅ **不要动** |
| EC `EngineCPUUtilization` / `DatabaseMemoryUsagePercentage` / `ReplicationLag` / `CurrConnections` / `CurrItems` | gauge | Average, Maximum（`ReplicationLag` 取 Maximum） | ✅ |
| EC `BytesUsedForCache` | **gauge**（瞬时驻留字节） | Average, Maximum | ✅ **不要动**，跨小时求和没有指代 |
| EC `Evictions` | **计数类** | Maximum | ⚠️ 判据是 `> 0` ⇒ 安全；字段名 `evictions_sum` 是历史命名 |
| EC `CPUCreditBalance` | gauge | Average, Minimum | ✅ |
| NLB `NewFlowCount` / `ProcessedBytes` / `ConsumedLCUs` | 计数类 | Sum | ✅ |
| NLB `ActiveFlowCount` | **gauge**（并发流） | Maximum | ✅ |
| NAT `ActiveConnectionCount` | **gauge**（真瞬时，实测 max 541） | Maximum | ✅ 与 ALB 同名不同义 |
| NAT `BytesOutToDestination` / `BytesInFromDestination` | 计数类 | Sum | ✅ 本轮改正（计费按总字节，无竞争读法） |
| ALB `RequestCount` | 计数类 | Sum | ✅ |
| ALB `ActiveConnectionCount` | **计数类（实测归类，非文档归类）** | Sum | ✅ **不得按文档改**，见该行的 ⚠️ 警告 |
| CWAgent `mem_used_percent` / `disk_used_percent` | gauge | 见 `cli-recipes.md §2.2` | ⚠️ 本文件无 stat 列，扫不到；stat 在采集侧 |

**本次扫描的净结果：**上面标 ⚠️ 的六项全部是「计数类配非 Sum stat」，其中五项
**目前没有任何判据消费**、一项（`CPUSurplusCreditsCharged` / `Evictions`）判据是 `> 0`
因而 max 与 sum 等价；没有一项影响当前任何结论。**三项 ❌ 已在本轮改正**
（EBS 两个 `*Bytes`、NAT 的 `*Bytes` 对），另有一处用途列断言了不存在的消费者，也已改。

## 2026-09-04 复核记录

把本文件所有标着「已实测」的可核对断言重跑了一遍（`AWS_PROFILE` 只读，
两个验证 region）。**这一轮里没有一条被推翻**；漂移的都是计数值，已在各节就地标注。

> **同日第二轮补记：这轮的问法漏掉了一整类错。** 本节问的是「这些**数字**还对不对」，
> 于是全部通过。但同日另一轮复核推翻了两条**规则**——ELB 闲置判据（把序列缺失
> 算作闲置）与 EC2 的 `Average` × 换算系数——它们的数字都没漂，
> 是**被本轮其他改动取代了**。两处都已就地改掉并留了撤回说明。
> 下一次复核这份文件，两个问题都要问：数字漂了吗？规则过期了吗？
> 另外新增的实测项（2026-09-04 第二轮）：ALB/NAT 闲置判定在两个 region
> 6 台 ALB + 6 个 NAT 上重跑，逐资源的序列点数与覆盖度记在
> `cli-recipes.md §2.6`；ElastiCache 最便宜 node type 取价见 `core.py` 的
> `eval_elasticache` 注释。

### 仍然成立（其中多条是逐位相同）

| 断言 | 复核结果 |
|---|---|
| `AWS/EC2` / `AWS/Kafka` / `AWS/NATGateway` / `CWAgent` / `AWS/RDS` 指标条数 | 与 2026-09-03 **完全一致** |
| CWAgent 维度集逐实例不一致（两种形态并存） | **仍并存**（us-west-2 的 `mem_used_percent` 两种维度集都在） |
| 内存/磁盘覆盖率 2/13、2/18、3/31 | **逐个相同** |
| 信用指标只在 `t*` 实例上 | 两 region 合计 4 台有 `CPUCreditBalance`，**非 T 实例 0 台** |
| RDS：2 个 MySQL 8.0 Multi-AZ（一 `db.t4g` 开 PI、一 `db.m5` 未开）+ 1 个 `db.serverless` | 完全一致，`DBLoad` 仍只在开了 PI 的那台上 |
| ElastiCache：一个 6 节点 Redis 7.1 复制组 + 一个单节点 | 完全一致 |
| ElastiCache 信用上限反推 baseline | `cache.t3.medium` **恰好 576**、`cache.t4g.micro` **恰好 288**，与 `baseline-pct.json` 仍吻合 |
| MSK 两集群覆盖 `DEFAULT` 与 `PER_TOPIC_PER_PARTITION` | 一致（2 broker / 3 broker） |
| **`RequestHandlerAvgIdlePercent` 在 `DEFAULT` 下不发布** | 坐实：`DEFAULT` 那个 region `list-metrics` 返回 **0** 条，`PER_TOPIC_PER_PARTITION` 返回 **2** 条 |
| MSK 刻度：磁盘 0–100、handler idle 0–1、内存字节 | 一致（handler idle 实测 1.0002–1.0012，**仍会略微超过 1**） |
| EKS：1 个 1.31 集群 / 1 个托管 nodegroup / 5 节点同机型 / 0 Fargate profile / 0 Karpenter 节点 | 完全一致 |
| `ContainerInsights` 为空 | 仍为 **0**（两 region） |
| NLB 全 region 为 0 | 仍为 0，且扫描面从 8 个 region 扩到 17 个 |

### 漂移的（已就地标成观测值）

| 项 | 2026-09-03 | 2026-09-04 |
|---|---|---|
| `AWS/ApplicationELB` 指标条数（us-west-2） | 411 | 432 |
| `AWS/ElastiCache` 指标条数（us-west-2） | 500 | **1036**（资源一个没变） |
| ALB 合计 | 12（8 region） | 18（17 region） |
| `CPUUtilization` 对 `EngineCPUUtilization` 的高估倍数 | 约 40× | 约 9× |
| `AWS/EBS` 指标条数（us-west-2） | 未单独计数 | 282（新增数据点） |

### 本次仍未核对

- **HPA 个数**（文档记「集群内 0 个 HPA ⇒ 未实测」）：要 `kubectl get hpa`，
  即需要连进集群，本次复核只走了 AWS API，没连集群。该结论保持原状。
- **`AWS/NetworkELB` 指标名**：账号里依然没有 NLB，仍然只能照文档写、
  仍须首次运行时 preflight 校验。
- 各处**负载相关的具体数值**（p95/max 样值）没有逐个对：它们随负载变，
  本来就只用于确定刻度，刻度已复核。
