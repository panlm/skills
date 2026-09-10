---
name: aws-rightsizing
description: Use when asked to right-size an AWS account, cut EC2/EBS/RDS/ElastiCache/MSK/EKS cost, find over-provisioned idle or underutilized resources, downsize instance types, or produce a configuration optimization or rightsizing report. Also use when a report must justify a target instance type from measured CloudWatch utilization rather than guesswork.
---

# AWS Rightsizing（配置优化）

本 skill **只读**。仅允许 `describe*` / `list*` / `get*`。

## 硬约束（非"暂不实现"，是本版本边界）

- **禁止 `ce:*` 及任何账单 API。** 允许 `pricing:GetProducts` 读公开按需价目。
- **禁止任何 mutating 调用。**
- **禁止产出改变架构形态、CPU 架构或可用性等级的建议**：Serverless 迁移、
  跨 CPU 架构（如 x86↔arm64）迁移、Spot/Karpenter 引入、Redis 减副本/减 shard、
  RDS Multi-AZ→Single-AZ、MSK 减 broker 数。
- **不代替人工在 non-burstable 与 burstable 之间选择**，两列一律都出。

## 价格口径：一律按需（On-Demand），报告中的比例也是按需口径

**本 skill 只使用公开按需价目。** 因此所有金额与所有百分比都是按需理论值：

| 输出项 | 口径 |
|---|---|
| `cur_usd` / `cur_cost_mo` | 该资源按**按需价**计费的理论小时价 / 月额 |
| `nb_save_mo` / `b_save_mo` | 按需价下的理论月省 |
| 报告摘要里的**节省比例** | 分子分母**都是按需理论值**，分母不是实际账单 |
| `other_save_mo` | 同上，采集侧自建行的按需理论月省 |

**比例的算式不在本节。** 分子有四条互斥口径、分母有明确范围，两者的定义都在
`report-template.md` 的「汇总口径」与「分母的范围」——**本节只管价格口径**。
（本文件此前在这里写过一个 `Σ按需理论月省 ÷ Σ按需理论月额`：分子没说是哪条口径，
于是两个 agent 各挑一条，同一支机队的头条百分比能差三成。算式只留一处。）

**必须在报告里显式写出分母是按需理论月额。** 若客户已买 RI/SP，实际账单基数低于
按需月额，则同样的绝对节省对应的**实际百分比会更高**，但绝对金额会更低（甚至为 0，
若折扣只是转移到别的资源）。两者不可混用。

本版本不读账单（禁 `ce:*`），所以无法给出实际口径的比例，只能给按需口径并标注清楚。

### 取价必须按 (机型, UsageOperation) 复合键，不能只按机型

同一 `m5.xlarge` 在 ap-northeast-1 的按需价（实测）：

| OS / License | `operation` | $/hr | 相对 Linux |
|---|---|---|---|
| Linux | `RunInstances` | 0.248 | 1.00x |
| Ubuntu Pro | `RunInstances:0g00` | 0.255 | 1.03x |
| SUSE | `RunInstances:000g` | 0.304 | 1.23x |
| RHEL | `RunInstances:0010` | 0.306 | 1.23x |
| Windows | `RunInstances:0002` | 0.432 | **1.74x** |
| Windows + SQL Ent | `RunInstances:0102` | 1.932 | **7.79x** |

只按机型取价（或把 `operatingSystem=Linux` 写死在过滤里）会让非 Linux 实例的
成本被低估最多 7.79 倍，节省金额完全失真。

`describe-instances` 的 `UsageOperation` 与 pricing API 的 `operation` 属性
一一对应，是权威连接键。取价时**不要按 `operatingSystem` 过滤**，
改为全量取回后按 `"<机型>|<operation>"` 建键（单 region 的唯一键数是
**A 类观测值、会漂移**，最近一次实测值在 `cli-recipes.md` 的价目缓存一节，
**此处不写数字**——本文此前两处各写了一个、还互相差 2，两个都已过期）。

降配不改变 OS 与授权，故候选沿用当前实例的 `operation`。

### 其他必须匹配的取价维度

取价固定 `tenancy=Shared` + `capacitystatus=Used`。执行前须校验每台实例满足：

```bash
aws ec2 describe-instances --region $R --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{id:InstanceId,op:UsageOperation,ten:Placement.Tenancy}' \
  --output json
```

`Placement.Tenancy` 非 `default` 的实例（dedicated / host）价格不同，
**须单独取价或标 `price-unknown` 排除，不得套用 Shared 价格。**

## 运行时输入（缺失则询问，不猜）

| 输入 | 说明 | 默认 |
|---|---|---|
| `target_account` | 目标账号 ID，用于校验凭证 | 无，必填 |
| `regions` | 扫描的 region 列表 | 当前 profile 的 region |
| `window_days` | 指标回看窗口 | 30 |
| `sizing_profile` | `aggressive` / `conservative`，见 `thresholds.md` | 无，必填 |
| `allow_stop_recommendations` | 是否产出定时停机建议（桶 C） | 无，必填 |
| `business_timezone` | 时段切档用业务时区 | UTC+8 |

三个必填项都不可推断：

- `target_account`——防止在错误账号产出报告。
- `sizing_profile`——**按风险偏好选，不按 prod/non-prod。** skill 无法验证环境类型，
  operator 却直接知道能接受多激进。实测原 prod/non-prod 两列产出完全相同，
  用环境命名会承诺一个不存在的保护。
- `allow_stop_recommendations`——**与 `sizing_profile` 正交。** 能否夜间停机取决于
  该负载的停机容忍度，跟规格压多紧无关：可以既要紧凑规格又不许停机，
  也可以规格宽松但乐意停机。不要从 profile 推导它。

## 执行顺序

```
0  preflight            凭证校验 + 数据源探测
1  规格与价目落盘         全量机型规格、region 可用集合、按需价目
2  资源清单采集           inventory/*.json
3  指标查询生成与提交      metrics/raw-*.json
4  时区归一化与聚合        metrics/summary-*.csv
5  逐服务判据 + solver     findings
6  报告生成              report_output/<account>-<region>-<date>/
```

命令模板见 `references/cli-recipes.md`（§6 含 `core.py` 的输入契约与
`price`/`catmap`/`offerings` 的生成方式）。**不要自行发明命令**，模板都经实测。

**只有两个静态资产**：`baseline-pct.json`（T 系列基线，无 API 可查）与
`legacy-families.json`（人工策展的排除清单）。其余一切——机型规格、region 可用
集合、按需价目、用途分类——**必须按当前 region 运行时现查**，不得作为 skill 资产提交。

**价目允许在运行环境缓存复用**（`~/.cache/aws-rightsizing/prices-<region>.json`，
不进 skill 包、不进版本库）。缓存有效性用**单机型探针比对 `version`** 判定——
实测探针 2.6 秒 vs 全量**分钟级 / 百 MB 级**（按 operation 复合键须不过滤 OS；
条数、体积、耗时都是 A 类观测值，逐 region 的最近实测值见
`cli-recipes.md` 的价目缓存一节，**本文不复述**），
且同次取回内全部记录 version 完全一致。
**不要用「缓存 N 天」这类时间猜测。** 文件名必须含 region（价格随 region 变，
实测东京对弗吉尼亚溢价 117–131%），顶层须存 `version`/`region`/`fetched`。
**探针失败不得回退缓存**——那说明 pricing 不可用，应按 preflight 规则停止。

## 0. Preflight

先校验凭证指向正确账号，不一致立即停止：

```bash
ACT=$(aws sts get-caller-identity --query Account --output text)
[ "$ACT" = "$TARGET_ACCOUNT" ] || { echo "STOP: 凭证指向 $ACT，目标 $TARGET_ACCOUNT"; exit 1; }
PARTITION=$(aws sts get-caller-identity --query Arn --output text | cut -d: -f2)
```

再逐项探测。**自己写探测命令，不要期待 skill 附带脚本。** 每项用一次最小只读
请求试探（`--max-items 1` 之类），成功即视为可用。**任一缺失都要在报告第 2 节
写明：缺什么、影响哪节结论、客户要开什么、需等多久。不静默降级产出半残报告。**

输出成一张 PASS / WARN / FAIL 表，末尾给汇总计数。判定口径：

- **FAIL**——阻断运行：凭证账号不符、`pricing:GetProducts` 不可用、
  `cloudwatch:GetMetricData` 不可用、aws cli 非 v2、无 jq。
- **WARN**——可继续但结论有缺口：某 namespace 为 0（该区无此类资源）、
  CWAgent 缺失、Performance Insights 不可用、basic monitoring。
- 存在 FAIL 时**停止**，不要产出报告。

除下表各项外，还须探测：

| 项 | 命令 | 判定 |
|---|---|---|
| aws cli 版本 | `aws --version` | 非 v2 ⇒ FAIL（本 skill 的时间戳与分页行为按 v2 验证） |
| jq 存在 | `jq --version` | 缺失 ⇒ FAIL（全部聚合依赖 jq） |
| `cli_timestamp_format` | `aws configure get cli_timestamp_format` | 仅记录；无论取值都必须用 `agg.jq` 的 `parse_ts`，不得假定 `Z` 结尾 |
| 逐项 IAM 权限 | 对下表每个数据源发一次最小请求 | 被拒 ⇒ 按上述口径归类 |

| 检查项 | 探测方式 | 缺失后果 |
|---|---|---|
| 各 namespace 有数据 | `cloudwatch list-metrics --namespace X` | 对应服务无法分析 |
| CWAgent 内存指标 | `list-metrics --namespace CWAgent --metric-name mem_used_percent` | 内存需求按当前规格保留，confidence 降 medium |
| CWAgent 磁盘指标 | 同上 `disk_used_percent` | EBS 容量过大判不了 |
| RDS Performance Insights | `describe-db-instances` 的 `PerformanceInsightsEnabled` | RDS 降配失去第一判据 |
| MSK enhanced monitoring | `describe-cluster-v2` 的 `EnhancedMonitoring` | `DEFAULT` 档**只缺 `RequestHandlerAvgIdlePercent`**（实测：CPU/磁盘/URP/内存 per-broker 都有）。缺的这一个是降配前置条件 ⇒ 不产出降配建议，但阻断判据仍可算 |
| EKS Container Insights | `list-metrics --namespace ContainerInsights` | pod 级分析不可得。**不能用"装了 observability addon"推断有指标**——实测装了 addon + agent DaemonSet 该 namespace 仍为 0 |
| EKS 只读 access entry | 临时 kubeconfig + `kubectl auth can-i list pods --all-namespaces` | 拿不到 requests ⇒ 预订率与 bin-packing 全部失效（比缺 Container Insights 影响更大） |
| pricing API 可用 | `pricing get-products` 试查一个型号 | **无价格则不产出降配建议**（见下） |
| detailed monitoring | `describe-instances` 的 `Monitoring.State` | `disabled` = basic，每 5 分钟发布且已做平均，**<5 分钟尖峰不可见**。须在报告标注；尖峰型负载建议先开 detailed monitoring 再评估 |
| 实例平台与租户 | `describe-instances` 的 `UsageOperation` / `Placement.Tenancy` | 非 `default` 租户或缺失 operation 对应价格 ⇒ 标 `price-unknown` 排除 |

**pricing 不可用时不得退回"最小够用"选型。** 实测无价格时会推荐出比现状更贵的
机型（`m5.xlarge` $0.248/hr → `i3en.large` $0.266/hr）。此时应停止并报出缺权限。

## 1–4. 采集与聚合

按 `references/cli-recipes.md` 的 §0–§4 执行。每个 namespace 都有实测过的模板，
**不要自行发明命令**。要点：

- **采集窗口必须对齐到业务本地午夜**（`cli-recipes.md` §2.0 ①）。
  `Period=3600` 的桶边界对齐 `StartTime` 而非自然小时；直接用
  `date -u -v-30d`（带当前分秒）会让同一份数据被切进不同时段档——实测同一实例
  `peak_cpu` 在 `18.18%` 与 `10.59%` 之间摆动，足以改变 `required_vcpu`。
  按天对齐后整个业务日内重跑结果逐字节一致。
- **必须分批提交并断言无重复 Label**（做法见 `cli-recipes.md` §2）。单次上限 500 query 且
  100,800 数据点（30 天/3600s ⇒ 139 序列）。超限时 API 不报错，CLI 自动翻页并把
  同一 Label 的序列拆段拼接 ⇒ **静默数据损坏，且四项不变式全部照样通过**。
- `period=3600`，每指标默认只取 `Average` 与 `Maximum`。**不取 CloudWatch 的 `p95` stat**
  ——那是每小时内的 p95，跨小时聚合无意义。**两类例外**（规则在 `cli-recipes.md §2.0 ⑤`）：
  - 下限型判据的指标须**额外加** `Minimum`（RDS `FreeableMemory`、
    `CPUCreditBalance`），否则 `agg.jq` 的 `min` 只是"每小时均值的最小值"。
  - **计数类（Sum 语义）指标只取 `Sum`**，`Average`/`Maximum` 都不取：
    EC2 的 `NetworkIn`/`NetworkOut`/`EBSRead|WriteBytes` 与 ALB 的
    `RequestCount`/`ActiveConnectionCount`。取 `Average` 再乘换算系数的写法
    **已撤回**（那个系数取决于 SampleCount 而非发布粒度，本 skill 写错过三次，
    每次都标着"实测"）——见「易错项速查」那一行与 `cli-recipes.md §7.1`。
- solver 的两个输入：
  `持续负载 = 小时级 Average 序列的 p95`、`峰值 = 小时级 Maximum 序列的 max`。
- `Label` 必须写成 `"<resource_id>|<type>|<stat>"`。多指标采集时把指标名编进
  第一段（`"<rid>@<metric>|<type>|<stat>"`），否则 `agg.jq` 会把指标名当成 stat。
- 多维度指标必须提供**发布时的全部维度**，且**维度集逐实例而异**——实测同账号
  内 CWAgent `mem_used_percent` 一台是 `ImageId`+`InstanceId`+`InstanceType`、
  另一台只有 `InstanceId`（取决于 agent 的 `append_dimensions`）。
  一律用 `mdq-dims.jq` 从 `list-metrics` 回包原样搬，不要硬编码。
- 多维度可选的 namespace 必须**只取单一资源维度**：RDS 用 `DBInstanceIdentifier`、
  ElastiCache 用 `CacheClusterId`、ALB 用 `LoadBalancer`。带上
  `DatabaseClass`/`Role`/`TargetGroup`/`AvailabilityZone` 等聚合维度会重复计数。
- MSK 维度名带空格：`Cluster Name`、`Broker ID`。
- 复合指标（如 MSK 的 `CpuUser + CpuSystem`）必须用 metric math
  `Expression: "m1+m2"` 逐点相加，**不能分别聚合再相加**。
- **Sum 语义指标（`NetworkIn`/`NetworkOut`/`EBSRead|WriteBytes`）不是速率**，
  **一律采 `Stat=Sum` 逐小时相加**，得到窗口内总字节数，零换算假设。
  日均 MB = Σ Sum ÷ 1048576 ÷ 窗口天数；B/s = Σ Sum ÷ 窗口秒数。**不要用 Average 乘系数**。
  实测乘 24 把 11 台有流量的实例误判成闲置。
- 时间戳必须用 `agg.jq` 的 `parse_ts` 归一化。AWS CLI v2 受
  `cli_timestamp_format` 影响，实测输出带 `+08:00` 偏移而非 `Z`。
- **空序列不报错**，是最危险的失效模式。每个 namespace 采集后必须打印非空序列数：
  全空 ⇒ 疑模板错（用 `list-metrics --dimensions` 验维度名）；
  部分空 ⇒ 多为真实缺失（PI 未开 / 非 burstable / 零流量），须交叉核对后写进报告缺口。
- 必须跑**五项**不变式，全部须为 0，顺序不可颠倒（见 `cli-recipes.md`）：
  **① raw 层「重复 Label 数」，采集后立即跑**——它是分页拼接损坏的唯一可靠信号；
  ②–⑤ 聚合层 `p95>max`、`mean>max`、空桶、`min>mean`
  **加上时段点数闭合式**（`biz + off + weekend == WINDOW_DAYS × 24`）。
  聚合层那四项抓不到分页损坏（实测判据只用了 74% 数据却全部通过），① 与闭合式能抓到。

## 判据核心 = `references/core.py`；采集与组装由你按环境拼

**职责边界**（这是本 skill 的核心设计决定）：

| 归属 | 内容 | 理由 |
|---|---|---|
| **skill 固定**（`core.py`） | 需求反推、候选筛选、双候选选型、缺失值语义、闲置判据、桶优先级、**RDS/ElastiCache/MSK 判据** | 错了是**静默**且后果重（降配/删除）。不得重新实现 |
| **你按环境组装** | 采集、region 循环、分批、输出路径、报告排版 | 环境相关，你适配比预设模板强 |

```bash
python3 references/core.py < ctx.json > findings.json
```

`ctx.json` 结构与逐字段语义见 `references/sample-solve.md`，那里的输入输出
**全部由真实执行产出**，照形状抄即可，不要凭描述重建。

**`resources` 的每一条必须带 `"service"`**，取值 `ec2` / `rds` / `elasticache` / `msk`，
决定走哪条判据。**缺失或不认识一律抛 `ValueError`，不回退 `ec2`**——回退会让托管服务
的资源被喂进 EC2 判据、因指标名不同而报 `metric-missing`，整个托管服务报告静默消失。
组装 `solver-in.json` 的那一步（`cli-recipes.md` §7）必须写出这个字段。

**为什么核心用 Python 而非 jq**：jq 有几个静默陷阱在本 skill 上反复咬——
`($specs[]|select(...)) as $x` 在生成器为空时**整条记录消失**（曾使
`spec-unknown` 分支完全不可达，未知机型静默从报告消失）、`//` 的 falsy 语义、
对象内不能裸 `+` 拼字符串。采集侧的 jq 保留（数据 reshape，已实测通过）。

Python 版与 jq 版在真实机队上**逐台一致**（13 台推荐相同）。当时记录的月省
$527.15 已作废——那次比对用的 fixture 把 `cpu_n` 填成了全窗口点数，
详见 `thresholds.md` 的预设对比小节。**逐台一致这个结论不受影响**
（两个实现吃的是同一份输入），受影响的只是那个金额。
当前可复现的基线在 `tests/fixtures/regression-fleet.json`。

## 5. 逐服务判据

阈值以 `references/thresholds.md` 为**唯一真值源**，运行时不可放宽。
候选选型算法在 `references/core.py`，过滤顺序不可调换：

```
legacy 族清单 → 用途分类 → region 可用性 → 规格硬约束 → 价格升序取第一
```

### EC2

- `g*`/`p*`/`inf*`/`trn*` 直接排除出桶 A（受限资源是加速器，无 GPU 利用率指标）。
- 其余走 solver 产出两个候选。当前已是 T 系列且 `CPUSurplusCreditsCharged > 0`
  时抑制 burstable 选项。
- **需求量超过当前规格 ⇒ `upsize-candidate`，不得输出「已合理配置」。**
  判定只用**持续项**（`sus_cpu` / `sus_mem` 对 `target_*_p95` 反推），
  峰值项不参与——它是降配方向的安全约束。仅峰值项超的行仍是「已合理配置」，
  但必须带一条 blocker 写明绑定约束是峰值项。本 skill **不产出升配的目标机型**：
  选型需要容量规划输入（增长率 / SLA / 峰值形态），不在本版本边界内。
- 闲置判据（桶 B）走 `core.py` 的 `is_idle()`，阈值见 `thresholds.md`。**不要自己实现**——`net_mb_day == 0` 是最强闲置信号，用缺失值兜底写法（Python 的 `or`、jq 的 `//`）会把 0 当缺失值替换掉，专挑信号最强的记录静默失效（实测漏判 $1,369/mo）。
- **桶 C 停机走 `core.py` 的 `is_stop_candidate()`，同样不要自己实现。**
  三个门限（`idle_cpu_p95` / `idle_net_mb_day` / `stop_candidate_peak_cpu_max`）
  在 `off-hours` 与 `weekend` 两档上都要过；输入是六个分档字段，见
  `cli-recipes.md` §7.0。它返回**三态**：`true` 候选 / `false` 不是候选 /
  **`null` 判不了**（缺分档输入或采样量不足）。**`null` 必须写成"桶 C 未评估"，
  不得写成"无候选"**——后者读起来像已经查过了。
  产出**只是候选清单 + 三档证据，不产出"建议停机"字样**；仅凭 CPU 一个信号
  会把被动监听型服务全部误判为可停，所以三个门限缺一不可，也不得自造阈值。
  `allow_stop_recommendations=no` 时该列**保留在 CSV 里但留空**（不是删列、
  也不是填 `false`），并在报告正文写「桶 C 未评估」。四种情形的区别见
  `report-template.md` 的「`stop_candidate` 的四种情形」。
- 内存**完全按实测利用率**定档，**不设绝对下限**（见 `thresholds.md`）。
  无内存数据 ⇒ `required_gib = cur_gib`（内存不动），confidence 上限 medium。
  没有数据时正确动作是不动内存，而不是拍一个地板值替实例做假设。

### EBS

- `gp2 → gp3` 全量清单。**原容量 > 334 GiB 时基线 IOPS 已超 3000，转 gp3 必须
  显式配 IOPS**，此约束写入 `blockers`。
- `state=available` 未挂载卷 → 桶 B。
- 卷容量是否过大**判不了**（需 CWAgent `disk_used_percent`），须在缺口中列出。

### RDS

- **第一判据是 Performance Insights 的 `db.load.avg`，不是 `CPUUtilization`。**
  `DBLoad p95 >= vCPU 数` ⇒ CPU 已是瓶颈，一律禁止降配。
- 内存用 `FreeableMemory` 反推：`已用 ≈ 实例内存 − FreeableMemory`。
- `db.serverless` 排除（Aurora Serverless v2 按 ACU 伸缩，无固定规格）。
- 非生产**不建议停实例**：停止的 RDS 仍收存储费且最多 7 天自动启动，
  桶 C 须改为"快照 + 删除"路径并在 `blockers` 写明。

### ElastiCache Redis

- **必须用 `EngineCPUUtilization`，不得用 `CPUUtilization`。** Redis 单线程，
  整机 CPU 含后台线程，用后者会系统性误判。
- 内存口径是**乘** `(1 − reserved)`，不是除：
  `required_gib_usable = mem_gib × (1 − reserved) × DatabaseMemoryUsagePercentage / 100`。
  该指标是 **maxmemory**（= 节点内存 × (1 − reserved)）的百分比，不是节点内存的百分比；
  写成除会算出节点总内存口径，与列名 `usable` 矛盾。`reserved` 缺省取
  `reserved_memory_pct_default`（值在 `thresholds.json`）。
- `Evictions > 0` 或 `ReplicationLag max >= redis_repl_lag_max_s` ⇒ 阻断。
- 分片倾斜只作为事实陈述，**不产出减 shard 建议**。

### MSK

- CPU 用 metric math 的 `CpuUser + CpuSystem`。
- 注意刻度：`KafkaDataLogsDiskUsed` 是 0–100，
  `RequestHandlerAvgIdlePercent` 是 **0–1**。
- `UnderReplicatedPartitions > 0` ⇒ 阻断。存储只能扩不能缩 ⇒ 桶 F。
- **不产出减 broker 数建议。**

### EKS

- 浪费主体不在节点利用率，在 **request 超配把节点池撑大**。
- 五项分析：request vs actual 预订率、bin-packing 理论最少节点数、
  空 nodegroup/未调度节点、HPA `minReplicas` 过高、Fargate request 超配。
- 托管 nodegroup 给具体目标机型；**Karpenter 给 NodePool `requirements`/`limits`
  建议**，因为机型由 NodePool 决定，两者必须在报告中区分标注。
- **节点级建议只出现在节点池聚合行上，不逐节点出。** 托管 nodegroup 的机型只能
  整池改，逐节点降配是不可单独执行的动作，且与聚合行的节省额重复计数。
  节点行与聚合行的逐格填法见 `report-template.md` 的「采集侧自建行的字段填法」。
- **Container Insights 缺失时不要直接放弃 pod 级分析。** 6 项分析里 4 项是
  「配置比配置」，**只需 kubectl**，不需要历史指标：

| 分析 | 只需 kubectl | 需要 Container Insights |
|---|---|---|
| ① request vs allocatable 预订率 | ✅ | — |
| ② bin-packing 理论最少节点数 | ✅ | — |
| ③ 空 nodegroup / 未调度节点 | ✅ | — |
| ④ HPA `minReplicas` 配置 | ✅ | 判断"是否过高"需历史负载 |
| ⑤ Fargate request 超配 | ✅ | — |
| ⑥ pod **实际**利用率历史（request vs actual 的 actual 侧） | — | ✅ 唯一真正不可替代的一项 |

  实测（某集群 Container Insights = 0 条指标，纯 kubectl 得出）：
  节点 allocatable 9.65 vCPU / 34.08 GiB，pod requests 7.79 vCPU / 11.56 GiB
  ⇒ CPU 预订率 80.7%、内存预订率 33.9%，两者差 2.4 倍 ⇒ 机型错配信号明确
  （该换 c 系列而非 m 系列）。这个结论不需要任何历史指标。

  所以缺 Container Insights 时的正确表述是「**pod 实际利用率不可得**」，
  而不是「pod 级分析不可得」。报告须区分这两者。

- **kubeconfig 必须写临时文件，禁止碰本地 `~/.kube/config`。**
  `aws eks update-kubeconfig` 默认写入本地并可能改掉 `current-context`，
  会让 operator 后续的 kubectl 悄悄打到别的集群——对只读审计而言不可接受。

```bash
KC=$(mktemp -d)/config
aws eks update-kubeconfig --region "$R" --name "$C" --kubeconfig "$KC"
export KUBECONFIG="$KC"          # 仅本 shell 生效
kubectl auth can-i list pods --all-namespaces   # 先探权限
# ... 采集 ...
rm -rf "$(dirname "$KC")"        # 用完删除
```

  实测验证：本地 `~/.kube/config` 的 md5 前后一致，`current-context` 未被改。
  **不要用 `aws eks update-kubeconfig` 的默认路径，也不要 `kubectl config use-context`。**

### VPC（本版本仅闲置资源）

- `ActiveConnectionCount` 全窗口恒 0 的 NAT、未关联 EIP → 桶 B。
  NAT 的「全窗口」含**覆盖度要求**（零值序列须覆盖整窗口，3 小时前新建的不算；
  序列整条不存在是 `metric-missing` 而非闲置）。门槛与实现见 `cli-recipes.md §2.6`，
  与 ALB 共用一份 jq。
- **ALB/NLB 是三态判定，不是「`RequestCount` 为 0 就删」。** 两点必须知道：
  `RequestCount` 单指标判不了闲置（实测出现过零 HTTP 请求但连接非零，
  零 HTTP 请求 ≠ 零连接），且**零值序列必须覆盖整窗口才算证据**
  （一台 3 小时前建的 LB 不算）。非闲置那一侧是「需人工确认的候选」，
  金额不计入确定节省。**判定矩阵、覆盖度门槛、取 stat 的要求与可执行实现
  全在 `cli-recipes.md §2.6`，本文不复述判据**——这条判据一度在五个文件各有一份、
  互不相同，其中两份照字面执行会把活跃 LB 报成可删除。
- NAT 数据处理费优化**不在本版本范围**（需实际流量计费数据）。

## 6. 报告生成

按 `references/report-template.md`。两段强制声明不可省。

产出根固定为 `report_output/<account>-<region>-<YYYYMMDD>/`：报告与 findings CSV
直接放在该目录下，原始数据放其 `raw/` 子目录。**作用域目录不可省**——多账号/多 region 靠重跑实现，共用一个目录会让
后一次静默覆盖前一次的报告与审计证据。
**两个交付物的文件名必须带 `sizing_profile`**（`aws-rightsizing-report-<profile>.md`
与 `findings-<profile>.csv`），`raw/` 与 profile 无关故共用：两个预设在同一机队上的
条数与总额都不同，文件名不带 profile 会让第二次运行静默覆盖第一次，
而共用的 `raw/` 两次一模一样，**覆盖之后看不出发生过覆盖**。

**产出物含账号 ID 与资源 ID，不要提交进版本库。** 交付时只交报告，
或把 `report_output/` 加入 `.gitignore`。

发报告前跑自检（**在 skill 根目录下跑**，三条都必须打印 `CLEAN`）：

```bash
# 已核实的假阳性白名单。理由见下——加进来之前必须逐条核实是不是真的只读。
WL='eks update-kubeconfig|configure get'
BILL='\bce [a-z-]|cost-explorer|get-cost-and-usage'   # selfcheck-exempt: 自检自身的模式串

# ① 非只读的 aws 调用
grep -oE 'aws [a-z0-9-]+ [a-z0-9-]+' SKILL.md references/*.md | sort -u \
  | grep -vE ' (describe|list|get)-' | grep -vE "$WL" \
  || echo "CLEAN: read-only"

# ② 账单 API
grep -niE "$BILL" SKILL.md references/*.md | grep -v selfcheck-exempt \
  || echo "CLEAN: no billing API"

# ③ 白名单的前提本身也要守：update-kubeconfig 的每条**调用**都必须带 --kubeconfig。
#    只查以 aws 开头的行（命令行），不查散文里对它的警告。
grep -nE '^[[:space:]]*aws eks update-kubeconfig' SKILL.md references/*.md \
  | grep -v -- '--kubeconfig' \
  || echo "CLEAN: update-kubeconfig 均写入临时 kubeconfig"
```

**白名单为什么是白名单（三条假阳性，逐条核实过）：**

| 命中 | 为什么不是 mutating |
|---|---|
| `aws eks update-kubeconfig` | 只写 `--kubeconfig "$KC"` 指向的临时文件，`KC` 来自 `mktemp -d`，用完 `rm -rf`（见上文 §5 EKS）。不碰 `~/.kube/config`，不调用任何 EKS 写接口。**前提由 ③ 守住** |
| `aws configure get` | 只读本地 CLI 配置文件，不发 API 调用，更不写任何东西 |
| ② 自身的模式串 | `BILL` 的定义行里字面写着 `cost-explorer`，会被 ② 自己命中。用 `selfcheck-exempt` 标记排除；**加这个标记等同于声明"我核实过这行不是真的调用"** |

**这三条必须白名单化，而不是"知道了忽略它"。** 修之前这道自检永远打不出
`CLEAN`，operator 只能学会跳过它——一个没人能让它通过的自检比没有自检更糟，
因为它把"有告警"训练成了默认状态。所以：**新增命中一律先核实，
真只读就进白名单并在上表补一行理由；核实不了就当真阳性处理。**

## 护栏

- 凭证账号与 `target_account` 不一致 ⇒ 立即停止。
- 阈值按 `sizing_profile` 取列，含 `max_reduction_ratio` 与
  `max_mem_reduction_ratio`（两预设取值不同，数值只在
  `references/thresholds.json`）。
- **单次降幅上限对 vCPU 与内存都设，且取值同源。** 内存**不设绝对下限**
  （那是替实例假设它的绝对需求），但设**相对上限**：候选的内存不得低于
  当前规格除以 `max_mem_reduction_ratio`。理由见
  `references/thresholds.md`——`mem_used_percent` 不含可回收 page cache，
  会把内存 p95 系统性压低。
- `allow_stop_recommendations=no` 时不生成桶 C 分节，`stop_candidate` 列保留但留空。
  该输入**不传进 `core.py`**——`core.py` 只做判断，「要不要看桶 C」是报告层的决定。
- **每条降配建议一律标注"需变更窗口 + 回滚预案"**，不按 profile 区分——
  任何规格变更都需要变更窗口与回滚路径，这与压多紧无关。
- 阈值不允许运行时放宽——防止为凑数字放宽判据导致生产事故。
- 无内存数据时不得给出 high confidence 的降配建议。
- 候选集为空 ⇒ 输出"已合理配置"，不得退而给出越界建议。
- **采样量决定置信度，不决定给不给建议。** `0 < biz-hours 点数 <
  min_biz_hours_points` ⇒ 照常产出降配建议，`confidence=low`，
  `blockers` 写明样本量与占门限比例。点数为 `0` 或缺失才标
  `insufficient-data`——那是「无」不是「少」，p95 无从计算。
  旧写法（低于门限即拒绝）**连否决项一起压掉**：实测一个 prod 命名的 MSK
  集群的 `UnderReplicatedPartitions=27` 与一个 Redis 复制组的
  `ReplicationLag=23.88s` 都因此没出现在报告里，报告只写了「点数不足」。
  **该分档只作用于降配路径**：`is_idle`（动作是删除）与
  `is_stop_candidate`（动作是停机）保持硬门限——可回滚的动作允许低置信度
  产出，不可回滚的不允许。
- 新增指标前必须实测确认刻度（0–1 还是 0–100）与维度集，否则判据会被静默吞掉。
- **改动 `core.py` 或任何 `references/*.json` 后必须跑测试**：

```bash
cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done
```

  八个测试文件分别防：阈值键**双向**覆盖（core.py 读的键必须在 JSON 里、
  JSON 里的键必须被读到——孤儿键会让"改 JSON 就能改行为"变成假承诺）、
  散文复述常量（清单由 `thresholds.json` 生成）、
  CSV 契约与实现漂移（四个 producer 全覆盖）、EKS requests 低估、
  sample 里的 verdict 分支不可达、`service` 分派与托管判据与桶 C 三态、
  必填输入的 fail-closed 契约（`sizing_profile` / `min_biz_hours_points` /
  reserved 内存口径 / 阈值字面量）、
  以及**真实机队的回归基线**（`tests/fixtures/regression-fleet.json`，
  两个 profile 的条数与总额逐值断言，且断言采样量守卫真的会触发）。
  循环用 `tests/test_*.py` 通配，新增文件自动纳入门禁；上面这份清单只是说明。
  **这些是本 skill 全部反复出错点的固化**，不要跳过。

## 验证状态（不要假定未标注的部分已验证）

| 部分 | 状态 |
|---|---|
| EC2 / EBS / VPC 判据与 solver | **已在真实账号端到端验证**（两个 region：ap-northeast-1 13 台 EC2 / 31 卷 / 2 NAT / 2 ALB；us-west-2 18 台 EC2 / 20 卷 / 4 NAT / 4 ALB）。可复现的样例是 ap-northeast-1 那 13 台的脱敏判据输入 `tests/fixtures/regression-fleet.json`（`tests/test_regression_fleet.py` 逐值断言其产出）；形状与逐字段语义见 `references/sample-solve.md`。**两次运行的原始产出都不提交**——含账号与资源 ID |
| **RDS 判据** | **已在 us-west-2 实测跑通**：2 个 MySQL 8.0 Multi-AZ（一个 `db.t4g.*`、一个 `db.m5.*`）+ 1 个 `db.serverless`（按规则排除）。指标名与维度名与文档一致。**burstable 实例类**（`db.t4g.*`）走通了降配路径与阻断路径各一条；**非 burstable 实例类**（`db.m5.*`）此前因判据无条件要求信用指标（而该类结构性不发布）而降配路径不可达，已修复——现在信用否决项只对 `db.t*` 生效。**未实测**：Aurora provisioned、PostgreSQL/Oracle/SQL Server、Single-AZ、只读副本 |
| **ElastiCache 判据** | **已在 us-west-2 实测跑通**：Redis 7.1 复制组（2 shard × 3 node）+ 单节点。指标名与维度名与文档一致，走通降配路径。**未实测**：Memcached、Valkey、Serverless、非集群模式 |
| **EKS 判据** | **节点级已在 us-west-2 实测跑通**：1.31 集群 / 1 个托管 nodegroup / 5 节点 / 71 pod，bin-packing 给出理论 4 节点。**pod 级 request 调优未走通**——`ContainerInsights` 命名空间为 0（即便装了 observability addon），拿不到 pod 级历史序列。**未实测**：HPA（集群内 0 个）、Fargate（0 个 profile）、Karpenter（0 个节点） |
| MSK 判据 | 已实测采集与刻度**两个集群、两个监控档**（`DEFAULT` 与 `PER_TOPIC_PER_PARTITION`）。**降配路径仍未走通**，但两个成因在 2026-09-09 后变了：数据仅约 26 小时的那个集群不再是 `insufficient-data`（采样量改分档后它会出结论并带 `confidence=low`），卡住它的是与另一个集群相同的那条——`EnhancedMonitoring=DEFAULT` 不发布 `RequestHandlerAvgIdlePercent`；且两者都已是最小 broker 机型，`cheaper_candidate_exists=false` 会在前置指标检查之前短路成「已合理配置」 |
| NLB (`AWS/NetworkELB`) | **仍未实测**——两个验证 region 均无 NLB |
| `describe-orderable-db-instance-options` | **不可靠**：2026-09-03 复测，pin `--engine-version` + 300 秒超时仍然超时。已在 `cli-recipes.md` §5 给出 pricing API 回退路径，用回退时须在报告注明"候选集来自价目表而非权威可订购列表" |
| **中国区（aws-cn）** | **完全未验证**。pricing API 可用性与 endpoint、币种字段、是否提供 Graviton 机型三项待核实，见 `partition-matrix.md`。**未核实前不得假定与全球区一致**——币种标错会让客户按错误汇率理解节省额 |

## 结论合并规则（单条判据各自正确，合并仍会算错）

单条判据的规则很细，但合并环节此前一条规则都没有。以下四处都实际出过错。

### 桶优先级：同一资源只出一行

```
idle > downsize > excluded
```

（`core.py` 的 `main()` 只产出这三个 `bucket` 值；托管服务行永不进 `idle`。）

命中 `idle` 时，降配方案**降级写入 `blockers`**（"若须保持运行，可降配至 X，省 $Y"），
**不另起一行**。否则同一资源在两个桶各出一行，任何按行求和都重复计数。

### 资源级互斥

**通则：两个动作若不能同时执行，就不能同时计入合计。** 下面几条是它的例子，
不是穷举——遇到新形态先套通则。

- **任何走删除路径的卷都不出 `storage-type` 行。** 两种情形都算：
  `state=available`（未挂载）、宿主实例 `state=stopped`。
  删卷与转存储类型互斥，前者省全额、后者只省约 20% 差价，相加高估。
  实测：一个未挂载的 gp2 卷会同时出删除行 $3.60/mo 与 `gp2→gp3` 行 $0.72/mo，
  两个动作互斥却都进了合计。
- 命中桶 B（闲置）的资源不再出降配行，降配方案降级进 `blockers`（见上一节）。
- 桶 C 候选与降配建议同时成立时，按 `action_type` 的优先级取一个
  （`report-template.md` 的「`action_type` 语义」），另一个降级进 `blockers`。

### 聚合行与成员行

一条建议作用于一组资源时，有两种合法形状。**判别式不是「动作能否对单个成员单独
执行」**——单个 MSK broker 的机型同样不能单独改，这个问法分不开下面两种。
判别式是：**这组成员在本 skill 的 inventory 里是否各自已经是一行。**

- **各自已是一行 ⇒ 多成员行 + 一聚合行。** 本版本只有 EKS 节点池：成员是独立的
  EC2 实例，各有实例 ID 与各自的按需价。
- **不是 ⇒ 就出一行，带 `instance_count`。** 本版本有 MSK 集群
  （`instance_count=brokers`）与 ElastiCache 复制组／集群（`instance_count=节点数`）。

**成本与节省额落在哪一行，唯一定义在 `report-template.md` 的「分母的范围」**，
本节不复述——两处各写一份，已经漂移过一次（旧版把 MSK 与 ElastiCache 也写成
「聚合行留空成本」，而它们没有成员行，照做会让整个服务从分母里消失）。

本节只留一条合并规则：**同一组资源只能有一处带节省额。** EKS 节点池的机型与节点数
只能整池改，所以成员行不带节省额、`action_type=none`，节省额只在聚合行的
`other_save_mo` 上；逐格填法见 `report-template.md` 的「采集侧自建行的字段填法」。

### 汇总口径：按「路线」求和，不按列求和

`nb_save_mo` 与 `b_save_mo` 是**同一资源上的替代选项**，不是两笔独立节省。
**禁止 `Σnb_save_mo + Σb_save_mo`。**

四条合法口径（两条降配路线 + 桶 B 合计 + 采集侧合计）的定义、作用域、互斥关系与
实测依据，在 `report-template.md` 的「汇总口径」一节，**本节不复述**——同一个口径在
两处各写一份必然漂移。这里只留禁止项：

- 不得按列相加（`Σnb + Σb`）。
- 不得把两条降配路线相加。
- 不得对 `bucket=idle` 的行求 `nb_save_mo`（那是"若须保持运行"的替代方案，
  不是删除可省；桶 B 的口径是 `Σ cur_cost_mo`）。**求和一律带作用域**，
  别对整表求和——`cli-recipes.md §6 ③` 修的就是这个漏掉的过滤。
- 不得把采集侧自建行的节省额写进 `nb_save_mo` / `b_save_mo`（那两列各自背着目标
  机型与 delta，是可审计的；采集侧用 `other_save_mo`）。
- 不得把托管服务候选小计并进头条数字。
- 摘要里不得只报一条口径——四条并列，各标口径，不相加。

`report-template.md` 原先只防了"每资源两行"，没防跨资源按列相加——两者都要防。

### 交付前必跑

```bash
# ① rid 唯一性：同一 ID 多行即重复计数（$4 = 契约列序里的 rid）
awk -F, 'NR>1{gsub(/"/,""); print $4}' findings-<profile>.csv | sort | uniq -d
# ② 分桶合计 == 逐条合计
# ③ bucket / action_type / confidence / window_profile / service 五个枚举的合法性
#    合法值见 report-template.md「枚举值」的 enum-values 代码块（测试解析的就是那一份）
# ④ 列数与契约一致：allow_stop_recommendations=no 时 stop_candidate **留空不删列**，
#    列数变化会破坏下游校验
# ⑤ 成员行存在的聚合行 cur_cost_mo 为空（否则分母把成员算两遍）；没有成员行的
#    （MSK / ElastiCache）照填成本，留空会让整个服务从分母消失。同一组资源只有一处带节省额
# ⑥ 分母完整性：范围内每个资源恰好一行，无建议的也出行（见 report-template.md「分母的范围」）
# ⑦ 采集侧自建行逐格与 report-template.md「采集侧自建行的字段填法」那 18 行比对，
#    **差异必须逐条记进报告**：那张表是从判据行为与两次运行的分歧推出来的规范，
#    还没有任何一次真实运行逐行验证过它。第一次真实运行就是它的第一次验证。
```

## 易错项速查（全部为实测踩过的坑）

| 坑 | 后果 | 正解 |
|---|---|---|
| 取价按机型单键 | 非 Linux 实例成本低估至多 **7.79x**（m5.xlarge Linux $0.248 / Win+SQL Ent $1.932） | 键用 `(机型, UsageOperation)` |
| 取价过滤 `operatingSystem=Linux` | 同上 | 不过滤 OS，全量取回后建复合键 |
| 无价格时退回"最小够用" | 推出比现状更贵的机型（`i3en.large` $0.266 > `m5.xlarge` $0.248） | 无价格则不产出降配建议 |
| 用 `CurrentGeneration` 判新旧 | 反向排除 m6i/r6i，同时放进 t2/i3/x1 | 用 legacy 清单 + 用途分类 |
| 不做用途分类过滤 | Storage optimized 的 `i3en` 被选为通用机型降配目标 | 限 GP/Compute/Memory 或同当前分类 |
| 先允许跨分类再剔 legacy | 跨分类把同组最便宜的老机型拉进来（`a1` 比 `m6g` 低 35%） | 顺序不可换：先 legacy 后跨分类 |
| 复用其他 region 的 offerings | 错误排除大量可用候选（观测值 @2026-09-04：东京 1198 / 弗州 1371，个数会漂移，见 `cli-recipes.md §0.1`） | 按当前 region 现查 |
| Redis 用 `CPUUtilization` | Redis 单线程，整机 CPU 含后台线程，系统性误判 | 用 `EngineCPUUtilization` |
| MSK 判据写 `> 70%` | `RequestHandlerAvgIdlePercent` 是 **0–1** 刻度，判据永不成立、建议被静默吞掉 | 写 `> msk_handler_idle_min`；同 namespace 内刻度不统一，新增指标先实测 |
| MSK CPU 分别聚合再相加 | 两序列 p95 之和 ≠ 和的 p95 | metric math `Expression: "m1+m2"` 逐点相加 |
| `agg.jq` Label 给 4 段 | `stat` 被指标名占掉，`Average`/`Maximum` 区分全丢 | 3 段；多指标把指标名编进第一段 `rid@metric\|type\|stat` |
| 假定时间戳以 `Z` 结尾 | `fromdateiso8601` 直接报错 | 用 `parse_ts`；CLI v2 实测输出 `+08:00` |
| CWAgent 只给 `InstanceId` 维度 | 返回空序列 | 提供发布时全部维度（`ImageId`+`InstanceId`+`InstanceType`） |
| burstable 候选只校验基线 | 突发上限是标称 vCPU 的 100%，选出物理上服务不了峰值的机型 | 另加 `cand_vcpu >= ceil(cur_vcpu × peak% / ceiling)` |
| burstable 回收量按标称 vCPU 算 | `m5.xlarge → t3.xlarge` 报 0 回收 | 按 `vcpu × baseline_pct` 算，当前机型也用有效容量 |
| **采样不足时拒绝出建议** | 「点数不足」会把**真实阻断原因一起压掉**：实测一个 prod 命名 MSK 集群的 `URP=27` 与一个 Redis 组的 `ReplicationLag=23.88s` 都因此没进报告。样本少不等于判不了 | `0 < n < min_biz_hours_points` ⇒ 照常出建议 + `confidence=low` + blocker 写明样本量；只有 `n` 为 `0`/缺失才 `insufficient-data`。**该分档不放开 `is_idle`／`is_stop_candidate`**（删除与停机不可回滚） |
| **否决项的容忍度看不见** | 三条否决项改判 p95 后，窗口内最多 **5%** 的时长处于破损仍不否决（30 天约 36 小时），而这个数藏在「用 p95」这个措辞里 | 容忍度写进 `core.py` 的 `VETO_TOLERANCE_PCT` 与 blocker 文案，客户看得到。**不放进 `thresholds.json`**——分位数写在 `agg.jq` 里、对所有 p95 一致，加键是假承诺。要真正收紧须采集侧给「破损持续了几个点」 |
| **ElastiCache 内存用 EC2 映射值** | 映射会成功但值是错的，无任何信号。实测 `cache.t3.medium` 真实 **3.09 GiB**、映射得 **4.00 GiB**，偏 29%。`DatabaseMemoryUsagePercentage` 是相对真实节点内存的百分比，乘错基数即算错绝对量 | 内存取 `AmazonElastiCache` pricing 的 `memory` 属性；映射只用于取 vCPU 与架构 |
| **多维度指标 Label 只编 id** | `disk_used_percent` 每挂载点一条序列（实测单实例 6 条），Label 必然撞名 ⇒ 要么被重复 Label 断言阻断，要么 `agg.jq` 静默只留一个挂载点 | 把 `path`/`device`/`fstype` 编进 Label（同一 path 可挂不同 device，故不能只编 path） |
| **拿 `mdq.json` 长度当结果数分母** | metric math 被加数标 `ReturnData:false` 不回传序列，实测 MSK 32 query 只回 24 条，按长度比对会误报 | 分母只数 `ReturnData != false` 的 query |
| **缺 Container Insights 就跳过整个 pod 级分析** | 6 项里 4 项是配置比配置，纯 kubectl 即可。实测某集群 CI=0 仍算出 CPU 预订率 80.7% vs 内存 33.9%（差 2.4 倍，机型错配信号明确） | 只有「pod 实际利用率历史」真正依赖 CI；报告须区分这两者 |
| **`aws eks update-kubeconfig` 用默认路径** | 写入本地 `~/.kube/config` 并可能改掉 `current-context`，operator 后续 kubectl 会悄悄打到别的集群 | `--kubeconfig $(mktemp -d)/config` + `export KUBECONFIG` 仅本 shell，`trap` 退出即删 |
| 无内存数据就拍个内存下限 | 替实例做假设，小实例过度保护、大实例照样放行 | 无数据则内存不动（`required_gib = cur_gib`） |
| 窗口用 `date -u -v-30d`（带当前分秒） | `Period=3600` 桶对齐 `StartTime` 而非自然小时，同一份数据被切进不同时段档。实测同一实例 `peak_cpu` 在 **18.18% 与 10.59%** 间摆动，另一台 **11.72% → 3.86%**，直接改变 `required_vcpu` | 对齐到**业务本地午夜**：`END=$(( (NOW+TZ)/86400*86400 - TZ ))`。整个业务日内重跑逐字节一致，且桶边界落在本地整点（非整小时时区也成立） |
| 一次把 >139 个序列丢给 `get-metric-data` | 超 100,800 数据点上限时 **API 不报错**，CLI 自动翻页把同一 Label 的序列拆段拼接（实测 189 序列 → 378 条结果，一条序列被拆成 534+187）。`agg.jq` 每键出两行、p95 只基于片段，`pick` 取 `.[0]` 只用 74% 数据，**四项不变式全部照样通过** | 按 `batch=139` 分批 + 合并后断言重复 Label 为 0；再加时段点数闭合式 `biz+off+weekend == WINDOW_DAYS×24` |
| **Sum 语义指标用 `Average` 再乘系数** | 该系数取决于 SampleCount 而非发布粒度，本 skill 上写错过三次（×24 → ×288 → ×1440），每次都标着"实测"。×24 低估 12 倍、×288 低估 5 倍，而闲置门限只有 5 MB/日 | **改采 `Stat=Sum` 逐小时相加**，零换算假设，整类错误消失 |
| 以为空序列 = 该 region 没这类资源 | 维度名/维度值写错时 `list-metrics` 与 `get-metric-data` **都只返回空、不报错**（实测把 `Cluster Name` 写成 `ClusterName` 即得 `[]`） | 全空 ⇒ 查模板；部分空 ⇒ 用 `list-metrics --dimensions` 交叉核对是否真实缺失（PI 未开 / 非 burstable / 零流量） |
| CWAgent 维度集当成全账号统一 | 实测同账号一台发布 `ImageId+InstanceId+InstanceType`、另一台只发布 `InstanceId`（取决于 agent 的 `append_dimensions`）；按固定三维度拼会漏掉后者 | 用 `mdq-dims.jq` 从 `list-metrics` 回包原样搬维度 |
| RDS/ElastiCache/ALB 用聚合维度采集 | 这些 namespace 同时发布 `DatabaseClass`/`EngineName`/`Role`/`NodeGroupId`/`TargetGroup`/`AvailabilityZone` 等组合，混用会重复计数且无法映射回单个资源 | 只取单一资源维度：`DBInstanceIdentifier` / `CacheClusterId` / `LoadBalancer` |
| `FreeableMemory` 用 `Maximum` 或 p95 判阻断 | 判据是"最小值 < 实例内存 15%"，空闲越多越安全 ⇒ **取错方向，把危险实例判成安全** | 显式采 `Stat=Minimum`，读 `agg.jq` 新增的 `min` 列 |
| RDS 只看 `DBLoad` 判是否可降配 | 实测某 `db.t4g.medium` 的 `DBLoad` p95 = 0.547 < 0.5×2vCPU ⇒ 前置"满足"，但 `CPUCreditBalance` 最小值 = 0、`CPUSurplusCreditsCharged` 单小时最大 = 730.6（采 `Maximum`，不是窗口累计） ⇒ 规格已不足，是升配候选 | `CPUSurplusCreditsCharged > 0` 作**独立否决项**，优先级高于 `DBLoad` |
| 以为 MSK `DEFAULT` 监控档没有 per-broker 指标 | 实测 `DEFAULT` 下 CPU/磁盘/URP/内存/吞吐**都有** per-broker 数据，唯一缺 `RequestHandlerAvgIdlePercent` | 按缺的那一个指标决定：前置不可评估 ⇒ 不产出降配建议，别整段放弃 MSK 分析 |
| 以为装了 CloudWatch agent 就有 Container Insights | 实测集群装了 `amazon-cloudwatch-observability` addon + `cloudwatch-agent` DaemonSet，`ContainerInsights` 命名空间**仍为 0** | 用 `list-metrics --namespace ContainerInsights` 实证；为 0 则只出节点级结论 |
| EKS bin-packing 把 DaemonSet 和业务 pod 混算 | DaemonSet request 是**每节点固定开销**，随节点数增减；混进总量会系统性高估所需节点数 | 按 `ownerReferences[0].kind` 分开：`可用量 = 节点可分配 − DaemonSet 每节点开销` |
| pod request 自己 sum 容器 | 实测有 6 容器的 controller pod，只取 `[0]` 严重低估；而**逐容器求和也仍然低估**——K8s 的调度用量是 `max(Σ 普通容器, 各 init 容器的最大值) + pod overhead`。示例：两容器 `250m+50m`、init `2`、overhead `100m`，求和得 300m，调度口径 2100m，差 **7 倍** | 一律调 `core.pod_requests()`，采集侧保留 `kubectl -o json` 原始输出（`cli-recipes.md` §4.1b） |
| ElastiCache/ALB 按机型或单一 `usagetype` 取价 | 同一 `cache.t3.medium` 有 `NodeUsage`(0.068) / `ExtendedSupportYr1_Yr2`(0.054) / `ExtendedSupportYr3`(0.109) 三个价，`unique_by` 随机取 ⇒ **高估 60% 或低估 21%**；ALB 同一 usagetype 返回 0.0125/0.0225/0.025 | ElastiCache 限 `usagetype` 以 `-NodeUsage:` 开头；ALB 叠加 `operation=LoadBalancing:Application`。**这两步都只是第一道，各自还有第二道，见下两条** |
| **挡住 `usagetype` 就以为 ElastiCache 取价对了** | Valkey / Redis / Memcached **共用逐字相同的 `usagetype`**，三行都过 `-NodeUsage:` 过滤、`vcpu`/`memory` 也都有值，两道旁证全不触发。实测 `unique_by(.t)` 取到 Valkey 的 0.0544 ⇒ **对 Redis 集群低估 20%**；只按机型分组时 us-west-2 有 **94** 个机型带多价 | 键改成 `(instanceType, operation)`，与 EC2 侧同构；`operation` 按集群 `Engine` 选（注意 API 回小写、pricing 回大写）。**两道过滤缺一不可**：只用 `(t, operation)` 而省掉 usagetype 过滤，实测仍有 **153** 个键带多价 |
| **ALB 取价只叠 `operation` 就收工** | 实测 `operation=LoadBalancing:Application` 下仍有 `Outposts-LoadBalancerUsage` 与 `-TS-LoadBalancerUsage`。`-TS-` 只有正确价的 **22%–28%**（us-west-2 0.0063/0.0225、ap-northeast-1 0.0054/0.0243），随机取到即**低估 3.6–4.5 倍** | 不按 `usagetype` 过滤，只按 `operation` 拉回，再在 jq 里排除 `Outposts` 与 `-TS-`，并断言筛完只剩 1 条 |
| **用 `usagetype` 反推 region 价目前缀** | 前缀**不能由 region 码机械推出**：实测 `eu-west-1` → `EU-`（不是 `EUW1-`）、`ca-central-1` → `CAN1-`、`us-east-1` **同一 region 内既有裸 `NatGateway-Hours` 也有 `USE1-RegionalNatGateway-Bytes`**。拼出不存在的串时 pricing API **返回空且退出码 0**（实测 `EUW1-NatGateway-Hours` 回 0 条无报错），是「空结果不报错」发生在取价侧 | 需要前缀就从回包里读，别拼；更好的做法是干脆不依赖前缀——按 `productFamily`/`operation` 拉回后在 jq 里按后缀筛（ALB 见 `cli-recipes.md` §5.1） |
| 大对象用 `--argjson` 传给 jq | 单 region 价格表约 21,000 键 / 1 MB，报 `Argument list too long` | 用 `--slurpfile f file.json` + 前缀表达式 `$f[0] as $price \|` 绑定 |
| jq 里靠 `$var // 默认值` 兜未传的参数 | 引用未定义的 `$var` 是**编译期错误**（实测 `$stats is not defined` / `$idprefix is not defined` + `1 compile error`），不会退化成 null，`//` 执行不到。**参数表里写"（默认 X）"而实现里没有默认值，等于教人写出必然编译失败的命令** | 必传参数就写成必传并在文件头注明；`mdq-dims.jq` 的 `mn`/`idname`/`ty`/`stats`/`idprefix` **五个全必传** |
| 沿用旧的 8 列 summary 列号写 awk | 加了 `metric` 与 `min` 后是 10 列，列号整体差 1；`$5+0==0` 变成"拿 bucket 字符串比 0"恒真 ⇒ 假告警 | 固定 10 列布局 `resource,metric,type,stat,bucket,n,mean,p95,max,min`，`n=$6 mean=$7 p95=$8 max=$9 min=$10` |
| **否决项判「曾经出现过」而不是「持续成立」** | 一次滚动重启的尖峰否决整个窗口。实测 8 个 MSK 集群 `UnderReplicatedPartitions` 的 Average 序列 p95 **全为 0**，而 max 达 27–244（MSK 自动打补丁必然产生尖峰）⇒ 任何被维护过的集群降配路径永久关闭。ElastiCache 的 `ReplicationLag` 同形状（p95 毫秒级，max 10.2s / 23.9s） | 判 `*_p95`（gauge 取全窗口 Average 的 p95，计数类取 `Sum` 的 p95）；`*_max` 只写进 `blockers` 让尖峰仍可见；`*_p95` 缺失时回退 `*_max` 保持向后兼容 |
| **下限型／峰值型指标只取 `biz-hours` 档** | `freeable_mem_min_gib` 取 biz-hours 最小值会漏掉备份/批处理窗口的真实低点（实测两台 RDS 偏高 0.18% 与 1.1%），方向是**把危险实例判成安全**；主判据指标（`sample_n` / `dbload_p95` / `engine_cpu_p95`）才限定 biz-hours | 下限型与峰值型一律取 `agg.jq` 的 **`full-window`** 档 |
| **给 `agg.jq` 加了 `full-window` 档后仍按 bucket 全量求和** | `§2.6` 的覆盖度一行是 `group_by(.rid+"|"+.stat) \| map(.n)\|add`，新档让 `n` 翻倍（实测 465 → 930），覆盖度看起来充足 ⇒ 正是该节警告的「偏松」失效 | 覆盖度直接读 `bucket == "full-window"` 那一行，不再拿三档相加 |
| **「仅某子集机型发布」的指标当成「缺失」fail-closed** | `CPUSurplusCreditsCharged` 只有 T 系列发布，非突发机型该序列结构性不存在。无条件卡 `is None` 会让**突发降配路线在生产上永久不可达**（实测 29 台机队里 25 台被压掉，3 行误判成「已合理配置」），且 `burst_na` 让客户去补一个不可能存在的指标。RDS 侧同一缺陷修于 2026-09-04，EC2 侧因文档误称「已做区分」而漏到 2026-09-10 | **先判适用性，再判缺失**：`if cs["burst"] and sc is None`（EC2）/ `_rds_is_burstable()`（RDS）。回归 fixture 必须用真实值（非突发机型填 `null`），填 0 会让整套基线为一个不可能的输入背书 |
| **「仅某子集资源发布」的指标，判据先判缺失而不先判适用性** | 「不适用」与「缺失」是两件事：前者是**资源形态**的属性，后者是**采集**的属性。混同的两个方向都错——把「不适用」当「缺失」会让整条路径永久不可达（实测 `CPUSurplusCreditsCharged` 让 25/29 台的突发路线关闭）；把「缺失」当「不适用」会让否决项静默消失。已知成员：`CPUSurplusCreditsCharged`（仅 `t*` / `db.t*`）、`CPUCreditBalance`（同）、`ReplicationLag`（仅有副本时）、`EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage`（仅 Redis/Valkey，Memcached 不发布） | **先解析适用性、再判缺失**，并在该判据处写明落在 fail-closed 还是 fail-open 哪一侧及理由。区分二者的依据必须是**输入里已有的形态字段**（`spec["burst"]` / 实例类前缀 / 引擎 / 节点数），**不得靠指标自身的有无去推断**——那是循环论证。新增指标先按这张清单比对 |

## references

| 文件 | 内容 |
|---|---|
| `thresholds.md` | 阈值、指标刻度、统计口径、机型族过滤（唯一真值源） |
| `legacy-families.md` / `.json` | 排除机型族及年代证据 |
| `instance-specs.md` | 实例类→EC2 映射、T 系列基线表 |
| `baseline-pct.json` | T 系列基线百分比（**静态资产**：无 API 可查，产品特性不变） |
| `metrics-catalog.md` | 服务→namespace/指标/维度/stat/刻度，含各服务实测状态 |
| `cli-recipes.md` | 采集、查询生成、聚合、solver 输入组装的命令模板（每 namespace 一段） |
| **`core.py`** | **全部判据（EC2 + RDS + ElastiCache + MSK）**：需求反推、候选筛选、双候选、缺失值语义、闲置、桶优先级 |
| `agg.jq` | 时区归一化 + 三档时段聚合，输出 `mean/p95/max/min` |
| `mdq-multi.jq` | **多指标查询生成器**，单维度 namespace 通用（EC2/RDS/ElastiCache/NAT/ALB），支持按指标覆盖 `stats` |
| `mdq-dims.jq` | **多维度查询生成器**，维度组合从 `list-metrics` 回包原样搬（CWAgent 类）。`mn`/`idname`/`ty`/`stats`/`idprefix` **五个全必传**（jq 引用未定义变量是编译期错误，`//` 兜不住） |
| `mdq-msk.jq` | **MSK 专用**：逐 broker 展开 + `CpuUser+CpuSystem` metric math + 带空格的维度名 |
| `partition-matrix.md` | aws / aws-cn 差异（含中国区 3 项待核实） |
| `report-template.md` | 报告骨架与 findings.csv 规范 |
