# 计价正确性（子项目 A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gp2→gp3 按 `AWS/EBS` 实测 IOPS / 吞吐对齐并扣除另配费用、专用租户在 `core.py` 里判 `price-unknown`、Spot 披露、公有 IPv4 按 `group` 取价。

**Architecture:** 判据性的计算全部进 `references/core.py`（新增 `gp2_capability()` / `gp3_tput_price_per_mibps()` / `gp3_plan()`，`evaluate()` 加租户判定）；采集侧的 reshape 进三个新的小 `.jq` 文件，各自可被测试直接执行；散文（SKILL.md、cli-recipes、report-template、metrics-catalog、method-explained.html）只引用键名与函数名。

**Tech Stack:** Python 3 标准库、jq、AWS CLI v2（只读）、Markdown / HTML。

**Spec:** `docs/specs/2026-10-04-pricing-correctness-design.md`（C1–C6；本计划的每个 Task 都标出对应的 C 编号）

## Global Constraints

- AWS 调用只许 `describe*` / `list*` / `get*` 与 `pricing:GetProducts`；禁止 `ce:*`、任何账单 API、任何 mutating 调用；不调 Compute Optimizer / Cost Optimization Hub 的开通接口。
- 金额一律按需理论值（`SKILL.md`「价格口径」）；Spot 照按需价计，只披露。
- 阈值数值只在 `references/thresholds.json`；`SKILL.md`、`references/*.md`、`references/*.jq` 只写键名，**同一行不得同时出现键名与其值**（`tests/test_no_duplicated_constants.py`）。
- 缺失一律 `None` / `null`；禁止 Python 的 `or`、jq 的 `//` 兜底会吞掉 `0` 的值（`core.py` 文件头的「缺失值语义」）。
- 每个测试文件以 `python3 <file>` 运行时打印 `n/n passed`，且 n 等于该文件 `test_*` 函数个数（`tests/test_gate_covers_every_test.py`）。
- 本 repo 公开：任何文件不得出现账号 ID、实例 ID、卷 ID、含用户名的本机路径、profile 名（`tests/test_no_private_data.py`）。
- 文档与注释用中文，沿用现有文件的写法。
- **不执行 `git commit` / `git push`**（项目 CLAUDE.md）。每个 Task 的收尾是检查点：`git status --short` 核对改动范围。
- 改了 `SKILL.md` 或 `references/` 后，必须同步 `../README.md` 与 `../README_CN.md`（项目 CLAUDE.md）。
- 只读验证用的 AWS profile 由用户指定（本轮为验证账号的只读调用）；该 profile 名不写进任何文件。

## Review Focus

1. **卷在窗口内换过宿主**：`list-metrics` 会同时回旧宿主与新宿主两条 `VolumeId+InstanceId` 序列，`mdq-dims.jq` 的 Label 只编卷 ID ⇒ 撞名、重复 Label 断言阻断整批。期望：只查当前挂载那条。由 Task 3 的 `test_attach_filter_keeps_only_the_current_attachment` 钉住。
2. **取价回包同一 productFamily 多条**（Local Zone / Outposts 混入）：期望该单价为 `null` ⇒ 整批 gp2 行 `price-unknown`，绝不取第一条。由 Task 3 的 `test_price_builder_refuses_ambiguous_families` 钉住。
3. **`mean × n` 的浮点残差**：触顶小时数要进 blocker 文案，期望是整数而不是 `27.000000000000004`。由 Task 3 的 `test_vol_inputs_take_the_full_window_band_and_keep_zero` 钉住。
4. **Avg 序列在、触顶序列缺**：期望按 gp2 能力对齐（看不见秒级突发），不按分钟均值定档。由 Task 1 的 `test_exceeded_series_missing_alone_still_means_parity` 钉住。
5. **旧版 solver-in 不带 tenancy / lifecycle**：期望按 AWS 默认（共享、按需）计价、结论不变、多一条 blocker。由 Task 2 的 `test_missing_tenancy_lifecycle_keys_default_and_say_so` 钉住。

---

### Task 1: `core.gp3_plan()` 与两个新阈值键（spec C2、C3）

**Files:**
- Create: `tests/test_gp3_plan.py`
- Modify: `references/core.py`（在 `booking_rates()` 之后、`# 分派：service → 判据` 那段注释之前插入新段）
- Modify: `references/thresholds.json`（两个 profile 各加两键）
- Modify: `references/thresholds.md`（solver 阈值表末尾加两行）

**Interfaces:**
- Consumes: `core.load_thresholds(profile)`、`core._ceil_div`、`core._n`、`core.VETO_TOLERANCE_PCT`（均已存在）
- Produces:
  - `core.gp2_capability(size_gib: int) -> tuple[int, int]` —— `(iops_cap, mibps_cap)`
  - `core.gp3_tput_price_per_mibps(usd: float | None, unit: str | None) -> float | None`
  - `core.gp3_plan(vol: dict, t: dict, price: dict) -> dict`
    - `vol` 键：`rid, size_gib, sus_iops, peak_iops, sus_kibs, peak_kibs, iops_exceeded_p95, iops_exceeded_hours, tput_exceeded_p95, tput_exceeded_hours`
    - `price` 键：`gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_mibps_mo`
    - 返回键：`rid, service("ebs"), cur("gp2"), gp3_iops, gp3_mibps, iops_basis, tput_basis, cur_cost_mo, gp3_cost_mo, other_save_mo, verdict, bucket, action_type, blockers`
    - `*_basis` 取值：`measured` / `exceeded-parity` / `missing-parity`
    - 三种出口：`(excluded, downsize, storage-type)`、`(excluded, excluded, none)`、`(price-unknown, excluded, none)`

- [ ] **Step 1: 写失败测试 `tests/test_gp3_plan.py`**

```python
"""gp2 → gp3：按 AWS/EBS 实测 IOPS / 吞吐对齐（`core.gp3_plan()`）。

守三类错（spec: docs/specs/2026-10-04-pricing-correctness-design.md）：
  ① 阈值写错维度 —— 334 GiB 是吞吐分界点，1000 GiB 才是 IOPS 分界点；
  ② 只扣存储差价 —— 为不降性能另配的 IOPS / 吞吐费要从节省额里扣；
  ③ 「出现过一次触顶就对齐」—— 一次几秒的高峰决定一块卷有没有建议。
另守两条单位 / 缺失语义：吞吐单价按 GiBps-mo 计；0 是有效值不是缺失。
"""
import json, pathlib, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).parent.parent
REF = ROOT / "references"
sys.path.insert(0, str(REF))
import core

T_AGG = core.load_thresholds("aggressive")
T_CON = core.load_thresholds("conservative")
# us-west-2 实测单价（观测值 @2026-10-04）；吞吐已按 GiBps-mo ÷ 1024 换成每 MiB/s
PRICE = {"gp2_gb_mo": 0.10, "gp3_gb_mo": 0.08, "gp3_iops_mo": 0.005,
         "gp3_mibps_mo": 0.04}


def _vol(size, **kw):
    """一块挂在 Nitro 实例上、用量很低、从未触顶的 gp2 卷；kw 覆盖任意字段。"""
    v = {"rid": "vol-EX", "size_gib": size, "sus_iops": 1.0, "peak_iops": 300.0,
         "sus_kibs": 512.0, "peak_kibs": 8192.0,
         "iops_exceeded_p95": 0, "iops_exceeded_hours": 0,
         "tput_exceeded_p95": 0, "tput_exceeded_hours": 0}
    v.update(kw)
    return v


def test_capability_tiers_follow_the_aws_table():
    """gp2 能力上限按 AWS EBS 用户指南逐档：IOPS 3/GiB、< 1000 GiB 可突发到 3000、
    5,334 GiB 起封顶 16,000；吞吐 ≤ 170 GiB 最高 128 MiB/s、以上 250 MiB/s。"""
    want = {8: (3000, 128), 170: (3000, 128), 171: (3000, 250), 334: (3000, 250),
            1000: (3000, 250), 1001: (3003, 250), 5334: (16000, 250),
            6000: (16000, 250)}
    got = {s: core.gp2_capability(s) for s in want}
    assert got == want, got


def test_low_usage_stays_at_gp3_baseline_and_saves_the_storage_difference():
    out = core.gp3_plan(_vol(80), T_AGG, PRICE)
    assert (out["gp3_iops"], out["gp3_mibps"]) == (3000, 125), out
    assert (out["iops_basis"], out["tput_basis"]) == ("measured", "measured"), out
    assert out["cur_cost_mo"] == 8.0 and out["gp3_cost_mo"] == 6.4, out
    assert out["other_save_mo"] == 1.6, out
    assert (out["verdict"], out["bucket"], out["action_type"]) == (
        "excluded", "downsize", "storage-type"), out


def test_throughput_at_the_gp2_limit_is_capped_not_upgraded():
    """验证账号 5 块 20 GiB 节点卷的分钟峰值 129–130 MiB/s（顶在 gp2 的 128 上）。
    反推需求 > 128 也只配到 128：迁移承诺「不比现在差」，不是升级。"""
    out = core.gp3_plan(_vol(20, peak_kibs=130.2 * 1024), T_AGG, PRICE)
    assert out["gp3_mibps"] == 128 and out["tput_basis"] == "measured", out
    assert out["gp3_cost_mo"] == round(20 * 0.08 + 3 * 0.04, 2), out
    assert out["other_save_mo"] == round(20 * 0.10 - (20 * 0.08 + 3 * 0.04), 2), out


def test_persistent_throughput_exceeded_forces_parity_and_can_erase_the_row():
    """持续触顶（p95 ≥ 1）⇒ 对齐 gp2 能力。200 GiB 卷要多配 125 MiB/s（$5），
    存储差价只有 $4 ⇒ 不出转换行，按「EBS 卷 其他」填。"""
    out = core.gp3_plan(_vol(200, tput_exceeded_p95=1, tput_exceeded_hours=60),
                        T_AGG, PRICE)
    assert out["gp3_mibps"] == 250 and out["tput_basis"] == "exceeded-parity", out
    assert out["gp3_iops"] == 3000 and out["iops_basis"] == "measured", out
    assert out["other_save_mo"] is None, out
    assert (out["verdict"], out["bucket"], out["action_type"]) == (
        "excluded", "excluded", "none"), out
    assert any("60 小时" in b for b in out["blockers"]), out["blockers"]


def test_occasional_exceeded_sizes_from_measurement_and_says_so():
    """偶发触顶（p95 = 0、小时数 > 0）⇒ 照常按实测定档，blocker 写出小时数。
    T1 普查：14 块卷里 12 块有触顶小时（2–27 / 720），0 块超过 5%。"""
    out = core.gp3_plan(_vol(200, tput_exceeded_p95=0, tput_exceeded_hours=27),
                        T_AGG, PRICE)
    assert out["gp3_mibps"] == 125 and out["tput_basis"] == "measured", out
    assert out["other_save_mo"] == 4.0, out
    assert any("27 小时" in b and "偶发" in b for b in out["blockers"]), out["blockers"]


def test_missing_metrics_fall_back_to_gp2_parity():
    """非 Nitro 宿主不发布 VolumeAvg* / *ExceededCheck ⇒ 两个维度都对齐 gp2 能力。"""
    v = _vol(1500, sus_iops=None, peak_iops=None, sus_kibs=None, peak_kibs=None,
             iops_exceeded_p95=None, iops_exceeded_hours=None,
             tput_exceeded_p95=None, tput_exceeded_hours=None)
    out = core.gp3_plan(v, T_AGG, PRICE)
    assert (out["gp3_iops"], out["gp3_mibps"]) == (4500, 250), out
    assert (out["iops_basis"], out["tput_basis"]) == (
        "missing-parity", "missing-parity"), out
    want = round(1500 * 0.10 - (1500 * 0.08 + 1500 * 0.005 + 125 * 0.04), 2)
    assert out["other_save_mo"] == want == 17.5, out


def test_exceeded_series_missing_alone_still_means_parity():
    """Avg 序列在、触顶序列缺 ⇒ 看不见秒级突发 ⇒ 对齐，不按分钟均值定档。"""
    out = core.gp3_plan(_vol(400, tput_exceeded_p95=None, tput_exceeded_hours=None),
                        T_AGG, PRICE)
    assert out["gp3_mibps"] == 250 and out["tput_basis"] == "missing-parity", out
    assert out["gp3_iops"] == 3000 and out["iops_basis"] == "measured", out


def test_large_volume_iops_measured_above_baseline():
    """> 1000 GiB 才可能需要另配 IOPS（官方迁移表：对齐 gp2，或实测最大 IOPS）。"""
    out = core.gp3_plan(_vol(2000, sus_iops=2000.0, peak_iops=5100.0), T_AGG, PRICE)
    # aggressive：max(ceil(2000/0.60), ceil(5100/0.85)) = max(3334, 6000)；能力上限 6000
    assert out["gp3_iops"] == 6000 and out["iops_basis"] == "measured", out
    assert out["gp3_cost_mo"] == round(2000 * 0.08 + 3000 * 0.005, 2), out


def test_conservative_profile_provisions_more_than_aggressive():
    v = _vol(3000, sus_iops=3500.0, peak_iops=5000.0)
    a, c = core.gp3_plan(v, T_AGG, PRICE), core.gp3_plan(v, T_CON, PRICE)
    assert c["gp3_iops"] > a["gp3_iops"], (a["gp3_iops"], c["gp3_iops"])


def test_zero_usage_is_a_value_not_missing():
    """0 是有效值（零 IO 的卷），不得被当成缺失而走对齐兜底。"""
    v = _vol(500, sus_iops=0.0, peak_iops=0.0, sus_kibs=0.0, peak_kibs=0.0)
    out = core.gp3_plan(v, T_AGG, PRICE)
    assert (out["iops_basis"], out["tput_basis"]) == ("measured", "measured"), out
    assert (out["gp3_iops"], out["gp3_mibps"]) == (3000, 125), out
    assert not any("偶发" in b for b in out["blockers"]), out["blockers"]


def test_any_missing_price_is_price_unknown_without_savings():
    for k in PRICE:
        out = core.gp3_plan(_vol(100), T_AGG, dict(PRICE, **{k: None}))
        assert out["verdict"] == "price-unknown", (k, out)
        assert out["other_save_mo"] is None and out["bucket"] == "excluded", (k, out)
        assert out["action_type"] == "none", (k, out)
    out = core.gp3_plan(_vol(100), T_AGG, dict(PRICE, gp3_iops_mo=None))
    assert out["cur_cost_mo"] == 10.0, out   # gp2 单价在就照填当前月额


def test_throughput_price_unit_must_be_gibps():
    """实测 gp3 吞吐单价 $40.96 / GiBps-mo = $0.04 / MiBps-mo。当成每 MiB/s 会高估
    1024 倍；单位对不上就按缺失处理，不猜换算。"""
    assert abs(core.gp3_tput_price_per_mibps(40.96, "GiBps-mo") - 0.04) < 1e-12
    assert core.gp3_tput_price_per_mibps(40.96, "MiBps-mo") is None
    assert core.gp3_tput_price_per_mibps(None, "GiBps-mo") is None


def test_gp3_ratio_limits_hold_on_every_parity_path():
    """吞吐 / IOPS ≤ 0.25 与另配 IOPS ≤ 500 × 容量：本设计取值域内恒成立，
    gp3_plan 里的断言防将来改上限时越界。这里把对齐路径跑遍 gp2 的容量范围。"""
    missing = dict(sus_iops=None, peak_iops=None, sus_kibs=None, peak_kibs=None)
    for size in (1, 8, 170, 171, 334, 999, 1000, 1001, 5334, 16384):
        out = core.gp3_plan(_vol(size, **missing), T_AGG, PRICE)
        assert out["gp3_mibps"] <= 0.25 * out["gp3_iops"], out


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"✓ {test_fn.__name__}")
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
```

（`json` / `subprocess` / `tempfile` 在 Task 3 追加的测试里才用到，这里先 import。）

- [ ] **Step 2: 运行，确认失败**

Run: `cd aws-rightsizing && python3 tests/test_gp3_plan.py`
Expected: 13 条全部 `✗ ... module 'core' has no attribute 'gp2_capability'`（或 `gp3_plan` / `gp3_tput_price_per_mibps`），末行 `0/13 passed`。

- [ ] **Step 3: `thresholds.json` 两个 profile 各加两键**

在 `"aggressive"` 段 `"ceiling_mem_max": 85,` 之后插入：

```json
      "target_ebs_p95": 60,
      "ceiling_ebs_max": 85,
```

在 `"conservative"` 段 `"ceiling_mem_max": 70,` 之后插入：

```json
      "target_ebs_p95": 40,
      "ceiling_ebs_max": 60,
```

（初值取同 profile 的 CPU 两键，spec C3。）

- [ ] **Step 4: `core.py` 加新段**

在 `booking_rates()` 的 `return out` 之后、`# ============================================================\n# 分派：service → 判据` 之前插入：

```python
# ============================================================
# EBS gp2 → gp3：按 AWS/EBS 实测 IOPS / 吞吐对齐
# ============================================================
# 下列数值是 gp2 / gp3 的产品定义（AWS EBS 用户指南），属稳定事实，不是可按
# profile 调的策略量，故不进 thresholds.json —— 与 VETO_TOLERANCE_PCT 同类。
GP3_BASE_IOPS = 3000          # gp3 基线 IOPS，含在存储价里
GP3_BASE_MIBPS = 125          # gp3 基线吞吐，含在存储价里
GP3_MIBPS_PER_IOPS = 0.25     # gp3 吞吐 / IOPS 比的上限
GP3_MAX_IOPS_PER_GIB = 500    # gp3 另配 IOPS / 容量比的上限
GP2_IOPS_PER_GIB = 3          # gp2 基线 IOPS
GP2_BURST_IOPS = 3000         # gp2 < 1000 GiB 时的突发上限
GP2_MAX_IOPS = 16000          # gp2 IOPS 封顶（5,334 GiB 起）
GP2_SMALL_GIB = 170           # ≤ 此容量的 gp2 吞吐最高 128 MiB/s
GP2_SMALL_MIBPS = 128
GP2_MAX_MIBPS = 250           # > 170 GiB 的 gp2 吞吐上限（170–334 GiB 靠突发积分）


def gp2_capability(size_gib):
    """gp2 卷能达到的上限 (IOPS, MiB/s)。gp3 的配置以它封顶：迁移承诺「不比现在差」，
    不是升级 —— 超出 gp2 能力的需求在 gp2 上本来就没有被满足。

    **334 GiB 是吞吐的分界点，不是 IOPS 的。** 此前 SKILL.md 写「> 334 GiB 时基线
    IOPS 已超 3000」，照做会让 334–1000 GiB 的卷去配 IOPS（白花钱）而吞吐照样从
    250 掉到 125。基线 IOPS 要到 1000 GiB 才超 3000。
    """
    iops = min(GP2_MAX_IOPS, max(GP2_BURST_IOPS, GP2_IOPS_PER_GIB * size_gib))
    mibps = GP2_SMALL_MIBPS if size_gib <= GP2_SMALL_GIB else GP2_MAX_MIBPS
    return iops, mibps


def gp3_tput_price_per_mibps(usd, unit):
    """gp3 另配吞吐的单价换成「每 MiB/s 每月」。

    pricing API 回的单位是 **GiBps-mo**（实测 us-west-2 $40.96 / GiBps-mo，描述字段原文
    「$0.04 per provisioned MiBps-month」）。直接当成每 MiB/s 的价会高估 1024 倍。
    单位不是 GiBps-mo ⇒ None（按缺失处理），不猜换算。
    """
    if usd is None or unit != "GiBps-mo":
        return None
    return usd / 1024


def _gp3_dim(sus, peak, ex_p95, ex_hours, base, cap, t, label, unit):
    """一个维度（IOPS 或吞吐）的 gp3 配置量。返回 (配置量, 依据, blocker 或 None)。

    顺序不可调换：缺失 ⇒ 对齐；持续触顶 ⇒ 对齐；否则按实测。
    「持续触顶」= 触顶序列（小时 Maximum）的 p95 ≥ 1，与否决项同一个持续态口径
    （`_persistent()`，容忍度 VETO_TOLERANCE_PCT）。「出现过一次即对齐」在验证账号
    14 块卷里命中 12 块（每块 2–27 / 720 小时），会让一次备份的几秒高峰决定一块卷
    有没有建议。分钟均值看不见秒级突发：触顶分钟的分钟均值实测只有 382–488 IOPS。
    按实测时与 `_required()` 同形：持续项对 target_ebs_p95、峰值项对 ceiling_ebs_max 反推。
    """
    if sus is None or peak is None or ex_p95 is None:
        return cap, "missing-parity", (
            f"{label} 指标缺失（非 Nitro 宿主不发布 VolumeAvg* 与 *ExceededCheck），"
            f"按 gp2 能力上限 {_n(cap)} {unit} 对齐")
    if ex_p95 >= 1:
        return cap, "exceeded-parity", (
            f"{label} 持续触顶：超过 {VETO_TOLERANCE_PCT}% 的小时出现秒级触顶"
            f"（共 {_n(ex_hours)} 小时），分钟均值被 gp2 上限压低、不可作定档依据，"
            f"按 gp2 能力上限 {_n(cap)} {unit} 对齐")
    need = max(_ceil_div(sus * 100, t["target_ebs_p95"]),
               _ceil_div(peak * 100, t["ceiling_ebs_max"]))
    note = None
    if ex_hours:
        note = (f"{label} 偶发触顶：窗口内 {_n(ex_hours)} 小时出现秒级触顶，未超过 "
                f"{VETO_TOLERANCE_PCT}% 的小时，按实测定档；gp3 的 {label} 可在线调高、不停机")
    return min(cap, max(base, need)), "measured", note


def gp3_plan(vol, t, price):
    """一块 gp2 卷转 gp3 的配置量与按需理论月省。填法表 gp2 行的金额来源。

    vol   = {rid, size_gib, sus_iops, peak_iops, sus_kibs, peak_kibs,
             iops_exceeded_p95, iops_exceeded_hours,
             tput_exceeded_p95, tput_exceeded_hours}   —— 缺失一律 None，禁止补 0
    t     = load_thresholds(profile)
    price = {gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_mibps_mo}   —— 缺失为 None

    三种出口与填法表三行一一对应：可转（downsize / storage-type）、转了不省
    （excluded / none，按「EBS 卷 其他」填）、单价不全（price-unknown）。
    """
    size = vol["size_gib"]
    cap_iops, cap_mibps = gp2_capability(size)

    def kib(v):
        return None if v is None else v / 1024

    iops, iops_basis, n1 = _gp3_dim(
        vol.get("sus_iops"), vol.get("peak_iops"), vol.get("iops_exceeded_p95"),
        vol.get("iops_exceeded_hours"), GP3_BASE_IOPS, cap_iops, t, "IOPS", "IOPS")
    mibps, tput_basis, n2 = _gp3_dim(
        kib(vol.get("sus_kibs")), kib(vol.get("peak_kibs")),
        vol.get("tput_exceeded_p95"), vol.get("tput_exceeded_hours"),
        GP3_BASE_MIBPS, cap_mibps, t, "吞吐", "MiB/s")
    assert mibps <= GP3_MIBPS_PER_IOPS * iops, (vol["rid"], iops, mibps)
    assert iops == GP3_BASE_IOPS or iops <= GP3_MAX_IOPS_PER_GIB * size, (
        vol["rid"], iops, size)
    out = {"rid": vol["rid"], "service": "ebs", "cur": "gp2",
           "gp3_iops": iops, "gp3_mibps": mibps,
           "iops_basis": iops_basis, "tput_basis": tput_basis,
           "cur_cost_mo": None, "gp3_cost_mo": None, "other_save_mo": None,
           "blockers": [n for n in (n1, n2) if n]}
    if price.get("gp2_gb_mo") is not None:
        out["cur_cost_mo"] = round(size * price["gp2_gb_mo"], 2)
    keys = ("gp2_gb_mo", "gp3_gb_mo", "gp3_iops_mo", "gp3_mibps_mo")
    missing = [k for k in keys if price.get(k) is None]
    if missing:
        out.update(verdict="price-unknown", bucket="excluded", action_type="none")
        out["blockers"].insert(0, (
            f"gp2 / gp3 单价不全（{'、'.join(missing)} 缺失），不出节省额。"
            f"即使这块卷不需另配也要求四个单价齐全：取价按 region 一次取回，"
            f"缺一条说明取价配方坏了"))
        return out
    gp3 = (size * price["gp3_gb_mo"]
           + (iops - GP3_BASE_IOPS) * price["gp3_iops_mo"]
           + (mibps - GP3_BASE_MIBPS) * price["gp3_mibps_mo"])
    save = round(size * price["gp2_gb_mo"] - gp3, 2)
    out["gp3_cost_mo"] = round(gp3, 2)
    if save <= 0:
        out.update(verdict="excluded", bucket="excluded", action_type="none")
        out["blockers"].insert(0, (
            f"转 gp3 须另配到 IOPS {_n(iops)} / 吞吐 {_n(mibps)} MiB/s 才不比现在差，"
            f"月额 ${out['gp3_cost_mo']} 不低于 gp2 的 ${out['cur_cost_mo']}，不出转换建议"))
        return out
    out.update(verdict="excluded", bucket="downsize", action_type="storage-type",
               other_save_mo=save)
    out["blockers"].insert(0, (
        f"转 gp3 配置 IOPS {_n(iops)}（依据 {iops_basis}）、吞吐 {_n(mibps)} MiB/s"
        f"（依据 {tput_basis}）；按需理论月省 ${save}"))
    return out
```

- [ ] **Step 5: `thresholds.md` 的 solver 阈值表末尾加两行**

在表的最后一行（`max_mem_reduction_ratio` 那一行）之后插入（**只写键名，不写数值**；放表尾而不是 `ceiling_mem_max` 之后，是因为表下方的散文用「前四项」指代 CPU / 内存四键）：

```markdown
| `target_ebs_p95` | gp2→gp3 另配后，卷的 IOPS / 吞吐持续 p95 占配置量的上限（`core.gp3_plan()`） | 不同，conservative 留更多余量 |
| `ceiling_ebs_max` | gp2→gp3 另配后，卷的 IOPS / 吞吐分钟峰值占配置量的上限 | 不同，conservative 留更多余量 |
```

- [ ] **Step 6: 运行，确认通过**

Run: `python3 tests/test_gp3_plan.py && python3 tests/test_thresholds.py && python3 tests/test_no_duplicated_constants.py`
Expected: `13/13 passed`、`5/5 passed`、该文件全部 passed（新键被 `core.py` 以 `t["..."]` 读到，双向覆盖成立；散文未复述数值）。

- [ ] **Step 7: 检查点**

Run: `git status --short`
Expected: 只有 `references/core.py`、`references/thresholds.json`、`references/thresholds.md`、`tests/test_gp3_plan.py`（及此前的 spec / docs/README.md 改动）。不 commit。

---

### Task 2: 专用租户判 `price-unknown`、Spot 与缺键只披露（spec C5）

**Files:**
- Modify: `references/core.py`（`_eff_vcpu()` 之后加 `_tenancy_lifecycle()`；`evaluate()` 三处）
- Modify: `tests/test_fail_closed_contracts.py`（`RES` / `T_RES` 补键；加 4 个测试并写进 runner 清单）
- Modify: `tests/test_csv_contract.py`（`RES_EC2` 补键）
- Modify: `tests/test_managed_dispatch.py`（`EC2_OK` 补键）
- Modify: `tests/fixtures/regression-fleet.json`（13 行补键 + `_comment` 记出处）
- Modify: `references/sample-solve.md`（两份样例 JSON 的 10 行补键；字段表加两行）

**Interfaces:**
- Consumes: 无新依赖
- Produces: `core._tenancy_lifecycle(res: dict) -> tuple[str | None, list[str]]` —— `(专用租户原因或 None, 披露 blocker 列表)`；EC2 的 `resources` 行新增可选键 `tenancy`（字符串）与 `lifecycle`（字符串或 `null`）

- [ ] **Step 1: 测试 fixture 补默认键（防止既有测试被新 blocker 干扰）**

`tests/test_fail_closed_contracts.py`：`RES` 字典里 `"operation": "RunInstances",` 之后加 `"tenancy": "default", "lifecycle": None,`；`T_RES` 同样。
`tests/test_csv_contract.py`：`RES_EC2` 的 `"operation": "RunInstances",` 之后加 `"tenancy": "default", "lifecycle": None,`。
`tests/test_managed_dispatch.py`：`EC2_OK` 的 `"operation": "RunInstances",` 之后加同样两键。

- [ ] **Step 2: 写失败测试（追加到 `tests/test_fail_closed_contracts.py`，放在 `if __name__` 之前）**

```python
def test_dedicated_tenancy_is_price_unknown_not_downsized():
    """dedicated / host ⇒ price-unknown。SKILL.md 早有这条规则，但此前 solver-in
    不带 tenancy、core.py 看不见它，专用租户实例照样按共享按需价出降配金额。"""
    t = core.load_thresholds("aggressive")
    for ten in ("dedicated", "host"):
        out = _evaluate(dict(RES, rid="i-T-21", cpu_n=243, tenancy=ten), t)
        assert out["verdict"] == "price-unknown", (ten, out)
        assert out.get("nb_save_mo") is None and out.get("cur_cost_mo") is None, (ten, out)
        assert ten in out["burst_na"], (ten, out["burst_na"])


def test_spot_is_priced_on_demand_and_disclosed():
    """Spot 不改金额：价格口径一律按需理论值，Spot 与 RI/SP 同口径，只做披露。"""
    t = core.load_thresholds("aggressive")
    base = _evaluate(dict(RES, rid="i-T-22", cpu_n=243), t)
    spot = _evaluate(dict(RES, rid="i-T-22", cpu_n=243, lifecycle="spot"), t)
    assert spot["verdict"] == base["verdict"], (base, spot)
    assert spot["nb_save_mo"] == base["nb_save_mo"], (base, spot)
    assert any("购买方式为 spot" in b for b in spot.get("blockers") or []), spot


def test_missing_tenancy_lifecycle_keys_default_and_say_so():
    """缺键 ⇒ 按 AWS 默认（共享、按需）计价并记 blocker；结论与带默认值时相同。
    describe-instances 总会返回 Placement.Tenancy，缺键只可能来自组装。"""
    t = core.load_thresholds("aggressive")
    full = _evaluate(dict(RES, rid="i-T-23", cpu_n=243), t)
    bare = {k: v for k, v in dict(RES, rid="i-T-23", cpu_n=243).items()
            if k not in ("tenancy", "lifecycle")}
    out = _evaluate(bare, t)
    assert out["verdict"] == full["verdict"], (full, out)
    assert out["nb_save_mo"] == full["nb_save_mo"], (full, out)
    assert any("组装未带 tenancy / lifecycle" in b for b in out.get("blockers") or []), out
    assert not any("组装未带" in b for b in full.get("blockers") or []), full


def test_insufficient_data_row_carries_cost_only_for_shared_tenancy():
    """insufficient-data 分支会尽力填成本（不填会让分母漏项）；专用租户不填
    （共享价不适用），Spot 照填（按需理论值口径）。"""
    t = core.load_thresholds("aggressive")
    host = core.evaluate(dict(RES, rid="i-T-24", cpu_n=None, tenancy="host"), _ctx(t, []))
    spot = core.evaluate(dict(RES, rid="i-T-25", cpu_n=None, lifecycle="spot"), _ctx(t, []))
    assert host["verdict"] == spot["verdict"] == "insufficient-data", (host, spot)
    assert host.get("cur_cost_mo") is None, host
    assert any("租户为 host" in b for b in host.get("blockers") or []), host
    assert spot.get("cur_cost_mo") is not None, spot
```

再把这 4 个函数名追加进文件末尾 runner 的 `tests = [...]` 清单（清单是手写的；`test_gate_covers_every_test.py` 要求条数相等）。

- [ ] **Step 3: 运行，确认失败**

Run: `python3 tests/test_fail_closed_contracts.py`
Expected: 4 条新测试 `✗`（`price-unknown` 断言、`购买方式为 spot`、`组装未带` 各自失败），其余照旧 `✓`；末行 `20/24 passed`。

- [ ] **Step 4: `core.py` 加 `_tenancy_lifecycle()`（放在 `_eff_vcpu()` 之后、`evaluate()` 之前）**

```python
def _tenancy_lifecycle(res):
    """(专用租户的不取价原因或 None, 披露 blocker 列表)。

    专用租户（dedicated / host）⇒ 不出金额：Dedicated Host 按整台主机计费，
    不合并主机时单台实例降配一分钱都省不下来。SKILL.md 早有这条规则，但此前
    solver-in 不带 tenancy，本文件看不到它 —— 规则只写在文字里。
    非按需购买方式（spot / scheduled / capacity-block）⇒ 金额照按需理论值算：
    本 skill 的价格口径一律按需，Spot 与 RI/SP 同属「实际账单按另一种价计」，
    只做披露、不改金额。
    缺键 ⇒ 取 AWS 默认（共享租户、按需）并记一条 blocker：describe-instances 总会
    返回 Placement.Tenancy、按需实例本就不返回 InstanceLifecycle，缺键只可能来自
    组装 —— cli-recipes.md §7.3 ② 在跑判据前拦下漏字段。
    """
    notes = []
    if "tenancy" not in res or "lifecycle" not in res:
        notes.append("组装未带 tenancy / lifecycle，按 AWS 默认（共享租户、按需）计价")
    ten = res.get("tenancy")
    if ten is None:
        ten = "default"
    life = res.get("lifecycle")
    if life is not None:
        notes.append(f"购买方式为 {life}：金额为按需理论值，实际账单按该方式计")
    if ten == "default":
        return None, notes
    return (f"租户为 {ten}：专用租户按另一种结构计费（Dedicated Host 按整台主机），"
            f"本版本不取价"), notes
```

- [ ] **Step 5: `evaluate()` 三处改动**

① 紧跟 `_coverage_note(out, res)` 之后加：

```python
    # 专用租户不出金额；Spot 与缺键只加披露。理由见 _tenancy_lifecycle 的 docstring。
    dedicated, pricing_notes = _tenancy_lifecycle(res)
    if pricing_notes:
        out.setdefault("blockers", []).extend(pricing_notes)
```

② insufficient-data 分支里，把

```python
        if usd is not None:
            out.update(cur_usd=usd, cur_cat=cats.get(itype),
                       cur_cost_mo=round(usd * HOURS_PER_MONTH
                                         * res.get("count", 1), 2))
        return out
```

改成

```python
        if dedicated is not None:
            # 专用租户的成本不是共享按需价：不填，免得分母按错价计入
            out.setdefault("blockers", []).append(dedicated)
        elif usd is not None:
            out.update(cur_usd=usd, cur_cat=cats.get(itype),
                       cur_cost_mo=round(usd * HOURS_PER_MONTH
                                         * res.get("count", 1), 2))
        return out
```

③ 主路径在 `cur_usd = prices.get(f"{itype}|{res.get('operation')}")` 之前插入：

```python
    if dedicated is not None:
        out["verdict"] = "price-unknown"
        out["burst_na"] = dedicated
        return out
```

- [ ] **Step 6: 回归 fixture 补键（按 spec T3 的证据）**

Run（在 `aws-rightsizing/` 下）：

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("tests/fixtures/regression-fleet.json")
raw = p.read_text(encoding="utf-8")
d = json.loads(raw)
for r in d["resources"]:
    items = list(r.items())
    i = [k for k, _ in items].index("operation") + 1
    items[i:i] = [("tenancy", "default"), ("lifecycle", None)]
    r.clear(); r.update(items)
d["_comment"].append(
    "tenancy / lifecycle（2026-10-04 补）：该次运行的原始 inventory 里 "
    "Placement.Tenancy 13/13 为 default；2026-10-04 复查 12/13 仍在运行，"
    "InstanceLifecycle 全为空（按需）。")
out = json.dumps(d, ensure_ascii=False, indent=1)
p.write_text(out + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
PY
git diff --stat tests/fixtures/regression-fleet.json
```

Expected: 只有补键与 `_comment` 那一行的增量（约 27 行插入），无其他格式变化。

- [ ] **Step 7: `sample-solve.md` 两份样例补键 + 字段表加两行**

Run：

```bash
sed -i '' 's/"operation":"RunInstances",$/"operation":"RunInstances","tenancy":"default","lifecycle":null,/' references/sample-solve.md
grep -c '"tenancy":"default","lifecycle":null' references/sample-solve.md
```

Expected: `10`（输入块 5 行 + 调用示例 5 行）。

再在字段表 `service` 那一行之后插入：

```markdown
| `tenancy` | `Placement.Tenancy` 原值 | 非 `default` ⇒ `price-unknown`（专用租户按另一种结构计费）；缺键 ⇒ 按 `default` 计价并记 blocker |
| `lifecycle` | `InstanceLifecycle` 原值，按需实例为 `null` | 非 `null` ⇒ 金额照按需理论值算并记披露 blocker；缺键 ⇒ 按按需计价并记 blocker |
```

- [ ] **Step 8: 运行，确认通过**

Run：

```bash
for t in tests/test_fail_closed_contracts.py tests/test_regression_fleet.py \
         tests/test_sample_reproduces.py tests/test_csv_contract.py \
         tests/test_managed_dispatch.py; do
  printf '%-46s' "$t"; out=$(python3 "$t") || { echo FAIL; echo "$out" | tail -20; break; }
  echo "$out" | tail -1
done
```

Expected: 每个文件 `n/n passed`；`test_regression_fleet.py` 的 `EXPECTED` 一个数都不用改（补键后无默认值 blocker、无租户分支命中）。

- [ ] **Step 9: 检查点**

Run: `git status --short`
Expected: 新增改动只有上面 Files 列出的 6 个文件。不 commit。

---

### Task 3: 采集与取价的三个 jq + `cli-recipes.md`（spec C1、C5 采集侧、C6）

**Files:**
- Create: `references/lm-ebs-attached.jq`
- Create: `references/ebs-gp3-in.jq`
- Create: `references/ebs-price.jq`
- Modify: `references/cli-recipes.md`（§1 投影；新增 §2.7；§6.1 EBS 取价；公有 IPv4 一节改写；§7.0 字段表；§7.2 组装式；§7.3 必检项 ②）
- Modify: `tests/test_gp3_plan.py`（追加 3 个行为测试）

**Interfaces:**
- Consumes: Task 1 的 `core.gp3_plan()` / `core.gp3_tput_price_per_mibps()`；既有 `references/mdq-dims.jq`、`references/agg.jq`
- Produces:
  - `lm-ebs-attached.jq`：`--slurpfile vols <ebs-gp2-eval.json>`，输入 list-metrics 原始 JSON，输出同形 JSON
  - `ebs-gp3-in.jq`：`--slurpfile agg <agg-ebs.json>`，输入 `ebs-gp2-eval.json`，输出 `gp3_plan()` 的 `vol` 数组
  - `ebs-price.jq`：`jq -n --slurpfile g2 <...> --slurpfile g3 <...>`，输出 `{gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_tput_usd, gp3_tput_unit}`
  - 产物文件名：`$IV/ebs-gp2-eval.json`、`$M/agg-ebs.json`、`$O/raw/solver/ebs-gp3-in.json`、`$SP/ebs-price.json`、`$O/raw/solver/ebs-gp3-<profile>.json`、`$SP/eip-idle-usd.json`

- [ ] **Step 1: 写失败测试（追加到 `tests/test_gp3_plan.py`，放在 `if __name__` 之前）**

```python
def _jq(args, stdin=None):
    """跑真 jq。jq 是本 skill 的硬性前置（preflight 缺它即 FAIL），缺失时报错不跳过。"""
    r = subprocess.run(["jq", "-c", *args], input=stdin, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _tmp(obj):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(obj, f); f.close()
    return f.name


def _agg(vol, metric, stat, bucket, n, mean, p95, mx):
    return {"rid": f"{vol}@{metric}", "itype": "gp2", "stat": stat, "bucket": bucket,
            "n": n, "mean": mean, "p95": p95, "max": mx, "min": 0}


def test_vol_inputs_take_the_full_window_band_and_keep_zero():
    """ebs-gp3-in.jq：只取 full-window 档（gp3 配置 24 小时生效）；0 原样保留；
    没有任何序列的卷照样出条、字段为 null（交给 missing-parity）；
    触顶小时数 = mean × n 取整（0/1 序列，mean × n 恰为取 1 的小时数）。"""
    rows = [
        _agg("vol-A", "VolumeAvgIOPS", "Average", "full-window", 720, 2.0, 12.5, 40.0),
        _agg("vol-A", "VolumeAvgIOPS", "Average", "biz-hours", 243, 9.0, 99.0, 99.0),
        _agg("vol-A", "VolumeAvgIOPS", "Maximum", "full-window", 720, 50.0, 300.0, 488.5),
        _agg("vol-A", "VolumeAvgIOPS", "Maximum", "biz-hours", 243, 50.0, 300.0, 9999.0),
        _agg("vol-A", "VolumeAvgThroughput", "Average", "full-window", 720, 0.0, 0.0, 0.0),
        _agg("vol-A", "VolumeAvgThroughput", "Maximum", "full-window", 720, 10.0, 90.0, 17000.0),
        _agg("vol-A", "VolumeIOPSExceededCheck", "Maximum", "full-window", 720,
             3 / 720, 0.0, 1.0),
        _agg("vol-A", "VolumeThroughputExceededCheck", "Maximum", "full-window", 720,
             0.0375, 0.0, 1.0),
    ]
    scope = [{"id": "vol-A", "size": 80, "attach": "i-EX-1"},
             {"id": "vol-B", "size": 30, "attach": "i-EX-2"}]
    out = _jq(["--slurpfile", "agg", _tmp(rows), "-f", str(REF / "ebs-gp3-in.jq"),
               _tmp(scope)])
    a, b = out
    assert a == {"rid": "vol-A", "size_gib": 80, "sus_iops": 12.5, "peak_iops": 488.5,
                 "sus_kibs": 0.0, "peak_kibs": 17000.0,
                 "iops_exceeded_p95": 0.0, "iops_exceeded_hours": 3,
                 "tput_exceeded_p95": 0.0, "tput_exceeded_hours": 27}, a
    assert b["rid"] == "vol-B" and b["size_gib"] == 30, b
    assert all(b[k] is None for k in b if k not in ("rid", "size_gib")), b
    # 端到端：jq 的产出直接喂 gp3_plan
    assert core.gp3_plan(a, T_AGG, PRICE)["tput_basis"] == "measured"
    assert core.gp3_plan(b, T_AGG, PRICE)["iops_basis"] == "missing-parity"


def test_attach_filter_keeps_only_the_current_attachment():
    """卷在窗口内换过宿主时 list-metrics 回两条序列，mdq-dims.jq 的 Label 只编卷 ID
    ⇒ 撞名阻断整批。lm-ebs-attached.jq 只留当前挂载那条，并顺带丢掉范围外的卷。"""
    def m(vol, inst):
        dims = [{"Name": "VolumeId", "Value": vol}]
        if inst:
            dims.append({"Name": "InstanceId", "Value": inst})
        return {"Namespace": "AWS/EBS", "MetricName": "VolumeAvgIOPS", "Dimensions": dims}
    lm = {"Metrics": [m("vol-A", "i-EX-new"), m("vol-A", "i-EX-old"),
                      m("vol-Z", "i-EX-9"), m("vol-A", None)]}
    scope = [{"id": "vol-A", "size": 80, "attach": "i-EX-new"}]
    out = _jq(["--slurpfile", "vols", _tmp(scope), "-f",
               str(REF / "lm-ebs-attached.jq")], stdin=json.dumps(lm))
    kept = [{d["Name"]: d["Value"] for d in x["Dimensions"]} for x in out["Metrics"]]
    assert kept == [{"VolumeId": "vol-A", "InstanceId": "i-EX-new"}], kept


def test_price_builder_refuses_ambiguous_families():
    """ebs-price.jq：每个 productFamily 恰好一条才取，否则 null ⇒ price-unknown。
    不取第一条：随机取一条就是 ALB `-TS-` 那个低估 3.6–4.5 倍的坑。"""
    g2 = [{"fam": "Storage", "ut": "USW2-EBS:VolumeUsage.gp2", "unit": "GB-Mo", "usd": 0.10}]
    g3 = [{"fam": "Storage", "ut": "USW2-EBS:VolumeUsage.gp3", "unit": "GB-Mo", "usd": 0.08},
          {"fam": "System Operation", "ut": "USW2-EBS:VolumeP-IOPS.gp3",
           "unit": "IOPS-Mo", "usd": 0.005},
          {"fam": "Provisioned Throughput", "ut": "USW2-EBS:VolumeP-Throughput.gp3",
           "unit": "GiBps-mo", "usd": 40.96}]
    ok = _jq(["-n", "--slurpfile", "g2", _tmp(g2), "--slurpfile", "g3", _tmp(g3),
              "-f", str(REF / "ebs-price.jq")])
    assert ok == {"gp2_gb_mo": 0.10, "gp3_gb_mo": 0.08, "gp3_iops_mo": 0.005,
                  "gp3_tput_usd": 40.96, "gp3_tput_unit": "GiBps-mo"}, ok
    dup = g3 + [dict(g3[0], ut="USW2-LZ-EBS:VolumeUsage.gp3", usd=0.096)]
    bad = _jq(["-n", "--slurpfile", "g2", _tmp(g2), "--slurpfile", "g3", _tmp(dup),
               "-f", str(REF / "ebs-price.jq")])
    assert bad["gp3_gb_mo"] is None and bad["gp3_iops_mo"] == 0.005, bad
    nothru = _jq(["-n", "--slurpfile", "g2", _tmp(g2), "--slurpfile", "g3", _tmp(g3[:2]),
                  "-f", str(REF / "ebs-price.jq")])
    assert nothru["gp3_tput_usd"] is None and nothru["gp3_tput_unit"] is None, nothru
```

- [ ] **Step 2: 运行，确认失败**

Run: `python3 tests/test_gp3_plan.py`
Expected: 3 条新测试 `✗`（jq 报 `Could not open ... ebs-gp3-in.jq` 之类），其余 13 条 `✓`；末行 `13/16 passed`。

- [ ] **Step 3: 新建 `references/lm-ebs-attached.jq`**

```jq
# list-metrics 回包只留「当前挂载」那一条序列。
#
# AWS/EBS 的 VolumeAvgIOPS / VolumeAvgThroughput / *ExceededCheck 维度是
# VolumeId + InstanceId。卷在窗口内换过宿主时，list-metrics 会同时回旧宿主与新宿主
# 两条序列；mdq-dims.jq 的 Label 只编卷 ID（`<vol>@<metric>|gp2|<stat>`），两条必然
# 撞名 ⇒ §2 的重复 Label 断言阻断整批采集。判据要的是「现在这台宿主上的用量」，
# 所以只取当前挂载那条；范围清单外的卷也在这里一并丢掉。
#
# 参数: --slurpfile vols <ebs-gp2-eval.json>   （§2.7 ① 的范围清单，含 .id 与 .attach）
# 输入: aws cloudwatch list-metrics --namespace AWS/EBS --metric-name X 的原始 JSON
# 产出: 同形 JSON（只删 Metrics 里的条目），直接喂 mdq-dims.jq
($vols[0] | map({key: .id, value: .attach}) | from_entries) as $att
| .Metrics |= map(
    (.Dimensions | map({key: .Name, value: .Value}) | from_entries) as $d
    | select($d.InstanceId != null and $att[$d.VolumeId] == $d.InstanceId))
```

- [ ] **Step 4: 新建 `references/ebs-gp3-in.jq`**

```jq
# agg 产出 + 范围清单 → core.gp3_plan() 的 vol 数组，一卷一条。
#
# 参数: --slurpfile agg <agg-ebs.json>   （agg.jq 产出，含 full-window 档）
# 输入: ebs-gp2-eval.json（§2.7 ① 的范围清单）
#
# **遍历方向是范围清单，不是 agg。** 以 agg 为主循环会让「一个指标都没采到」的卷
# 整条消失，而那恰恰是要走 missing-parity 兜底的那一类（非 Nitro 宿主）。
# **只取 full-window 档**：gp3 的配置 24 小时生效，夜间备份被限流同样是事故。
# 取值一律显式判 null，不用 `//`：0 是有效值（零 IO 的卷）。
def rid0: .rid | split("@")[0];
def mn:   .rid | split("@")[1];
def at($rows; $m; $st; $f):
  [ $rows[] | select(mn == $m and .stat == $st and .bucket == "full-window") | .[$f] ]
  | if length == 0 then null else .[0] end;
# 触顶序列只有 0 / 1，mean × n 恰为取 1 的小时数（与 §7 求 Σ Sum 同一个恒等式）；
# round 去掉浮点残差，否则 blocker 里会出现 27.000000000000004 小时。
def hours($rows; $m):
  [ $rows[] | select(mn == $m and .stat == "Maximum" and .bucket == "full-window")
    | .mean * .n ]
  | if length == 0 then null else (.[0] | round) end;
($agg[0] | group_by(rid0) | map({key: (.[0] | rid0), value: .}) | from_entries) as $BY
| map(
    . as $v
  | (if $BY[$v.id] == null then [] else $BY[$v.id] end) as $r
  | { rid: $v.id, size_gib: $v.size,
      sus_iops:  at($r; "VolumeAvgIOPS"; "Average"; "p95"),
      peak_iops: at($r; "VolumeAvgIOPS"; "Maximum"; "max"),
      sus_kibs:  at($r; "VolumeAvgThroughput"; "Average"; "p95"),
      peak_kibs: at($r; "VolumeAvgThroughput"; "Maximum"; "max"),
      iops_exceeded_p95:   at($r; "VolumeIOPSExceededCheck"; "Maximum"; "p95"),
      iops_exceeded_hours: hours($r; "VolumeIOPSExceededCheck"),
      tput_exceeded_p95:   at($r; "VolumeThroughputExceededCheck"; "Maximum"; "p95"),
      tput_exceeded_hours: hours($r; "VolumeThroughputExceededCheck") } )
```

- [ ] **Step 5: 新建 `references/ebs-price.jq`**

```jq
# EBS 取价回包 → core.gp3_plan() 要的单价。吞吐单价保留原单位，
# 换算交给 core.gp3_tput_price_per_mibps()（单位是 GiBps-mo，当成每 MiB/s 会高估 1024 倍）。
#
# 参数: --slurpfile g2 <gp2 回包投影>  --slurpfile g3 <gp3 回包投影>
#   两份投影都是 [{fam, ut, unit, usd}]（见 cli-recipes.md §6.1 的 EBS 取价命令）
# 产出: {gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_tput_usd, gp3_tput_unit}
#
# **每个 productFamily 恰好一条才取**，否则给 null ⇒ gp3_plan 判 price-unknown。
# 不取第一条：同一 family 多条说明回包里混进了别的东西（Local Zone、Outposts 之类），
# 随机取一条就是 ALB `-TS-` 那个坑（SKILL.md 易错项速查）。
def one($rows; $fam):
  [ $rows[] | select(.fam == $fam) ] | if length == 1 then .[0] else null end;
def usd($r): if $r == null then null else $r.usd end;
one($g2[0]; "Storage") as $s2
| one($g3[0]; "Storage") as $s3
| one($g3[0]; "System Operation") as $io
| one($g3[0]; "Provisioned Throughput") as $tp
| { gp2_gb_mo: usd($s2), gp3_gb_mo: usd($s3), gp3_iops_mo: usd($io),
    gp3_tput_usd: usd($tp),
    gp3_tput_unit: (if $tp == null then null else $tp.unit end) }
```

- [ ] **Step 6: 运行，确认通过**

Run: `python3 tests/test_gp3_plan.py && python3 tests/test_no_duplicated_constants.py`
Expected: `16/16 passed`；常量测试全绿（三个 `.jq` 不含任何阈值数值）。

- [ ] **Step 7: `cli-recipes.md` §1 投影加 `lifecycle`**

把 running 那条 `describe-instances` 的 `--query` 由

```
'Reservations[].Instances[].{id:InstanceId,type:InstanceType,az:Placement.AvailabilityZone,arch:Architecture,op:UsageOperation,ten:Placement.Tenancy,name:Tags[?Key==`Name`]|[0].Value,launch:LaunchTime}'
```

改为

```
'Reservations[].Instances[].{id:InstanceId,type:InstanceType,az:Placement.AvailabilityZone,arch:Architecture,op:UsageOperation,ten:Placement.Tenancy,lifecycle:InstanceLifecycle,name:Tags[?Key==`Name`]|[0].Value,launch:LaunchTime}'
```

并在 §1 代码块之后加一句：「`lifecycle` 对按需实例为 `null`（AWS 不返回该键）——这是值，不是缺失；Spot 为 `spot`。」

- [ ] **Step 8: `cli-recipes.md` 新增 §2.7（插在 §2.6 结束、`## §3` 之前）**

````markdown
### §2.7 EBS gp2 卷的 IOPS / 吞吐 — `AWS/EBS`，维度 `VolumeId` + `InstanceId`

**只为 gp2→gp3 采**（`core.gp3_plan()` 的输入，见 spec 2026-10-04）。四个指标都是
Nitro 实例专有、已是速率（`VolumeAvgIOPS` 为 Ops/s、`VolumeAvgThroughput` 为 KiB/s），
**不采 `VolumeReadOps` / `VolumeWriteOps` 做 ÷ 发布间隔换算**——换算系数这一类错本 skill
犯过三次。非 Nitro 宿主不发布这四个指标，由 `gp3_plan()` 按 gp2 能力对齐兜底。

实测（2026-10-04，验证账号两个 region 14 块在用 gp2 卷）：每小时 `SampleCount` = 60；
小时 `Maximum` 等于该小时分钟值的最大值，超出 1 分钟数据的 15 天保留期之后仍成立；
30 天 720/720 点。

```bash
# ① 范围：gp2、in-use、宿主在 running 清单里（走删除路径的卷不采，见 SKILL.md 资源级互斥）
jq -c --slurpfile e $IV/ec2.json '($e[0] | map(.id)) as $run
  | [ .[] | select(.type == "gp2" and .state == "in-use"
                   and (.attach as $a | $run | index($a)) != null) ]' \
  $IV/ebs.json > $IV/ebs-gp2-eval.json

# ② 逐指标 list-metrics → 只留当前挂载那条序列 → 生成查询（四批前缀各不相同）
TYV=$(jq -c '[.[] | {key: .id, value: "gp2"}] | from_entries' $IV/ebs-gp2-eval.json)
while read -r PFX MN STATS; do
  aws cloudwatch list-metrics --region $R --namespace AWS/EBS --metric-name "$MN" \
    --output json </dev/null \
  | jq --slurpfile vols $IV/ebs-gp2-eval.json -f $S/references/lm-ebs-attached.jq \
  | jq -c --arg mn "$MN" --arg idname VolumeId --argjson ty "$TYV" \
       --argjson stats "$STATS" --arg idprefix "$PFX" \
       -f $S/references/mdq-dims.jq > $M/mdq-ebs-$PFX.json
done <<'EOF'
ei VolumeAvgIOPS ["Average","Maximum"]
et VolumeAvgThroughput ["Average","Maximum"]
xi VolumeIOPSExceededCheck ["Maximum"]
xt VolumeThroughputExceededCheck ["Maximum"]
EOF
jq -s -c 'add' $M/mdq-ebs-ei.json $M/mdq-ebs-et.json $M/mdq-ebs-xi.json $M/mdq-ebs-xt.json \
  > $M/mdq-ebs.json
jq '[.[].Id] | group_by(.) | map(select(length > 1)) | length' $M/mdq-ebs.json   # 须为 0
# 按 §2 的「提交要求」分批提交 $M/mdq-ebs.json → $M/raw-ebs.json，并跑重复 Label 断言

# ③ 聚合（§3），再拼 gp3_plan() 的输入；行数须等于范围清单
jq -r --argjson tz $TZ_OFFSET -f $S/references/agg.jq $M/raw-ebs.json > $M/agg-ebs.json
mkdir -p $O/raw/solver
jq -c --slurpfile agg $M/agg-ebs.json -f $S/references/ebs-gp3-in.jq \
  $IV/ebs-gp2-eval.json > $O/raw/solver/ebs-gp3-in.json
[ "$(jq length $O/raw/solver/ebs-gp3-in.json)" = "$(jq length $IV/ebs-gp2-eval.json)" ] \
  || echo "FAIL: 卷数不符"
```

**为什么只留当前挂载那条（`lm-ebs-attached.jq`）**：卷在窗口内换过宿主时 `list-metrics`
回两条序列，`mdq-dims.jq` 的 Label 只编卷 ID，两条撞名会让重复 Label 断言阻断整批。

**为什么取 `full-window`**：gp3 的配置 24 小时生效，夜间备份被限流同样是事故，
沿用「峰值型取 full-window」的规则（`ebs-gp3-in.jq` 文件头）。

**④ 出 gp3 配置与金额**（单价见 §6.1 的 EBS 取价；结果随 `sizing_profile` 变，文件名带 profile）：

```bash
python3 - "$S/references" "$SIZING_PROFILE" $SP/ebs-price.json \
  $O/raw/solver/ebs-gp3-in.json > $O/raw/solver/ebs-gp3-$SIZING_PROFILE.json <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import core
t = core.load_thresholds(sys.argv[2])
p = json.load(open(sys.argv[3]))
price = {"gp2_gb_mo": p["gp2_gb_mo"], "gp3_gb_mo": p["gp3_gb_mo"],
         "gp3_iops_mo": p["gp3_iops_mo"],
         "gp3_mibps_mo": core.gp3_tput_price_per_mibps(p["gp3_tput_usd"],
                                                       p["gp3_tput_unit"])}
json.dump([core.gp3_plan(v, t, price) for v in json.load(open(sys.argv[4]))],
          sys.stdout, ensure_ascii=False, indent=1)
PY
jq -r '[.[].iops_basis] + [.[].tput_basis] | group_by(.) | map({(.[0]): length}) | add' \
  $O/raw/solver/ebs-gp3-$SIZING_PROFILE.json        # 依据分布，写进报告缺口
```

填法表 gp2 三行（可转 / 转了不省 / 单价不全）的 `verdict` / `bucket` / `action_type` /
`cur_cost_mo` / `other_save_mo` 逐格照抄这份产出，见 `report-template.md`。
````

- [ ] **Step 9: `cli-recipes.md` §6.1 补 EBS 取价**

非 EC2 取价表的 EBS 行，原文：

```markdown
| EBS | `AmazonEC2` | `productFamily=Storage` + `volumeApiName` | — |
```

改为：

```markdown
| EBS | `AmazonEC2` | `volumeApiName` + `productFamily`：存储 `Storage`、gp3 另配 IOPS `System Operation`、gp3 另配吞吐 `Provisioned Throughput` | 每个 family 恰好一条（`ebs-price.jq`）；**吞吐单位是 `GiBps-mo`**，换算交给 `core.gp3_tput_price_per_mibps()` |
```

并在该表之后（MSK 那段说明之前）加命令块：

````markdown
**EBS（gp2→gp3 用）：**

```bash
for VT in gp2 gp3; do
  aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
    --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
              "Type=TERM_MATCH,Field=volumeApiName,Value=$VT" --output json \
  | jq '[.PriceList[] | fromjson
         | (.terms.OnDemand | to_entries[0].value.priceDimensions | to_entries[0].value) as $d
         | {fam: .product.productFamily, ut: .product.attributes.usagetype,
            unit: $d.unit, usd: ($d.pricePerUnit.USD | tonumber)}]' \
  > $SP/ebs-$VT-price-raw.json
done
jq -n --slurpfile g2 $SP/ebs-gp2-price-raw.json --slurpfile g3 $SP/ebs-gp3-price-raw.json \
   -f $S/references/ebs-price.jq > $SP/ebs-price.json
jq -e 'all(.[]; . != null)' $SP/ebs-price.json >/dev/null \
  || echo "WARN: EBS 单价不全 ⇒ 全部 gp2 行 price-unknown，先查回包再往下走"
```

实测（观测值 @2026-10-04，us-west-2）：gp2 回 1 条、gp3 回 3 条；gp3 吞吐 $40.96 / GiBps-mo。
````

- [ ] **Step 10: `cli-recipes.md` 公有 IPv4 一节整段改写**

把从 `### 公有 IPv4 取不到价——标 price-unknown，不得用记忆值顶替` 到 `**不得用记忆里的单价顶替**——那会让一个无法核实的数字混进可核实的合计里。` 的整段替换为：

````markdown
### 公有 IPv4（未关联 EIP）：按 `group` 取价，不按 `productFamily`

单价在 `AmazonVPC` 里，但这组记录**没有 `productFamily` 属性**——此前按 family 查
（`AmazonEC2` 的 `IP Address`、`AmazonVPC` 的 `Public IPv4 Address`）必然为空，本节因此
曾断言「取不到价」、让 EIP 行标 `price-unknown`，桶 B 合计漏掉每个未关联 EIP。
按 `group` 过滤即得（实测 2026-10-04，us-west-2 与 ap-northeast-1 均为 $0.005 / 小时）：

```bash
aws pricing get-products --region us-east-1 --service-code AmazonVPC \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
            'Type=TERM_MATCH,Field=group,Value=VPCPublicIPv4Address' --output json \
| jq '[.PriceList[] | fromjson
       | select(.product.attributes.usagetype | endswith("PublicIPv4:IdleAddress"))
       | .terms.OnDemand | to_entries[0].value.priceDimensions | to_entries[0].value
       | {unit, usd: (.pricePerUnit.USD | tonumber)}]
      | if length == 1 and .[0].unit == "Hrs" then .[0].usd
        else error("公有 IPv4 闲置单价应恰好 1 条且按小时计，实际：\(.)") end' \
  > $SP/eip-idle-usd.json
```

同一 `group` 下另有 `InUseAddress` 一条（同价，已关联的地址同样计费），本版本不对它出建议。
EIP 行的 `cur_cost_mo` = 该单价 × `HOURS_PER_MONTH`（`core.py` 的常量）。
**取价失败时仍按 `price-unknown` 处理，不得用记忆里的单价顶替。**
````

- [ ] **Step 11: `cli-recipes.md` §7.0 / §7.2 / §7.3**

§7.0 字段表在 `operation` 那一行之后插入：

```markdown
| `tenancy` | 是（组装必检，见 §7.3 ②；`core.py` 缺键时按 `default` 并记 blocker） | inventory `.ten`（= `Placement.Tenancy`） | 非 `default` ⇒ `price-unknown`（Dedicated Host 按整台主机计费） |
| `lifecycle` | 是（同上；缺键时按按需并记 blocker） | inventory `.lifecycle`（= `InstanceLifecycle`，按需实例为 `null`） | 非 `null` ⇒ 金额照按需理论值算，加一条披露 blocker |
```

§7.2 组装式里把

```
  | { rid: $i.id, service: "ec2", type: $i.type, arch: $i.arch,
      operation: $i.op, az: $i.az, name: $i.name, count: 1,
```

改为

```
  | { rid: $i.id, service: "ec2", type: $i.type, arch: $i.arch,
      operation: $i.op, tenancy: $i.ten, lifecycle: $i.lifecycle,
      az: $i.az, name: $i.name, count: 1,
```

§7.3 ② 的字段数组 `["rid","service","type","arch","operation","sus_cpu",...` 改为
`["rid","service","type","arch","operation","tenancy","lifecycle","sus_cpu",...`（其余不动）。

- [ ] **Step 12: 运行，确认通过**

Run：

```bash
python3 tests/test_gp3_plan.py && python3 tests/test_no_duplicated_constants.py \
  && python3 tests/test_csv_contract.py | tail -1
```

Expected: `16/16 passed`；常量测试全绿（代码围栏配对、散文未复述阈值）；`test_csv_contract.py` 全绿（§6 ③ 与 §2.6 的抽取标记未被新内容打断）。

- [ ] **Step 13: 检查点**

Run: `git status --short`
Expected: 新增 3 个 `.jq`、`cli-recipes.md` 与 `tests/test_gp3_plan.py` 的改动。不 commit。

---

### Task 4: 报告契约、SKILL.md 与面向客户的文档（spec C4、C5 披露、C6 填法表）

**Files:**
- Modify: `references/report-template.md`
- Modify: `SKILL.md`
- Modify: `references/metrics-catalog.md`
- Modify: `docs/method-explained.html`
- Modify: `docs/specs/2026-09-03-utilization-based-rightsizing-design.md`（:388 后加勘误）
- Modify: `docs/README.md`（plans 索引加一行）
- Modify: `../README.md`、`../README_CN.md`
- Modify: `tests/test_csv_contract.py`（`REQUIRED_ROWS` 加两行）
- Modify: `tests/test_method_explained.py`（`TABLE_KEYS` 加两键）

**Interfaces:**
- Consumes: Task 1–3 的函数名、文件名、`*_basis` 取值、三种出口
- Produces: 填法表新增两行，行名分别为 `EBS 卷 \`gp2\`，取不到 gp3 单价` 与 `EKS 节点池（聚合行，成员含专用租户）`

- [ ] **Step 1: 先改测试（失败）**

`tests/test_csv_contract.py` 的 `REQUIRED_ROWS` 加两个键，加完后相关几行是：

```python
    "EBS 卷 `gp2` 且可转 `gp3`",
    "EBS 卷 `gp2`，取不到 gp3 单价",
    "EBS 卷 `state=available`",
```

```python
    "EKS 节点池（聚合行）",
    "EKS 节点池（聚合行，成员含专用租户）",
    "EKS 节点（成员行）",
```

（「`EKS 节点池（聚合行）`」不会命中新行：新行名在「聚合行」之后是「，」不是「）」。）

`tests/test_method_explained.py` 的 `TABLE_KEYS` 加：

```python
    "EBS 目标（持续项）": "target_ebs_p95",
    "EBS 上限（峰值项）": "ceiling_ebs_max",
```

Run: `python3 tests/test_csv_contract.py | tail -3; python3 tests/test_method_explained.py | tail -3`
Expected: `test_fill_table_covers_every_required_row` 失败（两个新键命中 0 行）；`test_threshold_table_matches_thresholds_json` 失败（找不到「EBS 目标（持续项）」这一行）。

- [ ] **Step 2: `report-template.md` 强制声明、分母范围、未包含项**

三处文字替换（左为原文，右为新文）：

```text
被 Reserved Instance 或 Savings Plan 覆盖的资源
→ 被 Reserved Instance 或 Savings Plan 覆盖、或以 Spot 购买的资源

RDS 实例、ElastiCache 节点、MSK broker、EKS 控制面。
→ RDS 实例、ElastiCache 节点、MSK broker、未关联 EIP、EKS 控制面。

RDS/MSK 存储与备份、CloudWatch、未关联的公有 IPv4（`price-unknown`）。
→ RDS/MSK 存储与备份、CloudWatch、已关联的公有 IPv4（本版本不出建议）。
```

（第一处在「报告开头的强制声明」第一段；第二处在「分母的范围」的「必须计入」清单；第三处是紧随其后的「显式声明为未包含」那一句。）

- [ ] **Step 3: `report-template.md` 填法表**

逐行替换（每组先给原行、再给新行；新增的两行紧跟在其上一行之后）：

```markdown
| EBS 卷 `gp2` 且可转 `gp3` | `ebs` | `gp2` | `excluded` | `downsize` | `storage-type` | 留空 | 留空 | 留空 | 当前卷月额 | gp3 与 gp2 的月额差 |
```

→

```markdown
| EBS 卷 `gp2` 且可转 `gp3` | `ebs` | `gp2` | `excluded` | `downsize` | `storage-type` | 留空 | 留空 | 留空 | `core.gp3_plan()` 的 cur_cost_mo | `core.gp3_plan()` 的 other_save_mo（已扣另配 IOPS / 吞吐费） |
| EBS 卷 `gp2`，取不到 gp3 单价 | `ebs` | `gp2` | `price-unknown` | `excluded` | `none` | 留空 | 留空 | 留空 | `core.gp3_plan()` 的 cur_cost_mo（gp2 单价也缺时为空） | 留空 |
```

```markdown
| EBS 卷 其他（已是 `gp3` / 挂 running 实例） | `ebs` | 卷类型原文 | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | 当前卷月额 | 留空 |
```

→

```markdown
| EBS 卷 其他（已是 `gp3` / 挂 running 实例 / `gp2` 但 `gp3_plan()` 节省额 ≤ 0） | `ebs` | 卷类型原文 | `excluded` | `excluded` | `none` | 留空 | 留空 | 留空 | 当前卷月额 | 留空 |
```

```markdown
| EIP 未关联 | `vpc` | `eip` | `price-unknown` | `idle` | `delete` | 留空 | 留空 | 留空 | 留空 | 留空 |
```

→

```markdown
| EIP 未关联 | `vpc` | `eip` | `excluded` | `idle` | `delete` | 留空 | 留空 | 留空 | 小时费月额 | 留空 |
```

```markdown
| EKS 节点池（聚合行） | `eks` | 节点池当前机型 | `downsize` | `downsize` | `downsize` | 留空 | 留空 | 留空 | **留空**（成本在成员行） | (当前节点数 − 理论节点数) × 单节点月额 |
| EKS 节点（成员行） | `eks` | 节点实例机型 | `excluded` | `excluded` | `none` | 留空 | `biz-hours` | `biz-hours` | 该节点月额 | 留空 |
```

→

```markdown
| EKS 节点池（聚合行） | `eks` | 节点池当前机型 | `downsize` | `downsize` | `downsize` | 留空 | 留空 | 留空 | **留空**（成本在成员行） | (当前节点数 − 理论节点数) × 单节点月额 |
| EKS 节点池（聚合行，成员含专用租户） | `eks` | 节点池当前机型 | `price-unknown` | `excluded` | `none` | 留空 | 留空 | 留空 | **留空**（成本在成员行） | 留空 |
| EKS 节点（成员行） | `eks` | 节点实例机型 | `excluded` | `excluded` | `none` | 留空 | `biz-hours` | `biz-hours` | 该节点月额（专用租户节点为空） | 留空 |
```

- [ ] **Step 4: `report-template.md` 逐格理由**

- 「`other_save_mo` 只出现在两行上」那一条末尾追加：「gp2→gp3 的金额由 `core.gp3_plan()` 产出，已扣为不降性能另配的 IOPS / 吞吐费（`cli-recipes.md` §2.7）。`gp3_plan()` 判出节省额 ≤ 0 的卷按「EBS 卷 其他」行填，单价不全的按「取不到 gp3 单价」行填 —— 两者都不带 `other_save_mo`。」
- 把「**EIP 是 `price-unknown` 而不是 `excluded`。**」那一整条替换为：

```markdown
- **EIP 的单价取自 `AmazonVPC` 的 `group=VPCPublicIPv4Address`**（`cli-recipes.md`「公有 IPv4」一节）。
  这组记录没有 `productFamily`，此前按 family 查不到，本行曾定为 `price-unknown`、
  `cur_cost_mo` 留空，桶 B 合计因此漏掉每个未关联 EIP。现在与 NAT / ALB 闲置行同形：
  `verdict=excluded`、`bucket=idle`、`cur_cost_mo` = 单价 × `HOURS_PER_MONTH`。
  取价失败时仍回到 `price-unknown`、`cur_cost_mo` 留空，并在「未包含项」里点名——不得用记忆里的单价顶替。
```

- 在该条之后新增一条：

```markdown
- **专用租户节点不填成本，含专用租户成员的节点池不出节省额。** 与 `core.py` 对独立 EC2 的
  处理同源（`_tenancy_lifecycle()`）：Dedicated Host 按整台主机计费，单台节点减少不一定省钱。
  Spot 节点照按需理论价计，成员行写一条「购买方式为 spot」的披露。
```

- [ ] **Step 5: `SKILL.md` 五处**

1. 「价格口径」一节与 2. 「其他必须匹配的取价维度」两处文字替换：

```text
若客户已买 RI/SP，实际账单基数低于
→ 若客户已买 RI/SP、或实例以 Spot 购买，实际账单基数低于

**须单独取价或标 `price-unknown` 排除，不得套用 Shared 价格。**
→ **由 `core.py` 判 `price-unknown`，不得套用 Shared 价格**（Dedicated Host 按整台主机计费，单台降配不一定省钱）；组装时须把 tenancy 带进 solver-in（`cli-recipes.md` §7.0）。Spot 等非按需购买方式照按需理论价计，只披露。
```

3. preflight 检查表在 `CWAgent 磁盘指标` 一行之后插入：

```markdown
| EBS 卷 IOPS / 吞吐 | `list-metrics --namespace AWS/EBS --metric-name VolumeAvgIOPS` | 为 0 ⇒ 全部 gp2 卷按 gp2 能力对齐另配，节省额偏保守（非 Nitro 宿主不发布该指标） |
```

4. 「### EBS」第一条整条替换为：

```markdown
- `gp2 → gp3`：**配置量与节省额由 `core.gp3_plan()` 产出**，不要自己算。按 `AWS/EBS` 实测的
  IOPS / 吞吐（持续项取 p95、峰值项取分钟峰值，阈值键 `target_ebs_p95` / `ceiling_ebs_max`）
  反推 gp3 要配多少，以 gp3 基线为下限、gp2 能力为上限；超过 `VETO_TOLERANCE_PCT`% 的小时
  出现秒级触顶、或指标缺失时，直接对齐 gp2 能力。gp2 能力随容量分三档：
  **> 170 GiB 可突发到 250 MiB/s，≥ 334 GiB 持续 250 MiB/s，> 1000 GiB 基线 IOPS 才超过 3000**
  （334 GiB 是吞吐的分界点，不是 IOPS 的）。另配费用从节省额里扣，扣完不省就不出转换行。
  采集见 `cli-recipes.md` §2.7。
```

5. 「验证状态」表在 `EC2 / EBS / VPC 判据与 solver` 一行之后插入：

```markdown
| gp2→gp3（`AWS/EBS` 实测对齐） | 2026-10-04 在验证账号两个 region 普查 14 块在用 gp2 卷（宿主全为 Nitro）：指标语义、15 天后的 rollup、30 天覆盖已逐项对账（spec 2026-10-04 的 T1）。**非 Nitro 宿主的对齐兜底未实测** |
```

6. 「易错项速查」表末尾（`**假定资源规格在窗口内不变**` 那一行之后）追加四行：

```markdown
| **gp2 的 334 GiB 当成 IOPS 分界点** | 334 GiB 是吞吐分界点（持续 250 MiB/s）；基线 IOPS 要到 1000 GiB 才超 3000 ⇒ 334–1000 GiB 的卷被要求白配 IOPS，吞吐照样从 250 掉到 125 | 分档只在 `core.gp2_capability()` |
| **gp3 吞吐单价当成每 MiB/s** | pricing API 回的单位是 `GiBps-mo`（实测 $40.96），当成每 MiB/s 高估 1024 倍 | `core.gp3_tput_price_per_mibps()` 断言单位后换算，单位不符按缺失 |
| **按 `productFamily` 查公有 IPv4 单价** | 这组记录没有 `productFamily`，必然查空，曾因此把未关联 EIP 判成取不到价、桶 B 漏计 | `AmazonVPC` + `group=VPCPublicIPv4Address`（`cli-recipes.md`） |
| **EBS IOPS 用 `VolumeReadOps` ÷ 发布间隔换算** | 又一个换算系数（本 skill 在这类系数上错过三次） | 用 Nitro 的 `VolumeAvgIOPS` / `VolumeAvgThroughput`（已是速率）；缺它们按 gp2 能力对齐 |
```

- [ ] **Step 6: `metrics-catalog.md` 的 EBS 一节**

在该节第一张表之后插入：

```markdown
**Nitro 专有的四个指标（维度 `VolumeId` + `InstanceId`）——`core.gp3_plan()` 的输入**，
采集见 `cli-recipes.md` §2.7：

| 指标 | 单位 | stat | 用途 |
|---|---|---|---|
| `VolumeAvgIOPS` | Ops/s（已是速率） | `Average`（持续项取 full-window p95）、`Maximum`（峰值项取 full-window max） | gp3 IOPS 定档 |
| `VolumeAvgThroughput` | KiB/s（已是速率） | 同上 | gp3 吞吐定档 |
| `VolumeIOPSExceededCheck` | 0 / 1（分钟内任一秒超出卷的上限即为 1） | `Maximum`（p95 判持续触顶，`mean × n` 为触顶小时数） | 判实测值是否被 gp2 压低 |
| `VolumeThroughputExceededCheck` | 同上 | 同上 | 同上 |

实测（2026-10-04，验证账号）：`VolumeAvgIOPS` 小时 `Maximum` 与 (读 + 写) ÷ 60 的分钟最大值
逐小时一致；超过 15 天的数据小时 `SampleCount` 仍为 60。只在卷挂在**运行中**实例上时发布。
```

并把「**谁在消费这张表：目前一个都没有。**」改为「**谁在消费：上面四行计数类指标没有消费者；Nitro 的四个指标由 `core.gp3_plan()` 消费。**」，其后原文保留。

- [ ] **Step 7: `method-explained.html` 两处**

1. EBS 卷那一条 `<li>`：把

```html
      <li><b><code>gp2 → gp3</code> 全量给出</b>：同容量下 gp3 单价更低。<b>原容量 &gt; 334 GiB 时基线 IOPS 已超 3000</b>，转 gp3 必须显式配置 IOPS，这条会写进阻断项。</li>
```

替换为

```html
      <li><b><code>gp2 → gp3</code> 按实测对齐</b>：同容量下 gp3 存储单价低约 20%，但 gp3 的基线固定为 3000 IOPS / 125 MiB/s，而 gp2 的能力随容量变——<b>大于 170 GiB 可突发到 250 MiB/s，334 GiB 起持续 250 MiB/s，大于 1000 GiB 基线 IOPS 才超过 3000</b>。按 CloudWatch 实测的 IOPS / 吞吐（持续项取 p95、峰值项取分钟峰值）反推 gp3 要配多少，以 gp3 基线为下限、gp2 能力为上限；超过 5% 的小时出现秒级触顶、或指标缺失时，直接对齐 gp2 能力。另配的 IOPS / 吞吐费从节省额里扣掉，扣完不省就不出转换建议。</li>
```

2. 预设表在 `<tr><td>内存上限（峰值项）</td>...</tr>` 之后插入：

```html
    <tr><td>EBS 目标（持续项）</td><td class="num">40%</td><td class="num">60%</td><td>gp2→gp3 另配 IOPS / 吞吐的持续项</td></tr>
    <tr><td>EBS 上限（峰值项）</td><td class="num">60%</td><td class="num">85%</td><td>gp2→gp3 另配 IOPS / 吞吐的峰值项</td></tr>
```

- [ ] **Step 8: 勘误、索引与两份 README**

1. `docs/specs/2026-09-03-utilization-based-rightsizing-design.md` 第 388 行之后插入一行：

```markdown
  > **勘误（2026-10-04）**：334 GiB 是 gp2 吞吐的分界点，不是 IOPS 的；基线 IOPS 要到 1000 GiB 才超 3000。现行规则见 `2026-10-04-pricing-correctness-design.md`。
```

2. `docs/README.md` 的 plans 表末尾加一行：

```markdown
| [2026-10-04-pricing-correctness.md](./plans/2026-10-04-pricing-correctness.md) | 按 spec 修三处计价错误：`core.gp3_plan()` 按 `AWS/EBS` 实测对齐 gp3 并扣另配费、专用租户在 `evaluate()` 判 `price-unknown`、Spot 只披露、公有 IPv4 按 `group` 取价；附验证账号回放 |
```

3. 两份 README 第 29 行（aws-rightsizing 那一格）各做一处文字替换：

```text
../README.md：
two selectable `sizing_profile` presets (`aggressive`/`conservative`). All verdict logic
→ two selectable `sizing_profile` presets (`aggressive`/`conservative`). gp2→gp3 conversions are sized from measured `AWS/EBS` IOPS/throughput, with the extra provisioned performance netted out of the savings. All verdict logic

../README_CN.md：
并提供 `aggressive`/`conservative` 两套 `sizing_profile` 预设。全部判据
→ 并提供 `aggressive`/`conservative` 两套 `sizing_profile` 预设。gp2→gp3 按 `AWS/EBS` 实测 IOPS / 吞吐定配置，另配性能的费用从节省额中扣除。全部判据
```

- [ ] **Step 9: 运行全部门禁**

Run（在 `aws-rightsizing/` 下，即 `SKILL.md` 的门禁循环）：

```bash
for t in tests/test_*.py; do
  printf '%-46s' "$t"
  out=$(python3 "$t") || { echo "FAIL"; echo "$out" | tail -20; break; }
  echo "$out" | tail -1
done
```

Expected: 除 `tests/test_no_private_data.py` 外每个文件 `n/n passed`。`test_no_private_data.py` 若失败，**只允许**出现 `others/ian-leslie-perspective/` 下两行（本轮之前就存在的未跟踪目录，不属本计划范围，交用户处理）；出现任何其他命中都必须修。

- [ ] **Step 10: SKILL.md 自检三条**

Run（在 `aws-rightsizing/` 下，命令照抄 `SKILL.md`「6. 报告生成」里的自检块）。
Expected: 三条都打印 `CLEAN`（新增的命令全是 `get-products` / `list-metrics` / `describe-*`）。

- [ ] **Step 11: 检查点**

Run: `git status --short`
Expected: 改动文件与本计划 Task 1–4 的 Files 列表一致；不 commit。

---

### Task 5: 验证账号上的只读回放（spec「验证方式」2、3）

**Files:**
- Modify: `docs/plans/2026-10-04-pricing-correctness.md`（本文件末尾追加「回放记录」一节，**只写聚合数字，不写任何 ID**）

**Interfaces:**
- Consumes: Task 1–3 的全部产物
- Produces: 回放记录（依据分布、改动前后合计、两道取价断言结果）

- [ ] **Step 1: 准备只读环境与工作目录（产物只放 /tmp，不进 repo）**

```bash
export AWS_PROFILE=<用户指定的只读验证 profile>     # 不要写进任何文件
S=$(pwd)                                            # aws-rightsizing/
aws sts get-caller-identity --query Arn --output text   # 只确认身份，不抄进文档
```

- [ ] **Step 2: 两个 region 逐个跑 §1（只跑 ec2 / ebs 两条）、§2.0 窗口、§2.7、§6.1 EBS 取价、§2.7 ④（两个 profile）**

对 `R in us-west-2 ap-northeast-1`：令 `O=/tmp/rs-replay/$R`、`IV=$O/raw/inventory`、`M=$O/raw/metrics`、`SP=$O/raw/specs`，按 `cli-recipes.md` 原样执行上述各段（窗口按 §2.0 ① 对齐到业务本地午夜，`TZ_OFFSET` 取 UTC+8 的秒数）。

Expected: 每个 region 的 `ebs-gp3-in.json` 行数 == `ebs-gp2-eval.json` 行数；`mdq-ebs.json` 重复 Id 为 0；`raw-ebs.json` 重复 Label 为 0。

- [ ] **Step 3: 取价两道断言**

```bash
for R in us-west-2 ap-northeast-1; do
  jq -e 'all(.[]; . != null) and .gp3_tput_unit == "GiBps-mo"' /tmp/rs-replay/$R/raw/specs/ebs-price.json
done
```

再按 `cli-recipes.md`「公有 IPv4」一节对两个 region 各跑一次。
Expected: 两个 region 都打印 `true`；公有 IPv4 命令不报 `error`，`eip-idle-usd.json` 为数字。

- [ ] **Step 4: 汇总并写回放记录**

```bash
for R in us-west-2 ap-northeast-1; do for P in aggressive conservative; do
  jq -r --arg r $R --arg p $P --slurpfile pr /tmp/rs-replay/$R/raw/specs/ebs-price.json '
    ($pr[0]) as $q
    | "\($r) \($p): 卷 \(length) 块；依据 \([.[].iops_basis, .[].tput_basis] | group_by(.) | map("\(.[0])×\(length)") | join(" "))；"
    + "转换行 \([.[] | select(.action_type == "storage-type")] | length) 条；"
    + "Σother_save_mo=\([.[] | select(.other_save_mo != null) | .other_save_mo] | add // 0 | . * 100 | round / 100)；"
    + "改动前口径（只算存储差价）=\([.[] | select(.cur_cost_mo != null)
         | .cur_cost_mo * (1 - $q.gp3_gb_mo / $q.gp2_gb_mo)] | add // 0 | . * 100 | round / 100)"' \
    /tmp/rs-replay/$R/raw/solver/ebs-gp3-$P.json
done; done
```

（`add // 0` 只处理空数组求和得 `null` 的情形，不会吞掉任何 0 值。「改动前口径」= 旧填法表的算法：gp2 月额 × (1 − gp3 存储单价 / gp2 存储单价)，单价取同一 region 的 `ebs-price.json`。）

把输出按下面格式追加到本文件末尾（**不写卷 ID、实例 ID、账号 ID、profile 名**；日期填实际回放日）：

```markdown
## 回放记录（<回放日期>，验证账号，只读）

| region | profile | 卷数 | 依据分布 | 转换行 | Σ other_save_mo | 改动前口径 |
|---|---|---:|---|---:|---:|---:|
| ... | ... | ... | ... | ... | ... | ... |

取价断言：两个 region 的 EBS 四个单价齐全、吞吐单位 `GiBps-mo`；公有 IPv4 闲置单价恰好 1 条。
与 spec「预期收益」的对照：<逐条写相符 / 不符及原因>
```

Expected: 依据分布里 `exceeded-parity` 为 0（spec T1：0 / 14 块持续触顶）；20 GiB 那 5 块的吞吐为 128。若与 spec 不符，**先停下报告，不改代码迁就数据**。

- [ ] **Step 5: 隐私自查**

Run: `python3 tests/test_no_private_data.py | tail -3` 以及 `grep -nE 'i-0[0-9a-f]{7,}|vol-0[0-9a-f]{7,}' docs/plans/2026-10-04-pricing-correctness.md || echo CLEAN`
Expected: 回放记录不引入任何新命中；`CLEAN`。

---

### Task 6: 收尾核对

**Files:** 无新改动（只核对）

- [ ] **Step 1: 门禁再跑一遍**（同 Task 4 Step 9 的循环）
Expected: 同 Task 4 Step 9。

- [ ] **Step 2: spec 覆盖核对**

逐条对照 `docs/specs/2026-10-04-pricing-correctness-design.md` 的「改动清单」表，每一行都能在 `git diff --stat` 里找到对应文件；「测试影响」每一条都有对应测试在跑。

- [ ] **Step 3: 交付说明**

向用户报告：改动文件清单、门禁结果（含 `test_no_private_data.py` 的那两行预存命中）、回放记录要点。**不 commit、不 push**，等用户决定。

## 回放记录（2026-10-05，验证账号，只读）

窗口 30 天，按业务本地午夜（UTC+8）对齐。

| region | profile | 卷数 | 依据分布（两个维度合计） | 转换行 | Σ other_save_mo | 改动前口径（只算存储差价） |
|---|---|---:|---|---:|---:|---:|
| us-west-2 | aggressive | 12 | measured × 24 | 12 | $8.92 | $9.52 |
| us-west-2 | conservative | 12 | measured × 24 | 12 | $8.92 | $9.52 |
| ap-northeast-1 | aggressive | 2 | measured × 4 | 2 | $1.44 | $1.44 |
| ap-northeast-1 | conservative | 2 | measured × 4 | 2 | $1.44 | $1.44 |

- 采集：us-west-2 72 个 query、ap-northeast-1 12 个 query；重复 Id 0、重复 Label 0；
  全部序列非空、每条 720 点；`ebs-gp3-in.json` 行数等于范围清单行数（12 / 2）。
- 取价断言：两个 region 的 EBS 四个单价齐全、吞吐单位均为 `GiBps-mo`
  （us-west-2 $40.96、ap-northeast-1 $49.152，即每 MiB/s $0.04 / $0.048）；
  公有 IPv4 闲置单价恰好 1 条，两个 region 均为 $0.005 / 小时。

与 spec「预期收益」的对照：

- **相符**：持续触顶 0 块（spec T1：0 / 14 块超过 5% 的小时）；5 块 20 GiB 卷的吞吐配到 128 MiB/s，
  每块比改动前少省 $0.12，合计 $0.60，正是 us-west-2 两列之差（$9.52 − $8.92）；其余卷与改动前一致。
- **相符**：两个 profile 结果相同 —— 全部卷的实测需求都在 gp3 基线之内，阈值差异不起作用。
- **未覆盖**：本次范围内没有 > 170 GiB 的卷，也没有非 Nitro 宿主，这两条路径仍只有单元测试。
