# 托管服务判出了「可以降」却不说降到哪，以及主判据缺失时整行消失

RDS / ElastiCache / MSK 三条判据的终点是 `downsize-candidate`，
而 `nonburst` / `burst` / `nb_save_mo` / `b_save_mo` 四列**恒空**。
客户拿到的是「这台值得压，你自己去挑目标」，不是一条建议。

同一批判据还有第二个洞：RDS 的第一判据 `dbload_p95` 缺失即 `metric-missing`
并 `return`，而 Performance Insights 在 `db.t2/t3.micro/small`、
`db.t4g.micro/small` 上**结构性不支持**，在任何机型上又都可以只是没开。
这类实例永远只有一行「db.load.avg 缺失」。

本轮把两件事一起做：**每行都必须有一个结论**，且当结论是「可以降」时
必须给出初选目标；人工的角色从「自己选型」变成「审核初选」。

## 问题陈述

### P1：候选池被压成一个布尔值扔掉

`cheaper_candidate_exists` 由采集侧按**价格**判定。采集侧为算出它，
必然已经把同形态候选连价格一起取全了 —— 然后只回传一个 `true`。

`true` 不含信息量到近乎误导：本机队 `db.m6g.large`（$0.230/hr）往下最近的
更便宜候选是 `db.t4g.large`（$0.222/hr），省 $5.84/mo，占月额 3.5%。
布尔值为 `true`，而真正装得下需求的目标是 `db.t4g.medium`，省 $86.87/mo，
两者差 14.9 倍。判据没有能力区分，因为它看不到列表。

### P2：`_FIT_UNVERIFIED` 是一句无法闭合的免责声明

现行注释（`core.py`）自陈：

> `cheaper_candidate_exists` 由采集侧按**价格**判定，不校验候选是否装得下
> 当前需求 …… 不把适配校验复制到采集侧（那会造出第二个判据实现点），
> 改为在结论上标注。

裁定「不复制到采集侧」是对的，但它的另一半 —— 「所以在 `core.py` 里做」——
一直没做。于是 `_FIT_UNVERIFIED` 这段文案挂在每一条托管建议上，
永久声明「我们没校验」。而 `eval_elasticache` **已经算出了** `required_gib_usable`，
只是没人拿它去筛候选。所需的东西已经在手里。

### P3：托管节省结构性不进头条，且这是当前口径**刻意**造成的

`report-template.md` 明写：

> 三条托管判据不产出 `nb_save_mo` …… 因此它们的节省额**结构性不在
> 路线一/二里**：那两条口径都是对 `nb_save_mo` / `b_save_mo` 求和，
> 而托管服务行这两列恒空。
> **也不许写进 `other_save_mo`。**

本机队 12 台 RDS 里 9 台判了 downsize，对头条贡献 **$0**。
这不是漏算，是"不选目标"的必然下游后果 —— 一旦 P1/P2 修好，
两列有值，托管节省自动进入现有两条路线，**不需要新口径**。

### P4：`dbload_p95` 缺失是死胡同，而文档已承诺了一条不存在的兜底

两处文档写了 CPUUtilization 兜底：

- `metrics-catalog.md`：`| CPUUtilization | Average, Maximum | 次级判据 / PI 未开时的替代 | 已实测 |`
- `sample-solve.md`：`sample_n` …… RDS 用 `DBLoad`（**未开 PI 时用 `CPUUtilization`**）

同一份 `sample-solve.md` 的字段表又写 `dbload_p95` 缺失 ⇒ `metric-missing`，
自相矛盾。`core.py` 里兜底一行都没有。

`metrics-catalog.md` 记录的实测正好包含这个形态：
「2 个 MySQL（一 `db.t4g` 开 PI、一 `db.m5` 未开）…… `DBLoad` 仍只在开了 PI 的那台上」——
那台 `db.m5` 在现行判据下**永远**只能是 `metric-missing`。

`CPUUtilization` 采集侧已经在采（`cli-recipes.md` §2.3 的 mdq 列表第一项），
兜底不需要任何新增 API 调用。

### P5：`upsize-candidate` 只有一个出口，而它只对 burstable 成立

`eval_rds` 的升配出口是 `surplus_credits > 0` 与信用触底，两者都只在
`db.t*` 上有数据。非 burstable 实例**没有任何路径**能被判成规格不足：
CPU 与内存两轴都到不了 verdict。

实测 `db-uat-05`（`db.m6g.xlarge`）：

| 轴 | 数值 | 现行结论 |
|---|---|---|
| DBLoad p95 | 2.328 vs `0.5 × 4 vCPU` = 2.0 | 已合理配置 ← 差 0.328 跨过阈值 |
| CPU 持续 p95 | **69.64%**（目标 60/40%）⇒ 需 5–7 vCPU，现有 4 | 判据不看 |
| FreeableMemory 最小值 | **0.86 GiB** = 16 GiB 的 5.4%（地板 15%） | 短路到不了 |

一台 CPU 已到 70%、可用内存只剩 5.4% 的实例，报告写「已合理配置」。
EC2 侧 2026-09-10 已经补过同一个洞（`2026-09-10-ec2-underprovisioned-verdict-design.md`），
托管侧没跟上。

### P6：`FreeStorageSpace` 采了三十天，全代码库零引用

```
$ grep -rn "FreeStorageSpace" references/
（无输出）
```

`cli-recipes.md` §2.3 采了它（含 `Minimum` 统计），`agg.jq` 聚合了它，
`core.py` / `report-template.md` / `sample-solve.md` 一次都没提。

实测 `db-sit-05`（`db.m6g.2xlarge`，400 GB gp3）：`FreeStorageSpace`
`Minimum` 序列最小值 = **0.000 GB**，`Average` 序列最小值 0.919 GB，
窗口内 free 在 0–103 GB 间大幅摆动。同期 `DatabaseConnections` 峰值 1,328。

这台在报告里的唯一结论是「FreeableMemory 最小值 2.98 GiB < 15%，降配会 OOM」。
**磁盘被写满过这件事，报告里不存在。**

这条与 rightsizing 的命题确实不同（它是可用性事故，不是成本项），
但采集成本已经付了，且它的严重度高于本 skill 全部节省项。

### P7：判据只读 `DBLoad` 的 Average 序列，而 Maximum 序列大出两到三个数量级

`solverin` 只取 `DBLoad` / `Average` / `biz-hours` 的 `p95` 当 `dbload_p95`。
Maximum 序列被完整采下、写进 CSV 的 `evidence_cpu_max` 列，**不参与任何判定**。

全窗口实测（12 台，`Period=3600`）：

| 实例 | Average 均值 | Maximum 均值 | 比值 | Maximum p95 | 当前 vCPU |
|---|---:|---:|---:|---:|---:|
| `db-sit-01` | 0.0003 | 0.411 | 1370x | 1.0 | 2 |
| `db-uat-01` | 0.0013 | 0.733 | 564x | **2.0** | 2 |
| `db-infra-01` | 0.0964 | 16.600 | 172x | **23.0** | 2 |
| `db-sit-05` | 0.0687 | 2.076 | 30x | 7.0 | 8 |
| `db-uat-04` | 0.0866 | 2.379 | 27x | 7.0 | 8 |
| `db-uat-05` | 1.2941 | 6.364 | 5x | 11.0 | 4 |

**成因无法从聚合值判定，本 spec 不假装能判。** 12 台中有 9 台的
`mean(Maximum) > 60 × mean(Average)`，这否证了「PI 按 1 分钟发布」
（60 个采样点下 max ≤ 60 × mean 是硬上界）。两种解释与观测同样自洽：

- PI 以 **1 秒**粒度发布 ⇒ 3600 点/小时，`3600 × mean ≥ max` 对全部 12 台成立；
  此时 Average 是合法的细粒度均值，不是被稀释的。
- PI 以 **StatisticSet** 发布且 `SampleCount` 远大于实际点数 ⇒ Average 被稀释。

**两种解释下同一个缺陷都成立**：`db-infra-01` 的小时峰值达 16–23 个活跃会话，
跑在 2 vCPU 上（137–199 个连接），而判据只看均值 0.0964 并判 downsize。
把 `dbload_p95` 换成 Maximum 序列也不对 —— 那会退回 `_persistent()` 
明令反对的「按单次尖峰否决」。

所以本轮**不改判据的输入**，改成：当**峰值单独看就会翻转结论**时报出来。
判别式与阈值见 C6。`metric-validation.json` 现有的 `p95 > max`、`mean > max`
都是**同序列内**检查，跨 stat 一条也没有。

### P8：`max_mem_reduction_ratio` 在 ElastiCache 的内存阶梯上不可满足

这一条是本轮设计验证时新发现的，不在原始问题清单里。

ElastiCache 的节点内存不是 2 的幂：

| node type | 内存 GiB | 与下一档比值 |
|---|---:|---:|
| `cache.t4g.micro` | 0.50 | — |
| `cache.t4g.small` | 1.37 | 2.74 |
| `cache.t4g.medium` | 3.09 | 2.26 |
| `cache.m6g.large` | 6.38 | 2.07 |

`passes_common` 的内存地板是 `sp["gib"] >= ceil(cs["gib"] / max_mem_reduction_ratio)`。
conservative 的 `max_mem_reduction_ratio = 2` ⇒ 从 `cache.m6g.large` 往下要求候选
≥ 3.19 GiB，而下一档 `cache.t4g.medium` 只有 3.09 GiB。**差 3%，永久挡死。**

实测：把 EC2 的这道地板原样搬到 ElastiCache，conservative 下 11 组
**全部选不出目标**，合计 $0；且失败原因会被写成「无合规候选（需可用内存 >= 0.313 GiB）」——
一个用了 0.313 GiB 的集群被告知 6.38 GiB 的节点不能降，而真正的约束是降幅地板。
诊断信息指向错误的方向。

这道地板的立论（`core.py` 注释）是「目标利用率管不了窗口外的周期与发布间隔内的尖峰」，
理由与指标种类无关、可以成立；问题在于它用**比值**表达，而比值只在
干净的 2 的幂阶梯上等价于「降几档」。

### P9：RDS 的 CPU 峰值项按 `max` 会被托管平面的维护动作污染

同样是设计验证时发现的。EC2 侧 `peak_cpu` 取 `Maximum` 序列的 **max**
（`cli-recipes.md` 字段表、`solverin.jq`）。把它原样用于 RDS：

| 实例 | CPU 持续 p95 | Maximum 序列 max | Maximum 序列 p95 |
|---|---:|---:|---:|
| `db-uat-01` | 4.00% | **88.33%** | 7.89% |
| `db-sit-01` | 2.82% | 42.01% | 4.92% |
| `db-uat-04` | 14.87% | 99.81% | 18.97% |

`db-uat-01` 按 max 反推需 `ceil(2 × 88.33 / 85)` = 3 vCPU（超过现有 2）⇒
一台 CPU 常态 4% 的库看起来满载。12 台按 max 判，aggressive 只剩 2 台可降、
conservative 0 台，与 DBLoad 的结论大面积冲突。

成因与 `_persistent()` 已经论证过的完全同类，逐字引它自己的话：

> 否决项要判「持续成立」而不是「曾经出现过一次」…… MSK 自动打补丁做滚动重启，
> 重启期间副本必然短暂落后。按 max 否决等于在任何被维护过的集群上
> 永久关闭降配路径。

RDS 的备份窗口、自动小版本升级、`ANALYZE`/`vacuum` 产生的正是同形状的单点尖峰。

## 预期收益（不粉饰）

### 本机队实测（12 RDS + 11 Redis 复制组 + 8 MSK 集群）

路线二的口径是 **Σ max(nb, b) 逐条取更省者**，不是「burst 列求和」——
`db-sit-06` 的 nb（$261.34）比 b（$21.17）更省，故它按 nb 计入。

| 服务 | 路线一（非突发） | 路线二（逐条取更省） | 说明 |
|---|---:|---:|---|
| RDS | $261.34 | $875.27 | 9 行选出目标；1 行存储触 0、1 行 `FreeableMemory` 越地板、1 行 CPU 持续超 |
| ElastiCache | $0 | ag $1,235.89 / co $1,158.51 | 5 组选出目标；4 组在价目地板、2 组指标越目标。同架构更便宜候选全是 `cache.t4g.*`，故路线一为空 |
| MSK | $0 | $0 | **8 个集群一个目标都选不出，理由具体**，见下 |
| 合计 | **$261.34** | **ag $2,111.16 / co $2,033.78** |

改动前这三行合计对头条贡献 $0。

### MSK 收益为零，但这是本轮的正面产出

`kafka.m7g.large` 在 ap-east-1 的非 Express broker 价目里，**更便宜的机型只有
一个** —— `kafka.t3.small`，而它是 x86，`kafka.m7g` 是 Graviton3，
跨 CPU 架构迁移是 `SKILL.md` 硬约束禁止项。6 个 `kafka.t3.small` 集群本身
就在价目地板上，更便宜的候选数为 **0**。

改动前这 8 行的说明是「同形态下没有更便宜的候选机型」（笼统，且它来自一个
采集侧布尔值，判据自己并不知道为什么）。改动后是「同架构下更便宜的候选数为 0；
全区更便宜的 broker 机型仅 `kafka.t3.small`(x86)，跨架构为硬约束禁止项」。
**结论金额相同，可审计性不同。**

### 不要期待两个 profile 拉开差距

RDS 侧两个 profile 给出**完全相同**的 8 个目标。原因是这批负载的需求量被
向下取整到地板（`req_vcpu = 1`，而最小的 db 实例类是 2 vCPU），
`target_cpu_p95` 60 与 40 都不成为约束。profile 差异只在
ElastiCache 的增长余量上体现（$1,235.89 vs $1,158.51，差 6.3%）。

**不要因此调 profile 阈值** —— 差距小是因为这支机队极度空闲，
不是阈值失效。

## 设计

### C1：`candidates` 取代 `cheaper_candidate_exists`

采集侧回传列表而非布尔值，字段加在托管 `res` 上：

```json
"candidates": [
  {"t":"db.t4g.medium","usd":0.111,"vcpu":2,"gib":4.0,"arch":"arm64","burst":true},
  {"t":"db.t4g.large","usd":0.222,"vcpu":2,"gib":8.0,"arch":"arm64","burst":true}
]
```

裁定：

1. **取价的复合键复杂性留在采集侧。** RDS 的 `engine + deploymentOption + instanceType`
   （Multi-AZ 是独立 usagetype，2 倍单价）、ElastiCache 的
   `^[A-Z0-9]+-NodeUsage:` 紧邻正则与 `(type, operation)` 双重消歧、
   MSK 的 `computeFamily` 且排除 Express —— 这些坑都已踩平并有碰撞守卫。
   搬进 `core.py` 等于让判据层知道 pricing API 的形状，且要重踩一遍。
   EC2 侧的先例支持这个划分：`ctx["prices"]` 是**预先按 `type|operation` 键好**
   交给 `core.py` 的，`core.py` 只做筛选。

2. **`cheaper_candidate_exists` 改为 `core.py` 内部派生。** 采集侧同名字段
   在兼容期仍被接受（见 C7），但当 `candidates` 存在时**以 `candidates` 为准**，
   派生式是 `any(c["usd"] < cur_usd for c in candidates)`。这消掉一个重复真值源。

3. **`arch` 由采集侧从 `ec2-types.json` 查**（剥掉 `db.` / `cache.` / `kafka.` 前缀
   后按 EC2 机型名查 `describe-instance-types` 的结果）。

   **只查 `arch`，绝不查 `memory`。** `cache.t3.medium` 真实 3.09 GiB，
   映射到 EC2 `t3.medium` 得 4.00 GiB，偏 +29%；
   `DatabaseMemoryUsagePercentage` 是相对真实节点内存的百分比，基数错则绝对量错。
   内存必须取 pricing 的 `memory` 属性。**这条区别要写进代码注释**，
   否则后人会把两个查询"顺手统一"成错的那个。

### C2：三个服务的适配规则，各自复用已有阈值

**RDS**

```
peak_persistent = CPUUtilization/Maximum/full-window 的 p95      # C4
req_vcpu = max( _required(cur_vcpu, sus_cpu, peak_persistent,
                          target_cpu_p95, ceiling_cpu_max),
                ceil(dbload_p95 / rds_dbload_ratio) )            # DBLoad 可缺
req_gib  = (cur_mem_gib − freeable_mem_min_gib) / (1 − rds_freeable_mem_floor_pct/100)
```

内存侧**不叠加额外增长余量**：`/(1 − 15%)` 本身就是余量，且与 OOM 否决
用的是同一个阈值，自洽 —— 一个候选"装得下"的定义就是"降配后 FreeableMemory
仍高于那道地板"。

已知局限，须写进 blocker：MySQL / PostgreSQL 的 InnoDB buffer pool 会占满
可分配内存，所以 `cur_mem_gib − freeable_mem_min_gib` 是真实工作集的**上界**。
方向保守（不会推荐过小的机型），代价是系统性少省。实测
`db-sit-06`：实占算出 18.4 GiB（32 GiB 节点），据此需 21.61 GiB ⇒ 选到
`db.r6g.xlarge`(32 GiB) 而非 `db.m6g.xlarge`(16 GiB)。要修需要
`innodb_buffer_pool_*` 计数器，CloudWatch 不发布，**本轮不修**。

**ElastiCache**

```
used_usable = cur_mem_gib × (1 − reserved) × db_mem_used_pct_max/100   # required_gib_usable，口径不变
req_usable  = used_usable / (target_mem_p95 / 100)
候选可用内存 = cand_mem_gib × (1 − reserved) ≥ req_usable
req_vcpu    = max(1, ceil(cur_vcpu × engine_cpu_p95 / target_cpu_p95))
```

**本轮不新增任何阈值。** 候选下限由已有的 `target_mem_p95` 反推，语义是
「降配后内存利用率不超过本 profile 已声明的目标」，形式与 EC2 侧 `_required`
的内存项逐字一致（`ceil(cur_gib × sus_mem / target_mem_p95)`）。

它替代 P8 那道不可满足的内存降幅地板。**为什么可以换**：那道地板的立论是
`mem_used_percent` 不含可回收 page cache、会把内存 p95 压低，所以只能用一个
粗糙的比值兜住。ElastiCache 这条不成立 —— `DatabaseMemoryUsagePercentage`
是相对 `maxmemory` 的权威利用率，没有那个盲区，可以直接用利用率目标表达。

**实现期作废的第一版**：先写的是新增 `managed_mem_headroom`（aggressive 1.5 /
conservative 2.0）作乘性余量。两条既有守卫测试各否掉它一半 ——
`test_required_gib_usable_is_actually_usable_memory` 锁死「键名说 usable，
值就必须是可用内存口径」，而乘上余量后不是；
`test_distinctive_threshold_values_not_restated_in_prose` 报出值 `2.0` 与散文里
满篇的「§2.0」冲突（11 处命中）。改用 `target_mem_p95` 反推后两条都自然满足，
且少一个阈值。**这两条守卫测试比我先写的设计更对。**

CPU 侧的 `max_reduction_ratio` **保留**：vCPU 阶梯是干净的 2 倍，比值表达等价于档数。

**MSK**

```
req_vcpu = ceil(cur_vcpu × cpu_total_p95 / msk_target_cpu_p95)
```

无内存轴（`AWS/Kafka` 不发布 broker 内存利用率）。broker 数不变（硬约束）。
存储不参与候选筛选：卷大小与 broker 机型无关，`msk_disk_used_max` 是
独立的「已合理配置」出口，不是候选约束。

**三个服务共同的候选筛选**

```
c["arch"] == cur_arch          # 跨 CPU 架构是硬约束禁止项
c["usd"]  <  cur_usd
c["vcpu"] >= req_vcpu
c["vcpu"] >= ceil(cur_vcpu / max_reduction_ratio)
（RDS/EC 另加各自的内存条件）
```

选出后按 `(usd, t)` 排序取首个，**burstable 与非 burstable 各出一列**
（`SKILL.md` 硬约束：「不代替人工在 non-burstable 与 burstable 之间选择，
两列一律都出」）。

### C3：候选池为空时必须说出**哪条约束绑定**

P8 暴露的诊断缺陷。候选池为空有五种成因，动作相同（不降配）但可操作性完全不同：

| 成因 | blocker 文案要点 |
|---|---|
| 更便宜的候选数为 0 | 已在价目地板上；补指标或延长窗口都不改结论 |
| 更便宜的都跨架构 | 列出全区更便宜机型及其架构，明写跨架构为硬约束禁止项 |
| 被 `req_vcpu` 挡住 | 给出 `req_vcpu` 与最接近候选的 vcpu |
| 被内存条件挡住 | 给出 `req_gib` / `req_usable` 与最接近候选的可用内存 |
| 被 `max_reduction_ratio` 挡住 | 明写是降幅地板而非适配失败，给出地板值 |

现行代码在这五种成因上给同一句话，且那句话（「同形态下没有更便宜的候选机型」）
在后三种成因下是**错的**。

### C4：RDS 峰值项走 `_persistent()` 口径

`peak` 取 `CPUUtilization` / `Maximum` / `full-window` 的 **p95**，不是 `max`。

**EC2 侧 `peak_cpu` 保持取 `max` 不动。** 两者不对称是有依据的，不是漏改：
EC2 的 CPU 尖峰是真实业务负载（`_required` 注释：「峰值项不可省——只看 p95
会把有尖峰的负载降到峰值打满」），而 RDS 的尖峰可证明来自托管平面的维护动作
（备份窗口、自动小版本升级），与 MSK 的 `UnderReplicatedPartitions`、
Redis 的 `ReplicationLag` 同类 —— 那两条已经因为同一个理由改判持续态。

容忍度同样是 `VETO_TOLERANCE_PCT = 5`（`agg.jq` 对所有指标统一 `pct(0.95)`），
不新增阈值。

### C5：RDS 判据补三个出口

顺序即判据，插入位置逐条说明：

1. **CPU 轴作并行第二判据。** 位置：与 DBLoad 阈值判定并列，两轴取 max
   得 `req_vcpu`（C2）。`dbload_p95` 缺失时降级为主判据，
   并按成因分写 blocker：
   - 当前实例类在 PI 不支持列表内 ⇒「该实例类结构性不支持 Performance Insights」
   - 不在列表内 ⇒「Performance Insights 未开启，开启后重采可得第一判据」

   两者动作不同（前者要换机型才能拿到，后者改个开关即可），必须分开。

2. **CPU 持续项超当前规格 ⇒ `upsize-candidate`。** 位置：与
   `surplus_credits > 0`、信用触底两个出口并列，在 DBLoad 阈值判定**之前**。
   与 EC2 侧一致，只按**持续项**判，不用峰值项反推规格不足
   （`2026-09-10-ec2-underprovisioned-verdict-design.md` 的裁定）。

3. ~~**`FreeableMemory` 跌破地板 ⇒ 从 `blocked` 升为 `upsize-candidate`。**~~
   **实现期撤回。** 既有守卫测试 `test_managed_vetoes_actually_fire_and_block`
   反对这条，而它是对的：MySQL / PostgreSQL 的 InnoDB buffer pool **有意**
   占满可分配内存，`FreeableMemory` 报的是 `MemAvailable` —— 一个 buffer pool
   配置正确的库按设计就是低 freeable。

   反证就在本机队：`db-uat-04` 可用内存剩 9.7%，但 DBLoad p95 1.211（8 vCPU、
   占 15%）、CPU 持续 15%，完全不缺算力。这条证据支持「**缩不了**」，
   不支持「需要更大的实例」。欠配的判定归 C5-2 的 CPU 持续项出口 ——
   那一条读的是与内存分配策略无关的指标。

   保留 `blocked`，只改文案补一句「这条说的是缩不了，不是规格不足」。
   位置也不动（仍在候选池判定之后）：既然它不是欠配断言，原有裁定
   「候选集为空时不该为一条不可达的建议要求 FreeableMemory 数据」继续成立。

三个出口都**不产出升配目标机型**，沿用 EC2 侧措辞：选型需容量规划输入
（增长率 / SLA / 峰值形态）。

**`eval_rds` 改动后的完整分支顺序**（位置是判据的一部分，这里定死以消歧）：

```
 1. type == db.serverless                    ⇒ excluded
 2. vcpu is None                             ⇒ spec-unknown
 3. surplus_credits > 0                      ⇒ upsize-candidate   ← 已有
 4. 信用触底（burstable 且两端非 None）        ⇒ upsize-candidate   ← 已有
 5. CPU 持续项 > cur_vcpu                     ⇒ upsize-candidate   ← 新增(C5-2)
 6. 主判据全缺（dbload 与 CPU 都无）           ⇒ metric-missing     ← 改(C5-1)
 7. dbload_p95 >= vcpu                        ⇒ blocked            ← 已有
 8. dbload_p95 >= rds_dbload_ratio × vcpu     ⇒ 已合理配置          ← 已有
 9. 候选池可行性探针（无更便宜 / 全跨架构）     ⇒ 已合理配置 + C3 成因
10. burstable 信用指标缺失                    ⇒ metric-missing     ← 已有
11. FreeableMemory 缺失 / 越地板               ⇒ metric-missing / blocked ← 已有，仅改文案
12. FreeStorageSpace Minimum 触 0             ⇒ blocked            ← 新增(C6)
13. 选出目标                                  ⇒ downsize-candidate
```

第 6 步取代原先「`dbload_p95` 缺失即 `metric-missing`」—— 现在只有**两轴都缺**
才判不了。

**第 9 步的位置是原有裁定，本轮不动。** 它必须早于第 10–12 步的所有
fail-closed：结构性不可能的两种情形（没有更便宜的候选、更便宜的全部跨架构）
与任何指标无关，先判掉，否则会让客户为一条不可能产出的建议去开 PI、
补 FreeableMemory、再等一个完整窗口。本轮只是把这一步从读采集侧布尔值
换成带成因的探针（`_pick_managed_target(res, t, 1, lambda c: True, base)`），
顺序与免责说明都保持原样。

### C6：容量与跨 stat 校验

**`FreeStorageSpace`（新判据，RDS）**

- `Minimum` 序列最小值 == 0 ⇒ `blocked`，blocker 明写这是**可用性事故而非成本项**，
  且优先级高于本行任何降配讨论。
- 否则按窗口内消耗速率外推剩余天数，低于门限则要求先开 storage autoscaling。
  门限入 `thresholds.json`（`rds_storage_days_floor`）。

  外推口径必须写清：用 `Average` 序列首尾差除以窗口天数，**不用 `Minimum`**
  —— `Minimum` 含 binlog 轮转造成的锯齿，会把速率算成负数或虚高。

**`DBLoad` 峰值反转校验（新增，RDS）**

判别式 —— 触发条件是**峰值单独看就会翻转本行结论**：

```
dbload_max_p95 / rds_dbload_ratio > cur_vcpu
```

即「若把 Maximum 序列的 p95 当作持续值，`req_vcpu` 会超过当前规格」。
输入是 `DBLoad` / `Maximum` / `full-window` 的 **p95**（不是 max —— 
按单次尖峰否决正是 `_persistent()` 明令反对的）。

动作：blocker 写明两个序列的数值与倍数、`confidence` 降一档、
要求在 Performance Insights 控制台核对 Average Active Sessions 实际曲线。
**不改 verdict。** 与 `_coverage_note()` 同一条纪律 —— 哪条序列代表真实负载
取决于 PI 的发布语义（1 秒粒度 vs `SampleCount` 稀释，见 P7），
本 skill 拿不到，拿不到就不能算。

**为什么不用「跨 stat 物理一致性」当判别式**：我先写的版本是
`mean(Maximum) > 60 × mean(Average)`（否证 1 分钟发布周期）。
实测 12 台命中 **9 台** —— 它测的是 PI 在这个 region 的发布语义，
是**全机队一致的属性**，逐行报出只是噪声。而上面这条按「是否翻转结论」判，
实测精确命中 **2 台**（`db-uat-01`：Maximum p95 2.0 ⇒ 需 4 vCPU > 2；
`db-infra-01`：23.0 ⇒ 需 46 vCPU > 2），其余 10 台不触发。

`mean(Maximum) > 60 × mean(Average)` 这个观测仍然要留 —— 但作为
**run 级注记**写进 `metric-validation.json`（"本次采集中 N/M 个 RDS 实例的
`DBLoad` 两条序列与 1 分钟发布周期不自洽"），不进逐行 blocker。
常数 `60` 不进 `thresholds.json`：它是 `Period=3600` 除以标称发布周期
得来的物理上界，不是可按 profile 调的策略量，与 `VETO_TOLERANCE_PCT` 同类。

### C7：输出契约

托管行填满 `nonburst` / `nb_cat` / `nb_save_mo` / `nb_delta_vcpu` / `nb_delta_gib`
及对应 `b_*` 列、`required_vcpu` / `required_gib`。CSV **列数不变**（41 列），
只是托管行不再恒空。

- `verdict` 仍是 `downsize-candidate`。人工的角色是**审核初选**，不是选型。
  新增 blocker：「目标规格为 skill 初选（依据见本行 `required_*` 与证据列），
  须人工确认变更窗口与回滚预案」。
- `_FIT_UNVERIFIED` **删除**。它声明的那件事本轮做了。
- 托管行 `confidence`：选出目标 ⇒ `medium`；样本不足 ⇒ `low`（沿用
  `dispatch()` 现行逻辑）。**永不 `high`** —— 适配校验建在观测稳态上，
  不含业务增长输入，而 `high` 在 EC2 侧的含义是「CPU 与内存两轴都有实测数据」，
  语义不同，不可套用。
- **目标落在同架构价目阶梯最底档** ⇒ 强制 `confidence = low` + blocker
  「绝对量极小，且触底后估错了没有退路（不能再降，任何增长只能升配）」。
  实测触发行：`redis-infra-01` 实占 0.013 GiB ⇒ 目标 `cache.t4g.micro`
  （0.375 GiB 可用），倍数余量 19x 但绝对量只有 0.375 GiB。

  **实现期作废的第一版**：先写的是「距当前规格 ≥ 4 档」。实测在 ElastiCache 上
  **永不触发** —— 同架构比 `cache.m6g.large` 便宜的候选总共只有 3 档
  （`t4g.micro` / `t4g.small` / `t4g.medium`），阈值取 4 等于把护栏关掉，
  取 3 又是为这条阶梯挑的数、换 region 或服务即失效。
  「落在最底档」是结构性属性而非调出来的数。

**PI 不支持的实例类**：当前实例 `pi_enabled = true` 时，从候选池中**硬排除**
`db.t2.micro` / `db.t2.small` / `db.t3.micro` / `db.t3.small` /
`db.t4g.micro` / `db.t4g.small`，并在 blocker 里量化放弃的金额。

裁定理由：本 skill 整体是「缺判据即 fail-closed」，主动推荐一个**保证**
下一轮变成 `metric-missing` 的动作与之矛盾。列表存入
`references/rds-pi-unsupported.json`，带来源 URL 与复查方式，
并纳入 `test_no_duplicated_constants.py` 的覆盖。

本机队上这条是空转的（那几个机型内存都不够），故不影响本轮数字 —— 
**这是好事，说明它不是为了凑数字而加的**。

**RDS burstable 候选的信用余量校验**：`_credit_exhausted` 注释明写
「RDS 的 baseline 百分比不在本 skill 的静态资产里」。解法是复用 EC2 的
`baseline-pct.json`（剥前缀查），并对**每个有信用数据的 `db.t*` / `cache.t*` 行**
做反推校验（信用上限 = `vcpu × baseline × 1440`），不符即该行 burst 列 fail-closed。
已确认吻合的两例：`cache.t3.medium` 576 = 2×0.20×1440、
`cache.t4g.micro` 288 = 2×0.10×1440。

### C8：向后兼容

`candidates` 缺失 ⇒ 行为与改动前**逐字相同**（读 `cheaper_candidate_exists`
布尔值、不出目标、保留 `_FIT_UNVERIFIED` 文案）。同理
`pi_enabled` / `partial_coverage` 等可选字段缺失不改变既有结论。

这条不是客套。实测教训（客户 123456789012）：旧契约缺两个必填字段时，
**86 条托管行全部 fail-closed**，升级后比不升级更差。
新字段一律走"缺失即回退旧行为"，不走 fail-closed。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | 新增 `_pick_managed_target()`；三个 evaluator 接候选池并选型；RDS 加 CPU 轴与两个 upsize 出口、`FreeStorageSpace` 判据、跨 stat 校验；删 `_FIT_UNVERIFIED`；`eval_rds` 分支重排（FreeableMemory 前移到 `cheaper` 之前） |
| `references/thresholds.json` | 新增 `rds_storage_days_floor`（唯一新增阈值；`managed_mem_headroom` 实现期作废，见 C2） |
| `references/rds-pi-unsupported.json` | 新建：PI 不支持的实例类列表 + 来源 URL |
| `references/cli-recipes.md` | 托管行组装加 `candidates` / `pi_enabled` / CPU 与 FreeStorageSpace 字段；`arch` 查法（只查 arch 不查 memory 的告警） |
| `references/sample-solve.md` | 字段契约表；修掉「`dbload_p95` 缺失 ⇒ `metric-missing`」与 `sample_n` 行 CPUUtilization 兜底承诺的自相矛盾 |
| `references/report-template.md` | 托管小节加目标列；删「托管节省结构性不进头条」那段裁定，改为进路线一/二并要求 confidence breakout |
| `references/metrics-catalog.md` | `DBLoad` 行补 StatisticSet 稀释说明与跨 stat 校验；`FreeStorageSpace` 行补消费者 |
| `references/thresholds.md` | `rds_storage_days_floor` 的标定证据；ElastiCache 内存轴改用 `target_mem_p95` 反推、取代内存降幅地板的立论 |
| `SKILL.md` | 托管服务小节：从「不自选目标」改为「初选目标 + 人工审核」；硬约束清单不变 |
| `tests/` | 见下 |

### 测试影响

新增：
- 三个服务各自的选型正确性与 fit 边界（含 P8 的 3.09 vs 3.19 GiB 边界）
- `candidates` 缺失回退旧行为（逐字比对改动前输出）
- PI 不支持实例类排除；`pi_enabled` 缺失时不排除
- 跨 stat 校验触发与不触发
- `FreeStorageSpace` 触 0 与外推剩余天数
- 两个新 upsize 出口；`eval_rds` 分支重排后的逐出口 blocker 保序
  （`_verdict()` 覆盖坑已踩过三次，新出口必须逐个验）
- `baseline-pct.json` 反推校验，含不符时 burst 列 fail-closed
- PI 不支持列表纳入 `test_no_duplicated_constants.py`（`managed_mem_headroom` 已作废，无需守卫）

**`test_regression_fleet.py` 的 `EXPECTED` 基线一分不动。** 已核实
`tests/fixtures/regression-fleet.json` 是 **EC2 独占的 13 行，零托管行**，
而 `route1_nb` / `route2_max` 只对 `bucket == "downsize"` 的行求和 ——
本轮不碰 EC2 路径，所以那两个数字必须**逐分不变**，任何变动都是回归。

改为新增独立的托管回归 fixture（`tests/fixtures/regression-managed.json`）
与独立 `EXPECTED`。两条基线分开的理由：EC2 基线的数字在仓库历史里带着
「旧值不删 + 写明成因」的长注释链（`527.15` 那段），把托管金额并进去
会让两类改动的成因永久纠缠在同一个数字上。

## 验证方式

1. `pytest` 全绿（当前 9 文件 / 100 测试，本轮后条数上升）。
2. **真实回放门禁**：对 `~/Downloads/<account>-<region>-<date>/raw/` 的归档数据
   离线重跑 solver + report，逐条核对：
   - 12 RDS：9 行选出目标、1 行存储触 0、1 行 `FreeableMemory` 越地板、1 行 CPU 持续超
   - RDS 路线一 $261.34 / 路线二 $875.27（两 profile 同值）
   - 11 Redis 复制组：5 组选出目标；4 组在价目地板；2 组指标越目标
   - 8 MSK：全部「同架构下更便宜候选数 0」，且 blocker 指明成因
   - `db-sit-05` 的 `FreeStorageSpace` 触 0 被报出
   - `DBLoad` 峰值反转校验**只命中 `db-uat-01` 与 `db-infra-01`**（不是 9 台）
   - `db-uat-05` 从「已合理配置」变为 `upsize-candidate`
3. 头条金额与 §预期收益的表逐格对账。
4. 安全自检：只读、无 `ce:*`、无 mutating 调用（三条 grep 照旧）。

## 明确不做

- **不产出升配目标机型。** 三个新 upsize 出口只报「已不足」与依据。
- **不碰硬约束清单。** Multi-AZ→Single-AZ、Redis 减副本/减 shard、
  MSK 减 broker、跨 CPU 架构、Serverless 迁移一律仍不产出。
  本轮只在**允许的动作空间内**选目标。
- **不修 buffer pool 上界问题**（C2 已说明缺指标）。
- **不改 EC2 侧 `peak_cpu` 口径**（C4 已说明不对称的依据）。
- **不做名字启发式判生产。** 本机队有一个 `msk-prod-01`，它本来就选不出候选；
  生产判定留给人工审核环节。
- **不放宽 `max_reduction_ratio` 的 CPU 侧。**

## 后续

- ElastiCache / MSK 的 `FreeStorageSpace` 等价物（`BytesUsedForCache` 对上限、
  `KafkaDataLogsDiskUsed` 的外推）本轮未做，MSK 那条已有「已合理配置」出口
  但没有耐久度外推。
- `DiskQueueDepth` / `EBSIOBalance%` / `EBSByteBalance%` / `SwapUsage` /
  `BurstBalance` 五个 RDS 指标未进采集契约。它们能给出「CPU 闲但 IO 堵」
  这个 DBLoad 缺失时无法替代的信号，是 P4 兜底路径的下一步加固。
- PI 的 `SampleCount` 真实语义若能确认，C6 的跨 stat 校验可以从「只标注」
  升级为「选定可信序列」。
