# Sample：core.py 的输入与输出（照形状抄，不要凭描述重建）

本文件的输入输出**全部由真实执行产出**，不是手写。改动 `core.py` 后重跑本样例，
四个 verdict 必须全部出现——**少任何一个都说明有分支不可达**。

`insufficient-data` 现在只由 `cpu_n` 为 `0`／`null` 触发（`i-EX-05`）。
样本**少但存在**走降档（`i-EX-04`，`confidence=low`），不再是拒绝。
所以 `i-EX-05` 不能删——删了这个 verdict 就没有任何资源产出，自检失效。

## 为什么用 sample 而不是散文

本 skill 反复验证出一条规律：**有代码/样例载体的判据一次就对；只有散文描述的
判据全部出过问题**（桶 C 判据被自造、采样量守卫未强制、闲置判据把 0 当缺失、
Sum 系数三处冲突）。样例落在必读路径上，agent 直接照形状抄，不需要把散文翻译成结构。

样例还自带**自检性**：跑出来的 verdict 集合与本文件不一致，就是有分支死了。
实测踩过——`($specs[] | select(...)) as $cs` 在生成器为空时整条记录消失，
`spec-unknown` 分支永远进不去，未知机型的资源**静默从报告消失**。

## 输入：solver-in.json（一条一资源）

```json
[{"rid":"i-EX-01","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":10,"peak_cpu":25,"sus_mem":20,"peak_mem":35,
  "ebs_need":5,"surplus_credits":0,"cpu_n":243,"metric_coverage":[]},

 {"rid":"i-EX-02","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":10,"peak_cpu":25,"sus_mem":20,"peak_mem":35,
  "ebs_need":null,"surplus_credits":0,"cpu_n":243,"metric_coverage":["ebs"]},

 {"rid":"i-EX-03","service":"ec2","type":"NOSUCH.type","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":1,"peak_cpu":2,"sus_mem":null,"peak_mem":null,
  "ebs_need":0,"surplus_credits":0,"cpu_n":243,"metric_coverage":[]},

 {"rid":"i-EX-04","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":2,"peak_cpu":5,"sus_mem":10,"peak_mem":15,
  "ebs_need":1,"surplus_credits":0,"cpu_n":154,"metric_coverage":[]},

 {"rid":"i-EX-05","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":2,"peak_cpu":5,"sus_mem":10,"peak_mem":15,
  "ebs_need":1,"surplus_credits":0,"cpu_n":0,"metric_coverage":[]}]
```

**`cpu_n` 是 `biz-hours` 档的点数，不是全窗口点数。** 上面的 `243` 是一个
30 天满窗口实例的实测 biz-hours 点数（22 个工作日 × 11 小时那一档）；
全窗口点数是 `WINDOW_DAYS × 24 = 720`，那是三档之和。
**把 720 填进 `cpu_n` 会让采样量守卫恒不触发**——本 skill 的回归基线曾经
就是这么错的，13 台里两台 biz-hours 只有 154 与 55 个点的新建实例照样产出了
降配建议，而总额没人怀疑。`i-EX-04` 的 `154` 就取自那两台之一。

**字段语义（缺失一律 null，禁止兜底为 0）**

| 字段 | 含义 | 缺失时 |
|---|---|---|
| `service` | `ec2` / `rds` / `elasticache` / `msk`，决定走哪条判据 | **抛错**，不回退 `ec2` |
| `sus_cpu` / `peak_cpu` | biz-hours 的 Average-p95 / Maximum-max | `null` ⇒ `metric-missing` |
| `sus_mem` / `peak_mem` | 同上，内存 | `null` ⇒ 内存保持当前规格，confidence 上限 `medium`（样本不足时为 `low`，样本量的问题盖过内存口径） |
| `ebs_need` | Σ Sum ÷ 窗口秒数 ÷ 1MiB，MB/s | `null` ⇒ `metric-missing`（**不可当 0**，否则跳过带宽校验） |
| `surplus_credits` | `CPUSurplusCreditsCharged` 的 max | `null` ⇒ 抑制 burstable 侧（不能断言"没超额"） |
| `cpu_n` | **`biz-hours` 档**的有效点数（不是全窗口点数，别填 `WINDOW_DAYS × 24`） | `0` 或 `null` ⇒ `insufficient-data`（「无」）。`0 < cpu_n < min_biz_hours_points` ⇒ 照常判据但 `confidence=low`（「少」），**不拒绝出建议** |
| `metric_coverage` | 缺失指标名数组 | 随建议输出，报告须列出 |

## 调用

```bash
# 构造 core.py 的输入对象：包含 sizing_profile、specs、prices 等上下文，
# 以及待评估的 resources 数组
cat > solver-ctx.json <<'EOF'
{
  "sizing_profile": "aggressive",
  "specs": [
    {"t": "m5.large", "vcpu": 2, "gib": 8, "arch": "x86_64", "burst": false, "store": null, "ebs": 10},
    {"t": "m5.xlarge", "vcpu": 4, "gib": 16, "arch": "x86_64", "burst": false, "store": null, "ebs": 10}
  ],
  "prices": {
    "m5.large|RunInstances": 0.124,
    "m5.xlarge|RunInstances": 0.248
  },
  "baseline_pct": {},
  "categories": {
    "m5.large": "General purpose",
    "m5.xlarge": "General purpose"
  },
  "offerings": ["m5.large", "m5.xlarge"],
  "legacy_families": [],
  "resources": [
    {"rid":"i-EX-01","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
     "sus_cpu":10,"peak_cpu":25,"sus_mem":20,"peak_mem":35,
     "ebs_need":5,"surplus_credits":0,"cpu_n":243,"metric_coverage":[]},
    {"rid":"i-EX-02","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
     "sus_cpu":10,"peak_cpu":25,"sus_mem":20,"peak_mem":35,
     "ebs_need":null,"surplus_credits":0,"cpu_n":243,"metric_coverage":["ebs"]},
    {"rid":"i-EX-03","service":"ec2","type":"NOSUCH.type","arch":"x86_64","operation":"RunInstances",
     "sus_cpu":1,"peak_cpu":2,"sus_mem":null,"peak_mem":null,
     "ebs_need":0,"surplus_credits":0,"cpu_n":243,"metric_coverage":[]},
    {"rid":"i-EX-04","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
     "sus_cpu":2,"peak_cpu":5,"sus_mem":10,"peak_mem":15,
     "ebs_need":1,"surplus_credits":0,"cpu_n":154,"metric_coverage":[]},
    {"rid":"i-EX-05","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
     "sus_cpu":2,"peak_cpu":5,"sus_mem":10,"peak_mem":15,
     "ebs_need":1,"surplus_credits":0,"cpu_n":0,"metric_coverage":[]}
  ]
}
EOF

python3 references/core.py < solver-ctx.json > findings-sample.json
```

## 输出：四个 verdict 必须全部出现

用上面的输入 + `sizing_profile=aggressive`（阈值从 `thresholds.json` 加载），价目 `{m5.large:0.124, m5.xlarge:0.248}`：

```
i-EX-01  verdict=downsize           nb=m5.large  save=90.52  missing=[]     confidence=high
i-EX-02  verdict=metric-missing     nb=-         save=-      missing=[ebs]
i-EX-03  verdict=spec-unknown       nb=-         save=-      missing=[]
i-EX-04  verdict=downsize           nb=m5.large  save=90.52  missing=[]     confidence=low
i-EX-05  verdict=insufficient-data  nb=-         save=-      missing=[]
```

### 逐条为什么

| 资源 | 结论 | 依据 |
|---|---|---|
| `i-EX-01` | `downsize` | `required_vcpu = max(ceil(4×sus_cpu/target_cpu_p95)=1, ceil(4×peak_cpu/ceiling_cpu_max)=2) = 2`；`required_gib = max(ceil(16×sus_mem/target_mem_p95)=5, ceil(16×peak_mem/ceiling_mem_max)=7) = 7`（阈值取 `aggressive` 列，数值只在 `thresholds.json`）；`m5.large`(2C/8G) 满足且 $0.124 < $0.248 ⇒ 月省 $90.52 |
| `i-EX-02` | `metric-missing` | `ebs_need` 为 null ⇒ 无法校验任何候选的带宽 ⇒ **fail-closed**。**注意它不是「已合理配置」**——verdict 链里 `metric-missing` 必须排在前面，否则"没能力判断"会被伪装成"无需优化" |
| `i-EX-03` | `spec-unknown` | 机型不在 `$specs` 里。此分支曾因 jq 生成器语义而**完全不可达**，输入 1 条输出 0 行 |
| `i-EX-04` | `downsize` + `confidence=low` | `cpu_n=154`（实测值，来自一台窗口内新建的实例）低于 `min_biz_hours_points` ⇒ p95 统计意义弱，但**样本少不等于不能判断**：照常出建议、把 `confidence` 降到 `low`、`blockers` 写明样本量与占门限比例。改动前这里是 `insufficient-data`，而那个分支**连否决项一起压掉**——实测两条真实健康事实（MSK URP 27、Redis 复制延迟 23.88s）因此被一句「点数不足」盖住 |
| `i-EX-05` | `insufficient-data` | `cpu_n=0`。**零个点算不出 p95，是「无」不是「少」** ⇒ fail-closed。`cpu_n` 缺失（`null`）同理。这是本样例里 `insufficient-data` 分支的**唯一**来源，删掉这条资源该分支即不可达 |

## 托管服务：RDS / ElastiCache / MSK 的输入样例

`service` 决定走哪条判据（`ec2` → `evaluate`，其余三个 → `eval_rds` /
`eval_elasticache` / `eval_msk`）。**缺失或写错一律抛错**，不回退 EC2 路径：
托管服务的指标名与 EC2 不同，喂进 EC2 判据会让指标齐全的资源被判成
`metric-missing`——「判得了」伪装成「判不了」，整个托管服务报告静默消失。

托管服务资源**不进桶 B（idle）**：闲置判据读的 `sus_cpu` / `net_mb_day`
只在 EC2 侧定义。`bucket` 只有两种取值：`downsize-candidate` ⇒ `downsize`，
其余（含 `upsize-candidate`、`blocked`、`已合理配置`）⇒ `excluded`。

### 输入

```json
[{"rid":"db-EX-01","service":"rds","type":"db.r6g.large","vcpu":2,"mem_gib":16,
  "surplus_credits":0,"dbload_p95":0.4,"freeable_mem_min_gib":9.6,"sample_n":243,
  "cheaper_candidate_exists":true},

 {"rid":"db-EX-02","service":"rds","type":"db.t4g.medium","vcpu":2,"mem_gib":4,
  "surplus_credits":730.6,"dbload_p95":0.547,"freeable_mem_min_gib":1.2,"sample_n":243,
  "cheaper_candidate_exists":true},

 {"rid":"cache-EX-01","service": "elasticache", "has_replica": false, "engine": "redis","type":"cache.r7g.large","vcpu":2,
  "mem_gib":13.07,"evictions_sum":0,"repl_lag_max":0.2,"engine_cpu_p95":12,
  "db_mem_used_pct_max":35,"reserved_memory_pct":null,"sample_n":243,
  "cheaper_candidate_exists":true},

 {"rid":"msk-EX-01","service":"msk","type":"kafka.m7g.xlarge","under_replicated_max":0,
  "disk_used_max":18,"handler_idle_p95":0.94,"cpu_total_p95":15,"sample_n":243,
  "cheaper_candidate_exists":true}]
```

顶层上下文与 EC2 共用同一个对象。只判托管服务时 `specs` / `prices` /
`baseline_pct` / `categories` / `offerings` / `legacy_families` 仍需存在
（可为空），它们只被 EC2 判据消费。

**字段语义（缺失一律 null，禁止兜底为 0）**

| 服务 | 字段 | 含义 | 缺失时 |
|---|---|---|---|
| 全部 | `sample_n` | **必填。** 该资源**主判据指标**在 biz-hours 档的有效点数：RDS 用 `DBLoad`（PI 不可得时用 `CPUUtilization`，两轴是并行关系，见下方 `dbload_p95` 行）、ElastiCache 用 `EngineCPUUtilization`、MSK 用 `CpuUser+CpuSystem` | `0` 或缺失 ⇒ `insufficient-data`。`0 < sample_n < min_biz_hours_points` ⇒ 照常跑完判据（**否决项照样报出**）并追加样本量 blocker；托管行不设 `confidence` |
| 全部 | `service` | `rds` / `elasticache` / `msk` | **抛错** |
| 全部 | `type` | 实例类 / node type / broker type 原文 | `KeyError` |
| RDS / EC / MSK | `cheaper_candidate_exists` | **兼容期字段。给了 `candidates` 就不再读它**（`core.py` 从候选列表派生，消掉一个重复真值源）。未升级采集侧时仍必填。 同形态下是否存在更便宜的机型。RDS 同引擎/同部署形态（不得跨引擎、不得改 Multi-AZ）、ElastiCache 同引擎（不得跨 CPU 架构）、MSK 同 broker 机型族系。由采集侧按取回的价目表判定。**仅按价格判定，不含规格适配校验**——该候选可能装不下当前需求，因此只给这个布尔值时 `downsize-candidate` **不保证有钱可省**，`core.py` 会在 `blockers` 里标注适配性未校验（实测：一个 `cache.t4g.medium` 复制组此字段为 `true`，但内存已用到 maxmemory 的 59.24% ⇒ 需节点内存 ≥ 1.830 GiB，同架构下更便宜的两个候选 1.37 GiB 与 0.5 GiB 都装不下 ⇒ 实际可省 $0）。**给了 `candidates` 就不再有这个问题** —— 适配校验在 `core.py` 里做 | 两者都缺 ⇒ `metric-missing`（不得假定存在） |
| RDS / EC | `vcpu`、`mem_gib` | 取自 pricing 属性，**不得由 EC2 机型外推** | `spec-unknown` |
| RDS / EC / MSK | `candidates` | 该资源同形态的**全部**候选（含比当前贵的），每项 `{t, usd, vcpu, gib, arch, burst}`。取价用各服务的复合键：RDS `engine` + `deploymentOption`（Multi-AZ 是独立 usagetype、2 倍单价）、ElastiCache `^[A-Z0-9]+-NodeUsage:` 紧邻正则 + `(type, operation)` 双重消歧、MSK `computeFamily` 且排除 Express。`gib` **必须**来自 pricing 的 `memory` / `memoryGib` 属性 | 缺失 ⇒ 回退旧路径（读 `cheaper_candidate_exists`、不出目标），**不 fail-closed** |
| RDS / EC / MSK | `cur_usd` | 当前规格的按需小时价。**给了 `candidates` 就必填** | 缺失 ⇒ 同上回退（视为采集侧契约违反，不静默选出目标） |
| RDS / EC / MSK | `arch` | `arm64` / `x86_64`。剥掉 `db.` / `cache.` / `kafka.` 前缀后查 `ec2-types.json`。**只查 `arch`，绝不查内存** —— `cache.t3.medium` 真实 3.09 GiB，EC2 映射得 4.00 GiB，偏 +29%，而 `DatabaseMemoryUsagePercentage` 是相对真实节点内存的百分比，基数错则绝对量全错 | 缺失 ⇒ 同架构筛选全落空 ⇒ 报「跨架构」成因 |
| EC / MSK | `count` | 节点数 / broker 数，金额按它乘算 | 缺失按 `1` |
| EC | `engine` | `redis` / `valkey` / `memcached`。判两个主判据指标是否适用 | `metric-missing`（不得假定 Redis） |
| EC | `has_replica` | 该复制组是否存在副本。区分「无副本故 `ReplicationLag` 不适用」与「采集失败」 | `metric-missing` |
| RDS | `dbload_p95` | Performance Insights `db.load.avg` 的 p95（`Average` 序列、`biz-hours` 档）。与 `sus_cpu` 是**并行两轴**，`required_vcpu` 取两轴的 max —— 不是主备关系 | **只有两轴都缺**才 `metric-missing`。单缺本字段 ⇒ 只用 CPU 轴 + blocker，且按成因分写「该实例类结构性不支持 PI」（查 `rds-pi-unsupported.json`）与「PI 未开启」：前者要换机型才能拿到，后者改个开关即可，动作不同 |
| RDS | `dbload_max_p95` | **可选。** `DBLoad` 的 **`Maximum`** 序列在 `full-window` 档的 **p95**（不是 `max` —— 按单次尖峰否决是本 skill 明令反对的）。用于**峰值反转校验**：`dbload_max_p95 / rds_dbload_ratio > vcpu` 时降 `confidence` 并要求人工去 PI 控制台核对，**不改 verdict** | 缺失 ⇒ 不做该校验，其余行为不变 |
| RDS | `sus_cpu` | `CPUUtilization` / `Average` / `biz-hours` 的 `p95`。CPU 轴的持续项，同时是唯一能产出「CPU 持续项超当前规格 ⇒ `upsize-candidate`」的输入 | 与 `dbload_p95` **两者都缺**才 `metric-missing` |
| RDS | `peak_cpu_p95` | `CPUUtilization` / `Maximum` / **`full-window`** 的 **`p95`**。**与 EC2 侧的 `peak_cpu`（取 `max`）口径不同**：RDS 的 CPU 尖峰可证明来自托管平面的维护动作（备份窗口、自动小版本升级），实测一台常态 4.00% 的库单峰 88.33%，按 `max` 反推需 3 vCPU 而它只有 2 —— 12 台按 `max` 判，aggressive 只剩 2 台可降、conservative 0 台 | 缺失 ⇒ CPU 轴只用持续项 + blocker（不当 0，那是替实例做假设） |
| RDS | `pi_enabled` | `describe-db-instances` 的 `PerformanceInsightsEnabled`。为真时把 `rds-pi-unsupported.json` 里的实例类从候选池排除，并在 blocker 里量化放弃的金额 | 缺失 ⇒ 不排除（PI 本来没开的实例已经没有 DBLoad 可失去） |
| RDS | `storage_free_min_gib` | `FreeStorageSpace` / **`Minimum`** / `full-window` 的 `min`，GiB。触 `0` ⇒ `blocked`，且文案明写这是**可用性事故而非成本项** | 缺失 ⇒ 不评估容量耐久度 + blocker |
| RDS | `storage_free_first_gib` / `storage_free_last_gib` / `window_days` | `FreeStorageSpace` / **`Average`** / `full-window` 的窗口首末点与窗口天数，用于外推剩余天数。**不用 `Minimum`** —— 它含 binlog 轮转的锯齿，会把速率算成负数或虚高 | 缺失 ⇒ 不外推 |
| RDS | `surplus_credits` | `CPUSurplusCreditsCharged` 的 `Maximum`（窗口内单小时最大，**不是窗口累计**） | **仅 `db.t*`**：`metric-missing`。非 burstable 结构性不发布该指标，缺失**不构成否决**（否则任何 `db.m*`/`db.r*` 的降配路径都永久不可达）。取到值且 >0 ⇒ `upsize-candidate`，**独立否决项，优先于 DBLoad**，这一半不分机型 |
| RDS | `freeable_mem_min_gib` | `FreeableMemory` 最小值，GiB，取 **`full-window`** 档（下限型判据，内存低点常在备份/批处理的 off-hours；只取 `biz-hours` 会把危险实例判成安全） | `metric-missing` |
| EC | `evictions_sum` | `Evictions` 的 **`Maximum`**（`full-window` 档，窗口内单小时最大）。**字段名里的 `_sum` 是历史命名，别照它去采 `Sum`**。它现在只是**尖峰值**，写进 `blockers` 让事件可见；否决与否看下一行 | `metric-missing`（且 `evictions_p95` 也缺 ⇒ 无从判断） |
| EC | `evictions_p95` | **可选。** `Evictions` 的 **`Sum`** 序列在 `full-window` 档的 p95 —— 即「有超过 5% 的小时发生过驱逐吗」。计数类取 `Sum` 不取 `Average`（后者需换算系数，本 skill 错过三次） | 回退 `evictions_sum`，行为与加该字段前逐字节相同 |
| EC | `repl_lag_max` | `ReplicationLag` max，秒（`full-window` 档）。现在只是**尖峰值** | 允许 null（非集群模式无此指标），不构成否决 |
| EC | `repl_lag_p95` | **可选。** `ReplicationLag` 的 `Average` 序列在 `full-window` 档的 p95，秒。这才是否决用的**持续值** | 回退 `repl_lag_max` |
| EC | `engine_cpu_p95` | `EngineCPUUtilization` p95。**不可用 `CPUUtilization` 替代**——Redis 单线程 | `metric-missing` |
| EC | `db_mem_used_pct_max` | `DatabaseMemoryUsagePercentage` max，是 **maxmemory（可用内存）** 的百分比 | `metric-missing` |
| EC | `reserved_memory_pct` | 集群参数 `reserved-memory-percent` | null ⇒ 取 `reserved_memory_pct_default` |
| MSK | `under_replicated_max` | `UnderReplicatedPartitions` max（**`DEFAULT` 档就有**，实测；不需要 `PER_BROKER`）。现在只是**尖峰值** | `metric-missing`（且 `under_replicated_p95` 也缺 ⇒ 无从判断） |
| MSK | `under_replicated_p95` | **可选。** 同指标 `Average` 序列在 `full-window` 档的 p95，是否决用的**持续值**。实测 8 个集群该值**全为 0** 而 max 达 27–244（MSK 滚动重启必然产生尖峰）⇒ 按 max 否决会永久关闭降配路径 | 回退 `under_replicated_max` |
| MSK | `disk_used_max` | `KafkaDataLogsDiskUsed` max，**0–100 刻度** | `metric-missing` |
| MSK | `handler_idle_p95` | `RequestHandlerAvgIdlePercent` p95，**0–1 刻度**（0.94 = 94% 空闲） | `metric-missing` |
| MSK | `cpu_total_p95` | metric math `CpuUser + CpuSystem` 逐点相加后的 p95，0–100 | `metric-missing` |

`handler_idle_p95` 是同 namespace 内唯一的 0–1 刻度指标，判据键
`msk_handler_idle_min` 也按 0–1 写。给成 `94` 会让「已合理配置」这道闸门
反向放行——升过 100 倍的值恒大于阈值，永远判成可降配。

`sample_n` 的守卫在 `dispatch()` 里短路，早于任何否决项——采样量不足时连否决项都不该报，因为那些指标同样没有统计意义。

`cheaper_candidate_exists` 的判定放采集侧是因为托管服务的价目阶梯与规格映射本来就在采集侧（见 `cli-recipes.md` 的非 EC2 取价属性表），`core.py` 只消费结论。

**三条否决项判「持续成立」而不是「曾经出现过一次」。** 每条读一个可选的
`*_p95`（缺失时回退 `*_max`，保证向后兼容）：持续值越界 ⇒ `blocked`；
持续值未越界而 max 越界 ⇒ **不否决**，但把尖峰写进 `blockers`。
尖峰不否决 ≠ 尖峰不报告——维护事件必须保持可见。

**三个托管服务的检查位置都在各自的欠配否决项之后，这是判据的一部分。**
「没有更便宜的候选」不得盖掉「这台机器太小了」：ElastiCache 是 `Evictions`／复制延迟，
MSK 是 `UnderReplicatedPartitions`，RDS 是**信用超额**（`surplus_credits > 0`
⇒ `upsize-candidate`）与 **DBLoad 瓶颈**（`dbload_p95 >= vCPU` ⇒ `blocked`）。
放在这些之后、在剩下的前置指标之前，就同时满足两件事：欠配问题照样报出来，
而候选集为空时不再要求客户为一条不可能存在的建议补指标、再等一个窗口。
RDS 侧有一处刻意接受的代价：`FreeableMemory` 的 OOM 阻断会被本条短路掉——
它说的是"缩不了"，与"没有可缩的目标"给出的动作完全一致（都不降配）。

### 输出（真实执行产出）

```
db-EX-01     verdict=downsize-candidate  bucket=downsize  blockers=[变更窗口+回滚；存储不可缩容]
db-EX-02     verdict=upsize-candidate    bucket=excluded  blockers=[CPUSurplusCreditsCharged=730.6 > 0]
cache-EX-01  verdict=downsize-candidate  bucket=downsize  required_gib_usable=3.431
msk-EX-01    verdict=downsize-candidate  bucket=downsize  blockers=[存储只能扩不能缩；不减 broker]
```

| 资源 | 结论 | 依据 |
|---|---|---|
| `db-EX-01` | `downsize-candidate` | 信用未超额 ⇒ 否决项不成立；DBLoad p95 0.4 低于 `rds_dbload_ratio`×vCPU；FreeableMemory 最小值 9.6 GiB 高于 `rds_freeable_mem_floor_pct`×16 GiB ⇒ 降配不会 OOM |
| `db-EX-02` | `upsize-candidate` | DBLoad p95 0.547 本身满足降配前置，但 `CPUSurplusCreditsCharged=730.6` ⇒ 规格已不足。**信用否决优先于 DBLoad**，且必须与降配建议分开呈现，否则会被读成可优化项 |
| `cache-EX-01` | `downsize-candidate` | Evictions=0、复制延迟未越界、EngineCPU 12% 与内存 35% 均低于目标。`required_gib_usable = 13.07 × (1 − 0.25) × 35 / 100 = 3.431` GiB——`DatabaseMemoryUsagePercentage` 是可用内存的百分比，故先扣 reserved 再乘 |
| `msk-EX-01` | `downsize-candidate` | UnderReplicatedPartitions=0；磁盘 18（0–100）低于 `msk_disk_used_max`；handler idle 0.94（0–1）高于 `msk_handler_idle_min` ⇒ 请求处理线程大部分时间空闲；CPU 15% 低于 `msk_target_cpu_p95` |

**本样例的托管行没有 `candidates`**，所以走的是兼容路径：只输出结论与
`blockers`，`nonburst` / `burst` 两列恒空 —— 上面那四行输出因此仍然是当前实现的
真实产出。给了 `candidates` + `cur_usd` + `arch`，同一条判据会选出初选目标与月省
（`nonburst` / `burst` / `nb_save_mo` / `b_save_mo`），并必带一条
「目标为本 skill 初选、须人工确认」的 blocker；人工的角色是**审核初选**，
不是选型。口径、代价与候选池为空的五种成因见 `report-template.md` 的
「托管服务的目标机型」一节。

## 改动 core.py 后的自检清单

```bash
# 1) 四个 verdict 全部出现（少一个 = 有死分支）
jq -r '[.[].verdict]|sort|unique|join(" ")' findings-sample.json
# 期望: downsize insufficient-data metric-missing spec-unknown

# 2) 输入行数 == 输出行数（不得静默丢行）
jq '.resources|length' solver-ctx.json; jq length findings-sample.json

# 3) 缺失指标不得产出建议
jq '[.[]|select((.metric_coverage|length)>0 and .verdict=="downsize")]|length' findings-sample.json
# 期望: 0
```

第 2 条是 `spec-unknown` 那个 bug 的通用检测式：**任何"输入 N 条、输出 <N 条"都是
静默丢行**，而丢掉的恰恰是判不了的那些资源——最需要被人看到的部分。
