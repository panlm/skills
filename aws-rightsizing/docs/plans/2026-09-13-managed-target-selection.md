# 托管服务初选目标机型 + RDS 判据补全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 RDS / ElastiCache / MSK 三条判据在判出 `downsize-candidate` 时给出初选目标机型与月省金额，并补上 RDS 主判据缺失即整行消失、`upsize` 只有一个出口、`FreeStorageSpace` 采而不用三个洞 —— 人工的角色从「自己选型」变成「审核初选」。

**Architecture:** 采集侧把已经取全的同形态候选连价格一起回传（`res["candidates"]`），取代压缩成一个布尔值的 `cheaper_candidate_exists`；`core.py` 新增一个纯函数 `_pick_managed_target()` 做适配校验与选型，三个 evaluator 各自只提供「需求量」与「内存条件」两个入参。RDS 额外把 `CPUUtilization` 提为并行第二判据（峰值项走 `_persistent()` 口径），并新增三个 verdict 出口。

**Tech Stack:** Python 3（标准库 only）、pytest、jq（采集配方）、AWS CLI（只读）

**Spec:** `docs/specs/2026-09-13-managed-target-selection-design.md`

## Global Constraints

- **`core.py` 只依赖标准库。** 不引入第三方依赖。
- **判据不得重新实现。** 适配校验只能在 `core.py`，不得复制到采集侧或报告侧。
- **取价的复合键留在采集侧。** RDS `engine + deploymentOption + instanceType`（Multi-AZ 是独立 usagetype，2 倍单价）、ElastiCache `^[A-Z0-9]+-NodeUsage:` 紧邻正则 + `(type, operation)` 双重消歧、MSK `computeFamily` 且排除 Express。
- **ElastiCache / RDS / MSK 的内存一律取 pricing 的 `memory` 属性**，绝不用 EC2 机型映射值（`cache.t3.medium` 真实 3.09 GiB，EC2 映射得 4.00 GiB，偏 +29%）。EC2 机型名映射**只用于查 `arch` 与 `baseline_pct`**。
- **新字段缺失即回退旧行为，不得 fail-closed。** 实测教训（真实机队回放）：旧契约缺必填字段时 86 条托管行全部 fail-closed，比不升级更差。
- **一律走 `_verdict()` 设 verdict。** 不得写 `out.update(verdict=X, blockers=[...])` —— 那会覆盖已 append 的说明，本文件已在这个覆盖上踩过三次。
- **`tests/fixtures/regression-fleet.json` 是 EC2 独占的 13 行。** `test_regression_fleet.py` 的 `EXPECTED`（aggressive `route1_nb=527.15` / `route2_max=668.85`，conservative `route1_nb=373.00` / `route2_max=492.72`）本轮必须**逐分不变**，任何变动都是回归。
- **不碰硬约束清单。** Multi-AZ→Single-AZ、Redis 减副本/减 shard、MSK 减 broker、跨 CPU 架构、Serverless 迁移一律仍不产出。
- **不改 EC2 侧 `peak_cpu` 口径**（仍取 `Maximum` 序列的 `max`）。
- **不产出升配目标机型。** 所有 `upsize-candidate` 出口只报「已不足」与依据。
- 脱敏：本仓库公开。文档里账号一律 `123456789012`，资源名用 `db-<env>-NN` / `redis-<env>-NN` / `msk-<env>-NN` 占位；指标值、点数、金额、机型是原值。

## File Structure

| 文件 | 职责 |
|---|---|
| `references/core.py` | 新增 `_managed_ec2_name()` / `_managed_baseline()` / `_pick_managed_target()` / `_apply_managed_pick()` 四个 helper；三个 evaluator 接选型；`eval_rds` 分支重排 + 三个新出口 |
| `references/thresholds.json` | 新增 `rds_storage_days_floor`（唯一新增阈值；`managed_mem_headroom` 实现期作废，改用已有 `target_mem_p95` 反推） |
| `references/rds-pi-unsupported.json` | 新建。PI 不支持的实例类列表 + 来源 URL + 复查方式 |
| `tests/test_managed_target_selection.py` | 新建。选型正确性、fit 边界、候选池为空的五种成因、向后兼容 |
| `tests/test_rds_criteria.py` | 新建。CPU 第二判据、`_persistent` 峰值项、三个新出口、分支保序、`FreeStorageSpace`、峰值反转校验 |
| `tests/fixtures/regression-managed.json` | 新建。托管回归机队（与 EC2 基线分开） |
| `tests/test_regression_managed.py` | 新建。托管侧 `route1_nb` / `route2_max` 基线 |
| `references/cli-recipes.md` | 托管行组装加 `candidates` / `cur_usd` / `count` / `pi_enabled` / CPU / `FreeStorageSpace` 字段 |
| `references/sample-solve.md` | 字段契约表；修掉 `dbload_p95` 缺失即 `metric-missing` 与 CPUUtilization 兜底承诺的自相矛盾 |
| `references/report-template.md` | 托管小节加目标列；删「托管节省结构性不进头条」裁定 |
| `references/metrics-catalog.md` | `DBLoad` 补两序列跨度说明；`FreeStorageSpace` 补消费者 |
| `references/thresholds.md` | 两个新阈值的标定证据 |
| `SKILL.md` | 托管服务小节：「不自选目标」→「初选目标 + 人工审核」 |

---

### Task 1: 选型 helper（纯函数，不碰任何 evaluator）

**Files:**
- Modify: `references/core.py`（在 `_FIT_UNVERIFIED` 之后、`_persistent` 之前插入）
- Test: `tests/test_managed_target_selection.py`（新建）

**Interfaces:**
- Consumes: 无（本任务是新基元）
- Produces:
  - `_managed_ec2_name(itype) -> str` —— `"db.t4g.medium"` → `"t4g.medium"`
  - `_managed_baseline(itype, base) -> float | None`
  - `_pick_managed_target(res, t, req_vcpu, mem_fit, base, exclude=frozenset()) -> dict | None`
    返回 `{"nonburst": dict|None, "burst": dict|None, "cheaper_exists": bool, "empty_reason": str|None, "excluded_best": dict|None}`；`res["candidates"]` 缺失时返回 `None`
  - `_apply_managed_pick(out, res, pick) -> None` —— 把两列与 `*_save_mo` / `*_delta_vcpu` / `*_delta_gib` / `*_cat` 写进 `out`

- [ ] **Step 1: 写失败测试 —— 基本选型与两列都出**

```python
# tests/test_managed_target_selection.py
"""托管服务的目标机型初选。

此前三条托管判据的 nonburst / burst / nb_save_mo / b_save_mo 四列恒空：
采集侧算 cheaper_candidate_exists 时已经把候选连价格取全，然后只回传一个
布尔值。布尔值不含信息量到近乎误导 —— 实测 db.m6g.large 往下最近的更便宜
候选省 $5.84/mo，而真正装得下需求的目标省 $86.87/mo，差 14.9 倍。
"""
import pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

# ap-east-1 MySQL Single-AZ 真实价目与规格（内存取 pricing 的 memory 属性）
RDS_CANDS = [
    {"t": "db.t4g.micro",  "usd": 0.0280, "vcpu": 2, "gib": 1.0,  "arch": "arm64", "burst": True},
    {"t": "db.t4g.small",  "usd": 0.0560, "vcpu": 2, "gib": 2.0,  "arch": "arm64", "burst": True},
    {"t": "db.t4g.medium", "usd": 0.1110, "vcpu": 2, "gib": 4.0,  "arch": "arm64", "burst": True},
    {"t": "db.t4g.large",  "usd": 0.2220, "vcpu": 2, "gib": 8.0,  "arch": "arm64", "burst": True},
    {"t": "db.m5.large",   "usd": 0.2585, "vcpu": 2, "gib": 8.0,  "arch": "x86_64", "burst": False},
]
# EC2 机型名 → baseline。db. 前缀剥掉后查，这张表只用于 baseline 与 arch。
BASE = {"t4g.micro": 0.10, "t4g.small": 0.20, "t4g.medium": 0.20,
        "t4g.large": 0.30, "t4g.2xlarge": 0.40}
T = core.load_thresholds("aggressive")


def _res(**kw):
    r = {"rid": "db-sit-01", "service": "rds", "type": "db.m6g.large",
         "vcpu": 2, "mem_gib": 8.0, "cur_usd": 0.2300, "arch": "arm64",
         "count": 1, "candidates": RDS_CANDS}
    r.update(kw)
    return r


def test_picks_cheapest_fitting_candidate_in_both_columns():
    # 需求：2 vCPU、3.40 GiB（= (8 − 5.110) / (1 − 15%)）
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=2, mem_fit=lambda c: c["gib"] >= 3.40, base=BASE)
    assert pick["burst"]["t"] == "db.t4g.medium"     # 4.0 GiB 装得下，最便宜
    assert pick["nonburst"] is None                 # 更便宜的非突发候选不存在
    assert pick["cheaper_exists"] is True
    assert pick["empty_reason"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/git/panlm-skills/aws-rightsizing && python -m pytest tests/test_managed_target_selection.py -x -q`
Expected: FAIL — `AttributeError: module 'core' has no attribute '_pick_managed_target'`

- [ ] **Step 3: 实现四个 helper**

在 `references/core.py` 的 `_FIT_UNVERIFIED` 常量**之后**插入：

```python
_MANAGED_PREFIX_RE = re.compile(r"^(?:db|cache|kafka)\.")


def _managed_ec2_name(itype):
    """`db.t4g.medium` -> `t4g.medium`。

    **只用于查 `baseline_pct` 与 `arch`，绝不用于查内存。**
    实测 `cache.t3.medium` 真实 3.09 GiB，映射到 EC2 `t3.medium` 得 4.00 GiB，
    偏 +29%；而 `DatabaseMemoryUsagePercentage` 是相对真实节点内存的百分比，
    基数错则绝对量全错。内存一律取 pricing 的 `memory` 属性。
    后人若想把这个映射"顺手统一"到内存上，先读这段注释。
    """
    return _MANAGED_PREFIX_RE.sub("", itype)


def _managed_baseline(itype, base):
    """托管突发机型的基线百分比。复用 EC2 的 baseline-pct.json。

    `_credit_exhausted` 的 docstring 写过「RDS 的 baseline 百分比不在本 skill
    的静态资产里」—— 那句话对**当前**机型的信用上限判定成立（那里改用观测
    最大值自归一化）。但候选机型没有观测数据，只能查表。
    可验证性：信用上限 = vcpu x baseline x 1440。已确认吻合两例 ——
    `cache.t3.medium` 576 = 2 x 0.20 x 1440、`cache.t4g.micro` 288 = 2 x 0.10 x 1440。
    查不到 ⇒ 返回 None ⇒ 该候选被排除在突发列之外（fail-closed，同 EC2 侧
    `base.get(s["t"]) is not None` 那道过滤）。
    """
    return base.get(_managed_ec2_name(itype)) if base else None


# 候选池为空的五种成因。动作相同（不降配）但可操作性完全不同，
# 现行代码在五种成因上给同一句话，且那句话在后三种下是**错的**。
_EMPTY_NO_CHEAPER = ("同形态下更便宜的候选数为 0（已在价目地板上）；"
                     "补充指标或延长窗口都不会改变结论")
_EMPTY_CROSS_ARCH = ("更便宜的候选存在但全部跨 CPU 架构（{types}）；"
                     "跨架构迁移是本 skill 的硬约束禁止项，不是可调阈值")
_EMPTY_VCPU = ("需求量 {req} vCPU 超过所有更便宜候选（最接近的 {best} 只有 "
               "{best_vcpu} vCPU）")
_EMPTY_MEM = ("更便宜的候选都装不下当前需求（最接近的是 {best}）")
_EMPTY_FLOOR = ("被降幅地板挡住而非适配失败：max_reduction_ratio={mrr} 要求候选"
                "至少 {floor} vCPU，更便宜的候选都低于它")


def _pick_managed_target(res, t, req_vcpu, mem_fit, base, exclude=frozenset()):
    """从 `res["candidates"]` 各选一个非突发 / 突发目标。

    `candidates` 缺失 ⇒ 返回 `None`，调用方走改动前的旧路径（读采集侧的
    `cheaper_candidate_exists` 布尔值、不出目标）。**不得 fail-closed** ——
    实测教训：旧契约缺字段时 86 条托管行全部 fail-closed，比不升级更差。

    `mem_fit` 是各服务自己的内存条件（RDS 比 `gib`、ElastiCache 比扣掉
    reserved 之后的可用内存、MSK 无内存轴恒 True）。判据留在各 evaluator，
    本函数只做筛选与排序 —— 与 EC2 侧 `passes_common` / `pool` 同一分工。
    """
    cands = res.get("candidates")
    if cands is None:
        return None
    cur_usd, cur_vcpu = res.get("cur_usd"), res.get("vcpu")
    if cur_usd is None or cur_vcpu is None:
        # candidates 存在却没有当前单价/核数：这是采集侧的契约违反，
        # 不是指标缺口。回退旧路径并让调用方写明，避免静默选出错的目标。
        return None
    cur_arch = res.get("arch")
    cheaper = [c for c in cands if c["usd"] < cur_usd]
    out = {"nonburst": None, "burst": None, "cheaper_exists": bool(cheaper),
           "empty_reason": None, "excluded_best": None}
    if not cheaper:
        out["empty_reason"] = _EMPTY_NO_CHEAPER
        return out
    same_arch = [c for c in cheaper if c.get("arch") == cur_arch]
    if not same_arch:
        out["empty_reason"] = _EMPTY_CROSS_ARCH.format(
            types="、".join(f"{c['t']}({c.get('arch')})"
                            for c in sorted(cheaper, key=lambda c: c["usd"])))
        return out
    excl = [c for c in same_arch if c["t"] in exclude]
    if excl:
        out["excluded_best"] = min(excl, key=lambda c: c["usd"])
    same_arch = [c for c in same_arch if c["t"] not in exclude]
    floor_vcpu = _ceil_div(cur_vcpu, t["max_reduction_ratio"])
    by_vcpu = [c for c in same_arch if c["vcpu"] >= max(req_vcpu, floor_vcpu)]
    if not by_vcpu:
        best = max(same_arch, key=lambda c: c["vcpu"])
        # 两条成因要分开：需求量超过候选 vs 降幅地板挡住。前者补容量规划
        # 无解，后者是策略选择，读者的下一步动作不同。
        if req_vcpu > floor_vcpu:
            out["empty_reason"] = _EMPTY_VCPU.format(
                req=req_vcpu, best=best["t"], best_vcpu=best["vcpu"])
        else:
            out["empty_reason"] = _EMPTY_FLOOR.format(
                mrr=t["max_reduction_ratio"], floor=floor_vcpu)
        return out
    fitting = [c for c in by_vcpu if mem_fit(c)]
    if not fitting:
        best = max(by_vcpu, key=lambda c: c["gib"])
        out["empty_reason"] = _EMPTY_MEM.format(best=best["t"])
        return out
    key = lambda c: (c["usd"], c["t"])
    nb = sorted((c for c in fitting if not c.get("burst")), key=key)
    bu = sorted((c for c in fitting if c.get("burst")
                 and _managed_baseline(c["t"], base) is not None), key=key)
    out["nonburst"] = nb[0] if nb else None
    out["burst"] = bu[0] if bu else None
    return out


def _apply_managed_pick(out, res, pick, base):
    """把选中的两列与派生金额写进 `out`。

    `*_delta_vcpu` 用 `_eff_vcpu` 而不是标称核数，与 EC2 侧同口径 ——
    否则 `db.m6g.large` -> `db.t4g.large`（同为 2 vCPU）会算出 delta=0，
    看起来毫无意义。突发候选查不到 baseline 时已在 `_pick_managed_target`
    里被排除，所以这里 `_eff_vcpu` 不会拿到 None。
    """
    cnt = res.get("count", 1)
    cur_usd, cur_vcpu, cur_gib = res["cur_usd"], res["vcpu"], res.get("mem_gib")
    cur_spec = {"t": res["type"], "vcpu": cur_vcpu}
    eff_cur = _eff_vcpu(cur_spec, {_managed_ec2_name(res["type"]):
                                   _managed_baseline(res["type"], base)}
                        if _managed_baseline(res["type"], base) else {})
    for key, p in (("nb", pick["nonburst"]), ("b", pick["burst"])):
        if not p:
            out[f"{key}_save_mo"] = None
            continue
        out[f"{key}_save_mo"] = round((cur_usd - p["usd"]) * HOURS_PER_MONTH * cnt, 2)
        pb = _managed_baseline(p["t"], base)
        eff_new = p["vcpu"] * (pb if pb is not None else 1.0)
        out[f"{key}_delta_vcpu"] = round(eff_cur - eff_new, 3)
        if cur_gib is not None:
            out[f"{key}_delta_gib"] = round(cur_gib - p["gib"], 3)
    out["nonburst"] = pick["nonburst"]
    out["burst"] = pick["burst"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_managed_target_selection.py -x -q`
Expected: PASS

- [ ] **Step 5: 补五种「候选池为空」成因的测试**

```python
def test_empty_reason_no_cheaper():
    pick = core._pick_managed_target(
        _res(type="db.t4g.micro", cur_usd=0.0280, mem_gib=1.0),
        T, req_vcpu=1, mem_fit=lambda c: True, base=BASE)
    assert pick["nonburst"] is None and pick["burst"] is None
    assert "价目地板" in pick["empty_reason"]
    assert pick["cheaper_exists"] is False


def test_empty_reason_cross_arch_lists_types_and_arch():
    # MSK 实测形态：kafka.m7g.large 全区更便宜的 broker 机型只有
    # kafka.t3.small(x86)，跨架构为硬约束禁止项。
    pick = core._pick_managed_target(
        _res(type="kafka.m7g.large", cur_usd=0.2805, vcpu=2, mem_gib=8.0,
             candidates=[{"t": "kafka.t3.small", "usd": 0.0639, "vcpu": 2,
                          "gib": 2.0, "arch": "x86_64", "burst": True}]),
        T, req_vcpu=1, mem_fit=lambda c: True, base=BASE)
    assert pick["cheaper_exists"] is True
    assert "kafka.t3.small(x86_64)" in pick["empty_reason"]
    assert "硬约束禁止项" in pick["empty_reason"]


def test_empty_reason_memory_names_closest_candidate():
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=2, mem_fit=lambda c: c["gib"] >= 99.0, base=BASE)
    assert "db.t4g.large" in pick["empty_reason"]     # 更便宜候选里内存最大的


def test_empty_reason_reduction_floor_is_distinguished_from_fit():
    # max_reduction_ratio=3 ⇒ 8 vCPU 的地板是 ceil(8/3)=3；候选全是 2 vCPU
    pick = core._pick_managed_target(
        _res(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0, cur_usd=0.9190),
        T, req_vcpu=1, mem_fit=lambda c: True, base=BASE)
    assert "降幅地板" in pick["empty_reason"]
    assert "max_reduction_ratio=3" in pick["empty_reason"]


def test_empty_reason_req_vcpu_is_distinguished_from_floor():
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=16, mem_fit=lambda c: True, base=BASE)
    assert "需求量 16 vCPU" in pick["empty_reason"]
    assert "降幅地板" not in pick["empty_reason"]
```

- [ ] **Step 6: 补向后兼容与 fail-safe 测试**

```python
def test_missing_candidates_returns_none_not_fail_closed():
    r = _res()
    del r["candidates"]
    assert core._pick_managed_target(r, T, 2, lambda c: True, BASE) is None


def test_candidates_present_but_cur_usd_missing_returns_none():
    r = _res()
    del r["cur_usd"]
    assert core._pick_managed_target(r, T, 2, lambda c: True, BASE) is None


def test_burst_candidate_without_baseline_is_excluded_from_burst_column():
    # baseline 查不到 ⇒ 信用余量无从校验 ⇒ 该候选不得进突发列
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=2, mem_fit=lambda c: c["gib"] >= 3.40, base={})
    assert pick["burst"] is None
    assert pick["nonburst"] is None


def test_managed_ec2_name_strips_all_three_prefixes():
    assert core._managed_ec2_name("db.t4g.medium") == "t4g.medium"
    assert core._managed_ec2_name("cache.m6g.large") == "m6g.large"
    assert core._managed_ec2_name("kafka.t3.small") == "t3.small"
    assert core._managed_ec2_name("t4g.medium") == "t4g.medium"
```

- [ ] **Step 7: 跑全套测试，确认 EC2 基线未动**

Run: `python -m pytest tests/ -q`
Expected: 全绿；`test_regression_fleet.py` 的 `route1_nb` / `route2_max` 一分不变

- [ ] **Step 8: Commit**

```bash
git add references/core.py tests/test_managed_target_selection.py
git commit -m "feat(aws-rightsizing): add managed-service target picker

Pure helper only; no evaluator consumes it yet. Candidate pool comes from
res[\"candidates\"] so the price-key complexity stays on the collection
side, mirroring how ctx[\"prices\"] is pre-keyed for the EC2 path.

Empty-pool diagnostics distinguish five causes. The current code gives one
sentence for all five, and that sentence is wrong for three of them."
```

---

### Task 2: `eval_elasticache` 接选型（内存下限由 `target_mem_p95` 反推）

> **实现期偏离本计划初稿。** 初稿新增阈值 `managed_mem_headroom`
> （ag 1.5 / co 2.0）作乘性余量，被两条既有守卫测试各否掉一半：
> `test_required_gib_usable_is_actually_usable_memory` 锁死「键名说 usable，
> 值就必须是可用内存口径」，乘上余量后不是；
> `test_distinctive_threshold_values_not_restated_in_prose` 报出值 `2.0`
> 与散文里满篇的「§2.0」冲突（11 处命中）。
> 改用已有的 `target_mem_p95` 反推后两条都自然满足，**且不新增任何阈值**。
> 「深度降配」护栏同样改了：初稿「距当前 >= 4 档」在 ElastiCache 上永不触发
> （同架构更便宜的候选只有 3 档），改判「落在同架构阶梯最底档」。

**Files:**
- Modify: `references/core.py`（`eval_elasticache`；`MANAGED_EVALUATORS` 调用点加 `base`）
- Test: `tests/test_managed_target_selection.py`

**Interfaces:**
- Consumes: `_pick_managed_target` / `_apply_managed_pick` / `_cheaper_exists` /
  `_managed_deep_note`（Task 1）
- Produces: `eval_elasticache(res, t, base=None)`；`out["required_gib_usable"]`
  口径**不变**（纯已用可用内存）

- [ ] **Step 1: 写失败测试**（见 `tests/test_managed_target_selection.py` 的
  `test_elasticache_*` 与 `test_bottom_of_ladder_forces_low_confidence` 五条）

- [ ] **Step 2: 跑测试确认失败**

Run: `uvx --from pytest pytest tests/test_managed_target_selection.py -q -k elasticache`
Expected: FAIL — `eval_elasticache() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 三个 evaluator 签名加 `base=None`，`dispatch()` 传 baseline**

```python
def eval_rds(res, t, base=None):
def eval_elasticache(res, t, base=None):
def eval_msk(res, t, base=None):
```
```python
    out = MANAGED_EVALUATORS[svc](res, t, ctx.get("baseline_pct") or {})
```

默认 `None` 是为了不破坏既有直接调用方（`tests/test_fail_closed_contracts.py`
用两参调用）。三个 evaluator 的 `out` 初始化同时补上目标列，
否则未升级路径上 `out["nonburst"]` 会 `KeyError`：

```python
    out = {"rid": res["rid"], "service": "elasticache", "cur": res["type"],
           "blockers": [], "nonburst": None, "burst": None,
           "required_vcpu": None, "required_gib": None}
```

- [ ] **Step 4: `cheaper` 读取改走 `_cheaper_exists()`，候选池为空改报具体成因**

```python
    cheaper = _cheaper_exists(res)
    if cheaper is None:
        _verdict(out, "metric-missing",
                 "cheaper_candidate_exists 缺失，无法确认是否存在"
                 "更便宜的同形态候选（不得假定存在）")
        return out
    if not cheaper:
        _verdict(out, "已合理配置", _EMPTY_NO_CHEAPER)
        return out
```

- [ ] **Step 5: 内存下限按 `target_mem_p95` 反推并接选型**

```python
    req = round(out["required_gib_usable"] / (t["target_mem_p95"] / 100.0), 3)
    pick = _pick_managed_target(
        res, t,
        req_vcpu=max(1, _ceil_div(res["vcpu"] * cpu, t["target_cpu_p95"])),
        mem_fit=lambda c: c["gib"] * (1 - reserved) >= req,
        base=base or {})
    if pick is None:
        return _verdict(out, "downsize-candidate", <旧文案 + req>, ..., _FIT_UNVERIFIED)
    if pick["empty_reason"]:
        _verdict(out, "已合理配置", pick["empty_reason"])
        return out
    _apply_managed_pick(out, res, pick, base or {})
    _managed_deep_note(out, res, pick, usable_ratio=1 - reserved)
    return _verdict(out, "downsize-candidate", <初选文案>,
                    "不产出减副本/减 shard 建议（降可用性等级 / 需数据重分布）")
```

- [ ] **Step 6: 跑全套，确认 EC2 基线逐分不变**

Run: `uvx --from pytest pytest tests/ -q`
然后 `git stash` 前后各跑 `tests/test_regression_fleet.py` 对比。

- [ ] **Step 7: Commit**

```bash
git add references/core.py tests/test_managed_target_selection.py
git commit -m "feat(aws-rightsizing): eval_elasticache picks a target node type"
```

### Task 3: `eval_msk` 接选型

**Files:**
- Modify: `references/core.py:810-872`（`eval_msk`）
- Test: `tests/test_managed_target_selection.py`

**Interfaces:**
- Consumes: `_pick_managed_target` / `_apply_managed_pick`（Task 1）
- Produces: `eval_msk(res, t, base=None)`

- [ ] **Step 1: 写失败测试**

```python
MSK_CANDS_ARM = [
    {"t": "kafka.t3.small", "usd": 0.0639, "vcpu": 2, "gib": 2.0,
     "arch": "x86_64", "burst": True},
]
MSK_CANDS_X86 = [
    {"t": "kafka.t3.small", "usd": 0.0639, "vcpu": 2, "gib": 2.0,
     "arch": "x86_64", "burst": True},
    {"t": "kafka.m5.large", "usd": 0.2100, "vcpu": 2, "gib": 8.0,
     "arch": "x86_64", "burst": False},
]


def _msk(**kw):
    r = {"rid": "msk-test-01", "service": "msk", "type": "kafka.m7g.large",
         "vcpu": 2, "mem_gib": 8.0, "cur_usd": 0.2805, "arch": "arm64",
         "count": 2, "under_replicated_p95": 0, "under_replicated_max": 0,
         "disk_used_max": 18, "handler_idle_p95": 0.94, "cpu_total_p95": 15,
         "candidates": MSK_CANDS_ARM}
    r.update(kw)
    return r


def test_msk_graviton_cluster_reports_cross_arch_as_the_reason():
    """实测：kafka.m7g.large 在 ap-east-1 的非 Express broker 价目里，
    更便宜的机型只有 kafka.t3.small，而它是 x86。8 个集群一个目标都选不出，
    但理由从「同形态下没有更便宜的候选机型」变成可审计的具体成因。
    """
    out = core.eval_msk(_msk(), core.load_thresholds("aggressive"), {})
    assert out["verdict"] == "已合理配置"
    assert out["nonburst"] is None and out["burst"] is None
    assert "kafka.t3.small(x86_64)" in " ".join(out["blockers"])


def test_msk_at_price_floor_reports_no_cheaper_candidate():
    out = core.eval_msk(
        _msk(type="kafka.t3.small", cur_usd=0.0639, arch="x86_64",
             candidates=[]),
        core.load_thresholds("aggressive"), {})
    assert out["verdict"] == "已合理配置"
    assert "价目地板" in " ".join(out["blockers"])


def test_msk_picks_target_when_same_arch_cheaper_exists():
    out = core.eval_msk(
        _msk(type="kafka.m5.xlarge", cur_usd=0.4200, vcpu=4, mem_gib=16.0,
             arch="x86_64", candidates=MSK_CANDS_X86),
        core.load_thresholds("aggressive"), {})
    assert out["verdict"] == "downsize-candidate"
    assert out["nonburst"]["t"] == "kafka.m5.large"
    assert out["nb_save_mo"] == round((0.4200 - 0.2100) * 730 * 2, 2)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_managed_target_selection.py -x -q -k msk`
Expected: FAIL — `eval_msk() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 改 `eval_msk`**

签名加 `base=None`；`cheaper` 读取改为 `candidates` 优先（与 Task 2 Step 4.5 同一段代码）；末尾出口改为：

```python
    # MSK 无内存轴：AWS/Kafka 不发布 broker 内存利用率。存储也不参与候选筛选
    # —— 卷大小与 broker 机型无关，msk_disk_used_max 是独立的「已合理配置」
    # 出口（上面已判过），不是候选约束。
    pick = _pick_managed_target(
        res, t,
        req_vcpu=max(1, _ceil_div(res["vcpu"] * cpu, t["msk_target_cpu_p95"])),
        mem_fit=lambda c: True,
        base=base or {})
    if pick is None:
        return _verdict(
            out, "downsize-candidate",
            "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
            "不产出减 broker 数建议（需 partition 重分配，属架构级）",
            _FIT_UNVERIFIED)
    if not pick["cheaper_exists"] or pick["empty_reason"]:
        return _verdict(out, "已合理配置", pick["empty_reason"])
    _apply_managed_pick(out, res, pick, base or {})
    return _verdict(
        out, "downsize-candidate",
        f"目标 broker 机型为本 skill 初选（CpuUser+CpuSystem p95 {cpu}% ⇒ 按目标 "
        f"{t['msk_target_cpu_p95']}% 反推需 "
        f"{max(1, _ceil_div(res['vcpu'] * cpu, t['msk_target_cpu_p95']))} vCPU），"
        f"须人工确认变更窗口与回滚预案",
        "存储只能扩不能缩 ⇒ 过度预配走 next-rebuild-only",
        "不产出减 broker 数建议（需 partition 重分配，属架构级）")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_managed_target_selection.py -q && python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add references/core.py tests/test_managed_target_selection.py
git commit -m "feat(aws-rightsizing): eval_msk picks a target broker type

Yields no target on the validation fleet, which is the point: all eight
clusters now say why. kafka.m7g.large has exactly one cheaper broker type
in ap-east-1 (kafka.t3.small, x86) and cross-arch is a hard constraint;
the six kafka.t3.small clusters sit on the price floor with zero cheaper
candidates. Same amount, auditable reason."
```

---

### Task 4: `eval_rds` — CPU 第二判据、`_persistent` 峰值项、分支重排、两个新 upsize 出口

**Files:**
- Modify: `references/core.py:573-671`（`eval_rds`）
- Test: `tests/test_rds_criteria.py`（新建）

**Interfaces:**
- Consumes: `_persistent`（已有）、`_required`（已有）、`_ceil_div`（已有）
- Produces: `eval_rds(res, t, base=None)`；新增读取 `res["sus_cpu"]` / `res["peak_cpu_p95"]`

- [ ] **Step 1: 写失败测试 —— CPU 轴与峰值口径**

```python
# tests/test_rds_criteria.py
"""RDS 判据：CPU 并行第二判据、峰值项改判持续态、三个新 verdict 出口。

改动前 dbload_p95 缺失即 metric-missing 并 return，而 Performance Insights
在 db.t2/t3.micro/small、db.t4g.micro/small 上结构性不支持，在任何机型上
又都可以只是没开。metrics-catalog.md 与 sample-solve.md 两处已承诺
CPUUtilization 兜底，core.py 里一行都没有。
"""
import pathlib, sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

BASE = {"t4g.medium": 0.20, "t4g.large": 0.30}


def _rds(**kw):
    """db-sit-01 的真实观测：CPU 持续 p95 2.82%、Maximum 序列 p95 4.92% /
    max 42.01%、DBLoad Average p95 0.001、FreeableMemory 最小值 5.110 GiB。"""
    r = {"rid": "db-sit-01", "service": "rds", "type": "db.m6g.large",
         "vcpu": 2, "mem_gib": 8.0, "cur_usd": 0.2300, "arch": "arm64",
         "count": 1, "pi_enabled": True,
         "sus_cpu": 2.82, "peak_cpu_p95": 4.92,
         "dbload_p95": 0.001, "dbload_max_p95": 1.0,
         "freeable_mem_min_gib": 5.110,
         "storage_free_min_gib": 191.588, "storage_free_first_gib": 191.613,
         "storage_free_last_gib": 191.589, "window_days": 30,
         "surplus_credits": 0, "cheaper_candidate_exists": True}
    r.update(kw)
    return r


T_AG = core.load_thresholds("aggressive")
T_CO = core.load_thresholds("conservative")


def test_rds_survives_missing_dbload_via_cpu_axis():
    """P4：dbload_p95 缺失不再是死胡同。CPUUtilization 采集侧已经在采
    （cli-recipes.md §2.3 mdq 列表第一项），兜底零新增 API 调用。"""
    out = core.eval_rds(_rds(dbload_p95=None, dbload_max_p95=None), T_AG, BASE)
    assert out["verdict"] != "metric-missing"
    assert any("Performance Insights" in b for b in out["blockers"])


def test_rds_pi_unsupported_class_gets_a_different_blocker_than_pi_off():
    """两种成因的动作不同：前者要换机型才能拿到，后者改个开关即可。"""
    unsupported = core.eval_rds(
        _rds(type="db.t4g.small", vcpu=2, mem_gib=2.0, cur_usd=0.0560,
             mem_gib_override=None, dbload_p95=None, dbload_max_p95=None,
             freeable_mem_min_gib=1.2), T_AG, BASE)
    assert any("结构性不支持" in b for b in unsupported["blockers"])
    off = core.eval_rds(_rds(dbload_p95=None, dbload_max_p95=None,
                             pi_enabled=False), T_AG, BASE)
    assert any("未开启" in b for b in off["blockers"])
    assert not any("结构性不支持" in b for b in off["blockers"])


def test_rds_peak_term_uses_persistent_not_single_spike():
    """P9：db-uat-01 实测 CPU 持续 p95 4.00%，Maximum 序列 max 88.33% /
    p95 7.89%。按 max 反推需 ceil(2 x 88.33 / 85) = 3 vCPU（超过现有 2）
    ⇒ 一台常态 4% 的库看起来满载。12 台按 max 判，aggressive 只剩 2 台
    可降、conservative 0 台，与 DBLoad 结论大面积冲突。

    EC2 侧 peak_cpu 仍取 max —— 那里的尖峰是真实业务负载；RDS 的可证明
    来自备份窗口与自动小版本升级，与 MSK URP / Redis ReplicationLag 同类。
    """
    out = core.eval_rds(_rds(sus_cpu=4.00, peak_cpu_p95=7.89), T_AG, BASE)
    assert out["required_vcpu"] == 1        # ceil(2x4.00/60)=1, ceil(2x7.89/85)=1
    assert out["verdict"] == "downsize-candidate"


def test_rds_req_vcpu_takes_max_of_cpu_and_dbload_axes():
    # DBLoad 轴：ceil(1.6 / 0.5) = 4；CPU 轴：1 ⇒ 取 4
    out = core.eval_rds(_rds(vcpu=8, mem_gib=32.0, cur_usd=0.9190,
                             dbload_p95=1.6, dbload_max_p95=3.0), T_AG, BASE)
    assert out["required_vcpu"] == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rds_criteria.py -x -q`
Expected: FAIL — `eval_rds() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 新建 PI 不支持列表**

`references/rds-pi-unsupported.json`：

```json
{
  "_source": "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_DatabaseInsights.Engines.html",
  "_recheck": "该页 RDS for MySQL / MariaDB 行的「Instance class restrictions」栏。同一列表也出现在 repost.aws/knowledge-center/rds-aurora-performance-db-insights 的 Instance type 小节。",
  "_why": "DBLoad 是 RDS 降配的第一判据。推荐一个保证下一轮变成 metric-missing 的目标，与本 skill「缺判据即 fail-closed」的整体设计矛盾，故当前实例已开 PI 时把这些实例类从候选池硬排除，并在 blocker 里量化放弃的金额。",
  "classes": ["db.t2.micro", "db.t2.small", "db.t3.micro", "db.t3.small",
              "db.t4g.micro", "db.t4g.small"]
}
```

`references/core.py` 顶部加载（紧跟 `_THRESHOLDS_PATH` 之后）：

```python
_PI_UNSUPPORTED_PATH = pathlib.Path(__file__).with_name("rds-pi-unsupported.json")


def load_pi_unsupported(path=None):
    """PI 不支持的 RDS 实例类。唯一真值源，测试锁死无第二处硬编码。"""
    p = pathlib.Path(path) if path else _PI_UNSUPPORTED_PATH
    return frozenset(json.loads(p.read_text(encoding="utf-8"))["classes"])
```

- [ ] **Step 4: 重写 `eval_rds`**

按 spec C5 定死的 12 步顺序。完整替换 `eval_rds`：

```python
def eval_rds(res, t, base=None):
    """RDS 判据。DBLoad 与 CPUUtilization 是**并行**两轴，不是主备。

    实测教训（保留）：某 db.t4g.medium 的 DBLoad p95 = 0.547 < 0.5x2vCPU
    ⇒ 前置"满足"，但 CPUSurplusCreditsCharged 单小时最大 730.6、
    CPUCreditBalance 最小值 0 ⇒ 规格已不足。故信用超额是**独立否决项**。

    本轮新增的三个出口（CPU 持续项超、FreeableMemory 越地板、
    FreeStorageSpace 触 0）与那条同类：它们说的都是「这台机器不能降」或
    「已经不够用」，必须排在「没有更便宜的候选」之前 —— 后者会把前者盖掉。
    分支顺序见 docs/specs/2026-09-13-managed-target-selection-design.md 的 C5。
    """
    out = {"rid": res["rid"], "service": "rds", "cur": res["type"],
           "blockers": [], "nonburst": None, "burst": None,
           "required_vcpu": None, "required_gib": None}
    _coverage_note(out, res)
    if res["type"] == "db.serverless":
        _verdict(out, "excluded", "Aurora Serverless v2 按 ACU 伸缩，无固定规格")
        return out
    vcpu = res.get("vcpu")
    if vcpu is None:
        _verdict(out, "spec-unknown", "实例类 vCPU 未知（映射失败且兜底表无此项）")
        return out
    burstable = _rds_is_burstable(res["type"])
    sc = res.get("surplus_credits")
    if sc is not None and sc > 0:
        _verdict(out, "upsize-candidate",
                 f"CPUSurplusCreditsCharged={sc} > 0，规格已不足，是升配候选")
        return out
    cb_min, cb_max = res.get("credit_balance_min"), res.get("credit_balance_max")
    if not burstable:
        if cb_min is not None:
            out["blockers"].append(CLASS_CHANGED_NOTE)
    elif (cb_min is not None and cb_max is not None
          and _credit_exhausted(cb_min, cb_max, t)):
        _verdict(out, "upsize-candidate",
                 f"CPU 信用余额窗口内触底（最小 {cb_min} / 窗口内最大 {cb_max}，"
                 f"门限 {t['credit_balance_floor_pct']}%），规格已不足，是升配候选")
        return out

    # ---- CPU 轴。峰值项取 Maximum 序列的 p95（_persistent 口径），不是 max ----
    sus_cpu, peak_cpu = res.get("sus_cpu"), res.get("peak_cpu_p95")
    dbload = res.get("dbload_p95")
    if sus_cpu is None and dbload is None:
        _verdict(out, "metric-missing",
                 "DBLoad 与 CPUUtilization 两轴都缺，无从反推需求量")
        return out
    rv_cpu = rv_cpu_sus = None
    if sus_cpu is not None:
        # peak 缺失 ⇒ 只用持续项，并写明。不当 0（那是替实例做假设），
        # 也不 fail-closed（另一轴可能可用）。
        rv_cpu_sus = _ceil_div(vcpu * sus_cpu, t["target_cpu_p95"])
        rv_cpu = (max(rv_cpu_sus, _ceil_div(vcpu * peak_cpu, t["ceiling_cpu_max"]))
                  if peak_cpu is not None else rv_cpu_sus)
        if peak_cpu is None:
            out["blockers"].append(
                "CPUUtilization Maximum 序列缺失，CPU 轴只用持续项 —— "
                "降配后峰值是否越 ceiling 未校验")
    if rv_cpu_sus is not None and rv_cpu_sus > vcpu:
        _verdict(out, "upsize-candidate",
                 f"CPU 持续 p95 {sus_cpu}% ⇒ 按目标 {t['target_cpu_p95']}% "
                 f"反推需 {rv_cpu_sus} vCPU，当前仅 {vcpu}。"
                 f"本 skill 不产出升配目标机型——选型需容量规划输入"
                 f"（增长率 / SLA / 峰值形态）")
        return out

    # ---- FreeableMemory 越地板：从 blocked 升为 upsize-candidate 并前移 ----
    freeable_min, mem_gib = res.get("freeable_mem_min_gib"), res.get("mem_gib")
    if freeable_min is None or mem_gib is None:
        _verdict(out, "metric-missing",
                 "FreeableMemory 或实例内存未知，无法判断降配是否 OOM")
        return out
    floor_gib = (t["rds_freeable_mem_floor_pct"] / 100) * mem_gib
    if freeable_min < floor_gib:
        # 原文案「降配会 OOM」只说了不能降，没说已经不够。实测两台可用内存
        # 分别剩 9.3% / 9.7%，那是欠配。前移到 cheaper 短路之前的依据见 C5。
        _verdict(out, "upsize-candidate",
                 f"FreeableMemory 最小值 {freeable_min} GiB < 实例内存 "
                 f"{t['rds_freeable_mem_floor_pct']}%（{round(floor_gib, 3)} GiB）"
                 f"⇒ 可用内存已不足，既不能降配也说明当前规格偏小。"
                 f"本 skill 不产出升配目标机型——选型需容量规划输入")
        return out

    # ---- DBLoad 轴 ----
    rv_dbload = None
    if dbload is None:
        cls_note = ("该实例类结构性不支持 Performance Insights"
                    f"（{res['type']} 在 rds-pi-unsupported.json 列表内），"
                    "DBLoad 不可得 ⇒ 本行只用 CPUUtilization 轴。"
                    "换用支持 PI 的实例类才能拿到第一判据"
                    if res["type"] in load_pi_unsupported()
                    else "Performance Insights 未开启，DBLoad 不可得 ⇒ 本行只用 "
                         "CPUUtilization 轴。开启后重采即可得第一判据")
        out["blockers"].append(cls_note)
    else:
        if dbload >= vcpu:
            _verdict(out, "blocked",
                     f"DBLoad p95 {dbload} >= vCPU {vcpu}，CPU 已是瓶颈")
            return out
        if dbload >= t["rds_dbload_ratio"] * vcpu:
            _verdict(out, "已合理配置",
                     f"DBLoad p95 {dbload} 未低于 {t['rds_dbload_ratio']}x"
                     f"vCPU({t['rds_dbload_ratio'] * vcpu})")
            return out
        rv_dbload = max(1, _ceil_div(dbload, t["rds_dbload_ratio"]))

    if burstable and sc is None:
        _verdict(out, "metric-missing",
                 "CPUSurplusCreditsCharged 缺失，无法排除信用已超额")
        return out
    if burstable and (cb_min is None or cb_max is None):
        _verdict(out, "metric-missing",
                 "CPUCreditBalance 缺失，无法排除信用已耗尽")
        return out

    req_vcpu = max(x for x in (rv_cpu, rv_dbload, 1) if x is not None)
    # buffer pool 会占满可分配内存，所以「已用」是真实工作集的上界。
    # 方向保守（不会推荐过小），代价是系统性少省。要修需要
    # innodb_buffer_pool_* 计数器，CloudWatch 不发布。
    req_gib = (mem_gib - freeable_min) / (1 - t["rds_freeable_mem_floor_pct"] / 100)
    out.update(required_vcpu=req_vcpu, required_gib=round(req_gib, 3))

    exclude = load_pi_unsupported() if res.get("pi_enabled") else frozenset()
    pick = _pick_managed_target(res, t, req_vcpu,
                                lambda c: c["gib"] >= req_gib, base or {},
                                exclude=exclude)
    if pick is None:
        cheaper = res.get("cheaper_candidate_exists")
        if cheaper is None:
            _verdict(out, "metric-missing",
                     "cheaper_candidate_exists 缺失，无法确认是否存在"
                     "更便宜的同形态候选（不得假定存在）")
            return out
        if not cheaper:
            _verdict(out, "已合理配置",
                     "同形态下没有更便宜的候选实例类；"
                     "补充指标或延长窗口都不会改变结论")
            return out
        _verdict(out, "downsize-candidate",
                 "需变更窗口 + 回滚预案；存储不可缩容，过度预配只能 next-rebuild",
                 _FIT_UNVERIFIED)
        return out
    if pick["excluded_best"]:
        eb = pick["excluded_best"]
        out["blockers"].append(
            f"更便宜的 {eb['t']} 已排除：该实例类不支持 Performance Insights，"
            f"而 DBLoad 是本判据的第一依据。若业务接受丢失 PI，可额外省 "
            f"${round((res['cur_usd'] - eb['usd']) * HOURS_PER_MONTH * res.get('count', 1), 2)}"
            f"/mo，但下一轮本行的 DBLoad 轴将不可得")
    if not pick["cheaper_exists"] or pick["empty_reason"]:
        _verdict(out, "已合理配置", pick["empty_reason"])
        return out
    _apply_managed_pick(out, res, pick, base or {})
    _verdict(out, "downsize-candidate",
             f"目标实例类为本 skill 初选（需 {req_vcpu} vCPU / "
             f"{round(req_gib, 3)} GiB，后者按 FreeableMemory 最小值反推并留 "
             f"{t['rds_freeable_mem_floor_pct']}% 余量），须人工确认变更窗口与回滚预案",
             "存储不可缩容，过度预配只能 next-rebuild",
             "内存需求由 FreeableMemory 反推，而 InnoDB buffer pool 会占满可分配"
             "内存 ⇒ 该值是真实工作集的**上界**，方向保守但会系统性少省。"
             "若变更时同步下调 innodb_buffer_pool_size，可选更小的实例类")
    return out
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_rds_criteria.py -q`
Expected: PASS

- [ ] **Step 6: 补三个新出口与逐出口 blocker 保序测试**

```python
def test_rds_cpu_sustained_over_current_yields_upsize():
    """P5：db-uat-05 实测 CPU 持续 p95 69.64%（4 vCPU），DBLoad p95 2.328
    差 0.328 跨过 0.5x4=2.0 的阈值 ⇒ 现行判「已合理配置」。"""
    out = core.eval_rds(
        _rds(type="db.m6g.xlarge", vcpu=4, mem_gib=16.0, cur_usd=0.4600,
             sus_cpu=69.64, peak_cpu_p95=71.09, dbload_p95=2.328,
             dbload_max_p95=11.0, freeable_mem_min_gib=0.864), T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"
    assert "CPU 持续 p95 69.64%" in out["blockers"][0]


def test_rds_freeable_memory_floor_yields_upsize_not_blocked():
    """db-uat-04 实测可用内存剩 9.7%、db-sit-05 剩 9.3%。"""
    out = core.eval_rds(
        _rds(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0, cur_usd=0.9190,
             sus_cpu=14.87, peak_cpu_p95=18.97, dbload_p95=1.211,
             dbload_max_p95=9.0, freeable_mem_min_gib=3.098), T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"
    assert "可用内存已不足" in out["blockers"][0]


def test_rds_verdict_reasons_precede_appended_notes_at_every_exit():
    """_verdict() 的覆盖坑已踩过三次（downsize-candidate 出口、已合理配置
    出口、没有更便宜候选出口），三次都是单元测试全绿而真实回放才发现。
    新出口必须逐个验分支理由排在已 append 的说明之前。"""
    r = _rds(partial_coverage=[("CPUCreditBalance", 178, 720)],
             sus_cpu=69.64, peak_cpu_p95=71.09)
    out = core.eval_rds(r, T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"
    assert "CPU 持续" in out["blockers"][0]           # 分支理由在最前
    assert any("覆盖不齐" in b for b in out["blockers"])  # 已 append 的没被吞
```

- [ ] **Step 7: 跑全套**

Run: `python -m pytest tests/ -q`
Expected: 全绿；EC2 基线不变

- [ ] **Step 8: Commit**

```bash
git add references/core.py references/rds-pi-unsupported.json tests/test_rds_criteria.py
git commit -m "feat(aws-rightsizing): RDS gets a CPU axis and three new exits

dbload_p95 absence was a dead end: metric-missing and return. PI is
structurally unsupported on db.t2/t3.micro/small and db.t4g.micro/small,
and can simply be off anywhere; metrics-catalog.md and sample-solve.md
both already promised a CPUUtilization fallback that did not exist.

The peak term uses the p95 of the Maximum series, not its max. RDS backup
windows and minor-version patching produce 42-99% single-hour spikes on
otherwise idle instances; judging on max leaves aggressive with 2 of 12
downsizable and conservative with 0. EC2's peak_cpu keeps taking max --
those spikes are real workload, not control-plane maintenance.

FreeableMemory below the floor becomes upsize-candidate and moves ahead of
the candidate-pool short-circuit: it now says \"too small\", not
\"cannot shrink\"."
```

---

### Task 5: `FreeStorageSpace` 耐久度判据

**Files:**
- Modify: `references/core.py`（`eval_rds` 第 7 步位置）
- Modify: `references/thresholds.json`
- Test: `tests/test_rds_criteria.py`

**Interfaces:**
- Consumes: `eval_rds`（Task 4）
- Produces: 读 `res["storage_free_min_gib"]` / `storage_free_first_gib` / `storage_free_last_gib` / `window_days`；新增阈值 `rds_storage_days_floor`

- [ ] **Step 1: 写失败测试**

```python
def test_rds_storage_exhausted_in_window_is_blocked_as_availability_incident():
    """P6：FreeStorageSpace 被采集、被聚合，全代码库零引用。
    db-sit-05 实测 Minimum 序列最小值 = 0.000 GB（400 GB gp3），
    Average 序列最小值 0.919 GB，窗口内 free 在 0-103 GB 间摆动。
    这台在报告里唯一的结论是「FreeableMemory < 15%，降配会 OOM」——
    磁盘被写满过这件事不存在。
    """
    out = core.eval_rds(
        _rds(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0, cur_usd=0.9190,
             sus_cpu=14.26, peak_cpu_p95=19.02, dbload_p95=1.070,
             dbload_max_p95=10.0, freeable_mem_min_gib=12.0,
             storage_free_min_gib=0.0, storage_free_first_gib=103.763,
             storage_free_last_gib=67.827), T_AG, BASE)
    assert out["verdict"] == "blocked"
    assert "可用性事故" in out["blockers"][0]


def test_rds_storage_runway_below_floor_requires_autoscaling_first():
    # 30 天消耗 (191.613 - 141.613) = 50 GiB ⇒ 速率 1.667 GiB/日
    # 剩余 141.613 / 1.667 = 85 天 —— 高于 aggressive 门限，不触发
    ok = core.eval_rds(_rds(storage_free_first_gib=191.613,
                            storage_free_last_gib=141.613,
                            storage_free_min_gib=141.613), T_AG, BASE)
    assert ok["verdict"] == "downsize-candidate"
    # 30 天消耗 180 GiB ⇒ 速率 6 GiB/日，剩余 11.6 / 6 = 1.9 天
    low = core.eval_rds(_rds(storage_free_first_gib=191.613,
                             storage_free_last_gib=11.613,
                             storage_free_min_gib=11.613), T_AG, BASE)
    assert low["verdict"] == "blocked"
    assert "storage autoscaling" in " ".join(low["blockers"])


def test_rds_storage_fields_missing_does_not_fail_closed():
    r = _rds()
    for k in ("storage_free_min_gib", "storage_free_first_gib",
              "storage_free_last_gib"):
        del r[k]
    out = core.eval_rds(r, T_AG, BASE)
    assert out["verdict"] == "downsize-candidate"
    assert any("FreeStorageSpace 缺失" in b for b in out["blockers"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rds_criteria.py -x -q -k storage`
Expected: FAIL — verdict 是 `downsize-candidate` 而非 `blocked`

- [ ] **Step 3: 加阈值**

`references/thresholds.json` 两个 profile 各加：

```json
"rds_storage_days_floor": 14
```

两档相同 —— 它不是利用率策略而是运维安全边界（见 `thresholds.md` 的标定段）。
即使两档同值也**必须两个 profile 都写**，`load_thresholds` 按 profile 取键，
少写一个会在另一档抛 `KeyError`。

- [ ] **Step 4: 实现（插在 `eval_rds` 的 FreeableMemory 出口之后、DBLoad 轴之前）**

```python
    # ---- FreeStorageSpace：容量耐久度。这是**可用性事故而非成本项** ----
    # 采集侧从一开始就采了它（含 Minimum 统计），agg.jq 也聚合了，
    # 而 core.py / report-template.md / sample-solve.md 一次都没提。
    st_min = res.get("storage_free_min_gib")
    st_first, st_last = (res.get("storage_free_first_gib"),
                         res.get("storage_free_last_gib"))
    if st_min is None:
        out["blockers"].append(
            "FreeStorageSpace 缺失，未评估容量耐久度（该指标对所有引擎都发布，"
            "缺失是采集缺口而非不适用）")
    elif st_min == 0:
        _verdict(out, "blocked",
                 "FreeStorageSpace 最小值 = 0 GiB ⇒ 窗口内存储被耗尽过。"
                 "**这是可用性事故，不是成本项**，优先级高于本行任何降配讨论。"
                 "先查 binlog / 事务日志保留与大临时表，并开启 storage autoscaling")
        return out
    elif st_first is not None and st_last is not None:
        # 速率用 Average 序列首尾差，**不用 Minimum** —— Minimum 含 binlog
        # 轮转造成的锯齿，会把速率算成负数或虚高。
        days = res.get("window_days") or 30
        rate = (st_first - st_last) / days
        if rate > 0:
            runway = st_last / rate
            if runway < t["rds_storage_days_floor"]:
                _verdict(out, "blocked",
                         f"按窗口内消耗速率 {round(rate, 3)} GiB/日外推，剩余 "
                         f"{round(runway, 1)} 天触顶（门限 "
                         f"{t['rds_storage_days_floor']} 天）⇒ 先开启 storage "
                         f"autoscaling 再谈降配。存储只能扩不能缩，"
                         f"降实例类不改变这条")
                return out
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_rds_criteria.py -q && python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add references/core.py references/thresholds.json tests/test_rds_criteria.py
git commit -m "feat(aws-rightsizing): consume FreeStorageSpace for durability

grep -rn FreeStorageSpace references/ returned nothing before this: the
recipe collects it with a Minimum statistic, agg.jq aggregates it, and no
criterion read it. One instance in the validation fleet has a Minimum-series
minimum of 0.000 GB on a 400 GB volume; its only reported conclusion was
that FreeableMemory sits below 15%.

Runway extrapolation uses the Average series head-to-tail delta. The
Minimum series carries binlog-rotation sawtooth and yields negative or
inflated rates."
```

---

### Task 6: `DBLoad` 峰值反转校验

**Files:**
- Modify: `references/core.py`（`eval_rds` 的 DBLoad 轴内）
- Test: `tests/test_rds_criteria.py`

**Interfaces:**
- Consumes: `eval_rds`（Task 4/5）
- Produces: 读 `res["dbload_max_p95"]`；模块常量 `DBLOAD_MINUTE_SAMPLES = 60`

- [ ] **Step 1: 写失败测试**

```python
def test_dbload_peak_reversal_fires_only_when_it_would_flip_the_verdict():
    """P7：判据只读 Average 序列，Maximum 序列大出两到三个数量级。

    先写的版本判「跨 stat 物理一致性」（mean(Maximum) > 60 x mean(Average)，
    否证 1 分钟发布周期），实测 12 台命中 9 台 —— 那测的是 PI 在本 region
    的发布语义，是全机队一致的属性，逐行报出只是噪声。

    改按「峰值单独看是否翻转结论」判：实测精确命中 2 台。
    """
    # db-infra-01：Maximum p95 = 23.0 ⇒ 23/0.5 = 46 vCPU > 2 ⇒ 触发
    hit = core.eval_rds(_rds(sus_cpu=6.05, peak_cpu_p95=9.67,
                             dbload_p95=0.186, dbload_max_p95=23.0,
                             freeable_mem_min_gib=3.167), T_AG, BASE)
    assert hit["confidence"] == "low"
    assert any("Performance Insights 控制台" in b for b in hit["blockers"])
    # db-sit-01：Maximum p95 = 1.0 ⇒ 1.0/0.5 = 2 vCPU，不超过 2 ⇒ 不触发
    miss = core.eval_rds(_rds(), T_AG, BASE)
    assert not any("Performance Insights 控制台" in b for b in miss["blockers"])
    # db-sit-06：Maximum p95 = 2.0 但 8 vCPU ⇒ 4 <= 8 ⇒ 不触发
    big = core.eval_rds(_rds(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0,
                             cur_usd=0.9190, sus_cpu=0.90, peak_cpu_p95=1.63,
                             dbload_p95=0.004, dbload_max_p95=2.0,
                             freeable_mem_min_gib=13.6), T_AG, BASE)
    assert not any("Performance Insights 控制台" in b for b in big["blockers"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rds_criteria.py -x -q -k peak_reversal`
Expected: FAIL — `assert hit["confidence"] == "low"`，实际为 `None`

- [ ] **Step 3: 实现**

模块常量（放在 `VETO_TOLERANCE_PCT` 旁）：

```python
# CloudWatch Period=3600 除以 PI 的标称 1 分钟发布周期。用于 run 级注记：
# mean(Maximum) > 60 x mean(Average) 否证「按 1 分钟发布」这个假设。
# 不进 thresholds.json —— 它是物理上界而非可按 profile 调的策略量，
# 与 VETO_TOLERANCE_PCT 同类。
DBLOAD_MINUTE_SAMPLES = 60
```

在 `eval_rds` 的 DBLoad 轴 `else` 分支里，`rv_dbload` 赋值之后：

```python
        # 峰值单独看就会翻转结论 ⇒ 报出来但**不改 verdict**。
        # 哪条序列代表真实负载取决于 PI 的发布语义（1 秒粒度 vs SampleCount
        # 稀释，两者与观测同样自洽），本 skill 拿不到，拿不到就不能算。
        # 与 _coverage_note() 同一条纪律。
        dbl_max = res.get("dbload_max_p95")
        if (dbl_max is not None
                and dbl_max / t["rds_dbload_ratio"] > vcpu):
            out["confidence"] = "low"
            out["blockers"].append(
                f"DBLoad 两条序列跨度极大：Average p95 {dbload} 判为可降，而 "
                f"Maximum 序列 p95 {dbl_max} 单独反推需 "
                f"{max(1, _ceil_div(dbl_max, t['rds_dbload_ratio']))} vCPU"
                f"（当前 {vcpu}）。降配前须在 Performance Insights 控制台核对 "
                f"Average Active Sessions 实际曲线 —— 本 skill 无法判定 Average "
                f"是细粒度均值还是被 SampleCount 稀释，两者与观测同样自洽")
```

`_ceil_div` 需要整数入参语义，`dbl_max` 是浮点：`_ceil_div` 内部用
`math.ceil(numer / denom)`，浮点安全，无需改动。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_rds_criteria.py -q && python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add references/core.py tests/test_rds_criteria.py
git commit -m "fix(aws-rightsizing): surface DBLoad peak when it flips the verdict

The Maximum series is collected, written to the CSV evidence column, and
judged by nothing. On the validation fleet it runs 5x to 1370x above the
Average series; one instance is judged downsize on an Average p95 of 0.096
while its hourly peaks reach 23 active sessions on 2 vCPU.

Fires on the peak-would-flip-the-verdict test, not on cross-stat physical
consistency. The latter hits 9 of 12 instances -- it measures PI's
publishing semantics for the whole fleet, so per-row output is noise. The
former hits exactly 2."
```

---

### Task 7: 托管回归机队

**Files:**
- Create: `tests/fixtures/regression-managed.json`
- Create: `tests/test_regression_managed.py`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 托管侧 `route1_nb` / `route2_max` 基线

- [ ] **Step 1: 造 fixture**

`tests/fixtures/regression-managed.json`。资源用脱敏名，**指标值与价目取真值**。
覆盖形态清单（每条至少一行）：RDS 选出突发目标 / RDS 选出非突发目标 /
RDS CPU 持续超 ⇒ upsize / RDS FreeableMemory 越地板 ⇒ upsize /
RDS 存储触 0 ⇒ blocked / RDS 峰值反转 ⇒ low /
ElastiCache 选出目标 / ElastiCache 在价目地板 / ElastiCache 指标越目标 /
MSK 跨架构无候选 / MSK 在价目地板 / 三个服务各一行 `candidates` 缺失（回退旧路径）。

```json
{
  "_comment": "托管回归机队。与 regression-fleet.json（EC2 独占 13 行）分开：EC2 基线的数字带着「旧值不删 + 写明成因」的长注释链，把托管金额并进去会让两类改动的成因永久纠缠在同一个数字上。资源名已脱敏，指标值/点数/金额/机型是真值。",
  "specs": [], "prices": {}, "categories": {}, "offerings": [],
  "legacy_families": [],
  "baseline_pct": {"t4g.micro": 0.10, "t4g.small": 0.20,
                   "t4g.medium": 0.20, "t4g.large": 0.30,
                   "t4g.xlarge": 0.40, "t4g.2xlarge": 0.40},
  "resources": []
}
```

`resources` 逐条按 Task 1–6 的测试常量填写（`_rds()` / `_ec()` / `_msk()`
的字段集），并给每条加 `"sample_n": 242`（真实 biz-hours 点数）。

- [ ] **Step 2: 写基线测试**

```python
# tests/test_regression_managed.py
"""托管侧回归基线。

**与 test_regression_fleet.py 分开**：那份 fixture 是 EC2 独占的 13 行，
它的 route1_nb=527.15 / route2_max=668.85（aggressive）在仓库历史里带着
一条长注释链。本轮不碰 EC2 路径，那两个数字必须逐分不变。

基线来源：账号 123456789012 / ap-east-1 的归档数据离线重放
（12 RDS + 11 Redis 复制组 + 8 MSK 集群）。
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).parent.parent
CORE = ROOT / "references" / "core.py"
FIXTURE = ROOT / "tests" / "fixtures" / "regression-managed.json"

# 逐格对账见 docs/specs/2026-09-13-managed-target-selection-design.md 的
# 「本机队实测」表。MSK 两条路线都是 0 且**这是正面产出** ——
# kafka.m7g.large 全区更便宜的 broker 机型只有 kafka.t3.small(x86)，
# 跨架构为硬约束禁止项；6 个 kafka.t3.small 集群在价目地板上。
EXPECTED = {
    "aggressive": {"rds_route1": 261.34, "rds_route2": 875.27,
                   "ec_route1": 0.0, "ec_route2": 1235.89,
                   "msk_route1": 0.0, "msk_route2": 0.0},
    "conservative": {"rds_route1": 261.34, "rds_route2": 875.27,
                     "ec_route1": 0.0, "ec_route2": 1158.51,
                     "msk_route1": 0.0, "msk_route2": 0.0},
}


def _run(profile):
    ctx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ctx["sizing_profile"] = profile
    p = subprocess.run([sys.executable, str(CORE)], input=json.dumps(ctx),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _totals(findings, service):
    dn = [f for f in findings
          if f["service"] == service and f.get("bucket") == "downsize"]
    return {
        "route1": round(sum(f.get("nb_save_mo") or 0 for f in dn), 2),
        "route2": round(sum(max(f.get("nb_save_mo") or 0,
                                f.get("b_save_mo") or 0) for f in dn), 2),
    }


def test_managed_route_totals_match_baseline():
    for profile, exp in EXPECTED.items():
        fs = _run(profile)
        for svc, key in (("rds", "rds"), ("elasticache", "ec"), ("msk", "msk")):
            got = _totals(fs, svc)
            assert got["route1"] == exp[f"{key}_route1"], (profile, svc, got)
            assert got["route2"] == exp[f"{key}_route2"], (profile, svc, got)


def test_rows_without_candidates_produce_no_target():
    """向后兼容：采集侧未升级的行必须逐字保持改动前行为。"""
    fs = {f["rid"]: f for f in _run("aggressive")}
    for rid in ("db-legacy-01", "redis-legacy-01", "msk-legacy-01"):
        f = fs[rid]
        assert f["nonburst"] is None and f["burst"] is None
        assert f.get("nb_save_mo") is None and f.get("b_save_mo") is None
        assert any("未经校验" in b for b in f["blockers"])


def test_managed_rows_never_claim_high_confidence():
    """high 在 EC2 侧的含义是「CPU 与内存两轴都有实测数据」，语义不同，
    不可套用。托管侧的适配校验建在观测稳态上，不含业务增长输入。"""
    for profile in EXPECTED:
        for f in _run(profile):
            if f["service"] != "ec2":
                assert f.get("confidence") in (None, "medium", "low"), f["rid"]
```

- [ ] **Step 3: 跑测试，按实际输出对账并修正 `EXPECTED`**

Run: `python -m pytest tests/test_regression_managed.py -q`

若数字与 spec 的表不符，**先查是 fixture 造错还是实现错，不要直接改 `EXPECTED`**。
`EXPECTED` 的每次变更都要在文件头注释里留「旧值 + 成因 + 逐条对账」。

- [ ] **Step 4: 确认 EC2 基线一分未动**

Run: `python -m pytest tests/test_regression_fleet.py -q -v`
Expected: PASS，`route1_nb` / `route2_max` 与改动前逐分相同

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/regression-managed.json tests/test_regression_managed.py
git commit -m "test(aws-rightsizing): managed-side regression baseline

Separate fixture from regression-fleet.json, which is EC2-only. That
baseline's numbers carry a long comment chain about why each value
changed; folding managed amounts in would entangle two classes of change
in one number permanently."
```

---

### Task 8: `test_no_duplicated_constants.py` 覆盖两个新真值源

**Files:**
- Modify: `tests/test_no_duplicated_constants.py`

**Interfaces:**
- Consumes: `load_pi_unsupported`（Task 4）。`managed_mem_headroom` 实现期作废，
  本轮只有一个新真值源需要守卫
- Produces: 无（守卫测试）

- [ ] **Step 1: 读现有约定**

Run: `sed -n '1,50p' tests/test_no_duplicated_constants.py`

- [ ] **Step 2: 写失败测试**

```python
def test_pi_unsupported_list_lives_in_exactly_one_file():
    src = (ROOT / "references" / "core.py").read_text(encoding="utf-8")
    for cls in ("db.t4g.micro", "db.t4g.small", "db.t3.micro", "db.t3.small",
                "db.t2.micro", "db.t2.small"):
        assert cls not in src, f"{cls} 硬编码进了 core.py；唯一真值源是 rds-pi-unsupported.json"
    data = json.loads((ROOT / "references" / "rds-pi-unsupported.json")
                      .read_text(encoding="utf-8"))
    assert data["_source"].startswith("https://")
    assert data["_recheck"] and data["_why"]
    assert len(data["classes"]) == len(set(data["classes"]))
```

- [ ] **Step 3: 跑测试，修掉任何硬编码**

Run: `python -m pytest tests/test_no_duplicated_constants.py -q`
Expected: PASS（若 FAIL，把硬编码值改为读真值源）

- [ ] **Step 4: Commit**

```bash
git add tests/test_no_duplicated_constants.py
git commit -m "test(aws-rightsizing): guard the two new sources of truth"
```

---

### Task 9: 采集契约与文档

**Files:**
- Modify: `references/cli-recipes.md`（§2.3 mdq 列表、§7 托管行组装、字段表）
- Modify: `references/sample-solve.md`（字段契约表、示例行、结论表）
- Modify: `references/report-template.md`（托管小节、汇总口径）
- Modify: `references/metrics-catalog.md`（`DBLoad` 行、`FreeStorageSpace` 行）
- Modify: `references/thresholds.md`（两个新阈值的标定）
- Modify: `SKILL.md`（托管服务小节）

**Interfaces:**
- Consumes: 全部前序任务的字段名与语义
- Produces: 采集侧可据以组装 `candidates` / `cur_usd` / `count` / `pi_enabled` / `sus_cpu` / `peak_cpu_p95` / `dbload_max_p95` / `storage_free_*` / `window_days`

- [ ] **Step 1: `cli-recipes.md` §2.3 加两个指标的 stat**

`DBLoad` 已采 `Average, Maximum`（无需改）。确认 `FreeStorageSpace` 已含
`Minimum`（第 470 行已有）。**新增**：`CPUUtilization` 的 `Maximum` 序列
须取 `full-window` 档的 `p95`（不是 `max`），在字段表里写明与 EC2 侧
`peak_cpu` 的口径差异及依据。

- [ ] **Step 2: `cli-recipes.md` 托管行组装段加字段表**

```markdown
| 全部托管 | `candidates` | 该资源同形态、同 `arch` 的**全部**候选（含比当前贵的），每项 `{t, usd, vcpu, gib, arch, burst}`。取价用各服务的复合键（RDS `engine`+`deploymentOption`；ElastiCache `^[A-Z0-9]+-NodeUsage:` 紧邻正则 + `(type, operation)` 双重消歧；MSK `computeFamily` 且排除 Express）。`gib` **必须**来自 pricing 的 `memory` 属性 | 缺失 ⇒ 回退旧路径（读 `cheaper_candidate_exists`、不出目标），**不 fail-closed** |
| 全部托管 | `cur_usd` | 当前规格的按需小时价。`candidates` 存在时必填 | 缺失 ⇒ 同上回退 |
| 全部托管 | `count` | 节点数 / broker 数，用于金额乘算 | 缺失按 1 |
| 全部托管 | `arch` | `arm64` / `x86_64`。剥掉 `db.`/`cache.`/`kafka.` 前缀后查 `ec2-types.json`。**只查 arch，绝不查 memory** —— `cache.t3.medium` 真实 3.09 GiB，EC2 映射得 4.00 GiB，偏 +29% | 缺失 ⇒ 同架构筛选失败 ⇒ 报「跨架构」成因 |
| RDS | `sus_cpu` | `CPUUtilization` / `Average` / `biz-hours` 的 `p95` | 与 `dbload_p95` **两者都缺**才 `metric-missing` |
| RDS | `peak_cpu_p95` | `CPUUtilization` / `Maximum` / **`full-window`** 的 `p95`（**不是 `max`**，与 EC2 侧 `peak_cpu` 口径不同，依据见 spec C4） | 缺失 ⇒ CPU 轴只用持续项 + blocker |
| RDS | `dbload_max_p95` | `DBLoad` / `Maximum` / `full-window` 的 `p95` | 缺失 ⇒ 不做峰值反转校验 |
| RDS | `storage_free_min_gib` | `FreeStorageSpace` / **`Minimum`** / `full-window` 的 `min`，单位 GiB | 缺失 ⇒ 不评估耐久度 + blocker |
| RDS | `storage_free_first_gib` / `storage_free_last_gib` | `FreeStorageSpace` / `Average` / `full-window` 的窗口首点与末点。**不用 `Minimum`** —— 含 binlog 轮转锯齿，会把速率算成负数或虚高 | 缺失 ⇒ 不做剩余天数外推 |
| RDS | `window_days` | 窗口天数 | 缺失按 30 |
| RDS | `pi_enabled` | `describe-db-instances` 的 `PerformanceInsightsEnabled` | 缺失 ⇒ 不排除 PI 不支持的候选 |
```

- [ ] **Step 3: `sample-solve.md` 修掉自相矛盾**

第 171 行 `sample_n` 的定义已写「未开 PI 时用 `CPUUtilization`」，
第 176 行写 `dbload_p95` 缺失 ⇒ `metric-missing`。把第 176 行改为：

```markdown
| RDS | `dbload_p95` | Performance Insights `db.load.avg` 的 p95。与 `sus_cpu` 是**并行两轴**（`req_vcpu` 取两轴的 max），不是主备 | **两轴都缺**才 `metric-missing`。单缺 `dbload_p95` ⇒ 只用 CPU 轴 + blocker，且按成因分写「该实例类结构性不支持 PI」与「PI 未开启」 |
```

同步更新示例行（加 `candidates` / `cur_usd` / `arch` / `count` / `pi_enabled` /
`sus_cpu` / `peak_cpu_p95`）与结论表（`db-EX-01` 的结论加目标机型）。

- [ ] **Step 4: `report-template.md` 删旧裁定、加目标列**

删掉「托管服务候选小计（不计入头条数字）」整节的**裁定部分**，保留
「托管服务的目标由人工审核」这层含义并改写：

```markdown
## 托管服务的目标机型（进头条，标 confidence）

三条托管判据现在产出 `nonburst` / `burst` 与对应 `*_save_mo`，因此它们的
节省额**与 EC2 行同等进入路线一/二**，不需要第三条口径。

代价与约束：
- 托管行 `verdict` 仍是 `downsize-candidate`，且**必带** blocker
  「目标实例类/node type 为本 skill 初选……须人工确认」。
- 托管行 `confidence` 只有 `medium` / `low`，**永不 `high`**。摘要必须给出
  `confidence=low` 的 breakout（这条规则此前对托管行永不触发，因为那一列是空的）。
- 摘要须单列「其中托管服务（待人工确认）$X」一行，让读者能把它从
  EC2 侧的金额里分出来。**这不是第三条口径**，是同一个分子的成分拆分。
```

- [ ] **Step 5: `metrics-catalog.md` 两行**

`DBLoad` 行的「已实测」栏补：

```markdown
两条序列跨度极大（实测 5x–1370x）。成因无法从聚合值判定：PI 以 1 秒粒度发布（3600 点/小时，`3600 x mean >= max` 对全部 12 台成立）与 `SampleCount` 稀释两种解释同样自洽。判据只用 Average 轴，Maximum 轴的 p95 用于**峰值反转校验**（见 core.py），不改 verdict。
```

`FreeStorageSpace` 行的消费者栏从空改为：

```markdown
`eval_rds` 的容量耐久度判据：`Minimum` 最小值触 0 ⇒ `blocked`（可用性事故）；`Average` 首尾差外推剩余天数 < `rds_storage_days_floor` ⇒ `blocked`
```

- [ ] **Step 6: `thresholds.md` 加两个阈值的标定段**

ElastiCache 内存轴：写明 `target_mem_p95` 反推取代 `max_mem_reduction_ratio` 的
职责，附阶梯比值表（2.74 / 2.26 / 2.07）与「按比值地板筛，conservative 下
11 组全部 $0」的实测结论。**不新增阈值。**

`rds_storage_days_floor`：写明两个 profile 同值的理由（运维安全边界而非
利用率策略），以及为什么仍要在两个 profile 都写（`load_thresholds` 按 profile
取键，少写一个会 `KeyError`）。

- [ ] **Step 7: `SKILL.md` 托管服务小节**

把「托管服务不自选目标」改为「托管服务产出**初选**目标，人工审核」。
**硬约束清单一字不改** —— 本轮只在允许的动作空间内选目标。
第 308 行 `DBLoad p95 >= vCPU 数 ⇒ CPU 已是瓶颈` 保留，其后补 CPU 轴与
三个新出口的一句话说明。

- [ ] **Step 8: 文档一致性自检**

```bash
cd ~/git/panlm-skills/aws-rightsizing
# 旧承诺是否清干净
grep -rn "不自选目标\|结构性不在路线一/二\|_FIT_UNVERIFIED" references/ SKILL.md
# 新字段是否三处都提到（cli-recipes 采集、sample-solve 契约、core.py 消费）
for f in candidates cur_usd pi_enabled peak_cpu_p95 dbload_max_p95 storage_free_min_gib; do
  echo "== $f"; grep -rln "$f" references/ | sort
done
# 脱敏
# 真实账号 ID 与客户资源名前缀：从本轮归档目录名与 raw/inventory/*.json 取，
# 逐个 grep。本仓库公开，命中即须改占位名（db-<env>-NN 等）。
grep -rnE "$(printf '%s|' "${REAL_NAME_PATTERNS[@]}")0{12}" references/ SKILL.md docs/ || echo CLEAN
```

Expected: 旧承诺零命中；每个新字段在 `cli-recipes.md` / `sample-solve.md` /
`core.py` 三处都有；脱敏 CLEAN

- [ ] **Step 9: Commit**

```bash
git add references/cli-recipes.md references/sample-solve.md \
        references/report-template.md references/metrics-catalog.md \
        references/thresholds.md SKILL.md
git commit -m "docs(aws-rightsizing): managed targets enter the headline routes

sample-solve.md said both 'RDS falls back to CPUUtilization when PI is
off' and 'dbload_p95 missing => metric-missing'. Only one can be true;
the fallback now exists, so the field table says so.

report-template.md's ruling that managed savings are structurally outside
route 1/2 was a downstream consequence of the target columns being empty.
They are no longer empty, so managed rows join the existing two routes
rather than needing a third."
```

---

### Task 10: 真实数据回放门禁

**Files:**
- Create: `docs/plans/2026-09-13-managed-target-selection-replay.md`（回放结果记录）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 逐条对账结论；`EXPECTED` 与 spec 表的一致性证明

- [ ] **Step 1: 从归档数据组装 solver 输入**

归档在 `~/Downloads/rightsizing-20260910/rerun-20260911/report_output/<account>-<region>-<date>/raw/`。
写一次性脚本（**不进仓库**，产出根 `report_output/` 已在 `.gitignore`）：
从 `raw/inventory/*.json` + `raw/metrics/agg-*.json` + `raw/specs/*-price-raw.json`
组装带 `candidates` 的托管行，喂 `references/core.py`。

`candidates` 的取价复合键按 Global Constraints 的三条规则实现；
ElastiCache 的 `gib` 取 pricing `memory`，`arch` 按机型名末位 `g` 判 Graviton
（ElastiCache pricing 无 arch 属性，RDS 用 `physicalProcessor` 含 `Graviton`）。

- [ ] **Step 2: 逐条核对**

Expected（与 spec 的「本机队实测」表逐格一致）：

| 断言 | 期望 |
|---|---|
| 12 RDS：选出目标 | 9 行 |
| RDS `verdict` 分布 | `downsize-candidate` 9 / `blocked` 2 / `upsize-candidate` 1 |
| 12 RDS：存储触 0 ⇒ blocked | 1 行 |
| 12 RDS：`FreeableMemory` 越地板 ⇒ blocked | 1 行 |
| 12 RDS：CPU 持续超 ⇒ upsize | 1 行 |
| 阶梯最底档告警命中 | 3 组（两 profile 同） |
| RDS 路线一 / 路线二 | $261.34 / $875.27（两 profile 同值） |
| 11 Redis：选出目标 | 5 组 |
| 11 Redis：在价目地板 | 4 组 |
| 11 Redis：指标越目标 | 2 组 |
| Redis 路线二 | ag $1,235.89 / co $1,158.51 |
| 8 MSK：全部「同架构下更便宜候选数 0」且 blocker 指明成因 | 8 行 |
| `FreeStorageSpace` 触 0 被报出 | 1 行（`db-sit-05`） |
| `DBLoad` 峰值反转校验命中 | **4 行**（`db-uat-01` / `db-infra-01` / `db-sit-05` / `db-uat-04`），不是 9 行 |
| 托管行 `confidence` 为 `high` | **0 行** |

- [ ] **Step 3: 安全自检（三条 grep 照旧）**

```bash
cd ~/git/panlm-skills/aws-rightsizing
grep -rnE "\b(create|delete|modify|update|put|terminate|stop|start|reboot)-" references/cli-recipes.md | grep -v "^.*#" || echo "只读 CLEAN"
grep -rn "ce:\|cost-explorer\|get-cost-and-usage" references/ SKILL.md || echo "账单 API CLEAN"
grep -rn "kubeconfig" references/cli-recipes.md | head -5
```

- [ ] **Step 4: 把回放结果写进记录文档并提交**

记录须含：逐条对账表（实际 vs 期望）、任何偏差的成因、
`test_regression_fleet.py` 两个数字改动前后的比对（必须相同）。
资源名脱敏。

- [ ] **Step 5: 跑全套测试并提交**

```bash
python -m pytest tests/ -q
git add docs/plans/2026-09-13-managed-target-selection-replay.md
git commit -m "docs(aws-rightsizing): record the managed-target replay gate"
```

---

## Self-Review

**1. Spec coverage**

| Spec 段 | 实现任务 |
|---|---|
| P1 / C1 候选池取代布尔值 | Task 1（helper）、Task 2/3/4（三个 evaluator 的 `candidates` 优先读取） |
| P2 / C2 适配校验进 `core.py`、删 `_FIT_UNVERIFIED` | Task 1/2/3/4，Task 9 Step 8 校验旧文案清干净 |
| P3 / C7 托管节省进头条 | Task 9 Step 4（口径）、Task 7（基线） |
| P4 / C5-1 CPU 兜底 + 两种 PI 成因分写 | Task 4 |
| P5 / C5-2、C5-3 两个新 upsize 出口 | Task 4 |
| P6 / C6 `FreeStorageSpace` | Task 5 |
| P7 / C6 峰值反转校验 | Task 6 |
| P8 / C2 内存下限改由 `target_mem_p95` 反推 | Task 2 |
| P9 / C4 RDS 峰值项走 `_persistent` | Task 4 |
| C3 候选池为空的五种成因 | Task 1 Step 5 |
| C7 PI 不支持列表 + baseline 反推 | Task 4 Step 3、Task 1 Step 6、Task 8 |
| C7 降幅超 4 档强制 low | Task 2 Step 6 |
| C8 向后兼容 | Task 1 Step 6、Task 7 Step 2 |
| 测试影响清单 | Task 1/2/3/4/5/6/7/8 |
| 验证方式 4 条 | Task 10 |

**缺口一处，已补**：spec C6 要求把 `mean(Maximum) > 60 x mean(Average)` 的观测
写进 `metric-validation.json` 的 run 级注记。`metric-validation.json` 由**采集侧**
生成（不在 `core.py`），故归入 Task 9 —— 已在 Step 1 的 `cli-recipes.md` 改动范围内，
但原文没点名。执行 Task 9 时须在 §校验段加这条注记的生成方式：
对每个 RDS 实例比较两条序列的 `mean`，把命中数写成
`"dbload_publish_period_inconsistent": {"hit": N, "total": M}`。

**2. Placeholder scan**：无 TBD / TODO / "similar to Task N" / "add error handling"。
每个代码步骤都有可运行的代码块。Task 7 Step 1 的 fixture 内容以「覆盖形态清单 +
指向 Task 1–6 测试常量」的方式给出而非逐行 JSON —— 那些常量在本文件里都是完整代码，
不是占位。

**3. Type consistency**

- `_pick_managed_target` 返回键 `nonburst` / `burst` / `cheaper_exists` /
  `empty_reason` / `excluded_best` —— Task 1/2/3/4 全部一致。
- `_apply_managed_pick(out, res, pick, base)` 四参 —— Task 2/3/4 调用一致。
- 三个 evaluator 签名统一 `(res, t, base=None)`，`dispatch()` 传
  `ctx.get("baseline_pct") or {}` —— Task 2 Step 4.4 改一次，Task 3/4 沿用。
- 字段名：`peak_cpu_p95`（RDS，非 EC2 的 `peak_cpu`）、`dbload_max_p95`、
  `storage_free_min_gib` / `storage_free_first_gib` / `storage_free_last_gib`、
  `pi_enabled`、`cur_usd`、`count`、`arch`、`candidates` —— Task 4/5/6 的测试与
  Task 9 的字段表一致。
- 阈值键：`rds_storage_days_floor` —— Task 5/8 一致。`managed_mem_headroom` 实现期作废。
- 常量：`DBLOAD_MINUTE_SAMPLES` 只出现一次定义。`_MANAGED_DEEP_STEPS` 实现期作废（护栏改判「落在阶梯最底档」，无阈值）。
