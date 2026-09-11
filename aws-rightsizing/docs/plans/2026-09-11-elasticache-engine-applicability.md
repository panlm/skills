# ElastiCache 引擎适用性分流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `eval_elasticache()` 先判引擎再判两个 Redis 独有指标，使 Memcached
集群得到 `excluded` 与正确说明，而不是一条指向不可能存在指标的 `metric-missing`。

**Architecture:** 新增输入字段 `engine`（取自 inventory 已有的同名字段），
在两条否决项之后、`cheaper_candidate_exists` 短路之前分流：
`redis` / `valkey` 走现有判据，`memcached` 与未知取值 ⇒ `excluded`，缺失 ⇒
`metric-missing`。既有 fixture 一律补 `engine="redis"` 以保住原意图。

**Tech Stack:** Python 3（标准库）；测试为可独立执行脚本。

**Spec:** [`docs/specs/2026-09-11-elasticache-engine-applicability-design.md`](../specs/2026-09-11-elasticache-engine-applicability-design.md)

## Global Constraints

- **本 skill 只读**；不引入 mutating AWS 调用或账单 API。
- **阈值唯一真值源是 `references/thresholds.json`**；本轮不新增阈值键。
- **`tests/test_regression_fleet.py` 与其 fixture 一律不改** —— 该机队只有 EC2 资源。
- **`route1` / `route2` / 桶 B / 采集侧四条口径与分母必须逐值不变**（两支机队全 redis）。
- **不为 Memcached 新增判据**，**不排除 Valkey**。
- **`excluded` 早退不得设或清 `cur_cost_mo`** —— 托管行的成本由采集侧填，
  判据插手会让整个服务从分母消失。
- **公开仓库**：不得出现真实账号 ID、实例 ID、资源名、profile 名、本机绝对路径。
- **不推 origin。**

---

### Task 1: 引擎分流 + 测试

**Files:**
- Modify: `references/core.py`（`eval_elasticache()`）
- Modify: `tests/test_managed_dispatch.py`（8 处 fixture + 新增一条测试）
- Modify: `tests/test_csv_contract.py`、`tests/test_fail_closed_contracts.py`（各 1 处 fixture）
- Modify: `references/sample-solve.md`（样例输入）
- Test: 全部 9 个测试文件

**Interfaces:**
- Consumes: `_verdict(out, verdict, *reasons)`；`res.get("engine")`。
- Produces: 输入字段 `engine`（ElastiCache 必填）；模块级常量
  `EC_ENGINES_WITH_ENGINE_CPU`（判据侧唯一的引擎白名单，供文档引用）。

- [ ] **Step 1: 给所有既有 elasticache fixture 补 `engine="redis"`**

`"redis"` 等价于改动前的行为，逐条保住原测试意图；新分流由 Step 3 的新测试覆盖。

```bash
cd aws-rightsizing && python3 - <<'PY'
import pathlib, re
total = 0
for f in ("tests/test_managed_dispatch.py", "tests/test_csv_contract.py",
          "tests/test_fail_closed_contracts.py"):
    p = pathlib.Path(f); s = p.read_text()
    a = len(re.findall(r'has_replica=False,', s))
    b = len(re.findall(r'"has_replica": False,', s))
    s = re.sub(r'has_replica=False,', 'has_replica=False, engine="redis",', s)
    s = re.sub(r'"has_replica": False,', '"has_replica": False, "engine": "redis",', s)
    p.write_text(s); total += a + b
    print(f"{f}: kwargs {a} 处 / dict 字面量 {b} 处")
print("合计", total, "处")
PY
```
Expected: `tests/test_managed_dispatch.py: kwargs 7 处 / dict 字面量 1 处`、
`tests/test_csv_contract.py: kwargs 0 处 / dict 字面量 1 处`、
`tests/test_fail_closed_contracts.py: kwargs 0 处 / dict 字面量 1 处`、`合计 10 处`。

**若合计不是 10，停下核对** —— 漏掉的那处会在 Step 4 变成一条 `metric-missing`
的假失败。`has_replica` 是上一轮刚加的，两种写法与它一一对应。

- [ ] **Step 2: `references/sample-solve.md` 补 `engine`**

该文档的 fixture 被 `tests/test_sample_reproduces.py` 解析。

```bash
cd aws-rightsizing && python3 - <<'PY'
import pathlib, re
p = pathlib.Path("references/sample-solve.md"); s = p.read_text()
n = len(re.findall(r'"has_replica": false,', s))
p.write_text(re.sub(r'"has_replica": false,',
                    '"has_replica": false, "engine": "redis",', s))
print("补了", n, "处")
PY
```
Expected: `补了 1 处`

- [ ] **Step 3: 写失败测试**

在 `tests/test_managed_dispatch.py` 的
`test_replication_lag_absence_splits_by_replica_presence` **之前**插入：

```python
def test_elasticache_engine_gates_the_redis_only_criteria():
    """两个主判据指标是 Redis/Valkey 独有 ⇒ 必须先判引擎，再判指标缺失。

    Memcached 是多线程的，EngineCPUUtilization 与
    DatabaseMemoryUsagePercentage 都不发布。此前它会拿到
    「EngineCPUUtilization 缺失。注意不可用 CPUUtilization 替代——Redis 单线程」
    —— 那句话对 Memcached 恰好是**反的**：它多线程，CPUUtilization 正是它的
    正确 CPU 指标。于是报告既给不出结论，又指导客户去补一个不可能存在的指标。
    与 CPUSurplusCreditsCharged 是同一类缺陷：把「不适用」当「缺失」。

    Valkey 必须与 Memcached 分开：它是 Redis 协议兼容的单线程引擎，两个指标
    都发布，现有判据对它成立。一起排除会白丢一整个引擎的降配路径。
    """
    t = core.load_thresholds("aggressive")
    base = dict(rid="cc-E", service="elasticache", type="cache.r7g.large",
                vcpu=2, mem_gib=13.07, evictions_sum=0, evictions_p95=0,
                repl_lag_p95=0.0007, repl_lag_max=0.03, has_replica=True,
                engine_cpu_p95=12, db_mem_used_pct_max=35, sample_n=243,
                cheaper_candidate_exists=True)

    # 反向半：两个单线程引擎都必须照常走到降配路径
    for eng in ("redis", "valkey"):
        ok = core.eval_elasticache(dict(base, engine=eng), t)
        assert ok["verdict"] == "downsize-candidate", (eng, ok["verdict"])
        assert ok["required_gib_usable"] is not None, (eng, ok)

    # Memcached ⇒ excluded，且说明不得指向那两个指标「缺失」
    mc = core.eval_elasticache(dict(base, engine="memcached",
                                    engine_cpu_p95=None,
                                    db_mem_used_pct_max=None), t)
    assert mc["verdict"] == "excluded", mc["verdict"]
    why = " ".join(mc["blockers"])
    assert "memcached" in why.lower(), mc["blockers"]
    assert "缺失" not in why, f"Memcached 的说明不得写成指标缺失 —— {mc['blockers']}"
    # 成本由采集侧填，判据不得插手（否则整个服务从分母消失）
    assert "cur_cost_mo" not in mc, mc

    # engine 缺失 ⇒ fail-closed，不得假定 Redis
    unknown = core.eval_elasticache(base, t)
    assert unknown["verdict"] == "metric-missing", unknown["verdict"]
    assert "engine 缺失" in unknown["blockers"][0], unknown["blockers"]

    # 未知取值 ⇒ 同样不评估，且理由里带上那个取值
    weird = core.eval_elasticache(dict(base, engine="dragonfly"), t)
    assert weird["verdict"] == "excluded", weird["verdict"]
    assert "dragonfly" in " ".join(weird["blockers"]), weird["blockers"]

    # Evictions 否决项对 Memcached 仍然有效（分流点在它之后）
    evict = core.eval_elasticache(dict(base, engine="memcached",
                                       evictions_p95=5, evictions_sum=9), t)
    assert evict["verdict"] == "blocked", (
        f"Memcached 也会淘汰键，该否决项不该被引擎分流跳过 —— {evict}")
```

同批在 `__main__` 的 `tests` 列表里，
`test_replication_lag_absence_splits_by_replica_presence,` **之前**插入：

```python
             test_elasticache_engine_gates_the_redis_only_criteria,
```

- [ ] **Step 4: 跑，确认只有新测试失败**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 8 个文件全绿；`tests/test_managed_dispatch.py` 为 `33/34 passed`，
唯一失败是 `test_elasticache_engine_gates_the_redis_only_criteria`。
若别的文件也红，回到 Step 1 核对 fixture 补漏。

- [ ] **Step 5: 加引擎白名单常量**

`references/core.py` 里，在 `def eval_elasticache(res, t):` **之前**插入：

```python
# 判据侧唯一的引擎白名单：这两个引擎是单线程、发布 EngineCPUUtilization 与
# DatabaseMemoryUsagePercentage。Memcached 多线程、两个都不发布，本版本不评估
# （它的 CPU 用 CPUUtilization、内存用 BytesUsedForCache 对上限，都**未实测**，
# 发明一套未验证的判据比诚实排除更糟）。改这个集合前先实测新引擎的指标与刻度。
EC_ENGINES_WITH_ENGINE_CPU = frozenset({"redis", "valkey"})
```

- [ ] **Step 6: 在 `eval_elasticache()` 里分流**

把这一段（`ReplicationLag` 尖峰注记之后、`cheaper` 短路的注释之前）：

```python
    if lag_max is not None and lag_max >= t["redis_repl_lag_max_s"]:
        out["blockers"].append(_spike_note("ReplicationLag", f"{lag_max}s",
                                           "failover / 备份快照"))
```

替换成：

```python
    if lag_max is not None and lag_max >= t["redis_repl_lag_max_s"]:
        out["blockers"].append(_spike_note("ReplicationLag", f"{lag_max}s",
                                           "failover / 备份快照"))
    # 引擎分流放在两条否决项**之后**：Evictions 与 ReplicationLag 对 Memcached
    # 同样成立（都会淘汰键；无副本则由 has_replica 放行），「这个缓存正在淘汰键」
    # 是有效阻断，与能不能降配无关。放在 cheaper 短路**之前**：excluded 是
    # 「本版本不评估」，比「没有更便宜候选」靠前——后者暗示已经评估过了。
    engine = res.get("engine")
    if engine is None:
        _verdict(out, "metric-missing",
                 "engine 缺失，无法判定 EngineCPUUtilization / "
                 "DatabaseMemoryUsagePercentage 是否适用（不得假定 Redis）")
        return out
    if engine not in EC_ENGINES_WITH_ENGINE_CPU:
        _verdict(out, "excluded",
                 f"引擎 {engine} 不在本版本的评估范围内："
                 f"两个主判据指标（EngineCPUUtilization / "
                 f"DatabaseMemoryUsagePercentage）只有 "
                 f"{'/'.join(sorted(EC_ENGINES_WITH_ENGINE_CPU))} 发布。"
                 f"该引擎需另一套判据（Memcached 多线程，CPU 看 CPUUtilization、"
                 f"内存看 BytesUsedForCache 对节点上限），本 skill **未实测**"
                 f"那套指标的刻度与维度集，故不产出结论而非猜一个")
        return out
```

- [ ] **Step 7: 跑全套，确认 9 个文件全绿**

Run: `cd aws-rightsizing && rm -rf tests/__pycache__ references/__pycache__ && for t in tests/test_*.py; do printf "%-42s " "$t"; python3 "$t" 2>&1 | tail -1; done`
Expected: 9 个文件全绿；`test_managed_dispatch.py` `34/34`、
`test_regression_fleet.py` `14/14`（锚定值未动）。

Run: `cd aws-rightsizing && git diff --quiet tests/test_regression_fleet.py tests/fixtures/regression-fleet.json && echo "回归文件未改 OK"`
Expected: `回归文件未改 OK`

- [ ] **Step 8: 提交**

```bash
git add references/core.py references/sample-solve.md \
        tests/test_managed_dispatch.py tests/test_csv_contract.py \
        tests/test_fail_closed_contracts.py
git commit -F - <<'MSG'
fix(aws-rightsizing): gate the Redis-only ElastiCache criteria on engine

EngineCPUUtilization and DatabaseMemoryUsagePercentage are published by
single-threaded engines only, and both failed closed on absence, so a
Memcached cluster would have been told "EngineCPUUtilization missing - note
that CPUUtilization is not a substitute, Redis is single-threaded". That
advice is backwards for Memcached, which is multi-threaded and for which
CPUUtilization is the right metric. Same defect class as
CPUSurplusCreditsCharged: treating "not applicable" as "missing".

Memcached is excluded rather than given invented criteria. Its CPU and memory
would come from CPUUtilization and BytesUsedForCache against the node limit,
neither of which this skill has measured for scale or dimensions, and the
house rule is to measure before adding a metric.

Valkey stays on the Redis path: it is protocol-compatible and single-threaded,
publishes both metrics, and lumping it in with Memcached would drop a whole
engine's downsize path. Its "unverified" note in SKILL.md is about the pricing
key, which the (instanceType, operation) composite already solved.

The split sits after the Evictions and ReplicationLag vetoes, because both
still hold for Memcached, and before the cheaper-candidate short-circuit,
because "not evaluated" outranks "nothing cheaper exists".
MSG
```

---

### Task 2: 契约与文档

**Files:**
- Modify: `references/cli-recipes.md`（`engine` 输入契约行）
- Modify: `references/metrics-catalog.md`（ElastiCache 两行指标标注）
- Modify: `SKILL.md`（ElastiCache 一节 + 通则清单状态）
- Modify: `docs/README.md`（specs / plans 索引）

- [ ] **Step 1: `cli-recipes.md` 加契约行**

在 `has_replica` 那一行**之后**插入：

```
| `engine` | ElastiCache 必填 | `raw/inventory/elasticache.json` 每个节点的 `engine` 字段原值（**小写**，实测 `"redis"`）。引擎是复制组级属性，同组取任一节点即可 | `metric-missing` —— 无法判定两个主判据指标是否适用，**不得假定 Redis**。`memcached` 与未知取值 ⇒ `excluded`（本版本不评估，判据侧白名单见 `core.py` 的 `EC_ENGINES_WITH_ENGINE_CPU`） |
```

- [ ] **Step 2: `metrics-catalog.md` 两行标注发布范围**

ElastiCache 一节里，`EngineCPUUtilization` 与
`DatabaseMemoryUsagePercentage` 两行的用途列各追加一句：

```
；**仅 redis / valkey 发布**（单线程引擎特有），Memcached 不发布 ⇒ 判据按 `engine` 分流成 `excluded`，不是 `metric-missing`
```

- [ ] **Step 3: `SKILL.md` ElastiCache 一节补引擎分流**

在「**必须用 `EngineCPUUtilization`，不得用 `CPUUtilization`**」那条**之前**插入：

```
- **先判引擎，再判指标。** `EngineCPUUtilization` 与
  `DatabaseMemoryUsagePercentage` 只有 `redis` / `valkey` 发布。Memcached
  多线程、两个都不发布 ⇒ `excluded`（本版本不评估），**不是 `metric-missing`** ——
  后者会让客户去补一个不可能存在的指标，并附带一条对该引擎恰好相反的断言
  （Memcached 的正确 CPU 指标就是 `CPUUtilization`）。`engine` 缺失 ⇒ fail-closed。
  白名单在 `core.py` 的 `EC_ENGINES_WITH_ENGINE_CPU`，**改它之前先实测新引擎的
  指标与刻度**。
```

- [ ] **Step 4: `SKILL.md` 通则清单更新状态**

把清单里这一段：

```
`EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage`（仅 Redis/Valkey，Memcached 不发布，**尚未分流** —— `eval_elasticache` 的输入里还没有 `engine` 字段）
```

替换成：

```
`EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage`（仅 redis/valkey 发布，**已按 `engine` 分流**）。**五个已知成员至此全部完成适用性分流**——新增指标时按本清单比对
```

- [ ] **Step 5: `docs/README.md` 加两行索引**

specs 表末尾：

```
| [2026-09-11-elasticache-engine-applicability-design.md](./specs/2026-09-11-elasticache-engine-applicability-design.md) | ElastiCache 的两个主判据指标仅 redis/valkey 发布,Memcached 此前得到指向不存在指标的 `metric-missing` 且说明与该引擎相反 |
```

plans 表末尾：

```
| [2026-09-11-elasticache-engine-applicability.md](./plans/2026-09-11-elasticache-engine-applicability.md) | `eval_elasticache` 先判 `engine` 再判两个 Redis 独有指标;Memcached ⇒ `excluded`,Valkey 留在 Redis 路径 |
```

- [ ] **Step 6: 跑测试与三条自检**

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

- [ ] **Step 7: 提交**

```bash
git add references/cli-recipes.md references/metrics-catalog.md \
        SKILL.md docs/README.md
git commit -m "docs(aws-rightsizing): record that the ElastiCache criteria are engine-scoped

Marks the two Redis-only metrics as such in the catalogue, adds the engine
input contract, and closes out the subset-published rule's checklist - all
five known members now resolve applicability before missingness."
```

---

### Task 3: 真实回放门禁

**Files:** 无仓库改动。

- [ ] **Step 1: 回放两支机队，确认逐行不变**

两支机队的 ElastiCache 节点全是 `redis`，所以本轮**期望零行为变化**。
设 `RAW` 指向一份既有交付的 `raw/`（含真实资源 ID，**不得提交**）。

```bash
RAW=<某份既有交付>/raw
python3 - "$RAW" "$PWD/references/core.py" <<'PY'
import json, re, subprocess, sys, glob, collections
raw, core = sys.argv[1], sys.argv[2]
inv = json.load(open(f"{raw}/inventory/elasticache.json"))
mem = collections.defaultdict(set)
eng = {}
for n in inv:
    m = re.search(r"-(\d{4})-\d{3}$", n["id"])
    mem[(n["rg"], m.group(1) if m else "0001")].add(n["id"])
    eng[n["rg"]] = n["engine"]
hr = collections.defaultdict(bool)
for (rg, _s), ms in mem.items():
    hr[rg] |= len(ms) > 1
print("engine 分布:", dict(collections.Counter(eng.values())))
def inject(r):
    if r.get("service") == "elasticache":
        r["has_replica"] = hr[r["rid"]]
        r["engine"] = eng[r["rid"]]
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
    ec = [r for r in rows if r.get("service") == "elasticache"]
    assert not [r for r in ec if r["verdict"] in ("metric-missing", "excluded")], \
        "全 redis 的机队不应出现 metric-missing / excluded"
    print(f"  {prof:<13} elasticache {len(ec)} 组 "
          f"verdicts={dict(collections.Counter(r['verdict'] for r in ec))}")
PY
```

Expected: `engine 分布: {'redis': N}`；两个 profile 的 ElastiCache verdict 分布
与上一轮回放**逐值相同**（实测第一支机队 `9 downsize-candidate / 4 已合理配置`），
脚本内的断言会拦住任何新出现的 `metric-missing` 或 `excluded`。

- [ ] **Step 2: 敏感信息扫描**

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
| C1 `engine` 字段与四条分流规则 | Task 1 Step 6；契约行在 Task 2 Step 1 |
| C2 分流点位置与三条依据 | Task 1 Step 6 的注释；`Evictions` 仍生效由 Step 3 最后一个断言锁住 |
| C3 说明写「不评估」而非「缺指标」 | Task 1 Step 6 的文案；Step 3 的 `"缺失" not in why` 断言 |
| P3 Valkey 不排除 | Task 1 Step 5 的白名单 + Step 3 的反向半（`valkey` 须 `downsize-candidate`） |
| 改动清单各文件 | Task 1（core / sample-solve / 三份测试）、Task 2（四份文档） |
| 测试影响：既有 fixture 补 `redis` 保住原意图 | Task 1 Step 1/2，含数量断言与「停下核对」 |
| 测试影响：回归 fixture 不受影响 | Global Constraints + Task 1 Step 7 的 `git diff --quiet` |
| 验证方式 1（9 文件全绿 + 锚定值不变） | Task 1 Step 7、Task 2 Step 6 |
| 验证方式 2（五态） | Task 1 Step 3（含第六个断言：Memcached 的 Evictions 仍阻断） |
| 验证方式 3（`excluded` 不丢成本） | Task 1 Step 3 的 `"cur_cost_mo" not in mc` |
| 验证方式 4（真实回放逐行不变） | Task 3 Step 1，脚本内断言 |
| 验证方式 5（三条自检） | Task 2 Step 6 |
| 「明确不做」各条 | Global Constraints 已收；Serverless 与 Memcached 判据未出现在任何 Files 里 |
| 「后续」第四轮 | **不在本 plan 范围** |

**Placeholder scan:** 无 TBD / TODO / 「类似 Task N」。唯一占位是 Task 3 Step 1 的
`RAW=<某份既有交付>/raw` —— 含真实账号，不能进版本库，已就地说明。

**Type consistency:**
- `EC_ENGINES_WITH_ENGINE_CPU` 是 `frozenset[str]`，Task 1 Step 5 定义、
  Step 6 用 `not in` 与 `sorted(...)` 消费，Task 2 Step 3 的文档引用同一名字。
- `engine` 是 `res` 的输入键，值为**小写**字符串；Step 1/2 注入的 fixture
  与 Task 3 从 inventory 取的 `n["engine"]` 都是小写，与白名单一致。
- 新测试函数名 `test_elasticache_engine_gates_the_redis_only_criteria`
  在 Task 1 Step 3 定义并同批注册进 `__main__` 的 `tests` 列表。
- blocker 断言用的子串（`engine 缺失`、引擎名本身）与 Step 6 的文案一致；
  `"缺失" not in why` 要求 `excluded` 分支的文案**不含**「缺失」二字 ——
  Step 6 的文案用的是「不在本版本的评估范围内」与「未实测」，满足该约束。
