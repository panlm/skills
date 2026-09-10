# EC2 判据补「规格不足」出口 + 「仅子集发布」指标的通则

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`；EC2 实例 ID 换成 `i-A01`…`i-A06`
> 占位（**台数、机型、彼此的区分度都保留**）。**指标值、点数、金额、机型全是原值**
> —— 它们是结论的证据。占位 ID 不对应任何真实资源。

**日期**：2026-09-10
**状态**：待 review
**触发**：排查 `2026-09-10-burstable-credit-not-applicable-design.md` 留下的「后续」项时，
发现一个与信用指标无关、且更严重的独立缺陷：`evaluate()` 的 verdict 只有两个出口，
把「规格不足」输出成了「已合理配置」。

**本 spec 是三轮里的第一轮。** 第二轮（`CPUCreditBalance` 适用性 + ElastiCache
两条否决项的 fail-open/fail-closed 不对称）与第三轮（ElastiCache 分不出 Redis 与
Memcached）各有独立 spec。三轮的关系见 P4 与「后续」。

## 问题陈述

### P1：verdict 是二元的，「已合理配置」盖住了规格不足

`references/core.py` 的 `evaluate()` 末尾一行：

```python
out["verdict"] = "downsize" if (out["nonburst"] or out["burst"]) else "已合理配置"
```

**没有第三个出口。** 而「找不到候选」有三种互不相同的成因：

| # | 成因 | 「已合理配置」是否成立 |
|---|---|---|
| 1 | 需求量 ≤ 当前规格，但没有更便宜的合规候选 | **成立** —— 这是该标签的本意 |
| 2 | **需求量 > 当前规格** | **不成立** —— 规格不足，降配搜索本来就不可能有结果 |
| 3 | 需求量 ≤ 当前规格，更便宜的选项都被别的过滤挡掉（架构 / legacy / 用途分类 / EBS 带宽 / 降幅上限） | 成立（机器装得下负载，只是没有更便宜的合规选项） |

成因 2 被折叠进了同一个**肯定断言**。「已合理配置」对客户的意思是「已核查，无需
优化」，而这些行的真相是「本 skill 算出来它需要的比现在有的更多」。

实测（账号 `123456789012` / `ap-east-1`，conservative）：**9 行 EC2 /
$1,705.84 月额**属于成因 2。同一份 CSV 里 `required_vcpu` 与 `cur_vcpu` 并排打印，
**自相矛盾就写在同一行上**，而读者没有任何线索发现它。

`eval_rds()` 早就有 `upsize-candidate` 出口（信用超额 ⇒ 规格已不足）。
EC2 侧连这个概念都没有。

### P2：「持续项超」与「仅峰值项超」必须分开

`_required()` 取两项的 max：

```python
return max(_ceil_div(cur * sustained, target), _ceil_div(cur * peak, ceiling))
```

**峰值项是为降配方向设计的安全约束** —— 它的含义是「降配之后 max CPU 不得越过
`ceiling`」，存在的理由是防止把有尖峰的负载降到峰值打满。**拿它反推「当前规格
不足」是把一个为降配方向设计的约束用在了升配方向**，会得出站不住的结论：

| 实例 | 机型 | cpu_p95 | cpu_max | conservative required vCPU | 真相 |
|---|---|---:|---:|---|---|
| `i-A05` | t3.medium | **1.09%** | 76.09% | 3 > 现有 2 | 一台闲置的小机器偶尔冲一下，**不是规格不足** |
| `i-A01` | c6a.xlarge | **99.96%** | 99.97% | 10 > 现有 4 | 常年跑满，**是规格不足** |

`i-A05` 的 required 完全由峰值项驱动。把它判成规格不足是虚报。

所以**规格不足只按持续项判**：

```
rv_sus = ceil(cur_vcpu × sus_cpu / target_cpu_p95)
rg_sus = ceil(cur_gib  × sus_mem / target_mem_p95)     # 仅当有内存数据
规格不足 ⟺ rv_sus > cur_vcpu 或 rg_sus > cur_gib
```

实测按此规则筛，9 行收敛到 **4 行 / $996.00**，且**两个 profile 结果完全一致**：

| 实例 | 机型 | cpu_p95 | mem_p95 | conservative 持续项 | aggressive 持续项 | 月额 |
|---|---|---:|---:|---|---|---:|
| `i-A01` | c6a.xlarge | **99.96%** | 36.43% | vCPU 4→10 | vCPU 4→7 | $141.91 |
| `i-A02` | m7i.2xlarge | **78.01%** | **66.06%** | vCPU 8→16 / GiB 32→43 | vCPU 8→11 / GiB 32→31 | $404.71 |
| `i-A03` | c7i.xlarge | 57.18% | **72.36%** | vCPU 4→6 / GiB 8→12 | GiB 8→9 | $165.56 |
| `i-A04` | c6a.2xlarge | 51.36% | **71.43%** | vCPU 8→11 / GiB 16→23 | GiB 16→17 | $283.82 |

**两个 profile 命中同一批 4 台，是这条规则正确的旁证** —— 真实的规格不足不应随
风险偏好改变结论；随 profile 摆动的那 5 行，摆动的正是峰值项。

### P3：`upsize-candidate` 枚举值早已存在，只是 EC2 侧不产出

`references/report-template.md` 的 `verdict-enum` 块里已有 `upsize-candidate`，
且紧随其后已写明语义：

> `upsize-candidate` 不是降配建议——它表示该资源规格**已不足**，
> 出现在报告里必须与降配建议分开呈现，否则会被误读成可优化项。

所以本次**不新增枚举值**，三处下游都已就位：

| 下游 | 现状 | 本次是否需改 |
|---|---|---|
| `tests/test_csv_contract.py` | 已断言实跑产出的 verdict ⊆ `verdict-enum` 块 | **不需要** |
| `main()` 的 bucket 映射 | `{"downsize": "downsize"}.get(verdict, "excluded")` | **不需要**，落进 `excluded` |
| 四条汇总口径 / 分母 | `excluded` 行不带节省额，照旧计入分母 | **不需要**，逐值不变 |

唯一要改的一句是 `report-template.md` 紧接枚举块的「后三个来自托管服务判据
（`eval_rds` / `eval_elasticache` / `eval_msk`）」—— 本次之后 `upsize-candidate`
也由 `evaluate()` 产出。

### P4：本轮抓不到被限流的 T 实例（第二轮的范围）

`i-A06`（t3.xlarge）在 conservative 下 required 7 vCPU > 现有 4，但它的
`cpu_p95` 只有 **1.62%**，持续项规则**抓不到它**。

原因是它的 CPU 信用余额已经触底：

| | full-window | biz-hours |
|---|---:|---:|
| `CPUCreditBalance` / `Minimum` 的最小值 | **0.00** | **0.00** |
| `CPUSurplusCreditsCharged` / `Maximum` | 0.00 | 0.00 |

信用耗尽 ⇒ 被限流到基线 ⇒ **`CPUUtilization` 被压住**，持续负载看起来极低。
能揭穿这件事的指标（`CPUCreditBalance` 下限）当前**没有任何判据消费**。

**登记这一点是为了防止有人以为 P1/P2 修完就覆盖了全部「规格不足」。** 它属于
第二轮，本轮不做；本轮的 blocker 文案也不得暗示已经查过信用。

## 预期收益（不粉饰）

| profile | 从「已合理配置」改判 `upsize-candidate` | 涉及月额 |
|---|---:|---:|
| conservative | 4 行 | $996.00 |
| aggressive | 4 行（同一批） | $996.00 |

**不粉饰的部分：**

- **本次不产生任何节省额。** 分母、`route1`、`route2`、桶 B、采集侧四条口径**逐值不变**
  —— 改的只是一个错误的肯定断言。收益是「不再对一台常年 CPU 跑满 99.96% 的机器
  说无需优化」，不是钱。
- **剩下 5 行仍是「已合理配置」，这是刻意的**（理由见 P2）。但它们必须补一条
  blocker 写明绑定约束是峰值项，否则「为什么 required 比 cur 大却说合理」这个
  疑问仍然无解。
- **本 skill 不产出升配建议的目标机型。** `upsize-candidate` 只是告警 + 证据。
  选目标规格需要容量规划输入（增长率、SLA、峰值形态），不在本 skill 边界内。
- **被限流的 T 实例本轮抓不到**（P4）。
- **`cpu_p95` 本身可能被 basic monitoring 平滑。** 实测该账号 54/55 台是 basic
  monitoring（5 分钟发布且已平均）。这只会让本判据**偏保守**（真实持续负载可能
  更高），方向安全，但要在 blocker 里说明。

## 设计

### C1：verdict 三分支，顺序不可调换

```python
if out["nonburst"] or out["burst"]:
    out["verdict"] = "downsize"
elif under_provisioned:
    out["verdict"] = "upsize-candidate"
else:
    out["verdict"] = "已合理配置"
```

**先查候选、再判规格不足**，顺序有依据：候选池的过滤条件含
`s["vcpu"] >= rv and s["gib"] >= rg`，其中 `rv`/`rg` 是**全量** required（两项取
max）。所以**只要选出了候选，它按构造就已满足全量需求** —— 这类行是合法的降配，
不是规格不足。实测存在这种形态且现行行为正确：`c7i.8xlarge` 的 required 内存
85 GiB > 现有 64 GiB，却选出了 `r5.4xlarge`（128 GiB / 16 vCPU）并省 $349.23 ——
solver 正确地在需要增长的轴上放大、同时降了总价。**这条路径不得受本次改动影响。**

### C2：持续项单独算，不复用 `rv` / `rg`

`rv` / `rg` 已经是两项取 max 的结果，无法从中还原是哪一项在驱动。必须单独算持续项：

```python
rv_sus = _ceil_div(cs["vcpu"] * sus_cpu, t["target_cpu_p95"])
rg_sus = _ceil_div(cs["gib"] * res["sus_mem"], t["target_mem_p95"]) if mem_known else 0
```

`mem_known is False` 时内存轴**不参与判定**（`rg_sus = 0`）：无内存数据时
`rg` 已被置为 `cs["gib"]`（内存保持当前规格），拿它反推「内存不足」是替实例
做假设——与本 skill 既有的「无内存数据则内存不动」一致。

### C3：两侧都要写明驱动项

`upsize-candidate` 行的 blocker 须写出：命中的是哪个轴、持续值、目标利用率、
反推出的需求量；并声明本 skill 不给升配目标机型；并声明 basic monitoring 会
让持续值偏低（偏保守）。

仅峰值项超的「已合理配置」行也须补一条 blocker：写明 required 大于当前规格是
**峰值项**驱动、持续项未超、故不判规格不足。**不写这条，P1 的自相矛盾只是从
9 行缩到 5 行，没有消失。**

### C4：`report-template.md` 的产出方归属

「后三个来自托管服务判据（`eval_rds` / `eval_elasticache` / `eval_msk`）」
改成 `downsize-candidate` / `blocked` 来自托管判据，`upsize-candidate` 由
`eval_rds()` 与 `evaluate()` 两侧产出。

### E：立一条通则，而不是逐个指标打补丁

上一轮修的是 `CPUSurplusCreditsCharged`，第二、三轮还有
`CPUCreditBalance` / `ReplicationLag` / `EngineCPUUtilization` /
`DatabaseMemoryUsagePercentage`。逐个打补丁会漏，因为漏的那次不会有任何信号。

在 `SKILL.md` 立一条通则：

> **凡「仅某子集资源发布」的指标，判据必须先解析适用性、再判缺失**，并在该判据处
> 写明落在 fail-closed 还是 fail-open 哪一侧及理由。「不适用」与「缺失」是两件事：
> 前者是资源形态的属性，后者是采集的属性。混同的两个方向都错——把「不适用」当
> 「缺失」会让整条路径永久不可达（实测 25/29 台）；把「缺失」当「不适用」会让
> 否决项静默消失。判据里能区分二者的依据必须是**输入里已有的形态字段**
> （`spec["burst"]` / 实例类前缀 / 引擎 / 节点数），不得靠指标自身的有无来推断。

同时在该通则处挂一张已知成员清单，供新增指标时比对。**清单只列指标名与适用范围，
不复述阈值**（`tests/test_no_duplicated_constants.py` 的约束）。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | C1 三分支；C2 持续项；C3 两侧 blocker 文案 |
| `references/report-template.md` | C4 产出方归属；`upsize-candidate` 语义段补「EC2 侧的判定依据是持续项，不是峰值项」 |
| `SKILL.md` | E 通则 + 已知成员清单；EC2 一节补「规格不足走 `upsize-candidate`，不得输出「已合理配置」」 |
| `tests/test_fail_closed_contracts.py` | 新增两条：持续项超 ⇒ `upsize-candidate`；仅峰值项超 ⇒ 仍「已合理配置」且带 blocker |
| `tests/test_regression_fleet.py` + fixture | **不改**（已实测该机队 0 行命中，见下） |

### 测试影响

**回归基线完全不受影响 —— 已实测。** 逐台算过 `regression-fleet.json` 的 13 行，
两个 profile 下**持续项超当前规格的行数都是 0**：

```
conservative: 持续项超当前规格的行 0，verdicts {'downsize': 12, '已合理配置': 1}
aggressive:   持续项超当前规格的行 0，verdicts {'downsize': 13}
```

所以 fixture 与 `test_regression_fleet.py` 的锚定值（`route1_nb` / `route2_max` /
`MEM_FLOOR_OFF_ROUTE2` / `WITHDRAWN_ROUTE2_20260904`）、`verdicts` / `buckets`
计数字典**一律不改**。落地后其中任何一项变化都视为实现错误。

**但这同时是一个覆盖缺口，必须记下来。** 该机队里没有任何一台规格不足，
所以**回归基线对新分支提供零覆盖** —— 与上一轮 `surplus_credits: 0` 掩盖缺陷
是同一种结构性弱点：基线只覆盖它恰好包含的形态。

裁定：**不往 fixture 里加合成实例**。加一台就会改动锚定总额，而那份总额的价值
正在于它来自一次真实运行、逐值可追溯。新分支的覆盖由
`tests/test_fail_closed_contracts.py` 的单元测试承担，且两条测试都必须带
「反向半」（见下），否则同样是「候选池恰好为空也照样通过」。
这个缺口写进本节，不靠记性。

新增两条测试各自都要有「反向半」：持续项超的那条，把 `sus_cpu` 降到目标以下后
必须回到「已合理配置」；仅峰值项超的那条，把 `sus_cpu` 提到目标以上后必须变
`upsize-candidate`。否则测试无法区分「规则生效」与「候选池恰好为空」。

## 验证方式

1. 9 个测试文件全绿。
2. 新增两条测试的反向半都成立。
3. 真实数据回放（数据在仓库外，不得提交）：conservative 与 aggressive 各
   **4 行**由「已合理配置」变 `upsize-candidate`，两个 profile 命中**同一批实例**；
   `route1` / `route2` / 桶 B / 采集侧四条口径与分母**逐值不变**。
4. 仅峰值项超的 5 行仍是「已合理配置」，且每行都带 C3 那条 blocker。
5. `i-A06`（信用触底的 t3.xlarge）本轮**仍**是「已合理配置」——
   这是预期，用于确认 P4 的边界没有被无意越过。
6. `SKILL.md` 三条自检打印 `CLEAN`。

## 明确不做

- **不产出升配的目标机型。** 需要容量规划输入，不在本 skill 边界内。
- **不用峰值项判规格不足**（理由见 P2）。
- **不新增 verdict 枚举值**（`upsize-candidate` 已存在）。
- **不改 bucket 归类**：`upsize-candidate` 落 `excluded`，四条口径与分母不动。
- **不消费 `CPUCreditBalance`** —— 第二轮。
- **不动 `eval_rds` / `eval_elasticache` / `eval_msk`。**
- **不重跑已交付的两份报告**（沿用上一轮的决定）。

## 后续

- **第二轮（B + D）：** `CPUCreditBalance` 下限在四个服务节被声明为 blocker 却
  无任何判据消费（实测 `i-A06` 触底 0.00 而 `CPUSurplusCreditsCharged` 全 0，
  现行否决项全盲）；`Evictions` fail-closed 与 `ReplicationLag` fail-open 不对称，
  两者都没判适用性，而 `count`（节点数）已在契约里可用于把门关严。
- **第三轮（C）：** `eval_elasticache` 输入里没有 `engine` 字段，
  `EngineCPUUtilization` / `DatabaseMemoryUsagePercentage` 是 Redis/Valkey 独有且
  都 fail-closed ⇒ Memcached 集群永久 `metric-missing`，且给出的说明
  （「Redis 单线程，整机 CPU 含后台线程」）对 Memcached 是错的。
- 成因 3（需求量 ≤ 当前规格但被别的过滤挡掉）目前与成因 1 共用「已合理配置」。
  本轮不拆——它对客户的行动含义相同（没有更便宜的合规选项）。若将来要拆，
  需要在行上留下「哪一道过滤是绑定约束」，那是独立的一份 spec。
