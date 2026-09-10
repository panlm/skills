# 采样守卫降档 + 否决项改判持续态

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`；集群/复制组名换成
> `msk-<env>-NN` / `redis-<env>-NN` 占位名（原 8 个 MSK + 2 个 Redis 的**条数、
> 环境分布与彼此的区分度都保留**，只是不再是真名）。**指标值、点数、金额、
> 机型全是原值** —— 它们是结论的证据。占位名不对应任何真实资源，不要拿去查。

**日期**：2026-09-09
**状态**：待 review
**触发**：账号 `123456789012` / `ap-east-1` 的实跑（30 天窗口，两个 profile）暴露出
310 行里只有 35 行进判据，而其中 2 行被采样守卫整段短路、另有 10 行被单次尖峰永久否决。

## 问题陈述

三处判据把「**曾经出现过**」当成「**持续成立**」，把「**样本少**」当成「**不能判断**」。
两类都会静默压掉本该产出的结论，而且都不是保守——是错。

### P1：采样守卫整段短路，连否决项一起压掉

`core.py` 的 `dispatch()` 与 `evaluate()` 在 `n < min_biz_hours_points` 时立即
`return`，`verdict=insufficient-data`。后果不只是没有降配建议，而是**该资源的
否决项也没跑**：

| 资源 | 采样点数 | 报告实际写的 | 被压掉的事实 |
|---|---:|---|---|
| `msk-prod-01` | 148 | 「biz-hours 仅 148 点 < 168」 | `UnderReplicatedPartitions` 曾达 27 |
| `redis-uat-02` | 59 | 「biz-hours 仅 59 点 < 168」 | `ReplicationLag` 曾达 23.88s |

一个 prod 命名的 MSK 集群与一个 Redis 复制组的异常，被一道**采样量**守卫盖住了。
守卫的本意是「p95 无统计意义」，但否决项读的不是 p95，是 max —— 拿采样量去挡它
没有依据。

### P2：三条否决项判「曾经出现」而非「持续成立」

| 判据 | 现行条件 | 实测（本账号） |
|---|---|---|
| `eval_msk` | `under_replicated_max > 0` | 8/8 集群命中。Average 序列 **p95 全为 0.00**，加权均值 0.02–0.06，max 27–244 |
| `eval_elasticache` | `repl_lag_max >= redis_repl_lag_max_s` | 2 组命中。p95 0.001–0.005s，max 10.2s / 23.9s |
| `eval_elasticache` | `evictions_sum > 0`（实际取 `Maximum`） | 本账号未命中，但同形状 |

即 **95% 以上的时间指标为 0**，命中的是短暂尖峰。MSK 会自动打补丁做滚动重启
broker，重启期间副本必然短暂落后 —— 这条判据因此会在**任何窗口内被维护过的
MSK 集群**上误阻断。

本账号的暴露面：

| | 行数 | 按需月额 |
|---|---:|---:|
| 现在就被这三条否决项挡住 | 8 | **$1,274.13** |
| └ MSK `URP` | 7 | $1,155.87 |
| └ ElastiCache `ReplicationLag` | 1 | $118.26 |
| └ ElastiCache `Evictions` | 0 | $0.00 |
| C1 放行后会撞上这三条的 | 2 | $920.90 |
| **C2 的总暴露面** | **10** | **$2,195.03** |

（`msk-prod-01` $614.30 与 `redis-uat-02` $306.60 现在是
`insufficient-data`，被 P1 的守卫抢先短路，所以还没走到否决项。）

同一份 skill 在别处已经把这类推敲做对了：`FreeableMemory` 专门论证过「取 `Maximum`
或 p95 会取错方向」，`CPUSurplusCreditsCharged` 明确注明「采 `Maximum`，不是窗口
累计」。这三条缺的是同一层。

### P3：`cheaper_candidate_exists` 只按价格判，不按装得下判

采集侧计算该字段时只问「有没有更便宜的同形态机型」，不问「那个机型装得下当前
需求吗」。于是 `verdict=downsize-candidate` **不保证有钱可省**。

实测：`redis-uat-02`（`cache.t4g.medium` × 4，$306.60/mo）
`cheaper_candidate_exists=true`，但内存已用到 maxmemory 的 59.24% ⇒ 需要节点内存
≥ 1.830 GiB，而同架构下更便宜的两个候选是 `cache.t4g.small`（可用内存 1.028 GiB）
与 `cache.t4g.micro`（0.375 GiB），**都装不下**。真实可省 $0。

## 预期收益（不粉饰）

**对本账号：头条四条口径一分不变。** 实测三种组合：

| 改动 | downsize-candidate 条数 | 覆盖按需月额 |
|---|---:|---:|
| 现状 | 14 | $3,745.63 |
| 只改 P1 | 14 | $3,745.63 |
| 只改 P2 | 14 | $3,745.63 |
| **P1 + P2 一起** | **15** | **$4,052.23** |

P1 与 P2 **必须叠加才生效**——`redis-uat-02` 同时被两道挡住，拆掉
任何一道另一道还在。而新解锁的这一条按 P3 校验后**实际可省 $0**（无装得下的更
便宜机型）。

所以本次改动的价值是**判据正确性**，不是本账号的省钱：

1. 两条被压掉的健康事实会出现在报告里（P1）。
2. 在**任何做过维护的机队**上不再系统性误阻断（P2）——这是 bug 修复。
3. `downsize-candidate` 不再给出无法落地的候选（P3）。
4. 在**频繁重建的机队**（autoscaling、蓝绿、定期换机型）上，P1 会大量兑现——那类
   资源永远凑不满 168 点，现在会全部拿到带 `low` 置信度的建议而不是一句「点数不足」。

**不在本次范围**：托管服务的目标规格选型（$261–1,722/mo，本账号唯一能立刻变成钱
的一块）。它需要把候选池喂进 `core.py`、并为托管服务设计 EC2 那样的双候选口径，
是独立一份 spec。见文末「后续」。

## 设计

### C1：采样守卫从「拒绝线」改为「置信度分档线」

`min_biz_hours_points` 这个键**保留、值不变**，含义从「低于此拒绝」改为「低于此降档」。
唯一真值源仍是 `thresholds.json`。

```
n is None            → insufficient-data（不变。「不知道有多少点」连降档都无从判断）
n == 0               → insufficient-data（不变。零个点算不出 p95，是「无」不是「少」）
0 < n < floor        → 跑完整判据，产出结论，confidence=low，blockers 追加样本量说明
n >= floor           → 现行行为不变
```

**`confidence` 枚举新增 `low`**。分档两轴单调：

| | 有内存数据 | 无内存数据 |
|---|---|---|
| `n >= floor` | `high` | `medium` |
| `0 < n < floor` | `low` | `low` |

样本不足时不区分内存口径——样本量的问题盖过内存口径的问题。

**`blockers` 追加固定文本**（`core.py` 产出，不由采集侧拼）：

```
样本 <n> 点 < <floor>（占门限 <pct>%），p95 统计意义弱；
建议按此执行但缩短观察期，窗口填满后复评；变更时优先安排回滚演练
```

#### C1 的边界：只放开降配路径，不放开删除与停机路径

| 函数 | 动作 | 是否降档放行 | 理由 |
|---|---|---|---|
| `evaluate()` / 三条托管 evaluator | 降配 | **是** | 降配可回滚 |
| `is_idle()` | **删除** | **否，保持硬门限** | 删除不可回滚。基于 33 点判定「闲置可删」与基于 33 点判定「可降一档」不是同一风险级别 |
| `is_stop_candidate()` | 定时停机 | **否，保持现行三态** | 同上；且 `null`（判不了）已经如实表达了这件事，改成 `true` 会把「样本不足」伪装成「已验证可停」 |

这条线是本设计的核心权衡：**可回滚的动作允许低置信度产出，不可回滚的动作不允许。**

### C2：否决项改判持续态

新增三个可选输入，语义是**全窗口的持续值**。**取哪个 stat 逐指标而异**——按该指标
是 gauge 还是 counter 决定，遵循 skill 既有的「计数类只取 `Sum`」规则：

| 服务 | 新字段 | 持续值取自 | 指标性质 | 对应现有字段 | 该 stat 现在采了吗 |
|---|---|---|---|---|---|
| MSK | `under_replicated_p95` | `Average` 序列的 p95 | gauge（当前 under-replicated 的分区数） | `under_replicated_max` | **已采** |
| ElastiCache | `repl_lag_p95` | `Average` 序列的 p95 | gauge（秒） | `repl_lag_max` | **未采，需加 `Average`** |
| ElastiCache | `evictions_p95` | **`Sum`** 序列的 p95 | counter（每小时驱逐条数） | `evictions_sum`（历史命名，实际取 `Maximum`） | **未采，需加 `Sum`** |

`Evictions` 用 `Sum` 而不是 `Average`：它是计数类，p95 of 小时 `Sum` 直接回答
「有超过 5% 的小时发生过驱逐吗」，而 `Average` 对计数类需要换算系数——本 skill 在
那个系数上错过三次。实测确认现行采集：`UnderReplicatedPartitions` 有
`Average`+`Maximum`，而 `Evictions` 与 `ReplicationLag` **只有 `Maximum`**。

判定逻辑（三条一致）：

```
persistent = *_p95 if *_p95 is not None else *_max     # 缺失 ⇒ fail-closed 回退现行行为
if persistent 越界:
    verdict = blocked（不变）
elif *_max is not None and *_max 越界:
    不否决，blockers 追加：
    「<指标> 持续值（p95）<p95> 未越界，但窗口内曾达 <max>（单次尖峰，
      常见成因：滚动重启 / failover / 备份）。降配前确认该尖峰非容量不足所致」
```

两点必须成立：

- **尖峰仍然可见。** 不否决 ≠ 不报告。max 一律写进 blockers，维护事件不会被藏起来。
- **向后兼容且 fail-closed。** 采集侧未升级（只送 `*_max`）时行为与今天逐字节相同。

#### C2 的前置：`agg.jq` 需要产出真正的 full-window 档

`agg.jq` 现在只 `group_by` 出 `biz-hours` / `off-hours` / `weekend` 三档。
`cli-recipes.md §2.6` 用 jq 把三档的 `n` 相加、`max` 取 max 来近似全窗口——这对
`n` 与 `max` 成立，**对 `p95` 与 `mean` 不成立**（并集的 p95 ≠ 各档 p95 的 max）。

因此 `agg.jq` 增发一个 `bucket = "full-window"` 组，含窗口内全部点。
顺带让 `report-template.md` 里已存在的 `window_profile=full-window` 枚举值
第一次真正有聚合结果支撑（目前 NAT/ALB 行填的是 jq 现算的近似值）。

**为什么否决项用全窗口而不是 `biz-hours`：** 主判据指标（`sample_n` / `dbload_p95` /
`engine_cpu_p95`）skill 明确限定 biz-hours 档；但否决项是**安全判据**，副本落后、
驱逐、复制延迟不分工作时间。这与本次实跑发现的另一处同源问题一致——
`freeable_mem_min_gib` 现行只取 biz-hours 档的最小值，而内存低点常落在备份/批处理
的 off-hours（实测两台 RDS 因此偏高 0.18% 与 1.1%，本机队未跨越地板，属潜在缺陷）。
**该项一并修正为全窗口最小值。**

### C3：`cheaper_candidate_exists` 的语义澄清 + 未校验标记

**不把规格适配逻辑复制到采集侧。** 那会违反本 skill 的核心设计边界
（「判据错了是静默的且后果重，不得重新实现」）。改为两步：

1. **澄清字段文档语义**（`sample-solve.md`）：
   「存在更便宜的同形态候选，**仅按价格判定，不含规格适配校验**」。
2. **`core.py` 在托管 `downsize-candidate` 行上追加固定 blocker**：
   「更便宜候选是否装得下当前需求未经校验（`cheaper_candidate_exists` 只按价格判定）；
    目标规格须人工确认，可能不存在满足需求的更便宜机型」

这样消除「候选 ⇒ 有钱」的误读，而不引入第二个判据实现点。真正的适配校验放到后续
spec（把候选池喂进 `core.py`）。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | `evaluate()` 采样守卫改降档；`dispatch()` 同；`confidence` 三档；`eval_msk` / `eval_elasticache` 三条否决项改持续态 + 尖峰 blocker；托管 `downsize-candidate` 追加 C3 blocker |
| `references/thresholds.json` | 不加键。改 `_comment` 说明 `min_biz_hours_points` 现在是置信度分档线，且**不适用于 `is_idle` / `is_stop_candidate`** |
| `references/agg.jq` | 增发 `full-window` 档 |
| `references/cli-recipes.md` | ElastiCache 的 `ReplicationLag` 加采 `Average`、`Evictions` 加采 `Sum`（现在两者都只采 `Maximum`）；三个新字段的组装（取 full-window 档的 p95）；`freeable_mem_min_gib` 改取全窗口最小值；§2.6 的全窗口近似改用 agg.jq 的 full-window 档 |
| `references/sample-solve.md` | 字段契约加三个新字段；`cheaper_candidate_exists` 语义澄清；**四 verdict 自检的 fixture 要换**——`i-EX-04`（`cpu_n=154`）从 `insufficient-data` 变成 `downsize`+`low`，需新增一条 `cpu_n=0` 或 `None` 的资源，否则 `insufficient-data` 分支在样例里消失、自检失效 |
| `references/report-template.md` | `confidence` 枚举加 `low`，删掉「**没有 `low`**」那句；填法表 confidence 一列；低样本行的呈现规则；§1 摘要新增 breakout 行「其中 `confidence=low` 贡献 $X（占该口径 Y%）」；「`confidence=high` 且内存下降须附人工复核提示」扩展到 `low` |
| `SKILL.md` | 护栏那节「`biz-hours` 采样点数低于 `min_biz_hours_points` ⇒ 标 `insufficient-data`，不产出降配建议」重写；易错项速查表补两行（否决项判持续态、下限型指标取全窗口） |

### 测试影响（4 个文件）

| 文件 | 现行断言 | 改成 |
|---|---|---|
| `tests/test_managed_dispatch.py` | `sample_n < floor ⇒ insufficient-data`（第 327–352 行）——**这正是被改掉的行为** | `sample_n < floor ⇒ 仍出判据结论 + confidence=low + blocker 含样本量`；`sample_n` 缺失仍 `insufficient-data`（第 355 行那条**保留不动**）；新增：三条否决项 p95 未越界而 max 越界时不否决且尖峰进 blockers |
| `tests/test_csv_contract.py` | fixture `RES_EC2_NEW(cpu_n=1)` 注释 `# bucket=excluded`；`confidence` 枚举块 | 改为低样本降档；枚举块加 `low`；填法表校验跟着 `report-template.md` 走 |
| `tests/test_sample_reproduces.py` | 四 verdict 全覆盖 | 换 fixture 后重新覆盖四个 verdict |
| `tests/test_regression_fleet.py` | 两个 profile 的条数与总额逐值断言；「断言采样量守卫真的会触发」 | 重新定基线；守卫断言改为断言**降档**而非拒绝 |

`tests/test_thresholds.py`（双向键覆盖）与 `tests/test_no_duplicated_constants.py`
不新增键、不新增散文常量，预期不变；仍须跑。

## 验证方式

1. 八个测试文件全绿：`cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done`
2. `sample-solve.md` 的四 verdict 自检仍打印四个值。
3. **回放本账号**：`~/Downloads/123456789012-ap-east-1-20260909/regen/` 的独立复算
   管线（`step1`–`step5`）重跑，逐条断言 verdict 迁移：

   | 资源 | 现在 | 改后应为 | 理由 |
   |---|---|---|---|
   | `redis-uat-02` | `insufficient-data` | `downsize-candidate` + `confidence=low` | n=59 放行；lag p95 0.005s 未越界；CPU 0.64% / 内存 59.24% 均低于目标 |
   | `msk-prod-01` | `insufficient-data` | `已合理配置` + `confidence=low` + URP 尖峰 blocker | n=148 放行；URP p95 = 0 未越界；但 `cheaper_candidate_exists=false` |
   | 7 个 URP-blocked 的 MSK | `blocked` | `已合理配置` + URP 尖峰 blocker | p95 全为 0；`cheaper_candidate_exists` 全 `false` |
   | `redis-uat-01` | `blocked` | `已合理配置` + lag 尖峰 blocker | lag p95 0.001s 未越界；`cache.t4g.micro` 已在价目地板 |
   | 其余 25 条 | 不变 | 不变 | 采样充足且无否决项 |

   并断言：
   - **`downsize-candidate` 仍是 14 条**（不是 15）。原因：本轮 `raw/` 的
     ElastiCache 只采了 `ReplicationLag` 的 `Maximum`，没采 `Average`，所以
     `repl_lag_p95` 为 `None` ⇒ `core.py` 回退 `repl_lag_max` = 23.882s ⇒
     `redis-uat-02` 从 `insufficient-data` 变成 `blocked` 而不是
     候选。**这不是缺陷，是向后兼容按设计生效的实证**：采集侧未升级时行为不变。
     要拿到第 15 条，必须先按 C2 的采集改动重采一轮（加 `Average` / `Sum`）。
   - **四条头条口径的金额一分不变**（$58.39 / $87.30 / $50.79 / $3.32）。
     即便将来重采后第 15 条出现，它按 C3 校验实际可省仍是 $0——同架构下更便宜的
     `cache.t4g.small` 可用内存 1.028 GiB < 所需 1.373 GiB。
   - 8 个 MSK 集群全部从 `blocked` / `insufficient-data` 变成 `已合理配置`，
     且每一行的 `blockers` 都带 URP 尖峰说明（`UnderReplicatedPartitions` 已采
     `Average`，所以 MSK 这一侧的持续态判定真正生效）
   - `confidence=low` 行数为 **0**：4 台独立 EC2 全是 242 点，而两个低样本资源
     都是托管服务，按本 spec 的决定托管行不设 `confidence`
   - 桶 B（28 个闲置卷 $50.79）与 `stop_candidate` 列**完全不变**——C1 不放开这两条路径
4. 采集侧未升级的向后兼容：只送 `*_max` 的旧 `solver-in.json` 跑出的结果与改动前
   逐字节相同。

## 明确不做

- **不降低 `min_biz_hours_points` 的数值。** 只改它的作用（拒绝→降档）。
- **不放开 `is_idle` / `is_stop_candidate` 的门限。** 见 C1 边界表。
- **不把规格适配逻辑复制到采集侧。** 见 C3。
- **不改任何阈值数值。**
- **不动 EKS 路径。** 24 个节点 `service=eks` 不进 `core.py` 是刻意设计（托管
  nodegroup 的机型只能整池改），与采样门限无关。EKS 的 $9,417/mo 需要只读
  access entry，是另一件事。

## 后续（独立 spec）

**托管服务目标规格选型。** 把同引擎/同部署/同架构的候选池（type / vcpu / mem_gib /
usd）喂进 `core.py`，由判据侧做适配校验与选型，像 `evaluate()` 对 EC2 那样。
本账号指示性收益 **$261–1,722/mo**（区间下端只用 non-burstable 目标，上端含
`db.t4g` / `cache.t4g`，后者改变 CPU 风险模型，需要 EC2 侧那样的双候选口径）。
它会让 §11 从「人工选择（未自选）」变成可审计金额，也会顺带把 C3 的适配校验做实。
