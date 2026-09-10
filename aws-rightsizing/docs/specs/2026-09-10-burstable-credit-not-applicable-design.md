# EC2 突发候选：信用指标缺失在非突发机型上是「不适用」不是「缺失」

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`；EC2 实例 ID 换成 `i-A01`…`i-A13`
> 占位（**台数、机型、彼此的区分度都保留**，只是不再是真 ID）。**指标值、点数、
> 金额、机型全是原值** —— 它们是结论的证据。占位 ID 不对应任何真实资源。

**日期**：2026-09-10
**状态**：待 review
**触发**：同一账号 `123456789012` / `ap-east-1` 的两次交付（2026-09-04 与 2026-09-10）
对比。突发路线从 15 台有候选塌到 1 台，`b_save_mo` 合计 $1,521.32 → $21.32。
排查后确认不是机队变了，是判据把「不适用」当成了「缺失」。

## 问题陈述

一条未经设计裁定的 fail-closed 分支，让**突发降配路线在生产环境永久不可达**。
四份文档各自都对，但没有一份对上代码；唯一能抓到它的测试用了一个物理上不可能
出现的输入值。

### P1：`surplus_credits is None` 无条件抑制突发候选

`references/core.py:256-260`：

```python
sc = res.get("surplus_credits")
if sc is None:
    out["burst_na"] = "CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用"
elif sc > 0:
    out["burst_na"] = "CPUSurplusCreditsCharged>0，当前规格已不足"
else:
    ...  # 唯一能选出突发候选的分支
```

`CPUSurplusCreditsCharged` **只有 T 系列实例发布**。`references/metrics-catalog.md`
的实测记录写得很清楚：「信用指标只在 `t*` 实例上｜两 region 合计 4 台有
`CPUCreditBalance`，**非 T 实例 0 台**」。

于是对每一台非突发机型，第一个分支必然命中，`else` 永远到不了。

本账号 29 台进判据的 EC2，`spec["burst"]` 与 `surplus_credits` 是否为空
**完全一一对应**：

| 当前机型 | 台数 | `spec["burst"]` | `surplus_credits` | 能否走到 `else` |
|---|---:|---|---|---|
| `t3.medium` ×3、`t3.xlarge` ×1 | 4 | `True` | `0.0` | 能 |
| `c6i.*` `c6a.*` `c7i.*` `c5a.*` `c5d.*` `m5d.*` `m7i.*` `r6i.*` | 25 | `False` | `None` | **不能** |

86% 的机队被一条读不到数据的判据挡在门外。而这条判据要回答的问题
（「这台 m5 有没有超额消费 CPU 信用」）对非突发机型**不存在**，不是「不知道」。

### P2：原始设计从没要求这条

`docs/specs/2026-09-03-utilization-based-rightsizing-design.md`：

> 峰值由突发信用吸收，但必须满足：
> - **当前机型已是 T 系列**且窗口内 `CPUSurplusCreditsCharged > 0` ⇒ 已在超额消费
>   信用，当前规格本就不足，**抑制 burstable 选项**

规则是**合取式**：「当前机型已是 T 系列」AND「`> 0`」。同一节还穷举了
`burstable 选项 N/A` 的合法理由，只有 T 系列 `8 vCPU / 32 GiB` 规格上限一条。
**「指标缺失」不在其中。**

`references/metrics-catalog.md` 的 EC2 行同样只写 `blocker（>0 抑制 burstable 选项）`；
真正记下 N/A 语义的是 RDS 行：「**仅 `db.t*` 发布**，非 burstable 缺失属"不适用"
不是"缺失"」。

`SKILL.md` 的 EC2 一节也是对的：「当前已是 T 系列且 `CPUSurplusCreditsCharged > 0`
时抑制 burstable 选项」。

所以实现比设计多了一个抑制条件，而这个条件在生产上覆盖绝大多数资源。

### P3：一句写错的设计文档把缺陷锁住了

`docs/specs/2026-09-04-run2-findings-design.md` 的 J2 条目，在记录 RDS 侧同类缺陷时写道：

> `eval_rds` 无条件卡 `surplus_credits is None`，而 `db.m5.*` / `db.r6g.*` 结构性
> 不发布信用指标 ⇒ 恒为 `metric-missing`。**EC2 侧用 `spec["burst"]` 做了这个区分，
> RDS 侧漏了**

最后半句当时就不成立 —— EC2 侧从未做过这个区分。这句话原样进了
`references/core.py` 的 `_rds_is_burstable()` docstring，于是 RDS 侧修好了，
EC2 侧因为「文档说它已经对了」而没有人复查。

EC2 路径上唯一用到 `spec["burst"]` 的地方是**候选池过滤**（`s["burst"]`，
判断候选机型是否突发型），与「当前机型是否突发型、信用指标是否适用」
是两件不同的事。J2 把这两者当成了同一个判断。

### P4：回归 fixture 用了物理上不可能的输入，正好绕过缺陷

`tests/fixtures/regression-fleet.json` 的 13 台机器里，**12 台是非突发机型**
（`c7g` / `m7g` / `m7a` / `m5` / `c5` / `m6g`），fixture 却给它们全填了
`"surplus_credits": 0`。

这个值在真实采集里**不可能出现** —— 那条序列对这些机型根本不存在。

于是官方锚定基线跑出来是这样（conservative，12 条突发候选中 11 条落在
`burst=False` 的当前机型上）：

```
i-EX-09  m5.xlarge   (burst=False) → t3a.xlarge   b_save=$38.11
i-EX-10  c5.large    (burst=False) → t3a.small    b_save=$60.22
i-EX-11  m5.large    (burst=False) → t3a.large    b_save=$19.05
...
```

**`tests/test_regression_fleet.py` 逐值断言这些数。** 也就是说 skill 的官方基线
断言的正是「非突发机型也要产出突发候选」—— 而生产上一条都产不出来。
fixture 里那个不可能的 `0` 是唯一挡在「声明的基线」与「实际行为」之间的东西。

**反向验证**（把 fixture 的 12 台改成真实值 `null`，core.py 不修）：

```
✗ test_regression_totals_both_profiles
    期望 route2_max=668.85  verdicts={'downsize': 13}
    实际 route2_max=548.98  verdicts={'downsize': 12, '已合理配置': 1}
✗ test_route_totals_exclude_idle_rows
✗ test_mem_reduction_floor_is_live_and_respected
✗ test_legacy_families_md_graviton2_cost_is_reproducible
10/14 passed
```

**14 条里 4 条断言当场崩，锚定的 `route2_max` 掉 $119.87，1 行 verdict 翻成
「已合理配置」。** 而 `route1_nb = 527.15` 一分不动 —— 与「缺陷只影响突发列」
完全吻合。fixture 若一开始就用真实值，这个缺陷第一天就会被抓住。

### P5：`burst_na` 文案给客户错误的整改指引

报告对一台 `c6i.4xlarge` 写「`CPUSurplusCreditsCharged` 缺失」，客户会去补一个
**物理上不可能存在的指标**。这比不给候选更糟：它把一条判据缺陷伪装成客户的
监控缺口。

## 预期收益（不粉饰）

真实数据回放（账号 `123456789012` / `ap-east-1`，30 天窗口，29 台 EC2，
用真实 `core-in-*.json` 分别跑修复前后）：

| profile | | downsize 行 | route1 | route2 | 突发候选 |
|---|---|---:|---:|---:|---:|
| conservative | 修复前 | 15 | 2,050.55 | 2,071.87 | 1 |
| | 修复后 | 18 | **2,050.55** | **2,419.81** | 12 |
| aggressive | 修复前 | 18 | 2,556.44 | 2,620.40 | 3 |
| | 修复后 | 20 | **2,556.44** | **3,064.98** | 16 |

`route1` 与每一行的 `nb_save_mo` **逐值不变**。爆炸半径严格限于突发列。

verdict 从「已合理配置」翻成 `downsize`：conservative 3 行、aggressive 2 行
（`i-A09` `c7i.large`、`i-A07` / `i-A08` `c5a.2xlarge`）。这三台没有合规的非突发
候选，但有合法的突发候选。

**不粉饰的部分：**

- **这不是「发现了新节省」，是恢复本该产出的候选列。** `route1` 与 `route2`
  是同一批资源上的**互斥**替代方案，客户最终只能选一条。头条金额不会因此变大。
- **真正的收益是那 3 行 verdict。** 「已合理配置」是对客户的**肯定断言**
  ——「查过了，没有优化空间」。在有合法降配路径的情况下这么写是错的结论，
  比少算金额严重。
- **跨到 T 系列的建议仍然需要人工判断。** `SKILL.md` 已声明「不代替人工在
  non-burstable 与 burstable 之间选择，两列一律都出」。本次修复只是让第二列
  真的出得来，不是主张 T 系列更优。
- **突发候选的安全性从来不靠信用指标。** 它靠 `core.py` 候选池里的两道校验：
  标称核数须吃得下峰值（`s["vcpu"] >= rv_peak`，突发上限是标称 vCPU 的 100%）、
  基线有效核数扣掉 headroom 后须吃得下持续负载
  （`_eff_vcpu(s, base) * head >= sus_abs`）。删掉的那条 fail-closed 不参与
  任何容量校验。
- **本次不改任何非突发候选、不改闲置判据、不改托管服务判据。**

## 设计

### C1：缺失分支加 `cs["burst"]` 守卫，与 `eval_rds` 同构

```python
sc = res.get("surplus_credits")
if cs["burst"] and sc is None:
    out["burst_na"] = "CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用"
elif sc is not None and sc > 0:
    out["burst_na"] = "CPUSurplusCreditsCharged>0，当前规格已不足"
else:
    ...
```

两处都必须改：

- **`cs["burst"] and`** —— 只有当前机型是 T 系列时，缺失才是真缺失。此时保持
  fail-closed：那种情况下「不知道有没有超额」是真实的未知。
- **`sc is not None and`** —— 不补这个守卫，`None > 0` 直接 `TypeError`。
  实测：只改第一行会让 core.py 在真实输入上崩，25 行全部失败。

**`> 0` 分支为什么保留对所有机型生效**：非突发机型上出现 `> 0` 只可能是采集侧
把别的资源的序列贴错了行（Label 撞名是本 skill 记录过的失效模式）。数据本身
有问题时抑制突发候选是安全反应，代价为零。不按 2026-09-03 spec 的字面把这个
分支也收窄到 T 系列。

### C2：采集契约写明「留空即正确」

`references/cli-recipes.md` 的 `surplus_credits` 一行现在只标「否（非必填）」，
取值定义为「agg 中 `CPUSurplusCreditsCharged` / `Maximum` 的 `max`，三档取最大」。
非突发机型那条序列不存在，照此执行自然产出空值 —— 契约本身是对的，但**没写
明这是预期状态**，所以组装侧会以为自己漏采了。

补两句：

- 非突发机型该序列**结构性不存在**，字段留空即正确，`core.py` 用 spec 的
  `burst` 标志区分「不适用」与「缺失」。
- **不要「贴心地」填 `0`。** 填 0 会让**当前机型是 T 系列而序列真的采失败**
  的情况被当成「已确认未超额」放行 —— 那是反方向的错，且没有任何信号。

### C3：回归 fixture 改成真实输入

`tests/fixtures/regression-fleet.json` 里 12 台非突发机型的
`"surplus_credits": 0` 改成 `null`。

实测：**C1 落地后，`test_regression_fleet.py` 14/14 全绿，锚定值一个不动。**
因为修复后 `0` 与 `None` 对非突发机型行为等价。所以这一步零代价。

不做这一步的后果见 P4 的反向验证：fixture 会继续用一个不可能的输入为整套
基线背书，同类缺陷下次还能再溜过去一遍。

### C4：订正 `core.py` docstring，不改历史 spec

`_rds_is_burstable()` docstring 里「EC2 侧用 `spec["burst"]` 做了这个区分，
RDS 侧此前漏了」现在才成立，改成两侧同构的表述，并注明本次日期。

`docs/specs/2026-09-04-run2-findings-design.md` 的 J2 **不改** —— 它是历史记录。
本 spec 点名它是缺陷的传播路径，这比抹掉它更有用。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | C1 两行判据；C4 docstring 订正 |
| `references/cli-recipes.md` | C2 `surplus_credits` 行补「留空即正确 / 不要填 0」 |
| `references/metrics-catalog.md` | EC2 的 `CPUSurplusCreditsCharged` 行补 N/A 注记，与 RDS 行对齐 |
| `SKILL.md` | 易错项速查加一行（EC2 突发规则正文**不动** —— 它本来就写对了） |
| `tests/fixtures/regression-fleet.json` | C3 12 台非突发机型 `surplus_credits` → `null` |
| `tests/test_fail_closed_contracts.py` | 抑制测试拆两条，见下 |
| `docs/README.md` | 索引加本 spec 与对应 plan |

### 测试影响（1 个文件 + 1 份 fixture）

`test_missing_surplus_credits_suppresses_the_burstable_candidate` 的被测对象是
`RES`，而 `RES["type"] = "m5.xlarge"` —— **非突发机型**。这个测试断言的正是缺陷
本身，必须拆成两条：

1. **当前机型是 T 系列 + 缺失 ⇒ 压制。** 原测试的 docstring 自己警告过
   「若只断言"缺失时 burst is None"，候选池本来就空也照样通过」。所以这条要
   有意义，需要一个「当前是 T 系列、且池子里有更便宜的 T 机型」的 fixture。
   **共享的 `SPECS` 只有 `t3.large` 一个突发机型**，往共享 `SPECS` 里加
   `t3.xlarge` 会给其他用同一份 `SPECS` 的测试引入一个新的更便宜候选，可能
   动到既有断言。**裁定：在新测试内部构造局部 specs，不碰共享常量。**
2. **当前机型非突发 + 缺失 ⇒ 给出候选。** 这条是缺陷的直接回归防护。

`test_regression_fleet.py` 的断言值全部不动，只改 fixture（见 C3）。

## 验证方式

1. `for t in tests/test_*.py; do python3 "$t"; done` —— 9 个文件全绿。
   **中间态实测**（C1 落地、测试尚未改写）：8 绿 1 红，红的**只有**
   `test_missing_surplus_credits_suppresses_the_burstable_candidate` 一条 ——
   即那条以非突发机型为被测对象、编码了错误契约的测试。
   其余 8 个文件（含回归基线）不受影响，这是 C1 爆炸半径的独立佐证。
2. 新增的两条测试各自都有意义：第 1 条同一台机器给 `surplus_credits=0` 时
   **必须**能选出候选（否则测试是空的）；第 2 条断言非突发机型缺失时候选非空。
3. 真实数据回放（不进版本库）：`route1` 与每行 `nb_save_mo` 逐值不变；
   `route2` 增量与本文表格一致；conservative 3 行 / aggressive 2 行 verdict
   从「已合理配置」翻成 `downsize`。
4. **fixture 反向验证**：C1 不落地 + fixture 为 `null` ⇒ 基线 4 条断言崩、
   `route2_max` 掉 $119.87（P4 已实测）。证明改完的 fixture 真的具备抓这类
   缺陷的能力，不是摆设。
5. `SKILL.md` 末尾三条自检仍打印 `CLEAN`。

## 明确不做

- **不重跑已交付的两份报告。** 本次只交付 skill 修复；口径变化留到下一次采集。
- **不改 `SKILL.md` 的 EC2 突发规则正文。** 它写的是「当前已是 T 系列且 `> 0`」，
  与本次裁定一致，只在易错项表加一行。
- **不把 `> 0` 分支收窄到 T 系列**（理由见 C1）。
- **不把 T 系列缺失升级成整行 `metric-missing`。** EC2 的非突发降配路径完全不
  依赖信用指标，砍掉整行是过度反应；`eval_rds` 那样做是因为 RDS 的第一判据
  链路不同。
- **不引入「是否允许跨到突发机型」的开关。** `SKILL.md` 已声明两列一律都出、
  不代替人工选择。
- **不动 `eval_rds`。** 它已经是对的，本次只是让 EC2 侧与它同构。

## 后续（独立 spec）

同一类错误（把「不适用」当「缺失」）可能还在别处：

- EC2 侧的 `CPUCreditBalance` —— 同样只有 T 系列发布，检查是否有判据无条件要求它。
- ElastiCache 的 `CPUCreditBalance` —— `metrics-catalog.md` 标注为「`cache.t*`
  是否触底」，需确认非 `cache.t*` 节点上是否走了 fail-closed。
- 通则待确认：**凡是「仅某子集机型发布」的指标，判据都必须先判适用性再判缺失。**
  值得在 `SKILL.md` 立一条通则，而不是逐个指标打补丁。
