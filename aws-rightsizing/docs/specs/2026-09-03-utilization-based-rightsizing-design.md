# 基于资源利用率的 AWS 机型配置优化 skill — 设计方案

- 日期：2026-09-03
- 阶段：第一阶段（纯配置优化，不含成本计算，不含架构变更）
- 作用域：**单个指定 AWS account**
- 交付形态：agent skill，交付给客户 devops 团队使用

## 1. 目标与非目标

### 目标

在**一个指定的 AWS account** 内，仅凭只读权限采集资源清单与 CloudWatch 利用率指标，产出一份按可回收容量排序的机型/配置优化建议报告。

覆盖服务：EC2、EBS、RDS、ElastiCache Redis、MSK、EKS、VPC（闲置资源部分）。

skill 不感知账号用途（prod / stg / sit 等），环境类型由运行时输入指定。多账号场景由 operator 换凭证重复执行，skill 内部不做跨账号 assume-role。

**建议范围限定为"同形态降配"**：在不改变架构形态、不改变 CPU 架构、不降低可用性等级的前提下，把资源规格调整到与实测负载匹配。

### 非目标（第一阶段明确不做）

| 不做 | 原因 |
|---|---|
| **任何 Cost Explorer / CUR / 账单 API 调用** | 不接触实际账单数据 |
| RI / SP 承诺覆盖分析 | 需账单数据，第二阶段 |
| 摊销成本、实际账单金额 | 需账单数据，第二阶段 |
| 跨账号 assume-role、多账号汇总 | 作用域为单账号 |
| ElastiCache / MSK / RDS 迁 Serverless | 架构变更，本版本不做 |
| Graviton（arm64）迁移 | CPU 架构变更，本版本不做 |
| Spot / Karpenter 引入 | 架构变更，本版本不做 |
| Redis 减副本、减 shard | 降低可用性等级 / 需数据重分布，本版本不做 |
| RDS Multi-AZ → Single-AZ | 降低可用性等级，本版本不做 |
| Trusted Advisor | 依赖 Support plan；窗口写死 14 天；不覆盖 Redis/MSK/EKS |
| NAT 合并、VPC Endpoint 替代 NAT | 结论 100% 取决于数据处理费 vs endpoint 小时费的平衡点，无价格无从判断 |
| 生成变更命令、IaC、工单 | 输出边界为纯只读报告 |
| 任何写操作 | skill 仅允许 describe / list / get |

skill 内必须写明两条硬约束，均非"暂不实现"而是本版本的边界：

- **禁止调用 `ce:*` 及任何账单 API。** 允许 `pricing:GetProducts` 读公开按需价目。
- **禁止产出改变架构形态、CPU 架构或可用性等级的建议。**

### 关于 pricing 的范围修订（2026-09-03）

原设计禁止一切 pricing 数据。实测证明该约束会产出**反向错误**的建议：
无价格时候选只能按"最小够用"挑，而 `m5.xlarge`（$0.248/hr）的最小够用候选是
`i3en.large`（**$0.266/hr**）——一条让账单上涨 7% 的"降配"建议。

因此改为：**使用公开按需价目（`pricing:GetProducts`）做候选选型与排序**。
仍然不碰实际账单数据（`ce:*` / CUR），所以 RI/SP 覆盖情况依旧不在本版本范围内。

实测成本可接受：单 region 加 Linux/Shared/NA/Used 过滤返回 1176 条、9 秒，
无需下载 288 MB 的 bulk 价目表。

### 第一阶段的已知缩水项

- VPC 这一节只剩闲置资源识别（零流量 NAT、未关联 EIP、零请求 ALB/NLB）。NAT 数据处理费优化是 VPC 成本主体，但无价格数据无法判断。
- Redis 与 MSK 只能给出同形态的节点/broker 型号降配，副本数、shard 数、Serverless 均不在范围内，因此这两个服务的优化空间会比全量分析小。

这些是设计上接受的缩水，不是遗漏。

## 2. 运行时输入

skill 启动时向 operator 确认以下输入，缺失则询问，不猜：

| 输入 | 说明 | 默认 |
|---|---|---|
| `target_account` | 目标账号 ID（用于校验当前凭证确实指向它，防止跑错账号） | 无，必填 |
| `regions` | 要扫描的 region 列表 | 当前 profile 的 region |
| `window_days` | 指标回看窗口 | 30 |
| `sizing_profile` | `aggressive` / `conservative`。决定阈值与 `max_reduction_ratio` | 无，必填 |
| `allow_stop_recommendations` | 是否产出桶 C 定时停机建议，与 profile 正交 | 无，必填 |
| `business_timezone` | 时段画像切档用的业务时区 | UTC+8 |

`target_account` 校验方式：`sts get-caller-identity` 的 `Account` 必须与输入一致，不一致立即停止。这是防止在错误账号上产出报告的最低成本护栏。

原设计用 `env_type`（prod / non-prod）同时控制阈值与停机建议，**2026-09-03 拆分**：

- 实测原 prod / non-prod 两列产出**完全相同**（13 条 / $555.03 无差别）——`ceil()` 在小 vCPU 数下吞掉了两档差异。用环境命名承诺了一个不存在的保护，故改为按风险偏好命名 `aggressive` / `conservative`，并把差距做实（实测 $527.15 vs $373.00）。

  > **⚠️ 2026-09-04 补注：本条里的三个金额（$555.03 / $527.15 / $373.00）已撤回，不可引用。**
  > 本文件是设计史，上面这段推理原样保留——**决策本身不受影响**：两个预设在纠正后的
  > 数据上确实产出不同，按风险偏好命名的理由也照旧成立。作废的只是金额。
  >
  > 原因：当时用的回归 fixture 把每台资源的 `cpu_n` 填成了 **720**，那是 30 天窗口的
  > **全窗口**点数（`biz + off + weekend == WINDOW_DAYS × 24`），而 `cpu_n` 的定义是
  > **`biz-hours` 档**的点数——是全窗口的子集，不可能等于全集。口径错的后果是采样量守卫
  > （`min_biz_hours_points`）恒不触发：13 台全部产出建议，其中两台是窗口内新建、
  > biz-hours 只有 154 与 55 个点、p95 没有统计意义的实例。
  >
  > 可复现的数值见 `aws-rightsizing/references/thresholds.md` 的「solver 阈值」小节，
  > 背后是仓库内的脱敏 fixture `aws-rightsizing/tests/fixtures/regression-fleet.json`，
  > 由 `aws-rightsizing/tests/test_regression_fleet.py` 逐值断言。用真实 biz-hours 点数
  > 跑出来是 **11 条 / $401.51（aggressive）** 与 **10 条 / $312.48（conservative）**。
- 停机容忍度与规格紧凑度**正交**，拆为独立输入 `allow_stop_recommendations`，不由 profile 推导。
- 原先仅 prod 才标的"需变更窗口 + 回滚预案"改为**无条件标注**——任何规格变更都需要它。

## 3. 权限与运行形态

### 所需权限（目标 account 内的只读 role）

```
sts:GetCallerIdentity
pricing:GetProducts          # 公开按需价目，用于候选选型与排序
cloudwatch:GetMetricData
cloudwatch:ListMetrics
ec2:Describe*                # 实例 / 卷 / 快照 / EIP / NAT / regions
                             # instance-types / instance-type-offerings
rds:Describe*                # 含 describe-orderable-db-instance-options
pi:GetResourceMetrics        # Performance Insights，RDS 降配的第一判据
pi:DescribeDimensionKeys
elasticache:Describe*
kafka:List*
kafka:Describe*
eks:Describe*
eks:List*
elasticloadbalancing:Describe*
```

外加：EKS access entry 绑定只读 ClusterRole（读 node / pod / workload / HPA / PDB 配置）。

可选增强（探测到则用，无则跳过）：`compute-optimizer:Get*`。仅取其 p99.5 利用率与推荐机型，用于交叉校验本 skill 判据是否跑偏；**忽略其输出中的所有金额字段**。

不需要 payer 权限，不需要账单权限，不需要跨账号信任关系。

### 运行形态

skill 不附带自研脚本包。skill 提供流程指令 + 内嵌 CLI/jq 命令模板，由 agent 现场执行。

`GetMetricData` 需一次提交数百个 query，agent 手写 JSON 不可靠。解法为内嵌 jq 模板，从 inventory JSON 生成查询体文件，再用 `--cli-input-json` 提交。

### partition 自适应

运行时探测 partition（`aws` / `aws-cn`），差异走 `references/partition-matrix.md` 查表：可用机型与 node type 集合差异（中国区显著更小，直接影响候选集筛选结果）、API endpoint 差异。

**降配目标机型不得硬编码 family ladder。** 必须先查目标 region/AZ 的实际可用集合，再从中挑选：

| 服务 | 可用性查询 |
|---|---|
| EC2 / EKS 节点 | `ec2 describe-instance-type-offerings --location-type region` |
| RDS | `rds describe-orderable-db-instance-options`（**必须 pin `--engine-version` 且异步执行**，实测不 pin 时超 120s 超时） |
| ElastiCache | `elasticache describe-reserved-cache-nodes-offerings`（唯一程序化来源，已实测） |
| MSK | 无 broker 型号列表 API（已实测确认），走文档维护的查表 |

可用性只做 **region 级**，不做 AZ 级。实测 ap-northeast-1 三个来源完全一致（各 1154 个）。
AZ 级更严（`ap-northeast-1d` 少 112 个机型、`t3a.micro` 在 `ap-northeast-1c` 不提供），
本版本不采用，允许实例在 AZ 间迁移。

## 4. 数据流

```
preflight  →  inventory/*.json  →  jq 生成查询体  →  get-metric-data --cli-input-json
   ↓              ↓                                          ↓
探测数据缺口     describe-*                            metrics/raw-*.json
                                                            ↓
                                              jq 切三档时段 + 算 avg/p95/max
                                                            ↓
                                                    metrics/summary.csv
                                                            ↓
                                          agent 只读 summary（不读 raw）→ 报告
```

中间产物落盘的三个理由：不需要维护脚本包；结果可重现可审计；agent 上下文只吃 summary 不吃全量 raw JSON，几百台资源不会撑爆上下文。

### 采集参数

- 窗口：`window_days`，默认 30
- `period=3600`（CloudWatch 1 小时粒度保留 455 天，覆盖任意窗口长度）
- 每指标取两个 stat：`Average` 与 `Maximum`。不取 CloudWatch 的 `p95` stat——它是每小时内的 p95，跨小时聚合无意义。solver 的两个输入改为：

```
p95_cpu := 小时级 Average 序列的 p95   （代表持续负载）
max_cpu := 小时级 Maximum 序列的 max   （代表峰值）
```

  内存同理。两个 stat 而非三个，query 数减少 1/3。
- 分批约束：`get-metric-data` 单次上限 500 个 MetricDataQuery 且 100,800 个数据点。30 天 × 3600s = 720 点/指标 → 单次约 140 个指标，按此分批

### 时段画像

按 timestamp 用 jq 切同一批 raw 数据，零额外 API 调用：

```
biz-hours   工作日 09:00–20:00   ← 降配判据只看这档
off-hours   工作日 20:00–09:00   ← 定时停机判据
weekend     周六日全天            ← 定时停机判据
```

降配判据只看 biz-hours，避免夜间低谷拉低均值导致误建议。这是本设计最重要的单一防误判措施。

切档使用运行时输入 `business_timezone`（默认 UTC+8）。CloudWatch 返回的 timestamp 为 UTC，jq 切档前须先做时区偏移。

## 5. 降配目标推算与排序

### 5.1 不采用"同 family 降一档"模型

降配不等于同 family 降档。常见场景是 CPU 严重空闲而内存吃满，正确动作是**换 family 同时降 size**：

```
m5.xlarge (4 vCPU / 16 GiB)  →  r5.large (2 vCPU / 16 GiB)
CPU 砍一半，内存不动
```

此时 normalization factor 无法用于排序（NF 只在同 family + 同 platform + 同 tenancy 内可比，跨 family 无意义），"降一档/降两档"的阶梯模型也无法表达这类建议。

因此改为：**按 CPU 与内存两个维度分别反推需求量，再从目标 region 可用的机型集合中筛选"最便宜且够用"的机型。** 跨 family 成为算法的自然输出，而非特例。

注意选型依据是**价格最低**而非**规格最小**。两者不等价：`m5.xlarge`（$0.248/hr）
的最小够用候选是 `i3en.large`（$0.266/hr），比现状更贵。详见 §1 的 pricing 范围修订。

注意跨 family 与跨架构的区别：`m5 → r5` 是同 x86 架构内换 family，在范围内；`m5 → m6g` 是 CPU 架构变更，不在范围内（见 §1 非目标）。

### 5.2 目标机型推算算法

统一适用于 EC2、EKS 节点、RDS、ElastiCache、MSK broker。

**第一步：反推需求量。** 由当前规格与实测利用率，反推满足目标利用率所需的容量。

```
required_vcpu = max(
    ceil( cur_vcpu × p95_cpu / target_cpu_p95 ),
    ceil( cur_vcpu × max_cpu / ceiling_cpu_max )
)

required_gib  = max(
    ceil( cur_gib × p95_mem / target_mem_p95 ),
    ceil( cur_gib × max_mem / ceiling_mem_max )
)
```

两项取 max，保证降配后 p95 与峰值都不越界。峰值项不可省——只看 p95 会把有尖峰的负载降到峰值打满。

阈值（`references/thresholds.md` 为唯一真值源）：

| 参数 | aggressive | conservative |
|---|---|---|
| `target_cpu_p95` | 60% | 40% |
| `ceiling_cpu_max` | 85% | 60% |
| `target_mem_p95` | 70% | 50% |
| `ceiling_mem_max` | 85% | 70% |
| `max_reduction_ratio` | 3x | 2x |

**无内存数据时 `required_gib = cur_gib`**，即内存维持不变、只回收 CPU。这正是产生 `m5.xlarge → r5.large` 这类建议的路径。此时 confidence 上限为 medium，并标注"内存需求按当前规格保守保留"。

**第二步：候选集与硬约束筛选。**

```
候选集 = 目标 region 可用机型 ∩ 机型详细规格
筛选   = 族不在 legacy 清单中          ← 第一道，见 references/legacy-families.md
     AND 用途分类 ∈ {General purpose, Compute optimized, Memory optimized}
         或 与当前机型分类相同          ← 专用机型可在同类内降配
     AND 族不含 "-flex"                ← flex 族可持续 CPU 低于标称却不报 burstable
     AND vcpu    >= required_vcpu
     AND memory  >= required_gib
     AND CPU 架构与当前完全相同        ← 硬约束，本版本不做 arm64 迁移
     AND NetworkCards[DefaultNetworkCardIndex].BaselineBandwidthInGbps
             >= 当前实测 NetworkIn+NetworkOut 的 max 换算值
     AND EBS 基线带宽 >= 当前实测 ReadThroughput + WriteThroughput 的 p95
     AND 实例存储(NVMe)属性与当前一致  ← 防止把无本地盘的换成带本地盘的贵机型
     AND 同族字母内代次不低于当前       ← 代次数字仅在同族字母内可比
     AND 有价格数据 且 单价 < 当前单价
排序   = 单价升序取第一（最便宜够用）
```

**过滤顺序不可调换**：先剔 legacy 族，再允许跨用途分类。否则跨分类会把
`a1`（同规格组最便宜）、`i3`（低于 i4i 10%）这类老机型拉进来。

**不使用任何 `currentGeneration` 字段**：实测 `describe-instance-types` 把
m6i/r6i 判为 false 却把 t2/i3/x1 判为 true；pricing API 把 m4/c4 判为 Yes。
两者对 1145 个共同型号有 80 处不一致。改用显式 legacy 清单 + 用途分类。

规格数据源：`ec2 describe-instance-types` 的 `VCpuInfo.DefaultVCpus`、`MemoryInfo.SizeInMiB`、`NetworkInfo.NetworkCards[DefaultNetworkCardIndex].BaselineBandwidthInGbps`（数值，可比较；`NetworkPerformance` 是字符串等级描述如 `"Up to 10 Gigabit"`，不可用于比较）、`EbsInfo.EbsOptimizedInfo.BaselineThroughputInMBps`、`InstanceStorageSupported`、`ProcessorInfo.SupportedArchitectures`、`BurstablePerformanceSupported`。可用性数据源见 §3。

**第三步：产出两个候选，不产出单一候选。**

`pick_nonburstable` = 候选集中 `BurstablePerformanceSupported=false` 的最小可行机型
`pick_burstable`    = 候选集中 `BurstablePerformanceSupported=true`  的最小可行机型

两者都按 §5.3 排序键在各自子集内取回收最多者。报告并列呈现，由人工选择：生产账号通常取 non-burstable，非生产可取 burstable。skill **不代替人工做这个选择**，两个选项一律都给。

若某一侧候选集为空，该侧标注具体原因；两侧都为空则该资源标注"已合理配置"，不产出建议。

**burstable 候选的额外硬约束**（non-burstable 候选不适用）：

持续负载必须落在候选机型的基线 CPU 之内：

```
cur_vcpu × sus_cpu%  <=  cand_vcpu × baseline_pct(cand) × (1 − burstable_baseline_headroom)
```

基线 CPU% 查表见 `references/instance-specs.md`。`describe-instance-types` 只给
`BurstablePerformanceSupported` 布尔值，**不提供基线百分比**（已实测确认）。

峰值由突发信用吸收，但必须满足：

- 当前机型已是 T 系列且窗口内 `CPUSurplusCreditsCharged > 0` ⇒ 已在超额消费信用，当前规格本就不足，**抑制 burstable 选项**
- `CPUCreditBalance` 长期贴近上限且持续 CPU 远低于基线 ⇒ 强 burstable 候选

**burstable 选项 N/A 时必须给出具体原因，不得留空**：

- `required_vcpu > 8` 或 `required_gib > 32`（T 系列规格上限，两个架构都是 8 vCPU / 32 GiB，已实测确认）

**burstable 候选族随当前架构而变**，这是同架构硬约束的自然结果：

| 当前架构 | burstable 候选族 | 上限 |
|---|---|---|
| `x86_64` | t2 / t3 / t3a | t3.2xlarge / t3a.2xlarge / t2.2xlarge = 8C / 32G |
| `arm64` | **t4g** | t4g.2xlarge = 8C / 32G |

`c7g → t4g` 与 `m5 → t3` 是同一类动作：都不跨 CPU 架构，不需要重编译或换镜像。因此 arm64 机型同样产出 burstable 候选，不因架构被排除。基线表必须覆盖两个架构共 24 个型号（x86 17 + t4g 7）。
- 持续负载超过最大 T 机型的基线 CPU
- EBS 基线带宽不足：**T 系列 EBS 基线在 t3.large 之后不再随规格增长，恒为 86.875 MBps**（实测：t3.2xlarge 8C 为 86.875，而 m5.xlarge 4C 为 143.75）。有真实 I/O 的负载会频繁因此被淘汰。
- 网络基线不足（实测 t3.small 0.128 Gbps vs m5.large 0.75 Gbps）
- `baseline_pct` 查表缺失 ⇒ 标 `baseline-unknown`，禁止用记忆值代替

**T 系列间的移动在范围内**：T→M 与 M→T 都允许。它改变计费与突发模型，但不改变架构形态、CPU 架构或可用性等级，因此不属 §1 的排除项。

**t3a 的处理**：t3a 是 AMD，`SupportedArchitectures` 同为 `x86_64`，通过同架构过滤。不因此排除，但若被选为候选，须在 `blockers` 标注"AMD 处理器，绑定 Intel 指令集的负载需验证"。t2 属旧代次，被"代次不低于当前"规则自动淘汰。

**加速计算机型（g / p / inf / trn 系列）排除出桶 A。** 受限资源是 GPU 或加速器，默认 CloudWatch 无 GPU 利用率指标，按 CPU/内存降配无意义且危险。这些机型在报告中单列，标注"需 GPU/加速器利用率数据，本版本不评估"，两个选项均不产出。

**RDS / ElastiCache / MSK 的规格数据源问题**：这三个服务的 API 不直接返回实例类的 vCPU 与内存。方案为把 `db.<family>.<size>` / `cache.<family>.<size>` / `kafka.<family>.<size>` 映射到对应 EC2 机型后查 `describe-instance-types`，对无 EC2 对应物的类型（如 `db.r5b`、部分 `x2g` 变体）用查表兜底。映射表与兜底表列入 §11 待核实项。

**ElastiCache 额外约束**：Redis 节点内存并非全部可用，`reserved-memory-percent` 默认预留 25% 给后台操作。因此 `required_gib` 需除以 `(1 − reserved_pct)` 后再筛选候选，否则会推荐出实际内存不足的节点类型。

### 5.3 排序键：月节省金额（按需价目理论值）

排序键为**月节省金额**，按公开按需价目计算：

```
save_mo = (当前单价 − 候选单价) × 730 × 实例数
主排序键：non-burstable 侧的 save_mo   降序
```

用 non-burstable 侧排序，因为它是始终适用的保守选项（burstable 侧可能为空）。

原设计用二维回收量 `(Δ vCPU, Δ GiB)` 作代理指标，因为当时禁用价格。引入按需价目后
该代理不再需要——它的问题是把两维压成标量必然隐含一个 CPU 与内存的兑换率，而那个
兑换率在无价格时没有客观依据。现在直接用金额。

`findings.csv` 为每个资源输出**一行、两个候选列组**（non-burstable 与 burstable），devops 可按自身关注点重排。不得每资源输出两行——那样任何人对 `save_mo` 求和都会把可节省总额翻倍高估。

容量回收量仍作为**证据列**输出（不用于排序）。burstable 侧必须按基线容量计算：

```
eff(type) = vcpu × baseline_pct(type)      non-burstable 时 baseline_pct = 1
delta_vcpu = eff(当前) − eff(候选)
```

否则 `m5.xlarge (4C/16G) → t3.xlarge (4C/16G)` 会报 `delta_vcpu = 0`，看起来毫无意义，
而实际上 t3.xlarge 只交付其基线作为持续容量。当前机型本身是 burstable 时也须用
`eff(当前)`，否则 `t3.medium → t3.medium` 会算出虚假回收量。

`baseline_pct` 查表见 `references/instance-specs.md`（28 个型号，来自官方 credit 表，
并用 `cap = vcpu × pct × 1440` 与本账号实测 `CPUCreditBalance` 三重校验）。

第二阶段引入实际账单后，排序键从按需理论节省替换为摊销后实际节省。

### 5.4 分桶：桶内排序，桶间不混排

| 桶 | 内容 | 桶内排序键 |
|---|---|---|
| A `downsize` | 机型/节点型号降配（可跨 family，同架构内） | `Δ vCPU × 实例数` |
| B `idle` | 疑似闲置：零流量 NAT、未关联 EIP、零请求 ALB/NLB、未挂载卷、空 nodegroup、闲置实例 | 当前 vCPU（无 vCPU 概念的资源排在同桶末尾） |
| C `schedule` | 定时停机（仅 `allow_stop_recommendations=yes` 时生成） | 当前 vCPU × 可停小时数/周 |
| D `config` | gp2→gp3、HPA minReplicas 下调、MSK 存储自动扩展未开等纯配置项 | 影响资源数 |
| E `request-tuning` | EKS pod / Fargate request 超配 | `Δ vCPU`，次 `Δ GiB` |
| F `next-rebuild-only` | RDS / MSK 存储过度预配（存储不可缩容） | 不排序，单列 |

## 6. 各服务判据

阈值以 `references/thresholds.md` 为唯一真值来源，写死，运行时不可放宽。按 `sizing_profile` 取列，取值见 §5.2 表。

### 6.1 EC2

指标 `AWS/EC2`（维度 `InstanceId`）：`CPUUtilization`、`NetworkIn`、`NetworkOut`。
若 `CWAgent` 命名空间存在，加 `mem_used_percent`。

| 结论 | 条件（biz-hours 档） |
|---|---|
| 桶 B 疑似闲置 → 建议关停 | p95 CPU < 5% 且日均 (NetworkIn+NetworkOut) < 5MB |
| 桶 A 降配 | 走 §5.2 算法，候选集非空且目标机型 ≠ 当前机型 |
| 阻断 | max CPU > `ceiling_cpu_max`（此时 §5.2 算法自然得出候选集为空） |
| 降级 | 无 CWAgent 内存数据 → `required_gib = cur_gib`，confidence 上限 medium |

### 6.2 EBS

- `gp2 → gp3` 全量清单。措辞为配置优势陈述（更新一代、IOPS 与吞吐可独立配置），**不含省钱结论**。约束：原 gp2 容量 > 334 GB 时基线 IOPS 已超 3000，转 gp3 必须显式配置 IOPS 否则性能下降。此约束必须写入 `blockers` 字段。
- `state=available` 未挂载卷。
- 超龄快照（`describe-snapshots` 按 `StartTime`）。

**已知缺口**：卷容量是否过大判不了。文件系统使用率需 CWAgent `disk_used_percent`；纯 CloudWatch 只有 `VolumeReadOps`/`VolumeWriteOps`，仅能判断卷是否闲置。此缺口必须在 preflight 中明确列出。

### 6.3 RDS

指标 `AWS/RDS`（维度 `DBInstanceIdentifier`）：`CPUUtilization`、`DatabaseConnections`、`FreeableMemory`、`FreeStorageSpace`、`ReadIOPS`、`WriteIOPS`、`ReadThroughput`、`WriteThroughput`。Aurora 另加 `VolumeBytesUsed`。

RDS 的内存维度不用 CWAgent，用 `FreeableMemory` 反推：`已用内存 ≈ 实例内存 − FreeableMemory`，据此算 `p95_mem` 与 `max_mem` 供 §5.2 使用。

**RDS 降配的第一判据不是 `CPUUtilization`，是 Performance Insights 的 `db.load.avg`**（`pi:GetResourceMetrics`）。`DBLoad p95 > vCPU 数` 表示 CPU 已是瓶颈，此时无论 CPUUtilization 数值多少，一律禁止降配。

| 结论 | 条件 |
|---|---|
| 桶 A 降配 | `DBLoad p95 < 0.5 × vCPU` 且 §5.2 候选集非空 |
| 阻断 | `DBLoad p95 >= vCPU 数` |
| 阻断 | `FreeableMemory` 最小值 < 实例内存 15%（降配会 OOM） |
| 阻断 | `ReadIOPS + WriteIOPS` 接近实例 EBS 基线 |
| 桶 F `next-rebuild-only` | `FreeStorageSpace` 最小值仍占 > 50% → 存储过度预配，但 RDS 存储不可缩容 |

非生产环境**不建议用"停止实例"作为节约手段**：停止的 RDS 实例仍收存储费，且最多停 7 天后自动启动。桶 C 生成 RDS 建议时必须改为"快照 + 删除"路径，并在 `blockers` 中写明 7 天限制。

### 6.4 ElastiCache Redis

**必须用 `EngineCPUUtilization`，不得用 `CPUUtilization`。** Redis 单线程，整机 CPU 包含后台线程，用它判断 Redis 瓶颈会产生系统性误判。

指标 `AWS/ElastiCache`：`EngineCPUUtilization`、`DatabaseMemoryUsagePercentage`、`BytesUsedForCache`、`Evictions`、`CurrConnections`、`CacheHits`、`CacheMisses`、`ReplicationLag`、`CurrItems`。

内存维度直接用 `DatabaseMemoryUsagePercentage` 的 p95/max 供 §5.2 使用，并按 §5.2 的 `reserved-memory-percent` 约束修正。

| 结论 | 条件 |
|---|---|
| 桶 A 降 node type | `Evictions` 窗口内累计 = 0 且 `ReplicationLag` max < 1s 且 §5.2 候选集非空 |
| 阻断 | `Evictions > 0`（内存已不足，降配更糟） |
| 阻断 | `ReplicationLag` max >= 1s |

集群模式额外检查各 shard 的 `CurrItems` / `BytesUsedForCache` 是否严重不均，不均则在报告中陈述"分片倾斜"这一事实供客户参考。**本版本不产出减 shard 建议。**

### 6.5 MSK

前提：enhanced monitoring 至少 `PER_BROKER`。默认 `DEFAULT` 级别指标不足。preflight 探测 `describe-cluster-v2` 返回中的 `EnhancedMonitoring` 字段。

指标 `AWS/Kafka`：`CpuUser`、`CpuSystem`、`CpuIdle`、`KafkaDataLogsDiskUsed`、`MemoryUsed`、`BytesInPerSec`、`BytesOutPerSec`、`MessagesInPerSec`、`PartitionCount`、`UnderReplicatedPartitions`、`RequestHandlerAvgIdlePercent`。

CPU 维度用 `(CpuUser + CpuSystem)` 供 §5.2 使用。注意 AWS 建议 MSK broker CPU 常态保持在 60% 以下，故 MSK 的 `target_cpu_p95` 取 40%，比通用值更保守，单独在 `thresholds.md` 中列出。

| 结论 | 条件 |
|---|---|
| 桶 A 降 broker 型号 | `KafkaDataLogsDiskUsed` max < 50% 且 `RequestHandlerAvgIdlePercent` > 70% 且 `UnderReplicatedPartitions = 0` 且 §5.2 候选集非空 |
| 阻断 | `UnderReplicatedPartitions > 0` |
| 桶 F `next-rebuild-only` | MSK 存储只能扩不能缩 |
| 桶 D `config` | `describe-cluster-v2` 的 `StorageInfo` 未启用存储自动扩展 |

**本版本不产出减 broker 数建议**（需 partition 重分配，属架构级操作）。

### 6.6 EKS

清单来源：`eks list-clusters` / `describe-cluster` / `list-nodegroups` / `describe-nodegroup` / `list-fargate-profiles`。Karpenter 管理的裸 EC2 节点通过 `ec2 describe-instances --filters tag:karpenter.sh/nodepool` 归因到集群。

k8s API（只读 ClusterRole）：node allocatable/capacity、pod requests/limits、workload replicas、HPA min/max/current、PDB。

指标 `ContainerInsights`：`node_cpu_utilization`、`node_memory_utilization`、`node_filesystem_utilization`、`pod_cpu_utilization`、`pod_memory_utilization`、`pod_number_of_container_restarts`。若启用 Container Insights enhanced observability，另有更细的 request 侧指标——具体名称在实现时以官方文档核实，不凭记忆写死。

**EKS 的浪费主体不在节点利用率，在 request 超配把节点池撑大。** 五项分析：

1. **Request vs Actual**：`Σ pod requests ÷ node allocatable` = 预订率；实际利用率来自 Container Insights。两者差值即被 request 锁死但未使用的容量，这是节点数偏多的根因。
2. **Bin-packing 效率**：由 `Σ requests` 反推理论最少节点数，与当前节点数比对。
3. 空 nodegroup、未被任何 pod 调度的节点、`desired=0` 但仍存在节点（桶 B）。
4. HPA `minReplicas` 过高——off-hours 档实际负载近零但 min 撑着（桶 D）。
5. **Fargate profile**：按 pod requests 计费，request 即用量，超配是直接浪费，优先级最高（桶 E）。

节点机型是否错配（如 CPU 预订率 90% 而内存预订率 20%）由 §5.2 算法统一处理，不作为独立规则——算法以 nodegroup 的聚合 request 为需求输入，自然会得出换 family 的结论。

**托管 nodegroup 与 Karpenter 的建议形态不同**：托管 nodegroup 给出具体目标机型；Karpenter 节点池的机型由 NodePool requirements 决定，因此建议对象是 NodePool 的 `requirements` / `limits` 约束，而非单个实例。这一区别必须在报告中标明。

输出粒度：deployment / statefulset 级的 request 调整建议（桶 E），nodegroup / NodePool 级的机型与数量建议（桶 A）。

### 6.7 VPC（第一阶段仅闲置资源）

清单：`describe-nat-gateways`、`describe-vpc-endpoints`、`describe-addresses`、`elbv2 describe-load-balancers`、`describe-target-groups`。

指标 `AWS/NATGateway`：`ActiveConnectionCount`、`BytesOutToDestination`、`BytesInFromDestination`、`PacketsDropCount`。
指标 `AWS/ApplicationELB`：`RequestCount`、`ActiveConnectionCount`。

| 结论 | 条件 |
|---|---|
| 桶 B `idle` | `ActiveConnectionCount` 全窗口恒 0 的 NAT Gateway |
| 桶 B `idle` | 未关联任何实例/ENI 的 EIP |
| 桶 B `idle` | `RequestCount` 全窗口恒 0 的 ALB/NLB |

跨 AZ 流量分析需 VPC Flow Logs，不在默认范围。

## 7. 报告结构

```
report_output/<account>-<region>-<YYYYMMDD>/
  aws-rightsizing-report.md    单文件报告，内部按服务分节
  findings.csv                 全量明细，一行一条建议
  raw/
    inventory/*.json           各服务 describe 原始输出
    metrics/*.json             get-metric-data 原始输出
    metrics/summary-*.csv      聚合后的 avg/p95/max × 三档时段
    specs/*.json               机型规格、按需价目、region 可用集合快照
```

作用域目录（账号-region-日期）不可省：多账号场景靠换凭证重跑，
若共用一个 `report/` 则第二次运行会静默覆盖第一次的报告与审计证据。

### 报告必须包含的声明（置于报告开头）

> 本报告基于资源利用率给出配置优化建议，金额一律为**公开按需（On-Demand）价目**计算的理论值，**不含实际账单数据**。
>
> 因此：被 Reserved Instance 或 Savings Plan 覆盖的资源，降配后账单可能不立即下降——折扣会转移到其他资源或在承诺期内搁置。报告中的节省金额是"若该资源按按需价计费"的上限估算，实际财务收益需结合账单数据另行评估。
>
> 本报告的建议均为**同形态降配**：不改变架构形态、不改变 CPU 架构、不降低可用性等级。Serverless 迁移、Graviton 迁移、Spot、副本或 AZ 数量削减均不在本次范围内。
>
> 报告作用域：账号 `<target_account>`，region `<regions>`，窗口 `<window_days>` 天，定档预设 `<sizing_profile>`，停机建议 `<allow_stop_recommendations>`。

第一段不写，客户会把"可降配"误读为"可省钱"；第二段不写，客户会问为什么没提 Graviton 和 Serverless。

### findings.csv 字段

```
account | region | service | resource_id | resource_name | bucket | current_spec
cur_vcpu | cur_gib | required_vcpu | required_gib
cur_usd_hr | cur_cost_mo
rec_nonburstable | nb_usd_hr | nb_save_mo | nb_delta_vcpu | nb_delta_gib
rec_burstable    | b_usd_hr  | b_save_mo  | b_delta_vcpu  | b_delta_gib | burstable_na_reason
cur_category | rec_category | instance_count
evidence_cpu_p95 | evidence_cpu_max | evidence_mem_p95 | evidence_mem_max
sample_days | window_profile
blockers | confidence | action_type
```

共 37 列，**一资源一行**（见 §5.3 关于不得拆两行的说明）。

金额列一律为公开按需价目理论值。`cur_category` / `rec_category` 用于让人工复核
跨用途分类的推荐（实测跨分类贡献 89% 的节省，是刻意允许的，但必须可见）。

`rec_burstable` 为空时 `burstable_na_reason` 必须给出具体原因，取值见 §5.2。
skill 不根据任何输入预先替人工选定其中一列，两列一律都出；报告开头写明生产一般取 non-burstable 列。

`bucket` ∈ `{downsize, idle, schedule, config, request-tuning, next-rebuild-only}`
`action_type` ∈ `{downsize, stop, schedule, delete, storage-type, next-rebuild-only, request-tuning}`
`confidence` ∈ `{high, medium, low}`
`window_profile` ∈ `{biz-hours, off-hours, weekend}`

无 vCPU/内存概念的资源（EBS 卷、EIP、NAT、ALB、快照）容量相关列留空。

### 报告的可执行性要求

输出边界是纯只读报告，不给变更命令。因此每条建议必须精确到 devops 能直接判断、无需回头询问：资源 ID、当前规格、建议规格、反推出的需求量、依据数值（p95/max + 采样天数 + 时段档）、阻断条件、confidence。

## 8. Preflight 检查

skill 第一阶段执行 preflight。任一缺失都在报告中明确写出：缺什么、影响哪一节结论、客户需要开什么、需要等多久。**不静默降级产出半残报告。**

| 检查项 | 探测方式 | 缺失后果 | 客户动作与 lead time |
|---|---|---|---|
| 凭证指向正确账号 | `sts get-caller-identity` 比对 `target_account` | 立即停止 | — |
| CloudWatch 各 namespace 有数据 | `cloudwatch list-metrics` | 对应服务无法分析 | — |
| CWAgent 内存指标 | `list-metrics --namespace CWAgent` | EC2 内存需求按当前规格保留，confidence 降级 | 装 CWAgent，需时间铺开 |
| CWAgent `disk_used_percent` | 同上 | EBS 容量过大判不了 | 同上 |
| RDS Performance Insights | `describe-db-instances` 的 `PerformanceInsightsEnabled` | RDS 降配失去第一判据 | 开启，7 天免费保留即可 |
| MSK enhanced monitoring ≥ PER_BROKER | `describe-cluster-v2` 的 `EnhancedMonitoring` | MSK 只能出粗结论 | 改集群监控级别 |
| EKS Container Insights | `list-metrics --namespace ContainerInsights` | pod 级分析全部不可得 | 部署 CloudWatch agent addon |
| EKS access entry 只读 | `kubectl auth can-i` | 拿不到 requests/limits，第 1/2/5 项分析失效 | 建 access entry |
| Compute Optimizer opt-in（可选） | `compute-optimizer get-enrollment-status` | 少一份免费交叉校验 | 开启后等约 12h |

## 9. 安全护栏（内置，不可运行时放宽）

- skill 仅允许 `describe*` / `list*` / `get*`，禁止任何 mutating API。
- **禁止调用 `ce:*` 及任何账单 API。** `pricing:GetProducts` 允许使用。
- **禁止产出改变架构形态、CPU 架构或可用性等级的建议**（见 §1 非目标清单）。
- 凭证账号与 `target_account` 不一致时立即停止。
- 阈值按 `sizing_profile` 取列，含 `max_reduction_ratio`（aggressive 3x / conservative 2x）。
- 每条降配建议**无条件**标注"需变更窗口 + 回滚预案"。
- `allow_stop_recommendations=no` 时不生成桶 C 停机建议。
- 降配幅度由 §5.2 的目标利用率与峰值上限约束，不设独立的"最多降几档"规则——档位概念在跨 family 场景下无意义。
- 阈值不允许运行时放宽，防止为凑数字放宽判据导致生产事故。
- 无内存数据时不得给出 high confidence 的降配建议。
- §5.2 候选集为空时必须输出"已合理配置"，不得退而给出越界建议。

## 10. skill 文件结构

```
aws-rightsizing/
  SKILL.md                主流程 + 运行时输入 + preflight + 报告规范 + 护栏
  references/
    thresholds.md         §5.2 阈值表 + 各服务专有阈值（唯一真值来源）
    sizing-algorithm.md   §5.2 推算算法的完整规则与边界情况
    metrics-catalog.md    服务 → namespace / 指标 / 维度 / 统计量 对照表
    instance-specs.md     RDS/ElastiCache/MSK 实例类 → EC2 机型映射表与兜底表
    cli-recipes.md        各服务 describe 命令 + jq 生成 GetMetricData 查询体模板
    partition-matrix.md   aws vs aws-cn 差异：endpoint、可用机型、node type 集合
    report-template.md    报告骨架 + findings.csv 字段定义
```

skill 目录名为 `aws-rightsizing`，不叫 `aws-cost-optimization`——本版本不产出任何金额，用成本命名会让 devops 误以为报告里有省钱数字。repo 名 `aws-cost-optimization-skill` 保留，覆盖后续成本阶段。

repo 位置：本文件所在仓库根目录。

## 11. 实现时需以官方文档核实的项

### 已核实（2026-09-03，通过 API 实测）

- `NetworkCards[].BaselineBandwidthInGbps` / `PeakBandwidthInGbps` 为数值字段（m5.xlarge = 1.25 / 10.0），用它替代字符串 `NetworkPerformance`。
- ElastiCache `reserved-memory-percent` 默认值 = **25**（`describe-engine-default-parameters` 验证，redis7 与 valkey8 一致）。
- `rds describe-orderable-db-instance-options` **不返回** vCPU/内存字段，确认必须走 EC2 机型映射。
- ElastiCache **无** node type 规格 API；可用集合可由 `describe-reserved-cache-nodes-offerings` 取得（us-east-1 实测 91 个）。
- MSK **无** broker 型号列表 API，型号集合只能来自文档维护的查表。
- AWS CLI v2 时间戳渲染受 `cli_timestamp_format` 影响，实测输出 `2026-08-04T16:10:00+08:00`（带本地偏移）而非 `...Z`。skill 必须防御性归一化，不能假定 `Z` 结尾。
- `describe-instance-types` 只给 `BurstablePerformanceSupported` 布尔值，**不给基线 CPU 百分比**。
- x86 T 系列规格上限 = 8 vCPU / 32 GiB（t3.2xlarge / t3a.2xlarge / t2.2xlarge）。`t4g` 为 arm64，被同架构过滤挡掉。
- T 系列 EBS 基线吞吐在 t3.large 之后不再随规格增长，恒为 86.875 MBps；t3.2xlarge(8C) 因此低于 m5.xlarge(4C) 的 143.75 MBps。
- **T 系列基线 CPU 表已取回并内置**（28 个型号，来源为官方 credit 表），三重校验通过：`cap = vcpu × pct × 1440` 与 `earn = vcpu × pct × 60` 各 28 行一致；本账号实测 `t3.medium` cap=576 反推 20% 与文档吻合。基线非均匀——t2.2xlarge 是 17% 而 t3.2xlarge 是 40%，禁止跨族外推。
- **`pricing:GetProducts` 在验证账号可用**：单 region + Linux/Shared/NA/Used 过滤返回 1176 条、9 秒、9 MB。bulk 价目表为 288 MB CSV / 442 MB JSON，不可用于 skill 运行时。
- **两个 `currentGeneration` 字段均不可用**：`describe-instance-types` 把 m6i/r6i 判 false、t2/i3/x1 判 true；pricing API 把 m4/c4 判 Yes。两者对 1145 个共同型号有 80 处不一致。前者跨 region 一致（0/1145），故不可靠是语义性的。
- **`instanceFamily`（用途分类）来自 pricing API**，是候选过滤的有效维度：`i3en` 属 Storage optimized，这才是它曾被误选为 `m5.xlarge` 降配目标的根因。
- **突增型角色无更新代次**：x86 止于 t3/t3a（无 t4/t5），arm64 仅 t4g（无 t5g）。故 t2 可排除，t3/t3a/t4g 必须保留。`t4g` 的 `4` 是 Graviton 线编号，非 Intel 第 4 代。

### 仍待核实

- Container Insights enhanced observability 的 request 侧指标准确名称（验证账号该 namespace 为空）
- MSK 可用 broker 型号集合（无 API，需文档维护的查表）
- RDS 停止实例的 7 天自动启动行为在各引擎下是否一致
- 中国区各服务可用机型与 node type 集合（运行时查询，不预置静态表）
- legacy 族清单的完整性（人工策展，非权威接口推导，详见 `references/legacy-families.md` 已知局限）
