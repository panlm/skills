# EC2「规格不足」verdict 出口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `evaluate()` 补第三个 verdict 出口，使「需求量超过当前规格」输出
`upsize-candidate` 而不是「已合理配置」，并按**持续项**（而非峰值项）判定。

**Architecture:** `evaluate()` 末尾的一行二元赋值改成三分支；持续项单独算
（`rv_sus` / `rg_sus`），不复用已经两项取 max 的 `rv` / `rg`。判定顺序为
「先查候选 → 再判持续项」，因为候选池已按全量需求过滤，选出候选即已满足需求。
`upsize-candidate` 是既有枚举值，`main()` 已把它归入 `excluded`，故分母与四条
汇总口径逐值不变。附带在 `SKILL.md` 立一条「仅子集发布的指标先判适用性」通则。

**Tech Stack:** Python 3（标准库）；测试为可独立执行脚本（`python3 tests/test_xxx.py`）。

**Spec:** [`docs/specs/2026-09-10-ec2-underprovisioned-verdict-design.md`](../specs/2026-09-10-ec2-underprovisioned-verdict-design.md)

## Global Constraints

- **本 skill 只读。** 不引入 mutating AWS 调用，不引入 `ce:*` / 账单 API。
- **阈值唯一真值源是 `references/thresholds.json`。** 判据与 blocker 文案里
  不得写死阈值数值，只能运行时从 `t[...]` 取值插值（沿用
  `f"超 T 系列上限 {t['burstable_max_vcpu']}C/..."` 的既有写法）。
- **不新增 verdict 枚举值。** `upsize-candidate` 已在 `report-template.md` 的
  `verdict-enum` 块里，`tests/test_csv_contract.py` 已断言实跑 verdict ⊆ 该块。
- **`tests/test_regression_fleet.py` 与 `tests/fixtures/regression-fleet.json`
  本次一律不改。** 已实测该机队两个 profile 下持续项超当前规格的行数都是 **0**
  （`conservative` verdicts `{'downsize': 12, '已合理配置': 1}`、
  `aggressive` `{'downsize': 13}`）。落地后其中任何一项变化都视为实现错误。
- **`route1` / `route2` / 桶 B / 采集侧四条口径与分母必须逐值不变**，
  `upsize-candidate` 落 `excluded` 且不带节省额。
- **不产出升配的目标机型。** `upsize-candidate` 只是告警 + 证据。
- **不用峰值项判规格不足。** 峰值项是降配方向的安全约束。
- **不消费 `CPUCreditBalance`**（第二轮）、**不动 `eval_rds` /
  `eval_elasticache` / `eval_msk`**。
- **公开仓库。** 提交内容不得出现真实账号 ID、实例 ID、资源名、profile 名、
  本机绝对路径。占位账号一律 `123456789012`。

---

### Task 1: 三分支 verdict 与两侧 blocker

**Files:**
- Modify: `references/core.py`（`evaluate()` 末尾的 verdict 赋值）
- Modify: `tests/test_fail_closed_contracts.py`（新增两条测试 + 修一条既有测试的
  fixture + `__main__` 的 `tests` 列表）
- Test: `tests/test_fail_closed_contracts.py`

**Interfaces:**
- Consumes: `core.evaluate(res, ctx)`；`_ctx(t, resources, specs=None, prices=None,
  cats=None, baseline=None)` 与 `_evaluate(res, t, **ctx_kw)`（上一轮已加的签名）；
  模块级 `RES`（`type="m5.xlarge"`，4 vCPU / 16 GiB）、`SPECS`
  （最大机型 4 vCPU / 16 GiB ⇒ 需求量 ≥5 vCPU 或 ≥17 GiB 时候选池必然为空）。
- Produces: `evaluate()` 新增 `upsize-candidate` 出口；判定量
  `rv_sus` / `rg_sus`（函数内局部，不进输出字典）。

- [ ] **Step 1: 写第一条失败测试 —— 持续项超 ⇒ `upsize-candidate`**

在 `tests/test_fail_closed_contracts.py` 里
`test_overspent_credits_suppress_the_burstable_candidate` **之前**插入：

```python
def test_sustained_demand_above_current_spec_is_upsize_candidate():
    """需求量超过当前规格 ⇒ `upsize-candidate`，不得输出「已合理配置」。

    「已合理配置」是面向客户的**肯定断言**（已核查、无需优化）。实测一支机队里
    9 行 EC2 带着这个标签，而同一行的 required_vcpu 大于 cur_vcpu —— 自相矛盾
    就写在同一行上，读者没有线索发现它。eval_rds 早有 upsize-candidate 出口，
    EC2 侧此前连这个概念都没有。

    三个反向半锁住规则边界，缺一条这个测试就不成立：
      ① 把 sus_cpu 降到目标以下 ⇒ 必须回到「已合理配置」（否则分不清是规则
         生效还是候选池恰好为空）；
      ② 内存轴独立成立（只有内存持续项超时也要判）；
      ③ 无内存数据时内存轴**不得**参与判定 —— rg 此时已被置为 cur_gib，
         拿它反推「内存不足」是替实例做假设。
    """
    t = core.load_thresholds("aggressive")
    base = dict(RES, rid="i-T-20", cpu_n=243, surplus_credits=0)

    cpu_over = _evaluate(dict(base, sus_cpu=80, peak_cpu=90), t)
    assert cpu_over["verdict"] == "upsize-candidate", cpu_over["verdict"]
    assert cpu_over["nonburst"] is None and cpu_over["burst"] is None, cpu_over
    assert cpu_over["required_vcpu"] == 6, cpu_over["required_vcpu"]
    need = [b for b in cpu_over["blockers"] if "当前规格已不足" in b]
    assert need, cpu_over["blockers"]
    assert "6 vCPU" in need[0] and "不产出升配目标机型" in need[0], need[0]

    # ① 反向：持续项落回目标以下 ⇒ 不再是规格不足
    sustained_ok = _evaluate(dict(base, sus_cpu=30, peak_cpu=90), t)
    assert sustained_ok["verdict"] == "已合理配置", sustained_ok["verdict"]

    # ② 内存轴独立成立
    mem_over = _evaluate(dict(base, sus_cpu=10, peak_cpu=20,
                              sus_mem=95, peak_mem=95), t)
    assert mem_over["verdict"] == "upsize-candidate", mem_over["verdict"]
    mem_need = [b for b in mem_over["blockers"] if "内存持续 p95" in b]
    assert mem_need and "22 GiB" in mem_need[0], mem_over["blockers"]

    # ③ 无内存数据 ⇒ 内存轴不参与判定，结论只由 CPU 轴驱动
    no_mem = _evaluate(dict(base, sus_cpu=80, peak_cpu=90,
                            sus_mem=None, peak_mem=None), t)
    assert no_mem["verdict"] == "upsize-candidate", no_mem["verdict"]
    assert no_mem["required_gib"] == no_mem["cur_gib"], no_mem
    assert not [b for b in no_mem["blockers"] if "内存持续 p95" in b], no_mem["blockers"]
```

同批在 `__main__` 的 `tests` 列表里，
`test_overspent_credits_suppress_the_burstable_candidate,` **之前**插入：

```python
             test_sustained_demand_above_current_spec_is_upsize_candidate,
```

- [ ] **Step 2: 跑，确认它失败**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py 2>&1 | grep -E "✗|passed"`
Expected: `✗ test_sustained_demand_above_current_spec_is_upsize_candidate: 已合理配置`
（第一个断言就挂：现行实现只有二元出口），`16/17 passed`

- [ ] **Step 3: 写第二条失败测试 —— 仅峰值项超 ⇒ 仍「已合理配置」但带 blocker**

紧接上一条测试之后插入：

```python
def test_peak_only_demand_stays_right_sized_but_says_why():
    """需求量超当前规格但只由**峰值项**驱动 ⇒ 仍「已合理配置」，且必须说明理由。

    _required 的峰值项是为**降配方向**设计的安全约束（降配后 max 不得越
    ceiling），拿它反推「当前规格不足」会把闲置的小机器判成不足 —— 实测一台
    t3.medium 的 CPU p95 仅 1.09% / max 76.09%，required 3 > 现有 2，
    它显然不是规格不足。

    但「已合理配置」这一侧也必须写明绑定约束是峰值项，否则「required 比 cur 大
    却说合理」这个疑问仍然无解 —— 那只是把自相矛盾的行数从 9 缩到 5。
    """
    t = core.load_thresholds("aggressive")
    base = dict(RES, rid="i-T-21", cpu_n=243, surplus_credits=0)
    out = _evaluate(dict(base, sus_cpu=30, peak_cpu=90), t)
    assert out["verdict"] == "已合理配置", out["verdict"]
    assert out["required_vcpu"] > out["cur_vcpu"], out
    why = [b for b in out["blockers"] if "峰值项" in b]
    assert why, out["blockers"]
    assert "持续项未超" in why[0], why[0]
    assert "不是升配判据" in why[0], why[0]

    # 反向：持续项一旦超过目标，同一台机器必须改判规格不足
    assert _evaluate(dict(base, sus_cpu=80, peak_cpu=90), t)["verdict"] \
        == "upsize-candidate"

    # 需求量未超当前规格的行不得带这条 blocker（它只解释「超了但不算不足」）
    fits = _evaluate(dict(base, sus_cpu=10, peak_cpu=20), t)
    assert fits["verdict"] == "downsize", fits["verdict"]
    assert not [b for b in fits["blockers"] if "峰值项" in b], fits["blockers"]
```

同批在 `__main__` 的 `tests` 列表里，紧跟上一步那行之后插入：

```python
             test_peak_only_demand_stays_right_sized_but_says_why,
```

- [ ] **Step 4: 跑，确认两条都失败**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py 2>&1 | grep -E "✗|passed"`
Expected: 两个 `✗`，`16/18 passed`。第二条的失败点是缺少含「峰值项」的 blocker。

- [ ] **Step 5: 改判据 —— 三分支**

`references/core.py` 里把这两行：

```python
    out["verdict"] = "downsize" if (out["nonburst"] or out["burst"]) else "已合理配置"
    return out
```

替换成：

```python
    # 「找不到候选」有三种成因，只有一种是「已合理配置」：需求量超过当前规格时
    # 降配搜索本来就不可能有结果，把它标成「已合理配置」是对客户的错误肯定断言。
    #
    # 只按**持续项**判规格不足。_required 的峰值项是为**降配方向**设计的安全约束
    # （降配后 max 不得越 ceiling），拿它反推「当前规格不足」会把 p95 1.09% /
    # max 76% 的闲置小机器判成不足。实测按持续项筛，9 行收敛到 4 行。
    rv_sus = _ceil_div(cs["vcpu"] * sus_cpu, t["target_cpu_p95"])
    # 无内存数据 ⇒ 内存轴不参与判定。此时 rg 已被置为 cs["gib"]（内存保持当前
    # 规格），拿它反推「内存不足」是替实例做假设。
    rg_sus = (_ceil_div(cs["gib"] * res["sus_mem"], t["target_mem_p95"])
              if mem_known else 0)
    if out["nonburst"] or out["burst"]:
        # 候选池已要求 vcpu >= rv and gib >= rg（rv/rg 是两项取 max 的全量需求），
        # 所以选出了候选就说明它满足全量需求 —— 合法降配，不是规格不足。
        # 实测存在这种形态且现行行为正确：某 c7i.8xlarge 的 required 内存
        # 85 GiB > 现有 64 GiB，却选出 r5.4xlarge（128 GiB）并省 $349.23。
        out["verdict"] = "downsize"
    elif rv_sus > cs["vcpu"] or rg_sus > cs["gib"]:
        out["verdict"] = "upsize-candidate"
        axes = []
        if rv_sus > cs["vcpu"]:
            axes.append(f"CPU 持续 p95 {sus_cpu}% ⇒ 按目标 "
                        f"{t['target_cpu_p95']}% 反推需 {rv_sus} vCPU，"
                        f"当前仅 {cs['vcpu']}")
        if rg_sus > cs["gib"]:
            axes.append(f"内存持续 p95 {res['sus_mem']}% ⇒ 按目标 "
                        f"{t['target_mem_p95']}% 反推需 {rg_sus} GiB，"
                        f"当前仅 {cs['gib']}")
        # insert(0) 而不是 append：规格不足是本行的**结论**，须排在低样本等
        # 附注之前。_verdict() 对托管侧做的是同一件事。
        out.setdefault("blockers", []).insert(
            0, "当前规格已不足（" + "；".join(axes)
            + "）。本 skill 不产出升配目标机型——选型需容量规划输入"
              "（增长率 / SLA / 峰值形态）。basic monitoring 会压低持续值，"
              "故本判据偏保守")
    else:
        out["verdict"] = "已合理配置"
        if rv > cs["vcpu"] or rg > cs["gib"]:
            out.setdefault("blockers", []).append(
                f"需求量 {rv} vCPU / {rg} GiB 大于当前规格 "
                f"{cs['vcpu']} vCPU / {cs['gib']} GiB，但由**峰值项**驱动"
                f"（CPU max {peak_cpu}% 对 ceiling {t['ceiling_cpu_max']}%）；"
                f"持续项未超（CPU p95 {sus_cpu}% 对目标 "
                f"{t['target_cpu_p95']}%），故不判规格不足。峰值项的作用是"
                f"防止降配落在尖峰上，不是升配判据")
    return out
```

- [ ] **Step 6: 跑，确认两条新测试通过、并定位那条既有测试的失败**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py 2>&1 | grep -E "✗|passed"`
Expected: `✗ test_low_sample_blocker_does_not_assert_a_recommendation_exists: upsize-candidate`，
`17/18 passed`。两条新测试均已通过。

- [ ] **Step 7: 修那条既有测试的 fixture（改输入，不改断言）**

`test_low_sample_blocker_does_not_assert_a_recommendation_exists` 的 ① 用
`sus_cpu=90 / sus_mem=90` 造「低样本且无候选」的行；新规则下持续项超 ⇒ 该行变
`upsize-candidate`。该测试的被测意图是「低样本 blocker 文案不得断言存在建议」，
`已合理配置` 只是脚手架（其 docstring 自己写着「`已合理配置` / `blocked` /
`metric-missing` 同理」）。把持续值降到目标以下、峰值保持高位即可保住原意图。

把这一行：

```python
    out = _evaluate(dict(RES, rid="i-LOW-NOREC", cpu_n=floor - 1,
                         sus_cpu=90, peak_cpu=95, sus_mem=90, peak_mem=95), t)
```

替换成：

```python
    # 持续值须落在目标以下、峰值保持高位：这样该行仍然无候选、仍然「已合理配置」，
    # 而不会命中新增的「持续项超 ⇒ upsize-candidate」分支。本测试锁的是 blocker
    # 文案，不是这个 verdict —— 但**不得**把断言放宽成「已合理配置 或
    # upsize-candidate」，那会让它不再锁定任何一种行形态。
    out = _evaluate(dict(RES, rid="i-LOW-NOREC", cpu_n=floor - 1,
                         sus_cpu=30, peak_cpu=95, sus_mem=30, peak_mem=95), t)
```

- [ ] **Step 8: 跑全套，确认 9 个文件全绿且回归锚定值未动**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿，`test_fail_closed_contracts.py` 为 `18/18 passed`，
`test_regression_fleet.py` 为 `14/14 passed`。

Run: `cd aws-rightsizing && git diff --quiet tests/fixtures/regression-fleet.json tests/test_regression_fleet.py && echo "回归 fixture 与断言均未改动 ✓"`
Expected: `回归 fixture 与断言均未改动 ✓`

- [ ] **Step 9: 提交**

```bash
git add references/core.py tests/test_fail_closed_contracts.py
git commit -F - <<'MSG'
fix(aws-rightsizing): give EC2 an under-provisioned verdict

evaluate() ended in a two-way verdict: a candidate means downsize, no
candidate means "already right-sized". That folded three different causes
into one affirmative claim, including "the requirement exceeds the current
spec", where a downsize search could never have succeeded. On a real fleet
9 rows carried that label while the same CSV row printed required_vcpu above
cur_vcpu.

Judges under-provisioning on the sustained term only. The peak term in
_required exists to stop a downsize landing on a spiky workload; reusing it
in the upsize direction flags a machine that idles at 1.09% p95 and touches
76% once. Sustained-only narrows 9 rows to 4.

Rows that clear the sustained bar but not the peak bar stay "already
right-sized" and now carry a blocker naming the peak term as the binding
constraint, so the reader is never left with a required value above the
current spec and no explanation.

upsize-candidate is an existing enum value that eval_rds already emits and
main() already buckets as excluded, so the denominator and all four totals
are byte-identical.
MSG
```

---

### Task 2: 通则与文档同步

**Files:**
- Modify: `SKILL.md`（易错项表加通则一行；EC2 一节补规格不足出口）
- Modify: `references/report-template.md`（`upsize-candidate` 的产出方与判定依据）
- Modify: `docs/README.md`（plans 表加本 plan）

**Interfaces:**
- Consumes: Task 1 落地的 `upsize-candidate` 出口。
- Produces: 「仅子集发布的指标先判适用性」通则，供第二、三轮引用。

- [ ] **Step 1: `report-template.md` 修正 `upsize-candidate` 的产出方**

把这一行：

```
后三个来自托管服务判据（`eval_rds` / `eval_elasticache` / `eval_msk`）。
```

替换成：

```
`downsize-candidate` 与 `blocked` 来自托管服务判据（`eval_rds` /
`eval_elasticache` / `eval_msk`）。`upsize-candidate` 由 `eval_rds()` 与
`evaluate()` **两侧**产出：RDS 侧的依据是信用超额，EC2 侧的依据是**持续项**
反推的需求量超过当前规格（**不是峰值项**——峰值项是降配方向的安全约束，
拿它反推规格不足会把闲置的小机器判成不足）。
```

- [ ] **Step 2: `SKILL.md` 的 EC2 一节补规格不足出口**

在 EC2 一节里「闲置判据（桶 B）走 `core.py` 的 `is_idle()`」那一条**之前**插入一条：

```
- **需求量超过当前规格 ⇒ `upsize-candidate`，不得输出「已合理配置」。**
  判定只用**持续项**（`sus_cpu` / `sus_mem` 对 `target_*_p95` 反推），
  峰值项不参与——它是降配方向的安全约束。仅峰值项超的行仍是「已合理配置」，
  但必须带一条 blocker 写明绑定约束是峰值项。本 skill **不产出升配的目标机型**：
  选型需要容量规划输入（增长率 / SLA / 峰值形态），不在本版本边界内。
```

- [ ] **Step 3: `SKILL.md` 易错项表加通则一行**

在易错项表最后一行之后、`## references` 之前插入：

```
| **「仅某子集资源发布」的指标，判据先判缺失而不先判适用性** | 「不适用」与「缺失」是两件事：前者是**资源形态**的属性，后者是**采集**的属性。混同的两个方向都错——把「不适用」当「缺失」会让整条路径永久不可达（实测 `CPUSurplusCreditsCharged` 让 25/29 台的突发路线关闭）；把「缺失」当「不适用」会让否决项静默消失。已知成员：`CPUSurplusCreditsCharged`（仅 `t*` / `db.t*`）、`CPUCreditBalance`（同）、`ReplicationLag`（仅有副本时）、`EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage`（仅 Redis/Valkey，Memcached 不发布） | **先解析适用性、再判缺失**，并在该判据处写明落在 fail-closed 还是 fail-open 哪一侧及理由。区分二者的依据必须是**输入里已有的形态字段**（`spec["burst"]` / 实例类前缀 / 引擎 / 节点数），**不得靠指标自身的有无去推断**——那是循环论证。新增指标先按这张清单比对 |
```

- [ ] **Step 4: `docs/README.md` 的 plans 表加一行**

在 plans 表最后一行之后加入：

```
| [2026-09-10-ec2-underprovisioned-verdict.md](./plans/2026-09-10-ec2-underprovisioned-verdict.md) | 给 `evaluate()` 补第三个 verdict 出口:需求量超当前规格 ⇒ `upsize-candidate`,按持续项判;附「仅子集发布」指标的通则 |
```

- [ ] **Step 5: 跑测试与三条安全自检**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿。`test_no_duplicated_constants.py` 尤其要过 —— 上面新增的
文案只提键名与实测台数，不含任何 `thresholds.json` 的数值。

Run（在 `aws-rightsizing/` 下，三条都须打印 `CLEAN`）：
```bash
cd aws-rightsizing
WL='eks update-kubeconfig|configure get'
BILL='\bce [a-z-]|cost-explorer|get-cost-and-usage'   # selfcheck-exempt: 自检自身的模式串
grep -oE 'aws [a-z0-9-]+ [a-z0-9-]+' SKILL.md references/*.md | sort -u \
  | grep -vE ' (describe|list|get)-' | grep -vE "$WL" || echo "CLEAN: read-only"
grep -niE "$BILL" SKILL.md references/*.md | grep -v selfcheck-exempt \
  || echo "CLEAN: no billing API"
grep -nE '^[[:space:]]*aws eks update-kubeconfig' SKILL.md references/*.md \
  | grep -v -- '--kubeconfig' || echo "CLEAN: update-kubeconfig 均写入临时 kubeconfig"
```
Expected: 三行 `CLEAN`

- [ ] **Step 6: 提交**

```bash
git add SKILL.md references/report-template.md docs/README.md
git commit -F - <<'MSG'
docs(aws-rightsizing): rule that subset-published metrics resolve applicability first

Three rounds of the same defect class are now on record, so the rule goes in
the pitfall table instead of being patched per metric: "not applicable" is a
property of the resource shape, "missing" is a property of collection, and
conflating them fails in both directions. Lists the known members so a new
metric gets compared against them.

Records that upsize-candidate now comes from evaluate() as well as
eval_rds(), and that the EC2 side judges it on the sustained term.
MSG
```

---

### Task 3: 交付前门禁与真实数据对账

**Files:**
- 无仓库改动。产出是一份验证记录，贴进 PR / 交付说明。

**Interfaces:**
- Consumes: Task 1–2 的全部改动。
- Produces: 对应 spec「验证方式」六条的可核对证据。

- [ ] **Step 1: 全量测试门禁**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿；`test_fail_closed_contracts.py` `18/18 passed`
（原 16，新增两条）；`test_regression_fleet.py` `14/14 passed`。

- [ ] **Step 2: 确认两条新测试的反向半都在**

```bash
cd aws-rightsizing && python3 - <<'PY'
import pathlib
src = pathlib.Path("tests/test_fail_closed_contracts.py").read_text()
checks = {
    "test_sustained_demand_above_current_spec_is_upsize_candidate": [
        'sustained_ok["verdict"] == "已合理配置"',   # ① 持续项降回 ⇒ 不再不足
        '"内存持续 p95" in b',                        # ② 内存轴独立
        'no_mem["required_gib"] == no_mem["cur_gib"]',  # ③ 无内存数据不参与
    ],
    "test_peak_only_demand_stays_right_sized_but_says_why": [
        '== "upsize-candidate"',                      # 反向：持续项超则改判
        'fits["verdict"] == "downsize"',              # 未超者不带该 blocker
    ],
}
for name, needles in checks.items():
    body = src.split(f"def {name}(")[1].split("\ndef ")[0]
    for n in needles:
        assert n in body, f"{name} 缺反向半断言：{n}"
    print("OK", name)
PY
```
Expected: 两行 `OK`

- [ ] **Step 3: 真实数据回放（数据在仓库外）**

设 `RAW` 指向一份既有交付的 `raw/` 目录（含 `solver/core-in-*-ec2-*.json` 与
`solver/totals-*.json`）。该目录含真实账号与资源 ID，**不得提交，逐行结果也不得
贴进仓库**。

```bash
RAW=<某份既有交付>/raw
CORE=$PWD/references/core.py
for prof in conservative aggressive; do
python3 - "$RAW" "$CORE" "$prof" <<'PY'
import json, subprocess, sys, glob, collections
raw, core, prof = sys.argv[1], sys.argv[2], sys.argv[3]
rows = []
for f in sorted(glob.glob(f"{raw}/solver/core-in-{prof}-ec2-*.json")):
    p = subprocess.run([sys.executable, core],
                       input=json.dumps(json.load(open(f)), ensure_ascii=False),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-400:]
    rows += json.loads(p.stdout)
ds = [r for r in rows if r.get("bucket") == "downsize"]
r1 = round(sum(r.get("nb_save_mo") or 0 for r in ds), 2)
r2 = round(sum(max(r.get("nb_save_mo") or 0, r.get("b_save_mo") or 0) for r in ds), 2)
old = json.load(open(f"{raw}/solver/totals-{prof}.json"))
up = [r for r in rows if r["verdict"] == "upsize-candidate"]
flag = "route1 一致 ✓" if r1 == old["route1"] else f"route1 变了 ✗ (旧 {old['route1']})"
assert all(r.get("bucket") == "excluded" for r in up), "upsize 行必须落 excluded"
assert all(r.get("nb_save_mo") is None and r.get("b_save_mo") is None for r in up), \
    "upsize 行不得带节省额"
print(f"  {prof:<13} route1={r1:<9} route2={r2:<9} upsize={len(up):<3} "
      f"verdicts={dict(collections.Counter(r['verdict'] for r in rows))} {flag}")
PY
done
```

Expected（与该份交付的旧 `totals-<profile>.json` 对账）：
- **`route1` 与旧值逐值相同**，`route2` 也应与该 raw 上一次回放的值一致
  （本轮不改候选选型）。
- `upsize-candidate` 行数 > 0 时，全部落 `excluded` 且两个 `*_save_mo` 皆为 `None`
  （脚本里已断言，不通过会直接 `AssertionError`）。
- **`upsize-candidate` 的行数允许两个 profile 不同。** 实测第一支机队两 profile
  都是 4 行、命中同一批；第二支机队 conservative 1 行、aggressive 0 行 ——
  持续值落在两个 profile 的目标利用率之间，属预期（见 spec 的 P2 末段）。
  **不要把「两 profile 必须一致」当成验收条件。**

若 `route1` 有任何变化 ⇒ **停止**，说明改动漏进了降配路径。

- [ ] **Step 4: 确认 P4 的边界没被越过**

在同一份 raw 上确认：**当前机型是 T 系列、`CPUSurplusCreditsCharged` 为 0、
但信用余额已触底**的那台实例，本轮**仍**是「已合理配置」。

```bash
RAW=<某份既有交付>/raw
python3 - "$RAW" "$PWD/references/core.py" <<'PY'
import json, subprocess, sys, glob
raw, core = sys.argv[1], sys.argv[2]
rows = []
for f in sorted(glob.glob(f"{raw}/solver/core-in-conservative-ec2-*.json")):
    p = subprocess.run([sys.executable, core],
                       input=json.dumps(json.load(open(f)), ensure_ascii=False),
                       capture_output=True, text=True)
    rows += json.loads(p.stdout)
t_rows = [r for r in rows if r["cur"].split(".")[0].startswith("t")]
for r in t_rows:
    print(f"  {r['rid']} {r['cur']:<12} verdict={r['verdict']}")
PY
```

Expected: T 系列行里，`required_vcpu` 超过 `cur_vcpu` 却因限流导致
`sus_cpu` 极低的那台，verdict 仍是 `已合理配置`。**这是预期结果，不是缺陷** ——
它需要 `CPUCreditBalance` 才能识别，属第二轮。把它记进验证记录，防止有人以为
本轮已覆盖全部「规格不足」。

- [ ] **Step 5: 三条安全自检 + 公开仓库敏感信息扫描**

Run: Task 2 Step 5 的三条 `grep` 自检。
Expected: 三行 `CLEAN`

```bash
cd ~/git/panlm-skills && git diff main...HEAD -U0 -- aws-rightsizing | grep '^+' \
  | grep -vE '^\+\+\+' \
  | grep -nE '[0-9]{12}|i-0[0-9a-f]{6,}|vol-0[0-9a-f]|snap-0[0-9a-f]|aws-(stg|pt|uat|sit|prod)-|/Users/|/home/|hk-(staging|situat)' \
  | grep -v '123456789012' || echo "CLEAN: no sensitive identifiers in diff"
```
Expected: `CLEAN: no sensitive identifiers in diff`

- [ ] **Step 6: 汇总验证记录**

整理成一段附在 PR 描述里，至少覆盖：9 个测试文件的通过数、
`test_fail_closed_contracts` 由 16 升到 18、`test_regression_fleet` 锚定值与
fixture 均未改、两条新测试的反向半齐备、真实回放的 `route1` 零变化与
`upsize-candidate` 行数（两支机队分别记）、P4 边界确认、三条自检 `CLEAN`、
敏感信息扫描 `CLEAN`。

---

## Self-Review

**Spec coverage:**

| spec 条目 | 落在哪个 task |
|---|---|
| C1 verdict 三分支、顺序不可调换 | Task 1 Step 5（含 `downsize` 分支的注释说明为何先查候选） |
| C2 持续项单独算、不复用 `rv`/`rg`、无内存数据不参与 | Task 1 Step 5 的 `rv_sus` / `rg_sus`；Task 1 Step 1 的反向半 ③ |
| C3 两侧 blocker | Task 1 Step 5 的 `insert(0, ...)` 与 `append(...)`；Task 1 Step 1/Step 3 的断言 |
| C4 `report-template.md` 产出方归属 | Task 2 Step 1 |
| E 通则 + 已知成员清单 | Task 2 Step 3 |
| 改动清单里的 `SKILL.md` EC2 一节 | Task 2 Step 2 |
| 改动清单里的 `docs/README.md` | Task 2 Step 4（spec 行已随 spec 提交，此处补 plan 行） |
| 测试影响：新增两条 + 各自反向半 | Task 1 Step 1 / Step 3；Task 3 Step 2 机械校验 |
| 测试影响：既有测试改 fixture 不改断言 | Task 1 Step 7 |
| 测试影响：回归 fixture 与锚定值不改 | Global Constraints + Task 1 Step 8 的 `git diff --quiet` |
| 验证方式 1（9 文件全绿） | Task 3 Step 1 |
| 验证方式 2（反向半成立） | Task 3 Step 2 |
| 验证方式 3（真实回放，四条口径逐值不变） | Task 3 Step 3（脚本内断言 `excluded` 与无节省额） |
| 验证方式 4（仅峰值项超的行仍「已合理配置」且带 blocker） | Task 1 Step 3 的单元测试 + Task 3 Step 3 的 verdicts 计数 |
| 验证方式 5（P4 边界未越过） | Task 3 Step 4 |
| 验证方式 6（三条自检 `CLEAN`） | Task 2 Step 5、Task 3 Step 5 |
| 「明确不做」各条 | Global Constraints 已收；`eval_rds` / `eval_elasticache` / `eval_msk` / `CPUCreditBalance` 未出现在任何 Files 里 |
| 「后续」第二、三轮 | **不在本 plan 范围**，spec 已声明各自独立 |

**Placeholder scan:** 无 TBD / TODO / 「类似 Task N」/ 「适当处理错误」。
唯一占位是 Task 3 Step 3 与 Step 4 的 `RAW=<某份既有交付>/raw` —— 那份数据含真实
账号，按仓库纪律不能进版本库，必须由执行者在本机指定，已在两处就地说明。

**Type consistency:**
- `rv_sus` / `rg_sus` 在 Task 1 Step 5 定义，仅函数内使用，不进输出字典，
  故不影响 CSV 契约与 `tests/test_csv_contract.py` 的 DERIVED 集合。
- 复用的既有局部量：`cs`（当前机型 spec）、`sus_cpu` / `peak_cpu`、`mem_known`、
  `rv` / `rg`、`t`，全部在 `evaluate()` 内、赋值早于本段。
- 两条新测试函数名在 Task 1 Step 1 / Step 3 定义，`__main__` 列表与
  Task 3 Step 2 的校验脚本引用同样的名字。
- blocker 断言用的子串（`当前规格已不足` / `不产出升配目标机型` / `内存持续 p95` /
  `峰值项` / `持续项未超` / `不是升配判据`）与 Task 1 Step 5 的文案逐字一致。
- `_evaluate(res, t, **ctx_kw)` 与 `_ctx(..., specs=None, prices=None, cats=None,
  baseline=None)` 是上一轮已落地的签名，本轮两条新测试只用默认 fixture，
  不传 `ctx_kw`。
