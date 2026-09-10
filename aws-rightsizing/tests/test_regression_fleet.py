"""回归基线：真实机队（脱敏）的总额与 verdict 分布，两个 profile 各一组。

为什么必须有这个文件
--------------------
本分支此前的回归基线是仓库外的一份 fixture（`/tmp` 下，重启即失），
客户拿不到、下一个改 `core.py` 的人也拿不到。更糟的是它把每台资源的
`cpu_n` 填成 **720**——那是 30 天窗口的**全窗口**点数
（`biz + off + weekend == WINDOW_DAYS × 24`），而 `cpu_n` 的定义是
**biz-hours 档**的点数，是全窗口的子集。子集不可能等于全集。

后果是采样量守卫（`min_biz_hours_points`）在那份 fixture 上**从未触发**：
13 台全部产出降配建议，总额被高估。所以「守卫失效」这类缺陷在回归里
一次都没有被抓到过（C1 就是这么活下来的）。

本 fixture 用同一次运行的**真实 biz-hours 点数**：11 台 243，两台 154 与 55。
**2026-09-09 起，后两台不再是 `insufficient-data`** —— 采样量从「拒绝线」改成
「置信度分档线」后，它们照常出降配建议并带 `confidence=low`。
**那两条仍然是本文件的要点**，只是要点从「被拒绝」变成「被降档」：
`test_sampling_downgrade_actually_fires_on_this_fixture` 显式点名它们的
`confidence` 必须为 `low`，防止有人"顺手"把它们改成满样本的值 ——
那正是本文件开头讲的那份 `cpu_n=720` 失效 fixture 的形状。
"""
import json, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).parent.parent
CORE = ROOT / "references" / "core.py"
FIXTURE = ROOT / "tests" / "fixtures" / "regression-fleet.json"

# 实测基线。改动 core.py / thresholds.json 后这些数字若变，必须先解释清楚为什么。
#
# ── 基线迁移记录：2026-09-04，内存降幅地板 ────────────────────────────────
# 旧值（**已撤回，但保留在此**）：
#     aggressive   route1_nb = 401.51   route2_max = 551.97
#     conservative route1_nb = 312.48   route2_max = 413.22
# 新值（本文件 EXPECTED 的当前内容）：
#     aggressive   route1_nb = 401.51   route2_max = 534.01
#     conservative route1_nb = 312.48   route2_max = 395.26
#
# 成因：加了 `max_mem_reduction_ratio` 内存降幅地板（`core.py` 的
# `passes_common`），滤掉了内存降幅超限的候选。此前只有 vCPU 有降幅地板，
# 内存无任何比例约束。
#
# 逐条对账（两个 profile 完全相同的两处变化，合计 −$17.96）：
#   i-EX-01  burst  2C/4G  t3a.micro(2C/1G, $30.81) → t3a.small(2C/2G, $21.83)
#   i-EX-10  burst  2C/4G  t3a.micro(2C/1G, $69.20) → t3a.small(2C/2G, $60.22)
# 两台都是 4 GiB → 1 GiB（**4x**）被地板拦下，改选 4 GiB → 2 GiB（2x）。
# i-EX-01 的 −$8.98 与 i-EX-10 的 −$8.98（69.20−60.22，其 nonburst $30.95
# 不受影响）之和即 −$17.96：551.97−17.96=534.01、413.22−17.96=395.26。
#
# **route1_nb 两个 profile 都一分不变**，因为路线一只取 non-burstable，
# 而没有任何 non-burstable 候选超限——i-EX-10 的 `c7a.medium`(1C/2G) 是
# 4 GiB → 2 GiB，正好顶在上限上（`ceil(4/3)=2` 与 `ceil(4/2)=2` 都等于 2），
# 两个 profile 下都放行。条数与桶分布同样不变：被拦下的两条都找到了替代候选，
# 没有资源因此变成"已合理配置"。
#
# 旧值不删的理由：本项目上一轮删过退役数字，几个月后有人从过期文档里
# 重新推导出来当成现值。撤回的数字必须带「为什么撤回」留在原地。
# ─────────────────────────────────────────────────────────────────────
#
# ── 基线迁移记录：2026-09-09，采样守卫改置信度分档 ──────────────────────
# 旧值（**已撤回，但保留在此**）：
#     aggressive   route1_nb = 401.51   route2_max = 534.01
#                  verdicts  = downsize 11, insufficient-data 2
#     conservative route1_nb = 312.48   route2_max = 395.26
#                  verdicts  = downsize 10, insufficient-data 2, 已合理配置 1
# 新值（本文件 EXPECTED 的当前内容）：
#     aggressive   route1_nb = 527.15   route2_max = 668.85
#                  verdicts  = downsize 13
#     conservative route1_nb = 373.00   route2_max = 492.72
#                  verdicts  = downsize 12, 已合理配置 1
#
# 成因：`min_biz_hours_points` 从「拒绝线」改为「置信度分档线」。fixture 里
# i-EX-03（cpu_n=55）与 i-EX-07（cpu_n=154）不再被拒绝，改为出建议 +
# confidence=low。逐条对账：
#   aggressive   i-EX-03 → r6g.large  nb +65.12  b +27.74
#                i-EX-07 → m6g.large  nb +60.52  b +69.72
#                route1  401.51 + 65.12 + 60.52 = 527.15
#                route2  逐条取 max(nb, b)：i-EX-03 取 nb 65.12（>27.74）、
#                        i-EX-07 取 b 69.72 ⇒ 534.01 + 65.12 + 69.72 = 668.85
#   conservative i-EX-03 无 non-burstable 候选（nb=None），只贡献 b 27.74
#                i-EX-07 → m6g.large  nb +60.52  b +69.72
#                route1  312.48 + 60.52 = 373.00
#                route2  395.26 + 27.74 + 69.72 = 492.72
#
# ⚠️ **$527.15 这个数字在本仓库历史上被标注为「已作废」，它的重现不是回归。**
# 当年那份坏 fixture 把每台的 cpu_n 填成 720（全窗口点数），守卫因此从未触发，
# 13 台全部被判据 ⇒ 得 527.15。现在守卫改成降档，13 台又全部被判据 ⇒ 回到
# 同一个数。两者**总额相同而成因相反**：一个是守卫失效，一个是守卫改成分档。
# 判别式：现在 i-EX-03 与 i-EX-07 的 confidence 必须是 `low`
# （见 test_sampling_downgrade_actually_fires_on_this_fixture），
# 而坏 fixture 那次它们是 `high`。**下一个看到 527.15 的人先读这一段。**
# ─────────────────────────────────────────────────────────────────────
EXPECTED = {
    "aggressive": {
        "rows": 13,
        "verdicts": {"downsize": 13},
        "buckets": {"downsize": 13},
        "route1_nb": 527.15,      # Σ nb_save_mo，一律取 non-burstable
        "route2_max": 668.85,     # Σ max(nb, b)，逐条取更省者
    },
    "conservative": {
        "rows": 13,
        "verdicts": {"downsize": 12, "已合理配置": 1},
        "buckets": {"downsize": 12, "excluded": 1},
        "route1_nb": 373.00,
        "route2_max": 492.72,
    },
}
# 窗口 30 天 ⇒ 全窗口点数。cpu_n 是 biz-hours 子集，取到这个值就说明填错了口径。
FULL_WINDOW_POINTS = 30 * 24
BELOW_FLOOR = {"i-EX-03": 55, "i-EX-07": 154}


def _fixture():
    return json.loads(FIXTURE.read_text())


def _run(profile, **over):
    ctx = dict(_fixture(), sizing_profile=profile, **over)
    ctx.pop("_comment", None)
    p = subprocess.run([sys.executable, str(CORE)], input=json.dumps(ctx),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-1500:]
    return json.loads(p.stdout)


def _summary(rows):
    """两条降配路线**必须带 `bucket == "downsize"` 作用域**，与 report-template.md
    的「汇总口径」和 `cli-recipes.md §6 ③` 同一个口径。

    不带作用域就是把 `bucket=idle` 行的 `nb_save_mo` 也算进路线一——那一列在闲置行上
    装的是"若须保持运行改为降配"的**替代方案**，该资源已按全额 `cur_cost_mo` 计入
    桶 B 合计，再进路线一就是同一笔钱两个口径各算一遍。本仓库已经在
    `cli-recipes.md §6` 犯过这个错一次。
    **本 fixture 恰好一条 idle 行都没有**（`test_no_idle_rows_in_this_fixture` 显式
    断言这件事），所以加作用域不改任何基线数字；但基线锚定用的求和式不能是错的口径，
    否则将来 fixture 一旦加进一条 idle 行，基线会因为错口径而静默变大。
    这条作用域的有效性由 `test_route_totals_exclude_idle_rows` 用一条**构造出来的**
    idle 行证明。
    """
    v, b = {}, {}
    for f in rows:
        v[f["verdict"]] = v.get(f["verdict"], 0) + 1
        b[f["bucket"]] = b.get(f["bucket"], 0) + 1
    dn = [f for f in rows if f["bucket"] == "downsize"]
    return {
        "rows": len(rows), "verdicts": v, "buckets": b,
        "route1_nb": round(sum(f.get("nb_save_mo") or 0 for f in dn), 2),
        "route2_max": round(sum(max(f.get("nb_save_mo") or 0,
                                    f.get("b_save_mo") or 0) for f in dn), 2),
    }


def _bucket_b(rows):
    """桶 B 合计 = Σ cur_cost_mo over bucket == "idle"（不是 Σ nb_save_mo）。"""
    return round(sum(f.get("cur_cost_mo") or 0
                     for f in rows if f["bucket"] == "idle"), 2)


def test_fixture_cpu_n_is_biz_hours_not_full_window():
    """cpu_n 必须是 biz-hours 点数。等于全窗口点数就是口径填错。

    这条断言是整份 fixture 的地基：口径一错，采样量守卫恒不触发，
    后面所有总额都偏高，而且没有任何信号。
    """
    res = _fixture()["resources"]
    bad = [r["rid"] for r in res if r["cpu_n"] >= FULL_WINDOW_POINTS]
    assert not bad, (f"{bad} 的 cpu_n >= 全窗口点数 {FULL_WINDOW_POINTS}，"
                     "这是全窗口口径，不是 biz-hours 子集")


def test_sampling_downgrade_actually_fires_on_this_fixture():
    """至少有一条资源走了降档路径。全过的 fixture 守不住「分档失效」这类缺陷。

    这条断言同时是 $527.15 的判别式：本文件的基线迁移注释解释了为什么这个
    被撤回过的数字会重现 —— 当年是守卫失效（那时这两台的 confidence 是
    `high`），现在是守卫改成分档（confidence 必须是 `low`）。
    """
    rows = {f["rid"]: f for f in _run("aggressive")}
    low = {rid: f for rid, f in rows.items() if f.get("confidence") == "low"}
    assert set(low) == set(BELOW_FLOOR), (
        f"低于采样地板的资源应降档为 low，应为 {sorted(BELOW_FLOOR)}，"
        f"实际 {sorted(low)}")
    for rid, f in low.items():
        assert f["verdict"] == "downsize", (
            f"{rid} 样本不足仍应出建议，实际 {f['verdict']}")
        assert f["bucket"] == "downsize", f
        blockers = " ".join(f.get("blockers") or [])
        assert "样本" in blockers and str(BELOW_FLOOR[rid]) in blockers, (
            f"{rid} 的 blockers 未写明样本量 —— {f.get('blockers')}")
    assert not [f for f in rows.values() if f["verdict"] == "insufficient-data"], (
        "本 fixture 没有 cpu_n 为 0 或缺失的资源，不应再出现 insufficient-data")


def test_regression_totals_both_profiles():
    """两个 profile 的条数、桶分布、两条路线合计都必须逐值命中。"""
    for profile, exp in EXPECTED.items():
        got = _summary(_run(profile))
        assert got == exp, f"{profile} 偏离基线：\n  期望 {exp}\n  实际 {got}"


def test_no_idle_rows_in_this_fixture():
    """本 fixture 没有 `bucket=idle` 的行——`_summary` 的作用域为何不移动基线，
    靠的就是这个事实，所以它必须是一条显式断言而不是一句注释。

    将来谁往 fixture 里加了闲置资源，这条先红：那时基线**应当**重算，
    而且必须按带作用域的口径重算，不能让全表求和把闲置行的替代方案混进路线一。
    """
    for profile in EXPECTED:
        rows = _run(profile)
        idle = [f["rid"] for f in rows if f["bucket"] == "idle"]
        assert not idle, (
            f"{profile}: fixture 现在有 idle 行 {idle}。基线要重算，"
            "且 _summary 的 bucket==downsize 作用域此刻开始真正改变数字——"
            "先读它的 docstring 再改 EXPECTED")


def test_route_totals_exclude_idle_rows():
    """作用域必须真的在起作用：构造一条 idle 行，它的节省额不得进路线一/二。

    只断言「fixture 没有 idle 行」是不够的——那种条件下把作用域整段删掉，
    所有断言照样绿（这正是本条修复前的状态）。所以这里现造一条闲置资源：
    它同时带 `nb_save_mo`（替代方案）与 `cur_cost_mo`（删除可省全额），
    然后要求路线一/二只认后者的桶 B 口径、一分不涨。
    """
    res = _fixture()["resources"]
    # 探针必须复制一台**本来就产出 non-burstable 节省额**的资源：拿 res[0] 试过，
    # 它的 nonburst 是 None（只有 burstable 候选），于是路线一根本不会被影响，
    # 断言就成了空的。所以捐赠者从实跑结果里挑，不硬编码下标。
    donor_rid = next(f["rid"] for f in _run("aggressive")
                     if (f.get("nb_save_mo") or 0) > 0)
    donor = next(r for r in res if r["rid"] == donor_rid)
    idle_res = dict(donor, rid="i-EX-idle-probe", sus_cpu=1, peak_cpu=2, net_mb_day=0)
    rows = _run("aggressive", resources=res + [idle_res])
    probe = [f for f in rows if f["rid"] == "i-EX-idle-probe"]
    assert len(probe) == 1, rows
    probe = probe[0]
    # 前提：这条探针行必须真的既是 idle、又带着节省额，否则本断言什么也没证明
    assert probe["bucket"] == "idle", probe
    assert (probe.get("nb_save_mo") or 0) > 0, (
        f"探针行没带 nb_save_mo，证明不了「闲置行的节省额被排除」—— {probe}")
    assert (probe.get("cur_cost_mo") or 0) > 0, probe

    got = _summary(rows)
    exp = EXPECTED["aggressive"]
    assert got["route1_nb"] == exp["route1_nb"], (
        f"加了一条 idle 行后路线一从 {exp['route1_nb']} 变成 {got['route1_nb']}"
        f"——作用域没生效，闲置行的替代方案被算进了降配合计")
    assert got["route2_max"] == exp["route2_max"], got["route2_max"]
    # 而它的钱确实出现在桶 B 合计里，一分不少
    assert _bucket_b(rows) == probe["cur_cost_mo"], (
        f"桶 B 合计 {_bucket_b(rows)} 应等于该行全额 {probe['cur_cost_mo']}")
    assert _bucket_b(_run("aggressive")) == 0, "无 idle 行时桶 B 合计应为 0"


# 三个节省额列。`other_save_mo` 是采集侧列、`core.py` 从不产出它，
# 但它照样要在这条不变式里：这条不变式管的是「excluded 行不带钱」，
# 而不是「core.py 不产出某列」——将来采集侧往 excluded 行上填它同样破坏等价性。
SAVE_COLS = ("nb_save_mo", "b_save_mo", "other_save_mo")


def test_excluded_rows_never_carry_savings():
    """`bucket == "excluded"` 的行不得带任何节省额。

    **这条不变式是两种写法等价的前提，而此前它没有被写下来过。**
    `report-template.md` 的口径块写 `over bucket == "downsize"`（allowlist），
    `cli-recipes.md §6 ③` 的 jq 写 `select(.bucket != "idle")`（denylist）。
    两者同值，唯一的理由就是 excluded 行不带钱。

    哪天出现一条既 `excluded` 又带金额的行——新 verdict、新资源类型、
    或一个知道自己成本的 `price-unknown` 变体——文档那一侧会**漏掉**那笔钱，
    命令那一侧会**算进去**，两次运行的头条数字从此不同。那正是本轮要消灭的
    失效类，只不过是从「没人写下来的前提」这个后门进来的。

    这里用真实机队查**两个 profile**，覆盖 `已合理配置` 与 `insufficient-data`
    两种 excluded verdict。

    采样量改成置信度分档后，aggressive 的 13 行全部进 `downsize`，
    `insufficient-data` 也不再由低样本产生 —— 两种 excluded 来源都从 fixture 里
    消失了。**当时的应急做法是把本条收窄到只跑 conservative，那是覆盖倒退**：
    一个只在一个 profile 上验证的不变式，挡不住只在另一个 profile 上出现的违规。
    改为注入一条 `cpu_n=0` 的探针（「无」而不是「少」，仍 fail-closed ⇒
    `insufficient-data` ⇒ `excluded`），两个 profile 的覆盖都拿回来，
    并且顺带把「判不了的行不许带节省额」这一支也钉住了。
    手法与 `test_route_totals_exclude_idle_rows` 相同：把不变式钉在构造出来的
    行上，而不是指望 fixture 恰好含有那一形态。

    契约那一侧（采集侧自建行的 `other_save_mo` 该不该填）由
    `test_csv_contract.py` 的 `test_fill_table_covers_the_new_savings_column` 查表。
    """
    res = _fixture()["resources"]
    probe = dict(res[0], rid="i-EX-nodata-probe", cpu_n=0)
    for profile in EXPECTED:
        rows = _run(profile, resources=res + [probe])
        excluded = [f for f in rows if f["bucket"] == "excluded"]
        assert excluded, f"{profile}: fixture 里没有 excluded 行，本不变式无从验证"
        verdicts = {f["verdict"] for f in excluded}
        assert "insufficient-data" in verdicts, (
            f"{profile}: 探针未产出 insufficient-data ⇒ 那一支没被覆盖 —— {verdicts}")
        for f in excluded:
            # 用 `is not None` 而不是"真值判断"：契约要求留空，`0` 也是违规
            # （一个"确定为 0 的节省额"没有意义，只会让读者以为判过了）
            carried = {c: f[c] for c in SAVE_COLS if f.get(c) is not None}
            assert not carried, (
                f"{profile} 的 {f['rid']}（verdict={f['verdict']}）"
                f"bucket=excluded 却带着 {carried} —— 口径块的 allowlist "
                f"(bucket == \"downsize\") 会漏掉这笔钱，而 cli-recipes §6 ③ 的 "
                f"denylist (bucket != \"idle\") 会算进去，两种写法从此不等价")


def test_conservative_is_strictly_more_conservative():
    """conservative 的条数与总额都不得高于 aggressive。

    两个 profile 若产出相同，说明 ceil() 把差异吞掉了（本 skill 曾因此
    把 prod/non-prod 两列做成完全相同的输出，承诺了一个不存在的保护）。
    """
    a, c = _summary(_run("aggressive")), _summary(_run("conservative"))
    assert c["route1_nb"] < a["route1_nb"], (a["route1_nb"], c["route1_nb"])
    assert c["verdicts"]["downsize"] < a["verdicts"]["downsize"]


# max_reduction_ratio 压到 1（一核都不许砍）时，只剩同 vCPU 的换价候选。
RATIO_1_TOTAL = 63.69


def test_max_reduction_ratio_floor_is_live_and_respected():
    """两件事一起断言，缺后半段前半段就是空断言。

    ① 不变式：每条建议的实际 vCPU 降幅不超过该 profile 的上限。
    ② 地板真的在起作用：把上限压到 1，总额必须塌到 RATIO_1_TOTAL。

    只有 ① 时，把 `passes_common` 里那行地板整段删掉，测试照样通过——
    **实测过**：这支机队实际降幅最多 2x，而两个 profile 的上限是 3 与 2，
    地板从来没顶到过。①"通过"只是因为没人挑战它。
    """
    sys.path.insert(0, str(ROOT / "references"))
    import core
    for profile in EXPECTED:
        limit = core.load_thresholds(profile)["max_reduction_ratio"]
        for f in _run(profile):
            for key in ("nonburst", "burst"):
                pick = f.get(key)
                if pick:
                    ratio = f["cur_vcpu"] / pick["vcpu"]
                    assert ratio <= limit, (profile, f["rid"], key, ratio, limit)

    squeezed = _summary(_run("aggressive", thresholds=core.load_thresholds(
        "aggressive", override={"max_reduction_ratio": 1})))
    assert squeezed["route1_nb"] == RATIO_1_TOTAL, (
        f"max_reduction_ratio=1 时总额应为 {RATIO_1_TOTAL}，实际 "
        f"{squeezed['route1_nb']}——地板没有生效")
    assert squeezed["route1_nb"] < EXPECTED["aggressive"]["route1_nb"]


# max_mem_reduction_ratio 压到 1（一 GiB 都不许砍）时的路线一合计。
# 唯一被它多拦下的是 i-EX-10 的 nonburst：`c7a.medium`(4→2 GiB, $30.95)
# 落选，改选 `m7a.medium`(4→4 GiB, $23.45) ⇒ 旧基线 401.51 − 7.50 = 394.01。
# 2026-09-09 采样分档后：i-EX-03 与 i-EX-07 也进降配（+65.12 +60.52 = +125.64）
# ⇒ 394.01 + 125.64 = 519.65。两台的内存降幅都没顶到地板，所以增量与
# ratio=1 下的增量相同。
MEM_RATIO_1_TOTAL = 519.65

# 把上限放到实质无穷大时的路线二合计，两个 profile 各一个。
# **这是活量**：它是"关掉内存地板会得到什么"的当次实测值，会随 fixture 变。
#
# 注意 `10 ** 6` 只把 `floor_gib` 压到 1，**并不是把地板拿掉**：
# `ceil(g / 10**6)` 对任何现实的 g 都等于 1，所以低于 1 GiB 的候选仍然被拦着
# ——本 fixture 就有三个 0.5 GiB 的 nano（`t3.nano` / `t3a.nano` / `t4g.nano`）。
# 它等价于删掉地板，只因为当前每一行的 `required_gib` 都 >= 1；
# 哪天有行的 required_gib 落到 1 以下，这个 override 就不再等价于删除。
# 2026-09-09 采样分档后重测（旧值 aggressive 551.97 / conservative 413.22）：
# i-EX-03 与 i-EX-07 也进降配，两条路线各自涨一段。
MEM_FLOOR_OFF_ROUTE2 = {"aggressive": 686.81, "conservative": 510.68}

# 2026-09-04 随内存降幅地板一起撤回的那组路线二旧基线。**冻结值，永不随实测更新。**
#
# **它与 MEM_FLOOR_OFF_ROUTE2 曾经数值相同，2026-09-09 起分开了。** 当时相同是
# 因为撤回的原因正是加了这道地板，而"关掉地板"就回到撤回前的状态；采样分档
# 改了判据行为之后，"关掉地板"回到的是**新行为下**的无地板状态，与 2026-09-04
# 那次撤回的历史值不再是同一个数。
# 这次分离正好证明了当初拆成两个常量是对的：**上面那个是活量，下次改判据或
# fixture 就会变；这个是历史，不会变。**
# 合成一个常量的后果是：将来有人为了让 ③ 继续绿而重测出新值，
# test_thresholds_md_still_documents_the_withdrawn_totals 就会逼他把**新数字**
# 当成"2026-09-04 撤回的值"写进 thresholds.md ——
# 一条以保护退役数字为职责的断言，反而伪造了一条历史。
WITHDRAWN_ROUTE2_20260904 = {"aggressive": 551.97, "conservative": 413.22}


def test_mem_reduction_floor_is_live_and_respected():
    """内存降幅也必须受上限约束。三件事一起断言。

    ① 不变式：每条建议的实际内存降幅不超过该 profile 的上限。
    ② 把上限压到 1，路线一合计必须塌到 MEM_RATIO_1_TOTAL。
    ③ 把上限放到无穷大（地板关闭），路线二合计必须**涨回** MEM_FLOOR_OFF_ROUTE2
       且严格大于**当次实跑**的总额 —— 即证明地板此刻**正在**拦东西。

    实测缺陷（本条断言的由来）：一台 4 GiB 实例内存 p95 5.175% 被建议降到
    1 GiB（4 倍），confidence=high，两个 profile 都一样 —— 而同一 profile
    允许的 vCPU 降幅要小得多。这个不对称此前没有任何地方写出来。
    mem_used_percent 是 mem_used/mem_total、不含可回收 page cache，
    会把内存 p95 系统性压低，所以内存比 vCPU 更需要这道地板。

    与 vCPU 那条不同，① 在这支机队上**是有约束力的**：加地板之前跑本条断言
    确实红了（`aggressive i-EX-01 的 burst 内存降幅 4.00x 超过上限 3x
    —— 4 GiB → 1 GiB`），i-EX-10 的 burst 同形状。所以 ① 不是空断言。

    ③ 不可省，因为 ① 有一个结构性盲区：**上限值本身既被 core.py 的地板读，
    也被 ① 当作比较基准**。把 `max_mem_reduction_ratio` 在 thresholds.json 里
    改大，两边一起放松，① 恒真（实测：改成 1 或改大，① 都绿）。能戳破这种
    改动的只有 ③——它拿一个与阈值无关的实测总额当锚。
    """
    # 与相邻的 vCPU 那条统一走 core.load_thresholds()，不再直接读 JSON：
    # 两条相邻断言用两种写法读同一个真值源，日后只改一处就会静默分叉。
    sys.path.insert(0, str(ROOT / "references"))
    import core
    for profile in EXPECTED:
        limit = core.load_thresholds(profile)["max_mem_reduction_ratio"]
        for f in _run(profile):
            for key in ("nonburst", "burst"):
                pick = f.get(key)
                if not pick or not f.get("cur_gib"):
                    continue
                ratio = f["cur_gib"] / pick["gib"]
                assert ratio <= limit, (
                    f"{profile} {f['rid']} 的 {key} 内存降幅 {ratio:.2f}x "
                    f"超过上限 {limit}x —— {f['cur_gib']} GiB → {pick['gib']} GiB")

    squeezed = _summary(_run("aggressive", thresholds=core.load_thresholds(
        "aggressive", override={"max_mem_reduction_ratio": 1})))
    assert squeezed["route1_nb"] == MEM_RATIO_1_TOTAL, (
        f"max_mem_reduction_ratio=1 时路线一合计应为 {MEM_RATIO_1_TOTAL}，实际 "
        f"{squeezed['route1_nb']}——地板没有生效")
    assert squeezed["route1_nb"] < EXPECTED["aggressive"]["route1_nb"]

    for profile, off_route2 in MEM_FLOOR_OFF_ROUTE2.items():
        loose = _summary(_run(profile, thresholds=core.load_thresholds(
            profile, override={"max_mem_reduction_ratio": 10 ** 6})))
        assert loose["route2_max"] == off_route2, (
            f"{profile} 关掉内存地板后路线二合计应为 {off_route2}，"
            f"实际 {loose['route2_max']}。这是活量：若确认是 fixture 变了，"
            f"改 MEM_FLOOR_OFF_ROUTE2，**不要**动 WITHDRAWN_ROUTE2_20260904")
        # 比的是**当次实跑**的总额，不是 EXPECTED 常量。用常量比会漏掉
        # 「有人把 thresholds.json 的比例放宽」这一种改动：那时地板已失效，
        # 而 loose 与常量的关系纹丝不动（实测：比例改成 99 时本条仍绿）。
        live = _summary(_run(profile))
        assert loose["route2_max"] > live["route2_max"], (
            f"{profile} 关掉内存地板后总额没变大（都是 {live['route2_max']}）"
            f"——这道地板此刻没有拦下任何候选，① 已退化成空断言")


# 清空 legacy 清单后，i-EX-06（c7g.xlarge）会选中 a1.xlarge（Graviton1, 2018）。
# 2026-09-09 采样分档后：440.57 + 125.64（i-EX-03 与 i-EX-07 的 nb）= 566.21
LEGACY_OFF_TOTAL = 566.21


def test_legacy_family_filter_is_live():
    """清空 legacy 清单后总额必须变大——否则这道过滤在本 fixture 上守不住。

    fixture 的 `specs` 刻意保留了 `a1` / `c4` / `r4`：这三族只会被 legacy 过滤
    拦下，架构/分类/带宽/价格/降幅五道过滤都放行它们。所以这条断言同时验证了
    「legacy 是人工策展清单、且必须在跨分类放行之前执行」这条 ruling——
    实测被放进来的正是 `a1.xlarge`，与 `legacy-families.md` 记的
    「a1 同规格组最便宜，不拦必被选中」一致。
    """
    got = _summary(_run("aggressive", legacy_families=[]))
    assert got["route1_nb"] == LEGACY_OFF_TOTAL, (
        f"清空 legacy 后总额应为 {LEGACY_OFF_TOTAL}，实际 {got['route1_nb']}")
    assert got["route1_nb"] > EXPECTED["aggressive"]["route1_nb"], (
        "清空 legacy 清单后总额没变大：fixture 的 specs 里已经没有 legacy 机型了，"
        "这道过滤失效也测不出来")


# legacy-families.md「Graviton2 不列入清单」那段声称的代价（aggressive）。
# 480.2 与文档里写的 $480.20 是同一个数。
# 2026-09-09 采样分档后重测。增量不是 125.64：整代排除 Graviton2 会同时
# 排掉 i-EX-03 的 r6g.large 与 i-EX-07 的 m6g.large，两台改选别的候选，
# 所以两条路线各自重测而非加常数。
G2_EXCLUDED = {"route1_nb": 497.36, "route2_max": 595.62}


def test_legacy_families_md_graviton2_cost_is_reproducible():
    """legacy-families.md 引用的四个数必须能由本 fixture 复现。

    **这是本轮唯一真正腐烂过的文件，而它此前一条守卫都没有。** 加内存降幅
    地板后，它那两个路线二数字过期了一轮，靠人工发现。thresholds.md 已经因为
    "只查一半"吃过一次亏并补齐了两条路线——同一个论证不该止步于文件边界。

    族名**从该小节正文抽取**、不手写：文档改了族清单，下面的实跑结果就会变，
    这条断言就会红。所以它守的不只是四个数字，还有"这四个数是由这个族清单
    算出来的"这层因果。
    """
    txt = (ROOT / "references" / "legacy-families.md").read_text()
    parts = txt.split("### Graviton2 不列入清单", 1)
    assert len(parts) == 2, "legacy-families.md 找不到「Graviton2 不列入清单」小节"
    seg = parts[1].split("\n### ", 1)[0]
    head, _, _ = seg.partition("代价（")
    bases = re.findall(r"`([a-z][a-z0-9]*)`", head)
    assert bases, f"该小节正文里没抽到反引号包起来的族名：{head[:120]!r}"
    fams = {f for f in (s["t"].split(".")[0] for s in _fixture()["specs"])
            if any(f == b or f in (b + "d", b + "n", b + "dn") for b in bases)}
    assert fams, f"fixture 的 specs 里没有属于 {sorted(bases)} 的族"

    leg = json.loads((ROOT / "references" / "legacy-families.json").read_text())
    got = _summary(_run("aggressive", legacy_families=sorted(set(leg) | fams)))
    for route, want in G2_EXCLUDED.items():
        assert got[route] == want, (
            f"整代排除 Graviton2（{sorted(fams)}）后 {route} 应为 {want}，"
            f"实际 {got[route]}——legacy-families.md 那段数字已过期")

    # 锚到行上，理由同 test_thresholds_md_quotes_the_anchored_totals：
    # 全文匹配会被文件里别处的同一个数字喂饱。
    for label, baseline in (("路线一", EXPECTED["aggressive"]["route1_nb"]),
                            ("路线二", EXPECTED["aggressive"]["route2_max"])):
        hits = [l for l in seg.splitlines() if f"{label}从" in l]
        assert len(hits) == 1, (
            f"legacy-families.md 该小节里含 `{label}从` 的行应恰好一条，实际 {len(hits)}")
        route = "route1_nb" if label == "路线一" else "route2_max"
        for v in (baseline, G2_EXCLUDED[route]):
            assert str(v) in hits[0], (
                f"legacy-families.md 的 {label} 那行未引用 {v}：{hits[0].strip()}")


def test_insufficient_data_rows_carry_cost_when_price_available():
    """采样不足的行、在单价查得到时必须带成本,否则摘要分母漏项、节省比例虚高。

    实测：漏掉两台合计 $286.67/mo,比例从 23.2% 虚高到 27.7%。
    单价查表不依赖任何指标,是事实不是判断。
    """
    # 采样分档后，本 fixture 的 13 台全部有点数 ⇒ 没有天然的 insufficient-data
    # 行。现造一条 cpu_n=0 的探针（「无」而不是「少」，仍须 fail-closed），
    # 手法与 test_route_totals_exclude_idle_rows 相同：把不变式钉在构造出来的
    # 行上，而不是依赖 fixture 恰好含有那一形态。
    res = _fixture()["resources"]
    donor = res[0]
    probe = dict(donor, rid="i-EX-nodata-probe", cpu_n=0)
    rows = _run("aggressive", resources=res + [probe])
    ins = [f for f in rows if f["verdict"] == "insufficient-data"]
    assert ins == [f for f in rows if f["rid"] == "i-EX-nodata-probe"], (
        f"cpu_n=0 的探针应且只应判 insufficient-data —— {[f['rid'] for f in ins]}")
    for f in ins:
        assert f.get("cur_cost_mo") is not None, (
            f"{f['rid']} 是 insufficient-data 但没有 cur_cost_mo,"
            f"摘要分母会漏掉它 —— {f}")
        assert f.get("cur_usd") is not None, f
        assert f.get("nb_save_mo") is None and f.get("b_save_mo") is None, (
            f"{f['rid']} 采样不足却带了节省额 —— {f}")


def test_thresholds_md_quotes_the_anchored_totals():
    """thresholds.md 的预设对比必须引用本 fixture 产出的数字。

    先前那张表引用的是仓库里不存在的一次运行，谁也复现不出来。
    数字与 fixture 脱钩过一次，就会永远脱钩。

    **两条路线都要查。** 本条断言原先只查路线一，结果加内存降幅地板时
    路线一恰好一分未变、路线二动了 $17.96，那张表的路线二一列就这么
    静默过期了一次，而本条断言全程是绿的——"只查一半"的断言比不查更危险，
    因为它让人以为查过了。

    **必须锚到表格那一行，不能全文查。** 原先用 `str(v) in txt` 全文匹配，
    实测把表格里 aggressive 的路线一单元格改成 399.99 后本条仍然绿——
    因为 401.51 在本文件出现三次（表格、撤回说明、护栏依据那段），
    全文匹配被别处的同一个数字喂饱了。锚到行上，改哪个单元格就红哪一条。
    """
    rows = {}
    for line in (ROOT / "references" / "thresholds.md").read_text().splitlines():
        for profile in EXPECTED:
            if line.startswith(f"| {profile} |"):
                assert profile not in rows, (
                    f"thresholds.md 有多行以 `| {profile} |` 开头，"
                    "本断言无法确定该锚哪一行——请给预设对比表加个更明确的锚点")
                rows[profile] = line
    for profile, exp in EXPECTED.items():
        assert profile in rows, (
            f"thresholds.md 的预设对比表里找不到 `| {profile} |` 开头的行")
        for route in ("route1_nb", "route2_max"):
            assert str(exp[route]) in rows[profile], (
                f"thresholds.md 预设对比表的 {profile} 行未引用 {route} 合计 "
                f"{exp[route]}：{rows[profile]}")


def test_thresholds_md_still_documents_the_withdrawn_totals():
    """撤回的旧基线必须仍然写在 thresholds.md 里，带"为什么撤回"。

    本项目删过一次退役数字，几个月后有人从过期文档里把它们重新推导出来
    当成现值。所以撤回的数字要留在原地并标明作废，不是删掉。

    这里查的是**冻结的** WITHDRAWN_ROUTE2_20260904，不是活量
    MEM_FLOOR_OFF_ROUTE2——两者今天数值相同，但只有前者是"历史"。
    详见那两个常量上方的注释。
    """
    txt = (ROOT / "references" / "thresholds.md").read_text()
    for profile, old in WITHDRAWN_ROUTE2_20260904.items():
        assert str(old) in txt, (
            f"thresholds.md 不再提及 {profile} 于 2026-09-04 撤回的路线二旧值 "
            f"{old}。退役数字要保留并标注作废，删掉会让它被重新推导出来当现值")


if __name__ == "__main__":
    tests = [test_fixture_cpu_n_is_biz_hours_not_full_window,
             test_sampling_downgrade_actually_fires_on_this_fixture,
             test_regression_totals_both_profiles,
             test_no_idle_rows_in_this_fixture,
             test_route_totals_exclude_idle_rows,
             test_excluded_rows_never_carry_savings,
             test_conservative_is_strictly_more_conservative,
             test_max_reduction_ratio_floor_is_live_and_respected,
             test_mem_reduction_floor_is_live_and_respected,
             test_legacy_family_filter_is_live,
             test_legacy_families_md_graviton2_cost_is_reproducible,
             test_insufficient_data_rows_carry_cost_when_price_available,
             test_thresholds_md_quotes_the_anchored_totals,
             test_thresholds_md_still_documents_the_withdrawn_totals]
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
