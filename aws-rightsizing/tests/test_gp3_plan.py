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
        _agg("vol-A", "VolumeAvgThroughput", "Average", "full-window", 700, 0.0, 0.0, 0.0),
        _agg("vol-A", "VolumeAvgThroughput", "Maximum", "full-window", 720, 10.0, 90.0, 17000.0),
        _agg("vol-A", "VolumeIOPSExceededCheck", "Maximum", "full-window", 720,
             3 / 720, 0.0, 1.0),
        _agg("vol-A", "VolumeThroughputExceededCheck", "Maximum", "full-window", 720,
             0.0375, 0.0, 1.0),
    ]
    scope = [{"id": "vol-A", "size": 80, "attach": "i-EX-1"},
             {"id": "vol-B", "size": 30, "attach": "i-EX-2"}]
    out = _jq(["--slurpfile", "agg", _tmp(rows), "--argjson", "win", "720",
               "-f", str(REF / "ebs-gp3-in.jq"), _tmp(scope)])
    a, b = out
    assert a == {"rid": "vol-A", "size_gib": 80, "sus_iops": 12.5, "peak_iops": 488.5,
                 "sus_kibs": 0.0, "peak_kibs": 17000.0,
                 "iops_exceeded_p95": 0.0, "iops_exceeded_hours": 3,
                 "tput_exceeded_p95": 0.0, "tput_exceeded_hours": 27,
                 "sample_n": 700, "window_points": 720}, a   # sample_n = full-window 档各序列点数的最小值
    assert b["rid"] == "vol-B" and b["size_gib"] == 30, b
    assert b["window_points"] == 720, b
    assert all(b[k] is None for k in b if k not in ("rid", "size_gib", "window_points")), b
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



sys.path.insert(0, str(ROOT / "tests"))
import test_csv_contract as csvc  # 复用填法表解析，不在这里再写一份

GP2_ROWS = {"可转": "EBS 卷 `gp2` 且可转 `gp3`",
            "单价不全": "EBS 卷 `gp2`，取不到 gp3 单价",
            "转了不省": "EBS 卷 其他（"}


def test_fill_table_gp2_rows_match_gp3_plan_and_say_to_copy_its_blockers():
    """gp3_plan() 是填法表 gp2 三行的唯一产出方（第五个 producer）：
    ① 三个出口的 (verdict, bucket, action_type) 必须逐格等于填法表那三行；
    ② 文档必须要求把 gp3_plan 的 blockers 照抄进交付物 —— gp3 的 IOPS / 吞吐配置
       与依据只在那里；不带它，执行的人只能按 gp3 默认 3000 / 125 配，
       而要另配的那些卷正是本判据要保护的。"""
    _, rows = csvc._fill_table()
    want = {}
    for key, name in GP2_ROWS.items():
        hit = [r for n, r in rows if name in n]
        assert len(hit) == 1, (key, name, len(hit))
        want[key] = tuple(csvc._cell_values(hit[0][c])[0]
                          for c in ("verdict", "bucket", "action_type"))
    got = {"可转": core.gp3_plan(_vol(80), T_AGG, PRICE),
           "单价不全": core.gp3_plan(_vol(80), T_AGG, dict(PRICE, gp3_gb_mo=None)),
           "转了不省": core.gp3_plan(_vol(200, tput_exceeded_p95=1, tput_exceeded_hours=60),
                                    T_AGG, PRICE)}
    for key, out in got.items():
        assert (out["verdict"], out["bucket"], out["action_type"]) == want[key], (key, out, want[key])
    tpl = (REF / "report-template.md").read_text(encoding="utf-8")
    rec = (REF / "cli-recipes.md").read_text(encoding="utf-8")
    assert "`blockers` 照抄 `core.gp3_plan()`" in tpl, "report-template 没要求 gp2 行照抄 gp3_plan 的 blockers"
    s27 = rec.split("### §2.7", 1)[1].split("## §3", 1)[0]
    assert "`blockers` 照抄" in s27, "cli-recipes §2.7 ④ 没要求照抄 gp3_plan 的 blockers"


def test_unpriced_rows_are_keyed_on_blank_cost_not_on_verdict():
    """「不进分母、进未包含项」的规则必须按 cur_cost_mo 是否留空来判，不能按 verdict。
    gp2 卷取不到 gp3 单价时 verdict 是 price-unknown，但 gp2 月额照填（填法表与 gp3_plan
    都如此）；规则若写成「price-unknown 行留空」，两个 runtime 会对这块卷在不在分母里
    给出两个答案。"""
    tpl = (REF / "report-template.md").read_text(encoding="utf-8")
    assert "`price-unknown` 行的 `cur_cost_mo`" not in tpl, "规则仍按 verdict 判成本留空"
    assert "`cur_cost_mo` 留空的行" in tpl, "规则没有改成按 cur_cost_mo 是否留空来判"
    out = core.gp3_plan(_vol(80), T_AGG, dict(PRICE, gp3_iops_mo=None))
    assert out["verdict"] == "price-unknown" and out["cur_cost_mo"] == 8.0, out


def test_short_coverage_is_disclosed_not_silently_sized_as_full_window():
    """卷在窗口内新建或换过宿主（lm-ebs-attached.jq 丢掉旧宿主那条序列）⇒ 序列只覆盖
    窗口的一段。照常按实测定档（采样量决定置信度、不决定给不给建议），但必须写明覆盖了
    多少小时 —— 否则一个 48 小时的配置与 30 天的配置在交付物里看起来一样。"""
    short = core.gp3_plan(_vol(300, sample_n=48, window_points=720), T_AGG, PRICE)
    assert any("48/720" in b for b in short["blockers"]), short["blockers"]
    assert short["tput_basis"] == "measured", short
    full = core.gp3_plan(_vol(300, sample_n=720, window_points=720), T_AGG, PRICE)
    assert not any("/720" in b for b in full["blockers"]), full["blockers"]
    legacy = core.gp3_plan(_vol(300), T_AGG, PRICE)   # 不带这两个键：行为与改动前相同
    assert not any("/720" in b for b in legacy["blockers"]), legacy["blockers"]


def test_counter_paragraph_does_not_sit_under_the_nitro_rate_metrics():
    """metrics-catalog 的 EBS 一节：「这四行都是计数类 … ÷ 发布间隔」只讲 Volume*Ops/Bytes。
    Nitro 速率表若排在它前面，「这四行」读起来就指 VolumeAvgIOPS —— 正是 spec 禁止的换算。"""
    s = (REF / "metrics-catalog.md").read_text(encoding="utf-8")
    sec = s.split("## EBS — `AWS/EBS`", 1)[1].split("\n## ", 1)[0]
    assert sec.index("**这四行都是计数类") < sec.index("**Nitro 专有的四个指标"), (
        "Nitro 速率表排在了「这四行都是计数类」那段之前")


def test_persistent_iops_exceeded_forces_iops_parity():
    """spec「测试影响」要求两个维度各自的持续触顶都有测试；这是 IOPS 维度。"""
    out = core.gp3_plan(_vol(2000, iops_exceeded_p95=1, iops_exceeded_hours=80), T_AGG, PRICE)
    assert out["gp3_iops"] == 6000 and out["iops_basis"] == "exceeded-parity", out
    assert out["gp3_mibps"] == 125 and out["tput_basis"] == "measured", out
    assert any("IOPS 持续触顶" in b and "80 小时" in b for b in out["blockers"]), out["blockers"]


def test_occasional_iops_exceeded_is_measured_with_a_note():
    out = core.gp3_plan(_vol(2000, iops_exceeded_p95=0, iops_exceeded_hours=4), T_AGG, PRICE)
    assert out["gp3_iops"] == 3000 and out["iops_basis"] == "measured", out
    assert any("IOPS 偶发触顶" in b and "4 小时" in b for b in out["blockers"]), out["blockers"]


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
