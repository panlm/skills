# EC2 突发候选信用指标「不适用」修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `evaluate()` 先判「信用指标是否适用于当前机型」再判「是否缺失」，
使突发降配路线在非突发机型上重新可达，同时把回归 fixture 从不可能的输入改成真实输入。

**Architecture:** 一处两行的判据守卫（`cs["burst"] and sc is None`），与
`eval_rds()` 里已有的 `_rds_is_burstable` 守卫同构。测试侧把「当前机型是 T 系列」
与「当前机型非突发」拆成两条独立回归，并给测试辅助函数加局部 specs 注入能力，
避免往共享 `SPECS` 加机型而静默改掉邻居测试的断言。

**Tech Stack:** Python 3（标准库，无第三方依赖）；测试为可独立执行的脚本
（`python3 tests/test_xxx.py`），非 pytest 驱动。

**Spec:** [`docs/specs/2026-09-10-burstable-credit-not-applicable-design.md`](../specs/2026-09-10-burstable-credit-not-applicable-design.md)

## Global Constraints

- **本 skill 只读。** 不得引入任何 mutating AWS 调用，不得引入 `ce:*` / 账单 API。
- **阈值唯一真值源是 `references/thresholds.json`。** 判据里不得写死阈值数值，
  散文文档不得复述数值，只能引用键名。
- **`references/*.json` 或 `references/core.py` 改动后必须跑全部 9 个测试文件**：
  `for t in tests/test_*.py; do python3 "$t" || exit 1; done`
- **`tests/test_regression_fleet.py` 的锚定值（`route1_nb` / `route2_max` /
  `MEM_FLOOR_OFF_ROUTE2` / `WITHDRAWN_ROUTE2_20260904`）本次一个都不许改。**
  本次改动对该 fixture 行为等价，若断言崩了说明实现错了，不是基线过期。
- **公开仓库。** 提交内容里不得出现真实账号 ID、实例 ID、资源名、profile 名、
  本机绝对路径。占位账号一律 `123456789012`。
- **不改 `eval_rds()`。** 它已经是对的，本次只让 EC2 侧与它同构。
- **不改 `SKILL.md` 的 EC2 突发规则正文** —— 它写的是「当前已是 T 系列且 `> 0`」，
  与本次裁定一致。

---

### Task 1: 判据守卫 + 抑制测试拆分

**Files:**
- Modify: `tests/test_fail_closed_contracts.py`（`_ctx` / `_evaluate` 签名；
  新增 T 系列 fixture 常量；替换 `test_missing_surplus_credits_suppresses_the_burstable_candidate`；
  新增一条测试；更新 `__main__` 的 `tests` 列表）
- Modify: `references/core.py:256-260`
- Test: `tests/test_fail_closed_contracts.py`

**Interfaces:**
- Consumes: `core.evaluate(res, ctx)`、`core.load_thresholds(profile)`；
  测试文件已有的模块级常量 `SPECS` / `PRICES` / `CATS` / `BASELINE` / `RES`。
- Produces: `_ctx(t, resources, specs=None, prices=None, cats=None, baseline=None)`
  与 `_evaluate(res, t, **ctx_kw)` 两个扩展签名，Task 2 之后的测试可复用；
  判据行为契约：`cs["burst"] is False` 时 `surplus_credits` 缺失**不**抑制突发候选。

- [ ] **Step 1: 给 `_ctx` / `_evaluate` 加局部 specs 注入能力（纯重构）**

把 `tests/test_fail_closed_contracts.py` 里现有的 `_ctx` 与 `_evaluate` 整体替换成：

```python
def _ctx(t, resources, specs=None, prices=None, cats=None, baseline=None):
    """构造 evaluate() 的 ctx。四个 fixture 参数缺省用模块级共享常量。

    允许传局部 specs，是为了让「当前机型是 T 系列」这类被测形态有自己的
    候选池，而不必往共享 SPECS 里加机型 —— 加进去会给其他复用同一份 SPECS
    的测试引入一个新的更便宜候选，静默改掉既有断言。
    """
    specs = SPECS if specs is None else specs
    ctx = {"thresholds": t, "specs": specs,
           "prices": PRICES if prices is None else prices,
           "baseline_pct": BASELINE if baseline is None else baseline,
           "categories": CATS if cats is None else cats,
           "offerings": [s["t"] for s in specs], "legacy_families": [],
           "resources": resources}
    ctx["_specs_by_type"] = {s["t"]: s for s in specs}
    ctx["_offerings"] = set(ctx["offerings"])
    ctx["_legacy"] = set()
    return ctx


def _evaluate(res, t, **ctx_kw):
    """跑 evaluate()，把异常翻译成指名缺陷的断言失败。

    这些分支坏掉时多半是「None 参与算术」而不是「结论错」，裸抛的
    TypeError 不说明是哪个守卫没了。
    """
    try:
        return core.evaluate(res, _ctx(t, [res], **ctx_kw))
    except Exception as e:
        raise AssertionError(
            f"{res['rid']} 未在早退分支短路，落进了选型算术并抛 {type(e).__name__}: {e}")
```

- [ ] **Step 2: 跑全套确认重构没改行为**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || echo "FAIL $t"; done`
Expected: 9 个文件全绿（`test_fail_closed_contracts.py` 仍是 `15/15 passed`）。
所有既有调用都是 `_ctx(t, [...])` / `_evaluate(res, t)`，新参数全部走缺省。

- [ ] **Step 3: 提交重构**

```bash
git add tests/test_fail_closed_contracts.py
git commit -m "test(aws-rightsizing): let _ctx take local specs fixtures

Injecting a per-test spec pool avoids adding instance types to the shared
SPECS constant, which would hand neighbouring tests a new cheaper candidate
and silently move their assertions."
```

- [ ] **Step 4: 把抑制测试改成以 T 系列当前机型为被测对象（含 runner 列表改名，一次改完）**

> 函数改名必须与末尾 `__main__` 的 `tests` 列表同批修改 —— 只改函数定义会让
> 该文件直接 `NameError`，中间态跑不了。

在 `tests/test_fail_closed_contracts.py` 的模块级常量区（`CACHE` 定义之后）加入：

```python
# 「当前机型已是 T 系列」专用池：抑制分支只在这种形态下才该触发。
# 不并入共享 SPECS —— t3.xlarge 会成为 RES(m5.xlarge) 的一个新候选。
T_SPECS = [{"t": "t3.xlarge", "vcpu": 4, "gib": 16, "burst": True,
            "arch": "x86_64", "store": False, "ebs": 86.875, "curgen": True},
           {"t": "t3.large", "vcpu": 2, "gib": 8, "burst": True,
            "arch": "x86_64", "store": False, "ebs": 86.875, "curgen": True}]
T_PRICES = {"t3.xlarge|RunInstances": 0.1664, "t3.large|RunInstances": 0.0832}
T_CATS = {"t3.xlarge": "General purpose", "t3.large": "General purpose"}
T_BASELINE = {"t3.xlarge": 0.4, "t3.large": 0.3}
T_FIXTURE = dict(specs=T_SPECS, prices=T_PRICES, cats=T_CATS, baseline=T_BASELINE)
T_RES = {"rid": "i-T-11", "service": "ec2", "type": "t3.xlarge", "arch": "x86_64",
         "operation": "RunInstances", "sus_cpu": 10, "peak_cpu": 25,
         "sus_mem": 20, "peak_mem": 35, "ebs_need": 5,
         "cpu_n": 243, "metric_coverage": []}
```

把整个 `test_missing_surplus_credits_suppresses_the_burstable_candidate` 函数
替换成：

```python
def test_missing_surplus_credits_suppresses_burst_only_on_burstable_current_type():
    """当前机型已是 T 系列时，信用指标缺失才是真缺失 ⇒ 保持 fail-closed。

    被测对象必须是 burstable 当前机型（t3.xlarge）。此测试原先拿 m5.xlarge
    做被测对象，把「不适用」当成「缺失」的缺陷写成了契约 —— 见
    docs/specs/2026-09-10-burstable-credit-not-applicable-design.md 的 P1。

    第二半是这个测试的关键：同一台机器把 surplus_credits 给成 0 时确实能选出
    t3.large。若只断言"缺失时 burst is None"，候选池本来就空也照样通过，
    删掉抑制分支不会被发现。
    """
    t = core.load_thresholds("aggressive")
    suppressed = _evaluate(dict(T_RES, surplus_credits=None), t, **T_FIXTURE)
    assert suppressed["burst"] is None, (
        "当前机型已是 T 系列且信用指标缺失时不得产出 burstable 建议，"
        f"却选出了 {suppressed['burst']}")
    assert "CPUSurplusCreditsCharged 缺失" in suppressed["burst_na"], suppressed
    assert suppressed.get("b_save_mo") is None, suppressed
    allowed = _evaluate(dict(T_RES, surplus_credits=0), t, **T_FIXTURE)
    assert allowed["burst"] is not None and allowed["burst"]["t"] == "t3.large", \
        f"候选池里本应有 t3.large，抑制测试才有意义：{allowed['burst_na']}"
    assert allowed["b_save_mo"] == 60.74, allowed["b_save_mo"]
```

同批把末尾 `__main__` 的 `tests` 列表里这一行：

```python
             test_missing_surplus_credits_suppresses_the_burstable_candidate,
```

改成新函数名：

```python
             test_missing_surplus_credits_suppresses_burst_only_on_burstable_current_type,
```

- [ ] **Step 5: 跑这一条，确认在未修复的 core 上就通过**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py`
Expected: `15/15 passed`，其中含
`✓ test_missing_surplus_credits_suppresses_burst_only_on_burstable_current_type`

这条**必须**在改 `core.py` 之前就通过 —— 它锁住的是要**保留**的行为（T 系列
侧的 fail-closed）。若它此刻失败，说明局部 fixture 参数没走通，先修 fixture，
不要动 `core.py`。

- [ ] **Step 6: 写新测试 —— 非突发当前机型缺信用指标仍须给候选（含 runner 注册）**

紧接上一条测试之后加入：

```python
def test_non_burstable_current_type_gets_a_burstable_candidate_without_credits():
    """非突发当前机型不发布信用指标 ⇒ 「不适用」，不得 fail-closed。

    CPUSurplusCreditsCharged 只有 T 系列发布（metrics-catalog.md 实测记录：
    非 T 实例 0 台）。对 m5 / c6i / c7i 这类机型要求它，会让突发降配路线在
    生产上永久不可达 —— 实测一支 29 台机队里 25 台被压掉，另有 3 行被误判成
    「已合理配置」。eval_rds 已用 _rds_is_burstable 做了这个区分，EC2 侧漏了。

    第二半锁住等价性：字段缺失与字段为 0，对非突发当前机型必须得出同一结论。
    这条等价性是 regression fixture 能从不可能的 0 改成真实的 null 而锚定值
    不变的依据。
    """
    t = core.load_thresholds("aggressive")
    base = dict(RES, rid="i-T-12", cpu_n=243, sus_cpu=10, peak_cpu=25)
    absent = _evaluate(dict(base, surplus_credits=None), t)
    assert absent["burst"] is not None, (
        "非突发当前机型的信用指标结构性不存在，属「不适用」，不得因此压掉"
        f"突发候选：burst_na={absent['burst_na']!r}")
    assert absent["burst"]["t"] == "t3.large", absent["burst"]
    assert absent["burst_na"] is None, absent["burst_na"]
    zero = _evaluate(dict(base, surplus_credits=0), t)
    assert zero["burst"] == absent["burst"], (
        f"缺失与 0 对非突发当前机型必须等价：{zero['burst']} vs {absent['burst']}")
    assert zero["b_save_mo"] == absent["b_save_mo"] == 79.42, \
        (zero["b_save_mo"], absent["b_save_mo"])
```

同批在 `__main__` 的 `tests` 列表里，紧跟上一步那行之后插入：

```python
             test_non_burstable_current_type_gets_a_burstable_candidate_without_credits,
```

- [ ] **Step 7: 跑测试，确认新测试失败、其余全过**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py`
Expected: `15/16 passed`，唯一失败的是
`✗ test_non_burstable_current_type_gets_a_burstable_candidate_without_credits`，
失败信息含
`非突发当前机型的信用指标结构性不存在，属「不适用」，不得因此压掉突发候选：burst_na='CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用'`

- [ ] **Step 8: 修判据（两行）**

`references/core.py` 里把这三行：

```python
    sc = res.get("surplus_credits")
    if sc is None:
        out["burst_na"] = "CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用"
    elif sc > 0:
```

替换成：

```python
    # 先判「适用性」再判「缺失」。CPUSurplusCreditsCharged 只有 T 系列发布，
    # 对非突发当前机型它是「不适用」而不是「缺失」——
    # 无条件 fail-closed 会让突发降配路线在生产上永久不可达（实测 25/29 台）。
    # 与 eval_rds 的 _rds_is_burstable 守卫同构。
    sc = res.get("surplus_credits")
    if cs["burst"] and sc is None:
        out["burst_na"] = "CPUSurplusCreditsCharged 缺失，无法确认是否已超额消费信用"
    elif sc is not None and sc > 0:
```

`sc is not None` 不可省：`None > 0` 抛 `TypeError`，会让全部非突发机型的行崩掉。

`> 0` 分支**故意保留对所有机型生效** —— 非突发机型上出现 `> 0` 只可能是采集侧
把别的资源的序列贴错了行，此时抑制突发候选是安全反应，代价为零。

- [ ] **Step 9: 跑测试，确认全绿**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py`
Expected: `16/16 passed`

Run: `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || echo "FAIL $t"; done`
Expected: 9 个文件全绿。**`test_regression_fleet.py` 必须仍是 `14/14 passed` 且
锚定值未改** —— fixture 现在的 `surplus_credits: 0` 在修复前后行为等价。

- [ ] **Step 10: 提交**

```bash
git add references/core.py tests/test_fail_closed_contracts.py
git commit -m "fix(aws-rightsizing): treat absent burst credits as N/A on non-burstable types

CPUSurplusCreditsCharged is published only by T-family instances. evaluate()
fail-closed the burstable candidate whenever the field was absent, without
first asking whether the current instance type can publish it at all, so the
burstable route was unreachable for every non-burstable instance. Guard the
missing-value branch on cs[\"burst\"], mirroring _rds_is_burstable.

The > 0 branch stays unguarded on purpose: a positive value on a
non-burstable type means the collector mis-mapped a series, and suppressing
the burstable candidate is the safe response to bad input.

Splits the suppression test in two - one subject that is a T-family current
type (keeps failing closed) and one that is not (must get a candidate). The
old test used m5.xlarge as its subject and so encoded the defect."
```

---

### Task 2: 回归 fixture 改成真实输入

**Files:**
- Modify: `tests/fixtures/regression-fleet.json`（12 台非突发机型的 `surplus_credits`）
- Test: `tests/test_regression_fleet.py`（断言值不动）

**Interfaces:**
- Consumes: Task 1 落地的判据行为（缺失与 0 对非突发机型等价）。
- Produces: 一份能真正抓到「把不适用当缺失」这类缺陷的回归 fixture。

- [ ] **Step 1: 先记录改之前的基线，供事后对账**

Run:
```bash
cd aws-rightsizing && python3 tests/test_regression_fleet.py | tail -2
```
Expected: `14/14 passed`（Task 1 已落地）

- [ ] **Step 2: 把非突发机型的 `surplus_credits` 改成 `null`**

用 fixture 自带的 `specs[].burst` 驱动，不要手工挑 rid：

```bash
cd aws-rightsizing && python3 - <<'PY'
import json
p = "tests/fixtures/regression-fleet.json"
d = json.load(open(p))
byt = {s["t"]: s for s in d["specs"]}
n = 0
for r in d["resources"]:
    t = r.get("type")
    if t and byt.get(t) and not byt[t]["burst"] and r.get("surplus_credits") == 0:
        r["surplus_credits"] = None
        n += 1
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
print("nulled", n)
PY
```
Expected: `nulled 12`（13 台里只有 `i-EX-01` 是 `t3.medium`，保持 `0`）

- [ ] **Step 3: 在 fixture 的 `_comment` 里写明为什么是 `null`**

把 `tests/fixtures/regression-fleet.json` 顶层 `_comment` 的字符串末尾追加一句
（保持它原有内容不变，只在结尾接上）：

```
非突发机型的 surplus_credits 一律为 null：CPUSurplusCreditsCharged 只有 T 系列发布，真实采集对这些机型不可能产出 0。此前这里填 0，让「把不适用当缺失」的判据缺陷绕过了整套基线，见 docs/specs/2026-09-10-burstable-credit-not-applicable-design.md 的 P4。
```

- [ ] **Step 4: 跑回归测试，确认锚定值一个没动**

Run: `cd aws-rightsizing && python3 tests/test_regression_fleet.py`
Expected: `14/14 passed`。**若任何锚定值报偏离，不要改锚定值** —— 说明 Task 1
的等价性不成立，回去查 `core.py`。

- [ ] **Step 5: 反向验证 —— 证明这份 fixture 现在真的能抓到该缺陷**

在 `/tmp` 的副本里把 `core.py` 退回改动前，再跑同一份新 fixture：

```bash
cd aws-rightsizing && rm -rf /tmp/rf-reverse && mkdir -p /tmp/rf-reverse \
  && cp -a references tests /tmp/rf-reverse/ \
  && rm -rf /tmp/rf-reverse/references/__pycache__ /tmp/rf-reverse/tests/__pycache__ \
  && git show HEAD~1:aws-rightsizing/references/core.py > /tmp/rf-reverse/references/core.py \
  && (cd /tmp/rf-reverse && python3 tests/test_regression_fleet.py 2>&1 | tail -8)
```

Expected: **不是**全绿。至少 `test_regression_totals_both_profiles` 失败，
实测 `route2_max` 由 `668.85` 掉到 `548.98`、`verdicts` 由 `{'downsize': 13}`
变成 `{'downsize': 12, '已合理配置': 1}`，而 `route1_nb` 仍是 `527.15`。
（另外 `test_mem_reduction_floor_is_live_and_respected` 与
`test_legacy_families_md_graviton2_cost_is_reproducible` 也会失败，它们是派生量。
实测总计 `10/14 passed`。）

若这一步全绿，说明 fixture 仍然抓不到缺陷，Step 2 没生效 —— 回去检查。

**注意** `git show HEAD~1:...` 假定 Task 1 是上一个提交。若中间有别的提交，
换成 Task 1 之前那个 commit 的 sha。

- [ ] **Step 6: 提交**

```bash
git add tests/fixtures/regression-fleet.json
git commit -m "test(aws-rightsizing): give the regression fleet realistic credit inputs

The fixture set surplus_credits to 0 on 12 non-burstable instances. Real
collection can never produce that value - the metric is T-family only - and
the impossible 0 was the only thing keeping the anchored baseline from
noticing that production suppressed every burstable candidate.

Anchored totals are unchanged: absent and 0 are equivalent for non-burstable
types once the judgment is correct. Against the previous core.py this same
fixture fails 4 of 14 assertions, which is the signal it should have carried
all along."
```

---

### Task 3: 契约与文档同步

**Files:**
- Modify: `references/cli-recipes.md`（`surplus_credits` 输入契约行）
- Modify: `references/metrics-catalog.md`（EC2 的 `CPUSurplusCreditsCharged` 行）
- Modify: `references/core.py`（`_rds_is_burstable` docstring 末行）
- Modify: `SKILL.md`（易错项速查追加一行）
- Modify: `docs/README.md`（plans 表加本 plan）

**Interfaces:**
- Consumes: Task 1 的判据行为。
- Produces: 组装侧的明确契约 —— 非突发机型该字段留空即正确、不得补 0。

- [ ] **Step 1: 改 `references/cli-recipes.md` 的输入契约行**

把这一行：

```
| `surplus_credits` | 否 | agg 中 `CPUSurplusCreditsCharged` / `Maximum` 的 `max`，**三档取最大** | 抑制 burstable 侧（不能断言"没超额"） |
```

替换成：

```
| `surplus_credits` | T 机型必填 | agg 中 `CPUSurplusCreditsCharged` / `Maximum` 的 `max`，**三档取最大**。**非突发机型该序列结构性不存在，字段留空即正确** —— `core.py` 用 spec 的 `burst` 标志区分「不适用」与「缺失」。**不要补 0**：补 0 会让「当前机型是 T 系列而序列真的采失败」被当成「已确认未超额」放行，那是反方向的错且无任何信号 | **当前机型是 T 系列时**抑制 burstable 侧（不能断言"没超额"）；非突发机型不受影响 |
```

- [ ] **Step 2: 改 `references/metrics-catalog.md` 的 EC2 指标行**

把这一行（EC2 一节，注意 RDS 一节有同名指标但文案不同，不要改错）：

```
| CPUSurplusCreditsCharged | Maximum | blocker（>0 抑制 burstable 选项） | 已实测 |
```

替换成：

```
| CPUSurplusCreditsCharged | Maximum | blocker（**当前机型已是 T 系列**且 >0 ⇒ 抑制 burstable 选项）；**仅 `t*` 发布**，非 burstable 缺失属「不适用」不是「缺失」，判据不走 fail-closed | 已实测 |
```

- [ ] **Step 3: 订正 `references/core.py` 的 `_rds_is_burstable` docstring**

把这一行：

```python
    EC2 侧用 spec["burst"] 做同一个区分，RDS 侧此前漏了。
```

替换成：

```python
    EC2 侧的 evaluate() 用 cs["burst"] 做同一个区分。注意：2026-09-04 记录
    J2 时曾断言「EC2 侧已做了这个区分」，那句话当时并不成立 —— EC2 侧同样
    无条件 fail-closed，直到 2026-09-10 才补上。别再凭这类断言跳过复查。
```

- [ ] **Step 4: `SKILL.md` 易错项速查追加一行**

在易错项表最后一行（`| **给 `agg.jq` 加了 `full-window` 档后仍按 bucket 全量求和** | ...`）
之后、`## references` 之前插入：

```
| **「仅某子集机型发布」的指标当成「缺失」fail-closed** | `CPUSurplusCreditsCharged` 只有 T 系列发布，非突发机型该序列结构性不存在。无条件卡 `is None` 会让**突发降配路线在生产上永久不可达**（实测 29 台机队里 25 台被压掉，3 行误判成「已合理配置」），且 `burst_na` 让客户去补一个不可能存在的指标。RDS 侧同一缺陷修于 2026-09-04，EC2 侧因文档误称「已做区分」而漏到 2026-09-10 | **先判适用性，再判缺失**：`if cs["burst"] and sc is None`（EC2）/ `_rds_is_burstable()`（RDS）。回归 fixture 必须用真实值（非突发机型填 `null`），填 0 会让整套基线为一个不可能的输入背书 |
```

- [ ] **Step 5: `docs/README.md` 的 plans 表加一行**

在 plans 表最后一行之后加入：

```
| [2026-09-10-burstable-credit-not-applicable.md](./plans/2026-09-10-burstable-credit-not-applicable.md) | 让 `evaluate()` 先判信用指标是否适用于当前机型再判是否缺失,恢复非突发机型的突发降配路线;回归 fixture 改用真实输入 |
```

- [ ] **Step 6: 跑测试与自检**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || echo "FAIL $t"; done`
Expected: 9 个文件全绿。`test_no_duplicated_constants.py` 尤其要过 —— 它防散文
复述 `thresholds.json` 的数值，上面新增的文案只提键名与实测台数，不含阈值。

Run（在 `aws-rightsizing/` 下，三条都必须打印 `CLEAN`）：
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

- [ ] **Step 7: 提交**

```bash
git add references/cli-recipes.md references/metrics-catalog.md references/core.py \
        SKILL.md docs/README.md
git commit -m "docs(aws-rightsizing): state that absent burst credits are N/A, not missing

Spells out in the collection contract that non-burstable instance types
cannot publish CPUSurplusCreditsCharged, so leaving the field absent is
correct and filling a 0 is harmful - a 0 would let a genuine collection
failure on a T-family instance pass as \"confirmed not overspent\".

Corrects the _rds_is_burstable docstring, which repeated the 2026-09-04
claim that the EC2 side already made this distinction. It did not, and that
sentence is why nobody rechecked it."
```

---

### Task 4: 交付前门禁与真实数据对账

**Files:**
- 无仓库改动。产出是一份验证记录，贴进 PR / 交付说明。

**Interfaces:**
- Consumes: Task 1–3 的全部改动。
- Produces: 可核对的验证证据，对应 spec「验证方式」五条。

- [ ] **Step 1: 全量测试门禁**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do echo "-- $t"; python3 "$t" | tail -1; done`
Expected: 9 个文件全绿；`test_fail_closed_contracts.py` 为 `16/16 passed`
（原 15，拆一条为两条）；`test_regression_fleet.py` 为 `14/14 passed`。

- [ ] **Step 2: 确认新测试的「第二半」不是空断言**

Run:
```bash
cd aws-rightsizing && python3 - <<'PY'
import re, pathlib
src = pathlib.Path("tests/test_fail_closed_contracts.py").read_text()
for name, needle in (
        ("test_missing_surplus_credits_suppresses_burst_only_on_burstable_current_type",
         'allowed["burst"]["t"] == "t3.large"'),
        ("test_non_burstable_current_type_gets_a_burstable_candidate_without_credits",
         'absent["burst"]["t"] == "t3.large"')):
    body = src.split(f"def {name}(")[1].split("\ndef ")[0]
    assert needle in body, f"{name} 缺少非空候选断言：{needle}"
    print("OK", name)
PY
```
Expected: 两行 `OK`。这一步防的是「候选池本来就空也照样通过」。

- [ ] **Step 3: 真实数据回放对账（数据在仓库外）**

设 `RAW` 指向一份既有交付的 `raw/` 目录（含 `solver/core-in-*-ec2-*.json`）。
该目录含真实账号与资源 ID，**不得提交，也不得把逐行结果贴进仓库**。

```bash
RAW=<某份既有交付>/raw            # 例如上一轮 report_output 的 raw
CORE=$PWD/references/core.py
for prof in conservative aggressive; do
  python3 - "$RAW" "$CORE" "$prof" <<'PY'
import json, subprocess, sys, glob, pathlib
raw, core, prof = sys.argv[1], sys.argv[2], sys.argv[3]
rows = []
for f in sorted(glob.glob(f"{raw}/solver/core-in-{prof}-ec2-*.json")):
    ctx = json.load(open(f))
    p = subprocess.run([sys.executable, core], input=json.dumps(ctx, ensure_ascii=False),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    rows += json.loads(p.stdout)
ds = [r for r in rows if r.get("bucket") == "downsize"]
r1 = round(sum(r.get("nb_save_mo") or 0 for r in ds), 2)
r2 = round(sum(max(r.get("nb_save_mo") or 0, r.get("b_save_mo") or 0) for r in ds), 2)
print(f"{prof}: downsize={len(ds)} route1={r1} route2={r2} "
      f"burst候选={sum(1 for r in rows if r.get('burst'))}")
PY
done
```

Expected（与该份交付的旧 `totals-<profile>.json` 对账）：
- **`route1` 与旧值逐值相同** —— 这是本次改动爆炸半径的核心断言。
- `route2` 高于旧值，差额等于原先被压掉的突发候选。
- `burst候选` 数量由「仅 T 系列台数」上升到「有合规 T 候选的台数」。
- 出现若干行由 `已合理配置` 变 `downsize`（无非突发候选但有突发候选的那些）。

若 `route1` 有任何变化 ⇒ **停止**，说明改动漏进了非突发路径。

- [ ] **Step 4: 安全自检三条 `CLEAN`**

Run: Task 3 Step 6 的三条 `grep` 自检。
Expected: 三行 `CLEAN`

- [ ] **Step 5: 公开仓库敏感信息扫描**

```bash
cd aws-rightsizing && git diff --stat main...HEAD && \
git diff main...HEAD -U0 | grep -E '^\+' | \
  grep -nE '[0-9]{12}|i-0[0-9a-f]{6,}|vol-0|snap-0|aws-(stg|pt|uat|sit|prod)-|/Users/|/home/|[A-Za-z]:\\\\' \
  | grep -v '123456789012' || echo "CLEAN: no sensitive identifiers in diff"
```
Expected: `CLEAN: no sensitive identifiers in diff`

- [ ] **Step 6: 汇总验证记录**

把 Step 1–5 的实际输出整理成一段，附在 PR 描述里。至少覆盖：
9 个测试文件的通过数、`test_regression_fleet` 锚定值未改、反向验证的
`10/14 passed` 与 `route2_max 668.85 → 548.98`、真实回放的 `route1` 零变化、
三条自检 `CLEAN`、敏感信息扫描 `CLEAN`。

---

## Self-Review

**Spec coverage:**

| spec 条目 | 落在哪个 task |
|---|---|
| C1 判据两行 | Task 1 Step 9 |
| C1「`> 0` 分支保留对所有机型」的理由 | Task 1 Step 9 注释 + 提交信息 |
| C2 采集契约「留空即正确 / 不要补 0」 | Task 3 Step 1 |
| C3 fixture 真实化 + 锚定值不变 | Task 2 Step 2–4 |
| C4 docstring 订正、不改历史 spec | Task 3 Step 3（`docs/specs/2026-09-04-*` 未出现在任何 Files 里） |
| 测试影响：抑制测试拆两条 | Task 1 Step 4、Step 6 |
| 测试影响：不动共享 `SPECS` | Task 1 Step 1 的 `_ctx` 注入 + Step 4 的 `T_SPECS` 局部常量 |
| 改动清单里的 `metrics-catalog.md` | Task 3 Step 2 |
| 改动清单里的 `SKILL.md` 易错项 | Task 3 Step 4 |
| 改动清单里的 `docs/README.md` | Task 3 Step 5（spec 行已随 spec 提交，此处补 plan 行） |
| 验证方式 1（9 文件全绿） | Task 4 Step 1 |
| 验证方式 2（新测试两半都有意义） | Task 4 Step 2 |
| 验证方式 3（真实回放，route1 不变） | Task 4 Step 3 |
| 验证方式 4（fixture 反向验证） | Task 2 Step 5 |
| 验证方式 5（三条自检 `CLEAN`） | Task 3 Step 6、Task 4 Step 4 |
| 「明确不做」各条 | Global Constraints 已收；`eval_rds` 与 EC2 规则正文未出现在任何 Files 里 |
| spec「后续」的通则 | **不在本 plan 范围**，spec 已声明另起一份 |

**Placeholder scan:** 无 TBD / TODO / 「类似 Task N」/ 「适当处理错误」。
唯一的占位是 Task 4 Step 3 的 `RAW=<某份既有交付>/raw` —— 那份数据含真实账号，
按 spec 与仓库纪律不能进版本库，必须由执行者在本机指定，已在该步说明。

**Type consistency:**
- `_ctx(t, resources, specs=None, prices=None, cats=None, baseline=None)` 与
  `_evaluate(res, t, **ctx_kw)` 的关键字名在 Task 1 Step 1 定义，
  Step 4 的 `T_FIXTURE = dict(specs=..., prices=..., cats=..., baseline=...)` 逐字一致。
- 两个新测试函数名在 Step 4 / Step 6 定义，Step 7 的 `tests` 列表与
  Task 4 Step 2 的检查脚本引用的是同样的名字。
- `cs["burst"]` 用下标而非 `.get()`：`cs` 来自 `specs_by_type`，
  `references/*/ec2-types.json` 与测试 `SPECS` 都必带 `burst` 键；
  缺键应当 `KeyError` 而不是静默当 `False`（当 `False` 会让缺 spec 的机型
  绕过 T 系列侧的 fail-closed）。
