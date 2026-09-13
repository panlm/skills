"""RDS 判据：CPU 并行第二判据、峰值项改判持续态、新增的 verdict 出口。

改动前 `dbload_p95` 缺失即 `metric-missing` 并 `return`，而 Performance
Insights 在 db.t2/t3.micro/small、db.t4g.micro/small 上**结构性不支持**，
在任何机型上又都可以只是没开。`metrics-catalog.md` 与 `sample-solve.md`
两处已承诺 CPUUtilization 兜底，`core.py` 里一行都没有。

分支顺序是判据的一部分，见
`docs/specs/2026-09-13-managed-target-selection-design.md` 的 C5。
`_verdict()` 的覆盖坑已踩过三次，三次都是单元测试全绿而真实回放才发现，
所以每个新出口都要验「分支理由排在已 append 的说明之前」。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

# ap-east-1 MySQL Single-AZ 真实价目。内存取 pricing 的 memory 属性。
RDS_CANDS = [
    {"t": "db.t4g.micro", "usd": 0.0280, "vcpu": 2, "gib": 1.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.small", "usd": 0.0560, "vcpu": 2, "gib": 2.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.medium", "usd": 0.1110, "vcpu": 2, "gib": 4.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.large", "usd": 0.2220, "vcpu": 2, "gib": 8.0,
     "arch": "arm64", "burst": True},
    {"t": "db.t4g.xlarge", "usd": 0.4450, "vcpu": 4, "gib": 16.0,
     "arch": "arm64", "burst": True},
    {"t": "db.m6g.xlarge", "usd": 0.4600, "vcpu": 4, "gib": 16.0,
     "arch": "arm64", "burst": False},
    {"t": "db.r6g.xlarge", "usd": 0.5610, "vcpu": 4, "gib": 32.0,
     "arch": "arm64", "burst": False},
    {"t": "db.t4g.2xlarge", "usd": 0.8900, "vcpu": 8, "gib": 32.0,
     "arch": "arm64", "burst": True},
]
BASE = {"t4g.micro": 0.10, "t4g.small": 0.20, "t4g.medium": 0.20,
        "t4g.large": 0.30, "t4g.xlarge": 0.40, "t4g.2xlarge": 0.40}
T_AG = core.load_thresholds("aggressive")
T_CO = core.load_thresholds("conservative")


def _rds(**kw):
    """db-sit-01 的真实观测：CPU 持续 p95 2.82%、Maximum 序列 p95 4.92%
    （max 42.01%）、DBLoad Average p95 0.001 / Maximum p95 1.0、
    FreeableMemory 最小值 5.110 GiB、FreeStorageSpace 191.6 GiB 几乎不动。"""
    r = {"rid": "db-sit-01", "service": "rds", "type": "db.m6g.large",
         "vcpu": 2, "mem_gib": 8.0, "cur_usd": 0.2300, "arch": "arm64",
         "count": 1, "pi_enabled": True,
         "sus_cpu": 2.82, "peak_cpu_p95": 4.92,
         "dbload_p95": 0.001, "dbload_max_p95": 1.0,
         "freeable_mem_min_gib": 5.110,
         "surplus_credits": 0,
         "cheaper_candidate_exists": True, "candidates": RDS_CANDS}
    r.update(kw)
    return r


# ------------------------------------------------------- CPU 轴与峰值项口径

def test_rds_survives_missing_dbload_via_cpu_axis():
    """P4：`dbload_p95` 缺失不再是死胡同。CPUUtilization 采集侧已经在采
    （`cli-recipes.md` §2.3 mdq 列表第一项），兜底零新增 API 调用。"""
    out = core.eval_rds(_rds(dbload_p95=None, dbload_max_p95=None), T_AG, BASE)
    assert out["verdict"] == "downsize-candidate", out["blockers"]
    assert any("Performance Insights" in b for b in out["blockers"])


def test_rds_pi_unsupported_class_and_pi_off_get_different_blockers():
    """两种成因的动作不同：前者要换机型才能拿到 DBLoad，后者改个开关即可。"""
    unsupported = core.eval_rds(
        _rds(type="db.t4g.small", vcpu=2, mem_gib=2.0, cur_usd=0.0560,
             dbload_p95=None, dbload_max_p95=None, freeable_mem_min_gib=1.2,
             candidates=[c for c in RDS_CANDS if c["usd"] < 0.0560]),
        T_AG, BASE)
    assert any("结构性不支持" in b for b in unsupported["blockers"]), \
        unsupported["blockers"]
    off = core.eval_rds(_rds(dbload_p95=None, dbload_max_p95=None,
                             pi_enabled=False), T_AG, BASE)
    assert any("未开启" in b for b in off["blockers"])
    assert not any("结构性不支持" in b for b in off["blockers"])


def test_rds_peak_term_uses_persistent_not_single_spike():
    """P9：db-uat-01 实测 CPU 持续 p95 4.00%，Maximum 序列 max 88.33% /
    p95 7.89%。按 max 反推需 ceil(2 x 88.33 / 85) = 3 vCPU（超过现有 2）
    ⇒ 一台常态 4% 的库看起来满载。12 台按 max 判，aggressive 只剩 2 台可降、
    conservative 0 台，与 DBLoad 结论大面积冲突。

    EC2 侧 `peak_cpu` 仍取 max —— 那里的尖峰是真实业务负载；RDS 的可证明
    来自备份窗口与自动小版本升级，与 MSK URP / Redis ReplicationLag 同类。
    """
    out = core.eval_rds(_rds(sus_cpu=4.00, peak_cpu_p95=7.89), T_AG, BASE)
    assert out["required_vcpu"] == 1     # ceil(2x4.00/60)=1, ceil(2x7.89/85)=1
    assert out["verdict"] == "downsize-candidate"


def test_rds_req_vcpu_takes_max_of_cpu_and_dbload_axes():
    # DBLoad 轴 ceil(1.6/0.5)=4；CPU 轴 1 ⇒ 取 4
    out = core.eval_rds(_rds(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0,
                             cur_usd=0.9190, dbload_p95=1.6,
                             dbload_max_p95=3.0, freeable_mem_min_gib=20.0),
                        T_AG, BASE)
    assert out["required_vcpu"] == 4


def test_rds_missing_peak_only_uses_sustained_and_says_so():
    out = core.eval_rds(_rds(peak_cpu_p95=None), T_AG, BASE)
    assert out["verdict"] == "downsize-candidate"
    assert any("只用持续项" in b for b in out["blockers"])


def test_rds_both_axes_missing_is_metric_missing():
    out = core.eval_rds(_rds(sus_cpu=None, peak_cpu_p95=None,
                             dbload_p95=None, dbload_max_p95=None), T_AG, BASE)
    assert out["verdict"] == "metric-missing"
    assert "两轴都缺" in out["blockers"][0]


# --------------------------------------------------------------- 选型与适配

def test_rds_picks_t4g_medium_for_the_idle_sit_instance():
    """需求 2 vCPU / 3.40 GiB（=(8−5.110)/(1−15%)）⇒ db.t4g.medium(4 GiB)。

    布尔值 cheaper_candidate_exists 为 true 时最近的更便宜候选是
    db.t4g.large，只省 $5.84/mo；装得下需求的最便宜目标省 $86.87/mo。
    """
    for t in (T_AG, T_CO):
        out = core.eval_rds(_rds(), t, BASE)
        assert out["verdict"] == "downsize-candidate"
        assert out["required_gib"] == 3.4
        assert out["burst"]["t"] == "db.t4g.medium"
        assert out["b_save_mo"] == round((0.2300 - 0.1110) * 730, 2)   # 86.87


def test_rds_memory_bound_instance_only_reaches_t4g_large():
    """db-infra-01 实测 FreeableMemory 最小值 3.167 GiB ⇒ 已用 4.833 GiB ⇒
    需 5.686 GiB ⇒ 只能到 db.t4g.large，省 $5.84/mo。诚实的小数字。"""
    out = core.eval_rds(_rds(sus_cpu=6.05, peak_cpu_p95=9.67,
                             dbload_p95=0.186, dbload_max_p95=23.0,
                             freeable_mem_min_gib=3.167), T_AG, BASE)
    assert out["burst"]["t"] == "db.t4g.large"
    assert out["b_save_mo"] == round((0.2300 - 0.2220) * 730, 2)       # 5.84


def test_rds_pi_unsupported_candidate_excluded_with_forgone_amount():
    """量化的必须是「本来装得下、只因排除才没选」的那一个。

    实测 req 1.765 GiB 时最便宜的被排除候选是 db.t4g.micro(1.0 GiB)，
    它压根装不下 —— 报它的差价 $147.46 是误导。正确答案是
    db.t4g.small(2.0 GiB) 的 $127.02，所以 `exclude` 必须在适配筛选之后应用。
    """
    out = core.eval_rds(_rds(freeable_mem_min_gib=6.5), T_AG, BASE)
    # 已用 1.5 GiB ⇒ 需 1.765 GiB ⇒ db.t4g.small(2 GiB) 本可装下，但它不支持 PI
    assert out["burst"]["t"] == "db.t4g.medium"
    note = [b for b in out["blockers"] if "db.t4g.small" in b]
    assert note, out["blockers"]
    assert "不支持 Performance Insights" in note[0]
    assert str(round((0.2300 - 0.0560) * 730, 2)) in note[0]


def test_rds_pi_disabled_does_not_exclude_unsupported_classes():
    out = core.eval_rds(_rds(freeable_mem_min_gib=6.5, pi_enabled=False,
                             dbload_p95=None, dbload_max_p95=None),
                        T_AG, BASE)
    assert out["burst"]["t"] == "db.t4g.small"


def test_rds_without_candidates_keeps_old_behaviour():
    r = _rds()
    del r["candidates"]
    out = core.eval_rds(r, T_AG, BASE)
    assert out["verdict"] == "downsize-candidate"
    assert out["nonburst"] is None and out["burst"] is None
    assert any("未经校验" in b for b in out["blockers"])


# ------------------------------------------------------------ 新的 upsize 出口

def test_rds_cpu_sustained_over_current_yields_upsize():
    """P5：db-uat-05 实测 CPU 持续 p95 69.64%（4 vCPU），而 DBLoad p95 2.328
    差 0.328 就跨过 0.5x4=2.0 的阈值 ⇒ 现行判「已合理配置」。"""
    out = core.eval_rds(
        _rds(type="db.m6g.xlarge", vcpu=4, mem_gib=16.0, cur_usd=0.4600,
             sus_cpu=69.64, peak_cpu_p95=71.09, dbload_p95=2.328,
             dbload_max_p95=11.0, freeable_mem_min_gib=0.864), T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"
    assert "CPU 持续 p95 69.64%" in out["blockers"][0]
    assert "不产出升配目标机型" in out["blockers"][0]


def test_rds_freeable_memory_floor_stays_blocked_not_upsize():
    """本轮 spec 曾提议把这条从 blocked 升为 upsize-candidate，
    既有守卫测试反对，**而它是对的**。

    MySQL / PostgreSQL 的 InnoDB buffer pool 有意占满可分配内存，
    `FreeableMemory` 报的是 MemAvailable —— 一个 buffer pool 配置正确的库
    按设计就是低 freeable。实测这台可用内存剩 9.7%，但 DBLoad p95 1.211
    （8 vCPU）、CPU 14.87%，完全不缺算力。证据支持「缩不了」，
    不支持「需要更大的实例」。欠配判定归 CPU 持续项那条出口。
    """
    out = core.eval_rds(
        _rds(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0, cur_usd=0.9190,
             sus_cpu=14.87, peak_cpu_p95=18.97, dbload_p95=1.211,
             dbload_max_p95=9.0, freeable_mem_min_gib=3.098), T_AG, BASE)
    assert out["verdict"] == "blocked"
    assert "降配会 OOM" in out["blockers"][0]
    assert "不是规格不足" in out["blockers"][0]


def test_rds_empty_pool_short_circuits_before_metric_fail_closed():
    """候选集为空 ⇒ 已合理配置，且**早于**信用与 FreeableMemory 的 fail-closed。

    否则会让客户为一条不可能产出的建议去开 PI / 补 FreeableMemory、
    再等一个完整窗口。这是 eval_rds 原有的裁定，本轮只把那个采集侧布尔值
    换成带成因的探针，顺序不变。
    """
    out = core.eval_rds(
        _rds(candidates=[], cheaper_candidate_exists=False,
             freeable_mem_min_gib=None, surplus_credits=None), T_AG, BASE)
    assert out["verdict"] == "已合理配置"
    assert any("未评估内存压力" in b for b in out["blockers"])


def test_rds_upsize_precedes_empty_candidate_pool():
    """欠配否决必须排在候选池判定之前：候选集为空不该压掉
    「这台机器已经不够用了」这条警告。"""
    out = core.eval_rds(
        _rds(candidates=[], cheaper_candidate_exists=False,
             sus_cpu=69.64, peak_cpu_p95=71.09), T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"


def test_rds_verdict_reasons_precede_appended_notes_at_every_exit():
    r = _rds(partial_coverage=[("CPUCreditBalance", 178, 720)],
             sus_cpu=69.64, peak_cpu_p95=71.09)
    out = core.eval_rds(r, T_AG, BASE)
    assert out["verdict"] == "upsize-candidate"
    assert "CPU 持续" in out["blockers"][0]              # 分支理由在最前
    assert any("覆盖不齐" in b for b in out["blockers"])   # 已 append 的没被吞


def test_rds_existing_veto_exits_unchanged():
    """既有三条出口不得因重排而失效。"""
    assert core.eval_rds(_rds(surplus_credits=730.6), T_AG,
                         BASE)["verdict"] == "upsize-candidate"
    assert core.eval_rds(_rds(type="db.serverless"), T_AG,
                         BASE)["verdict"] == "excluded"
    assert core.eval_rds(_rds(dbload_p95=2.5, dbload_max_p95=5.0), T_AG,
                         BASE)["verdict"] == "blocked"       # >= vcpu 2
    assert core.eval_rds(_rds(dbload_p95=1.2, dbload_max_p95=3.0), T_AG,
                         BASE)["verdict"] == "已合理配置"      # >= 0.5 x 2


# ---------------------------------------------- PI 不支持列表的唯一真值源

def test_pi_unsupported_list_is_loaded_from_json():
    classes = core.load_pi_unsupported()
    assert "db.t4g.small" in classes and "db.t3.micro" in classes
    assert "db.t4g.medium" not in classes


# --------------------------------------------------- FreeStorageSpace 耐久度

def _rds_storage(**kw):
    """db-sit-01 的存储观测：200 GB gp2，free 191.588–191.613 GiB，
    30 天只涨了 25 MB。"""
    defaults = {"storage_free_min_gib": 191.588,
                "storage_free_first_gib": 191.613,
                "storage_free_last_gib": 191.589, "window_days": 30}
    defaults.update(kw)
    return _rds(**defaults)


def test_rds_storage_exhausted_in_window_is_blocked_as_availability_incident():
    """P6：`FreeStorageSpace` 被采集、被聚合，全代码库零引用。

    db-sit-05 实测 Minimum 序列最小值 = 0.000 GB（400 GB gp3），
    Average 序列最小值 0.919 GB，窗口内 free 在 0–103 GB 间摆动。
    这台在报告里唯一的结论是「FreeableMemory < 15%，降配会 OOM」——
    磁盘被写满过这件事不存在。
    """
    out = core.eval_rds(
        _rds_storage(type="db.m6g.2xlarge", vcpu=8, mem_gib=32.0,
                     cur_usd=0.9190, sus_cpu=14.26, peak_cpu_p95=19.02,
                     dbload_p95=1.070, dbload_max_p95=10.0,
                     freeable_mem_min_gib=12.0,
                     storage_free_min_gib=0.0,
                     storage_free_first_gib=103.763,
                     storage_free_last_gib=67.827), T_AG, BASE)
    assert out["verdict"] == "blocked"
    assert "可用性事故" in out["blockers"][0]
    assert "storage autoscaling" in out["blockers"][0]


def test_rds_storage_runway_below_floor_blocks():
    # 30 天消耗 191.613 − 11.613 = 180 GiB ⇒ 6 GiB/日，剩 11.613/6 = 1.9 天
    low = core.eval_rds(_rds_storage(storage_free_last_gib=11.613,
                                     storage_free_min_gib=11.613), T_AG, BASE)
    assert low["verdict"] == "blocked"
    assert "storage autoscaling" in " ".join(low["blockers"])
    # 30 天消耗 50 GiB ⇒ 1.667 GiB/日，剩 141.613/1.667 = 85 天 ⇒ 不触发
    ok = core.eval_rds(_rds_storage(storage_free_last_gib=141.613,
                                    storage_free_min_gib=141.613), T_AG, BASE)
    assert ok["verdict"] == "downsize-candidate"


def test_rds_storage_flat_or_growing_free_space_does_not_extrapolate():
    """free 不减（速率 <= 0）时不外推 —— 否则会算出负天数。"""
    out = core.eval_rds(_rds_storage(storage_free_first_gib=180.0,
                                     storage_free_last_gib=191.589), T_AG, BASE)
    assert out["verdict"] == "downsize-candidate"


def test_rds_storage_fields_missing_does_not_fail_closed():
    out = core.eval_rds(_rds(), T_AG, BASE)          # 不带任何 storage_* 字段
    assert out["verdict"] == "downsize-candidate"
    assert any("FreeStorageSpace 缺失" in b for b in out["blockers"])


def test_rds_storage_check_runs_after_the_pool_probe():
    """存储判据也不得早于候选池探针：候选集为空时它同样是"补了也没用"。"""
    out = core.eval_rds(
        _rds_storage(candidates=[], cheaper_candidate_exists=False,
                     storage_free_min_gib=0.0), T_AG, BASE)
    assert out["verdict"] == "已合理配置"
