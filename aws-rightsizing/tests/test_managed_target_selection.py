"""托管服务的目标机型初选。

此前三条托管判据的 nonburst / burst / nb_save_mo / b_save_mo 四列恒空：
采集侧算 cheaper_candidate_exists 时已经把候选连价格取全，然后只回传一个
布尔值。布尔值不含信息量到近乎误导 —— 实测 db.m6g.large 往下最近的更便宜
候选省 $5.84/mo，而真正装得下需求的目标省 $86.87/mo，差 14.9 倍。

候选池为空的五种成因必须逐个可区分：动作相同（不降配）但可操作性完全不同，
改动前五种给同一句话，且那句话在后三种下是**错的**。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

# ap-east-1 MySQL Single-AZ 真实价目与规格（内存取 pricing 的 memory 属性）
RDS_CANDS = [
    {"t": "db.t4g.micro", "usd": 0.0280, "vcpu": 2, "gib": 1.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.small", "usd": 0.0560, "vcpu": 2, "gib": 2.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.medium", "usd": 0.1110, "vcpu": 2, "gib": 4.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.large", "usd": 0.2220, "vcpu": 2, "gib": 8.0,
     "arch": "arm64", "burst": True},
    {"t": "db.m5.large", "usd": 0.2585, "vcpu": 2, "gib": 8.0,
     "arch": "x86_64", "burst": False},
]
# EC2 机型名 → baseline。db. 前缀剥掉后查；这张表只用于 baseline 与 arch。
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


def test_missing_candidates_returns_none_not_fail_closed():
    """实测教训（真实机队回放）：旧契约缺必填字段时 86 条托管行全部
    fail-closed，比不升级更差。新字段一律走「缺失即回退旧行为」。"""
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


def test_exclude_set_removes_candidate_and_reports_the_best_excluded():
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=2, mem_fit=lambda c: c["gib"] >= 2.0, base=BASE,
        exclude=frozenset({"db.t4g.small"}))
    assert pick["excluded_best"]["t"] == "db.t4g.small"
    assert pick["burst"]["t"] == "db.t4g.medium"


def test_managed_ec2_name_strips_all_three_prefixes():
    assert core._managed_ec2_name("db.t4g.medium") == "t4g.medium"
    assert core._managed_ec2_name("cache.m6g.large") == "m6g.large"
    assert core._managed_ec2_name("kafka.t3.small") == "t3.small"
    assert core._managed_ec2_name("t4g.medium") == "t4g.medium"


def test_apply_managed_pick_uses_effective_vcpu_for_delta():
    """delta 用 _eff_vcpu 而不是标称核数：db.m6g.large -> db.t4g.large
    同为 2 vCPU，按标称算 delta=0，看起来毫无意义。"""
    out = {}
    pick = core._pick_managed_target(
        _res(), T, req_vcpu=2, mem_fit=lambda c: c["gib"] >= 7.9, base=BASE)
    assert pick["burst"]["t"] == "db.t4g.large"
    core._apply_managed_pick(out, _res(), pick, BASE)
    # 当前 db.m6g.large 非突发 ⇒ 交付 2.0；t4g.large baseline 0.30 ⇒ 0.6
    assert out["b_delta_vcpu"] == 1.4
    assert out["b_delta_gib"] == 0.0
    assert out["b_save_mo"] == round((0.2300 - 0.2220) * 730, 2)


# ---------------------------------------------------------------- ElastiCache
# ap-east-1 Redis 真实价目。内存取 pricing 的 memory 属性 —— 相邻档比值
# 2.74 / 2.26 / 2.07 全部 > 2，这正是 max_mem_reduction_ratio=2 在这条阶梯上
# 结构性不可满足的原因。
EC_CANDS = [
    {"t": "cache.t4g.micro", "usd": 0.0270, "vcpu": 2, "gib": 0.50,
     "arch": "arm64", "burst": True},
    {"t": "cache.t4g.small", "usd": 0.0520, "vcpu": 2, "gib": 1.37,
     "arch": "arm64", "burst": True},
    {"t": "cache.t4g.medium", "usd": 0.1050, "vcpu": 2, "gib": 3.09,
     "arch": "arm64", "burst": True},
    {"t": "cache.m5.large", "usd": 0.2130, "vcpu": 2, "gib": 6.38,
     "arch": "x86_64", "burst": False},
]
EC_BASE = {"t4g.micro": 0.10, "t4g.small": 0.20, "t4g.medium": 0.20}


def _ec(**kw):
    r = {"rid": "redis-test-01", "service": "elasticache", "engine": "redis",
         "type": "cache.m6g.large", "vcpu": 2, "mem_gib": 6.38,
         "cur_usd": 0.2030, "arch": "arm64", "count": 3,
         "has_replica": True, "evictions_sum": 0, "evictions_p95": 0,
         "repl_lag_p95": 0.001, "repl_lag_max": 0.0,
         "engine_cpu_p95": 0.231, "db_mem_used_pct_max": 6.54,
         "cheaper_candidate_exists": True, "candidates": EC_CANDS}
    r.update(kw)
    return r


def test_elasticache_ladder_step_is_not_blocked_by_a_ratio_floor():
    """P8：ElastiCache 内存阶梯相邻档比值 2.74 / 2.26 / 2.07 全部 > 2。

    把 EC2 的 max_mem_reduction_ratio=2 原样搬过来，conservative 下从
    cache.m6g.large(6.38 GiB) 往下要求候选 >= 3.19 GiB，而下一档
    cache.t4g.medium 只有 3.09 GiB —— 差 3%，永久挡死。实测该做法下
    conservative 的 11 个复制组全部选不出目标，合计 $0。
    """
    for profile in ("aggressive", "conservative"):
        out = core.eval_elasticache(_ec(), core.load_thresholds(profile), EC_BASE)
        assert out["verdict"] == "downsize-candidate", (profile, out["blockers"])
        assert out["burst"] is not None, profile


def test_elasticache_fit_requirement_derives_from_target_mem_p95():
    """`required_gib_usable` 保持纯已用量口径（键名说 usable，值就是可用内存）；
    候选须满足的下限由 target_mem_p95 反推，随 profile 变化。

    形式与 EC2 侧 `_required` 的内存项逐字一致
    （`ceil(cur_gib * sus_mem / target_mem_p95)`），**不新增阈值**。
    先写的版本引入了 managed_mem_headroom（1.5 / 2.0），有两个问题：
    它把 required_gib_usable 乘成了非 usable 口径（撞上
    test_required_gib_usable_is_actually_usable_memory 那条裁定），
    且值 `2.0` 在散文里与「§2.0」满篇冲突，撞上
    test_distinctive_threshold_values_not_restated_in_prose。
    """
    ag = core.eval_elasticache(_ec(), core.load_thresholds("aggressive"), EC_BASE)
    co = core.eval_elasticache(_ec(), core.load_thresholds("conservative"), EC_BASE)
    # 已用可用内存 = 6.38 x 0.75 x 6.54/100 = 0.313 GiB，两档相同
    assert ag["required_gib_usable"] == 0.313
    assert co["required_gib_usable"] == 0.313
    # 候选下限：0.313 / 0.70 = 0.447（ag）、0.313 / 0.50 = 0.626（co）
    assert any("0.447 GiB" in b for b in ag["blockers"]), ag["blockers"]
    assert any("0.626 GiB" in b for b in co["blockers"]), co["blockers"]
    # 两档都排除 cache.t4g.micro（可用 0.375 < 0.447）⇒ 落在 cache.t4g.small
    assert ag["burst"]["t"] == "cache.t4g.small"
    assert co["burst"]["t"] == "cache.t4g.small"


def test_elasticache_savings_multiplied_by_node_count():
    out = core.eval_elasticache(_ec(), core.load_thresholds("aggressive"), EC_BASE)
    assert out["b_save_mo"] == round((0.2030 - 0.0520) * 730 * 3, 2)   # 330.69


def test_elasticache_cross_arch_only_reports_that_reason():
    out = core.eval_elasticache(
        _ec(candidates=[{"t": "cache.m5.large", "usd": 0.1000, "vcpu": 2,
                         "gib": 6.38, "arch": "x86_64", "burst": False}]),
        core.load_thresholds("aggressive"), EC_BASE)
    assert out["verdict"] == "已合理配置"
    assert "跨 CPU 架构" in " ".join(out["blockers"])


def test_elasticache_without_candidates_keeps_old_behaviour():
    r = _ec()
    del r["candidates"]
    out = core.eval_elasticache(r, core.load_thresholds("aggressive"), EC_BASE)
    assert out["verdict"] == "downsize-candidate"
    assert out["nonburst"] is None and out["burst"] is None
    assert any("未经校验" in b for b in out["blockers"])


def test_bottom_of_ladder_forces_low_confidence():
    """乘性余量在极小基数上会给出激进目标：实测一个复制组实占 0.013 GiB，
    x1.5 后仍选到最底档 cache.t4g.micro。倍数余量 19x，绝对量只有
    0.375 GiB 可用 —— 任何数据量增长都会立刻淘汰键。

    护栏判「是否落在同架构阶梯最底档」而不是「距当前几档」：后者要挑一个
    阈值，而同架构比 cache.m6g.large 便宜的候选总共只有 3 档，取 4 等于
    把护栏关掉、取 3 又是为这条阶梯凑的数。
    """
    out = core.eval_elasticache(
        _ec(db_mem_used_pct_max=0.28), core.load_thresholds("aggressive"), EC_BASE)
    assert out["burst"]["t"] == "cache.t4g.micro"
    assert out["confidence"] == "low"
    assert any("最底档" in b for b in out["blockers"])


# ----------------------------------------------------------------------- MSK
# ap-east-1 非 Express broker 真实价目。kafka.m7g 是 Graviton3、kafka.t3 是 x86
# —— 全区比 kafka.m7g.large 便宜的 broker 机型只有 kafka.t3.small 一个，
# 而它跨架构，故 Graviton 集群一个目标都选不出。
MSK_CANDS_ARM_FLEET = [
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
         "cheaper_candidate_exists": True, "candidates": MSK_CANDS_ARM_FLEET}
    r.update(kw)
    return r


def test_msk_graviton_cluster_reports_cross_arch_as_the_reason():
    """实测：kafka.m7g.large 在 ap-east-1 的非 Express broker 价目里更便宜的
    机型只有 kafka.t3.small，而它是 x86。8 个集群一个目标都选不出，但理由从
    「同形态下没有更便宜的候选机型」变成可审计的具体成因。
    """
    out = core.eval_msk(_msk(), core.load_thresholds("aggressive"), {})
    assert out["verdict"] == "已合理配置"
    assert out["nonburst"] is None and out["burst"] is None
    joined = " ".join(out["blockers"])
    assert "kafka.t3.small(x86_64)" in joined
    assert "硬约束禁止项" in joined


def test_msk_at_price_floor_reports_no_cheaper_candidate():
    out = core.eval_msk(
        _msk(type="kafka.t3.small", cur_usd=0.0639, arch="x86_64", candidates=[]),
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


def test_msk_without_candidates_keeps_old_behaviour():
    r = _msk()
    del r["candidates"]
    out = core.eval_msk(r, core.load_thresholds("aggressive"), {})
    assert out["verdict"] == "downsize-candidate"
    assert out["nonburst"] is None and out["burst"] is None
    assert any("未经校验" in b for b in out["blockers"])


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
