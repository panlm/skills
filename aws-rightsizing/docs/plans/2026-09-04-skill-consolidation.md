# aws-rightsizing Skill 固化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消灭 skill 里剩余的"同一事实多处复述"与"schema 与实现不符",让阈值只有一份机器可读真值、CSV 契约与 `core.py` 输出一致，并补上 EKS 的 requests 低估。

**Architecture:** 三件事。阈值与常量抽成 `thresholds.json`，`core.py` 直接读它，散文只引用不复述；`report-template.md` 的 CSV 契约按 `core.py` 实际输出重写，并加一条字段对齐自检；EKS 的 requests 计算补 init container 与 Pod overhead，并支持多集群。

**Tech Stack:** Python 3（stdlib，无第三方依赖）、jq 1.7、AWS CLI v2、kubectl。

## Global Constraints

> **⚠️ 2026-09-04 补注：本计划里的 `527.15` 已撤回，不是回归锚点。**
> 它来自 `/tmp/core-in2.json`——一份仓库外的 fixture，把每台资源的 `cpu_n` 填成了
> **720**，即 30 天窗口的**全窗口**点数（`biz + off + weekend == WINDOW_DAYS × 24`），
> 而 `cpu_n` 的定义是 **`biz-hours` 档**的点数，是全窗口的子集。口径错的后果是
> 采样量守卫恒不触发，13 台全部产出建议，其中两台 biz-hours 只有 154 与 55 个点。
>
> **现行回归锚点**：`aws-rightsizing/tests/fixtures/regression-fleet.json`（仓库内、已脱敏）
> + `aws-rightsizing/tests/test_regression_fleet.py`。命令是
> `cd aws-rightsizing && python3 tests/test_regression_fleet.py`，数值是
> **11 条 / $401.51（aggressive）**、**10 条 / $312.48（conservative）**。
> 下文两处 Step 的 `Expected:` **已改成可复现的 `401.51`**——那是执行时的验收条件，
> 放一个作废的数字等于给下一个人一道错的门禁。只有两段引用的 commit message
> （`527.15` 各出现一次）**逐字保留**：那是已经提交过的记录，改它等于篡改记录。

以下为 skill 现有硬约束，逐字来自 `SKILL.md`，每个任务都隐含包含：

- 只读：仅 `describe*` / `list*` / `get*`。**禁止任何 mutating 调用。**
- **禁止 `ce:*` 及任何账单 API。** 允许 `pricing:GetProducts` 读公开按需价目。
- **禁止产出改变架构形态、CPU 架构或可用性等级的建议**（Serverless 迁移、跨 CPU 架构迁移、Spot/Karpenter、Redis 减副本/减 shard、RDS Multi-AZ→Single-AZ、MSK 减 broker 数）。
- **不代替人工在 non-burstable 与 burstable 之间选择**，两列一律都出。
- **缺失一律为 `None`，禁止兜底为 0 或任何默认值**；关键指标缺失时 fail-closed。
- **`metric-missing` 必须排在「已合理配置」之前**判定。
- 判据只有一个实现：`references/core.py`。采集侧 jq 只做 reshape，不含判据。
- skill 文件内**不得出现**账号 ID、实例/卷/NAT ID、ARN、集群名、LB 名。
- 静态资产共**三个**：`thresholds.json`（阈值策略）、`baseline-pct.json`（T 系列基线）、`legacy-families.json`（排除清单）。三者共同点是**无 API 可查**。其余一律运行时现查——该约束的真正意图是禁止把运行时可查的数据落成快照（如已删除的 `offerings-region.json`）。
- 验证环境：`AWS_PROFILE=panlm`。`ap-northeast-1` 有 13 running EC2 / 1 MSK / 2 ALB / 2 NAT；`us-west-2` 有 3 RDS（含 `db.serverless`、`db.t4g.medium`）/ 7 ElastiCache / 1 EKS（无 Container Insights）。**8 个 region 均无 NLB。**

---

## 现状与问题

| 文件 | 行 | 词 |
|---|---|---|
| `SKILL.md` | 486 | 2990 |
| `cli-recipes.md` | 963 | 3846 |
| `core.py` | 416 | 1512 |
| `thresholds.md` | 316 | 1493 |
| `metrics-catalog.md` | 258 | 1521 |
| 其余 11 个 | — | — |
| **合计** | **3124** | — |

Review 实测出的 5 个问题：

| # | 问题 | 实测证据 | 何时引入 |
|---|---|---|---|
| 1 | 阈值仍散在多文件 | `168` 在 4 个文件、`8C/32G` 在 4 个、`60` 在 5 个 | 原有，根因 A 未治 |
| 2 | `core.py` 不读阈值文件，全靠调用方传 | `json.load` 仅 1 处（读 stdin），阈值来自 `ctx["thresholds"]` | 新引入 |
| 3 | `idle_cpu_p95` / `msk_target_cpu_p95` 只在 `core.py` 里出现 | grep 仅命中 `core.py`，`thresholds.md` 无定义 | 新引入 |
| 4 | CSV 契约与实现不符 | 模板声明 7 段字段，`core.py` 实际输出 18 个键，名字也不同 | 新引入 |
| 5 | EKS requests 低估 | 未计 init container 与 Pod overhead；只取第一个集群 | 原有，P0-⑤ 未完 |

2 与 3 是我在把判据搬进 `core.py` 时造成的：阈值默认值散进了 Python 字面量，`thresholds.md` 反而不再是真值源——**根因 A 被搬了个家，没被治好**。

## File Structure

```
references/
  thresholds.json      新增。所有阈值与常量的唯一真值，core.py 直接读
  core.py              修改。从 thresholds.json 读默认值；补 EKS requests 计算
  thresholds.md        修改。删掉所有具体数值，只留判据说明与实测理由
  report-template.md   修改。CSV 契约按 core.py 实际输出重写
  cli-recipes.md       修改。EKS 段补多集群循环与 overhead 说明
  sample-solve.md      修改。补 thresholds.json 的加载方式
SKILL.md               修改。删掉正文里的具体阈值数字，改为指向 thresholds.json
tests/
  fixtures/            新增。每条判据一个最小输入 + 期望输出
```

拆分依据：数值与判据分离，是为了让"改数值"不需要碰代码、"改判据"不需要碰数值。
`thresholds.md` 保留是因为**理由和实测证据有独立价值**，它们不是配置。

---

## Task 1: 抽出 `thresholds.json`，`core.py` 读它

**Files:**
- Create: `aws-rightsizing/references/thresholds.json`
- Create: `aws-rightsizing/tests/fixtures/thresholds-default.json`
- Modify: `aws-rightsizing/references/core.py`

**Interfaces:**
- Produces: `load_thresholds(path=None, override=None) -> dict`，返回完整阈值字典。`thresholds.json` 的键名与现有 `ctx["thresholds"]` 完全一致，故 Task 2–5 的调用方式不变。
- Consumes: 无。

- [ ] **Step 1: 写失败测试**

`aws-rightsizing/tests/test_thresholds.py`：

```python
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "references"))
import core

REF = pathlib.Path(__file__).parent.parent / "references"

def test_thresholds_json_exists_and_covers_all_keys():
    """core.py 引用的每个阈值键都必须在 thresholds.json 里有定义。"""
    data = json.loads((REF / "thresholds.json").read_text())
    profiles = data["profiles"]
    for name in ("aggressive", "conservative"):
        p = profiles[name]
        for k in ("target_cpu_p95", "ceiling_cpu_max", "target_mem_p95",
                  "ceiling_mem_max", "burstable_baseline_headroom",
                  "max_reduction_ratio", "min_biz_hours_points",
                  "idle_cpu_p95", "idle_net_mb_day", "msk_target_cpu_p95",
                  "reserved_memory_pct_default", "burstable_max_vcpu",
                  "burstable_max_gib", "rds_dbload_ratio",
                  "rds_freeable_mem_floor_pct", "redis_repl_lag_max_s",
                  "msk_disk_used_max", "msk_handler_idle_min"):
            assert k in p, f"{name} 缺少 {k}"

def test_load_thresholds_returns_profile():
    t = core.load_thresholds(profile="conservative")
    assert t["target_cpu_p95"] == 40
    assert t["max_reduction_ratio"] == 2

def test_load_thresholds_rejects_unknown_profile():
    try:
        core.load_thresholds(profile="nope")
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("未知 profile 必须抛 ValueError，不得静默回退默认值")
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd ~/Documents/git/aws-cost-optimization-skill/aws-rightsizing
python3 -m pytest tests/test_thresholds.py -q 2>&1 | tail -5
```
Expected: FAIL，`FileNotFoundError: thresholds.json` 或 `AttributeError: module 'core' has no attribute 'load_thresholds'`

- [ ] **Step 3: 写 `thresholds.json`**

数值全部取自当前 `thresholds.md` 与 `core.py` 的现有值，不改动任何判据行为：

```json
{
  "_comment": "唯一真值源。散文文档不得复述这里的数值，只能引用键名。",
  "_verified": "2026-09-04",
  "profiles": {
    "aggressive": {
      "target_cpu_p95": 60,
      "ceiling_cpu_max": 85,
      "target_mem_p95": 70,
      "ceiling_mem_max": 85,
      "burstable_baseline_headroom": 0.20,
      "max_reduction_ratio": 3,
      "min_biz_hours_points": 168,
      "idle_cpu_p95": 5,
      "idle_net_mb_day": 5,
      "msk_target_cpu_p95": 40,
      "reserved_memory_pct_default": 25,
      "burstable_max_vcpu": 8,
      "burstable_max_gib": 32,
      "rds_dbload_ratio": 0.5,
      "rds_freeable_mem_floor_pct": 15,
      "redis_repl_lag_max_s": 1,
      "msk_disk_used_max": 50,
      "msk_handler_idle_min": 0.70
    },
    "conservative": {
      "target_cpu_p95": 40,
      "ceiling_cpu_max": 60,
      "target_mem_p95": 50,
      "ceiling_mem_max": 70,
      "burstable_baseline_headroom": 0.20,
      "max_reduction_ratio": 2,
      "min_biz_hours_points": 168,
      "idle_cpu_p95": 5,
      "idle_net_mb_day": 5,
      "msk_target_cpu_p95": 40,
      "reserved_memory_pct_default": 25,
      "burstable_max_vcpu": 8,
      "burstable_max_gib": 32,
      "rds_dbload_ratio": 0.5,
      "rds_freeable_mem_floor_pct": 15,
      "redis_repl_lag_max_s": 1,
      "msk_disk_used_max": 50,
      "msk_handler_idle_min": 0.70
    }
  }
}
```

注意 `msk_handler_idle_min` 是 **0.70 不是 70**——`RequestHandlerAvgIdlePercent` 是 0–1 刻度，写成 70 会让判据永不成立。

- [ ] **Step 4: `core.py` 加 `load_thresholds`**

在 `core.py` 的 `import` 之后、`_fam` 之前插入：

```python
import pathlib

_THRESHOLDS_PATH = pathlib.Path(__file__).with_name("thresholds.json")


def load_thresholds(profile="aggressive", path=None, override=None):
    """从 thresholds.json 读一个 profile。

    阈值不在本文件内写字面量——那会让 thresholds.json 失去唯一真值地位，
    且散文文档与代码可能各自漂移（本 skill 已在 Sum 系数上犯过两次）。

    未知 profile 抛 ValueError 而非回退默认值：静默回退会让
    `--profile consrvative`（拼错）跑出 aggressive 的结果而无人察觉。
    """
    data = json.loads((pathlib.Path(path) if path else _THRESHOLDS_PATH).read_text())
    profiles = data["profiles"]
    if profile not in profiles:
        raise ValueError(f"未知 sizing_profile: {profile}；可选 {sorted(profiles)}")
    t = dict(profiles[profile])
    if override:
        unknown = set(override) - set(t)
        if unknown:
            raise ValueError(f"override 含未定义的键: {sorted(unknown)}")
        t.update(override)
    return t
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
python3 -m pytest tests/test_thresholds.py -q 2>&1 | tail -3
```
Expected: `3 passed`

- [ ] **Step 6: `main()` 支持不传 thresholds 时自动加载**

把 `core.py` 的 `main()` 开头改为：

```python
def main():
    ctx = json.load(sys.stdin)
    # ctx 未给 thresholds 时按 sizing_profile 从 thresholds.json 加载。
    # 给了则原样使用，便于测试注入。
    if "thresholds" not in ctx:
        ctx["thresholds"] = load_thresholds(ctx.get("sizing_profile", "aggressive"))
    ctx["_specs_by_type"] = {s["t"]: s for s in ctx["specs"]}
```

- [ ] **Step 7: 回归——真实机队结论必须不变**

```bash
cd /tmp/rs-build/run
jq '. + {sizing_profile:"aggressive"} | del(.thresholds)' /tmp/core-in.json > /tmp/core-in2.json
python3 ~/Documents/git/aws-cost-optimization-skill/aws-rightsizing/references/core.py \
  < /tmp/core-in2.json > /tmp/core-out2.json
jq -r '(map(.nb_save_mo//0)|add)*100|round/100' /tmp/core-out2.json
```
Expected: `401.51`（与抽取前完全一致。**任何差异都说明抽取改变了判据行为**，必须查明再继续。）
（本行原写 `527.15`，已撤回——上面命令里的 `/tmp/core-in2.json` 把 `cpu_n` 填成了全窗口点数，
采样量守卫恒不触发；原因见文件开头的补注。**改跑 `cd aws-rightsizing && python3 tests/test_regression_fleet.py`**。）

- [ ] **Step 8: Commit**

```bash
cd ~/Documents/git/aws-cost-optimization-skill
git add aws-rightsizing/references/thresholds.json aws-rightsizing/references/core.py aws-rightsizing/tests/
git commit -m "feat: single machine-readable threshold source

Thresholds lived as Python literals in core.py while thresholds.md described them
in prose, so the duplicated-truth problem had simply moved rather than been fixed.
They now live only in thresholds.json, which core.py reads. An unknown profile
raises rather than falling back, since a typo would otherwise silently produce
aggressive results. Verified the live fleet total is unchanged at 527.15."
```

---

## Task 2: `thresholds.md` 删数值，只留理由

**Files:**
- Modify: `aws-rightsizing/references/thresholds.md`
- Modify: `aws-rightsizing/SKILL.md`
- Create: `aws-rightsizing/tests/test_no_duplicated_constants.py`

**Interfaces:**
- Consumes: Task 1 的 `thresholds.json`。
- Produces: 一条可执行的 lint 断言，防止数值再次漂回散文。

- [ ] **Step 1: 写失败测试**

`aws-rightsizing/tests/test_no_duplicated_constants.py`：

```python
import json, pathlib, re

ROOT = pathlib.Path(__file__).parent.parent
REF = ROOT / "references"

# 这些数值只能出现在 thresholds.json。出现在散文里就是复述，会漂移。
GUARDED = ["168", "0.70"]   # 不含 86400：它是「一天的秒数」这一物理常量，
                            # 不是可调阈值，也不在 thresholds.json 里；
                            # 守护它会在合法的窗口对齐算术上报假阳性

# 允许的例外：实测证据里引用数值是有价值的，但必须带「实测」二字同行。
EVIDENCE_MARK = re.compile(r"实测|verified|证据")


def _prose_files():
    return [ROOT / "SKILL.md"] + sorted(REF.glob("*.md"))


def test_guarded_constants_not_restated_in_prose():
    bad = []
    for f in _prose_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if EVIDENCE_MARK.search(line):
                continue
            for c in GUARDED:
                if re.search(rf"(?<![\d.]){re.escape(c)}(?![\d.])", line):
                    bad.append(f"{f.name}:{i} 复述了常量 {c}: {line.strip()[:70]}")
    assert not bad, "散文复述了 thresholds.json 的数值：\n" + "\n".join(bad)


def test_thresholds_md_points_at_json():
    txt = (REF / "thresholds.md").read_text()
    assert "thresholds.json" in txt, "thresholds.md 必须指向 thresholds.json 作为真值源"
```

- [ ] **Step 2: 运行，确认失败**

```bash
cd ~/Documents/git/aws-cost-optimization-skill/aws-rightsizing
python3 -m pytest tests/test_no_duplicated_constants.py -q 2>&1 | tail -12
```
Expected: FAIL，列出 `thresholds.md` 与 `SKILL.md` 里复述 `168` 等数值的具体行。

- [ ] **Step 3: 改 `thresholds.md`——数值换成键名**

把 solver 阈值表整段替换为：

```markdown
## solver 阈值

**数值在 `references/thresholds.json`，本文件不复述。** 两个 profile：
`aggressive` / `conservative`，按运行时输入 `sizing_profile` 取。

| 键 | 含义 |
|---|---|
| `target_cpu_p95` | 降配后 CPU 的 p95 应落在此值 |
| `ceiling_cpu_max` | 降配后 CPU 峰值不得超过此值 |
| `target_mem_p95` / `ceiling_mem_max` | 内存同上 |
| `max_reduction_ratio` | 单次 vCPU 降幅上限 |
| `min_biz_hours_points` | biz-hours 最少有效点数，低于则 `insufficient-data` |
| `idle_cpu_p95` / `idle_net_mb_day` | 桶 B 闲置门限 |
| `msk_target_cpu_p95` / `msk_disk_used_max` / `msk_handler_idle_min` | MSK 专有 |
| `rds_dbload_ratio` / `rds_freeable_mem_floor_pct` | RDS 专有 |
| `redis_repl_lag_max_s` / `reserved_memory_pct_default` | Redis 专有 |
| `burstable_max_vcpu` / `burstable_max_gib` | T 系列规格上限 |

含义是**降配之后**应达到的利用率，不是「低于多少才降配」的触发门限。
是否降配是算法副产品：算出的 required 等于当前规格则无建议。

`msk_handler_idle_min` 是 0–1 刻度（`RequestHandlerAvgIdlePercent` 实测
0.998–1.002），与同 namespace 的 `KafkaDataLogsDiskUsed`（0–100）不同。
写错刻度会让判据永不成立、建议被静默吞掉。
```

保留文件里所有「为什么这么定」的段落与实测证据（`ceiling` 为何留余量、
`max_reduction_ratio` 为何必要、内存不设下限的理由）——那些不是配置。

- [ ] **Step 4: 改 `SKILL.md`——正文数值改为引用**

`SKILL.md` 里凡出现具体阈值处，改为「见 `thresholds.json` 的 `<键名>`」。
运行时输入表里 `sizing_profile` 一行改为：

```markdown
| `sizing_profile` | `aggressive` / `conservative`，数值见 `references/thresholds.json` | 无，必填 |
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
python3 -m pytest tests/test_no_duplicated_constants.py -q 2>&1 | tail -3
```
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add aws-rightsizing/references/thresholds.md aws-rightsizing/SKILL.md aws-rightsizing/tests/
git commit -m "docs: prose references threshold keys instead of restating values

A lint test now fails if a guarded constant is restated outside thresholds.json,
except on lines carrying measured evidence, where citing the number is the point.
This is the structural fix for the duplication that produced three conflicting
statements of the Sum coefficient."
```

---

## Task 3: CSV 契约按 `core.py` 实际输出重写

**Files:**
- Modify: `aws-rightsizing/references/report-template.md`
- Create: `aws-rightsizing/tests/test_csv_contract.py`

**Interfaces:**
- Consumes: `core.evaluate()` 的返回字典（18 个键，见测试）。
- Produces: `report-template.md` 里的 CSV 列清单，与实现一一对应。

- [ ] **Step 1: 写失败测试**

`aws-rightsizing/tests/test_csv_contract.py`：

```python
import pathlib, re, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

def _sample_finding():
    ctx = {"thresholds": core.load_thresholds("aggressive"),
           "specs": [{"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
                      "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True}],
           "prices": {"m5.large|RunInstances": 0.124},
           "baseline_pct": {}, "categories": {"m5.large": "General purpose"},
           "offerings": ["m5.large"], "legacy_families": []}
    ctx["_specs_by_type"] = {s["t"]: s for s in ctx["specs"]}
    ctx["_offerings"] = set(ctx["offerings"]); ctx["_legacy"] = set()
    res = {"rid": "i-EX", "type": "m5.large", "arch": "x86_64",
           "operation": "RunInstances", "sus_cpu": 5, "peak_cpu": 10,
           "sus_mem": None, "peak_mem": None, "ebs_need": 1,
           "surplus_credits": 0, "cpu_n": 720, "metric_coverage": []}
    return core.evaluate(res, ctx)

def test_every_output_key_is_documented():
    """core.py 输出的每个键都必须在 report-template.md 的列清单里。"""
    doc = (ROOT / "references" / "report-template.md").read_text()
    m = re.search(r"```csv-columns\n(.*?)```", doc, re.S)
    assert m, "report-template.md 缺少 ```csv-columns``` 块"
    documented = {c.strip() for c in m.group(1).replace("\n", ",").split(",") if c.strip()}
    produced = set(_sample_finding())
    missing = produced - documented
    assert not missing, f"实现输出了未记入契约的字段: {sorted(missing)}"

def test_no_documented_column_is_fabricated():
    """反向：契约里不得有实现根本不产出的字段（除派生列）。"""
    doc = (ROOT / "references" / "report-template.md").read_text()
    m = re.search(r"```csv-columns\n(.*?)```", doc, re.S)
    documented = {c.strip() for c in m.group(1).replace("\n", ",").split(",") if c.strip()}
    derived = {"account", "region", "service", "resource_name", "bucket",
               "instance_count", "blockers", "sample_points", "window_profile",
               "action_type", "nb_delta_vcpu", "nb_delta_gib", "b_delta_vcpu",
               "b_delta_gib", "nb_cat", "b_cat", "evidence_cpu_p95",
               "evidence_cpu_max", "evidence_mem_p95", "evidence_mem_max"}
    produced = set(_sample_finding())
    fabricated = documented - produced - derived
    assert not fabricated, f"契约声明了实现不产出且非派生的字段: {sorted(fabricated)}"
```

- [ ] **Step 2: 运行，确认失败**

```bash
python3 -m pytest tests/test_csv_contract.py -q 2>&1 | tail -8
```
Expected: FAIL，`report-template.md 缺少 csv-columns 块`

- [ ] **Step 3: 重写 `report-template.md` 的字段节**

把现有 `### findings.csv 字段` 整节替换为：

````markdown
### findings.csv 字段

**契约以下方代码块为准，由 `tests/test_csv_contract.py` 双向校验：
`core.py` 输出的键必须都在此，此处非派生列也必须都被输出。**

```csv-columns
account, region, service, resource_id, resource_name, bucket, verdict,
cur, cur_vcpu, cur_gib, cur_cat, cur_usd, cur_cost_mo,
required_vcpu, required_gib,
nonburst, nb_cat, nb_save_mo, nb_delta_vcpu, nb_delta_gib,
burst, b_cat, b_save_mo, b_delta_vcpu, b_delta_gib, burst_na,
az, instance_count, metric_coverage, confidence,
evidence_cpu_p95, evidence_cpu_max, evidence_mem_p95, evidence_mem_max,
sample_points, window_profile, blockers, action_type
```

**来自 `core.py` 的字段**（名字即实现字段名，不得重命名）：
`rid`→`resource_id`、`cur`、`cur_vcpu`、`cur_gib`、`cur_cat`、`cur_usd`、
`cur_cost_mo`、`required_vcpu`、`required_gib`、`nonburst`、`burst`、
`nb_save_mo`、`b_save_mo`、`burst_na`、`az`、`metric_coverage`、
`confidence`、`verdict`。

**由采集侧补齐的派生列**：`account`、`region`、`service`、`resource_name`、
`bucket`、`instance_count`、`evidence_*`、`sample_points`、`window_profile`、
`blockers`、`action_type`。

### verdict 枚举（由 `core.py` 产出，不得自造）

```
downsize | 已合理配置 | insufficient-data | spec-unknown | price-unknown
metric-missing | excluded | downsize-candidate | upsize-candidate | blocked
```

后三个来自托管服务判据（`eval_rds` / `eval_elasticache` / `eval_msk`）。
`upsize-candidate` 不是降配建议——它表示该资源规格**已不足**，
出现在报告里必须与降配建议分开呈现，否则会被误读成可优化项。
````

- [ ] **Step 4: 运行测试，确认通过**

```bash
python3 -m pytest tests/test_csv_contract.py -q 2>&1 | tail -3
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add aws-rightsizing/references/report-template.md aws-rightsizing/tests/
git commit -m "docs: CSV contract matches core.py output, checked both ways

The template declared field groups that no longer matched the implementation after
judgments moved into core.py: it named seven groups while evaluate returns eighteen
keys under different names. The contract is now a single machine-checkable block,
verified in both directions so neither an undocumented output nor a fabricated
column can pass. Also records that upsize-candidate is not a downsizing
recommendation and must be presented separately."
```

---

## Task 4: EKS requests 计算补 init container 与 Pod overhead

**Files:**
- Modify: `aws-rightsizing/references/core.py`
- Modify: `aws-rightsizing/references/cli-recipes.md`
- Create: `aws-rightsizing/tests/test_eks_requests.py`
- Create: `aws-rightsizing/tests/fixtures/k8s-pods-sample.json`

**Interfaces:**
- Consumes: Task 1 的 `load_thresholds`。
- Produces: `pod_requests(pod) -> (cpu_cores, mem_gib)`，供预订率与 bin-packing 使用。

- [ ] **Step 1: 写失败测试**

`aws-rightsizing/tests/test_eks_requests.py`：

```python
import json, pathlib, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

def test_init_container_takes_max_not_sum():
    """K8s 调度取 max(Σ普通容器, 各 init 容器)，不是相加。

    init 容器顺序执行且在普通容器启动前完成，故其 request 与普通容器不叠加，
    但单个 init 容器的 request 可能高于普通容器之和，此时以它为准。
    """
    pod = {"spec": {"containers": [{"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}}}],
                    "initContainers": [{"resources": {"requests": {"cpu": "2", "memory": "4Gi"}}}]}}
    cpu, mem = core.pod_requests(pod)
    assert cpu == 2.0, f"init 容器 2 核应胜出，得到 {cpu}"
    assert abs(mem - 4.0) < 1e-9

def test_pod_overhead_is_added():
    """Pod overhead 是叠加的，不参与 max 比较。"""
    pod = {"spec": {"containers": [{"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}}}],
                    "overhead": {"cpu": "50m", "memory": "128Mi"}}}
    cpu, mem = core.pod_requests(pod)
    assert abs(cpu - 0.15) < 1e-9, f"0.1 + 0.05 overhead，得到 {cpu}"
    assert abs(mem - 0.375) < 1e-9

def test_missing_requests_count_as_zero_not_none():
    """未声明 request 的容器按 0 计——这是 K8s 的真实调度行为，不是缺失数据。"""
    pod = {"spec": {"containers": [{"resources": {}}, {"resources": {"requests": {"cpu": "1"}}}]}}
    cpu, mem = core.pod_requests(pod)
    assert cpu == 1.0
    assert mem == 0.0

def test_booking_rate_over_multiple_clusters():
    """必须逐集群分别算，不能把多个集群的 requests 与 allocatable 混在一起。"""
    fx = json.loads((ROOT / "tests" / "fixtures" / "k8s-pods-sample.json").read_text())
    rates = core.booking_rates(fx["clusters"])
    assert set(rates) == {"cluster-a", "cluster-b"}
    assert rates["cluster-a"]["cpu_pct"] != rates["cluster-b"]["cpu_pct"]
```

- [ ] **Step 2: 写 fixture**

`aws-rightsizing/tests/fixtures/k8s-pods-sample.json`：

```json
{"clusters": [
  {"name": "cluster-a",
   "nodes": [{"allocatable": {"cpu": "1930m", "memory": "7146376Ki"}}],
   "pods": [{"spec": {"containers": [{"resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}}]}}]},
  {"name": "cluster-b",
   "nodes": [{"allocatable": {"cpu": "3860m", "memory": "14292752Ki"}}],
   "pods": [{"spec": {"containers": [{"resources": {"requests": {"cpu": "200m", "memory": "512Mi"}}}]}}]}
]}
```

- [ ] **Step 3: 运行，确认失败**

```bash
python3 -m pytest tests/test_eks_requests.py -q 2>&1 | tail -5
```
Expected: FAIL，`AttributeError: module 'core' has no attribute 'pod_requests'`

- [ ] **Step 4: 实现**

在 `core.py` 的托管服务判据之后追加：

```python
# ============================================================
# EKS：requests 计算与预订率
# ============================================================

def _cpu_cores(v):
    """K8s CPU 量转核数。None 按 0 计——未声明 request 是真实调度行为，不是缺失数据。"""
    if v is None:
        return 0.0
    v = str(v)
    return float(v[:-1]) / 1000 if v.endswith("m") else float(v)


def _mem_gib(v):
    if v is None:
        return 0.0
    v = str(v)
    for suf, div in (("Ki", 1048576), ("Mi", 1024), ("Gi", 1), ("Ti", 1 / 1024)):
        if v.endswith(suf):
            return float(v[:-2]) / div
    return float(v) / (1024 ** 3)


def pod_requests(pod):
    """返回 (cpu_cores, mem_gib)，遵循 K8s 实际调度算法。

    调度用量 = max(Σ 普通容器, 各 init 容器的最大值) + pod overhead

    init 容器顺序执行且先于普通容器完成，故不与普通容器叠加；但单个 init
    容器可能比普通容器之和更大，那时以它为准。overhead 是 RuntimeClass 的
    固定开销，恒叠加。

    漏算这两项会**低估 requests**，而预订率是 EKS 分析的核心结论
    （且它不依赖 Container Insights），低估会直接得出错误的机型建议。
    """
    spec = pod.get("spec") or {}
    def req(c, key):
        return ((c.get("resources") or {}).get("requests") or {}).get(key)
    regular_cpu = sum(_cpu_cores(req(c, "cpu")) for c in spec.get("containers") or [])
    regular_mem = sum(_mem_gib(req(c, "memory")) for c in spec.get("containers") or [])
    init_cpu = max((_cpu_cores(req(c, "cpu")) for c in spec.get("initContainers") or []),
                   default=0.0)
    init_mem = max((_mem_gib(req(c, "memory")) for c in spec.get("initContainers") or []),
                   default=0.0)
    oh = spec.get("overhead") or {}
    return (max(regular_cpu, init_cpu) + _cpu_cores(oh.get("cpu")),
            max(regular_mem, init_mem) + _mem_gib(oh.get("memory")))


def booking_rates(clusters):
    """逐集群算预订率。**不得跨集群汇总**——不同集群的节点池互不调度，
    混算会掩盖单个集群的错配。"""
    out = {}
    for c in clusters:
        ac = sum(_cpu_cores((n.get("allocatable") or {}).get("cpu")) for n in c.get("nodes") or [])
        am = sum(_mem_gib((n.get("allocatable") or {}).get("memory")) for n in c.get("nodes") or [])
        rc = rm = 0.0
        for p in c.get("pods") or []:
            pc, pm = pod_requests(p)
            rc += pc
            rm += pm
        out[c["name"]] = {
            "alloc_cpu": round(ac, 3), "alloc_gib": round(am, 3),
            "req_cpu": round(rc, 3), "req_gib": round(rm, 3),
            "cpu_pct": round(rc / ac * 100, 1) if ac else None,
            "mem_pct": round(rm / am * 100, 1) if am else None,
            "pods": len(c.get("pods") or []),
        }
    return out
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
python3 -m pytest tests/test_eks_requests.py -q 2>&1 | tail -3
```
Expected: `4 passed`

- [ ] **Step 6: 用真实集群验证，并与旧算法对比**

```bash
KCDIR=$(mktemp -d); KC="$KCDIR/config"; trap 'rm -rf "$KCDIR"' EXIT
C=$(aws eks list-clusters --region us-west-2 --query 'clusters[0]' --output text)
aws eks update-kubeconfig --region us-west-2 --name "$C" --kubeconfig "$KC" >/dev/null
export KUBECONFIG="$KC"
kubectl get nodes -o json > /tmp/n.json
kubectl get pods --all-namespaces -o json > /tmp/p.json
python3 - <<'PY'
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() /
  "Documents/git/aws-cost-optimization-skill/aws-rightsizing/references"))
import core
nodes = json.load(open("/tmp/n.json"))["items"]
pods = [p for p in json.load(open("/tmp/p.json"))["items"]
        if p.get("status", {}).get("phase") == "Running"]
r = core.booking_rates([{"name": "live", "nodes": [{"allocatable": n["status"]["allocatable"]}
                                                   for n in nodes], "pods": pods}])["live"]
print("  新算法:", r)
old_cpu = sum(core._cpu_cores(((c.get("resources") or {}).get("requests") or {}).get("cpu"))
              for p in pods for c in p["spec"]["containers"])
print(f"  旧算法(仅普通容器) req_cpu={round(old_cpu,3)}  新={r['req_cpu']}  "
      f"差={round(r['req_cpu']-old_cpu,3)} 核")
PY
```
Expected: 打印两者对比。若差值 > 0，说明该集群确有 init container 或 overhead，
旧算法在低估——把实测数字记进 Step 7 的文档。若差值为 0，说明该集群无这两项，
**仍要保留实现**（其他集群会有），并在文档标注本次未观察到。

- [ ] **Step 7: 更新 `cli-recipes.md` 的 EKS 段**

在 §4.1 之后追加：

````markdown
### §4.1b requests 必须走 `core.py` 的 `pod_requests()`

**不要自己 sum 容器 requests。** K8s 的调度用量是：

```
max(Σ 普通容器, 各 init 容器的最大值) + pod overhead
```

init 容器顺序执行且先于普通容器完成，故**不与普通容器叠加**；但单个 init 容器
可能大于普通容器之和，那时以它为准。overhead 是 RuntimeClass 固定开销，恒叠加。

漏算这两项会**低估 requests**，而预订率是 EKS 分析里唯一不依赖
Container Insights 的核心结论，低估会直接推出错误的机型建议。

### §4.1c 多集群必须逐个算，不得汇总

```bash
for C in $(aws eks list-clusters --region "$R" --query 'clusters[]' --output text); do
  KCDIR=$(mktemp -d); KC="$KCDIR/config"
  aws eks update-kubeconfig --region "$R" --name "$C" --kubeconfig "$KC" >/dev/null
  KUBECONFIG="$KC" kubectl get nodes -o json > "$IV/k8s-nodes-$C.json"
  KUBECONFIG="$KC" kubectl get pods --all-namespaces -o json > "$IV/k8s-pods-$C.json"
  rm -rf "$KCDIR"
done
```

不同集群的节点池互不调度，**跨集群汇总预订率会掩盖单个集群的错配**。
`core.booking_rates()` 接收集群数组并逐个返回，不提供汇总口径。
````

- [ ] **Step 8: Commit**

```bash
git add aws-rightsizing/references/core.py aws-rightsizing/references/cli-recipes.md aws-rightsizing/tests/
git commit -m "fix: EKS requests include init containers and pod overhead

Requests were summed across regular containers only, which understates what the
scheduler actually reserves: it takes the max of the regular sum and the largest
init container, then adds pod overhead. Understating requests corrupts the booking
rate, which is the one EKS conclusion that needs no Container Insights, so a wrong
figure there yields a wrong instance-family recommendation.

Booking rate is now computed per cluster and the collection recipe iterates all
clusters rather than the first. Node pools do not schedule across clusters, so an
aggregate would mask a single cluster's mismatch."
```

---

## Task 5: 补全 sample，串起端到端自检

**Files:**
- Modify: `aws-rightsizing/references/sample-solve.md`
- Modify: `aws-rightsizing/SKILL.md`
- Create: `aws-rightsizing/tests/test_sample_reproduces.py`

**Interfaces:**
- Consumes: Task 1–4 的全部产出。
- Produces: 一条端到端断言：sample 里记录的输出必须由当前代码重新产生。

- [ ] **Step 1: 写失败测试**

`aws-rightsizing/tests/test_sample_reproduces.py`：

```python
import pathlib, re, subprocess, sys, json
ROOT = pathlib.Path(__file__).parent.parent

def test_sample_verdicts_all_reachable():
    """sample-solve.md 记录的四个 verdict 必须由当前 core.py 重新产生。

    少任何一个都说明有分支不可达——本 skill 曾因 jq 生成器语义
    让 spec-unknown 分支完全死掉，未知机型静默从报告消失。
    """
    doc = (ROOT / "references" / "sample-solve.md").read_text()
    m = re.search(r"```json\n(\[.*?\])\n```", doc, re.S)
    assert m, "sample-solve.md 缺少输入 JSON 块"
    resources = json.loads(m.group(1))
    ctx = {"sizing_profile": "aggressive",
           "specs": [{"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
                      "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True},
                     {"t": "m5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
                      "arch": "x86_64", "store": False, "ebs": 143.75, "curgen": True}],
           "prices": {"m5.large|RunInstances": 0.124, "m5.xlarge|RunInstances": 0.248},
           "baseline_pct": {}, "categories": {"m5.large": "General purpose",
                                              "m5.xlarge": "General purpose"},
           "offerings": ["m5.large", "m5.xlarge"], "legacy_families": [],
           "resources": resources}
    out = subprocess.run([sys.executable, str(ROOT / "references" / "core.py")],
                         input=json.dumps(ctx), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    findings = json.loads(out.stdout)
    assert len(findings) == len(resources), "输入输出行数不等：存在静默丢行"
    got = {f["verdict"] for f in findings}
    assert got == {"downsize", "metric-missing", "spec-unknown", "insufficient-data"}, got
```

- [ ] **Step 2: 运行，确认失败**

```bash
python3 -m pytest tests/test_sample_reproduces.py -q 2>&1 | tail -5
```
Expected: FAIL（`sizing_profile` 路径未接通，或 verdict 集合不符）

- [ ] **Step 3: 修 sample 使其自洽**

`sample-solve.md` 的「调用」节改为：

```bash
# thresholds 省略时由 core.py 按 sizing_profile 从 thresholds.json 加载
jq -n --slurpfile sp specs/ec2-types.json --argjson price "$PRICE_KEYED" \
   --argjson cat "$CAT_MAP" --argjson off "$OFFERINGS" \
   --slurpfile bp references/baseline-pct.json \
   --slurpfile lf references/legacy-families.json \
   --slurpfile rs solver-in.json \
   '{sizing_profile:"aggressive", specs:$sp[0], prices:$price, categories:$cat,
     offerings:$off, baseline_pct:$bp[0], legacy_families:$lf[0], resources:$rs[0]}' \
| python3 references/core.py > findings.json
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```
Expected: 全部通过（Task 1–5 的测试合计）

- [ ] **Step 5: `SKILL.md` 增测试入口**

在「护栏」节末尾追加：

```markdown
- **改动 `core.py` 或任何 `references/*.json` 后必须跑测试**：

```bash
cd aws-rightsizing && python3 -m pytest tests/ -q
```

  五组断言分别防：阈值键缺失、散文复述常量、CSV 契约与实现漂移、
  EKS requests 低估、sample 里的 verdict 分支不可达。
  **这些是本 skill 全部反复出错点的固化**，不要跳过。
```

- [ ] **Step 6: 全量回归 + 打包**

```bash
cd ~/Documents/git/aws-cost-optimization-skill/aws-rightsizing
python3 -m pytest tests/ -q 2>&1 | tail -3
for j in references/*.jq; do jq 'empty' -f "$j" </dev/null 2>&1 | grep -q error && echo "JQ FAIL $j"; done
python3 -c "import ast;ast.parse(open('references/core.py').read());print('core.py OK')"
cd /tmp/rs-build/run && python3 ~/Documents/git/aws-cost-optimization-skill/aws-rightsizing/references/core.py \
  < /tmp/core-in2.json | jq -r '(map(.nb_save_mo//0)|add)*100|round/100'
```
Expected: 测试全绿、jq 无报错、`core.py OK`、真实机队合计为 `401.51`
（本行原写 `527.15`，已撤回——上面命令里的 `/tmp/core-in2.json` 是那份失效 fixture，
原因见文件开头的补注。**机队合计改跑 `python3 tests/test_regression_fleet.py`**。）

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "test: five assertions covering every recurring failure mode

Adds the missing test layer. Each assertion corresponds to a defect that actually
shipped here: a threshold key absent from the JSON, a constant restated in prose
and drifting from code, the CSV contract diverging from core.py after the
refactor, EKS requests understated by omitting init containers, and a verdict
branch made unreachable by jq generator semantics so unknown instance types
vanished from reports silently. The live-fleet total is asserted unchanged at
527.15."
```

---

## Self-Review

**1. Spec coverage**

| Review 发现的问题 | 对应 Task |
|---|---|
| 阈值散在 4–5 个文件 | 1（抽 JSON）、2（散文改引用 + lint） |
| `core.py` 不读阈值文件 | 1 |
| `idle_cpu_p95` 等只存在于 `core.py` | 1 |
| CSV 契约与实现不符 | 3 |
| EKS requests 低估 + 单集群 | 4 |
| 无测试层 | 1–5 各自带测试，5 汇总入口 |

未纳入本计划、需另行决定的：`SKILL.md` 486 行 / `cli-recipes.md` 963 行的整体瘦身。
Task 2 只删数值不重构结构——重构应在数值收拢稳定之后单独做，否则两种改动混在
一次会难以判断回归来源。

**2. Placeholder scan**

无 TBD / TODO。每个代码步骤都是可直接粘贴运行的完整内容。Task 4 Step 6 的预期
结果写明了"差值为 0 时如何处理"，不留判断空白。

**3. Type consistency**

- `load_thresholds(profile, path, override)` 定义于 Task 1 Step 4，被 Task 3 测试与 Task 5 调用。
- `pod_requests(pod) -> (float, float)` 定义于 Task 4 Step 4，被同任务 Step 6 与测试调用。
- `booking_rates(clusters) -> dict` 同上；键名 `alloc_cpu` / `req_cpu` / `cpu_pct` 在测试与文档中一致。
- `core.evaluate()` 输出键名在 Task 3 的契约块与测试里逐一列出，与现有实现一致（18 个）。
- `thresholds.json` 的 18 个键在 Task 1 Step 1 测试、Step 3 数据、Task 2 Step 3 文档表格中三处一致。
