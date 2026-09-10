"""阈值读取契约与 EC2 侧的抑制分支：缺键必须响，缺指标必须短路。

本文件守的是「静默错答」而不是「算错」——每条对应一个已发生的缺陷：
注入的 thresholds 缺键时守卫消失、sizing_profile 缺失时静默选 aggressive、
默认值与阈值文件各写一份、面向客户的文案写死阈值数字。

后半部分守 evaluate() 里那几个**只抑制建议、不产出建议**的早退分支
（price-unknown / 加速机型 excluded / CPU metric-missing / 信用缺失抑制
burstable）。它们坏掉的方向是漏报而不是误报，但实测逐个删除时八个测试文件
全绿，等于完全不设防。托管服务的否决项在 test_managed_dispatch.py。
"""
import json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

CORE = ROOT / "references" / "core.py"

# ebs 均为真实基线吞吐；t3.large 基线 30%、g5.xlarge 为加速机型（ACCEL_RE 命中）
SPECS = [{"t": "m5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
          "arch": "x86_64", "store": False, "ebs": 143.75, "curgen": True},
         {"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
          "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True},
         {"t": "t3.large", "vcpu": 2, "gib": 8, "burst": True,
          "arch": "x86_64", "store": False, "ebs": 86.875, "curgen": True},
         {"t": "g5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
          "arch": "x86_64", "store": False, "ebs": 87.5, "curgen": True}]
PRICES = {"m5.xlarge|RunInstances": 0.192, "m5.large|RunInstances": 0.096,
          "t3.large|RunInstances": 0.0832, "g5.xlarge|RunInstances": 1.006}
CATS = {"m5.xlarge": "General purpose", "m5.large": "General purpose",
        "t3.large": "General purpose", "g5.xlarge": "Accelerated computing"}
BASELINE = {"t3.large": 0.3}
RES = {"rid": "i-T-01", "service": "ec2", "type": "m5.xlarge", "arch": "x86_64",
       "operation": "RunInstances", "sus_cpu": 30, "peak_cpu": 40,
       "sus_mem": 20, "peak_mem": 35, "ebs_need": 5, "surplus_credits": 0,
       "cpu_n": 13, "metric_coverage": []}
CACHE = {"rid": "cache-T-01", "service": "elasticache", "type": "cache.r7g.large",
         "vcpu": 2, "mem_gib": 13.07, "evictions_sum": 0, "repl_lag_max": 0.2,
         "engine_cpu_p95": 12, "db_mem_used_pct_max": 35,
         "cheaper_candidate_exists": True}


def _ctx(t, resources, specs=None, prices=None, cats=None, baseline=None):
    """构造 evaluate() 的 ctx。四个 fixture 参数缺省用模块级共享常量。

    允许传局部 specs，是为了让「当前机型是 T 系列」这类被测形态有自己的
    候选池，而不必往共享 SPECS 里加机型 —— 加进去会给其他复用同一份 SPECS
    的测试引入一个新的更便宜候选，静默改掉既有断言。
    """
    specs = SPECS if specs is None else specs
    ctx = {"thresholds": t, "specs": specs,
           "prices": PRICES if prices is None else prices,
           "baseline_pct": BASELINE if baseline is None else baseline,
           "categories": CATS if cats is None else cats,
           "offerings": [s["t"] for s in specs], "legacy_families": [],
           "resources": resources}
    ctx["_specs_by_type"] = {s["t"]: s for s in specs}
    ctx["_offerings"] = set(ctx["offerings"])
    ctx["_legacy"] = set()
    return ctx


def _evaluate(res, t, **ctx_kw):
    """跑 evaluate()，把异常翻译成指名缺陷的断言失败。

    这些分支坏掉时多半是「None 参与算术」而不是「结论错」，裸抛的
    TypeError 不说明是哪个守卫没了。
    """
    try:
        return core.evaluate(res, _ctx(t, [res], **ctx_kw))
    except Exception as e:
        raise AssertionError(
            f"{res['rid']} 未在早退分支短路，落进了选型算术并抛 {type(e).__name__}: {e}")


def test_injected_thresholds_missing_sampling_floor_raises():
    """thresholds 缺 min_biz_hours_points 必须 KeyError，不得让守卫静默消失。

    cli-recipes 教调用方自己拼 $THRESHOLDS，拼漏这个键时用 .get() 会让
    cpu_n=13 的资源从 insufficient-data 变成 downsize + 编造的节省额。
    """
    t = core.load_thresholds("aggressive")
    t.pop("min_biz_hours_points")
    for fn, args in ((core.evaluate, (RES, _ctx(t, [RES]))),
                     (core.is_idle, (dict(RES, sus_cpu=1, net_mb_day=0), t))):
        try:
            fn(*args)
        except KeyError as e:
            assert "min_biz_hours_points" in str(e), e
        else:
            raise AssertionError(f"{fn.__name__} 缺键时未抛错")
    # 键在时分档仍然生效。cpu_n=13 现在走降档而非拒绝（见
    # test_low_sample_downgrades_instead_of_refusing）；本测试的要点是
    # 「缺 min_biz_hours_points 必须抛 KeyError」，不是这条 verdict。
    ok = core.evaluate(RES, _ctx(core.load_thresholds("aggressive"), [RES]))
    assert ok["confidence"] == "low", ok


def test_missing_sizing_profile_raises():
    """sizing_profile 是必填输入，缺失不得静默选 aggressive。

    两个 profile 在同一机队上产出不同：13 项/$527.15 对 12 项/$373.00
    （回归 fixture 实测，逐值断言在 tests/test_regression_fleet.py 的 EXPECTED，
    那里也记着这两组数字的迁移由来）。静默选一个等于替 operator 做了决定，
    而报告里看不出选过。
    """
    ctx = {"specs": SPECS, "prices": {}, "baseline_pct": {}, "categories": {},
           "offerings": [], "legacy_families": [], "resources": []}
    p = subprocess.run([sys.executable, str(CORE)], input=json.dumps(ctx),
                       capture_output=True, text=True)
    assert p.returncode != 0, f"缺 sizing_profile 竟然成功了：{p.stdout[:200]}"
    assert "sizing_profile" in p.stderr, p.stderr
    # 拼错键名同样必须响（不能因为存在别的键就放行）
    p2 = subprocess.run([sys.executable, str(CORE)],
                        input=json.dumps(dict(ctx, sizing_profiles="aggressive")),
                        capture_output=True, text=True)
    assert p2.returncode != 0, p2.stdout[:200]


def test_reserved_memory_default_comes_from_thresholds_json():
    """reserved_memory_pct 缺省值只能来自 thresholds.json。

    写死在 core.py 里时，改 thresholds.json 的
    reserved_memory_pct_default 不会让结果动一毫米。
    """
    base = core.load_thresholds("aggressive")
    bumped = core.load_thresholds("aggressive",
                                  override={"reserved_memory_pct_default": 50})
    a = core.eval_elasticache(CACHE, base)["required_gib_usable"]
    b = core.eval_elasticache(CACHE, bumped)["required_gib_usable"]
    assert a != b, f"改 reserved_memory_pct_default 后结果未变（{a}）：值被写死了"
    assert b == round(CACHE["mem_gib"] * 0.5 * CACHE["db_mem_used_pct_max"] / 100, 3), b


def test_required_gib_usable_is_actually_usable_memory():
    """键名说 usable，值就必须是可用内存口径。

    原式 usable*memp/100/(1-reserved) 里 (1-reserved) 相消，任何 reserved
    都得到同一个数（= 节点总内存口径），与键名和 blockers 文案都矛盾。
    """
    t = core.load_thresholds("aggressive")
    vals = {}
    for pct in (0, 25, 50):
        out = core.eval_elasticache(dict(CACHE, reserved_memory_pct=pct), t)
        vals[pct] = out["required_gib_usable"]
        assert out["required_gib_usable"] == round(
            CACHE["mem_gib"] * (1 - pct / 100) * CACHE["db_mem_used_pct_max"] / 100, 3)
    assert len(set(vals.values())) == 3, f"reserved 不影响结果，算式相消了：{vals}"
    # 扣了 reserved 的值必须小于总内存口径
    total_basis = round(CACHE["mem_gib"] * CACHE["db_mem_used_pct_max"] / 100, 3)
    assert vals[25] < total_basis, (vals[25], total_basis)
    assert vals[0] == total_basis, "reserved=0 时两种口径应当相等"
    # blockers 必须复述真实使用的百分比与真实数值
    out25 = core.eval_elasticache(dict(CACHE, reserved_memory_pct=25), t)
    blob = " ".join(out25["blockers"])
    assert str(vals[25]) in blob and "25%" in blob, blob


def test_burstable_ceiling_message_quotes_the_threshold():
    """T 系列上限文案里的数字必须来自 thresholds，不得写死。

    写死时把 burstable_max_vcpu 调低，报告仍向客户断言旧上限。
    """
    t = core.load_thresholds("aggressive",
                            override={"burstable_max_vcpu": 1,
                                      "burstable_max_gib": 1})
    res = dict(RES, cpu_n=243)
    out = core.evaluate(res, _ctx(t, [res]))
    assert out["burst"] is None, out
    assert out["burst_na"] == "超 T 系列上限 1C/1G", out["burst_na"]


def test_unpriced_instance_is_price_unknown_not_downsized():
    """取不到按需价 ⇒ price-unknown，不得退回「最小够用」选型。

    价格键是 (机型, UsageOperation) 复合键，同机型 Linux 与 Windows+SQL 差 7.79 倍。
    取不到价时若继续选型，省下的钱是拿错价算的，而且看不出来。
    """
    t = core.load_thresholds("aggressive")
    # 机型规格在，但这个 UsageOperation 没有价格
    out = _evaluate(dict(RES, rid="i-T-06", cpu_n=243,
                         operation="RunInstances:0002"), t)
    assert out["verdict"] == "price-unknown", out
    assert out["nonburst"] is None and out["burst"] is None, out
    assert out.get("nb_save_mo") is None, out


def test_accelerated_instance_is_excluded_before_sizing():
    """加速机型 ⇒ excluded。按 CPU/内存给 GPU 机器降配是无依据的。"""
    t = core.load_thresholds("aggressive")
    out = _evaluate(dict(RES, rid="i-T-07", type="g5.xlarge", cpu_n=243), t)
    assert out["verdict"] == "excluded", out
    assert out["nonburst"] is None and out["burst"] is None, out


def test_missing_cpu_metrics_short_circuit_before_sizing_math():
    """CPU 指标缺失 ⇒ metric-missing，必须早于任何选型算术与「已合理配置」。"""
    t = core.load_thresholds("aggressive")
    for miss in ("sus_cpu", "peak_cpu"):
        out = _evaluate(dict(RES, rid="i-T-08", cpu_n=243, **{miss: None}), t)
        assert out["verdict"] == "metric-missing", (miss, out)
        assert out["required_vcpu"] is None, (miss, out)


def test_missing_surplus_credits_suppresses_the_burstable_candidate():
    """信用指标缺失 ⇒ 不得给 burstable 建议（不能断言"没超额"）。

    第二半是这个测试的关键：同一台机器把 surplus_credits 给成 0 时确实能选出
    t3.large。若只断言"缺失时 burst is None"，候选池本来就空也照样通过，
    删掉抑制分支不会被发现。
    """
    t = core.load_thresholds("aggressive")
    base = dict(RES, rid="i-T-09", cpu_n=243, sus_cpu=10, peak_cpu=25)
    suppressed = _evaluate(dict(base, surplus_credits=None), t)
    assert suppressed["burst"] is None, \
        f"信用指标缺失时不得产出 burstable 建议，却选出了 {suppressed['burst']}"
    assert "CPUSurplusCreditsCharged 缺失" in suppressed["burst_na"], suppressed
    assert suppressed.get("b_save_mo") is None, suppressed
    allowed = _evaluate(dict(base, surplus_credits=0), t)
    assert allowed["burst"] is not None and allowed["burst"]["t"] == "t3.large", \
        f"候选池里本应有 t3.large，抑制测试才有意义：{allowed['burst_na']}"


def test_overspent_credits_suppress_the_burstable_candidate():
    """信用已超额 ⇒ 当前规格已不足，更不能推 burstable。

    与「指标缺失」是两条不同的抑制分支，同一个 T 候选池：给 0 时能选出
    t3.large（见上一条），给 >0 时必须一个都不给。
    """
    t = core.load_thresholds("aggressive")
    out = _evaluate(dict(RES, rid="i-T-10", cpu_n=243, sus_cpu=10, peak_cpu=25,
                         surplus_credits=5), t)
    assert out["burst"] is None, \
        f"信用已超额时不得产出 burstable 建议，却选出了 {out['burst']}"
    assert out["burst_na"] == "CPUSurplusCreditsCharged>0，当前规格已不足", out["burst_na"]


def test_serverless_rds_is_excluded_not_spec_unknown():
    """db.serverless 按 ACU 伸缩，没有固定规格可降 ⇒ excluded 而非 spec-unknown。"""
    t = core.load_thresholds("aggressive")
    out = core.eval_rds({"rid": "db-T-09", "service": "rds",
                         "type": "db.serverless"}, t)
    assert out["verdict"] == "excluded", out
    assert "Serverless" in " ".join(out["blockers"]), out["blockers"]


def test_low_sample_downgrades_instead_of_refusing():
    """样本不足不得拒绝出建议，只降 confidence 并写明样本量。

    旧行为：cpu_n < min_biz_hours_points ⇒ insufficient-data，连否决项
    都不跑。实测后果（某 ap-east-1 机队）：两条真实健康事实
    （MSK URP 27、Redis 复制延迟 23.88s）被一句「点数不足」盖住。
    采样量挡不住否决项 —— 否决项读的是 max，不是 p95。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    out = _evaluate(dict(RES, rid="i-LOW", cpu_n=floor - 1), t)
    assert out["verdict"] != "insufficient-data", (
        f"样本不足仍应出判据结论，实际 {out['verdict']} —— {out}")
    assert out["confidence"] == "low", out
    blockers = " ".join(out.get("blockers") or [])
    assert "样本" in blockers and str(floor) in blockers, (
        f"blockers 未写明样本量与门限 —— {out.get('blockers')}")


def test_low_sample_blocker_does_not_assert_a_recommendation_exists():
    """低样本 blocker 是**无条件**追加的，所以它的文案不能断言存在建议。

    原文案写「建议按此执行但缩短观察期」。它会被追加到没有建议、甚至结论
    相反的行上 —— 一个 `sample_n` 不足且 `surplus_credits > 0` 的 RDS 判
    `upsize-candidate`（「规格已不足，是升配候选」），紧跟一句「建议按此执行」，
    是面向客户的直接矛盾。`已合理配置` / `blocked` / `metric-missing` 同理。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    # ① EC2 低样本但无候选 ⇒ 已合理配置
    out = _evaluate(dict(RES, rid="i-LOW-NOREC", cpu_n=floor - 1,
                         sus_cpu=90, peak_cpu=95, sus_mem=90, peak_mem=95), t)
    assert out["verdict"] == "已合理配置", out["verdict"]
    low = [b for b in out["blockers"] if "样本" in b]
    assert low, out["blockers"]
    assert "建议按此执行" not in low[0], (
        f"「已合理配置」行上出现了「建议按此执行」—— {low[0]}")
    # ② 托管：结论是「这台机器太小了」，更不能说「建议按此执行」
    up = core.dispatch(dict(rid="db-UP", service="rds", type="db.t4g.medium",
                            vcpu=2, mem_gib=4, sample_n=floor - 1,
                            surplus_credits=730.6, dbload_p95=0.05,
                            freeable_mem_min_gib=3.0,
                            cheaper_candidate_exists=True),
                       {"thresholds": t})
    assert up["verdict"] == "upsize-candidate", up
    low = [b for b in up["blockers"] if "样本" in b]
    assert low and "建议按此执行" not in low[0], (
        f"upsize-candidate 行上出现了「建议按此执行」—— {low}")


def test_low_sample_row_records_that_the_idle_path_was_not_evaluated():
    """采样分档只放开降配路径；被硬门限挡掉的闲置判据必须在行上留痕。

    否则一条实际闲置、`cpu_n` 又不足的实例会拿到一条看起来确定的降配建议，
    而删除路径（值全额 `cur_cost_mo`，实测可比降配差价大 13.9 倍）被静默跳过。
    改动前它是 `insufficient-data`，至少说了「判不了」。
    """
    t = core.load_thresholds("aggressive")
    floor = t["min_biz_hours_points"]
    ctx = _ctx(t, [])
    res = dict(RES, rid="i-IDLE-LOW", cpu_n=floor - 1, sus_cpu=0.1,
               peak_cpu=0.2, net_mb_day=0, sus_mem=3, peak_mem=5, ebs_need=1)
    # 走 main() 的分桶逻辑（is_idle 在那里被调用）
    out = subprocess.run([sys.executable, str(CORE)],
                         input=json.dumps(dict(
                             sizing_profile="aggressive", specs=SPECS,
                             prices=PRICES, baseline_pct=BASELINE,
                             categories=CATS, offerings=[s["t"] for s in SPECS],
                             legacy_families=[], resources=[res])),
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    f = json.loads(out.stdout)[0]
    assert f["bucket"] == "downsize", f["bucket"]
    assert any("闲置判据" in b and "未评估" in b for b in f["blockers"]), (
        f"低样本行未记录「闲置判据未评估」—— {f['blockers']}")
    # 采样充足时不该出现这句
    ok = subprocess.run([sys.executable, str(CORE)],
                        input=json.dumps(dict(
                            sizing_profile="aggressive", specs=SPECS,
                            prices=PRICES, baseline_pct=BASELINE,
                            categories=CATS, offerings=[s["t"] for s in SPECS],
                            legacy_families=[],
                            resources=[dict(res, rid="i-OK", cpu_n=floor)])),
                        capture_output=True, text=True)
    g = json.loads(ok.stdout)[0]
    assert not any("闲置判据" in b and "未评估" in b for b in g["blockers"]), (
        f"采样充足却也说闲置判据未评估 —— {g['blockers']}")


def test_zero_and_missing_sample_stay_insufficient():
    """0 点与缺失是「无」不是「少」，仍须 fail-closed。"""
    t = core.load_thresholds("aggressive")
    for n in (0, None):
        out = _evaluate(dict(RES, rid=f"i-N{n}", cpu_n=n), t)
        assert out["verdict"] == "insufficient-data", (
            f"cpu_n={n!r} 必须 insufficient-data，实际 {out['verdict']}")


if __name__ == "__main__":
    tests = [test_injected_thresholds_missing_sampling_floor_raises,
             test_low_sample_downgrades_instead_of_refusing,
             test_low_sample_blocker_does_not_assert_a_recommendation_exists,
             test_low_sample_row_records_that_the_idle_path_was_not_evaluated,
             test_zero_and_missing_sample_stay_insufficient,
             test_missing_sizing_profile_raises,
             test_reserved_memory_default_comes_from_thresholds_json,
             test_required_gib_usable_is_actually_usable_memory,
             test_burstable_ceiling_message_quotes_the_threshold,
             test_unpriced_instance_is_price_unknown_not_downsized,
             test_accelerated_instance_is_excluded_before_sizing,
             test_missing_cpu_metrics_short_circuit_before_sizing_math,
             test_missing_surplus_credits_suppresses_the_burstable_candidate,
             test_overspent_credits_suppress_the_burstable_candidate,
             test_serverless_rds_is_excluded_not_spec_unknown]
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
