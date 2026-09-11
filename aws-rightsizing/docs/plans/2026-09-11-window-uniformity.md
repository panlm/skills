# 窗口内覆盖不齐的可见性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「同资源内部分指标满覆盖、部分短覆盖」这个信号在报告里可见 ——
它意味着窗口内改过规格，而 `required_*` 正拿当前规格去乘测自另一规格的利用率。

**Architecture:** 一个共用 helper `_coverage_note(out, res)`，在四个判据的**最前面**
调用（早退路径也要带上注记）。消费可选输入字段 `partial_coverage`，缺失即维持
原行为。**不改任何 verdict 或金额** —— 判定偏差方向需要逐小时规格历史，
describe API 不提供。

**Tech Stack:** Python 3（标准库）；测试为可独立执行脚本。

**Spec:** [`docs/specs/2026-09-11-window-uniformity-design.md`](../specs/2026-09-11-window-uniformity-design.md)

## Global Constraints

- **本 skill 只读**；不引入新的 API 调用（信号来自已采的 `n`）。
- **不新增 `thresholds.json` 键** —— 90% / 600 两个门限只在采集侧派生时用，
  `core.py` 不读；放进 JSON 会造出孤儿键并弄红 `test_no_duplicated_constants.py`
  的双向键覆盖。
- **`partial_coverage` 是可选字段**，缺失时行为与本轮之前**逐字相同**。
  既有 fixture 一律不改（与前三轮不同）。
- **`tests/test_regression_fleet.py` 与其 fixture 不改**，锚定值不变。
- **不改任何 verdict、不改任何金额**；四条口径与分母逐值不变。
- **不处理「所有指标都短覆盖」**（资源新建）——那是既有的独立未完成项。
- **公开仓库**：不得出现真实账号 ID、实例 ID、资源名、profile 名、本机绝对路径。
- **不推 origin。**

---

### Task 1: `_coverage_note()` + 四个调用点

**Files:**
- Modify: `references/core.py`
- Modify: `tests/test_managed_dispatch.py`（新增一条测试）
- Test: 全部 9 个测试文件

**Interfaces:**
- Consumes: `res.get("partial_coverage")` —— 三元组数组
  `[[metric: str, n: int, expected: int], …]`。
- Produces: `_coverage_note(out, res) -> None`（就地 append 到 `out["blockers"]`）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_managed_dispatch.py` 的
`test_elasticache_engine_gates_the_redis_only_criteria` **之前**插入：

```python
def test_uneven_metric_coverage_is_flagged_on_every_service_and_exit():
    """同资源内部分指标短覆盖 ⇒ 每个服务、每条出口都要留一条注记。

    required_* 拿**当前**规格去乘**整窗口**的利用率百分比，只有在窗口内规格没变过
    时才成立，而一处都没校验。实测两台 db.m6g.xlarge 的核心指标 720/720、
    信用序列只有 178/720，且信用余额上限 576 对应 2 vCPU 机型 ⇒ 窗口内被放大过。
    方向：先小后大 ⇒ 混合 p95 虚高 ⇒ 低估节省（保守）；先大后小则相反，是危险方向。

    **注记必须在早退路径上也出现**——spec-unknown / metric-missing 这些行恰恰
    最需要解释「为什么数据看起来怪」。这是 helper 必须放在每个判据最前面的回归。

    反向半：字段缺失或为空时不得加任何注记，且 verdict 与不传时逐字相同。
    """
    t = core.load_thresholds("aggressive")
    gaps = [["CPUCreditBalance", 178, 720], ["CPUSurplusCreditsCharged", 178, 720]]

    # ① 四个服务都要产出注记，且 verdict 不受影响
    cases = {
        "ec2": (core.eval_rds, None),   # 占位，下面单独处理 EC2
    }
    ec2 = dict(EC2_OK, rid="i-U-01", partial_coverage=gaps)
    got = _findings(_ctx([ec2]))["i-U-01"]
    assert got["verdict"] == "downsize", got["verdict"]
    assert any("覆盖不齐" in b for b in got["blockers"]), got["blockers"]

    for label, fn, res in (
            ("rds", core.eval_rds, dict(RDS_OK, partial_coverage=gaps)),
            ("elasticache", core.eval_elasticache,
             dict(CACHE_OK, partial_coverage=gaps)),
            ("msk", core.eval_msk, dict(MSK_OK, partial_coverage=gaps))):
        out = fn(res, t)
        assert out["verdict"] == "downsize-candidate", (label, out["verdict"])
        note = [b for b in out["blockers"] if "覆盖不齐" in b]
        assert note, (label, out["blockers"])
        assert "CPUCreditBalance 178/720" in note[0], (label, note[0])
        assert "不改结论" in note[0], (label, note[0])

    # ② 早退路径也要带注记（spec-unknown 在最靠前的守卫上）
    early = core.eval_elasticache(dict(CACHE_OK, mem_gib=None,
                                       partial_coverage=gaps), t)
    assert early["verdict"] == "spec-unknown", early["verdict"]
    assert any("覆盖不齐" in b for b in early["blockers"]), (
        f"早退路径丢了覆盖注记 —— helper 没放在判据最前面：{early['blockers']}")

    # ③ 反向半：缺失与空数组都不得加注记，且 verdict 与不传时相同
    baseline = core.eval_rds(RDS_OK, t)
    for empty in (None, []):
        res = dict(RDS_OK)
        if empty is not None:
            res["partial_coverage"] = empty
        out = core.eval_rds(res, t)
        assert out["verdict"] == baseline["verdict"], (empty, out["verdict"])
        assert out["blockers"] == baseline["blockers"], (empty, out["blockers"])
```

同批在 `__main__` 的 `tests` 列表里，
`test_elasticache_engine_gates_the_redis_only_criteria,` **之前**插入：

```python
             test_uneven_metric_coverage_is_flagged_on_every_service_and_exit,
```

> 上面 `cases` 那个占位字典在最终代码里应删掉 —— 它是草稿残留，EC2 已单独处理。
> 落地时直接不写这四行（`cases = {...}` 到 `}`）。

- [ ] **Step 2: 跑，确认只有新测试失败**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 8 个文件全绿；`tests/test_managed_dispatch.py` `34/35 passed`，
唯一失败是 `test_uneven_metric_coverage_is_flagged_on_every_service_and_exit`。

- [ ] **Step 3: 加 helper**

`references/core.py` 里，在 `def _verdict(out, verdict, *reasons):` **之前**插入：

```python
def _coverage_note(out, res):
    """把「窗口内指标覆盖不齐」记成 blocker。**必须在任何早退分支之前调用。**

    整套判据的需求反推是 `required_vcpu = ceil(cur_vcpu × sus_cpu% / target)`
    —— 拿 describe 返回的**当前**规格去乘 CloudWatch 的**整窗口**利用率百分比。
    这个乘法只在「窗口内规格没变过」时成立，而本 skill 一处都没校验它。

    信号不需要新增采集：同一资源内某指标的点数明显低于该资源其他指标的点数，
    就说明它只在窗口的一段时间内存在。实测两台 db.m6g.xlarge 的
    CPUUtilization / DBLoad / FreeableMemory 都是 720/720，而
    CPUCreditBalance 只有 178/720，且信用余额上限 576 对应 2 vCPU 机型
    ⇒ 窗口内被放大过。

    **只标注、不改结论。** 判定偏差方向需要逐小时的规格历史：先小后大 ⇒
    混合 p95 虚高 ⇒ 低估节省（保守）；先大后小则相反，是危险方向。
    describe-* 只返回当前规格，CloudWatch 也没有「规格」这个维度，拿不到就不能算。

    放在最前面而不是各出口：早退路径（spec-unknown / metric-missing / excluded）
    上的行恰恰最需要解释「为什么数据看起来怪」。`_verdict()` 保证分支理由排在
    已追加的说明之前，所以先 append 再 `_verdict` 不会被覆盖。
    """
    gaps = res.get("partial_coverage")
    if not gaps:
        return
    detail = "、".join(f"{m} {n}/{exp}" for m, n, exp in gaps)
    out.setdefault("blockers", []).append(
        f"窗口内指标覆盖不齐（{detail}）：同资源的其他指标满覆盖，说明这些指标"
        f"只在窗口的一段时间里存在——常见成因是**窗口内改过规格**，"
        f"也可能是中途才开启的监控。此时本行的利用率百分比混合了两个规格的采样，"
        f"而需求量是按**当前**规格反推的，须人工确认窗口内规格未变。"
        f"本判据**不改结论**：判定偏差方向需要逐小时的规格历史，"
        f"describe-* 只返回当前规格，拿不到就不能算")
```

- [ ] **Step 4: 四个判据各加一行调用**

四处都插在 `out = {...}` 初始化**之后**、第一个守卫**之前**。

`evaluate()`：把

```python
    out = {"rid": rid, "cur": itype, "az": res.get("az"),
           "metric_coverage": coverage, "nonburst": None, "burst": None,
           "burst_na": None, "required_vcpu": None, "required_gib": None}
```

之后紧接着插入：

```python
    _coverage_note(out, res)
```

`eval_rds()` / `eval_elasticache()` / `eval_msk()`：三处的
`out = {"rid": res["rid"], "service": ..., "cur": res["type"], "blockers": []}`
之后各插入同一行 `_coverage_note(out, res)`。

- [ ] **Step 5: 跑全套**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿；`test_managed_dispatch.py` `35/35`、
`test_regression_fleet.py` `14/14`。

Run: `cd aws-rightsizing && git diff --quiet tests/test_regression_fleet.py tests/fixtures/regression-fleet.json && echo "回归文件未改 OK"`
Expected: `回归文件未改 OK`

- [ ] **Step 6: 提交**

```bash
git add references/core.py tests/test_managed_dispatch.py
git commit -F - <<'MSG'
feat(aws-rightsizing): surface uneven metric coverage across the window

required_vcpu multiplies the current spec by utilisation percentages measured
over the whole window, which only holds if the spec never changed - and
nothing checked that. Two real db.m6g.xlarge instances have CPUUtilization,
DBLoad and FreeableMemory at 720/720 while their credit series covers 178/720,
and the credit ceiling of 576 corresponds to a 2-vCPU class, so they were
scaled up mid-window. Their percentages blend two specs.

Flags it without changing any verdict or amount. Deciding which way the bias
runs needs an hourly spec history: scaled up means the blended p95 reads high
and savings are understated, scaled down means the opposite and that is the
dangerous direction. describe-* returns only the current spec and CloudWatch
has no spec dimension, so the honest ceiling is a note.

The helper runs before every guard, because the early exits - spec-unknown,
metric-missing, excluded - are exactly the rows that most need an explanation
for why their data looks odd. partial_coverage stays optional, so absent input
behaves exactly as before and no existing fixture changes.
MSG
```

---

### Task 2: 采集配方与文档

**Files:**
- Modify: `references/cli-recipes.md`（契约行 + 派生配方）
- Modify: `SKILL.md`（易错项 + 「资源新 vs 监控缺失」的分界）
- Modify: `references/report-template.md`（`blockers` 一节）
- Modify: `docs/README.md`（索引）

- [ ] **Step 1: `cli-recipes.md` 加契约行**

在 `metric_coverage` 那一行**之后**插入（注意与它区分：那条列的是**完全缺失**的
字段名，本条列的是**部分覆盖**的指标）：

```
| `partial_coverage` | 否 | 三元组数组 `[[指标名, 该指标点数, 该资源最大点数], …]`。派生规则见下方配方：同资源 `full-window` 档内，**该资源最大点数 >= 600** 且某指标点数 **< 最大值的 90%**。与 `metric_coverage` 不同——那条列的是**完全缺失**的字段，本条列的是**部分覆盖**的指标 | 不加注记，行为与不传时逐字相同（**可选字段，向后兼容**） |
```

- [ ] **Step 2: `cli-recipes.md` 加派生配方**

紧接 `has_replica` 那段派生之后插入：

```
**`partial_coverage` 的派生。** 信号在已采的 `n` 里，不需要新增任何 API 调用：
同一资源内某指标的点数明显低于该资源其他指标的点数，说明它只在窗口的一段时间
里存在 —— 常见成因是**窗口内改过规格**（实测两台 `db.m6g.xlarge` 的信用序列
只覆盖 178/720，而核心指标 720/720，且信用上限对应一个更小的机型）。

```bash
# 对每个 summary-*.csv 跑；门限 600 与 90% 的理由见下
for f in raw/metrics/summary-*.csv; do
  awk -F, 'NR>1 && $5=="\"full-window\"" {
             gsub(/"/,""); res=$1; met=$2; n=$6+0
             if (n > mx[res]) mx[res]=n
             key=res SUBSEP met; pts[key]=n; r[key]=res; m[key]=met }
           END { for (k in pts)
                   if (mx[r[k]] >= 600 && pts[k] < mx[r[k]] * 0.9)
                     printf "%s\t%s\t%d\t%d\n", r[k], m[k], pts[k], mx[r[k]] }' "$f"
done
```

**两个门限的理由**：`>= 600`（30 天窗口的 ~83%）确保拿来做基准的「该资源最大
点数」自己是满覆盖的 —— 否则一个整体新建的资源会让所有指标互相比较、全部通过；
`< 90%` 留出正常抖动的余量（CloudWatch 偶发缺点、窗口边界）。

**这两个数不进 `thresholds.json`**：它们只在派生时用，`core.py` 只消费结果数组、
从不读它们。放进去会造出一个判据从不读取的孤儿键，而
`tests/test_no_duplicated_constants.py` 的键覆盖是**双向**的。

**实测结果**（两支机队）：命中 **2 台 RDS**（各 2 个指标，均 `178/720`）。
另有 2 个 ALB 的 `ActiveConnectionCount` 也会命中，但那属采集侧的 VPC 行、
`core.py` 没有 VPC 判据，且 §2.6 的 ALB/NAT 闲置判据**本来就带覆盖度门槛** ——
**不要把 ALB/NAT 的行喂进 `partial_coverage`**，那会重复告警。
```

- [ ] **Step 3: `SKILL.md` 易错项加一行**

在易错项表最后一行之后、`## references` 之前插入：

```
| **假定资源规格在窗口内不变** | `required_vcpu = ceil(cur_vcpu × sus_cpu% / target)` 拿 describe 返回的**当前**规格去乘 CloudWatch 的**整窗口**利用率，而一处都没校验规格没变过。实测两台 `db.m6g.xlarge` 的核心指标 720/720、信用序列 178/720、信用上限 576 对应 2 vCPU ⇒ 窗口内被放大过，它们的百分比混合了两个规格。方向：先小后大 ⇒ 低估节省（保守）；**先大后小 ⇒ 高估节省，是危险方向** | 采集侧派生 `partial_coverage`（同资源内某指标点数 < 最大值的 90%），判据用 `_coverage_note()` 在**每条出口**上留注记。**只标注不校正** —— 判定方向需要逐小时的规格历史，`describe-*` 只返回当前规格。要真正校正须引入配置历史类数据源，超出本 skill 的只读边界 |
```

- [ ] **Step 4: `SKILL.md` 划清与「资源新」的分界**

把易错项里既有的那条：

```
| 无内存数据就拍个内存下限 |
```

**不动**。改的是本文件末尾「验证状态」之外的那条既有未完成项描述 ——
在 `SKILL.md` 里搜索 `「资源新」与「监控缺失」仍未分开`，若存在则在其后补一句：

```
（与 `partial_coverage` 是两件事：那条信号是**部分**指标短覆盖、其余满覆盖，
成因是窗口内改过规格；「资源新」是**所有**指标都短覆盖。两者方向与处置都不同，
不要合并成一条判据。）
```

若 `SKILL.md` 里没有这句（它在 `RERUN-NOTES.md` 而非 `SKILL.md`），
则跳过本步并在提交信息里说明 —— **不要为了补这句而新造一段**。

- [ ] **Step 5: `report-template.md` 的 `blockers` 一节补一句**

在 `blockers` 那一行的说明末尾追加：

```
。**覆盖不齐注记（`partial_coverage`）可能出现在任何 verdict 上**，包括
`spec-unknown` / `metric-missing` / `excluded` 这些早退行——它解释的是数据本身
可疑，与该行有没有建议无关
```

- [ ] **Step 6: `docs/README.md` 加索引两行**

specs 表末尾：

```
| [2026-09-11-window-uniformity-design.md](./specs/2026-09-11-window-uniformity-design.md) | 判据假定规格在窗口内不变却一处未校验;用「部分指标短覆盖」这个已有信号标注,只标注不校正 |
```

plans 表末尾：

```
| [2026-09-11-window-uniformity.md](./plans/2026-09-11-window-uniformity.md) | `_coverage_note()` 在四个判据的每条出口留注记;`partial_coverage` 为可选字段,既有 fixture 不改 |
```

- [ ] **Step 7: 跑测试与三条自检**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿。

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

- [ ] **Step 8: 提交**

```bash
git add references/cli-recipes.md references/report-template.md \
        SKILL.md docs/README.md
git commit -m "docs(aws-rightsizing): record the window-uniformity signal and its limits

Adds the partial_coverage derivation - the signal is already in the collected
n values, so no new API call - with the two thresholds kept in the recipe
rather than thresholds.json, because core.py consumes the result array and
never reads them.

States the boundary against the separate unfinished item: partial_coverage is
some metrics short while others are full, meaning the spec changed; a new
resource is all metrics short. Different causes, different handling."
```

---

### Task 3: 真实回放门禁

**Files:** 无仓库改动。

- [ ] **Step 1: 派生配方跑真实数据，与手工扫描对账**

设 `RAW` 指向一份既有交付的 `raw/`（含真实资源 ID，**不得提交**）。

```bash
RAW=<某份既有交付>/raw
for f in "$RAW"/metrics/summary-*.csv; do
  awk -F, 'NR>1 && $5=="\"full-window\"" {
             gsub(/"/,""); res=$1; met=$2; n=$6+0
             if (n > mx[res]) mx[res]=n
             key=res SUBSEP met; pts[key]=n; r[key]=res; m[key]=met }
           END { for (k in pts)
                   if (mx[r[k]] >= 600 && pts[k] < mx[r[k]] * 0.9)
                     printf "%s\t%s\t%d\t%d\n", r[k], m[k], pts[k], mx[r[k]] }' "$f"
done | sort
```

Expected: 该机队上 **2 台 RDS 各 2 个指标**（`CPUCreditBalance` 与
`CPUSurplusCreditsCharged`，均 `178/720`），外加 ALB 的
`ActiveConnectionCount`（**不喂进 `partial_coverage`**，见 Task 2 Step 2）。

- [ ] **Step 2: 注入后回放，确认 verdict 逐行不变**

```bash
RAW=<某份既有交付>/raw
python3 - "$RAW" "$PWD/references/core.py" <<'PY'
import csv, json, re, subprocess, sys, glob, collections
raw, core = sys.argv[1], sys.argv[2]

# partial_coverage：同资源内点数 < 最大值 90%，且最大值 >= 600；排除 VPC/ALB 行
gaps = collections.defaultdict(list)
for f in glob.glob(f"{raw}/metrics/summary-*.csv"):
    if "vpc" in f:
        continue
    rows = [r for r in csv.DictReader(open(f)) if r["bucket"] == "full-window"]
    mx = collections.defaultdict(int)
    for r in rows:
        mx[r["resource"]] = max(mx[r["resource"]], int(r["n"]))
    for r in rows:
        n, m = int(r["n"]), mx[r["resource"]]
        if m >= 600 and n < m * 0.9:
            entry = [r["metric"], n, m]
            if entry not in gaps[r["resource"]]:
                gaps[r["resource"]].append(entry)
print("partial_coverage 命中资源:", len(gaps))

# 上三轮的字段也要补齐，否则 fail-closed 会盖掉本轮的观察
inv = json.load(open(f"{raw}/inventory/elasticache.json"))
mem, eng = collections.defaultdict(set), {}
for n in inv:
    m = re.search(r"-(\d{4})-\d{3}$", n["id"])
    mem[(n["rg"], m.group(1) if m else "0001")].add(n["id"])
    eng[n["rg"]] = n["engine"]
hr = collections.defaultdict(bool)
for (rg, _s), ms in mem.items():
    hr[rg] |= len(ms) > 1
cb = {}
for f in ("summary-ec2-all.csv", "summary-rds.csv"):
    for r in csv.DictReader(open(f"{raw}/metrics/{f}")):
        if (r["metric"] == "CPUCreditBalance" and r["stat"] == "Minimum"
                and r["bucket"] == "full-window"):
            cb[r["resource"]] = (float(r["min"]), float(r["max"]))

def inject(r):
    if r["rid"] in gaps:
        r["partial_coverage"] = gaps[r["rid"]]
    if r["rid"] in cb:
        r["credit_balance_min"], r["credit_balance_max"] = cb[r["rid"]]
    if r.get("service") == "elasticache":
        r["has_replica"], r["engine"] = hr[r["rid"]], eng[r["rid"]]
    return r

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
    noted = [r for r in rows if any("覆盖不齐" in b for b in (r.get("blockers") or []))]
    ds = [r for r in rows if r.get("bucket") == "downsize"]
    r1 = round(sum(r.get("nb_save_mo") or 0 for r in ds), 2)
    old = json.load(open(f"{raw}/solver/totals-{prof}.json"))
    assert r1 == old["route1"], f"route1 变了：{r1} vs {old['route1']}"
    print(f"  {prof:<13} route1={r1} 覆盖注记={len(noted)} "
          f"其 verdict={[r['verdict'] for r in noted]}")
PY
```

Expected：`覆盖注记=2`，两行的 verdict 都是 `blocked`（`FreeableMemory` 独立否决，
优先级更高），`route1` 与旧值逐值相同（脚本内已断言）。

- [ ] **Step 3: 敏感信息扫描**

```bash
cd ~/git/panlm-skills && git diff main...HEAD -U0 -- aws-rightsizing | grep '^+' \
  | grep -vE '^\+\+\+' \
  | grep -nE '[0-9]{12}|i-0[0-9a-f]{6,}|vol-0[0-9a-f]|snap-0[0-9a-f]|aws-(stg|pt|uat|sit|prod)-|/Users/|/home/|hk-(staging|situat)' \
  | grep -v '123456789012' || echo "CLEAN: no sensitive identifiers in diff"
```
Expected: `CLEAN`（plan 内自检脚本自身的模式串会命中，属既有假阳性）

---

## Self-Review

**Spec coverage:**

| spec 条目 | 落在哪个 task |
|---|---|
| C1 `partial_coverage` 字段与派生规则 | Task 2 Step 1/2；契约上的「可选、向后兼容」由 Task 1 Step 1 的反向半锁住 |
| C1 两个门限不进 `thresholds.json` 的理由 | Global Constraints + Task 2 Step 2 |
| C2 helper 与四个调用点、必须在早退之前 | Task 1 Step 3/4；早退回归由 Step 1 的 ② 锁住 |
| C3 文案三要点 | Task 1 Step 3 的文案；Step 1 断言 `CPUCreditBalance 178/720` 与 `不改结论` |
| P3 ALB/NAT 不喂进本字段 | Task 2 Step 2 的显式警告 + Task 3 Step 2 脚本里 `if "vpc" in f: continue` |
| P4 与「资源新」的分界 | Task 2 Step 4（含「找不到就跳过、不要新造一段」的处置） |
| 验证方式 1（9 文件全绿 + 回归不变） | Task 1 Step 5、Task 2 Step 7 |
| 验证方式 2（三项） | Task 1 Step 1 的 ①②③ |
| 验证方式 3（派生与手工扫描一致） | Task 3 Step 1 |
| 验证方式 4（注入后 verdict 逐行不变、route1 不变） | Task 3 Step 2，脚本内断言 |
| 验证方式 5（三条自检） | Task 2 Step 7 |
| 「明确不做」各条 | Global Constraints 已收；§2.6 与「资源新」判据未出现在任何 Files 里 |

**Placeholder scan:** Task 1 Step 1 的测试代码里有一处**故意留下的草稿残留**
（`cases = {...}` 占位字典），已在紧随其后的引用块里明确指出落地时删掉 ——
这是提示而非占位符。唯一真占位是 Task 3 的 `RAW=<某份既有交付>/raw`，
含真实账号不能进版本库，已就地说明。

**Type consistency:**
- `partial_coverage` 是 `list[list[str | int]]`（三元组），Task 1 Step 3 的
  `for m, n, exp in gaps` 按此解包；Task 2 Step 2 的 awk 与 Task 3 Step 2 的
  Python 都产出同一形状（`[指标名, 点数, 最大点数]`）。
- `_coverage_note(out, res) -> None` 就地改 `out`，与 `_spike_note()`
  返回字符串的风格**不同** —— 后者由调用方 append，本函数自己 append，
  因为它要在四个判据里以同一行调用。
- 新测试函数名 `test_uneven_metric_coverage_is_flagged_on_every_service_and_exit`
  在 Task 1 Step 1 定义并同批注册。
- 测试复用 `EC2_OK` / `RDS_OK` / `CACHE_OK` / `MSK_OK` 四个既有 fixture 常量与
  `_findings` / `_ctx` 两个既有 helper，均在 `test_managed_dispatch.py` 顶部。
