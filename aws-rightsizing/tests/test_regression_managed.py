"""托管侧回归基线。

**与 test_regression_fleet.py 分开。** 那份 fixture 是 EC2 独占的 13 行，
它的 route1_nb / route2_max 在仓库历史里带着一条长注释链（527.15 那段）。
本轮不碰 EC2 路径，那两个数字必须逐分不变；把托管金额并进去会让两类改动的
成因永久纠缠在同一个数字上。

基线来源：账号 123456789012 / ap-east-1 的归档数据离线重放
（12 RDS + 11 Redis 复制组 + 8 MSK 集群 + 3 条「采集侧未升级」行）。
逐格对账见 docs/specs/2026-09-13-managed-target-selection-design.md 的
「本机队实测」表。
"""
import collections
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.parent
CORE = ROOT / "references" / "core.py"
FIXTURE = ROOT / "tests" / "fixtures" / "regression-managed.json"

# 路线口径与 test_regression_fleet.py 一致：
#   route1_nb  = Σ nb_save_mo，一律取 non-burstable
#   route2_max = Σ max(nb, b)，**逐条取更省者**（不是 burst 列求和）
#
# MSK 两条路线都是 0，且**这是正面产出** —— kafka.m7g.large 在本 region
# 更便宜的 broker 机型只有 kafka.t3.small(x86)，跨架构为硬约束禁止项；
# 6 个 kafka.t3.small 集群在价目地板上，更便宜的候选数为 0。
# 金额与改动前相同，可审计性不同。
EXPECTED = {
    "aggressive": {
        "rds": {"route1": 261.34, "route2": 875.27, "downsize": 9},
        "elasticache": {"route1": 0.0, "route2": 1235.89, "downsize": 5},
        "msk": {"route1": 0.0, "route2": 0.0, "downsize": 0},
    },
    "conservative": {
        "rds": {"route1": 261.34, "route2": 875.27, "downsize": 9},
        "elasticache": {"route1": 0.0, "route2": 1158.51, "downsize": 5},
        "msk": {"route1": 0.0, "route2": 0.0, "downsize": 0},
    },
}
LEGACY_RIDS = ("db-legacy-01", "redis-legacy-01", "msk-legacy-01")


def _run(profile):
    ctx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ctx["sizing_profile"] = profile
    p = subprocess.run([sys.executable, str(CORE)], input=json.dumps(ctx),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _totals(findings, service):
    dn = [f for f in findings
          if f["service"] == service and f.get("bucket") == "downsize"
          and f["rid"] not in LEGACY_RIDS]
    return {
        "route1": round(sum(f.get("nb_save_mo") or 0 for f in dn), 2),
        "route2": round(sum(max(f.get("nb_save_mo") or 0,
                                f.get("b_save_mo") or 0) for f in dn), 2),
        "downsize": len(dn),
    }


def test_managed_route_totals_match_baseline():
    for profile, exp in EXPECTED.items():
        fs = _run(profile)
        for svc, want in exp.items():
            got = _totals(fs, svc)
            assert got == want, f"{profile}/{svc}: {got} != {want}"


def test_rds_verdict_mix_matches_the_replay():
    """9 行选出目标、1 行存储触 0、1 行 FreeableMemory 越地板、1 行 CPU 持续超。"""
    for profile in EXPECTED:
        fs = [f for f in _run(profile)
              if f["service"] == "rds" and f["rid"] not in LEGACY_RIDS]
        assert collections.Counter(f["verdict"] for f in fs) == {
            "downsize-candidate": 9, "blocked": 2, "upsize-candidate": 1}, profile


def test_every_msk_row_names_its_specific_cause():
    """改动前 8 行共用一句「同形态下没有更便宜的候选机型」，且那句话来自一个
    采集侧布尔值 —— 判据自己并不知道为什么。"""
    fs = [f for f in _run("aggressive")
          if f["service"] == "msk" and f["rid"] not in LEGACY_RIDS]
    assert len(fs) == 8
    cross = [f for f in fs if any("跨 CPU 架构" in b for b in f["blockers"])]
    floor = [f for f in fs if any("价目地板" in b for b in f["blockers"])]
    assert len(cross) == 2 and len(floor) == 6
    for f in fs:
        assert f["verdict"] == "已合理配置", (f["rid"], f["verdict"])


def test_rows_without_candidates_produce_no_target():
    """向后兼容：采集侧未升级的行必须逐字保持改动前行为。

    三行走的是三条不同的旧路径，不能用同一句断言：
      db-legacy-01    / redis-legacy-01 ⇒ downsize-candidate + `_FIT_UNVERIFIED`
      msk-legacy-01   ⇒ metric-missing（RequestHandlerAvgIdlePercent 缺失）。
        这台正是 kafka.m7g.large：没有 candidates 时探针返回 None、
        采集侧布尔值为 true，于是照旧撞上缺指标 —— **这就是改动前的行为**，
        本轮刻意不改它。可行性探针只在采集侧升级后才有能力抢在它之前。
    """
    fs = {f["rid"]: f for f in _run("aggressive")}
    for rid in LEGACY_RIDS:
        f = fs[rid]
        assert f["nonburst"] is None and f["burst"] is None, rid
        assert f.get("nb_save_mo") is None and f.get("b_save_mo") is None, rid
    for rid in ("db-legacy-01", "redis-legacy-01"):
        assert fs[rid]["verdict"] == "downsize-candidate", rid
        assert any("未经校验" in b for b in fs[rid]["blockers"]), fs[rid]["blockers"]
    assert fs["msk-legacy-01"]["verdict"] == "metric-missing"
    assert "RequestHandlerAvgIdlePercent" in fs["msk-legacy-01"]["blockers"][0]


def test_managed_rows_never_claim_high_confidence():
    """`high` 在 EC2 侧的含义是「CPU 与内存两轴都有实测数据」，语义不同，
    不可套用。托管侧的适配校验建在观测稳态上，不含业务增长输入。"""
    for profile in EXPECTED:
        for f in _run(profile):
            assert f.get("confidence") in (None, "medium", "low"), f["rid"]


def test_storage_exhaustion_and_peak_reversal_are_reported():
    fs = {f["rid"]: f for f in _run("aggressive")}
    assert any("存储被耗尽过" in b for b in fs["db-sit-05"]["blockers"])
    # 峰值反转命中 4 台，不是 9 台。
    #
    # 「9 台」是另一个判别式的命中数：mean(Maximum) > 60 x mean(Average)
    # 否证「PI 按 1 分钟发布」—— 那测的是全机队一致的发布语义，逐行报是噪声。
    # 本判据按「峰值单独看是否翻转结论」判：
    #   db-uat-01   Maximum p95 2.0  / 0.5 = 4  > 2 vCPU
    #   db-infra-01 Maximum p95 23.0 / 0.5 = 46 > 2 vCPU
    #   db-sit-05   Maximum p95 7.0  / 0.5 = 14 > 8 vCPU
    #   db-uat-04   Maximum p95 7.0  / 0.5 = 14 > 8 vCPU
    # 其余 8 台（含 db-sit-06 的 2.0/0.5=4 <= 8）不触发。
    # 后两台最终是 blocked，注记仍要留 —— 阻断被解决后读者会回到这一行。
    hits = [r for r, f in fs.items()
            if any("Performance Insights 控制台" in b for b in f["blockers"])]
    assert set(hits) == {"db-uat-01", "db-infra-01", "db-sit-05",
                         "db-uat-04"}, hits


if __name__ == "__main__":
    # 退出码必须随失败非零：门禁是 `python3 "$t" || exit 1`，打印 ✗ 后仍 exit 0
    # 会让整个文件的断言不设防。清单**自动枚举**而不是手写：手写清单漏掉新加的
    # 函数，门禁照样打印全绿（本文件此前就漏过两条）。
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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
