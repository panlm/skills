# 第二轮运行反馈修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉两次真实端到端运行暴露的 5 个判据缺陷、10 个契约缺口、7 个采集配方缺陷和 6 项文档卫生问题，使同一机队在任何 agent runtime 下产出可比的报告。

**Architecture:** 判据缺陷全部收敛到 `references/core.py`（含托管采样守卫放进已有的 `dispatch()` 单一入口）；契约与口径缺口写进 `references/report-template.md`；采集配方缺陷改 `references/cli-recipes.md`。判据改动一律配可失败的测试；文档改动不碰判据、不需重跑回归。

**Tech Stack:** Python 3（无 pytest，每个测试文件用 `if __name__ == "__main__"` 块）、jq、AWS CLI v2（只读）。

**Spec:** `docs/superpowers/specs/2026-09-04-run2-findings-design.md` —— 含 7 条已核实的裁定（R1–R7）与全部实测证据。**执行前必读**，尤其 R1（ElastiCache 的原记录是对的，只能新增不能删改）与 R2（内存降幅上限会移动回归基线）。

## Global Constraints

- `references/thresholds.json` 是全部阈值数字的唯一真值源。`references/core.py` 与任何 `references/*.md` / `references/*.jq` 里不得出现阈值字面量，除非该行同时带实测标记（`实测` / `verified` / `证据`）。`tests/test_no_duplicated_constants.py` 强制这条，且它的守卫清单由 `thresholds.json` 生成。
- 缺失指标一律 `None` 且 fail-closed。禁止 `or 0`、`// 0`、`or 1e9` 或任何让缺失读成真实值的兜底。`0` 是有效测量值，与缺失用显式 `is None` 区分。
- 阈值一律用下标 `t["key"]` 取，不用 `.get()`。缺键必须抛 `KeyError`。
- 回归基线由 `aws-rightsizing/tests/fixtures/regression-fleet.json` 与 `tests/test_regression_fleet.py` 锚定：aggressive `route1_nb=401.51` / **`route2_max=534.01`**，conservative `route1_nb=312.48` / **`route2_max=395.26`**。**只有 Task 5 允许改这些数字，且必须重算后记录新值与成因，永不为了让断言通过而调数字。**

  > **⚠️ 2026-09-04 补注：路线二那两个数已在 Task 5 执行中迁移,上面写的是迁移后的现行值。**
  > 本计划最初写的是 `route2_max=551.97` / `413.22`——那是**加内存降幅地板之前**的口径。
  > Task 5 加了 `max_mem_reduction_ratio` 后,两台 4 GiB 实例的 burst 候选由 1 GiB(4x)
  > 被拦成 2 GiB(2x),两个 profile 各降 $17.96。路线一两个数未变(超限候选全是 burstable,
  > 而路线一只取 non-burstable)。
  > 旧值没有被删除:它们在 `tests/test_regression_fleet.py` 里既作为撤回记录保留、
  > 又作为"地板关闭态"的活断言(`MEM_FLOOR_OFF_ROUTE2`),所以这道地板一旦被静默移除就会报红。
  > **本行按现行值改而不是只加注,因为它是可执行的验收标准**——重跑的人拿这一行当通过条件,
  > 留着作废数字等于递给下一个人一个错的门禁。
  > **同一条判据在本文件里唯一还留着旧值的地方是 Task 5 Step 6 那段**,
  > 它写的是「旧值保留标注、不删」,读起来就是记录、不会被当成通过条件,所以原样保留。
  > (本文件的八条 `git commit -m` 都是不带数字的一行标题,不在这条取舍的范围内——
  > 上一版这句话把它们说成"被引用的 commit message 正文",会让人去找一个不存在的东西。)
- 全部测试文件必须能独立跑通：`python3 <file>`。门禁是 `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done`，必须 `exit 0`。
- 任何提到的机型必须是真实存在的 AWS 机型，且其族不在 `references/legacy-families.json` 里（注意 `t2` 在清单内）。用 `AWS_PROFILE=panlm aws ec2 describe-instance-types --instance-types <t> --region ap-northeast-1` 核实，不要凭印象——上一轮出过 `m5.small` 这种不存在的机型。
- `aws-rightsizing/` 下任何文件不得含 AWS 账号 ID、实例/卷/NAT/ENI/子网/安全组 ID、ARN、EKS 集群名、负载均衡器名。本 skill 交付到 public repo。
- `references/core.py` 只做判断：不调 AWS API，除同目录 `thresholds.json` 与测试 fixture 外不做文件 I/O，不含采集逻辑。
- skill 不做任何变更类 AWS 调用，不用 Cost Explorer / 账单 API（`pricing:GetProducts` 允许）。
- 每加一条断言，都要把它守的行为改坏一次、确认它以**自己的消息**失败（不是顺带的 `KeyError`），并把该验证的输出粘进报告。裸 `assert` 一律补消息——上一轮有断言在变异下报空消息通过。

---

### Task 1: 托管三判据的采样量守卫

**Files:**
- Modify: `aws-rightsizing/references/core.py`（`dispatch()`，当前在 `:547`）
- Modify: `aws-rightsizing/references/sample-solve.md`（托管服务输入契约字段表）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: `dispatch(res, ctx)`、`SERVICES`、`MANAGED_EVALUATORS`、`t["min_biz_hours_points"]`
- Produces: 托管输入契约新增必填字段 `sample_n`（整数或 `None`），语义=该资源**主判据指标**在 biz-hours 档的有效点数。后续任务不依赖它。

**背景（实测）：** 一个 MSK 集群指标历史仅 31 小时、biz-hours 只有 14 点（门限 168），`core.py` 照样输出 `downsize-candidate`。`eval_rds` / `eval_elasticache` / `eval_msk` 都不读任何点数字段。两个 agent 都被迫在采集侧自己补这道守卫——而 `evaluate()` 里那条守卫的注释原话是「必须在此短路，不能只写在文档里靠调用方自觉」。

- [ ] **Step 1: 写失败测试**

在 `tests/test_managed_dispatch.py` 末尾（`__main__` 块之前）加：

```python
def test_managed_evaluators_have_sampling_guard():
    """托管三判据必须和 EC2 一样在采样量不足时短路。

    实测缺陷：某 MSK 集群 biz-hours 仅 14 点（门限 168），仍输出
    downsize-candidate。两个 agent 都被迫在采集侧自己补守卫。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = {
        "rds": dict(rid="db-X", service="rds", type="db.r6g.large", vcpu=2,
                    mem_gib=16, surplus_credits=0, dbload_p95=0.1,
                    freeable_mem_min_gib=8.0),
        "elasticache": dict(rid="cc-X", service="elasticache",
                            type="cache.m6g.large", vcpu=2, mem_gib=6.38,
                            evictions_sum=0, repl_lag_max=0.0,
                            engine_cpu_p95=1.0, db_mem_used_pct_max=2.0),
        "msk": dict(rid="mk-X", service="msk", type="kafka.m7g.large",
                    under_replicated_max=0, disk_used_max=10.0,
                    handler_idle_p95=0.99, cpu_total_p95=3.0),
    }
    for svc, res in cases.items():
        res["sample_n"] = floor - 1
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "insufficient-data", (
            f"{svc}: sample_n={floor - 1} < {floor} 却给出 {got['verdict']}；"
            f"采样量不足时不得产出任何建议 —— got={got}")
        assert str(floor) in " ".join(got.get("blockers") or []), (
            f"{svc}: blockers 未写出门限值，运维看不到为什么判不了 —— {got}")
    for svc, res in cases.items():
        res["sample_n"] = floor
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] != "insufficient-data", (
            f"{svc}: sample_n 恰好等于门限应放行，却仍是 insufficient-data —— {got}")


def test_managed_missing_sample_n_is_insufficient_not_pass():
    """sample_n 缺失必须 fail-closed，不得当成「点数够」放行。"""
    t = core.load_thresholds("aggressive")
    res = dict(rid="mk-Y", service="msk", type="kafka.m7g.large",
               under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "insufficient-data", (
        f"sample_n 缺失被当成点数充足放行了 —— {got}")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
```
Expected: FAIL，消息形如 `msk: sample_n=167 < 168 却给出 downsize-candidate`

- [ ] **Step 3: 在 `dispatch()` 里加守卫**

把 `dispatch()` 的末两行改成：

```python
    if svc == "ec2":
        return evaluate(res, ctx)
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

- [ ] **Step 4: 跑测试确认通过 + 全门禁**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 两条新测试 PASS，8 个文件全绿（`sample_n` 只影响托管行，EC2 回归基线不动）

- [ ] **Step 5: 变异验证**

把守卫的 `if n is None or n < floor_pts:` 改成 `if False:`，重跑 `tests/test_managed_dispatch.py`，确认以自己的消息失败；再把 `res.get("sample_n")` 改成 `res.get("sample_n", 10**9)`，确认第二条测试失败。两次输出都粘进报告，然后还原。

- [ ] **Step 6: 更新托管输入契约**

在 `references/sample-solve.md` 的托管服务字段表最前面加一行，并在表下方补一句说明：

```markdown
| `sample_n` | **必填。** 该资源**主判据指标**在 biz-hours 档的有效点数：RDS 用 `DBLoad`（未开 PI 时用 `CPUUtilization`）、ElastiCache 用 `EngineCPUUtilization`、MSK 用 `CpuUser+CpuSystem` | 低于 `min_biz_hours_points` 或缺失 ⇒ `insufficient-data`，不产出任何建议 |
```

说明句：`sample_n` 的守卫在 `dispatch()` 里短路，早于任何否决项——采样量不足时连否决项都不该报，因为那些指标同样没有统计意义。

- [ ] **Step 7: 提交**

```bash
git add aws-rightsizing/references/core.py aws-rightsizing/references/sample-solve.md aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "fix: managed evaluators get the same sampling guard as EC2"
```

---

### Task 2: 非 burstable RDS 的信用否决项按实例类分支

**Files:**
- Modify: `aws-rightsizing/references/core.py`（`eval_rds()`，当前在 `:316`）
- Modify: `aws-rightsizing/SKILL.md`（验证状态表的 RDS 行）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: `eval_rds(res, t)`、`res["type"]`
- Produces: 无新字段。`eval_rds` 对 `db.t*` 之外的实例类不再要求 `surplus_credits`。

**背景（实测）：** `eval_rds` 无条件卡 `surplus_credits is None`，而 `db.m5.*` / `db.r6g.*` 等非 burstable 实例类**结构性不发布** `CPUCreditBalance` / `CPUSurplusCreditsCharged`（实测同批 `db.t4g.medium` 三条序列都有数据，`db.m5.large` 全空）。而全局规则禁止兜底为 0 且没给例外 ⇒ **任何非 burstable RDS 恒为 `metric-missing`，降配路径不可达**。EC2 侧用 `spec["burst"]` 做了这个区分，RDS 侧漏了。

- [ ] **Step 1: 写失败测试**

```python
def test_nonburstable_rds_does_not_require_credit_metrics():
    """非 burstable RDS 结构性不发布信用指标，不得因此恒为 metric-missing。

    实测：db.m5.large 的 CPUCreditBalance / CPUSurplusCreditsCharged 三条序列
    全空，而同批 db.t4g.medium 都有数据。若无条件要求该指标，
    任何非 burstable RDS 的降配路径都不可达。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    res = dict(rid="db-NB", service="rds", type="db.m5.large", vcpu=2,
               mem_gib=8, sample_n=floor, surplus_credits=None,
               dbload_p95=0.05, freeable_mem_min_gib=5.98)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"非 burstable RDS 因缺信用指标被判 {got['verdict']}，"
        f"降配路径不可达 —— {got}")


def test_burstable_rds_still_requires_credit_metrics():
    """burstable RDS 仍必须 fail-closed —— 这条否决项对 db.t* 是真实的。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    res = dict(rid="db-B", service="rds", type="db.t4g.medium", vcpu=2,
               mem_gib=4, sample_n=floor, surplus_credits=None,
               dbload_p95=0.05, freeable_mem_min_gib=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "metric-missing", (
        f"burstable RDS 缺信用指标却放行了 —— {got}")


def test_burstable_rds_credit_overage_still_vetoes():
    """信用超额否决项不得被本次改动削弱。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    res = dict(rid="db-B2", service="rds", type="db.t4g.medium", vcpu=2,
               mem_gib=4, sample_n=floor, surplus_credits=3.11,
               dbload_p95=0.05, freeable_mem_min_gib=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "upsize-candidate", (
        f"CPUSurplusCreditsCharged=3.11 > 0 应判升配候选 —— {got}")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
```
Expected: FAIL，`非 burstable RDS 因缺信用指标被判 metric-missing，降配路径不可达`

- [ ] **Step 3: 加实例类分支**

在 `core.py` 的 `eval_rds` 之前加一个判定函数：

```python
def _rds_is_burstable(itype):
    """RDS 实例类是否 burstable。只有 db.t* 系列发布信用指标。

    非 burstable（db.m*/db.r*/db.x* 等）结构性不发布 CPUCreditBalance 与
    CPUSurplusCreditsCharged —— 实测 db.m5.large 三条序列全空，同批
    db.t4g.medium 都有数据。对它们要求信用指标会让降配路径永久不可达，
    这是「不适用」而不是「缺失」，所以不走 fail-closed。
    EC2 侧用 spec["burst"] 做同一个区分，RDS 侧此前漏了。
    """
    return itype.split(".")[1].startswith("t") if "." in itype else False
```

把 `eval_rds` 里的信用否决项块改成：

```python
    # 否决项优先，且缺失一律 fail-closed —— 但只对 burstable 实例类成立
    burstable = _rds_is_burstable(res["type"])
    sc = res.get("surplus_credits")
    if burstable and sc is None:
        out.update(verdict="metric-missing",
                   blockers=["CPUSurplusCreditsCharged 缺失，无法排除信用已超额"])
        return out
    if sc is not None and sc > 0:
        out.update(verdict="upsize-candidate",
                   blockers=[f"CPUSurplusCreditsCharged={sc} > 0，规格已不足，是升配候选"])
        return out
```

注意 `sc is not None and sc > 0`：非 burstable 时 `sc` 是 `None`，不能直接比较。

- [ ] **Step 4: 跑测试确认通过 + 全门禁**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 三条新测试 PASS，8 个文件全绿

- [ ] **Step 5: 变异验证**

三次变异，每次单独跑并粘输出：把 `burstable and sc is None` 改回 `sc is None`（第一条测试须失败）；把 `_rds_is_burstable` 改成恒 `False`（第二条须失败）；把 `sc is not None and sc > 0` 改成 `False`（第三条须失败）。逐次还原。

- [ ] **Step 6: 复核 SKILL.md 的验证状态表**

`SKILL.md` 的验证状态表声称 RDS「走通了降配路径与阻断路径各一条」。照改动前的代码，非 burstable 的降配路径不可达，所以那条记录要么是用 `db.t4g.*` 走通的、要么当时的输入兜底过 0。找到该行，改成明确写出**哪个实例类**走通了哪条路径，并注明非 burstable 的降配路径在本次修复前不可达。不要泛泛写「已修复」——写清原记录的范围。

- [ ] **Step 7: 提交**

```bash
git add aws-rightsizing/references/core.py aws-rightsizing/SKILL.md aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "fix: RDS credit veto applies only to burstable instance classes"
```

---

### Task 3: 候选集为空时输出「已合理配置」而非降配候选

**Files:**
- Modify: `aws-rightsizing/references/core.py`（`eval_elasticache()` 当前在 `:370`、`eval_msk()` 当前在 `:428`）
- Modify: `aws-rightsizing/references/sample-solve.md`（托管服务输入契约字段表）
- Test: `aws-rightsizing/tests/test_managed_dispatch.py`

**Interfaces:**
- Consumes: `eval_elasticache(res, t)`、`eval_msk(res, t)`
- Produces: 托管输入契约新增必填字段 `cheaper_candidate_exists`（布尔或 `None`），语义=同形态（同引擎 / 同架构）下是否存在更便宜的机型。

**背景（实测）：** `kafka.t3.small` 是两个 region 都最便宜的 broker 机型（次便宜的 `kafka.m7g.large` 贵约 4.5 倍）⇒ **MSK 降配路径在任何账号都到不了**。而报告会让客户把 `EnhancedMonitoring` 提到 `PER_BROKER` 再等一个窗口——做完也不会有建议，白等 30 天。ElastiCache 侧同形：一个已是 `cache.t4g.micro`（该族最小）的节点仍被判 `downsize-candidate`。`SKILL.md` 护栏里「候选集为空 ⇒ 输出『已合理配置』」这条现在只对 EC2 生效。

- [ ] **Step 1: 写失败测试**

```python
def test_no_cheaper_candidate_yields_already_right_sized():
    """已是最小/最便宜规格时必须直接判已合理配置，不得要求前置指标。

    实测：kafka.t3.small 是两个 region 最便宜的 broker 机型（次便宜的贵
    约 4.5 倍）⇒ MSK 降配路径在任何账号都到不了。报告却让客户提升
    EnhancedMonitoring 再等一个窗口，做完也不会有建议。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    msk = dict(rid="mk-MIN", service="msk", type="kafka.t3.small",
               sample_n=floor, cheaper_candidate_exists=False,
               under_replicated_max=None, disk_used_max=None,
               handler_idle_p95=None, cpu_total_p95=None)
    got = core.dispatch(msk, {"thresholds": t})
    assert got["verdict"] == "已合理配置", (
        f"最小规格仍判 {got['verdict']}，会让客户为不可能的建议白等一个窗口 —— {got}")
    assert any("最小" in b or "更便宜" in b for b in got.get("blockers") or []), (
        f"blockers 未说明原因是没有更便宜候选 —— {got}")

    cc = dict(rid="cc-MIN", service="elasticache", type="cache.t4g.micro",
              vcpu=2, mem_gib=0.5, sample_n=floor,
              cheaper_candidate_exists=False, evictions_sum=None,
              repl_lag_max=None, engine_cpu_p95=None, db_mem_used_pct_max=None)
    got = core.dispatch(cc, {"thresholds": t})
    assert got["verdict"] == "已合理配置", (
        f"已是该族最小 node type 仍判 {got['verdict']} —— {got}")


def test_missing_cheaper_candidate_flag_is_fail_closed():
    """cheaper_candidate_exists 缺失不得当成「有更便宜候选」继续判。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    res = dict(rid="mk-Z", service="msk", type="kafka.m7g.large",
               sample_n=floor, under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "metric-missing", (
        f"cheaper_candidate_exists 缺失却继续判到了 {got['verdict']} —— {got}")


def test_cheaper_candidate_true_still_reaches_downsize():
    """有更便宜候选时原路径不得被削弱。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    res = dict(rid="mk-OK", service="msk", type="kafka.m7g.large",
               sample_n=floor, cheaper_candidate_exists=True,
               under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"有更便宜候选却没走到 downsize-candidate —— {got}")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
```
Expected: FAIL，`最小规格仍判 metric-missing，会让客户为不可能的建议白等一个窗口`

- [ ] **Step 3: 在两个 evaluator 开头插判据**

在 `eval_elasticache` 的 `out = {...}` 之后、`mem_gib` 检查之前，以及 `eval_msk` 的 `out = {...}` 之后、`under_replicated_max` 检查之前，各插入同一段（两处都要写全，不要提取成函数——两个 evaluator 的 `out` 初始值不同，且这段要读起来就在各自的判据链最前面）：

```python
    # 候选集为空 ⇒ 直接已合理配置，且早于所有前置指标要求。
    # 否则会让客户为一条不可能产出的建议去补指标、再等一个窗口。
    # 实测：kafka.t3.small 是两 region 最便宜的 broker 机型，次便宜的贵约 4.5 倍。
    cheaper = res.get("cheaper_candidate_exists")
    if cheaper is None:
        out.update(verdict="metric-missing",
                   blockers=["cheaper_candidate_exists 缺失，无法确认是否存在"
                             "更便宜的同形态候选（不得假定存在）"])
        return out
    if not cheaper:
        out.update(verdict="已合理配置",
                   blockers=["同形态下没有更便宜的候选机型，已是最小规格；"
                             "补充指标或延长窗口都不会改变结论"])
        return out
```

- [ ] **Step 4: 跑测试确认通过 + 全门禁**

```bash
cd aws-rightsizing && python3 tests/test_managed_dispatch.py
for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 三条新测试 PASS，8 个文件全绿

- [ ] **Step 5: 变异验证**

把 `if not cheaper:` 改成 `if False:`（第一条须失败）；把 `res.get("cheaper_candidate_exists")` 改成 `res.get("cheaper_candidate_exists", True)`（第二条须失败）。逐次还原，粘输出。

- [ ] **Step 6: 更新托管输入契约**

在 `references/sample-solve.md` 托管服务字段表加一行：

```markdown
| `cheaper_candidate_exists` | **必填。** 同形态下是否存在更便宜的机型。ElastiCache 同引擎（不得跨 CPU 架构）、MSK 同 broker 机型族系。由采集侧按取回的价目表判定 | 缺失 ⇒ `metric-missing`（不得假定存在） |
```

并在表下加一句：这个判定放采集侧是因为托管服务的价目阶梯与规格映射本来就在采集侧（见 `cli-recipes.md` 的非 EC2 取价属性表），`core.py` 只消费结论。

- [ ] **Step 7: 提交**

```bash
git add aws-rightsizing/references/core.py aws-rightsizing/references/sample-solve.md aws-rightsizing/tests/test_managed_dispatch.py
git commit -m "fix: empty candidate set yields already-right-sized, not a dead recommendation"
```

---

### Task 4: `insufficient-data` 行补齐成本字段

**Files:**
- Modify: `aws-rightsizing/references/core.py`（`evaluate()` 的采样守卫分支，当前在 `:130-139`）
- Test: `aws-rightsizing/tests/test_regression_fleet.py`

**Interfaces:**
- Consumes: `evaluate(res, ctx)`、`ctx["_specs_by_type"]`、`ctx["prices"]`
- Produces: `insufficient-data` 行新增 `cur_vcpu` / `cur_gib` / `cur_usd` / `cur_cat` / `cur_cost_mo`（查得到时），`verdict` 不变。

**背景（实测）：** `evaluate()` 的顺序是采样守卫 → 规格查表 → 价格查表 → 写 `cur_cost_mo`，所以 `insufficient-data` 分支**在成本字段赋值之前就 return** 了。后果：摘要分母漏掉这些行，实测漏掉两台合计 $286.67/mo，比例从 23.2% 虚高到 27.7%。单价查表不依赖任何指标，是事实不是判断。

**注意：** 不要把整段价格查表提到守卫之前——那会让 `spec-unknown` / `price-unknown` 抢在 `insufficient-data` 前面，改变 verdict 优先级并动到回归断言。只在守卫分支内部做 best-effort 查表。

- [ ] **Step 1: 写失败测试**

在 `tests/test_regression_fleet.py` 加：

```python
def test_insufficient_data_rows_still_carry_cost():
    """采样不足的行必须带成本，否则摘要分母漏项、节省比例虚高。

    实测：漏掉两台合计 $286.67/mo，比例从 23.2% 虚高到 27.7%。
    单价查表不依赖任何指标，是事实不是判断。
    """
    rows = _run("aggressive")
    ins = [f for f in rows if f["verdict"] == "insufficient-data"]
    assert ins, "fixture 里应有 insufficient-data 行，是它锚定这条断言"
    for f in ins:
        assert f.get("cur_cost_mo") is not None, (
            f"{f['rid']} 是 insufficient-data 但没有 cur_cost_mo，"
            f"摘要分母会漏掉它 —— {f}")
        assert f.get("cur_usd") is not None, f
        assert f.get("nb_save_mo") is None and f.get("b_save_mo") is None, (
            f"{f['rid']} 采样不足却带了节省额 —— {f}")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd aws-rightsizing && python3 tests/test_regression_fleet.py
```
Expected: FAIL，`... 是 insufficient-data 但没有 cur_cost_mo，摘要分母会漏掉它`

- [ ] **Step 3: 在守卫分支内 best-effort 填成本**

把 `evaluate()` 的采样守卫分支改成：

```python
    n = res.get("cpu_n")
    floor_pts = t["min_biz_hours_points"]
    if n is None or n < floor_pts:
        out["verdict"] = "insufficient-data"
        out["burst_na"] = f"biz-hours 仅 {n} 点 < {floor_pts}，p95 无统计意义"
        # 成本是事实、不是判断：单价查表不依赖任何指标。不填会让摘要分母
        # 漏掉这些行、节省比例虚高（实测漏 $286.67/mo，23.2% 虚高成 27.7%）。
        # 只在本分支内 best-effort 查，不把查表整段提到守卫之前 ——
        # 那会让 spec-unknown / price-unknown 抢在 insufficient-data 之前，
        # 改变 verdict 链的优先级。
        cs = specs_by_type.get(itype)
        usd = prices.get(f"{itype}|{res.get('operation')}")
        if cs is not None:
            out.update(cur_vcpu=cs["vcpu"], cur_gib=cs["gib"])
        if usd is not None:
            out.update(cur_usd=usd, cur_cat=cats.get(itype),
                       cur_cost_mo=round(usd * HOURS_PER_MONTH
                                         * res.get("count", 1), 2))
        return out
```

- [ ] **Step 4: 跑测试确认通过 + 全门禁**

```bash
cd aws-rightsizing && python3 tests/test_regression_fleet.py
for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 新测试 PASS，8 个文件全绿。`route1_nb` / `route2_max` **不得变化**（只加了成本列，没加节省额）——若 `EXPECTED` 的四个金额有任何变动，说明改动越界了，停下来查明。

- [ ] **Step 5: 变异验证**

把 `if usd is not None:` 那一块整段删掉，确认新测试以自己的消息失败；再把 `out.update(cur_usd=usd, ...)` 里加一句 `out["nb_save_mo"] = 1.0`，确认最后那条断言失败。粘输出，还原。

- [ ] **Step 6: 提交**

```bash
git add aws-rightsizing/references/core.py aws-rightsizing/tests/test_regression_fleet.py
git commit -m "fix: insufficient-data rows carry cost so the denominator is complete"
```

---

### Task 5: 内存降幅上限（会移动回归基线）

**Files:**
- Modify: `aws-rightsizing/references/thresholds.json`（两个 profile 各加一个键）
- Modify: `aws-rightsizing/references/core.py`（`passes_common()` 的降幅地板，当前在 `:212-214`）
- Modify: `aws-rightsizing/references/thresholds.md`（键说明与不对称说明）
- Test: `aws-rightsizing/tests/test_regression_fleet.py`、`aws-rightsizing/tests/test_thresholds.py`

**Interfaces:**
- Consumes: `passes_common(sp)`、`t["max_reduction_ratio"]`
- Produces: 新阈值键 `max_mem_reduction_ratio`（aggressive `3`、conservative `2`）

**背景（实测）：** `core.py:213` 只对 vCPU 设降幅地板，内存无任何比例约束。实测一台 4 GiB 的 T 系列实例内存 p95 5.175% ⇒ 建议降到 1 GiB（**4 倍**）、`confidence=high`、两个 profile 都一样，而 conservative 的 vCPU 最多才降 2 倍。取值与 vCPU 相同的理由见 spec R2：现有 vCPU 地板的依据「目标利用率管不了窗口外的周期与发布间隔内的尖峰」与指标种类无关；且 `mem_used_percent` 不含可回收 page cache，会把内存 p95 系统性压低。

**⚠️ 本任务会改变回归基线。** 加了内存地板会滤掉部分候选 ⇒ 总额下降。必须重算并把新值写进 `EXPECTED`，同时在测试文件里写明旧值、新值与成因。**永不为了让断言通过而反推数字。**

- [ ] **Step 1: 加阈值键**

`references/thresholds.json` 两个 profile 各加一行，紧跟在 `max_reduction_ratio` 之后：

```json
      "max_mem_reduction_ratio": 3,
```
（conservative 用 `2`）

- [ ] **Step 2: 跑 `test_thresholds.py` 确认键覆盖断言仍通过**

```bash
cd aws-rightsizing && python3 tests/test_thresholds.py
```
Expected: PASS（该文件断言两个 profile 的键集合一致；若它还断言键的**总数**，同步改那个数字并在注释里写明为什么变）

- [ ] **Step 3: 写失败测试**

在 `tests/test_regression_fleet.py` 加：

```python
def test_mem_reduction_floor_is_live_and_respected():
    """内存降幅也必须受上限约束。

    实测缺陷：一台 4 GiB 实例内存 p95 5.175% 被建议降到 1 GiB（4 倍），
    confidence=high，两个 profile 都一样 —— 而 conservative 的 vCPU
    最多才降 2 倍。这个不对称此前没有任何地方写出来。
    mem_used_percent 是 mem_used/mem_total、不含可回收 page cache，
    会把内存 p95 系统性压低，所以内存比 vCPU 更需要这道地板。
    """
    th = json.loads((ROOT / "references" / "thresholds.json").read_text())
    for profile in EXPECTED:
        limit = th["profiles"][profile]["max_mem_reduction_ratio"]
        for f in _run(profile):
            for key in ("nonburst", "burst"):
                pick = f.get(key)
                if not pick or not f.get("cur_gib"):
                    continue
                ratio = f["cur_gib"] / pick["gib"]
                assert ratio <= limit, (
                    f"{profile} {f['rid']} 的 {key} 内存降幅 {ratio:.2f}x "
                    f"超过上限 {limit}x —— {f['cur_gib']} GiB → {pick['gib']} GiB")
```

- [ ] **Step 4: 跑测试确认失败**

```bash
cd aws-rightsizing && python3 tests/test_regression_fleet.py
```
Expected: FAIL —— 若这支机队本来就没有超限的行，该测试会**假通过**。此时必须先构造一个会超限的输入验证断言真的会响（临时把 `max_mem_reduction_ratio` 改成 `1` 重跑，确认失败），再改回。上一轮有一条同形状的断言因为「这支机队从没顶到上限」而假通过，别重复。

- [ ] **Step 5: 加内存地板**

把 `passes_common` 的降幅地板改成：

```python
        # 降幅上限：目标利用率管不了「窗口外的周期」与「发布间隔内的尖峰」。
        # 这个理由与指标种类无关，所以内存同样要设地板 —— 而且
        # mem_used_percent 不含可回收 page cache，会把内存 p95 压低，
        # 内存比 vCPU 更需要它。实测缺陷：4 GiB 被建议降到 1 GiB（4x），
        # 同一 profile 下 vCPU 最多才降 2x。
        if sp["vcpu"] < _ceil_div(cs["vcpu"], t["max_reduction_ratio"]):
            return False
        if sp["gib"] < _ceil_div(cs["gib"], t["max_mem_reduction_ratio"]):
            return False
```

- [ ] **Step 6: 重算基线并记录**

```bash
cd aws-rightsizing && python3 - <<'PY'
import json, subprocess, pathlib, collections
FX = pathlib.Path("tests/fixtures/regression-fleet.json")
base = json.loads(FX.read_text())
for prof in ("aggressive", "conservative"):
    p = subprocess.run(["python3", "references/core.py"],
                       input=json.dumps(dict(base, sizing_profile=prof)),
                       capture_output=True, text=True)
    d = json.loads(p.stdout)
    print(prof,
          "route1_nb=", round(sum(f.get("nb_save_mo") or 0 for f in d), 2),
          "route2_max=", round(sum(max(f.get("nb_save_mo") or 0,
                                       f.get("b_save_mo") or 0) for f in d), 2),
          dict(collections.Counter(f["verdict"] for f in d)))
PY
```

把实际输出的四个数字写进 `EXPECTED`，并在该字典上方加注释块：旧值 `401.51 / 551.97 / 312.48 / 413.22`、新值、以及成因「Task 5 加了 `max_mem_reduction_ratio` 内存降幅地板，滤掉了内存降幅超限的候选」。**旧值保留标注、不删**——删了以后有人会重新推导出来。

- [ ] **Step 7: 跑全门禁**

```bash
cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 8 个文件全绿

- [ ] **Step 8: 写不对称说明**

在 `references/thresholds.md` 里 `max_reduction_ratio` 那一段之后补 `max_mem_reduction_ratio` 的说明：两者取同值、理由同源（目标利用率管不了窗口外周期与发布间隔内尖峰，与指标种类无关）、以及为什么内存更需要它（`mem_used_percent` 不含可回收 page cache，系统性压低内存 p95）。**不要在散文里复述阈值数字**——lint 的守卫清单由 `thresholds.json` 生成，写了数字会被拦。写键名。

- [ ] **Step 9: 提交**

```bash
git add aws-rightsizing/references/thresholds.json aws-rightsizing/references/core.py aws-rightsizing/references/thresholds.md aws-rightsizing/tests/test_regression_fleet.py aws-rightsizing/tests/test_thresholds.py
git commit -m "fix: bound memory reduction the same way vCPU is bounded"
```

---

### Task 6: 报告口径与契约补全

**Files:**
- Modify: `aws-rightsizing/references/report-template.md`
- Modify: `aws-rightsizing/SKILL.md`（结论合并规则、资源级互斥）
- Test: `aws-rightsizing/tests/test_csv_contract.py`

**Interfaces:**
- Consumes: `core.py` 实际产出的键（用 `python3 references/core.py` 跑一次取，不要凭读代码猜）
- Produces: 无代码接口。产出的是 `report-template.md` 的契约，后续无任务依赖。

**背景：** 本任务解决 spec 的 C1–C10。两个 agent 在每一处都各自发明了不同做法，导致同一机队两次运行的 `findings.csv` 形状不同、百分比不可比。

- [ ] **Step 1: 汇总口径加第三条（C1，裁定 R5）**

在「汇总口径」小节把两条路线扩成三条，并写明互斥关系：

```markdown
路线一 = Σ nb_save_mo                          （降配，一律取 non-burstable）
路线二 = Σ max(nb_save_mo, b_save_mo)          （降配，逐条取更省者）
桶 B 合计 = Σ cur_cost_mo over bucket == "idle" （闲置资源移除后的全额）

- 路线一与路线二**互斥**，不得相加。
- 桶 A 与桶 B **互斥**（同一资源只进一个桶），故桶 B 合计**可以**与路线一或路线二相加。
- 命中 `idle` 的行，其 `nb_save_mo` 是「若须保持运行改为降配」的**替代方案**，
  **不进桶 B 合计**，也不进路线一/二 —— 否则同一资源被算两遍。
```

补一句实测依据：某闲置实例删除可省 $1,369.48、降配可省 $98.55，**差 13.9 倍**；只对 `nb_save_mo` 求和会让该 region 桶 B 的 93% 不出现在报告里。

- [ ] **Step 2: 新增「分母的范围」小节（C2，裁定 R7）**

```markdown
## 分母的范围

`分母 = Σ cur_cost_mo`（findings.csv 全表求和），且**范围内每个资源恰好贡献一行**。

- 无建议的资源照样出行：`verdict=已合理配置` 或 `bucket=excluded`，`cur_cost_mo` 照填。
- 已停止的 EC2 实例 `cur_cost_mo=0`（计算不计费），其成本落在所属卷那一行。
- 必须计入：EC2running（含 EKS 节点）、EBS 卷、快照、NAT 小时费、ALB 小时费、
  RDS 实例、ElastiCache 节点、MSK broker、EKS 控制面。
- 必须在报告里**显式声明为未包含**：数据传输、NAT 数据处理费、ALB LCU、
  RDS/MSK 存储与备份、CloudWatch、未关联的公有 IPv4（`price-unknown`）。

**任何进入作用域的运行时输入都必须出现在路径或文件名里。**
```

补实测依据：漏掉 `insufficient-data` 行会让比例从 23.2% 虚高到 27.7%。

- [ ] **Step 3: 聚合行规则（C6）**

在 `SKILL.md` 的「结论合并规则」加第四条：

```markdown
4. **聚合行只带节省额，不带成本；成本一律记在成员行上。**
   一条建议若作用于一组资源（EKS 节点池、MSK broker 组、ElastiCache 复制组），
   聚合行的 `cur_cost_mo` 必须留空，否则分母把成员算两遍。
   反例对照：MSK 是**单行带 `instance_count=brokers`**（成本 = 单价 × broker 数 × 730，
   一行），与 EKS 的「多成员行 + 一聚合行」不是同一种形状。两种都合法，
   按「这条建议能否对单个成员单独执行」选：能则多成员行，不能则聚合行。
```

- [ ] **Step 4: 资源级互斥补 `state=available`（C10）**

在 `SKILL.md` 的「资源级互斥」里把通则提到最前面、枚举作为例子：

```markdown
**通则：两个动作若不能同时执行，就不能同时计入合计。**

- **任何走删除路径的卷都不出 `storage-type` 行。** 两种情形都算：
  `state=available`（未挂载）、宿主实例 `state=stopped`。
```

补实测依据：一个未挂载的 gp2 卷会同时出删除行 $3.60/mo 与 `gp2→gp3` 行 $0.72/mo，两个动作互斥却都进了合计。

- [ ] **Step 5: `stop_candidate` 的第四种情形（C3，裁定 R4）**

在枚举小节把四种情形并列写出：

```markdown
`stop_candidate`（桶 C）：
- `true`  —— 是候选
- `false` —— 判过了，不是候选
- `null`  —— **判不了**（缺分档输入或采样量不足）
- **留空** —— `allow_stop_recommendations=no`，本次未评估

`null` 与留空是两件事，不得混用：`null` 是「查了但判不了」，
留空是「按输入要求没查」。填 `false` 会让报告看起来像「已经查过、没有可停的」。
`allow_stop_recommendations=no` 时该列**保留在 CSV 里但留空**，
并在报告正文写一句「桶 C 未评估（`allow_stop_recommendations=no`）」。
该列不得从 CSV 删除 —— 列数变化会破坏下游校验。
```

- [ ] **Step 6: 托管服务节省额小计（C4）**

在报告分节里新增一节并写明它不进头条：

```markdown
## 托管服务候选小计（不计入头条数字）

三条托管判据不产出 `nb_save_mo`（node type 的价格与规格映射在采集侧，
候选由人工在变更方案里定）。因此它们的节省额**结构性不在路线一/二里**。
报告必须单列本节，给出每个候选的目标 node type 与月省，并明写
「本节金额不计入第 1 节合计」。

实测规模：某 region 6 个 ElastiCache 节点降一档合计 $148.92/mo，
占该 region 路线一的 9–13% —— 不单列就等于丢掉。
```

- [ ] **Step 7: 多 profile 命名（C5）**

在产出物布局小节写死方案一：

```markdown
交付物文件名带 profile，`raw/` 共用：

report_output/<account>-<region>-<YYYYMMDD>/
  aws-rightsizing-report-<profile>.md
  findings-<profile>.csv
  raw/            ← 采集与 profile 无关，故共用，不重复落盘

`sizing_profile` 与 `target_account` / `regions` 一样是运行时输入，
且两个预设在同一机队上的条数与总额都不同 —— 文件名不带 profile
会让第二次运行静默覆盖第一次，而 `raw/` 是共用的，**覆盖之后看不出发生过覆盖**。
```

- [ ] **Step 8: `nonburst` / `burst` 的渲染规则（C8）**

在字段契约表加一行说明：`nonburst` 与 `burst` 在 `core.py` 的输出里是**机型规格对象**（含 `t` / `vcpu` / `gib` / `usd` 等），CSV 单列取 `.t`。同行的 `nb_cat` / `nb_save_mo` / `nb_delta_*` 都是顶层键，唯独机型字符串在嵌套对象里。

- [ ] **Step 9: `window_profile` 加 `full-window`（C9）**

枚举加 `full-window`，并说明：NAT / ALB 的闲置判据取全窗口（三档合并）的 max，结论填 `full-window`；纯配置类判断（`gp2→gp3`、未挂载卷、快照）该列留空。

- [ ] **Step 10: 采集侧自建行的字段填法表（C7）**

新增一张表，按资源类型给出 `service` / `cur` / `verdict` / `bucket` / `action_type` / `confidence` / `window_profile` 的取值。至少覆盖：EBS 卷（`gp2→gp3` / 未挂载 / 挂 stopped 实例 / 其他）、快照、NAT、ALB、EIP、EKS 节点池、EKS 控制面、已停止的 EC2 实例。

每一格都要给具体值，不要写「视情况」。这张表的存在理由和 `sample-solve.md` 一样：本 skill 反复验证出「有代码/样例载体的判据一次就对；只有散文描述的判据全部出过问题」，而采集侧自建行目前连散文都没有。

- [ ] **Step 11: 更新契约测试并验证双向性**

先跑一次拿到 `core.py` 的真实输出键：

```bash
cd aws-rightsizing && python3 references/core.py < tests/fixtures/regression-fleet.json 2>/dev/null | head -c 400
```
（该 fixture 不含 `sizing_profile`，会抛 `KeyError` —— 用 `tests/test_regression_fleet.py` 里 `_run()` 的方式注入 profile 再取。）

确认 `test_csv_contract.py` 的双向断言仍成立：契约里每一列都被断言、每个被断言的列都在契约里。若 Step 5 的留空规则或 Step 9 的新枚举值需要断言，补上。

```bash
cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 8 个文件全绿

- [ ] **Step 12: 提交**

```bash
git add aws-rightsizing/references/report-template.md aws-rightsizing/SKILL.md aws-rightsizing/tests/test_csv_contract.py
git commit -m "docs: define the totals, the denominator, and the collection-side row contract"
```

---

### Task 7: 采集配方的硬失败与取价消歧

**Files:**
- Modify: `aws-rightsizing/references/cli-recipes.md`（§1.1、§2.0 ④、§2.2、§2.6、§5.1、§7.3）
- Modify: `aws-rightsizing/references/mdq-dims.jq`（文件头参数表）

**Interfaces:**
- Consumes: 无
- Produces: 无代码接口。

**背景：** P1 与 P2 是**照文档逐字执行必然失败**的两处。P3–P7 是取价与闲置判据的静默失真。

- [ ] **Step 1: 修 `$idprefix`（P1）**

`references/mdq-dims.jq` 的参数表把 `--arg idprefix <字符串>  Id 前缀，合并多批时必须各不相同（默认 "d"）` 里的「（默认 "d"）」改成「**必传**」。实现里没有任何默认值——jq 引用未定义的 `$var` 是**编译期错误**，不会退化成 null。把这句和文件头已有的 `$stats` 那段合并成一句：本文件的 `$mn` / `$idname` / `$ty` / `$stats` / `$idprefix` **全部必传**。

`cli-recipes.md §2.2` 的内存与磁盘两处模板各补 `--arg idprefix`（内存用 `m`、磁盘用 `d`），并在该节留一行说明：两批必须用不同前缀，否则合并后 `Id` 撞名会让 `get-metric-data` 直接报 `ValidationError`——这是本 skill 唯一会硬失败的错。

- [ ] **Step 2: 验证模板真的能跑**

按改后的 §2.2 模板，用一个最小的 `list-metrics` 回包样本实跑一次 jq，确认无编译错误。把命令与输出粘进报告。**不要写没跑过的命令**——本轮每一条悬空引用类缺陷都是这么来的。

- [ ] **Step 3: 修 §7.3 ① 与 §1.1（P2）**

§7.3 ① 的断言 `[ "$(jq length $O/solver-in.json)" = "$(jq length $IV/ec2.json)" ]` 改成对 `ec2-standalone.json` 比对。§1.1 标题「三个派生清单」改成「四个」，并加上 `ec2-standalone.json` 的生成式：

```bash
EKS=$(jq -c '[.[]|select(.ng!=null or .np!=null)|.id]' $IV/ec2-eks-owned.json)
jq -c --argjson e "$EKS" '[.[]|select(.id as $i|($e|index($i))|not)]' $IV/ec2.json > $IV/ec2-standalone.json
jq -c --argjson e "$EKS" '[.[]|select(.id as $i|($e|index($i)))]'      $IV/ec2.json > $IV/ec2-eksnodes.json
```

补一句为什么：§4 要求 EKS 节点与独立 EC2 分开处理（否则会对节点单机出降配建议，而节点机型由 nodegroup 的 `instanceTypes` 决定），所以 solver 输入必然少于 `ec2.json`——原断言与 §4 直接冲突，照文档跑必然 FAIL。

- [ ] **Step 4: 修 ALB 取价（P3）**

§5.1 的 ALB 取价改成**不按 usagetype 过滤**，只按 `operation=LoadBalancing:Application` 拉回，再在 jq 里筛。给出可直接抄的 jq：

```bash
jq '[.PriceList[]|fromjson
     | select((.product.attributes.usagetype // "")|test("LoadBalancerUsage$"))
     | select((.product.attributes.usagetype // "")|test("Outposts|-TS-")|not)
     | {ut:.product.attributes.usagetype,
        usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
             |to_entries[0].value.pricePerUnit.USD|tonumber)}]' alb-price-raw.json
```

在「非 EC2 服务的取价属性」表的 ELB 行补排除项 `Outposts` / `-TS-`，并注明 `-TS-` 实测只有正确价的 **22%–28%**（us-west-2 0.0063/0.0225、ap-northeast-1 0.0054/0.0243），若用 `unique_by` 或 `.[0]` 随机取到它，ALB 成本**低估 3.6–4.5 倍**。〔**2026-09-04 改正**：本行原写「约 26% / 约 3.6 倍」，那是单 region 单次测量；两 region 复测后的区间是上面这个。按本文件开头那条准则——可执行的验收标准就地改正，不留作废数字。〕这与该表已记录的 ElastiCache `ExtendedSupport` 陷阱是同一形状，只是 ALB 侧的排除项此前没写全。

- [ ] **Step 5: NAT 前缀不可反推（P4）**

「易错项速查」加一行：**前缀不能由 region 码机械推出，所以不得用 `usagetype` 反推 region 价目前缀。** 〔**2026-09-04 改正**：本行原来的机制写的是「形态逐 region 不同（`APN1-` vs `USW2-Regional`）」，那个说法**已被推翻**——复测发现前缀本身就不可由 region 码推导（`eu-west-1` → `EU-` 而不是 `EUW1-`、`ca-central-1` → `CAN1-`），且**同一个 region 内**就同时存在裸 `NatGateway-Hours` 与 `USE1-RegionalNatGateway-Bytes`（us-east-1 实测）。照原文写进「易错项速查」会把一个错的机制装进交付文件，所以就地改正；已发货的正确版本见 `SKILL.md` 该行。〕 拼出不存在的串时 pricing API **返回空且不报错**，是 §2.0 ④ 那类静默失效发生在取价侧。需要前缀时从形态稳定的 usagetype 取，或按 Step 4 的做法干脆不依赖前缀。同时把 §5.1 里那个来源未定义的 `${P}` 一并消除。

- [ ] **Step 6: ElastiCache 加 `cacheEngine` 消歧（P5，裁定 R1）**

**先读 spec 的 R1。** 已实测确认：`ExtendedSupportYr1_Yr2` 确实是 $0.0540 且 `vcpu`/`memory` 为 `null`，现有 `^[A-Z0-9]+-NodeUsage:` 过滤式已经挡住它——**该记录准确，不得删改**。要新增的是另一个独立陷阱：Valkey 与 Redis / Memcached **共用同一个 usagetype**，三行都能过现有过滤、`vcpu`/`memory` 都有值。

把键改成 `(instanceType, operation)`，与 EC2 侧的 `(机型, UsageOperation)` 同构；`operation` 字段本来就在回包里。取价时按集群的 `Engine`（`describe-cache-clusters` 的 `.engine`）选 `operation`。给出可直接抄的 jq，并给一条校验式：**同机型多价的型号数必须为 0**。

实测数字（`us-west-2` / `cache.t3.medium`）写进表里：

```
$0.0680  Redis      CreateCacheCluster:0002    vcpu=2  3.09 GiB
$0.0680  Memcached  CreateCacheCluster:0001    vcpu=2  3.09 GiB
$0.0544  Valkey     CreateCacheCluster:Valkey  vcpu=2  3.09 GiB   ← unique_by(.t) 随机取到它 ⇒ 对 Redis 低估 20%
```

- [ ] **Step 7: ALB 闲置判据三态（P6）**

§2.6 的「`RequestCount` 全窗口为 0 的 ALB/NLB → 桶 B」改成三态，并把 `ActiveConnectionCount` 写进必取指标与证据列：

```markdown
| `RequestCount` | `ActiveConnectionCount` | 判定 |
|---|---|---|
| 序列存在，全窗口全 0 | 序列不存在 | 桶 B（闲置，证据最强） |
| 序列存在，全窗口全 0 | 存在且 max > 0 | **候选，需人工确认**，不计入确定节省 |
| **序列不存在** | 存在且 max > 0 | **候选，需人工确认** —— 零 HTTP 请求 ≠ 零连接 |
```

补实测依据：一个 ALB 的 `RequestCount` 序列不存在（`list-metrics` 回 0）看起来像闲置，但 `ActiveConnectionCount` max 非零 ⇒ 实际活跃（大概是健康检查或目标端连接）。只看 `RequestCount` 会把在用的 ALB 判成可删除。

- [ ] **Step 8: `list-metrics` 的时间窗差异（P7）**

在 §2.0 ④ 补一条：`list-metrics` 只回**最近 2 周**有数据的指标，而 `get-metric-data` 覆盖整个窗口。实测某 ALB `list-metrics --metric-name RequestCount` 回 **0**，而 `get-metric-data` 有 **250** 个非零点（单小时 max 1646，点的时间跨度 2026-08-05 .. 2026-08-15，最新点距查询日 20 天，正好落在 2 周窗口外）。〔**2026-09-04 改正**：原写「500 个非零点」，实测值是 250，已发货的 `cli-recipes.md` §2.0 ④ 用的就是 250。〕所以 `list-metrics` 回空**不能**直接当「真实缺失」——会把「3 周前有流量、近 2 周没有」误判成模板写错，或反过来把活跃资源判成闲置。

- [ ] **Step 9: 跑门禁 + 敏感扫描**

```bash
cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done
grep -rnE '(^|[^0-9])[0-9]{12}([^0-9]|$)|\bi-[0-9a-f]{8,}|\bvol-[0-9a-f]{8,}|arn:aws' . && echo "!! 有敏感信息" || echo "clean"
```
Expected: 8 个文件全绿；敏感扫描 clean（本任务会粘实测价目，注意不要连带贴入账号 ID 或资源 ID）

- [ ] **Step 10: 提交**

```bash
git add aws-rightsizing/references/cli-recipes.md aws-rightsizing/references/mdq-dims.jq
git commit -m "fix: two recipes that fail verbatim, plus ALB/ElastiCache price disambiguation"
```

---

### Task 8: 文档卫生

**Files:**
- Modify: `aws-rightsizing/references/mdq-msk.jq`（文件头注释或实现）
- Modify: `aws-rightsizing/references/cli-recipes.md`（§1 的 MSK inventory、§0 与 §6.2 的机型数）
- Modify: `aws-rightsizing/references/report-template.md`（快照分节）
- Modify: `aws-rightsizing/references/thresholds.md`（快照说明、统计口径）
- Modify: `aws-rightsizing/references/metrics-catalog.md`（`mem_used_percent` 口径）
- Modify: `aws-rightsizing/SKILL.md`（只读自检的 grep）

**Interfaces:**
- Consumes: 无
- Produces: 无。

- [ ] **Step 1: `mdq-msk.jq` 注释与实现对齐（D1）**

文件头说 `broker_ids` 必须来自 `kafka list-nodes`、**不得由 brokers 计数生成 1..N**，而实现是 `range(1; ($c.value.brokers + 1))`——正是被禁止的写法。两次运行的 broker ID 恰好连续所以没暴露。

按 fail-closed 取向选实现方案：`cli-recipes.md §1` 的 MSK inventory 加一步 `kafka list-nodes` 取 `broker_ids`（注释里那段处理浮点 `BrokerId` 的 `awk '{printf "%d\n", $1}'` 已经写好，直接用），`mdq-msk.jq` 改读 `broker_ids`。加一句为什么：broker 替换后 ID 不保证连续，`range(1; N+1)` 会取到不存在的 Broker ID，而维度值错误时 `get-metric-data` **返回空且不报错**。

- [ ] **Step 2: 快照改为仅事实陈述（D2，裁定 R6）**

`report-template.md` 的报告分节里「超龄快照」改成「快照清单（仅事实陈述）」——列出快照、容量、创建日期、月额，不产出删除建议。在 `thresholds.md` 写明本版本不判快照年龄及原因：快照该不该删取决于 RPO 与合规要求，这个 skill 拿不到那些信息。**不加阈值**——`thresholds.json` 无快照年龄键，任何 agent 自己拍一个天数都违反「阈值以 `thresholds.json` 为唯一真值源」。

- [ ] **Step 3: 机型数标为参考值（D3）**

`cli-recipes.md §0` 与 §6.2 的「实测机型数：…」加限定：**（截至核实日期的观测值，会随 AWS 上新机型增长；对不上属正常，不必修模板）**。实测已漂移：某 region 从 1154 变成 1198。

同时区分漂移与稳定：会漂移的还有唯一 `(型号, operation)` 键数、价目全量取回的耗时与体积、`offerings` 数量；**不会**漂移的（T 系列基线百分比、`RequestHandlerAvgIdlePercent` 的 0–1 刻度）明确标为稳定。这样 agent 知道哪些数字该当断言、哪些该当参考。

- [ ] **Step 4: `pct` 的统计口径（D4）**

`agg.jq:27` 的 `def pct(p): sort | ... .[ (((length-1) * p) | floor) ]` 是**最近秩、不插值**。在 `thresholds.md` 的统计口径一节写一行说明——报告里的 p95 是客户直接照着动手的数，口径必须写清。

- [ ] **Step 5: `mem_used_percent` 的口径（D5）**

`metrics-catalog.md` 里该指标现在只有「已实测」一行。补：它是 CloudWatch agent 的 `mem_used / mem_total`，**不含可回收的 page cache**，所以对重度依赖文件缓存的负载（数据库、构建机、日志处理）会把内存需求**系统性低估**、定档偏紧。指向 Task 5 加的 `max_mem_reduction_ratio` 作为对策，并要求 `confidence=high` 的内存降幅行在报告里附一句人工复核提示。

- [ ] **Step 6: 修只读自检的假阳性（D6）**

`SKILL.md` 第 6 节末尾那两条 grep 会命中 `aws eks update-kubeconfig` 与 `aws configure get` ⇒ **`CLEAN` 永远打不出来**，自检等于失效。给这两个加白名单，并注明理由：前者只写临时 kubeconfig（`--kubeconfig "$KC"`，`KC` 来自 `mktemp -d`），后者只读本地配置，都不是 mutating 调用。

改完实跑一次，确认真的打印 `CLEAN`，把输出粘进报告。

- [ ] **Step 7: 跑门禁 + 敏感扫描**

```bash
cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" || exit 1; done
```
Expected: 8 个文件全绿

- [ ] **Step 8: 提交**

```bash
git add aws-rightsizing/references aws-rightsizing/SKILL.md
git commit -m "docs: align msk broker ids, snapshot scope, drift markers, and the self-check"
```

---

## 自检结果

**Spec 覆盖：** J1→Task 1、J2→Task 2、J3→Task 3、J5→Task 4、J4→Task 5、C1/C2/C3/C4/C5/C6/C7/C8/C9/C10→Task 6、P1–P7→Task 7、D1–D6→Task 8。R1→Task 7 Step 6、R2→Task 5、R3→Task 1 Step 3、R4→Task 6 Step 5、R5→Task 6 Step 1、R6→Task 8 Step 2、R7→Task 6 Step 2。无遗漏。

**占位符扫描：** 无 TBD / TODO / 「类似 Task N」。每个代码步骤都带可直接粘的代码。Task 6 Step 10 与 Task 8 各步是文档撰写，给出了必须覆盖的具体条目而非「视情况」。

**类型一致性：** 新增输入字段两个——`sample_n`（Task 1，整数或 `None`）与 `cheaper_candidate_exists`（Task 3，布尔或 `None`），两处都在 `sample-solve.md` 的托管字段表登记。新增阈值键一个——`max_mem_reduction_ratio`（Task 5）。`dispatch(res, ctx)` 签名不变；托管 evaluator 仍是 `(res, t)`。Task 4 只往 `insufficient-data` 行加已有名字的键（`cur_usd` / `cur_cost_mo` 等），不引入新键名。

**任务顺序依据：** Task 1–4 不动回归基线，Task 5 会动且只有它允许动——放在判据类任务最后，这样前四个任务都能拿 `401.51 / 312.48` 当不变式验证自己没越界。Task 6–8 只碰文档与配方，不需重跑回归。
