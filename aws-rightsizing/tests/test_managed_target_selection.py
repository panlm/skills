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
    """实测教训（客户 123456789012）：旧契约缺必填字段时 86 条托管行全部
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
