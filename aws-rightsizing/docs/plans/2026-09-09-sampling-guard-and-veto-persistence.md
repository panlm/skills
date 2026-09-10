# 采样守卫降档 + 否决项改判持续态 实现计划

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`；集群/复制组名换成
> `msk-<env>-NN` / `redis-<env>-NN` 占位名（原 8 个 MSK + 2 个 Redis 的条数、
> 环境分布与区分度都保留）；本机绝对路径改成 `~/` 开头。**指标值、点数、金额、
> 机型全是原值。** 文中 `~/Downloads/123456789012-ap-east-1-20260909/` 那批
> 复算脚本与原始产出**不在本仓库**（含真实账号与资源 ID，只存在于私有工作区）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `core.py` 在样本不足时照样产出降配建议（降置信度而非拒绝），并把三条「曾经出现过一次」的否决项改为判持续状态。

**Architecture:** 三处独立改动都落在 `references/core.py` 的判据侧，采集侧只增字段不改判据。所有新输入都是可选的：缺失时逐字节回退到今天的行为，因此未升级的采集侧不受影响。`min_biz_hours_points` 的**值不变**，只把作用从「拒绝线」改为「置信度分档线」，且**只对降配路径生效**——`is_idle`（删除）与 `is_stop_candidate`（停机）保持硬门限。

**Tech Stack:** Python 3（无第三方依赖）、jq（`agg.jq`）、纯 `assert` 测试（8 个 `tests/test_*.py`，各自可独立 `python3` 运行）

**Spec:** `docs/superpowers/specs/2026-09-09-sampling-guard-and-veto-persistence-design.md`

## Global Constraints

- 阈值数值**一个都不改**。`thresholds.json` 不新增键。唯一真值源地位不变。
- 所有新增输入字段**必须可选**，缺失时行为与改动前逐字节相同（fail-closed 且向后兼容）。
- 缺失一律 `None`，**禁止兜底为 0**。`0` 与 `None` 在本仓库是两种语义。
- `min_biz_hours_points` 必须继续用下标 `t["min_biz_hours_points"]` 读取，**不得改成 `.get()`**——`tests/test_fail_closed_contracts.py` 断言缺键时抛 `KeyError`。
- 散文文档**不得复述**阈值数值，只能引用键名（`tests/test_no_duplicated_constants.py` 会查）。
- 每个 Task 结束时 `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done` 必须全绿。
- 提交到分支 `feat/sampling-guard-and-veto-persistence`。**不 push、不合并 master。**

## 对 spec 的两处更正（实现前已核实）

1. **spec 说 4 个测试文件受影响，实际是 5 个。** 漏了 `tests/test_fail_closed_contracts.py:85`，它断言 `cpu_n=13 ⇒ insufficient-data`。同文件第 68–80 行断言「缺 `min_biz_hours_points` 抛 `KeyError`」**必须保留**。
2. **托管行不设 `confidence`。** spec 的 C1 分档表是按 EC2 的「有无内存数据」两轴写的，托管判据没有这个轴，且 `report-template.md` 现行契约写明 `confidence` 由 `evaluate()` 独占产出、托管行留空。因此：**EC2 低样本行给 `confidence=low`；托管低样本行只追加 blocker，`confidence` 保持留空。** 低样本事实通过 `sample_points` 列 + blocker 文本可见。

---

### Task 1: C1-EC2 —— `evaluate()` 采样守卫改降档，`confidence` 新增 `low`

**Files:**
- Modify: `aws-rightsizing/references/core.py:130-151`（守卫）、`:279`（confidence）
- Modify: `aws-rightsizing/references/report-template.md:295`（`enum-values` 块）、`:309`（confidence 语义行）
- Test: `aws-rightsizing/tests/test_fail_closed_contracts.py`

**Interfaces:**
- Consumes: 无（首个 Task）
- Produces: `evaluate()` 在 `0 < cpu_n < min_biz_hours_points` 时返回完整判据结果，`confidence == "low"`，且 `blockers` 含一条以 `样本 ` 开头、内含 `n` 与门限值的字符串。`cpu_n is None` 或 `== 0` 仍返回 `verdict == "insufficient-data"`。

- [ ] **Step 1: 写失败测试**

在 `aws-rightsizing/tests/test_fail_closed_contracts.py` 末尾（`if __name__` 之前）加：

```python
def test_low_sample_downgrades_instead_of_refusing():
    """样本不足不得拒绝出建议，只降 confidence 并写明样本量。

    旧行为：cpu_n < min_biz_hours_points ⇒ insufficient-data，连否决项
    都不跑。实测后果：两条真实健康事实被一句「点数不足」盖住。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    out = _evaluate(dict(RES, rid="i-LOW", cpu_n=floor - 1,
                         sus_cpu=5, peak_cpu=15, sus_mem=3, peak_mem=5,
                         ebs_need=1, surplus_credits=0), t)
    assert out["verdict"] != "insufficient-data", (
        f"样本不足仍应出判据结论，实际 {out['verdict']} —— {out}")
    assert out["confidence"] == "low", out
    blockers = " ".join(out.get("blockers") or [])
    assert "样本" in blockers and str(floor) in blockers, (
        f"blockers 未写明样本量与门限 —— {out.get('blockers')}")


def test_zero_and_missing_sample_stay_insufficient():
    """0 点与缺失是「无」不是「少」，仍须 fail-closed。"""
    t = core.load_thresholds("aggressive")
    for n in (0, None):
        out = _evaluate(dict(RES, rid=f"i-N{n}", cpu_n=n), t)
        assert out["verdict"] == "insufficient-data", (
            f"cpu_n={n!r} 必须 insufficient-data，实际 {out['verdict']}")
```

并把同文件第 85 行那条断言改为承认新契约。把：

```python
    assert ok["verdict"] == "insufficient-data", ok
```

改成：

```python
    # cpu_n=13 现在走降档而非拒绝（见 test_low_sample_downgrades_instead_of_refusing）；
    # 本测试的要点是「缺 min_biz_hours_points 必须抛 KeyError」，不是这条 verdict。
    assert ok["confidence"] == "low", ok
```

在文件底部的 `tests = [...]` 列表里补上两个新函数名。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd aws-rightsizing && python3 tests/test_fail_closed_contracts.py`
Expected: FAIL —— `test_low_sample_downgrades_instead_of_refusing` 报 `样本不足仍应出判据结论，实际 insufficient-data`

- [ ] **Step 3: 改 `core.py` 的守卫**

把 `references/core.py` 第 130–151 行整段：

```python
    # ---- 采样量守卫：必须在此短路，不能只写在文档里靠调用方自觉 ----
    # 阈值用下标取而非 .get()：注入的 thresholds 缺这个键时必须抛 KeyError。
    # 用 .get() 会让守卫静默消失，短窗口资源变成 downsize 并给出编造的节省额。
    n = res.get("cpu_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n < floor_pts:
        out["verdict"] = "insufficient-data"
        out["burst_na"] = f"biz-hours 仅 {n} 点 < {floor_pts}，p95 无统计意义"
```

替换为：

```python
    # ---- 采样量：分档而非拒绝 ----
    # 阈值用下标取而非 .get()：注入的 thresholds 缺这个键时必须抛 KeyError。
    # 用 .get() 会让分档静默消失。
    #
    # 「少」与「无」是两件事，走相反的路：
    #   n is None  —— 不知道有多少点，连降档都无从判断 ⇒ fail-closed
    #   n == 0     —— 零个点算不出 p95 ⇒ fail-closed
    #   0 < n < 门限 —— 数据少但存在 ⇒ 照常判据，confidence 降到 low
    # 旧行为（n < 门限即 return insufficient-data）连**否决项**一起压掉了：
    # 实测两条真实健康事实（MSK URP 27、Redis 复制延迟 23.88s）被一句
    # 「点数不足」盖住。采样量挡不住否决项——否决项读的是 max，不是 p95。
    n = res.get("cpu_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n == 0:
        out["verdict"] = "insufficient-data"
        out["burst_na"] = (f"biz-hours "
                           f"{'点数未知' if n is None else '0 点'}"
                           f"（门限 {floor_pts}），p95 无从计算")
```

紧随其后的 `cs = specs_by_type.get(itype)` 那段 best-effort 查表与 `return out` 保持不动。

在那个 `return out` 之后、`cs = specs_by_type.get(itype)`（第二次，非 best-effort 的那处）之前，插入：

```python
    low_sample = n < floor_pts
```

- [ ] **Step 4: 改 confidence 与 blocker**

把第 279 行：

```python
    out["confidence"] = "medium" if not mem_known else "high"
```

替换为：

```python
    # 样本量的问题盖过内存口径的问题：低样本一律 low，不再区分有无内存数据。
    if low_sample:
        out["confidence"] = "low"
        out.setdefault("blockers", []).append(
            f"样本 {n} 点 < {floor_pts}（占门限 {round(n / floor_pts * 100)}%），"
            f"p95 统计意义弱；建议按此执行但缩短观察期，窗口填满后复评；"
            f"变更时优先安排回滚演练")
    else:
        out["confidence"] = "medium" if not mem_known else "high"
```

- [ ] **Step 5: 改 `report-template.md` 的 confidence 契约**

`references/report-template.md` 第 295 行，把：

```
confidence:      high | medium | (empty)
```

改成：

```
confidence:      high | medium | low | (empty)
```

第 309 行整行替换。原文：

```
| `confidence` | `core.py` 的 `evaluate()` | **没有 `low`**；判定提前短路时留空。**采集侧自建行一律留空**——两个取值在 `evaluate()` 里由"有无内存数据"决定，采集侧没有这个输入，填任何值都是自造 |
```

新文：

```
| `confidence` | `core.py` 的 `evaluate()` | 三档：`high`（样本充足且有内存数据）／`medium`（样本充足、无内存数据）／`low`（`0 < cpu_n < min_biz_hours_points`，样本不足——此时不再区分内存口径，样本量的问题盖过它）。判定提前短路（`insufficient-data` / `spec-unknown` / `price-unknown` / `excluded` / `metric-missing`）时留空。**托管判据行留空**——`confidence` 的两个上档由 `evaluate()` 的「有无内存数据」决定，托管侧没有这个轴。**采集侧自建行一律留空**，填任何值都是自造 |
```

同文件第 404 行那条规则（`confidence=high` 且内存下降须附人工复核提示），把 `confidence=high` 改成 `confidence` 为 `high` 或 `low`：

```
- **`confidence` 为 `high` 或 `low`、且 `required_gib < cur_gib` 的行，报告正文必须附一句人工复核
```

- [ ] **Step 6: 跑全部测试**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf '%-42s' "$t"; python3 "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done`
Expected: `test_fail_closed_contracts.py` PASS、`test_csv_contract.py` PASS；`test_regression_fleet.py` **FAIL**（基线数字变了，Task 7 处理）。其余 PASS。

- [ ] **Step 7: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/references/core.py aws-rightsizing/references/report-template.md aws-rightsizing/tests/test_fail_closed_contracts.py
git commit -m "feat(core): low sample downgrades confidence instead of refusing a verdict

evaluate() used to return insufficient-data whenever cpu_n fell below
min_biz_hours_points, which also skipped every veto check. Now only a
missing or zero count fails closed; a small-but-present count gets the
full judgement plus confidence=low and a blocker naming the count.

test_regression_fleet is expected to fail until its baseline is
re-recorded; the two fixture rows below the floor now produce verdicts."
```

---

### Task 2: C1-托管 —— `dispatch()` 采样守卫改降档

**Files:**
- Modify: `aws-rightsizing/references/core.py:656-669`（`dispatch()` 的托管守卫）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py:320-352`

**Interfaces:**
- Consumes: Task 1 的 `low_sample` 语义（同一条门限、同一个键）
- Produces: `dispatch()` 对 `0 < sample_n < floor` 的托管资源返回该服务 evaluator 的完整结果，并在 `blockers` 追加以`样本 ` 开头的说明；`confidence` **不设置**。`sample_n is None` 或 `== 0` 仍返回 `verdict == "insufficient-data"`。

- [ ] **Step 1: 改测试**

`aws-rightsizing/tests/test_managed_dispatch.py` 第 320–352 行的 `test_managed_evaluators_have_sampling_guard` 整个函数替换为：

```python
def test_managed_low_sample_downgrades_instead_of_refusing():
    """托管三判据在样本不足时仍须跑完判据、报出否决项。

    旧行为：sample_n < floor ⇒ dispatch() 立即 return insufficient-data，
    连否决项都不跑。实测两条真实健康事实（MSK URP 27、Redis 复制延迟
    23.88s）因此被一句「点数不足」盖住 —— 而否决项读的是 max，不是 p95，
    采样量挡它没有依据。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = {
        "rds": dict(rid="db-X", service="rds", type="db.r6g.large", vcpu=2,
                    mem_gib=16, surplus_credits=0, dbload_p95=0.1,
                    freeable_mem_min_gib=8.0, cheaper_candidate_exists=True),
        "elasticache": dict(rid="cc-X", service="elasticache",
                            type="cache.m6g.large", vcpu=2, mem_gib=6.38,
                            evictions_sum=0, repl_lag_max=0.0,
                            engine_cpu_p95=1.0, db_mem_used_pct_max=2.0,
                            cheaper_candidate_exists=True),
        "msk": dict(rid="mk-X", service="msk", type="kafka.m7g.large",
                    under_replicated_max=0, disk_used_max=10.0,
                    handler_idle_p95=0.99, cpu_total_p95=3.0,
                    cheaper_candidate_exists=True),
    }
    for svc, res in cases.items():
        res["sample_n"] = floor - 1
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "downsize-candidate", (
            f"{svc}: 样本不足仍应跑完判据，实际 {got['verdict']} —— {got}")
        blockers = " ".join(got.get("blockers") or [])
        assert "样本" in blockers and str(floor) in blockers, (
            f"{svc}: blockers 未写明样本量与门限 —— {got.get('blockers')}")
        assert "confidence" not in got, (
            f"{svc}: 托管行不设 confidence（该列由 evaluate() 独占）—— {got}")
    for svc, res in cases.items():
        res["sample_n"] = floor
        got = core.dispatch(res, {"thresholds": t})
        assert "样本" not in " ".join(got.get("blockers") or []), (
            f"{svc}: 样本充足不应出现样本量 blocker —— {got}")


def test_managed_zero_sample_stays_insufficient():
    """0 点是「无」不是「少」，仍须 fail-closed（缺失那条见下一个测试）。"""
    t = core.load_thresholds("aggressive")
    res = dict(rid="mk-Z", service="msk", type="kafka.m7g.large",
               under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0, sample_n=0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "insufficient-data", got
```

在文件底部的 `tests = [...]` 列表里把旧函数名换成这两个新名字。
**`test_managed_missing_sample_n_is_insufficient_not_pass`（第 355 行）保持不动。**

- [ ] **Step 2: 跑测试确认失败**

Run: `cd aws-rightsizing && python3 tests/test_managed_dispatch.py`
Expected: FAIL —— `rds: 样本不足仍应跑完判据，实际 insufficient-data`

- [ ] **Step 3: 改 `dispatch()`**

把 `references/core.py` 第 656–669 行：

```python
    # ---- 托管侧采样量守卫：与 EC2 同一道门限，放这里而不是三个 evaluator 里 ----
    # 三份副本会各自漂移；dispatch 是唯一的托管入口。
    # 实测缺陷：某 MSK 集群 biz-hours 仅 14 点仍输出 downsize-candidate，
    # 两个 agent 都被迫在采集侧自己补这道守卫 —— 那正是本 skill 划归
    # core.py 的职责被推回调用方。
    t = ctx["thresholds"]
    n = res.get("sample_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n < floor_pts:
        return {"rid": res.get("rid"), "service": svc, "cur": res.get("type"),
                "verdict": "insufficient-data",
                "blockers": [f"主判据指标 biz-hours 仅 {n} 点 < {floor_pts}，"
                             f"p95 无统计意义，不产出任何建议"]}
    return MANAGED_EVALUATORS[svc](res, t)
```

替换为：

```python
    # ---- 托管侧采样量：分档而非拒绝，与 EC2 同一道门限 ----
    # 放这里而不是三个 evaluator 里：三份副本会各自漂移，dispatch 是唯一入口。
    #
    # 「少」与「无」走相反的路（与 evaluate() 一致）：
    #   sample_n is None / == 0 ⇒ fail-closed
    #   0 < sample_n < 门限      ⇒ 跑完判据，追加样本量 blocker
    # 旧行为在门限之下直接 return，**连否决项一起压掉**：实测
    # msk-prod-01 的 UnderReplicatedPartitions=27 与
    # redis-uat-02 的 ReplicationLag=23.88s 都因此没出现在
    # 报告里，报告只写了「点数不足」。否决项读的是 max，采样量挡它没有依据。
    #
    # 托管行**不设 confidence**：该列的两个上档由 evaluate() 的「有无内存
    # 数据」决定，托管侧没有这个轴（见 report-template.md 的契约表）。
    t = ctx["thresholds"]
    n = res.get("sample_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n == 0:
        return {"rid": res.get("rid"), "service": svc, "cur": res.get("type"),
                "verdict": "insufficient-data",
                "blockers": [f"主判据指标 biz-hours "
                             f"{'点数未知' if n is None else '0 点'}"
                             f"（门限 {floor_pts}），p95 无从计算，"
                             f"不产出任何建议"]}
    out = MANAGED_EVALUATORS[svc](res, t)
    if n < floor_pts:
        out.setdefault("blockers", []).append(
            f"样本 {n} 点 < {floor_pts}（占门限 {round(n / floor_pts * 100)}%），"
            f"p95 统计意义弱；建议按此执行但缩短观察期，窗口填满后复评；"
            f"变更时优先安排回滚演练")
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd aws-rightsizing && python3 tests/test_managed_dispatch.py`
Expected: PASS（全部函数）

- [ ] **Step 5: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/references/core.py aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "feat(core): managed dispatch downgrades on low sample instead of refusing

The managed guard returned insufficient-data below the floor, which
skipped the veto checks too. Now only a missing or zero sample_n fails
closed. Managed rows deliberately do not carry confidence; the column's
upper tiers come from evaluate()'s memory axis, which managed judgements
do not have."
```

---

### Task 3: C2 —— 三条否决项改判持续态

**Files:**
- Modify: `aws-rightsizing/references/core.py`（`eval_elasticache` 的 `evictions` 与 `repl_lag` 否决、`eval_msk` 的 `urp` 否决）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: Task 2 的 `dispatch()`（三个 evaluator 的调用方不变）
- Produces: 三个可选输入 `under_replicated_p95` / `repl_lag_p95` / `evictions_p95`。判定用 `p95 if p95 is not None else max`；`p95` 未越界而 `max` 越界时**不否决**，`blockers` 追加一条含 `单次尖峰` 字样与 max 值的说明。三个字段全缺时行为与改动前逐字节相同。

- [ ] **Step 1: 写失败测试**

在 `aws-rightsizing/tests/test_managed_dispatch.py` 末尾（`if __name__` 之前）加：

```python
def test_vetoes_judge_persistence_not_a_single_spike():
    """三条否决项判持续态，不判「曾经出现过」。

    实测（123456789012/ap-east-1）：8 个 MSK 集群的
    UnderReplicatedPartitions Average 序列 p95 全为 0，而 max 达 27–244。
    MSK 自动打补丁做滚动重启，重启期间副本必然短暂落后 ⇒ 旧判据会在
    任何被维护过的集群上误阻断。ElastiCache 的 ReplicationLag 同形状
    （p95 0.001–0.005s，max 10.2s / 23.9s）。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    lag_limit = t["redis_repl_lag_max_s"]

    # MSK：URP 尖峰 244，持续值 0 ⇒ 不否决，但尖峰必须可见
    msk = dict(rid="mk-spike", service="msk", type="kafka.m7g.large",
               under_replicated_max=244.0, under_replicated_p95=0.0,
               disk_used_max=10.0, handler_idle_p95=0.99, cpu_total_p95=3.0,
               cheaper_candidate_exists=True, sample_n=floor)
    got = core.dispatch(msk, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"URP 持续值为 0 不应否决，实际 {got['verdict']} —— {got}")
    assert "单次尖峰" in " ".join(got["blockers"]) and "244" in " ".join(got["blockers"]), (
        f"尖峰未写进 blockers，维护事件被藏起来了 —— {got['blockers']}")

    # MSK：持续值也越界 ⇒ 照旧否决
    got = core.dispatch(dict(msk, under_replicated_p95=3.0),
                        {"thresholds": t})
    assert got["verdict"] == "blocked", got

    # ElastiCache ReplicationLag：尖峰 23.88s，持续值 0.005s ⇒ 不否决
    ec = dict(rid="cc-spike", service="elasticache", type="cache.t4g.medium",
              vcpu=2, mem_gib=3.09, evictions_sum=0.0, evictions_p95=0.0,
              repl_lag_max=23.882, repl_lag_p95=0.005,
              engine_cpu_p95=0.64, db_mem_used_pct_max=59.24,
              cheaper_candidate_exists=True, sample_n=floor)
    got = core.dispatch(ec, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"复制延迟持续值 0.005s 不应否决，实际 {got['verdict']} —— {got}")
    assert "23.882" in " ".join(got["blockers"]), got["blockers"]

    # ElastiCache：持续延迟越界 ⇒ 照旧否决
    got = core.dispatch(dict(ec, repl_lag_p95=lag_limit + 1),
                        {"thresholds": t})
    assert got["verdict"] == "blocked", got

    # ElastiCache Evictions：尖峰有、持续无 ⇒ 不否决
    got = core.dispatch(dict(ec, evictions_sum=17.0, evictions_p95=0.0),
                        {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", got
    assert "17" in " ".join(got["blockers"]), got["blockers"]

    # ElastiCache：持续驱逐 ⇒ 照旧否决
    got = core.dispatch(dict(ec, evictions_sum=17.0, evictions_p95=2.0),
                        {"thresholds": t})
    assert got["verdict"] == "blocked", got


def test_persistence_fields_absent_keeps_old_behaviour():
    """采集侧未升级（只送 *_max）时，行为与改动前逐字节相同。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    msk = dict(rid="mk-old", service="msk", type="kafka.m7g.large",
               under_replicated_max=244.0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0,
               cheaper_candidate_exists=True, sample_n=floor)
    assert core.dispatch(msk, {"thresholds": t})["verdict"] == "blocked"
    ec = dict(rid="cc-old", service="elasticache", type="cache.t4g.medium",
              vcpu=2, mem_gib=3.09, evictions_sum=0.0, repl_lag_max=23.882,
              engine_cpu_p95=0.64, db_mem_used_pct_max=59.24,
              cheaper_candidate_exists=True, sample_n=floor)
    assert core.dispatch(ec, {"thresholds": t})["verdict"] == "blocked"
```

在底部 `tests = [...]` 里补这两个函数名。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd aws-rightsizing && python3 tests/test_managed_dispatch.py`
Expected: FAIL —— `URP 持续值为 0 不应否决，实际 blocked`

- [ ] **Step 3: 加持续态辅助函数**

在 `references/core.py` 的 `_rds_is_burstable` 定义之前插入：

```python
def _persistent(res, p95_key, max_key):
    """返回 (用于否决的持续值, 尖峰值)。

    否决项要判「持续成立」而不是「曾经出现过一次」。实测
    （123456789012/ap-east-1）：8 个 MSK 集群的 UnderReplicatedPartitions
    Average 序列 p95 全为 0，而 max 达 27–244 —— MSK 自动打补丁做滚动重启，
    重启期间副本必然短暂落后。按 max 否决等于在任何被维护过的集群上
    永久关闭降配路径。ElastiCache 的 ReplicationLag 同形状。

    `*_p95` 缺失时回退到 `*_max`：采集侧未升级时行为与改动前完全相同
    （fail-closed 且向后兼容）。
    """
    p95 = res.get(p95_key)
    mx = res.get(max_key)
    return (mx if p95 is None else p95), mx


def _spike_note(label, mx, cause):
    return (f"{label} 持续值（p95）未越界，但窗口内曾达 {mx}（单次尖峰，"
            f"常见成因：{cause}）。降配前确认该尖峰非容量不足所致")
```

- [ ] **Step 4: 改 `eval_elasticache` 的两条否决**

把 `eval_elasticache` 里：

```python
    ev = res.get("evictions_sum")
    if ev is None:
        out.update(verdict="metric-missing", blockers=["Evictions 缺失"])
        return out
    if ev > 0:
        out.update(verdict="blocked",
                   blockers=[f"Evictions 单小时最大 {ev} > 0（采 Maximum，不是窗口累计；判据是 > 0，两种口径等价），内存已不足，降配更糟"])
        return out
    lag = res.get("repl_lag_max")
    if lag is not None and lag >= t["redis_repl_lag_max_s"]:
        out.update(verdict="blocked", blockers=[f"ReplicationLag max {lag}s >= {t['redis_repl_lag_max_s']}s"])
        return out
```

替换为：

```python
    ev_persist, ev_max = _persistent(res, "evictions_p95", "evictions_sum")
    if ev_persist is None:
        out.update(verdict="metric-missing", blockers=["Evictions 缺失"])
        return out
    if ev_persist > 0:
        out.update(verdict="blocked",
                   blockers=[f"Evictions 持续值 {ev_persist} > 0（窗口内最大 "
                             f"{ev_max}），内存已不足，降配更糟"])
        return out
    if ev_max is not None and ev_max > 0:
        out["blockers"].append(_spike_note("Evictions", ev_max,
                                           "短时热点 / 批量写入"))
    lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
    if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:
        out.update(verdict="blocked",
                   blockers=[f"ReplicationLag 持续值 {lag_persist}s >= "
                             f"{t['redis_repl_lag_max_s']}s（窗口内最大 {lag_max}s）"])
        return out
    if lag_max is not None and lag_max >= t["redis_repl_lag_max_s"]:
        out["blockers"].append(_spike_note("ReplicationLag", f"{lag_max}s",
                                           "failover / 备份快照"))
```

- [ ] **Step 5: 改 `eval_msk` 的 URP 否决**

把 `eval_msk` 里：

```python
    urp = res.get("under_replicated_max")
    if urp is None:
        out.update(verdict="metric-missing",
                   blockers=["UnderReplicatedPartitions 缺失。**不要因此去提 EnhancedMonitoring**——实测 DEFAULT 档该指标 per-broker 就有（见 metrics-catalog.md）；缺失另有原因，先查维度值与集群状态"])
        return out
    if urp > 0:
        out.update(verdict="blocked", blockers=[f"UnderReplicatedPartitions {urp} > 0"])
        return out
```

替换为：

```python
    urp_persist, urp_max = _persistent(res, "under_replicated_p95",
                                       "under_replicated_max")
    if urp_persist is None:
        out.update(verdict="metric-missing",
                   blockers=["UnderReplicatedPartitions 缺失。**不要因此去提 EnhancedMonitoring**——实测 DEFAULT 档该指标 per-broker 就有（见 metrics-catalog.md）；缺失另有原因，先查维度值与集群状态"])
        return out
    if urp_persist > 0:
        out.update(verdict="blocked",
                   blockers=[f"UnderReplicatedPartitions 持续值 {urp_persist} > 0"
                             f"（窗口内最大 {urp_max}）"])
        return out
    if urp_max is not None and urp_max > 0:
        out["blockers"].append(_spike_note("UnderReplicatedPartitions", urp_max,
                                           "broker 滚动重启 / 自动打补丁"))
```

- [ ] **Step 6: 跑全部测试**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf '%-42s' "$t"; python3 "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done`
Expected: 除 `test_regression_fleet.py`（Task 7 处理）外全 PASS

- [ ] **Step 7: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/references/core.py aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "feat(core): vetoes judge persistence, not a single spike

MSK under_replicated, ElastiCache evictions and replication lag all
vetoed on the window max, so one rolling restart shut the downsize path
for 30 days. All eight MSK clusters in the reference account show an
Average-series p95 of 0 against a max of 27-244.

Each veto now reads an optional *_p95 input and falls back to *_max when
absent, so an un-upgraded collection side behaves identically. A spike
that clears the persistent test no longer vetoes but is always recorded
in blockers -- maintenance events stay visible."
```

---

### Task 4: C3 —— `cheaper_candidate_exists` 未校验标记

**Files:**
- Modify: `aws-rightsizing/references/core.py`（三个 evaluator 的 `downsize-candidate` 分支）
- Modify: `aws-rightsizing/references/sample-solve.md`（字段语义表）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: Task 3 的三个 evaluator
- Produces: 每个 `verdict == "downsize-candidate"` 的托管行，`blockers` 必含 `未经校验` 字样。

- [ ] **Step 1: 写失败测试**

在 `aws-rightsizing/tests/test_managed_dispatch.py` 末尾加：

```python
def test_downsize_candidate_flags_unverified_fit():
    """候选 ≠ 有钱可省。cheaper_candidate_exists 只按价格判，不校验装得下。

    实测：redis-uat-02（cache.t4g.medium×4）该字段为 true，
    但内存已用到 maxmemory 的 59.24% ⇒ 需节点内存 >= 1.830 GiB，而同架构下
    更便宜的 cache.t4g.small 可用内存只有 1.028 GiB ⇒ 实际可省 $0。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = [
        dict(rid="db-F", service="rds", type="db.r6g.large", vcpu=2,
             mem_gib=16, surplus_credits=0, dbload_p95=0.1,
             freeable_mem_min_gib=8.0, cheaper_candidate_exists=True,
             sample_n=floor),
        dict(rid="cc-F", service="elasticache", type="cache.m6g.large",
             vcpu=2, mem_gib=6.38, evictions_sum=0, repl_lag_max=0.0,
             engine_cpu_p95=1.0, db_mem_used_pct_max=2.0,
             cheaper_candidate_exists=True, sample_n=floor),
        dict(rid="mk-F", service="msk", type="kafka.m7g.large",
             under_replicated_max=0, disk_used_max=10.0,
             handler_idle_p95=0.99, cpu_total_p95=3.0,
             cheaper_candidate_exists=True, sample_n=floor),
    ]
    for res in cases:
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "downsize-candidate", got
        assert "未经校验" in " ".join(got["blockers"]), (
            f"{res['service']}: downsize-candidate 未标注适配性未校验 —— "
            f"{got['blockers']}")
```

在底部 `tests = [...]` 里补该函数名。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd aws-rightsizing && python3 tests/test_managed_dispatch.py`
Expected: FAIL —— `rds: downsize-candidate 未标注适配性未校验`

- [ ] **Step 3: 加常量与追加逻辑**

在 `references/core.py` 的 `_persistent` 定义之前插入：

```python
# cheaper_candidate_exists 由采集侧按**价格**判定，不校验候选是否装得下
# 当前需求。实测：一个 cache.t4g.medium 复制组该字段为 true，但内存已用到
# maxmemory 的 59.24%，同架构下更便宜的两个候选都装不下 ⇒ 实际可省 $0。
# 不把适配校验复制到采集侧（那会造出第二个判据实现点），改为在结论上标注。
_FIT_UNVERIFIED = ("更便宜候选是否装得下当前需求未经校验"
                   "（cheaper_candidate_exists 只按价格判定）；"
                   "目标规格须人工确认，可能不存在满足需求的更便宜机型")
```

在三个 evaluator 的 `downsize-candidate` 分支的 `blockers` 列表末尾各加一项 `_FIT_UNVERIFIED`：

`eval_rds` 结尾：

```python
    out.update(verdict="downsize-candidate",
               blockers=["需变更窗口 + 回滚预案；存储不可缩容，过度预配只能 next-rebuild",
                         _FIT_UNVERIFIED])
    return out
```

`eval_elasticache` 结尾：

```python
    out.update(verdict="downsize-candidate",
               blockers=[f"候选 node type 扣掉 reserved-memory-percent "
                         f"{reserved * 100:.0f}% 后的可用内存须 >= "
                         f"{out['required_gib_usable']} GiB"
                         f"（该值＝当前节点已用的可用内存，未含增长余量）",
                         "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）",
                         _FIT_UNVERIFIED])
    return out
```

**注意 `eval_elasticache` 的 `out.update(blockers=[...])` 会覆盖 Task 3 追加的尖峰说明。** 改成保留已有项：

```python
    out["blockers"].extend([
        f"候选 node type 扣掉 reserved-memory-percent "
        f"{reserved * 100:.0f}% 后的可用内存须 >= "
        f"{out['required_gib_usable']} GiB"
        f"（该值＝当前节点已用的可用内存，未含增长余量）",
        "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）",
        _FIT_UNVERIFIED])
    out["verdict"] = "downsize-candidate"
    return out
```

`eval_msk` 结尾同样改成 `extend` 以保住尖峰说明：

```python
    out["blockers"].extend([
        "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
        "不产出减 broker 数建议（需 partition 重分配，属架构级）",
        _FIT_UNVERIFIED])
    out["verdict"] = "downsize-candidate"
    return out
```

- [ ] **Step 4: 改 `sample-solve.md` 的字段语义**

`references/sample-solve.md` 的字段语义表里，`cheaper_candidate_exists` 那一行的含义列，把：

```
同形态下是否存在更便宜的机型。
```

改成：

```
同形态下是否存在更便宜的机型。**仅按价格判定，不含规格适配校验**——该候选可能装不下当前需求（实测：一个 cache.t4g.medium 复制组此字段为 true，但更便宜的候选都装不下已用内存，实际可省 $0）。因此 `downsize-candidate` 不保证有钱可省，`core.py` 会在 `blockers` 里标注适配性未校验。
```

- [ ] **Step 5: 跑全部测试**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf '%-42s' "$t"; python3 "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done`
Expected: 除 `test_regression_fleet.py` 外全 PASS

- [ ] **Step 6: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/references/core.py aws-rightsizing/references/sample-solve.md aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "feat(core): mark downsize-candidate rows as fit-unverified

cheaper_candidate_exists is judged on price alone, so the verdict does
not imply an achievable saving. Rather than duplicating the fit check
into the collection side -- which would create a second judgement
implementation -- every managed downsize-candidate now carries a blocker
saying the fit is unverified."
```

---

### Task 5: `agg.jq` 增发 full-window 档

**Files:**
- Modify: `aws-rightsizing/references/agg.jq:36-47`
- Test: `aws-rightsizing/tests/test_agg_full_window.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `agg.jq` 对每个 (resource, stat) 额外输出一行 `bucket == "full-window"`，其 `n` 等于三档之和，`p95` / `mean` / `max` / `min` 基于全部点计算。

- [ ] **Step 1: 写失败测试**

新建 `aws-rightsizing/tests/test_agg_full_window.py`：

```python
"""agg.jq 必须产出真正的 full-window 档。

§2.6 此前用 jq 把三档的 n 相加、max 取 max 来近似全窗口。这对 n 与 max
成立，**对 p95 与 mean 不成立**：并集的 p95 不等于各档 p95 的 max。
否决项改判持续态后需要真正的全窗口 p95，所以这一档必须由 agg.jq 出。
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).parent.parent
AGG = ROOT / "references" / "agg.jq"

# 4 个点，跨 biz-hours 与 off-hours 两档（UTC+8）：
#   2026-08-10T02:00Z = 10:00 本地 → biz-hours
#   2026-08-10T03:00Z = 11:00 本地 → biz-hours
#   2026-08-10T14:00Z = 22:00 本地 → off-hours
#   2026-08-10T15:00Z = 23:00 本地 → off-hours
PAYLOAD = {"MetricDataResults": [{
    "Label": "r-1|t3.medium|Average",
    "Timestamps": ["2026-08-10T02:00:00Z", "2026-08-10T03:00:00Z",
                   "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z"],
    "Values": [1.0, 2.0, 3.0, 100.0]}]}


def _run():
    p = subprocess.run(["jq", "-r", "--argjson", "tz", "28800", "-f", str(AGG)],
                       input=json.dumps(PAYLOAD), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_full_window_bucket_is_emitted():
    rows = {r["bucket"]: r for r in _run()}
    assert "full-window" in rows, f"缺 full-window 档：{sorted(rows)}"
    fw = rows["full-window"]
    assert fw["n"] == 4, fw
    assert fw["max"] == 100.0 and fw["min"] == 1.0, fw
    assert abs(fw["mean"] - 26.5) < 1e-9, fw


def test_full_window_p95_is_not_the_max_of_per_band_p95():
    """本不变式是这一档存在的理由：并集 p95 ≠ 各档 p95 的 max。"""
    rows = {r["bucket"]: r for r in _run()}
    per_band_max = max(rows["biz-hours"]["p95"], rows["off-hours"]["p95"])
    assert rows["full-window"]["p95"] == 100.0, rows["full-window"]
    assert per_band_max == 2.0, rows
    assert rows["full-window"]["p95"] != per_band_max


def test_three_bands_unchanged():
    rows = {r["bucket"]: r for r in _run()}
    assert rows["biz-hours"]["n"] == 2 and rows["off-hours"]["n"] == 2, rows
    assert "weekend" not in rows, "无 weekend 点时不应凭空产出该档"


if __name__ == "__main__":
    tests = [test_full_window_bucket_is_emitted,
             test_full_window_p95_is_not_the_max_of_per_band_p95,
             test_three_bands_unchanged]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"✓ {fn.__name__}")
        except Exception as e:
            print(f"✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd aws-rightsizing && python3 tests/test_agg_full_window.py`
Expected: FAIL —— `缺 full-window 档：['biz-hours', 'off-hours']`

- [ ] **Step 3: 改 `agg.jq`**

把 `references/agg.jq` 第 35–47 行（`.rid as $rid` 开始到文件末尾的 `]`）：

```
  | .rid as $rid | .itype as $it | .stat as $st
  | ( .pts | group_by(.b)[]
      | { rid: $rid, itype: $it, stat: $st, bucket: .[0].b, n: length,
```

替换为在三档之后追加一个全量组。整段改为：

```
  | .rid as $rid | .itype as $it | .stat as $st
  # 三档 + 一个 full-window 档。full-window 不是三档的算术合并：
  # n 与 max 可以合并，但 **p95 与 mean 不行**（并集的 p95 ≠ 各档 p95 的 max）。
  # 否决项判持续态要的正是全窗口 p95，所以这一档必须在这里出。
  | ( ( [ { b: "full-window", pts: .pts } ]
        + ( .pts | group_by(.b) | map({ b: .[0].b, pts: . }) ) )[]
      | { rid: $rid, itype: $it, stat: $st, bucket: .b, n: (.pts | length),
          mean: ((.pts | map(.v) | add) / (.pts | length)),
          p95:  (.pts | map(.v) | pct(0.95)),
          max:  (.pts | map(.v) | max),
          # min 是给"下限型"判据用的：RDS 的 FreeableMemory 阻断
          # （最小值 < 实例内存的 rds_freeable_mem_floor_pct% ⇒ 降配会 OOM）、
          # burstable 的 CPUCreditBalance
          # 是否触底。这类判据要的是窗口最小值，不是 max/p95，用后者会反向误判。
          # 采集时须对这些指标显式加 Stat=Minimum（见 mdq-multi.jq 的 "stats"），
          # 否则这里算的是"每小时均值的最小值"，仍会高于真实低点。
          min:  (.pts | map(.v) | min) } ) ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd aws-rightsizing && python3 tests/test_agg_full_window.py`
Expected: PASS（3/3）

- [ ] **Step 5: 确认三档消费方不被新档破坏**

Run:
```bash
cd ~/Downloads/123456789012-ap-east-1-20260909/raw/metrics
jq -r --argjson tz 28800 -f ~/git/aws-cost-optimization-skill/aws-rightsizing/references/agg.jq raw-msk.json \
  | jq -r 'group_by(.bucket)|map({bucket:.[0].bucket,rows:length})'
```
Expected: 四个 bucket，`full-window` 的 rows 等于其余三档各自的 rows（每序列一行）

- [ ] **Step 6: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/references/agg.jq aws-rightsizing/tests/test_agg_full_window.py
git commit -m "feat(agg): emit a real full-window bucket

Section 2.6 approximated the full window by summing per-band n and
taking the max of per-band max. That works for n and max but not for
p95 or mean -- the p95 of a union is not the max of per-band p95s. The
persistence-based vetoes need a genuine full-window p95."
```

---

### Task 6: 文档 —— `SKILL.md`、`thresholds.json` 注释、`cli-recipes.md`、`sample-solve.md` fixture、`report-template.md` 低样本呈现

**Files:**
- Modify: `aws-rightsizing/SKILL.md`（护栏那节 + 易错项速查表）
- Modify: `aws-rightsizing/references/thresholds.json`（`_comment`）
- Modify: `aws-rightsizing/references/cli-recipes.md`（ElastiCache 两个 stat、三个新字段组装、`freeable_mem_min_gib` 改全窗口、§2.6 改用 full-window 档）
- Modify: `aws-rightsizing/references/sample-solve.md`（输入块加一条 0 点资源 + 输出块）
- Modify: `aws-rightsizing/references/report-template.md`（低样本呈现规则 + 摘要 breakout）
- Test: `aws-rightsizing/tests/test_sample_reproduces.py`

**Interfaces:**
- Consumes: Task 1–5
- Produces: `sample-solve.md` 的输入块含 5 条资源，其 verdict 集合仍为四个documented 值。

- [ ] **Step 1: 改 `sample-solve.md` 的 fixture（`i-EX-04` 不再是 insufficient-data）**

`i-EX-04`（`cpu_n: 154`）改动后变成 `downsize` + `confidence=low`，四 verdict 里
`insufficient-data` 会消失。在 `references/sample-solve.md` 的**两处** JSON 块
（「输入：solver-in.json」与「调用」里的 `solver-ctx.json`）的 `resources` 数组末尾各加一条：

```json
 {"rid":"i-EX-05","service":"ec2","type":"m5.xlarge","arch":"x86_64","operation":"RunInstances",
  "sus_cpu":2,"peak_cpu":5,"sus_mem":10,"peak_mem":15,
  "ebs_need":1,"surplus_credits":0,"cpu_n":0,"metric_coverage":[]}
```

并把「输出：四个 verdict 必须全部出现」那一节的期望块改为：

```
i-EX-01  verdict=downsize           nb=m5.large  save=90.52  missing=[]   confidence=high
i-EX-02  verdict=metric-missing     nb=-         save=-      missing=[ebs]
i-EX-03  verdict=spec-unknown       nb=-         save=-      missing=[]
i-EX-04  verdict=downsize           nb=m5.large  save=90.52  missing=[]   confidence=low
i-EX-05  verdict=insufficient-data  nb=-         save=-      missing=[]
```

并把「逐条为什么」表里 `i-EX-04` 那行改为：

```
| `i-EX-04` | `downsize` + `confidence=low` | `cpu_n=154`（实测值，来自一台窗口内新建的实例）低于 `min_biz_hours_points` ⇒ p95 统计意义弱，但**样本少不等于不能判断**：照常出建议并降置信度，`blockers` 写明样本量。改动前这里是 `insufficient-data`，连否决项一起被压掉 |
| `i-EX-05` | `insufficient-data` | `cpu_n=0`。**零个点算不出 p95，是「无」不是「少」** ⇒ fail-closed。这是本样例里 `insufficient-data` 分支的唯一来源，删掉它该分支即不可达 |
```

- [ ] **Step 2: 跑 sample 自检确认通过**

Run: `cd aws-rightsizing && python3 tests/test_sample_reproduces.py`
Expected: PASS —— verdict 集合仍为 `{downsize, metric-missing, spec-unknown, insufficient-data}`

- [ ] **Step 3: 改 `thresholds.json` 的 `_comment`**

把 `_comment` 值改为：

```
"唯一真值源。散文文档不得复述这里的数值，只能引用键名。min_biz_hours_points 是**置信度分档线**不是拒绝线：0 < n < 该值 ⇒ 照常判据 + confidence=low；n 为 0 或缺失才 fail-closed。它**不适用于 is_idle 与 is_stop_candidate**——那两条的动作是删除与停机，不可回滚，保持硬门限。"
```

- [ ] **Step 4: 改 `SKILL.md` 护栏那节**

把护栏里这一行：

```
- `biz-hours` 采样点数低于 `min_biz_hours_points` ⇒ 标
  `insufficient-data`，不产出降配建议。
```

替换为：

```
- **采样量决定置信度，不决定给不给建议。** `0 < biz-hours 点数 <
  `min_biz_hours_points`` ⇒ 照常产出降配建议，`confidence=low`，
  `blockers` 写明样本量与占门限比例。点数为 `0` 或缺失才标
  `insufficient-data`（那是「无」不是「少」，p95 无从计算）。
  **该分档只作用于降配路径**：`is_idle`（动作是删除）与
  `is_stop_candidate`（动作是停机）保持硬门限——可回滚的动作允许
  低置信度产出，不可回滚的不允许。
```

- [ ] **Step 5: `SKILL.md` 易错项速查表补两行**

在易错项速查表末尾加：

```
| **否决项判「曾经出现过」而不是「持续成立」** | 一次滚动重启的尖峰否决整个 30 天窗口。实测 8 个 MSK 集群 `UnderReplicatedPartitions` 的 Average 序列 p95 **全为 0**，而 max 达 27–244（MSK 自动打补丁必然产生尖峰）⇒ 任何被维护过的集群降配路径永久关闭 | 判 `*_p95`（全窗口 Average／计数类用 Sum），`*_max` 只写进 `blockers` 让尖峰可见；`*_p95` 缺失时回退 `*_max` 保持向后兼容 |
| **下限型指标只取 `biz-hours` 档** | `freeable_mem_min_gib` 取 biz-hours 最小值会漏掉备份/批处理窗口的真实低点（实测两台 RDS 偏高 0.18% 与 1.1%），方向是「把危险实例判成安全」 | 下限型与峰值型指标一律取 **full-window** 档（`agg.jq` 已增发该档） |
```

- [ ] **Step 6: 改 `cli-recipes.md`**

三处改动：

1. ElastiCache 的 metrics 数组里，给 `ReplicationLag` 加 `Average`、给 `Evictions` 加 `Sum`（现在两者都只采 `Maximum`）：

```
  {"ns":"AWS/ElastiCache","mn":"ReplicationLag","dim":"CacheClusterId","stats":["Average","Maximum"]},
  {"ns":"AWS/ElastiCache","mn":"Evictions","dim":"CacheClusterId","stats":["Sum","Maximum"]},
```

`Evictions` 用 `Sum` 而非 `Average`：它是计数类，p95 of 小时 `Sum` 直接回答
「有超过 5% 的小时发生过驱逐吗」；`Average` 对计数类需要换算系数，本 skill 在
那个系数上错过三次。

2. §7 的托管行组装，三个新字段各取 **full-window 档**：

```
under_replicated_p95  = UnderReplicatedPartitions / Average / full-window 的 p95
repl_lag_p95          = ReplicationLag            / Average / full-window 的 p95
evictions_p95         = Evictions                 / Sum     / full-window 的 p95
freeable_mem_min_gib  = FreeableMemory            / Minimum / full-window 的 min   ← 改：原为 biz-hours
```

3. §2.6 里那段用 jq 把三档 `n` 相加、`max` 取 max 的全窗口近似，改为直接读
`agg.jq` 的 `bucket == "full-window"` 行，并注明：近似式对 `n`/`max` 成立、
对 `p95`/`mean` 不成立，所以持续态判据必须用真档。

- [ ] **Step 7: 改 `report-template.md` 的低样本呈现规则**

在「字段规则」那节加两条：

```
- **`confidence=low` 的行必须在报告正文标注样本量。** `core.py` 已把
  「样本 N 点 < 门限（占 X%）」写进 `blockers`，报告不得省略该句——它是读者
  判断这条建议可信度的唯一线索。
- **摘要的四条口径照常包含 `confidence=low` 的行，但必须另给一行 breakout：**
  「其中 `confidence=low` 贡献 $X（占该口径 Y%）」。低样本行进头条是刻意的
  （样本少不等于不给建议），breakout 让读者知道成分而不必翻 CSV。
```

同文件「采集侧自建行的字段填法」表里，`EC2 running（判据行，作对照）` 与
`RDS / ElastiCache / MSK（判据行，作对照）` 两行的 `confidence` 一列保持
`core.py` 产出／留空不变（托管行仍留空）。

- [ ] **Step 8: 跑全部测试**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf '%-42s' "$t"; python3 "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done`
Expected: 除 `test_regression_fleet.py` 外全 PASS

- [ ] **Step 9: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/SKILL.md aws-rightsizing/references/thresholds.json aws-rightsizing/references/cli-recipes.md aws-rightsizing/references/sample-solve.md aws-rightsizing/references/report-template.md
git commit -m "docs: record the sampling and persistence contracts

SKILL.md guardrail rewritten: sample size sets confidence, not whether a
recommendation is produced, and the downgrade applies to the downsize
path only. sample-solve.md gains a zero-point resource so the
insufficient-data branch stays reachable now that cpu_n=154 downgrades
instead. cli-recipes adds the Average/Sum stats the persistence vetoes
need and moves the floor-type metrics to the full-window bucket."
```

---

### Task 7: 重定回归基线

**Files:**
- Modify: `aws-rightsizing/tests/test_regression_fleet.py:26-70`（基线迁移注释 + `EXPECTED`）、`:134-144`（守卫断言）

**Interfaces:**
- Consumes: Task 1–6 的全部行为改动
- Produces: 8 个测试文件全绿。

- [ ] **Step 1: 改基线迁移注释**

在 `EXPECTED` 之前的注释块末尾（`# ────` 分隔线之前）插入：

```
# ── 基线迁移记录：2026-09-09，采样守卫改置信度分档 ──────────────────────
# 旧值（**已撤回，但保留在此**）：
#     aggressive   route1_nb = 401.51   route2_max = 534.01
#                  verdicts  = downsize 11, insufficient-data 2
#     conservative route1_nb = 312.48   route2_max = 395.26
#                  verdicts  = downsize 10, insufficient-data 2, 已合理配置 1
# 新值（本文件 EXPECTED 的当前内容）：
#     aggressive   route1_nb = 527.15   route2_max = 668.85
#                  verdicts  = downsize 13
#     conservative route1_nb = 373.00   route2_max = 492.72
#                  verdicts  = downsize 12, 已合理配置 1
#
# 成因：`min_biz_hours_points` 从「拒绝线」改为「置信度分档线」。fixture 里
# i-EX-03（cpu_n=55）与 i-EX-07（cpu_n=154）不再被拒绝，改为出建议 +
# confidence=low。逐条对账：
#   aggressive   i-EX-03 → r6g.large  nb +65.12  b +27.74
#                i-EX-07 → m6g.large  nb +60.52  b +69.72
#                route1 401.51 + 65.12 + 60.52 = 527.15
#                route2 534.01 + 27.74 + 69.72 = 631.47 ≠ 668.85 —— 差额来自
#                路线二逐条取 max(nb, b)：i-EX-03 取 nb 65.12（>27.74）、
#                i-EX-07 取 b 69.72，即 534.01 + 65.12 + 69.72 = 668.85
#   conservative i-EX-03 无 non-burstable 候选（nb=None），只贡献 b 27.74
#                i-EX-07 → m6g.large  nb +60.52  b +69.72
#                route1 312.48 + 60.52 = 373.00
#                route2 395.26 + 27.74 + 69.72 = 492.72
#
# ⚠️ **$527.15 这个数字在本仓库历史上被标注为「已作废」，它的重现不是回归。**
# 当年那份坏 fixture 把每台的 cpu_n 填成 720（全窗口点数），守卫因此从未触发，
# 13 台全部被判据 ⇒ 得 527.15。现在守卫改成降档，13 台又全部被判据 ⇒ 回到
# 同一个数。两者的**总额相同而成因相反**：一个是守卫失效，一个是守卫改成
# 分档。判别式：现在 i-EX-03 与 i-EX-07 的 confidence 必须是 `low`
# （见 test_sampling_downgrade_actually_fires_on_this_fixture），
# 而坏 fixture 那次它们是 `high`。
# ─────────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: 改 `EXPECTED`**

```python
EXPECTED = {
    "aggressive": {
        "rows": 13,
        "verdicts": {"downsize": 13},
        "buckets": {"downsize": 13},
        "route1_nb": 527.15,      # Σ nb_save_mo，一律取 non-burstable
        "route2_max": 668.85,     # Σ max(nb, b)，逐条取更省者
    },
    "conservative": {
        "rows": 13,
        "verdicts": {"downsize": 12, "已合理配置": 1},
        "buckets": {"downsize": 12, "excluded": 1},
        "route1_nb": 373.00,
        "route2_max": 492.72,
    },
}
```

- [ ] **Step 3: 改守卫断言**

把 `test_sampling_guard_actually_fires_on_this_fixture`（第 134–144 行）整个函数替换为：

```python
def test_sampling_downgrade_actually_fires_on_this_fixture():
    """至少有一条资源走了降档路径。全过的 fixture 守不住「分档失效」这类缺陷。

    这条断言同时是 $527.15 的判别式：本文件的基线迁移注释解释了为什么这个
    被撤回过的数字会重现——当年是守卫失效（那时这两台的 confidence 是
    `high`），现在是守卫改成分档（confidence 必须是 `low`）。
    """
    rows = {f["rid"]: f for f in _run("aggressive")}
    low = {rid: f for rid, f in rows.items() if f.get("confidence") == "low"}
    assert set(low) == set(BELOW_FLOOR), (
        f"低于采样地板的资源应降档为 low，应为 {sorted(BELOW_FLOOR)}，"
        f"实际 {sorted(low)}")
    for rid, f in low.items():
        assert f["verdict"] == "downsize", (
            f"{rid} 样本不足仍应出建议，实际 {f['verdict']}")
        assert f["bucket"] == "downsize", f
        blockers = " ".join(f.get("blockers") or [])
        assert "样本" in blockers and str(BELOW_FLOOR[rid]) in blockers, (
            f"{rid} 的 blockers 未写明样本量 —— {f.get('blockers')}")
    assert not [f for f in rows.values() if f["verdict"] == "insufficient-data"], (
        "本 fixture 没有 cpu_n 为 0 或缺失的资源，不应再出现 insufficient-data")
```

在文件底部 `tests = [...]` 里把旧函数名换成新名。

- [ ] **Step 4: 检查 `test_excluded_rows_never_carry_savings` 的前提仍成立**

该测试断言「fixture 里有 excluded 行」。`aggressive` 现在 13 行全是 `downsize`，
`excluded` 为 0 ⇒ 该断言会失败。把它的取样范围改为只用 `conservative`
（那里仍有 1 行 `已合理配置` ⇒ `excluded`），并在 docstring 补一句为什么：

```python
    # aggressive 在采样分档后 13 行全部进 downsize，excluded 为 0；
    # conservative 仍有一行「已合理配置」⇒ excluded，本不变式在那里验证。
    for profile in ("conservative",):
```

- [ ] **Step 5: 跑全部测试**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do printf '%-42s' "$t"; python3 "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done`
Expected: **9 个文件全 PASS**（含 Task 5 新建的 `test_agg_full_window.py`）

- [ ] **Step 6: 提交**

```bash
cd ~/git/aws-cost-optimization-skill
git add aws-rightsizing/tests/test_regression_fleet.py
git commit -m "test: re-record the regression baseline for sampling downgrade

The two fixture rows below the floor (cpu_n 55 and 154) now produce
verdicts, so both profiles move. aggressive route1 401.51 -> 527.15,
conservative 312.48 -> 373.00, with a per-row reconciliation in the
migration note.

527.15 was previously retracted in this repo. Its reappearance is not
the old bug: back then the guard never fired because the fixture used
full-window point counts, and those rows carried confidence=high. Now
they carry low, and the guard assertion checks exactly that."
```

---

### Task 8: 回放真实账号数据，验证 verdict 迁移

**Files:**
- Modify: `~/Downloads/123456789012-ap-east-1-20260909/regen/step2_solve.py`（补三个持续态字段）
- Create: `~/Downloads/123456789012-ap-east-1-20260909/regen/verify_migration.py`

**Interfaces:**
- Consumes: Task 1–7 的 `core.py`
- Produces: 一份逐资源 verdict 迁移报告，断言 spec「验证方式」第 3 条那张表。

- [ ] **Step 1: 给 `step2_solve.py` 的托管组装补三个持续态字段**

在 `ec_resources()` 里，`repl_lag_max` 之后加：

```python
            "repl_lag_p95": worst_p95(ECS, m, "ReplicationLag", "Average"),
            "evictions_p95": worst_p95(ECS, m, "Evictions", "Sum"),
```

在 `msk_resources()` 里，`under_replicated_max` 之后加：

```python
            "under_replicated_p95": worst_p95(MSK, brokers,
                                              "UnderReplicatedPartitions",
                                              "Average"),
```

**注意**：本轮 raw 数据里 `ReplicationLag` 与 `Evictions` 只采了 `Maximum`
（Task 6 才把 `Average`/`Sum` 加进采集模板），所以这两个 `worst_p95` 会返回
`None` ⇒ `_persistent` 回退 `*_max` ⇒ ElastiCache 的两条否决行为不变。
**这正是向后兼容的实证**，不是缺陷。`UnderReplicatedPartitions` 已有 `Average`，
所以 MSK 那条会真正生效。

- [ ] **Step 2: 写验证脚本**

新建 `~/Downloads/123456789012-ap-east-1-20260909/regen/verify_migration.py`：

```python
#!/usr/bin/env python3
"""回放本账号，断言 spec 的 verdict 迁移表。"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))

# spec「验证方式」第 3 条那张表
EXPECT = {
    "msk-prod-01":                 ("insufficient-data", "已合理配置"),
    "msk-test-01":     ("blocked",           "已合理配置"),
    "msk-sit-01":   ("blocked",           "已合理配置"),
    "msk-sit-02":  ("blocked",           "已合理配置"),
    "msk-uat-01":   ("blocked",           "已合理配置"),
    "msk-uat-02":  ("blocked",           "已合理配置"),
    "msk-sit-03":            ("blocked",           "已合理配置"),
    "msk-uat-03":            ("blocked",           "已合理配置"),
    # ElastiCache 的 Average/Sum 本轮未采 ⇒ 回退 max ⇒ 这两条不变
    "redis-uat-01": ("blocked",          "blocked"),
    "redis-uat-02":          ("insufficient-data", "blocked"),
}
BASE = json.load(open(os.path.join(HERE, "baseline-core-out-aggressive.json")))
NEW = json.load(open(os.path.join(HERE, "core-out-aggressive.json")))
b = {r["rid"]: r for r in BASE}
n = {r["rid"]: r for r in NEW}
fail = []
for rid, (was, now) in EXPECT.items():
    if b[rid]["verdict"] != was:
        fail.append(f"{rid}: 基线应为 {was}，实际 {b[rid]['verdict']}")
    if n[rid]["verdict"] != now:
        fail.append(f"{rid}: 改后应为 {now}，实际 {n[rid]['verdict']}")
unchanged = [rid for rid in b if rid not in EXPECT
             and b[rid]["verdict"] != n[rid]["verdict"]]
if unchanged:
    fail.append(f"迁移表外的资源 verdict 也变了：{unchanged}")
for line in fail:
    print("FAIL:", line)
print("MIGRATION OK" if not fail else f"\n{len(fail)} 处不符")
sys.exit(1 if fail else 0)
```

- [ ] **Step 3: 存基线、重跑、验证**

```bash
cd ~/Downloads/123456789012-ap-east-1-20260909/regen
cp core-out-aggressive.json baseline-core-out-aggressive.json
python3 step2_solve.py && python3 step3_rows.py && python3 step4_validate.py && python3 step5_report.py
python3 verify_migration.py
```
Expected: `VALIDATION PASS` 后 `MIGRATION OK`

- [ ] **Step 4: 断言四条头条口径不变**

```bash
cd ~/Downloads/123456789012-ap-east-1-20260909
python3 -c "
import csv
def f(x):
    try: return float(x)
    except: return 0.0
def t(p):
    rows=list(csv.DictReader(open(p)))
    d=[r for r in rows if r['bucket']=='downsize']
    return (round(sum(f(r['nb_save_mo']) for r in d),2),
            round(sum(max(f(r['nb_save_mo']),f(r['b_save_mo'])) for r in d),2),
            round(sum(f(r['cur_cost_mo']) for r in rows if r['bucket']=='idle'),2),
            round(sum(f(r['other_save_mo']) for r in d),2))
got=t('regen/findings-aggressive.csv')
exp=(58.39, 87.30, 50.79, 3.32)
print('四条口径:', got, '期望:', exp)
assert got==exp, '头条金额变了，spec 说应当不变'
print('HEADLINE UNCHANGED')
"
```
Expected: `HEADLINE UNCHANGED`

- [ ] **Step 5: 断言桶 B 与 stop_candidate 未被 C1 触及**

```bash
cd ~/Downloads/123456789012-ap-east-1-20260909
python3 -c "
import csv
rows=list(csv.DictReader(open('regen/findings-aggressive.csv')))
idle=[r for r in rows if r['bucket']=='idle']
assert len(idle)==28, f'桶 B 行数变了：{len(idle)}'
assert all(r['stop_candidate']=='' for r in rows), 'stop_candidate 列不再全空'
print('BUCKET-B AND STOP-CANDIDATE UNTOUCHED')
"
```
Expected: `BUCKET-B AND STOP-CANDIDATE UNTOUCHED`

- [ ] **Step 6: 提交（只提交 skill 仓库侧；产出目录含账号与资源 ID，不入库）**

```bash
cd ~/git/aws-cost-optimization-skill
git status --short   # 确认 regen/ 不在本仓库内、无待提交内容
git log --oneline -8
```
Expected: 工作树干净，7 个新提交在 `feat/sampling-guard-and-veto-persistence` 上

---

## Self-Review

**1. Spec coverage**

| spec 要求 | 实现于 |
|---|---|
| C1 EC2 守卫改降档 + `confidence` 三档 | Task 1 |
| C1 托管守卫改降档 | Task 2 |
| C1 边界：`is_idle` / `is_stop_candidate` 保持硬门限 | 不改这两个函数（Task 1 只动 `evaluate()`）；Task 8 Step 5 断言桶 B 与 `stop_candidate` 不变 |
| C2 三条否决项改持续态 + 尖峰进 blockers + 向后兼容 | Task 3 |
| C2 前置：`agg.jq` full-window 档 | Task 5 |
| C2 附带：`freeable_mem_min_gib` 改全窗口 | Task 6 Step 6（`cli-recipes.md` 采集侧口径） |
| C3 语义澄清 + 未校验标记 | Task 4 |
| `thresholds.json` 只改注释 | Task 6 Step 3 |
| `report-template.md` confidence 枚举 + 低样本呈现 + 摘要 breakout | Task 1 Step 5、Task 6 Step 7 |
| `sample-solve.md` 字段契约 + 换 fixture | Task 4 Step 4、Task 6 Step 1 |
| `SKILL.md` 护栏重写 + 易错项两行 | Task 6 Step 4、Step 5 |
| `cli-recipes.md` 两个 stat + 三字段组装 + §2.6 改真档 | Task 6 Step 6 |
| 5 个测试文件 | Task 1（fail_closed）、Task 2–4（managed_dispatch）、Task 6（sample_reproduces）、Task 7（regression_fleet）、Task 1 Step 6 间接覆盖 csv_contract |
| 验证：8 测试全绿 + sample 自检 + 回放本账号 | Task 7 Step 5、Task 6 Step 2、Task 8 |

**2. Placeholder scan** —— 无 TBD／TODO／「similar to Task N」。每个 code step 都带完整代码块。基线数字（527.15 / 668.85 / 373.00 / 492.72）已实测得出，非估算。

**3. Type consistency** —— `_persistent(res, p95_key, max_key) -> (persist, max)` 在 Task 3 定义、仅在 Task 3 使用；`_spike_note(label, mx, cause) -> str` 同。`_FIT_UNVERIFIED` 在 Task 4 定义、三处使用。`low_sample` 在 Task 1 的 `evaluate()` 内定义与使用，Task 2 的 `dispatch()` 用的是自己的局部 `n < floor_pts`（两处不共享变量，故无命名冲突）。

**4. 已知风险**

- Task 4 的 `eval_elasticache` / `eval_msk` 从 `out.update(blockers=[...])` 改成 `out["blockers"].extend([...])`，**必须一并改 `verdict` 的赋值方式**，否则 `update` 会覆盖 Task 3 追加的尖峰说明。计划里已写明。
- Task 7 Step 4 改动 `test_excluded_rows_never_carry_savings` 的取样 profile。若 `conservative` 的那行「已合理配置」在实现中也变成 `downsize`，该不变式将无处验证——届时须给 fixture 加一条 `cpu_n=0` 的资源而不是放弃断言。
