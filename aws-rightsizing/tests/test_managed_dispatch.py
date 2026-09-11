"""main() 的 service 分派、三个托管判据（含否决项两半）、桶归类、is_idle、桶 C。

这些路径此前**一个测试都没有**：main() 把所有资源都喂给 evaluate()，
于是 eval_rds / eval_elasticache / eval_msk 零调用点，指标齐全的托管服务
资源被判成 metric-missing 而没人发现。

否决项必须测**两半**：指标缺失 ⇒ metric-missing，以及指标越界 ⇒ blocked。
只测前一半会让「删掉 OOM 否决」这类改动全绿通过——实测十个否决/抑制分支
被逐个删除时，八个测试文件全部 exit 0。
"""
import json, pathlib, re, subprocess, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

CORE = ROOT / "references" / "core.py"

# EC2 侧上下文。ebs 是真实基线吞吐（m5.xlarge 1,150 Mbps = 143.75 MB/s）
EC2_SPECS = [{"t": "m5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
              "arch": "x86_64", "store": False, "ebs": 143.75, "curgen": True},
             {"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
              "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True}]


def _ctx(resources):
    return {"sizing_profile": "aggressive", "specs": EC2_SPECS,
            "prices": {"m5.xlarge|RunInstances": 0.192,
                       "m5.large|RunInstances": 0.096},
            "baseline_pct": {}, "categories": {"m5.xlarge": "General purpose",
                                               "m5.large": "General purpose"},
            "offerings": ["m5.xlarge", "m5.large"], "legacy_families": [],
            "resources": resources}


def _run(ctx):
    return subprocess.run([sys.executable, str(CORE)], input=json.dumps(ctx),
                          capture_output=True, text=True)


def _findings(ctx):
    p = _run(ctx)
    assert p.returncode == 0, p.stderr
    return {f["rid"]: f for f in json.loads(p.stdout)}


RDS_OK = {"rid": "db-T-01", "service": "rds", "type": "db.r6g.large",
          "vcpu": 2, "mem_gib": 16, "surplus_credits": 0, "dbload_p95": 0.4,
          "freeable_mem_min_gib": 9.6, "sample_n": 243,
          "cheaper_candidate_exists": True}
CACHE_OK = {"rid": "cache-T-01", "service": "elasticache", "has_replica": False, "engine": "redis",
            "type": "cache.r7g.large", "vcpu": 2, "mem_gib": 13.07,
            "evictions_sum": 0, "repl_lag_max": 0.2, "engine_cpu_p95": 12,
            "db_mem_used_pct_max": 35, "sample_n": 243, "cheaper_candidate_exists": True}
MSK_OK = {"rid": "msk-T-01", "service": "msk", "type": "kafka.m7g.xlarge",
          "under_replicated_max": 0, "disk_used_max": 18,
          "handler_idle_p95": 0.94, "cpu_total_p95": 15, "sample_n": 243,
          "cheaper_candidate_exists": True}
EC2_OK = {"rid": "i-T-01", "service": "ec2", "type": "m5.xlarge",
          "arch": "x86_64", "operation": "RunInstances", "sus_cpu": 10,
          "peak_cpu": 25, "sus_mem": 20, "peak_mem": 35, "ebs_need": 5,
          "surplus_credits": 0, "cpu_n": 243, "metric_coverage": []}


def test_managed_resources_reach_their_own_evaluators():
    """指标齐全的托管服务资源必须判出结论，不得是 metric-missing。

    这是 C4 的回归：main() 只调 evaluate() 时，三条资源全部报
    「CPU 指标缺失」——它们的指标名是 dbload_p95 / engine_cpu_p95 /
    cpu_total_p95，evaluate() 找的是 sus_cpu / peak_cpu。
    """
    got = _findings(_ctx([RDS_OK, CACHE_OK, MSK_OK, EC2_OK]))
    assert len(got) == 4, got
    for rid in ("db-T-01", "cache-T-01", "msk-T-01"):
        assert got[rid]["verdict"] == "downsize-candidate", (rid, got[rid])
        assert got[rid]["bucket"] == "downsize", (rid, got[rid])
        assert got[rid]["blockers"], f"{rid} 必须给出 blockers"
    assert got["db-T-01"]["service"] == "rds"
    assert got["cache-T-01"]["service"] == "elasticache"
    assert got["msk-T-01"]["service"] == "msk"
    # EC2 路径不受影响，且 service 列在两条路径上都存在
    assert got["i-T-01"]["service"] == "ec2"
    assert got["i-T-01"]["verdict"] == "downsize"


def test_absent_service_raises_instead_of_defaulting_to_ec2():
    """service 缺失必须抛错。静默走 EC2 路径正是被修的缺陷本身。"""
    res = dict(RDS_OK)
    res.pop("service")
    p = _run(_ctx([res]))
    assert p.returncode != 0, f"service 缺失竟然成功了：{p.stdout[:200]}"
    # 必须是分派自己的报错。只断言「非零退出」会被后面某行偶然的 KeyError
    # 满足——那时 service 已经悄悄按 ec2 判过一遍了。
    assert "必填" in p.stderr and "ec2" in p.stderr, p.stderr
    assert not p.stdout.strip(), "抛错时不得已经输出部分 findings"


def test_unknown_service_raises():
    """不认识的 service 同样抛错，并列出合法取值。"""
    p = _run(_ctx([dict(RDS_OK, service="dynamodb")]))
    assert p.returncode != 0, p.stdout[:200]
    assert "dynamodb" in p.stderr and "ec2" in p.stderr, p.stderr


def test_upsize_candidate_never_lands_in_a_savings_bucket():
    """规格已不足的资源不得进 downsize/idle 桶——那会被读成可节省项。"""
    got = _findings(_ctx([dict(RDS_OK, rid="db-T-02", type="db.t4g.medium",
                              mem_gib=4, surplus_credits=730.6,
                              dbload_p95=0.547, freeable_mem_min_gib=1.2)]))
    f = got["db-T-02"]
    assert f["verdict"] == "upsize-candidate", f
    assert f["bucket"] == "excluded", f


def test_managed_resource_never_enters_idle_bucket():
    """托管服务不进桶 B：闲置判据的指标只在 EC2 侧定义。

    这条资源同时带齐了 is_idle 需要的 sus_cpu / net_mb_day / cpu_n，
    若 main() 把托管资源也送进 is_idle，它会被判 idle 并附上一段面向 EC2 的
    blockers 文案——而 RDS 的闲置根本没被评估过。「没评估」伪装成「不闲置」
    或「闲置」都是静默错答，方向不同而已。
    """
    got = _findings(_ctx([dict(RDS_OK, rid="db-T-03", sus_cpu=0,
                               net_mb_day=0, cpu_n=243)]))
    assert got["db-T-03"]["bucket"] == "downsize", got["db-T-03"]
    assert isinstance(got["db-T-03"]["blockers"], list)


def test_msk_handler_idle_is_read_on_0_1_scale():
    """RequestHandlerAvgIdlePercent 是 0–1 刻度，阈值键也按 0–1 写。

    换成任何 0–100 刻度的键（如 msk_target_cpu_p95），0.94 会 <= 阈值，
    这条资源就从 downsize-candidate 变成「已合理配置」。
    """
    t = core.load_thresholds("aggressive")
    busy = core.eval_msk(dict(MSK_OK, handler_idle_p95=0.5), t)
    assert busy["verdict"] == "已合理配置", busy
    idle = core.eval_msk(MSK_OK, t)
    assert idle["verdict"] == "downsize-candidate", idle


def test_missing_veto_metrics_yield_metric_missing_not_a_pass():
    """否决项**指标缺失**这一半：⇒ metric-missing，不得当 0 放行。

    原名叫 ..._vetoes_fail_closed_on_missing_metrics，读起来像覆盖了否决项，
    实际只覆盖缺失半边。越界半边由 test_managed_vetoes_actually_fire_and_block
    覆盖——两个名字各自只承诺自己断言的东西。
    """
    t = core.load_thresholds("aggressive")
    # RDS 用 burstable 实例测信用指标缺失：非 burstable 不发布该指标，不测它
    rds_burstable = dict(RDS_OK, type="db.t4g.medium", mem_gib=4)
    for label, out in (
            ("MSK UnderReplicatedPartitions",
             core.eval_msk(dict(MSK_OK, under_replicated_max=None), t)),
            ("ElastiCache Evictions",
             core.eval_elasticache(dict(CACHE_OK, evictions_sum=None), t)),
            ("RDS CPUSurplusCreditsCharged",
             core.eval_rds(dict(rds_burstable, surplus_credits=None), t))):
        assert out["verdict"] == "metric-missing", \
            f"{label} 缺失必须 metric-missing，不得当 0 放行：{out}"
    # 0 是有效值，必须继续判下去
    zero = core.eval_msk(dict(MSK_OK, under_replicated_max=0), t)
    assert zero["verdict"] == "downsize-candidate", f"0 是有效值，不是缺失：{zero}"


def test_managed_vetoes_actually_fire_and_block():
    """否决项**指标越界**这一半：必须判 blocked，且不得退化成降配建议。

    这是本 skill 唯一会造成故障的错误方向：把 OOM 边缘的库、正在淘汰键的
    缓存、有 under-replicated 分区的集群判成可降配。三条删掉任一条，
    verdict 都从 blocked 变成 downsize-candidate，且全部静默。
    """
    t = core.load_thresholds("aggressive")
    # ① RDS：FreeableMemory 最小值低于 rds_freeable_mem_floor_pct × 实例内存 ⇒ 降配会 OOM
    oom = core.eval_rds(dict(RDS_OK, freeable_mem_min_gib=0.5), t)
    assert oom["verdict"] == "blocked", f"降配会 OOM 的库必须 blocked，得到 {oom}"
    assert any("OOM" in b for b in oom["blockers"]), oom["blockers"]
    # ② RDS：DBLoad p95 >= vCPU ⇒ CPU 已是瓶颈。注意与「未低于 ratio×vCPU」是两档：
    #    2.5 >= vcpu 2 走 blocked；1.5 只越过 ratio×vCPU=1.0，走「已合理配置」
    bottleneck = core.eval_rds(dict(RDS_OK, dbload_p95=2.5), t)
    assert bottleneck["verdict"] == "blocked", \
        f"DBLoad p95 2.5 >= vCPU 2，CPU 已是瓶颈，必须 blocked：{bottleneck}"
    near = core.eval_rds(dict(RDS_OK, dbload_p95=1.5), t)
    assert near["verdict"] == "已合理配置", \
        f"只越过 rds_dbload_ratio×vCPU 的应是「已合理配置」而非 blocked：{near}"
    # ③ ElastiCache：Evictions > 0 ⇒ 内存已不足，降配更糟
    ev = core.eval_elasticache(dict(CACHE_OK, evictions_sum=4821), t)
    assert ev["verdict"] == "blocked", f"已在淘汰键的缓存必须 blocked，得到 {ev}"
    # ④ ElastiCache：复制延迟越界
    lag = core.eval_elasticache(
        dict(CACHE_OK, repl_lag_max=t["redis_repl_lag_max_s"] + 2), t)
    assert lag["verdict"] == "blocked", f"复制延迟越界必须 blocked，得到 {lag}"
    # ⑤ MSK：UnderReplicatedPartitions > 0 ⇒ 集群已降级
    urp = core.eval_msk(dict(MSK_OK, under_replicated_max=7), t)
    assert urp["verdict"] == "blocked", f"有 under-replicated 分区必须 blocked，得到 {urp}"
    # ⑥ RDS：信用超额 ⇒ upsize-candidate（升配候选，不是降配候选）
    up = core.eval_rds(dict(RDS_OK, surplus_credits=730.6), t)
    assert up["verdict"] == "upsize-candidate", f"信用超额必须 upsize，得到 {up}"


def test_rds_credit_veto_outranks_dbload_and_memory():
    """否决项之间的优先级：信用超额高于 DBLoad 与 FreeableMemory。

    实测来源就是这个组合——DBLoad 低（前置"满足"）但信用已超额。若把信用检查
    挪到 DBLoad 之后，这台机器会被判 blocked 或 downsize-candidate，
    而正确结论是升配。顺序本身就是判据，不能只测各分支单独成立。
    """
    t = core.load_thresholds("aggressive")
    worst = dict(RDS_OK, surplus_credits=730.6, dbload_p95=2.5,
                 freeable_mem_min_gib=0.5)
    out = core.eval_rds(worst, t)
    assert out["verdict"] == "upsize-candidate", f"信用否决必须最先命中，得到 {out}"
    assert "CPUSurplusCreditsCharged" in " ".join(out["blockers"]), out["blockers"]


def test_ec2_idle_bucket_treats_zero_traffic_as_idle():
    """net_mb_day=0 是最强闲置信号，不得被当成缺失。is_idle + main() 的唯一覆盖。"""
    got = _findings(_ctx([dict(EC2_OK, rid="i-T-02", sus_cpu=1, peak_cpu=3,
                               net_mb_day=0, ebs_need=0)]))
    f = got["i-T-02"]
    assert f["bucket"] == "idle", f
    # blockers 是字符串数组（与三条托管判据同一类型），不是拼接出来的长字符串
    assert isinstance(f["blockers"], list), type(f["blockers"])
    blob = " ".join(f["blockers"])
    assert "不证明可删除" in blob, f["blockers"]
    # 命中 idle 时降配方案降级进 blockers，不另起一行
    assert "若须保持运行" in blob, f["blockers"]


def test_blockers_is_a_list_on_every_row():
    """`blockers` 在四条判据与 idle 路径上必须是同一种类型：字符串数组。

    过去托管侧是 list、EC2 的 idle 行是字符串拼接。同一个 CSV 列两种类型时，
    写出侧无论假定哪一种都会在另一半资源上出错，而且是静默的——
    对字符串做 join 会把它逐字符拆开，不报错。
    """
    got = _findings(_ctx([RDS_OK, CACHE_OK, MSK_OK, EC2_OK,
                          dict(EC2_OK, rid="i-T-04", sus_cpu=1, peak_cpu=3,
                               net_mb_day=0, ebs_need=0)]))
    assert got["i-T-04"]["bucket"] == "idle", got["i-T-04"]      # idle 路径确实走到了
    for rid, f in got.items():
        assert isinstance(f["blockers"], list), (rid, type(f["blockers"]))
        assert all(isinstance(s, str) for s in f["blockers"]), (rid, f["blockers"])


STOP_BANDS_OK = {"off_sus_cpu": 1, "off_peak_cpu": 8, "off_net_mb_day": 1,
                 "weekend_sus_cpu": 1, "weekend_peak_cpu": 8, "weekend_net_mb_day": 1}


def test_stop_candidate_is_three_state_and_defaults_to_unknown():
    """桶 C 候选是 True / False / None 三态，缺输入必须是 None 而不是 False。

    「没评估」显示成「不是候选」是最坏的静默降级：报告会看起来像
    "已经查过、没有可停的"。桶 C 的产出是候选清单 + 证据，判断权在执行方。
    """
    t = core.load_thresholds("aggressive")
    base = dict(EC2_OK)
    # ① 六个 off/weekend 字段全缺 ⇒ None（当前 solver-in 组装式的默认情形）
    assert core.is_stop_candidate(base, t) is None
    # ② 只给一档 ⇒ 仍然 None（两档必须都有）
    half = dict(base, off_sus_cpu=1, off_peak_cpu=8, off_net_mb_day=1)
    assert core.is_stop_candidate(half, t) is None
    # ③ 两档齐全且都很闲 ⇒ True
    assert core.is_stop_candidate(dict(base, **STOP_BANDS_OK), t) is True
    # ④ 采样量不足 ⇒ None，不得是 False
    assert core.is_stop_candidate(dict(base, cpu_n=13, **STOP_BANDS_OK), t) is None
    # ⑤ main() 把它放进独立一列，且托管服务行恒为 null
    got = _findings(_ctx([dict(EC2_OK, rid="i-T-05", **STOP_BANDS_OK), RDS_OK]))
    assert got["i-T-05"]["stop_candidate"] is True, got["i-T-05"]
    assert got["db-T-01"]["stop_candidate"] is None, got["db-T-01"]
    # 桶 C 与桶归类互不影响：这台仍然是 downsize
    assert got["i-T-05"]["bucket"] == "downsize", got["i-T-05"]


def test_stop_candidate_needs_all_three_signals():
    """三个门限任一不过就是 False。只看 CPU 会把被动监听型服务判成可停。"""
    t = core.load_thresholds("aggressive")
    base = dict(EC2_OK, **STOP_BANDS_OK)
    assert core.is_stop_candidate(base, t) is True
    # 网络超门限（CPU 依然很闲）⇒ False
    assert core.is_stop_candidate(dict(base, weekend_net_mb_day=500), t) is False
    # 峰值超 stop_candidate_peak_cpu_max（p95 依然很闲）⇒ False
    over = t["stop_candidate_peak_cpu_max"] + 1
    assert core.is_stop_candidate(dict(base, off_peak_cpu=over), t) is False
    # 峰值正好等于门限 ⇒ 仍是候选（判据写的是「无峰值 > 上限」）
    assert core.is_stop_candidate(
        dict(base, off_peak_cpu=t["stop_candidate_peak_cpu_max"]), t) is True


def test_stop_candidate_peak_gate_comes_from_thresholds():
    """峰值门限必须来自 thresholds.json，不得写死在 core.py 里。"""
    strict = core.load_thresholds("aggressive",
                                  override={"stop_candidate_peak_cpu_max": 1})
    res = dict(EC2_OK, **STOP_BANDS_OK)          # off/weekend 峰值都是 8
    assert core.is_stop_candidate(res, core.load_thresholds("aggressive")) is True
    assert core.is_stop_candidate(res, strict) is False, "调低门限后结果没变：值被写死了"


def test_ec2_missing_network_is_not_idle():
    """net_mb_day 缺失 ⇒ 不得判闲置（fail-closed）。"""
    got = _findings(_ctx([dict(EC2_OK, rid="i-T-03", sus_cpu=1, peak_cpu=3,
                               net_mb_day=None, ebs_need=0)]))
    assert got["i-T-03"]["bucket"] != "idle", got["i-T-03"]


def test_sample_solve_managed_block_reproduces():
    """sample-solve.md 的托管样例必须能被当前 core.py 重新跑出同样的判定。"""
    doc = (ROOT / "references" / "sample-solve.md").read_text()
    resources = []
    for block in re.findall(r"```json\n(\[.*?\])\n```", doc, re.S):
        resources += [r for r in json.loads(block) if r.get("service") != "ec2"]
    assert resources, "sample-solve.md 缺少托管服务输入样例"
    got = _findings(_ctx(resources))
    assert got["db-EX-01"]["verdict"] == "downsize-candidate", got["db-EX-01"]
    assert got["db-EX-02"]["verdict"] == "upsize-candidate", got["db-EX-02"]
    assert got["db-EX-02"]["bucket"] == "excluded", got["db-EX-02"]
    assert got["cache-EX-01"]["required_gib_usable"] == 3.431, got["cache-EX-01"]
    assert got["msk-EX-01"]["verdict"] == "downsize-candidate", got["msk-EX-01"]


def test_managed_low_sample_downgrades_instead_of_refusing():
    """托管三判据在样本不足时仍须跑完判据、报出否决项。

    旧行为：sample_n < floor ⇒ dispatch() 立即 return insufficient-data，
    连否决项都不跑。实测（某 ap-east-1 机队）两条真实健康事实
    （MSK URP 27、Redis 复制延迟 23.88s）因此被一句「点数不足」盖住 ——
    而否决项读的是 max，不是 p95，采样量挡它没有依据。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = {
        "rds": dict(rid="db-X", service="rds", type="db.r6g.large", vcpu=2,
                    mem_gib=16, surplus_credits=0, dbload_p95=0.1,
                    freeable_mem_min_gib=8.0, cheaper_candidate_exists=True),
        "elasticache": dict(rid="cc-X", service="elasticache", has_replica=False, engine="redis",
                            type="cache.m6g.large", vcpu=2, mem_gib=6.38,
                            evictions_sum=0, repl_lag_max=0.0,
                            engine_cpu_p95=1.0, db_mem_used_pct_max=2.0,
                            cheaper_candidate_exists=True),
        "msk": dict(rid="mk-X", service="msk", type="kafka.m7g.large",
                    under_replicated_max=0, disk_used_max=10.0,
                    handler_idle_p95=0.99, cpu_total_p95=3.0,
                    cheaper_candidate_exists=True),
    }
    for svc, res in cases.items():
        res["sample_n"] = floor - 1
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "downsize-candidate", (
            f"{svc}: 样本不足仍应跑完判据，实际 {got['verdict']} —— {got}")
        blockers = " ".join(got.get("blockers") or [])
        assert "样本" in blockers and str(floor) in blockers, (
            f"{svc}: blockers 未写明样本量与门限 —— {got.get('blockers')}")
        assert got.get("confidence") == "low", (
            f"{svc}: 低样本托管行必须带 confidence=low，否则 report-template 的"
            f"「低样本须标样本量」与「摘要给 low 的 breakout」两条规则对托管服务"
            f"永远不触发 —— {got}")
    for svc, res in cases.items():
        res["sample_n"] = floor
        got = core.dispatch(res, {"thresholds": t})
        assert "样本" not in " ".join(got.get("blockers") or []), (
            f"{svc}: 样本充足不应出现样本量 blocker —— {got}")
        assert "confidence" not in got, (
            f"{svc}: 样本充足的托管行不设 confidence（上两档是 EC2 的内存轴）—— {got}")


def test_managed_zero_sample_stays_insufficient():
    """0 点是「无」不是「少」，仍须 fail-closed（缺失那条见下一个测试）。"""
    t = core.load_thresholds("aggressive")
    res = dict(rid="mk-Z", service="msk", type="kafka.m7g.large",
               under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0, sample_n=0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "insufficient-data", got


def test_vetoes_judge_persistence_not_a_single_spike():
    """三条否决项判持续态，不判「曾经出现过」。

    实测（某 ap-east-1 机队）：8 个 MSK 集群的
    UnderReplicatedPartitions Average 序列 p95 全为 0，而 max 达 27–244。
    MSK 自动打补丁做滚动重启，重启期间副本必然短暂落后 ⇒ 旧判据会在
    任何被维护过的集群上误阻断。ElastiCache 的 ReplicationLag 同形状
    （p95 0.001–0.005s，max 10.2s / 23.9s）。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    lag_limit = t["redis_repl_lag_max_s"]

    # MSK：URP 尖峰 244，持续值 0 ⇒ 不否决，但尖峰必须可见
    msk = dict(rid="mk-spike", service="msk", type="kafka.m7g.large",
               under_replicated_max=244.0, under_replicated_p95=0.0,
               disk_used_max=10.0, handler_idle_p95=0.99, cpu_total_p95=3.0,
               cheaper_candidate_exists=True, sample_n=floor)
    got = core.dispatch(msk, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"URP 持续值为 0 不应否决，实际 {got['verdict']} —— {got}")
    joined = " ".join(got["blockers"])
    assert "单次尖峰" in joined and "244" in joined, (
        f"尖峰未写进 blockers，维护事件被藏起来了 —— {got['blockers']}")

    # MSK：持续值也越界 ⇒ 照旧否决
    got = core.dispatch(dict(msk, under_replicated_p95=3.0), {"thresholds": t})
    assert got["verdict"] == "blocked", got

    # ElastiCache ReplicationLag：尖峰 23.88s，持续值 0.005s ⇒ 不否决
    ec = dict(rid="cc-spike", service="elasticache", has_replica=False, engine="redis", type="cache.t4g.medium",
              vcpu=2, mem_gib=3.09, evictions_sum=0.0, evictions_p95=0.0,
              repl_lag_max=23.882, repl_lag_p95=0.005,
              engine_cpu_p95=0.64, db_mem_used_pct_max=59.24,
              cheaper_candidate_exists=True, sample_n=floor)
    got = core.dispatch(ec, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"复制延迟持续值 0.005s 不应否决，实际 {got['verdict']} —— {got}")
    assert "23.882" in " ".join(got["blockers"]), got["blockers"]

    # ElastiCache：持续延迟越界 ⇒ 照旧否决
    got = core.dispatch(dict(ec, repl_lag_p95=lag_limit + 1), {"thresholds": t})
    assert got["verdict"] == "blocked", got

    # ElastiCache Evictions：尖峰有、持续无 ⇒ 不否决
    got = core.dispatch(dict(ec, evictions_sum=17.0, evictions_p95=0.0),
                        {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", got
    assert "17" in " ".join(got["blockers"]), got["blockers"]

    # ElastiCache：持续驱逐 ⇒ 照旧否决
    got = core.dispatch(dict(ec, evictions_sum=17.0, evictions_p95=2.0),
                        {"thresholds": t})
    assert got["verdict"] == "blocked", got


def test_downsize_candidate_flags_unverified_fit():
    """候选 ≠ 有钱可省。cheaper_candidate_exists 只按价格判，不校验装得下。

    实测：某 cache.t4g.medium 复制组（4 节点）该字段为 true，
    但内存已用到 maxmemory 的 59.24% ⇒ 需节点内存 >= 1.830 GiB，而同架构下
    更便宜的 cache.t4g.small 可用内存只有 1.028 GiB ⇒ 实际可省 $0。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = [
        dict(rid="db-F", service="rds", type="db.r6g.large", vcpu=2,
             mem_gib=16, surplus_credits=0, dbload_p95=0.1,
             freeable_mem_min_gib=8.0, cheaper_candidate_exists=True,
             sample_n=floor),
        dict(rid="cc-F", service="elasticache", has_replica=False, engine="redis", type="cache.m6g.large",
             vcpu=2, mem_gib=6.38, evictions_sum=0, repl_lag_max=0.0,
             engine_cpu_p95=1.0, db_mem_used_pct_max=2.0,
             cheaper_candidate_exists=True, sample_n=floor),
        dict(rid="mk-F", service="msk", type="kafka.m7g.large",
             under_replicated_max=0, disk_used_max=10.0,
             handler_idle_p95=0.99, cpu_total_p95=3.0,
             cheaper_candidate_exists=True, sample_n=floor),
    ]
    for res in cases:
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "downsize-candidate", got
        assert "未经校验" in " ".join(got["blockers"]), (
            f"{res['service']}: downsize-candidate 未标注适配性未校验 —— "
            f"{got['blockers']}")


def test_spike_note_survives_every_exit_branch():
    """尖峰说明必须在**所有**出口都活下来，不只是 downsize-candidate 那个。

    实测踩过三次：`out.update(verdict=X, blockers=[...])` 会把此前 append
    的尖峰说明整段覆盖掉。第一次在 downsize-candidate 出口，第二次在
    已合理配置出口，第三次在「没有更便宜候选」出口——那一次是回放真实账号
    才发现的：8 个 MSK 集群放行后 URP 尖峰一条都没写出来。
    所以三个 evaluator 的 verdict 出口统一走 `_verdict()`，而本条断言
    逐出口验证它真的生效。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    base = dict(rid="mk-exit", service="msk", type="kafka.m7g.large",
                under_replicated_max=244.0, under_replicated_p95=0.0,
                sample_n=floor)
    # 每个 case 走一个不同的退出分支，尖峰说明都必须在
    cases = {
        "已合理配置（没有更便宜候选）": dict(
            base, cheaper_candidate_exists=False),
        "metric-missing（缺 cheaper_candidate_exists）": dict(base),
        "metric-missing（缺前置指标）": dict(
            base, cheaper_candidate_exists=True, disk_used_max=None,
            handler_idle_p95=None, cpu_total_p95=None),
        "已合理配置（磁盘水位越界）": dict(
            base, cheaper_candidate_exists=True,
            disk_used_max=t["msk_disk_used_max"] + 1,
            handler_idle_p95=0.99, cpu_total_p95=3.0),
        "已合理配置（handler idle 太低）": dict(
            base, cheaper_candidate_exists=True, disk_used_max=10.0,
            handler_idle_p95=t["msk_handler_idle_min"], cpu_total_p95=3.0),
        "已合理配置（CPU 越界）": dict(
            base, cheaper_candidate_exists=True, disk_used_max=10.0,
            handler_idle_p95=0.99, cpu_total_p95=t["msk_target_cpu_p95"] + 1),
        "downsize-candidate": dict(
            base, cheaper_candidate_exists=True, disk_used_max=10.0,
            handler_idle_p95=0.99, cpu_total_p95=3.0),
    }
    for label, res in cases.items():
        got = core.dispatch(res, {"thresholds": t})
        blockers = " ".join(got.get("blockers") or [])
        assert "单次尖峰" in blockers and "244" in blockers, (
            f"{label}：出口把尖峰说明覆盖掉了 —— verdict={got['verdict']} "
            f"blockers={got.get('blockers')}")


def test_branch_reasons_precede_appended_notes_on_every_exit():
    """分支理由必须排在尖峰说明**之前**，每个出口都一样。

    `_verdict()` 的契约就是这个顺序。此前 downsize-candidate 出口用
    `blockers.extend(...)`，于是那一条路上顺序是反的：读者在一条**可执行建议**上
    先看到两条尖峰告警，才看到真正的动作要求。契约没规定顺序，所以不会被别的
    断言抓到——而代码自己的 docstring 却写着相反的话。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    cases = {
        "elasticache": dict(
            rid="cc-ord", service="elasticache", has_replica=False, engine="redis", type="cache.t4g.medium",
            vcpu=2, mem_gib=3.09, evictions_sum=17.0, evictions_p95=0.0,
            repl_lag_max=23.882, repl_lag_p95=0.005, engine_cpu_p95=0.64,
            db_mem_used_pct_max=59.24, cheaper_candidate_exists=True,
            sample_n=floor),
        "msk": dict(
            rid="mk-ord", service="msk", type="kafka.m7g.large",
            under_replicated_max=244.0, under_replicated_p95=0.0,
            disk_used_max=10.0, handler_idle_p95=0.99, cpu_total_p95=3.0,
            cheaper_candidate_exists=True, sample_n=floor),
    }
    for svc, res in cases.items():
        got = core.dispatch(res, {"thresholds": t})
        assert got["verdict"] == "downsize-candidate", got
        bl = got["blockers"]
        spike_at = [i for i, b in enumerate(bl) if "单次尖峰" in b]
        reason_at = [i for i, b in enumerate(bl) if "单次尖峰" not in b]
        assert spike_at and reason_at, (
            f"{svc}: 本 fixture 应同时产出分支理由与尖峰说明 —— {bl}")
        assert max(reason_at) < min(spike_at), (
            f"{svc}: 分支理由与尖峰说明的顺序错了（理由下标 {reason_at}，"
            f"尖峰下标 {spike_at}）—— {bl}")


def test_persistence_fields_absent_keeps_old_behaviour():
    """采集侧未升级（只送 *_max）时，行为与改动前逐字节相同。"""
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    msk = dict(rid="mk-old", service="msk", type="kafka.m7g.large",
               under_replicated_max=244.0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0,
               cheaper_candidate_exists=True, sample_n=floor)
    assert core.dispatch(msk, {"thresholds": t})["verdict"] == "blocked"
    ec = dict(rid="cc-old", service="elasticache", has_replica=False, engine="redis", type="cache.t4g.medium",
              vcpu=2, mem_gib=3.09, evictions_sum=0.0, repl_lag_max=23.882,
              engine_cpu_p95=0.64, db_mem_used_pct_max=59.24,
              cheaper_candidate_exists=True, sample_n=floor)
    assert core.dispatch(ec, {"thresholds": t})["verdict"] == "blocked"


def test_managed_missing_sample_n_is_insufficient_not_pass():
    """sample_n 缺失必须 fail-closed，不得当成「点数够」放行。"""
    t = core.load_thresholds("aggressive")
    res = dict(rid="mk-Y", service="msk", type="kafka.m7g.large",
               under_replicated_max=0, disk_used_max=10.0,
               handler_idle_p95=0.99, cpu_total_p95=3.0)
    got = core.dispatch(res, {"thresholds": t})
    assert got["verdict"] == "insufficient-data", (
        f"sample_n 缺失被当成点数充足放行了 —— {got}")


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
               dbload_p95=0.05, freeable_mem_min_gib=5.98,
               cheaper_candidate_exists=True)
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


def test_replication_lag_absence_splits_by_replica_presence():
    """`ReplicationLag` 的缺失按副本存在性分流，不再无条件放行。

    Evictions 的 fail-closed 与 ReplicationLag 的分流**不对称是有依据的**：
    Evictions 每个节点都发布，缺失是真缺失；ReplicationLag 只在存在副本时才有
    意义。但放行必须有依据 —— 无条件放行会让这条否决项在一个真实复制组上
    静默消失，而该 skill 已记录「维度名写错时 list-metrics 与 get-metric-data
    都只返回空、不报错」。

    不用 count 做代理：`3 分片 x 1 节点`（count=3、无副本）是合法的 cluster-mode
    配置，按 count > 1 会把它误判成「该有副本却缺指标」。
    """
    t = core.load_thresholds("aggressive")
    base = dict(rid="cc-R", service="elasticache", type="cache.r7g.large",
                vcpu=2, mem_gib=13.07, evictions_sum=0, evictions_p95=0,
                engine="redis", engine_cpu_p95=12, db_mem_used_pct_max=35,
                sample_n=243, cheaper_candidate_exists=True)

    # 有副本 + 序列缺失 ⇒ 采集缺口，不得放行
    gap = core.eval_elasticache(dict(base, has_replica=True), t)
    assert gap["verdict"] == "metric-missing", gap["verdict"]
    assert "存在副本却无 ReplicationLag" in gap["blockers"][0], gap["blockers"]

    # 无副本 + 序列缺失 ⇒ 不适用，放行
    na = core.eval_elasticache(dict(base, has_replica=False), t)
    assert na["verdict"] == "downsize-candidate", na["verdict"]

    # has_replica 自身缺失 ⇒ fail-closed（不得假定无副本）
    unknown = core.eval_elasticache(base, t)
    assert unknown["verdict"] == "metric-missing", unknown["verdict"]
    assert "has_replica 缺失" in unknown["blockers"][0], unknown["blockers"]

    # 有副本 + 序列有值且越界 ⇒ 否决判定不受本次分流影响
    veto = core.eval_elasticache(dict(base, has_replica=True, repl_lag_p95=2.0,
                                      repl_lag_max=5.0), t)
    assert veto["verdict"] == "blocked", veto["verdict"]

    # 有副本 + 序列有值且正常 ⇒ 照常走降配路径
    fine = core.eval_elasticache(dict(base, has_replica=True,
                                      repl_lag_p95=0.0007, repl_lag_max=0.03), t)
    assert fine["verdict"] == "downsize-candidate", fine["verdict"]


def test_rds_credit_floor_and_branch_order():
    """RDS 余额触底 ⇒ upsize-candidate；且缺失型 fail-closed 必须晚于 cheaper 短路。

    顺序有两条相反的边界，缺一不可：
      · **已能评估**的否决项早于 cheaper 短路 —— 候选集为空不该压掉「这台机器
        已经不够用了」这条警告（与 2026-09-09 那轮采样守卫是同一个教训）。
      · **缺失型** fail-closed 晚于 cheaper 短路 —— 候选集为空时补指标也换不来
        建议，要求它就是让客户白等一个窗口。eval_msk / eval_elasticache 的注释
        早已写明这条原则，eval_rds 此前把两条 fail-closed 放在了前面。
    """
    t = core.load_thresholds("aggressive")
    base = dict(rid="db-C", service="rds", type="db.t4g.medium", vcpu=2,
                mem_gib=4, sample_n=243, surplus_credits=0, dbload_p95=0.05,
                freeable_mem_min_gib=3.0, cheaper_candidate_exists=True)

    hit = core.eval_rds(dict(base, credit_balance_min=0.70,
                             credit_balance_max=576.0), t)
    assert hit["verdict"] == "upsize-candidate", hit["verdict"]
    assert any("信用余额窗口内触底" in b for b in hit["blockers"]), hit["blockers"]

    # 反向：健康余额 ⇒ 照常走降配路径
    ok = core.eval_rds(dict(base, credit_balance_min=575.3,
                            credit_balance_max=576.0), t)
    assert ok["verdict"] == "downsize-candidate", ok["verdict"]

    # db.t* 缺余额字段 ⇒ fail-closed
    miss = core.eval_rds(base, t)
    assert miss["verdict"] == "metric-missing", miss["verdict"]
    assert "CPUCreditBalance 缺失" in miss["blockers"][0], miss["blockers"]

    # 非突发有序列 ⇒ 不否决，但留说明
    changed = core.eval_rds(dict(base, type="db.m6g.xlarge", vcpu=4, mem_gib=16,
                                 freeable_mem_min_gib=12.0,
                                 credit_balance_min=0.79,
                                 credit_balance_max=576.0), t)
    assert changed["verdict"] == "downsize-candidate", changed["verdict"]
    assert any("窗口内改过规格" in b for b in changed["blockers"]), changed["blockers"]

    # 顺序：无更便宜候选 + 缺余额字段 ⇒ 已合理配置（不得要求补指标）
    no_cheaper = core.eval_rds(dict(base, cheaper_candidate_exists=False), t)
    assert no_cheaper["verdict"] == "已合理配置", (
        f"候选集为空时仍要求信用指标，会让客户白等一个窗口 —— {no_cheaper}")

    # 顺序：无更便宜候选 + 余额已触底 ⇒ 仍须报 upsize-candidate（警告不可被压掉）
    veto_wins = core.eval_rds(dict(base, cheaper_candidate_exists=False,
                                   credit_balance_min=0.70,
                                   credit_balance_max=576.0), t)
    assert veto_wins["verdict"] == "upsize-candidate", (
        f"候选集为空压掉了「规格已不足」的警告 —— {veto_wins}")


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
               under_replicated_max=0, disk_used_max=None,
               handler_idle_p95=None, cpu_total_p95=None)
    got = core.dispatch(msk, {"thresholds": t})
    assert got["verdict"] == "已合理配置", (
        f"最小规格仍判 {got['verdict']}，会让客户为不可能的建议白等一个窗口 —— {got}")
    assert any("最小" in b or "更便宜" in b for b in got.get("blockers") or []), (
        f"blockers 未说明原因是没有更便宜候选 —— {got}")

    cc = dict(rid="cc-MIN", service="elasticache", has_replica=False, engine="redis", type="cache.t4g.micro",
              vcpu=2, mem_gib=0.5, sample_n=floor,
              cheaper_candidate_exists=False, evictions_sum=0,
              repl_lag_max=0.0, engine_cpu_p95=None, db_mem_used_pct_max=None)
    got = core.dispatch(cc, {"thresholds": t})
    assert got["verdict"] == "已合理配置", (
        f"已是该族最小 node type 仍判 {got['verdict']} —— {got}")

    # RDS：`freeable_mem_min_gib` / `mem_gib` 故意留 None —— 候选集为空时
    # 不得再要求 FreeableMemory 数据，那正是本条要挡的"白等一个窗口"。
    db = dict(rid="db-MIN", service="rds", type="db.t4g.micro", vcpu=2,
              mem_gib=None, sample_n=floor, cheaper_candidate_exists=False,
              surplus_credits=0, dbload_p95=0.05, freeable_mem_min_gib=None)
    got = core.dispatch(db, {"thresholds": t})
    assert got["verdict"] == "已合理配置", (
        f"已是最便宜实例类的 RDS 仍判 {got['verdict']}，"
        f"会让客户为不可能的建议去开 PI / 补 FreeableMemory —— {got}")
    assert any("更便宜" in b for b in got.get("blockers") or []), (
        f"blockers 未说明原因是没有更便宜候选 —— {got}")


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
    # RDS 同一条契约。缺 flag 时**不得**因为其余指标齐全就放行到 downsize-candidate。
    db = dict(rid="db-Z", service="rds", type="db.r6g.large", vcpu=2, mem_gib=16,
              sample_n=floor, surplus_credits=0, dbload_p95=0.4,
              freeable_mem_min_gib=9.6)
    got = core.dispatch(db, {"thresholds": t})
    assert got["verdict"] == "metric-missing", (
        f"RDS 缺 cheaper_candidate_exists 却继续判到了 {got['verdict']} —— {got}")
    assert any("cheaper_candidate_exists" in b for b in got.get("blockers") or []), (
        f"blockers 未点名缺的是哪个字段 —— {got}")


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
    db = dict(rid="db-OK2", service="rds", type="db.r6g.large", vcpu=2, mem_gib=16,
              sample_n=floor, cheaper_candidate_exists=True, surplus_credits=0,
              dbload_p95=0.4, freeable_mem_min_gib=9.6)
    got = core.dispatch(db, {"thresholds": t})
    assert got["verdict"] == "downsize-candidate", (
        f"RDS 有更便宜候选却没走到 downsize-candidate —— {got}")


def test_cheaper_candidate_check_does_not_suppress_under_provisioning_vetoes():
    """cheaper_candidate_exists=False 不得掩盖欠配否决项。

    这是 cheaper_candidate 检查位置的回归：它必须在健康否决项之后——
    否则会让正在 evict 键的缓存、有 under-replicated 分区的集群被判成
    「已合理配置」，客户看不到真实问题是规格不够。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    # ElastiCache：Evictions > 0 ⇒ 即使已是最小规格也必须判 blocked
    cc_evict = dict(rid="cc-EVICT", service="elasticache", has_replica=False, engine="redis", type="cache.t4g.micro",
                    vcpu=2, mem_gib=0.5, sample_n=floor,
                    cheaper_candidate_exists=False, evictions_sum=123,
                    repl_lag_max=0.0, engine_cpu_p95=None, db_mem_used_pct_max=None)
    got = core.dispatch(cc_evict, {"thresholds": t})
    assert got["verdict"] == "blocked", (
        f"Evictions > 0 必须判 blocked，不得被 cheaper_candidate_exists=False 掩盖 —— {got}")
    assert any("Evictions" in b or "不足" in b for b in got.get("blockers") or []), (
        f"blockers 未说明 Evictions 问题 —— {got}")

    # MSK：UnderReplicatedPartitions > 0 ⇒ 即使已是最小规格也必须判 blocked
    msk_urp = dict(rid="mk-URP", service="msk", type="kafka.t3.small",
                   sample_n=floor, cheaper_candidate_exists=False,
                   under_replicated_max=5, disk_used_max=None,
                   handler_idle_p95=None, cpu_total_p95=None)
    got = core.dispatch(msk_urp, {"thresholds": t})
    assert got["verdict"] == "blocked", (
        f"UnderReplicatedPartitions > 0 必须判 blocked，不得被 cheaper_candidate_exists=False 掩盖 —— {got}")
    assert any("UnderReplicated" in b or "Partitions" in b for b in got.get("blockers") or []), (
        f"blockers 未说明 UnderReplicatedPartitions 问题 —— {got}")

    # RDS 有**两条**欠配否决项，都在候选集检查之前，两条都要守。
    # 信用超额：db.t4g.medium 的 CPUSurplusCreditsCharged > 0 ⇒ 升配候选
    db_credit = dict(rid="db-SC", service="rds", type="db.t4g.medium", vcpu=2,
                     mem_gib=4, sample_n=floor, cheaper_candidate_exists=False,
                     surplus_credits=730.6, dbload_p95=0.05,
                     freeable_mem_min_gib=3.0)
    got = core.dispatch(db_credit, {"thresholds": t})
    assert got["verdict"] == "upsize-candidate", (
        f"CPUSurplusCreditsCharged > 0 必须判 upsize-candidate，"
        f"不得被 cheaper_candidate_exists=False 掩盖成「已合理配置」 —— {got}")
    assert any("CPUSurplusCreditsCharged" in b for b in got.get("blockers") or []), (
        f"blockers 未说明信用已超额 —— {got}")
    # DBLoad 瓶颈：dbload_p95 >= vCPU ⇒ CPU 已是瓶颈，blocked
    db_load = dict(rid="db-BN", service="rds", type="db.r6g.large", vcpu=2,
                   mem_gib=16, sample_n=floor, cheaper_candidate_exists=False,
                   surplus_credits=0, dbload_p95=2.5, freeable_mem_min_gib=9.6)
    got = core.dispatch(db_load, {"thresholds": t})
    assert got["verdict"] == "blocked", (
        f"DBLoad p95 >= vCPU 必须判 blocked，"
        f"不得被 cheaper_candidate_exists=False 掩盖 —— {got}")
    assert any("DBLoad" in b for b in got.get("blockers") or []), (
        f"blockers 未说明 CPU 已是瓶颈 —— {got}")


if __name__ == "__main__":
    tests = [test_managed_resources_reach_their_own_evaluators,
             test_absent_service_raises_instead_of_defaulting_to_ec2,
             test_unknown_service_raises,
             test_upsize_candidate_never_lands_in_a_savings_bucket,
             test_managed_resource_never_enters_idle_bucket,
             test_msk_handler_idle_is_read_on_0_1_scale,
             test_missing_veto_metrics_yield_metric_missing_not_a_pass,
             test_managed_vetoes_actually_fire_and_block,
             test_rds_credit_veto_outranks_dbload_and_memory,
             test_ec2_idle_bucket_treats_zero_traffic_as_idle,
             test_blockers_is_a_list_on_every_row,
             test_stop_candidate_is_three_state_and_defaults_to_unknown,
             test_stop_candidate_needs_all_three_signals,
             test_stop_candidate_peak_gate_comes_from_thresholds,
             test_ec2_missing_network_is_not_idle,
             test_sample_solve_managed_block_reproduces,
             test_managed_low_sample_downgrades_instead_of_refusing,
             test_managed_zero_sample_stays_insufficient,
             test_vetoes_judge_persistence_not_a_single_spike,
             test_downsize_candidate_flags_unverified_fit,
             test_spike_note_survives_every_exit_branch,
             test_branch_reasons_precede_appended_notes_on_every_exit,
             test_persistence_fields_absent_keeps_old_behaviour,
             test_managed_missing_sample_n_is_insufficient_not_pass,
             test_nonburstable_rds_does_not_require_credit_metrics,
             test_burstable_rds_still_requires_credit_metrics,
             test_burstable_rds_credit_overage_still_vetoes,
             test_elasticache_engine_gates_the_redis_only_criteria,
             test_replication_lag_absence_splits_by_replica_presence,
             test_rds_credit_floor_and_branch_order,
             test_no_cheaper_candidate_yields_already_right_sized,
             test_missing_cheaper_candidate_flag_is_fail_closed,
             test_cheaper_candidate_true_still_reaches_downsize,
             test_cheaper_candidate_check_does_not_suppress_under_provisioning_vetoes]
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
