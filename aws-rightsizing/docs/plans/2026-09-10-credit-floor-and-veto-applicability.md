# 信用余额下限 + 否决项适用性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `CPUCreditBalance` 下限成为真判据（被限流的实例不再显形为「闲置」），
并把 `ReplicationLag` 的缺失处理从无条件 fail-open 改为按副本存在性分流。

**Architecture:** 新增一个共用判定函数 `_credit_exhausted()`（按「占窗口内观测最大
余额的百分比」判，避免依赖 RDS 不存在的 baseline 静态表）与一个阈值键。EC2 侧在
候选池**之前**算出 `credit_exhausted`，触底时压掉两列候选并在 verdict 链首位产出
`upsize-candidate`。RDS 侧同构，并顺带把 `eval_rds` 的分支顺序对齐到
`eval_msk` / `eval_elasticache` 的既定原则。ElastiCache 侧用 `has_replica`
（从节点 id 的分片-成员结构推出，零新增 API）分流 `ReplicationLag` 的缺失。

**Tech Stack:** Python 3（标准库）；测试为可独立执行脚本（`python3 tests/test_xxx.py`）。

**Spec:** [`docs/specs/2026-09-10-credit-floor-and-veto-applicability-design.md`](../specs/2026-09-10-credit-floor-and-veto-applicability-design.md)

## Global Constraints

- **本 skill 只读。** 不引入 mutating AWS 调用、不引入 `ce:*` / 账单 API、
  **不引入 `describe-replication-groups`**（副本存在性从现有 inventory 推出）。
- **阈值唯一真值源是 `references/thresholds.json`。** 判据与 blocker 文案里不得
  写死阈值数值，只能运行时 `t[...]` 插值。散文文档不得复述数值，只能引用键名。
- **`tests/test_regression_fleet.py` 的锚定值（`route1_nb` / `route2_max` /
  `MEM_FLOOR_OFF_ROUTE2` / `WITHDRAWN_ROUTE2_20260904`）与 `verdicts` /
  `buckets` 计数一律不改。** 试装已验证：给那台 burstable 补健康信用值后
  回归回到 14/14、锚定值逐值未动。落地后任一项变化都视为实现错误。
- **`route1` / `route2` / 桶 B / 采集侧四条口径与分母必须逐值不变。**
- **不为 ElastiCache / MSK 新增信用判据**（它们的输入里没有 burstable 形态字段）。
- **不产出升配的目标机型。**
- **不解决窗口内规格变更导致的采样混合**（第四轮）；本轮只让它可见。
- **公开仓库。** 提交内容不得出现真实账号 ID、实例 ID、资源名、profile 名、
  本机绝对路径。占位账号一律 `123456789012`。
- **不推 origin。**

---

### Task 1: 阈值键 + `_credit_exhausted()` + EC2 侧

**Files:**
- Modify: `references/thresholds.json`（两个 profile 各加一键）
- Modify: `references/core.py`（`CLASS_CHANGED_NOTE`、`_credit_exhausted()`、
  `evaluate()` 三处）
- Modify: `tests/fixtures/regression-fleet.json`（唯一的 burstable 实例补两字段）
- Modify: `tests/test_fail_closed_contracts.py`（`T_RES` 补两字段 + 新增一条测试）
- Test: `tests/test_fail_closed_contracts.py`、`tests/test_regression_fleet.py`

**Interfaces:**
- Consumes: `core.evaluate(res, ctx)`；`_ctx(t, resources, specs=None, prices=None,
  cats=None, baseline=None)` / `_evaluate(res, t, **ctx_kw)`；`T_SPECS` / `T_FIXTURE` /
  `T_RES`（第一轮已加，`T_RES["type"] == "t3.xlarge"`，burstable）。
- Produces: `CLASS_CHANGED_NOTE`（模块级常量，Task 2 复用）；
  `_credit_exhausted(cb_min, cb_max, t) -> bool`（Task 2 复用）；
  输入字段 `credit_balance_min` / `credit_balance_max`；
  阈值键 `credit_balance_floor_pct`。

- [ ] **Step 1: 加阈值键**

`references/thresholds.json` 里，**两个 profile** 的 `"msk_handler_idle_min": 0.7`
之后各加一行（注意给前一行补逗号）：

```json
      "msk_handler_idle_min": 0.7,
      "credit_balance_floor_pct": 10
```

取值 `10` 对两个 profile 相同 —— 「信用是否耗尽」是事实而非风险偏好，
与既有的 `rds_freeable_mem_floor_pct` / `redis_repl_lag_max_s` 同样两 profile 一致。

- [ ] **Step 2: 加共用常量与判定函数**

`references/core.py` 里，在 `def _eff_vcpu(spec, baseline_pct):` **之前**插入：

```python
CLASS_CHANGED_NOTE = (
    "当前机型非突发，却存在 CPU 信用序列 —— 说明**窗口内改过规格**。"
    "该余额测自另一个规格，不作为当前规格的否决依据；但本行的利用率百分比"
    "混合了两个规格的采样（需求量按当前核数反推），须人工复核")


def _credit_exhausted(cb_min, cb_max, t):
    """信用余额在窗口内是否触底。两个入参都必须非 None（由调用方守卫）。

    判「占窗口内观测最大余额的百分比」而不是「占信用上限」：上限
    = vcpu x baseline_pct x 1440，而 RDS 的 baseline 百分比**不在本 skill 的
    静态资产里**（baseline-pct.json 只覆盖 EC2 机型）。用观测最大值自归一化，
    EC2 与 RDS 共用一套算法，且不引入第二张静态表。
    实测分离度：触底 0.00%-0.14%，健康 85.07%-99.91%，中间无观测点。

    **不判 `cb_min == 0`。** Minimum 是逐小时最小值，真实耗尽时通常落到 0 但
    不保证——实测两台 RDS 的最小值是 0.79 / 0.70。把判据建在「恰好等于 0」上，
    会让余额在 0.3 附近徘徊的饿死实例逃掉，而那正是本判据要抓的一类。
    """
    if cb_max == 0:
        return True          # 整窗口恒为 0 = 彻底耗尽；同时兜住除零
    return cb_min <= cb_max * t["credit_balance_floor_pct"] / 100.0
```

- [ ] **Step 3: 给两份 fixture 补字段（否则后续步骤会红成一片，看不出真信号）**

`tests/test_fail_closed_contracts.py` 里 `T_RES` 的定义，把：

```python
         "sus_mem": 20, "peak_mem": 35, "ebs_need": 5,
         "cpu_n": 243, "metric_coverage": []}
```

替换成：

```python
         "sus_mem": 20, "peak_mem": 35, "ebs_need": 5,
         "credit_balance_min": 575.34, "credit_balance_max": 576.0,
         "cpu_n": 243, "metric_coverage": []}
```

（`RES` 是 `m5.xlarge`、非突发，**不需要**这两个字段 —— 加了反而会触发
「窗口内改过规格」的 blocker。）

`tests/fixtures/regression-fleet.json`：给**唯一的 burstable 实例**补健康余额。
用 `specs[].burst` 驱动，不要手工挑 rid：

```bash
cd aws-rightsizing && python3 - <<'PY'
import json
p = "tests/fixtures/regression-fleet.json"
d = json.load(open(p))
byt = {s["t"]: s for s in d["specs"]}
n = 0
for r in d["resources"]:
    if byt.get(r.get("type"), {}).get("burst"):
        r["credit_balance_min"] = 575.34
        r["credit_balance_max"] = 576.0
        n += 1
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
print("补了", n, "台 burstable")
PY
```
Expected: `补了 1 台 burstable`

同时在该 fixture 顶层 `_comment` 数组（**是数组，不是字符串**）末尾追加一条：

```
burstable 实例的 credit_balance_min/max 取健康值（余额几乎满格）：本机队没有信用耗尽的实例，锚定总额因此不受 credit_balance_floor_pct 影响。非突发机型不带这两个字段——CPUCreditBalance 只有 T 系列发布。
```

- [ ] **Step 4: 写失败测试 —— EC2 侧七态**

在 `tests/test_fail_closed_contracts.py` 的
`test_overspent_credits_suppress_the_burstable_candidate` **之前**插入：

```python
def test_credit_balance_floor_makes_a_throttled_instance_visible():
    """信用余额触底 ⇒ `upsize-candidate`，且必须压掉两列候选。

    CPUSurplusCreditsCharged 是个**窄**信号：只在 unlimited 模式且透支超期未偿还
    时为真。standard 模式触底只会被限流到基线、不产生 surplus 计费；unlimited
    模式 24 小时内偿还也不计费。两种情形下实例都已把持续需求跑到超出基线，
    而**限流会把 CPUUtilization 压住** —— 实测一台 t3.xlarge 余额跑到 0.00、
    surplus 四档全 0、cpu_p95 仅 1.62%，被报成「已合理配置」。

    压掉两列候选是本条的关键：不压掉就会对一台饿死的机器按被限流压低的持续值
    再推荐降一档，而 upsize-candidate 行带节省额还会破坏「该行不得有金额」的不变式。
    """
    t = core.load_thresholds("aggressive")
    hit = _evaluate(dict(T_RES, rid="i-C-01", credit_balance_min=0.0,
                         credit_balance_max=2304.0), t, **T_FIXTURE)
    assert hit["verdict"] == "upsize-candidate", hit["verdict"]
    assert hit["nonburst"] is None and hit["burst"] is None, hit
    assert hit["nb_save_mo"] is None and hit["b_save_mo"] is None, hit
    why = [b for b in hit["blockers"] if "信用余额窗口内触底" in b]
    assert why and "不产出升配目标机型" in why[0], hit["blockers"]

    # 反向：同一台机器给健康余额 ⇒ 不判规格不足（否则分不清规则生效与池子为空）
    ok = _evaluate(dict(T_RES, rid="i-C-02", credit_balance_min=490.0,
                        credit_balance_max=576.0), t, **T_FIXTURE)
    assert ok["verdict"] != "upsize-candidate", ok["verdict"]
    assert not [b for b in (ok.get("blockers") or []) if "信用余额" in b], ok

    # 整窗口恒为 0 ⇒ 彻底耗尽（同时是除零的兜底）
    zero = _evaluate(dict(T_RES, rid="i-C-03", credit_balance_min=0.0,
                          credit_balance_max=0.0), t, **T_FIXTURE)
    assert zero["verdict"] == "upsize-candidate", zero["verdict"]


def test_credit_balance_applicability_splits_by_current_type():
    """余额字段的「缺失」与「不适用」按当前机型分流，两个方向都要锁住。

    ① 当前是 T 系列 ⇒ 该序列必然存在，缺失是真缺失 ⇒ fail-closed。放行等于对一台
       可能饿死的机器按被限流压低的持续值定档。只缺 max 也算缺失。
    ② 当前非突发 ⇒ 缺失属「不适用」，什么都不做。
    ③ 当前非突发**却有**序列 ⇒ 窗口内改过规格（实测两台 db.m6g.xlarge 有
       178/720 的信用序列，余额上限对应 2 vCPU 机型）。不作为否决依据，
       但必须留一条说明 —— 那份余额测自另一个规格。
    """
    t = core.load_thresholds("aggressive")
    for missing in ({"credit_balance_min": None, "credit_balance_max": None},
                    {"credit_balance_max": None}):
        out = _evaluate(dict(T_RES, rid="i-C-04", **missing), t, **T_FIXTURE)
        assert out["verdict"] == "metric-missing", (missing, out["verdict"])
        assert "CPUCreditBalance 缺失" in out["burst_na"], out["burst_na"]

    # ② 非突发 + 缺失 ⇒ 不适用（RES 是 m5.xlarge）
    na = _evaluate(dict(RES, rid="i-C-05", cpu_n=243, surplus_credits=0,
                        sus_cpu=10, peak_cpu=20), t)
    assert na["verdict"] == "downsize", na["verdict"]
    assert not [b for b in (na.get("blockers") or []) if "改过规格" in b], na

    # ③ 非突发 + 有序列 ⇒ 加说明，不否决
    changed = _evaluate(dict(RES, rid="i-C-06", cpu_n=243, surplus_credits=0,
                             sus_cpu=10, peak_cpu=20,
                             credit_balance_min=0.79, credit_balance_max=576.0), t)
    assert changed["verdict"] == "downsize", changed["verdict"]
    note = [b for b in changed["blockers"] if "窗口内改过规格" in b]
    assert note, changed["blockers"]
```

同批在 `__main__` 的 `tests` 列表里，
`test_overspent_credits_suppress_the_burstable_candidate,` **之前**插入两行：

```python
             test_credit_balance_floor_makes_a_throttled_instance_visible,
             test_credit_balance_applicability_splits_by_current_type,
```

- [ ] **Step 5: 跑，确认两条新测试失败、其余全过**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && python3 tests/test_fail_closed_contracts.py 2>&1 | grep -E "✗|passed"`
Expected: 两个 `✗`（`upsize-candidate` 与 `metric-missing` 都还没实现），
`18/20 passed`。

- [ ] **Step 6: 改 `evaluate()` —— 三处**

① 在 `passes_common` 定义结束、`pool = [dict(sp, usd=prices[` **之前**插入：

```python
    # 信用余额触底 = 当前规格已不足，且**会把 CPUUtilization 压住**（限流到基线），
    # 所以必须在用持续值挑候选之前就把两列候选压掉 —— 否则会对一台饿死的机器
    # 推荐再降一档。适用性同 surplus_credits：仅当前机型为 T 系列才判。
    cb_min, cb_max = res.get("credit_balance_min"), res.get("credit_balance_max")
    if not cs["burst"]:
        # 非突发机型：缺失属「不适用」；**存在**则说明窗口内改过规格（实测两台
        # db.m6g.xlarge 有 178/720 的信用序列，上限对应 2 vCPU 机型）。
        credit_exhausted = False
        if cb_min is not None:
            out.setdefault("blockers", []).append(CLASS_CHANGED_NOTE)
    elif cb_min is None or cb_max is None:
        # 当前机型是 T 系列 ⇒ 该序列必然存在，缺失是真缺失 ⇒ fail-closed。
        # 不能放行：信用耗尽会把 CPUUtilization 压住，放行等于对一台可能饿死的
        # 机器按被压低的持续值定档。
        out["verdict"] = "metric-missing"
        out["burst_na"] = "CPUCreditBalance 缺失，无法排除信用已耗尽"
        return out
    else:
        credit_exhausted = _credit_exhausted(cb_min, cb_max, t)

```

② 把 `out["nonburst"] = nb[0] if nb else None` 替换成：

```python
    out["nonburst"] = None if credit_exhausted else (nb[0] if nb else None)
```

③ 把 `    if cs["burst"] and sc is None:`（`sc = res.get("surplus_credits")`
紧后那一行）替换成：

```python
    if credit_exhausted:
        out["burst_na"] = "CPU 信用余额窗口内触底，当前规格已不足"
    elif cs["burst"] and sc is None:
```

④ 把第一轮加的 verdict 链首行 `    if out["nonburst"] or out["burst"]:`
替换成：

```python
    if credit_exhausted:
        # 与「持续项超」是同一结论（当前规格已不足）的两条独立证据。信用触底须
        # 排在持续项之前：被限流的实例持续值必然偏低，先判持续项会让它落进
        # 「已合理配置」。两者同时成立时 blocker 都写，它们解释的是不同事实。
        out["verdict"] = "upsize-candidate"
        out.setdefault("blockers", []).insert(
            0, f"CPU 信用余额窗口内触底（最小 {cb_min} / 窗口内最大 {cb_max}，"
               f"门限 {t['credit_balance_floor_pct']}%）⇒ 当前规格已不足。"
               f"注意此时 CPUUtilization 被限流压住，持续值不可用于定档。"
               f"本 skill 不产出升配目标机型——选型需容量规划输入")
    elif out["nonburst"] or out["burst"]:
```

- [ ] **Step 7: 跑，确认 EC2 侧全绿且回归锚定值未动**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && python3 tests/test_fail_closed_contracts.py 2>&1 | tail -1 && python3 tests/test_regression_fleet.py 2>&1 | tail -1`
Expected: `20/20 passed` 与 `14/14 passed`

Run: `cd aws-rightsizing && git diff tests/test_regression_fleet.py | wc -l`
Expected: `0`（断言文件一个字未改）

- [ ] **Step 8: 提交**

```bash
git add references/thresholds.json references/core.py \
        tests/test_fail_closed_contracts.py tests/fixtures/regression-fleet.json
git commit -F - <<'MSG'
feat(aws-rightsizing): consume the CPU credit balance floor on EC2

metrics-catalog has declared CPUCreditBalance a blocker in four service
sections since the first design; core.py consumed it nowhere. The gap hid an
entire failure mode: CPUSurplusCreditsCharged only fires for unlimited-mode
instances that overspend past repayment, so a standard-mode instance that
exhausts its credits reads as idle - throttling caps CPUUtilization - and the
solver sees a quiet machine. A real t3.xlarge sits at balance 0.00 with
surplus 0.00 in every band and p95 1.62%, reported as already right-sized.

Judges the floor as a share of the window's observed maximum balance, not of
the credit cap, because the cap needs an RDS baseline table this skill does
not have. Observed separation is wide: exhausted 0.00-0.14%, healthy
85.07-99.91%.

Suppresses both candidate columns when the floor is hit, so the row cannot
carry an amount and cannot recommend shrinking a starved machine further.
Absence splits by current type: a T-family instance must publish the series,
so absence fails closed; a non-burstable one cannot, so absence is N/A - and
presence means the class changed mid-window, which gets a note rather than a
veto because that balance was measured on a different spec.
MSG
```

---

### Task 2: RDS 侧余额判据 + `eval_rds` 分支重排

**Files:**
- Modify: `references/core.py`（`eval_rds()`）
- Modify: `tests/test_managed_dispatch.py`（新增一条测试）
- Test: `tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: Task 1 的 `_credit_exhausted()` 与 `CLASS_CHANGED_NOTE`；
  `_rds_is_burstable(itype)`。
- Produces: `eval_rds()` 的新分支顺序（见下），Task 5 的回放依赖它。

- [ ] **Step 1: 写失败测试**

在 `tests/test_managed_dispatch.py` 的
`test_no_cheaper_candidate_yields_already_right_sized` **之前**插入：

```python
def test_rds_credit_floor_and_branch_order():
    """RDS 余额触底 ⇒ upsize-candidate；且缺失型 fail-closed 必须晚于 cheaper 短路。

    顺序有两条相反的边界，缺一不可：
      · **已能评估**的否决项早于 cheaper 短路 —— 候选集为空不该压掉「这台机器
        已经不够用了」这条警告（与 2026-09-09 那轮采样守卫是同一个教训）。
      · **缺失型** fail-closed 晚于 cheaper 短路 —— 候选集为空时补指标也换不来
        建议，要求它就是让客户白等一个窗口。eval_msk / eval_elasticache 的注释
        早已写明这条原则，eval_rds 此前把两条 fail-closed 放在了前面。
    """
    t = core.load_thresholds("aggressive")
    base = dict(rid="db-C", service="rds", type="db.t4g.medium", vcpu=2,
                mem_gib=4, sample_n=243, surplus_credits=0, dbload_p95=0.05,
                freeable_mem_min_gib=3.0, cheaper_candidate_exists=True)

    hit = core.eval_rds(dict(base, credit_balance_min=0.70,
                             credit_balance_max=576.0), t)
    assert hit["verdict"] == "upsize-candidate", hit["verdict"]
    assert any("信用余额窗口内触底" in b for b in hit["blockers"]), hit["blockers"]

    # 反向：健康余额 ⇒ 照常走降配路径
    ok = core.eval_rds(dict(base, credit_balance_min=575.3,
                            credit_balance_max=576.0), t)
    assert ok["verdict"] == "downsize-candidate", ok["verdict"]

    # db.t* 缺余额字段 ⇒ fail-closed
    miss = core.eval_rds(base, t)
    assert miss["verdict"] == "metric-missing", miss["verdict"]
    assert "CPUCreditBalance 缺失" in miss["blockers"][0], miss["blockers"]

    # 非突发有序列 ⇒ 不否决，但留说明
    changed = core.eval_rds(dict(base, type="db.m6g.xlarge", vcpu=4, mem_gib=16,
                                 freeable_mem_min_gib=12.0,
                                 credit_balance_min=0.79,
                                 credit_balance_max=576.0), t)
    assert changed["verdict"] == "downsize-candidate", changed["verdict"]
    assert any("窗口内改过规格" in b for b in changed["blockers"]), changed["blockers"]

    # 顺序：无更便宜候选 + 缺余额字段 ⇒ 已合理配置（不得要求补指标）
    no_cheaper = core.eval_rds(dict(base, cheaper_candidate_exists=False), t)
    assert no_cheaper["verdict"] == "已合理配置", (
        f"候选集为空时仍要求信用指标，会让客户白等一个窗口 —— {no_cheaper}")

    # 顺序：无更便宜候选 + 余额已触底 ⇒ 仍须报 upsize-candidate（警告不可被压掉）
    veto_wins = core.eval_rds(dict(base, cheaper_candidate_exists=False,
                                   credit_balance_min=0.70,
                                   credit_balance_max=576.0), t)
    assert veto_wins["verdict"] == "upsize-candidate", (
        f"候选集为空压掉了「规格已不足」的警告 —— {veto_wins}")
```

同批在 `__main__` 的 `tests` 列表里，
`test_no_cheaper_candidate_yields_already_right_sized,` **之前**插入：

```python
             test_rds_credit_floor_and_branch_order,
```

- [ ] **Step 2: 跑，确认失败**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && python3 tests/test_managed_dispatch.py 2>&1 | grep -E "✗|passed"`
Expected: `✗ test_rds_credit_floor_and_branch_order`（第一个断言就挂：
现行实现没有余额判据），`31/32 passed`

- [ ] **Step 3: 把两条缺失型 fail-closed 从前面摘掉**

`references/core.py` 的 `eval_rds()` 里，把：

```python
    sc = res.get("surplus_credits")
    if burstable and sc is None:
        _verdict(out, "metric-missing",
                 "CPUSurplusCreditsCharged 缺失，无法排除信用已超额")
        return out
    if sc is not None and sc > 0:
```

替换成：

```python
    sc = res.get("surplus_credits")
    if sc is not None and sc > 0:
```

- [ ] **Step 4: 加余额否决项（已能评估的那一侧，留在前面）**

紧接上一步那个 `if sc is not None and sc > 0:` 分支的 `return out` 之后、
`    dbload = res.get("dbload_p95")` **之前**插入：

```python
    cb_min, cb_max = res.get("credit_balance_min"), res.get("credit_balance_max")
    if not burstable:
        if cb_min is not None:
            out["blockers"].append(CLASS_CHANGED_NOTE)
    elif cb_min is not None and cb_max is not None and _credit_exhausted(cb_min, cb_max, t):
        _verdict(out, "upsize-candidate",
                 f"CPU 信用余额窗口内触底（最小 {cb_min} / 窗口内最大 {cb_max}，"
                 f"门限 {t['credit_balance_floor_pct']}%），规格已不足，是升配候选")
        return out
```

- [ ] **Step 5: 把两条缺失型 fail-closed 补到 `cheaper` 短路之后**

在 `    freeable_min, mem_gib = res.get("freeable_mem_min_gib"), res.get("mem_gib")`
**之前**插入：

```python
    # 缺失型 fail-closed 必须排在 cheaper 短路**之后**：候选集为空时补指标也不会
    # 产出建议，要求它就是让客户白等一个窗口 —— eval_msk / eval_elasticache 的
    # 注释早已写明「候选集为空 ⇒ 直接已合理配置，且早于所有前置指标要求」，
    # eval_rds 此前把这两条放在了前面。而**已能评估**的否决项仍在最前：
    # 候选集为空不该压掉「这台机器已经不够用了」这条警告。
    if burstable and sc is None:
        _verdict(out, "metric-missing",
                 "CPUSurplusCreditsCharged 缺失，无法排除信用已超额")
        return out
    if burstable and (cb_min is None or cb_max is None):
        _verdict(out, "metric-missing",
                 "CPUCreditBalance 缺失，无法排除信用已耗尽")
        return out
```

- [ ] **Step 6: 跑，确认全绿**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && python3 tests/test_managed_dispatch.py 2>&1 | grep -E "✗|passed"`
Expected: `32/32 passed`，无 `✗`

- [ ] **Step 7: 提交**

```bash
git add references/core.py tests/test_managed_dispatch.py
git commit -F - <<'MSG'
feat(aws-rightsizing): consume the credit floor on RDS and fix eval_rds ordering

Mirrors the EC2 credit-balance veto onto eval_rds, gated on the same
_rds_is_burstable applicability test.

Adding one more fail-closed exposed a pre-existing ordering bug. eval_msk and
eval_elasticache both document "an empty candidate set means already
right-sized, ahead of every metric prerequisite", because asking a customer to
enable a metric that cannot change the outcome costs them a whole window.
eval_rds had its fail-closed branches ahead of that short-circuit, and the
existing test for a cheapest-class instance with no memory data caught the new
field immediately.

The two boundaries run in opposite directions and both matter: vetoes that can
be evaluated stay ahead of the short-circuit, because an empty candidate set
must not suppress "this machine is already too small" - the same lesson the
sampling guard learned. Fail-closed on a missing metric moves behind it.
MSG
```

---

### Task 3: ElastiCache `ReplicationLag` 按副本存在性分流

**Files:**
- Modify: `references/core.py`（`eval_elasticache()`）
- Modify: `tests/test_managed_dispatch.py`（8 处 fixture + 新增一条测试）
- Modify: `tests/test_csv_contract.py`（1 处 fixture）
- Modify: `tests/test_fail_closed_contracts.py`（`CACHE` fixture）
- Modify: `references/sample-solve.md`（样例输入）
- Test: 全部 9 个测试文件

**Interfaces:**
- Consumes: `_persistent(res, p95_key, max_key)`、`_verdict(out, verdict, *reasons)`。
- Produces: 输入字段 `has_replica`（ElastiCache 必填）。

- [ ] **Step 1: 给所有既有 elasticache fixture 补 `has_replica=False`**

`False` 等价于改动前的 fail-open，**逐条保住原测试意图**；新门槛由 Step 3
的新测试用 `True` 覆盖。`test_managed_vetoes_actually_fire_and_block` 不受影响 ——
`lag_persist >= 门限` 的否决判定与 `has_replica` 无关，只有**缺失**的处理被分流。

```bash
cd aws-rightsizing && python3 - <<'PY'
import pathlib, re
total = 0
for f in ("tests/test_managed_dispatch.py", "tests/test_csv_contract.py",
          "tests/test_fail_closed_contracts.py"):
    p = pathlib.Path(f); s = p.read_text()
    a = len(re.findall(r'service="elasticache",', s))
    b = len(re.findall(r'"service": "elasticache",', s))
    s = re.sub(r'service="elasticache",',
               'service="elasticache", has_replica=False,', s)
    s = re.sub(r'"service": "elasticache",',
               '"service": "elasticache", "has_replica": False,', s)
    p.write_text(s); total += a + b
    print(f"{f}: kwargs {a} 处 / dict 字面量 {b} 处")
print("合计", total, "处")
PY
```
Expected: `tests/test_managed_dispatch.py: kwargs 7 处 / dict 字面量 1 处`、
`tests/test_csv_contract.py: kwargs 0 处 / dict 字面量 1 处`、
`tests/test_fail_closed_contracts.py: kwargs 0 处 / dict 字面量 1 处`、
`合计 10 处`（`test_fail_closed_contracts.py` 的 `CACHE` 用的是
`"service": "elasticache",` 形式，会被第二个正则命中）。

若 `合计` 不是 10，**停下核对** —— 说明 fixture 的写法与预期不同，
漏掉的那处会在 Step 4 变成一条 `metric-missing` 的假失败。

- [ ] **Step 2: 给 `references/sample-solve.md` 的样例输入补字段**

该文档的 fixture 被 `tests/test_sample_reproduces.py` 解析，漏了它那条测试会红。

```bash
cd aws-rightsizing && python3 - <<'PY'
import pathlib, re
p = pathlib.Path("references/sample-solve.md"); s = p.read_text()
n = len(re.findall(r'"service": *"elasticache",', s))
s = re.sub(r'"service": *"elasticache",',
           '"service": "elasticache", "has_replica": false,', s)
p.write_text(s); print("补了", n, "处")
PY
```
Expected: `补了 1 处`

- [ ] **Step 3: 写失败测试**

在 `tests/test_managed_dispatch.py` 的 `test_rds_credit_floor_and_branch_order`
**之前**插入：

```python
def test_replication_lag_absence_splits_by_replica_presence():
    """`ReplicationLag` 的缺失按副本存在性分流，不再无条件放行。

    Evictions 的 fail-closed 与 ReplicationLag 的分流**不对称是有依据的**：
    Evictions 每个节点都发布，缺失是真缺失；ReplicationLag 只在存在副本时才有
    意义。但放行必须有依据 —— 无条件放行会让这条否决项在一个真实复制组上
    静默消失，而该 skill 已记录「维度名写错时 list-metrics 与 get-metric-data
    都只返回空、不报错」。

    不用 count 做代理：`3 分片 x 1 节点`（count=3、无副本）是合法的 cluster-mode
    配置，按 count > 1 会把它误判成「该有副本却缺指标」。
    """
    t = core.load_thresholds("aggressive")
    base = dict(rid="cc-R", service="elasticache", type="cache.r7g.large",
                vcpu=2, mem_gib=13.07, evictions_sum=0, evictions_p95=0,
                engine_cpu_p95=12, db_mem_used_pct_max=35, sample_n=243,
                cheaper_candidate_exists=True)

    # 有副本 + 序列缺失 ⇒ 采集缺口，不得放行
    gap = core.eval_elasticache(dict(base, has_replica=True), t)
    assert gap["verdict"] == "metric-missing", gap["verdict"]
    assert "存在副本却无 ReplicationLag" in gap["blockers"][0], gap["blockers"]

    # 无副本 + 序列缺失 ⇒ 不适用，放行
    na = core.eval_elasticache(dict(base, has_replica=False), t)
    assert na["verdict"] == "downsize-candidate", na["verdict"]

    # has_replica 自身缺失 ⇒ fail-closed（不得假定无副本）
    unknown = core.eval_elasticache(base, t)
    assert unknown["verdict"] == "metric-missing", unknown["verdict"]
    assert "has_replica 缺失" in unknown["blockers"][0], unknown["blockers"]

    # 有副本 + 序列有值且越界 ⇒ 否决判定不受本次分流影响
    veto = core.eval_elasticache(dict(base, has_replica=True, repl_lag_p95=2.0,
                                      repl_lag_max=5.0), t)
    assert veto["verdict"] == "blocked", veto["verdict"]

    # 有副本 + 序列有值且正常 ⇒ 照常走降配路径
    fine = core.eval_elasticache(dict(base, has_replica=True,
                                      repl_lag_p95=0.0007, repl_lag_max=0.03), t)
    assert fine["verdict"] == "downsize-candidate", fine["verdict"]
```

同批在 `__main__` 的 `tests` 列表里，`test_rds_credit_floor_and_branch_order,`
**之前**插入：

```python
             test_replication_lag_absence_splits_by_replica_presence,
```

- [ ] **Step 4: 跑，确认只有新测试失败**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 8 个文件全绿；`tests/test_managed_dispatch.py` 为 `32/33 passed`，
唯一失败是 `test_replication_lag_absence_splits_by_replica_presence`。

若别的文件也红，**先回到 Step 1** 核对 fixture 补漏。

- [ ] **Step 5: 改 `eval_elasticache()`**

把：

```python
    lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
    if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:
```

替换成：

```python
    # Evictions 的 fail-closed（上面）与 ReplicationLag 的分流（下面）**不对称是
    # 有依据的**，不是漏改：Evictions 每个节点都发布，缺失是真缺失；
    # ReplicationLag 只在存在副本时才有意义，缺失可能是「不适用」。
    # 但放行必须有依据——无条件放行会让这条否决项在一个真实复制组上静默消失。
    # 不用 count 做代理：`3 分片 x 1 节点`（count=3、无副本）是合法配置。
    has_replica = res.get("has_replica")
    lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
    if has_replica is None:
        _verdict(out, "metric-missing",
                 "has_replica 缺失，无法区分「无副本故不适用」与「采集失败」")
        return out
    if has_replica and lag_persist is None:
        _verdict(out, "metric-missing",
                 "存在副本却无 ReplicationLag 序列 ⇒ 采集缺口，"
                 "不得按「无副本」放行")
        return out
    if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:
```

- [ ] **Step 6: 跑全套，确认 9 个文件全绿**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿；`test_managed_dispatch.py` `33/33`、
`test_fail_closed_contracts.py` `20/20`、`test_regression_fleet.py` `14/14`。

- [ ] **Step 7: 提交**

```bash
git add references/core.py references/sample-solve.md \
        tests/test_managed_dispatch.py tests/test_csv_contract.py \
        tests/test_fail_closed_contracts.py
git commit -F - <<'MSG'
fix(aws-rightsizing): split ReplicationLag absence by replica presence

Evictions fails closed on absence and ReplicationLag failed open, with
nothing in core.py able to tell "single node, so not applicable" from
"collection broke". The asymmetry itself is justified - every node publishes
Evictions, only a replicated group publishes lag - but the open side was
unconditional, so on a real replication group a dimension typo would make the
veto vanish silently, and this skill has already recorded that a wrong
dimension name returns empty from both list-metrics and get-metric-data
without erroring.

Replica presence comes from the node id's shard/member shape in the existing
inventory, so no new API call. count is not a usable proxy: three shards with
one node each is a legal cluster-mode layout with count=3 and no replica, and
gating on count > 1 would report a collection gap that does not exist.

Existing fixtures get has_replica=False, which reproduces the previous
fail-open behaviour exactly, so every one of their assertions keeps its
original intent.
MSG
```

---

### Task 4: 采集契约与文档

**Files:**
- Modify: `references/cli-recipes.md`（三个新字段的输入契约行 + 派生配方）
- Modify: `references/metrics-catalog.md`（四行 `CPUCreditBalance` 用途列）
- Modify: `references/thresholds.md`（新阈值键的语义与选值依据）
- Modify: `SKILL.md`（EC2 / RDS / ElastiCache 三节 + 通则成员清单标注）
- Modify: `references/report-template.md`（`upsize-candidate` 的 EC2 侧依据）
- Modify: `docs/README.md`（plans 表）

**Interfaces:**
- Consumes: Task 1–3 的判据行为。
- Produces: 组装侧可执行的三个字段派生配方。

- [ ] **Step 1: `cli-recipes.md` 加三行输入契约**

在 `surplus_credits` 那一行**之后**插入：

```
| `credit_balance_min` | T 机型必填 | agg 中 `CPUCreditBalance` / `Minimum` / **`full-window`** 档的 `min`。**这是下限型指标，必须取 `full-window`** —— `biz-hours` 会漏掉夜间批处理把信用耗尽的低点（同 `freeable_mem_min_gib` 的坑）。**非突发机型该序列结构性不存在，字段留空即正确，不要补 0** | 当前机型是 T 系列时 `metric-missing`（信用耗尽会把 `CPUUtilization` 压住，放行等于按被限流的持续值定档）；非突发机型不受影响 |
| `credit_balance_max` | T 机型必填 | 同一行的 `max`（判据按「占窗口内观测最大余额的百分比」判，不依赖信用上限——RDS 的 baseline 百分比不在本 skill 的静态资产里） | 同上 |
| `has_replica` | ElastiCache 必填 | 由 `raw/inventory/elasticache.json` 的节点 `id`（形如 `<rg>-<NNNN>-<MMM>`）按 `(rg, NNNN)` 分组，**任一分片的成员数 > 1** 即 `true`。**不要用 `count` 代替** —— `3 分片 × 1 节点`（`count=3`、无副本）是合法的 cluster-mode 配置 | `metric-missing`（无法区分「无副本故不适用」与「采集失败」，不得假定无副本） |
```

- [ ] **Step 2: `cli-recipes.md` 加 `has_replica` 的派生片段**

在 §7 组装 `solver-in.json` 的那一节里，加入这段（与该文件其他片段同样是可直接跑的）：

```bash
# has_replica：从节点 id 的分片-成员结构推出，无需 describe-replication-groups
jq -s '
  [ .[0][]
    | (.id | capture("^(?<rg>.*)-(?<shard>\\d{4})-(?<member>\\d{3})$")) as $p
    | {rg: .rg, shard: $p.shard, member: $p.member} ]
  | group_by(.rg)
  | map({ (.[0].rg): (group_by(.shard) | map(length) | max > 1) })
  | add
' raw/inventory/elasticache.json > raw/solver/has-replica.json
```

**注意节点 id 有两种形态**（实测两支机队都同时存在）：cluster mode enabled 是
`<rg>-<NNNN>-<MMM>`，**disabled 是 `<rg>-<MMM>`、没有分片号**。只认前一种会静默
丢掉后一种 —— 实测 13 个复制组里有 2 组是非集群模式，单形态正则只得到 11 组。
所以分片号必须**可选**，缺省当 `0001`；`rg` 直接取 inventory 字段，不从 id 解析。
以 `references/cli-recipes.md` 里的那份配方为准，**不要照抄本节的早期版本**。

**自检**（复制组数须与 inventory 的 `rg` 去重数一致，且覆盖到的节点数须等于
inventory 节点总数）：

```bash
jq 'length' raw/solver/has-replica.json
jq '[.[].rg] | unique | length' raw/inventory/elasticache.json
```

- [ ] **Step 3: `metrics-catalog.md` 改四行**

EC2 一节：

```
| CPUCreditBalance | Average, **Minimum** | blocker：`full-window` 的 `min` 触底 ⇒ `upsize-candidate`（当前规格已不足）。**仅 `t*` 发布**，非 burstable 缺失属「不适用」不是「缺失」；**存在**则说明窗口内改过规格 | 已实测 |
```

RDS 一节：

```
| CPUCreditBalance | Average, **Minimum** | blocker：`full-window` 的 `min` 触底 ⇒ `upsize-candidate`。**仅 `db.t*` 发布**，非 burstable 缺失属「不适用」；**存在**则说明窗口内改过规格（实测两台 `db.m6g.xlarge` 有 178/720 的信用序列） | 已实测 |
```

ElastiCache 一节与 MSK 一节的 `CPUCreditBalance` 行，用途列改成
**「无判据消费」**（与该文件既有的 `CPUCreditUsage` /
`CPUSurplusCreditBalance` 写法一致）：两者的判据输入里没有 burstable 形态字段，
不为未实测的引擎/机型发明判据。

同时把 stat 扫描表里 `EC2 CPUCreditBalance` 与
`RDS FreeableMemory / FreeStorageSpace / CPUCreditBalance` 两行的结论列
从「下限型判据要 Minimum」改成「下限型判据，**已有消费者**」，
`EC CPUCreditBalance` 那行改成「无判据消费」。

- [ ] **Step 4: `thresholds.md` 记新键**

加一节写明 `credit_balance_floor_pct` 的语义（余额下限占**窗口内观测最大余额**的
百分比，低于它即判触底）、为什么不用信用上限做分母（RDS 的 baseline 百分比不在
静态资产里）、以及 `credit_balance_max == 0` 的兜底。
**数值只引用键名，不复述**（`tests/test_no_duplicated_constants.py` 的约束）。
选值依据写实测分离度：触底 0.00%–0.14%，健康 85.07%–99.91%，中间无观测点。

- [ ] **Step 5: `SKILL.md` 三节 + 通则清单**

EC2 一节，在第一轮加的「需求量超过当前规格」那条**之后**插入：

```
- **CPU 信用余额触底 ⇒ `upsize-candidate`，且必须压掉两列候选。**
  `CPUSurplusCreditsCharged > 0` 是**窄**信号（仅 unlimited 模式且透支超期未偿还），
  standard 模式触底只会被限流、不产生 surplus 计费。**限流会把 `CPUUtilization`
  压住**，于是饿死的机器看起来最闲、最容易被推荐再降一档。
  取 `full-window` 的 `Minimum`，判据在 `core.py`，阈值键
  `credit_balance_floor_pct`。
```

RDS 一节，在信用超额那条之后补一句：余额触底与 `CPUSurplusCreditsCharged > 0`
是**两条独立**否决项，都产出 `upsize-candidate`；且**已能评估的否决项排在
`cheaper_candidate_exists` 短路之前，缺失型 fail-closed 排在它之后**。

ElastiCache 一节，把 `Evictions > 0 或 ReplicationLag max >= ... ⇒ 阻断`
那条改成写明两者的缺失处理不对称及理由，并写明 `has_replica` 的来源。

「仅子集发布」通则的成员清单里，给 `CPUCreditBalance` 与 `ReplicationLag`
标注**已消费 / 已分流**（清单的作用是新增指标时比对，状态过期会让它失效）。

- [ ] **Step 6: `report-template.md` 补 EC2 侧依据**

把第一轮写的 `upsize-candidate` 语义段里「EC2 侧的依据是**持续项**反推的需求量
超过当前规格」改成「EC2 侧有**两条独立依据**：持续项反推的需求量超过当前规格，
**或** CPU 信用余额触底（后者必须优先判 —— 被限流的实例持续值必然偏低）」。

- [ ] **Step 7: `docs/README.md` 的 plans 表加一行**

```
| [2026-09-10-credit-floor-and-veto-applicability.md](./plans/2026-09-10-credit-floor-and-veto-applicability.md) | 消费 `CPUCreditBalance` 下限让被限流的实例可见;`eval_rds` 分支重排;`ReplicationLag` 缺失按副本存在性分流 |
```

- [ ] **Step 8: 跑测试与三条安全自检**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿。`test_no_duplicated_constants.py` 尤其要过 ——
新增文案只提键名与实测百分比区间，不含 `thresholds.json` 的取值。

Run（三条都须打印 `CLEAN`）：
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

- [ ] **Step 9: 提交**

```bash
git add references/cli-recipes.md references/metrics-catalog.md \
        references/thresholds.md references/report-template.md \
        SKILL.md docs/README.md
git commit -F - <<'MSG'
docs(aws-rightsizing): document the credit floor contract and drop a false promise

metrics-catalog claimed CPUCreditBalance was a blocker in four service
sections while core.py consumed it nowhere. Two of those sections now have a
real consumer and say what it does; the other two say "no consumer", matching
how this file already describes CPUCreditUsage and CPUSurplusCreditBalance.
A catalogue that claims a judgment nobody implements teaches readers to
distrust the whole column.

Adds the collection recipe for has_replica, derived from the node id's
shard/member shape rather than a new API call, with a self-check that catches
node ids the pattern silently drops.
MSG
```

---

### Task 5: 交付前门禁与真实数据对账

**Files:**
- 无仓库改动。产出是一份验证记录。

**Interfaces:**
- Consumes: Task 1–4 的全部改动。

- [ ] **Step 1: 全量测试门禁**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿；`test_fail_closed_contracts.py` `20/20`（原 18）、
`test_managed_dispatch.py` `33/33`（原 31）、`test_regression_fleet.py` `14/14`。

- [ ] **Step 2: 证明新阈值键是活的，不是孤儿键**

```bash
cd aws-rightsizing && python3 - <<'PY'
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path("references").resolve()))
import core
t = core.load_thresholds("aggressive")
# 一台余额 490/576（占 85.07%）的健康实例：门限调到 90 后必须翻转成触底
healthy = (490.0, 576.0)
assert core._credit_exhausted(*healthy, t) is False, "基线取值下应判健康"
t2 = dict(t, credit_balance_floor_pct=90)
assert core._credit_exhausted(*healthy, t2) is True, \
    "把门限调到 90 后仍判健康 ⇒ credit_balance_floor_pct 是孤儿键，判据没读它"
print("OK: credit_balance_floor_pct 是活量")
PY
```
Expected: `OK: credit_balance_floor_pct 是活量`

- [ ] **Step 3: 真实数据回放 —— 必须先补齐新字段**

**旧的 `core-in-*.json` 不再是合法输入**：它们由本轮之前的组装脚本产出，
不带 `credit_balance_min` / `credit_balance_max` / `has_replica`。直接回放会让
所有 T 系列 EC2 行与全部 ElastiCache 行变成 `metric-missing` —— 那是**正确的
fail-closed**，不是缺陷，但也证不了什么。所以回放前必须按 Task 4 的配方从
`raw/` 派生这三个字段注入进去，这一步同时验证了配方本身。

设 `RAW` 指向一份既有交付的 `raw/`（含真实账号与资源 ID，**不得提交，
逐行结果也不得贴进仓库**）。

```bash
RAW=<某份既有交付>/raw
CORE=$PWD/references/core.py
python3 - "$RAW" "$CORE" <<'PY'
import csv, json, re, subprocess, sys, glob, collections
raw, core = sys.argv[1], sys.argv[2]

# ① 从 summary-*.csv 取 CPUCreditBalance / Minimum / full-window 的 min 与 max
def credits(path):
    out = {}
    for r in csv.DictReader(open(path)):
        if (r["metric"] == "CPUCreditBalance" and r["stat"] == "Minimum"
                and r["bucket"] == "full-window"):
            out[r["resource"]] = (float(r["min"]), float(r["max"]))
    return out
ec2_cb = credits(f"{raw}/metrics/summary-ec2-all.csv")
rds_cb = credits(f"{raw}/metrics/summary-rds.csv")

# ② 从 inventory 推 has_replica：任一分片成员数 > 1
mem = collections.defaultdict(set)
for n in json.load(open(f"{raw}/inventory/elasticache.json")):
    m = re.match(r"^(.*)-(\d{4})-(\d{3})$", n["id"])
    assert m, f"节点 id 不符合 <rg>-<NNNN>-<MMM>：{n['id']}"
    mem[(n["rg"], m.group(2))].add(m.group(3))
has_rep = collections.defaultdict(bool)
for (rg, _sh), ms in mem.items():
    has_rep[rg] |= len(ms) > 1
print(f"has_replica 推导：{sum(has_rep.values())} 组有副本 / "
      f"{len(has_rep) - sum(has_rep.values())} 组无副本")

def inject(res):
    cb = ec2_cb.get(res["rid"]) or rds_cb.get(res["rid"])
    if cb:
        res["credit_balance_min"], res["credit_balance_max"] = cb
    if res.get("service") == "elasticache":
        res["has_replica"] = has_rep[res["rid"]]
    return res

for prof in ("conservative", "aggressive"):
    rows = []
    for f in sorted(glob.glob(f"{raw}/solver/core-in-{prof}-*.json")):
        ctx = json.load(open(f))
        ctx["resources"] = [inject(r) for r in ctx["resources"]]
        p = subprocess.run([sys.executable, core],
                           input=json.dumps(ctx, ensure_ascii=False),
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-500:]
        rows += json.loads(p.stdout)
    ds = [r for r in rows if r.get("bucket") == "downsize"]
    r1 = round(sum(r.get("nb_save_mo") or 0 for r in ds), 2)
    r2 = round(sum(max(r.get("nb_save_mo") or 0, r.get("b_save_mo") or 0)
                   for r in ds), 2)
    up = [r for r in rows if r["verdict"] == "upsize-candidate"]
    assert all(r.get("bucket") == "excluded" for r in up), "upsize 行必须落 excluded"
    assert all(r.get("nb_save_mo") is None and r.get("b_save_mo") is None
               for r in up), "upsize 行不得带节省额"
    changed = [r for r in rows
               if any("窗口内改过规格" in b for b in (r.get("blockers") or []))]
    print(f"  {prof:<13} route1={r1:<9} route2={r2:<9} upsize={len(up)} "
          f"规格变更注记={len(changed)} "
          f"verdicts={dict(collections.Counter(r['verdict'] for r in rows))}")
PY
```

Expected（与该份交付的旧 `totals-<profile>.json` 对账）：
- **`route1` 与旧值逐值相同**（本轮不改候选选型，只在触底时压掉候选，
  而触底的实例本就没有候选）。
- `upsize-candidate` 比第一轮多出**信用触底的那台 t3.xlarge**。
- 「规格变更注记」出现在那两台 `db.m6g.xlarge` 上，且它们的 verdict
  **仍是 `blocked`**（`FreeableMemory` 独立否决，优先级更高）。
- ElastiCache 13 组结论**不变**（推导应得 12 组有副本 / 1 组无副本，
  且全部有 `repl_lag`，所以新门槛一条都不触发）。

若 `route1` 有任何变化 ⇒ **停止**，说明改动漏进了降配路径。

- [ ] **Step 4: 三条安全自检 + 公开仓库敏感信息扫描**

Run: Task 4 Step 8 的三条 `grep` 自检。
Expected: 三行 `CLEAN`

```bash
cd ~/git/panlm-skills && git diff main...HEAD -U0 -- aws-rightsizing | grep '^+' \
  | grep -vE '^\+\+\+' \
  | grep -nE '[0-9]{12}|i-0[0-9a-f]{6,}|vol-0[0-9a-f]|snap-0[0-9a-f]|aws-(stg|pt|uat|sit|prod)-|/Users/|/home/|hk-(staging|situat)' \
  | grep -v '123456789012' || echo "CLEAN: no sensitive identifiers in diff"
```
Expected: `CLEAN: no sensitive identifiers in diff`（plan 内自检脚本自身的模式串
会命中，属既有假阳性，与 `SKILL.md` 的 `selfcheck-exempt` 同类）

- [ ] **Step 5: 汇总验证记录**

整理成一段附在 PR / 交付说明里，至少覆盖：9 个测试文件的通过数与增量、
回归锚定值与断言文件未改、新阈值键的活量证明、真实回放的 `route1` 零变化、
新增的 `upsize-candidate` 与「规格变更注记」条数、ElastiCache 13 组结论不变、
`has_replica` 推导的 12/1 分布、三条自检 `CLEAN`、敏感信息扫描 `CLEAN`。

---

## Self-Review

**Spec coverage:**

| spec 条目 | 落在哪个 task |
|---|---|
| C1 两个信用字段 + 阈值键 + `full-window` 要求 | Task 1 Step 1/2；契约行在 Task 4 Step 1 |
| C1 被否决的更简方案（判 `== 0`） | Task 1 Step 2 的 docstring |
| C2 EC2 侧消费余额、压掉两列候选、优先级早于持续项 | Task 1 Step 6 的四处改动 |
| C3 RDS 侧同构 | Task 2 Step 4 |
| C4 `ReplicationLag` 按 `has_replica` 分流 + `Evictions` 不对称注释 | Task 3 Step 5 |
| C5 `metrics-catalog` 四行订正 | Task 4 Step 3 |
| **C6 `eval_rds` 分支重排** | Task 2 Step 3/4/5，测试在 Task 2 Step 1 的后两个断言 |
| P5 不用 `count` 做代理 | Task 3 Step 5 的注释 + Task 4 Step 1 的契约行 |
| 改动清单里的 `sample-solve.md` | Task 3 Step 2 |
| 改动清单里的 `thresholds.md` | Task 4 Step 4 |
| 改动清单里的 `SKILL.md` / `report-template.md` / `docs/README.md` | Task 4 Step 5/6/7 |
| 测试影响：fixture 波及面 5 处清单 | Task 1 Step 3、Task 3 Step 1/2（含数量断言与「不符则停下核对」） |
| 测试影响：既有 elasticache fixture 一律 `False` 保住原意图 | Task 3 Step 1 |
| 测试影响：每条新测试带反向半 | Task 1 Step 4、Task 2 Step 1、Task 3 Step 3 |
| 验证方式 1（9 文件全绿 + 锚定值不变） | Task 5 Step 1 + Task 1 Step 7 的 `git diff` 断言 |
| 验证方式 2（反向半成立） | 三条新测试内部 |
| 验证方式 3（真实回放五项） | Task 5 Step 3 |
| 验证方式 4（阈值键是活量） | Task 5 Step 2 |
| 验证方式 5（三条自检 `CLEAN`） | Task 4 Step 8、Task 5 Step 4 |
| 「明确不做」各条 | Global Constraints 已收；`eval_msk` 与 `describe-replication-groups` 未出现在任何 Files 里 |
| 「后续」第三、四轮 | **不在本 plan 范围**，spec 已声明各自独立 |

**Placeholder scan:** 无 TBD / TODO / 「类似 Task N」/ 「适当处理错误」。
唯一占位是 Task 5 Step 3 的 `RAW=<某份既有交付>/raw` —— 那份数据含真实账号，
按仓库纪律不能进版本库，必须由执行者在本机指定，已就地说明。

**Type consistency:**
- `_credit_exhausted(cb_min, cb_max, t) -> bool` 在 Task 1 Step 2 定义，
  Task 2 Step 4 与 Task 5 Step 2 按同一签名调用（位置参数，第三个是 thresholds 字典）。
- `CLASS_CHANGED_NOTE` 在 Task 1 Step 2 定义为模块级常量，
  Task 1 Step 6 与 Task 2 Step 4 都直接引用该名字。
- 局部量 `cb_min` / `cb_max` / `credit_exhausted` 在 `evaluate()` 内，
  Step 6 的四处改动按「① 定义 → ②③④ 使用」的顺序落地，
  **①必须插在 `pool = [dict(sp, usd=prices[` 之前** —— 试装时把它放在
  `sc = res.get("surplus_credits")` 处会得到 `UnboundLocalError`，
  因为 `out["nonburst"]` 的赋值在那之前。
- `has_replica` 是 `res` 的输入键，`eval_elasticache()` 内用 `res.get()` 读，
  与 Task 3 Step 1/2 注入的 fixture 键名逐字一致（`has_replica`，非 `hasReplica`）。
- 新测试函数名（`test_credit_balance_floor_makes_a_throttled_instance_visible`、
  `test_credit_balance_applicability_splits_by_current_type`、
  `test_rds_credit_floor_and_branch_order`、
  `test_replication_lag_absence_splits_by_replica_presence`）在各自 Task 里定义，
  并在同批插入对应文件 `__main__` 的 `tests` 列表。
- blocker 断言用的子串（`信用余额窗口内触底` / `不产出升配目标机型` /
  `CPUCreditBalance 缺失` / `窗口内改过规格` / `存在副本却无 ReplicationLag` /
  `has_replica 缺失`）与实现文案逐字一致。
