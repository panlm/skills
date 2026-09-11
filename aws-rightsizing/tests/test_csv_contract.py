import json, pathlib, re, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "references"))
import core

SPECS = [{"t": "m5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
          "arch": "x86_64", "store": False, "ebs": 143.75, "curgen": True},
         {"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
          "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True},
         # t3.large 是**唯一能过内存降幅地板的 burstable 候选**，缺它则
         # b_cat / b_delta_vcpu / b_delta_gib 三列不产出，
         # test_no_documented_column_is_fabricated 会把它们判成"契约里的虚构列"。
         # 加 max_mem_reduction_ratio 时实测撞到过：当前机型 16 GiB ⇒
         # floor_gib = ceil(16 / 上限)，t3.small 的 2 GiB（8x 降幅）被拦下，
         # 于是这份 fixture 里再没有 burstable 候选。
         # 后来动这份 SPECS 的人：burstable 候选的内存不能离当前机型太远。
         {"t": "t3.large", "vcpu": 2, "gib": 8, "burst": True,
          "arch": "x86_64", "store": False, "ebs": 86.875, "curgen": True},
         # t3.small 在这份 fixture 里**永远选不上**（2 GiB 顶不住 floor_gib），
         # 但**故意留着**：它是这里唯一一个会被内存地板真正拦下的候选，
         # 少了它，地板在本文件就成了一道从不触发的过滤。要删的不是它。
         {"t": "t3.small", "vcpu": 2, "gib": 2, "burst": True,
          "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True}]
PRICES = {"m5.xlarge|RunInstances": 0.192, "m5.large|RunInstances": 0.096,
          "t3.large|RunInstances": 0.0832, "t3.small|RunInstances": 0.0208}
# baseline_pct 是小数（t3.small 基线 20% ⇒ 0.2），不是百分数：
# 写成 20 会让 t3.small 交付 40 个有效 vCPU，回收量算成负数
BASELINE = {"t3.small": 0.2, "t3.large": 0.3}
CATS = {"m5.xlarge": "General purpose", "m5.large": "General purpose",
        "t3.large": "General purpose", "t3.small": "General purpose"}
RES_EC2 = {"rid": "i-EX", "service": "ec2", "type": "m5.xlarge", "arch": "x86_64",
           "operation": "RunInstances", "sus_cpu": 5, "peak_cpu": 15,
           "sus_mem": 3, "peak_mem": 5, "ebs_need": 1,
           "surplus_credits": 0, "cpu_n": 243, "metric_coverage": []}
# 三个 bucket 值与三个 stop_candidate 态都要有资源产出，否则
# test_documented_enums_cover_every_produced_value 只查到实际出现过的那一个值：
# 实测过——只有 RES_EC2 时把 `excluded` 从枚举里删掉，那条断言照样绿。
_BANDS_QUIET = {"off_sus_cpu": 1, "off_peak_cpu": 2, "off_net_mb_day": 0,
                "weekend_sus_cpu": 1, "weekend_peak_cpu": 2, "weekend_net_mb_day": 0}
RES_EC2_IDLE = dict(RES_EC2, rid="i-EX-idle", sus_cpu=1, peak_cpu=2,
                    net_mb_day=0, **_BANDS_QUIET)                    # bucket=idle + stop=true
RES_EC2_BUSY_OFF = dict(RES_EC2, rid="i-EX-busy-off", net_mb_day=999,
                        **dict(_BANDS_QUIET, off_peak_cpu=99))       # stop=false
# cpu_n 低于 min_biz_hours_points ⇒ 照常出建议但 confidence=low（不再是
# bucket=excluded：采样量现在是分档线不是拒绝线）。这条同时是 `low` 在
# confidence 枚举里的唯一覆盖来源——删掉它，把 `low` 从枚举里删掉也照样绿。
RES_EC2_NEW = dict(RES_EC2, rid="i-EX-new", cpu_n=1)                 # confidence=low
# 无内存数据 ⇒ confidence 上限 medium，且需求内存保持当前规格 ⇒ 无候选 ⇒
# 已合理配置/excluded。它同时是 `medium` 与 `excluded` 两个枚举值的覆盖来源；
# 少了它，把任一个从枚举里删掉，
# test_documented_enums_cover_every_produced_value 照样绿（实测过）。
RES_EC2_NOMEM = dict(RES_EC2, rid="i-EX-nomem", sus_mem=None, peak_mem=None,
                     metric_coverage=["mem"])          # confidence=medium, bucket=excluded
# 三条托管 fixture 都带 sample_n：不带的话 dispatch() 的采样量守卫会在判据之前
# 短路成 insufficient-data，于是「跑一次托管判据」实际上一条判据都没跑到。
RES_RDS = {"rid": "db-EX", "service": "rds", "type": "db.r6g.large", "vcpu": 2,
           "mem_gib": 16, "surplus_credits": 0, "dbload_p95": 0.4,
           "freeable_mem_min_gib": 9.6, "sample_n": 243,
           "cheaper_candidate_exists": True}
RES_CACHE = {"rid": "cache-EX", "service": "elasticache", "has_replica": False, "type": "cache.r7g.large",
             "vcpu": 2, "mem_gib": 13.07, "evictions_sum": 0, "repl_lag_max": 0.2,
             "engine_cpu_p95": 12, "db_mem_used_pct_max": 35,
             "reserved_memory_pct": None, "cheaper_candidate_exists": True,
             "sample_n": 243}
RES_MSK = {"rid": "msk-EX", "service": "msk", "type": "kafka.m7g.xlarge",
           "under_replicated_max": 0, "disk_used_max": 18,
           "handler_idle_p95": 0.94, "cpu_total_p95": 15,
           "cheaper_candidate_exists": True, "sample_n": 243}

DOC = ROOT / "references" / "report-template.md"

# 采集侧补齐的列。service / bucket / blockers **不在此列**——core.py 产出它们，
# 把它们当派生列会让采集侧去合成已经存在的列（实测踩过，见 report-template 契约表）。
# 这份清单同时被 test_derived_columns_match_the_document 与 report-template.md
# 的「由采集侧补齐的派生列」那一行对齐——两处不一致即失败。
DERIVED = {"account", "region", "resource_name", "instance_count",
           "sample_points", "window_profile", "action_type",
           "evidence_cpu_p95", "evidence_cpu_max",
           "evidence_mem_p95", "evidence_mem_max", "other_save_mo"}

# 表里「该列由判据填，采集侧不要合成」的写法。
CORE_FILLED = "core.py"
# 18×N 表要逐格校验的枚举列 → 合法值取自哪个块。
TABLE_ENUM_COLS = ("service", "verdict", "bucket", "action_type",
                   "confidence", "window_profile")


def _fenced(tag):
    """取 report-template.md 里某个带 tag 的代码块正文。"""
    m = re.search(rf"```{tag}\n(.*?)```", DOC.read_text(), re.S)
    assert m, f"report-template.md 缺少 ```{tag}``` 块"
    return m.group(1)


def _documented_columns():
    return {c.strip() for c in _fenced("csv-columns").replace("\n", ",").split(",")
            if c.strip()}


def _documented_enums():
    """```enum-values``` 块 → {列名: {合法值}}。

    值写成 `(empty)` 的表示「该格留空」，在这里映射成 None——CSV 的空格与
    JSON 的键缺失是同一件事，而 `null` 是一个**有值**的状态，两者不可混。
    """
    out, cur = {}, None
    for line in _fenced("enum-values").splitlines():
        if not line.strip():
            continue
        if ":" in line and not line.lstrip().startswith("|"):
            cur, _, rest = line.partition(":")
            cur = cur.strip()
            out[cur] = set()
        else:
            rest = line
        for v in rest.split("|"):
            v = v.strip()
            if v:
                out[cur].add(None if v == "(empty)" else v)
    return out

def _ec2_ctx():
    ctx = {"thresholds": core.load_thresholds("aggressive"), "specs": SPECS,
           "prices": PRICES, "baseline_pct": BASELINE, "categories": CATS,
           "offerings": [s["t"] for s in SPECS], "legacy_families": []}
    ctx["_specs_by_type"] = {s["t"]: s for s in SPECS}
    ctx["_offerings"] = set(ctx["offerings"]); ctx["_legacy"] = set()
    return ctx

def _sample_finding():
    return core.evaluate(RES_EC2, _ec2_ctx())

def _produced_keys():
    """四个 producer 的输出键并集 + main() 补齐的键。

    只跑 evaluate() 是不够的：契约漏掉 eval_elasticache 的 required_gib_usable
    整整一轮无人发现，因为这个测试当时只覆盖 1/4 个 producer。
    """
    t = core.load_thresholds("aggressive")
    keys = set(_sample_finding())
    keys |= set(core.eval_rds(RES_RDS, t))
    keys |= set(core.eval_elasticache(RES_CACHE, t))
    keys |= set(core.eval_msk(RES_MSK, t))
    keys |= _main_stamped_keys()
    return keys

def _core_rows(resources):
    """跑一次 core.py 取真实输出行。

    **枚举值与列清单一律从这里取，不读 core.py 的源码去推。**
    `core.py` 没有 `sizing_profile` 会直接 `KeyError`，所以这里统一注入 aggressive。
    """
    ctx = {"sizing_profile": "aggressive", "specs": SPECS, "prices": PRICES,
           "baseline_pct": BASELINE, "categories": CATS,
           "offerings": [s["t"] for s in SPECS], "legacy_families": [],
           "resources": resources}
    p = subprocess.run([sys.executable, str(ROOT / "references" / "core.py")],
                       input=json.dumps(ctx), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    rows = json.loads(p.stdout)
    assert len(rows) == len(resources), rows
    return rows

def _run_rows():
    return _core_rows([RES_EC2, RES_EC2_IDLE, RES_EC2_BUSY_OFF, RES_EC2_NEW,
                       RES_EC2_NOMEM, RES_RDS])

def _managed_rows():
    """三条托管判据各跑一行。

    只跑 RDS 是不够的：contract 测试的覆盖面漏过一次
    （eval_elasticache 的 required_gib_usable 整轮无人发现）。
    """
    return _core_rows([RES_RDS, RES_CACHE, RES_MSK])

def _main_stamped_keys():
    """main() 在每行上补的键——从真实输出取，不手列。

    手列过 {"service", "bucket", "stop_candidate"}：那份清单让
    test_every_output_key_is_documented 的名字兑现不了「每个键」，
    main() 再补第四个键时契约漏了也没人发现。这正是 GUARDED 清单
    刚被改成从 thresholds.json 生成的同一个反模式。
    """
    produced = set().union(*(set(r) for r in _run_rows()))
    # 两条 producer 自己的键不算 main() 补的
    own = set(core.evaluate(RES_EC2, _ec2_ctx())) | set(
        core.eval_rds(RES_RDS, core.load_thresholds("aggressive")))
    return produced - own

def test_every_output_key_is_documented():
    """core.py 输出的每个键都必须在 report-template.md 的列清单里。"""
    produced = _produced_keys()
    missing = produced - _documented_columns()
    assert not missing, f"实现输出了未记入契约的字段: {sorted(missing)}"

def test_no_documented_column_is_fabricated():
    """反向：契约里不得有实现根本不产出的字段（除派生列）。"""
    fabricated = _documented_columns() - _produced_keys() - DERIVED
    assert not fabricated, f"契约声明了实现不产出且非派生的字段: {sorted(fabricated)}"

def test_derived_columns_match_the_document():
    """本文件的 DERIVED 与 report-template.md 的派生列清单必须逐项一致。

    反向断言（test_no_documented_column_is_fabricated）拿 DERIVED 当豁免名单：
    往 DERIVED 里多加一个名字，就能让一个 core.py 根本不产出的虚构列静默过关。
    这条断言把豁免名单钉在文档上，改一处不改另一处即红。
    """
    line = re.search(r"\*\*由采集侧补齐的派生列\*\*(.*?)\n\n", DOC.read_text(), re.S)
    assert line, "report-template.md 缺少「由采集侧补齐的派生列」段落"
    # `[a-z0-9_]+` 的 0-9 不可省：漏掉数字会静默漏掉 evidence_*_p95 两列，
    # 断言仍然"通过"到只剩两处都写了的那些名字。
    documented = set(re.findall(r"`([a-z0-9_]+)`", line.group(1)))
    assert documented == DERIVED, (
        f"派生列清单两处不一致：文档独有 {sorted(documented - DERIVED)}，"
        f"本文件独有 {sorted(DERIVED - documented)}")

def _stop_candidate_section():
    """「stop_candidate 的四种情形」那一节的正文，**到下一个 ### 为止**。

    上一版在整节后面 1200 个字符里找「留空」，而「留空」在邻近散文里出现了三次
    ⇒ 把四态块里那一条删掉，断言照样绿（实测）。这与本项目已经吃过两次的
    「拿整份文件去证明某一处」是同一个形状：范围必须收到那一处。
    """
    doc = DOC.read_text()
    parts = doc.split("### `stop_candidate` 的四种情形", 1)
    assert len(parts) == 2, "report-template.md 缺少「stop_candidate 的四种情形」小节"
    return parts[1].split("\n### ", 1)[0]


def test_stop_candidate_four_states_are_each_documented():
    """四态块里四条**逐条**都要在，删掉任何一条即红。

    R4 的第四态（留空）是本任务补的契约，它只写在这一个块里；
    第三态（`null`）与它的区别是整条 ruling 的要点。
    """
    block = _fenced("stop-candidate-states")
    bullets = [b.strip() for b in block.splitlines() if b.strip().startswith("-")]
    for state, why in (("`true`", "是候选"), ("`false`", "判过了、不是候选"),
                       ("`null`", "判不了"), ("留空", "未评估")):
        hit = [b for b in bullets if state in b]
        assert hit, (f"四态块里缺「{state}」那一条（{why}）——"
                     f"当前只有 {len(bullets)} 条：{bullets}")


def test_stop_candidate_column_survives_allow_stop_off():
    """`stop_candidate` 列必须留在契约里，且该节必须写明关掉时是「留空不删列」。

    实测的两种契约违反：一个 runtime 给这一列填了违反枚举的字符串，
    另一个直接删列（40 列变 39 列）——两份 findings.csv 连列数都不同。
    「core.py 每行都产出它」由 test_empty_stop_candidate_is_report_layer_only 守，
    四态齐全由 test_stop_candidate_four_states_are_each_documented 守，
    这里只钉「列在契约里」+「该节禁止删列」。

    上一版只查了前半段：把该节改写成「把该列整列从 CSV 删除」——即 R4 明令禁止的
    那种做法——上一版的断言照样全绿（review 实测）。所以后半段必须查那两句禁止语本身。
    """
    assert "stop_candidate" in _documented_columns(), (
        "stop_candidate 不在契约列清单里 —— 该列不得删除，"
        "allow_stop_recommendations=no 时是留空不是删列")
    sec = _stop_candidate_section()
    assert "allow_stop_recommendations" in sec, (
        "该节未说明 allow_stop_recommendations=no 时这一列怎么填")
    assert "保留在 CSV 里但留空" in sec, (
        "该节没写「保留在 CSV 里但留空」——R4 禁止的正是删列与填 false 两种做法")
    assert "不得从 CSV 删除" in sec, "该节没写「不得从 CSV 删除」"

    # `thresholds.md` 此前是唯一还写着「整列不输出 …… 丢弃该列」的地方，
    # 而那正是 R4 禁止、且上一轮真实运行**实测**发生过的契约违规（列数变化）。
    # 这一段没有任何断言看过，所以在这里一并守住。
    #
    # 只看**指令行**：撤回说明按本仓库惯例写在 `>` 引用块里并逐字引用旧写法，
    # 那是刻意留的病历，不能被当成指令（不剥掉就必然假红）。
    lines = (ROOT / "references" / "thresholds.md").read_text().splitlines()
    instr = [l for l in lines if not l.lstrip().startswith(">")]
    for phrase in ("整列不输出", "丢弃该列"):
        hits = [l.strip() for l in instr if phrase in l]
        assert not hits, (
            f"thresholds.md 的指令行里又写了「{phrase}」——`allow_stop_recommendations=no` "
            f"时是留空而不是删列，改列数会破坏下游校验（R4，实测违规过）：{hits}")
    assert any("保留在 CSV 里但留空" in l for l in instr), (
        "thresholds.md 没写「保留在 CSV 里但留空」——四处里三处写对、一处写反，"
        "而写反的那处正好在阈值真值源文件里")


def test_literal_null_rendering_rule_is_in_the_document():
    """`null` 必须渲染成字面量这条规则，必须写在文档里、不能只活在测试里。

    这条规则是 R4 的补全（三态里的 `null` 与「未评估」在 CSV 里都会是空格子，
    除非规定 `null` 写成字面量）。它此前唯一的"守卫"是本文件的 `_cell()`——
    那只是测试自己的渲染模型，改坏 `_cell` 会红纯属循环论证，
    删掉文档里这段话则上一版全绿（review 实测）。所以要正面断言文档里有它。
    """
    sec = _stop_candidate_section()
    assert "写成字面量" in sec and "`null`" in sec, (
        "该节没写「`null` 写成字面量 `null`」——少了它，"
        "「判不了」与「未评估」在 CSV 里不可区分，R4 的区分只剩纸面")
    assert "真正的空格" in sec, (
        "该节没写清「只有未评估才是真正的空格」这一半")

def _cell(row, col):
    """该列在 CSV 里那一格的取值。

    **键缺失 ⇒ 留空（None）；值是 JSON null ⇒ 字面量 `"null"`。** 这两者在 CSV 里
    必须长得不一样，否则 `stop_candidate` 的「判不了」与「未评估」不可区分——
    而契约明确要求区分。把 JSON null 直接当成空格，就是把这条契约在测试里废掉。
    """
    if col not in row:
        return None
    v = row[col]
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    return v

def test_documented_enums_cover_every_produced_value():
    """`core.py` 实跑产出的每个枚举值都必须在 enum-values 块里。

    枚举值此前只在一张散文表里，测试一个字都没查过——两个 runtime 于是各自
    往 stop_candidate 里写了非法值。这条断言只查 core.py 产出的三列
    （bucket / confidence / stop_candidate）：另三列（window_profile /
    action_type / service 的采集侧取值）由采集侧填，实现里没有可取的真值，
    **本断言守不到它们**，别把它读成"六列全守住了"。
    """
    enums = _documented_enums()
    for col in ("bucket", "confidence", "stop_candidate"):
        assert col in enums, f"enum-values 块缺 {col}"
    rows = _run_rows() + _managed_rows()
    for col in ("bucket", "confidence", "stop_candidate"):
        for r in rows:
            v = _cell(r, col)
            assert v in enums[col], (
                f"{r['rid']} 的 {col}={v!r} 不在 enum-values 的合法值 "
                f"{sorted(enums[col], key=str)} 里")

def test_empty_stop_candidate_is_report_layer_only():
    """「留空」这一态 `core.py` 永远产不出来，只能由报告层写出。

    契约把 `null`（查了判不了）与留空（按输入要求没查）定成两件事。
    如果 `core.py` 自己就能漏掉这个键，那两态在 CSV 里会因为同一个原因变空，
    区分就只是纸面上的。所以这里正面钉住：每一行都带这个键，
    而 `null` 必须渲染成字面量而不是空格。
    """
    enums = _documented_enums()
    assert None in enums["stop_candidate"], "枚举缺「留空」这一态"
    assert "null" in enums["stop_candidate"], "枚举缺 null 这一态"
    for r in _run_rows() + _managed_rows():
        assert _cell(r, "stop_candidate") is not None, (
            f"{r['rid']}: core.py 漏了 stop_candidate 键 —— 留空只能由报告层产生")

def test_every_produced_verdict_is_documented():
    """实跑产出的 verdict 必须都在 verdict-enum 块里。

    `verdict` 是 core.py 独占产出的列，却和 bucket / confidence 不在同一节，
    此前没有任何断言看过它。本 fixture 覆盖 downsize / insufficient-data /
    downsize-candidate 三个值；**十个值里另七个本断言覆盖不到**
    （spec-unknown / price-unknown 等要靠 sample-solve.md 那份 fixture，
    见 tests/test_sample_reproduces.py），别当成"十个全验过"。
    """
    documented = {v.strip() for v in _fenced("verdict-enum").replace("\n", "|").split("|")
                  if v.strip()}
    got = {r["verdict"] for r in _run_rows() + _managed_rows()}
    assert len(got) >= 3, f"fixture 只产出了 {got}，覆盖面不足以守住这条断言"
    assert got <= documented, f"未记入枚举的 verdict: {sorted(got - documented)}"

def test_window_profile_enum_has_the_full_window_value():
    """`full-window` 必须在枚举里：NAT / ALB 的闲置判据取的就是全窗口的 max。

    三档（biz/off/weekend）里任何一档都不能代表全窗口，缺这个值时两个 runtime
    各自挑了一档填进去，同一个闲置 NAT 在两份报告里 window_profile 不同。
    """
    got = _documented_enums()["window_profile"]
    need = {"biz-hours", "off-hours", "weekend", "full-window"}
    # 消息必须点名缺了哪个：上一版写 `assert need <= got, got`，失败时只打印
    # 现有集合，读的人得自己做差集才知道少了什么。
    assert need <= got, f"window_profile 枚举缺 {sorted(need - got)}（现有 {sorted(got, key=str)}）"
    assert None in got, "纯配置类判断要留空，枚举里必须有 (empty)"


RATIO_FORMULA = re.compile(r"比例[ \t]*[=＝]")


def test_savings_ratio_formula_exists_in_exactly_one_place():
    """节省比例的算式**只能有一份**，且必须逐口径各一条。

    此前有两份、各自欠定义：`SKILL.md` 写 `Σ按需理论月省 ÷ Σ按需理论月额`
    （分子没说哪条口径），`report-template.md` 写「所选口径的合计 ÷ 分母」
    （把选择权留给了 agent）。两个 agent 各挑一条口径，同一支机队的头条百分比
    就差三成——而百分比是报告里最显眼的数字。

    所以这里钉两件事：算式只出现在 savings-ratios 块里（`SKILL.md` 与其他
    reference 都不许再有一份），且四条口径**各有一条**、没有"所选口径"这种口子。
    """
    fence = _fenced("savings-ratios")
    # 块里为了对齐带了空格（`桶 B 比例`），比对前先去掉所有空白
    flat = re.sub(r"\s+", "", fence)
    for route in ("路线一", "路线二", "桶B", "采集侧"):
        assert f"{route}比例" in flat, f"savings-ratios 块里缺「{route}比例」那一行"
    assert "所选" not in fence, "算式里不得留「所选口径」这种由 agent 挑的口子"

    ref = ROOT / "references"
    hits = []
    for f in [ROOT / "SKILL.md"] + sorted(ref.glob("*.md")) + sorted(ref.glob("*.jq")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if RATIO_FORMULA.search(line):
                hits.append((f.name, i, line.strip()))
    outside = [h for h in hits if h[2] not in
               [l.strip() for l in fence.splitlines() if l.strip()]]
    assert not outside, (
        "节省比例的算式在 savings-ratios 块之外又出现了一份，"
        f"两份必然漂移：{outside}")
    assert len(hits) == 4, f"算式应当恰好四条（每条口径一条），实际 {len(hits)} 条：{hits}"


def _fill_table():
    """「采集侧自建行的字段填法」那张表 → [(资源类型, {列名: 单元格原文})]。

    表头的列名带反引号，正文的格子按 markdown 竖线分列。
    """
    doc = DOC.read_text()
    sec = doc.split("## 采集侧自建行的字段填法", 1)
    assert len(sec) == 2, "report-template.md 缺少「采集侧自建行的字段填法」一节"
    rows, header = [], None
    for line in sec[1].splitlines():
        if not line.startswith("|"):
            if header and rows:
                break            # 表结束
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.strip("`") for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue             # 分隔行
        assert len(cells) == len(header), (
            f"表格列数不齐：表头 {len(header)} 列，此行 {len(cells)} 列 —— {cells}")
        rows.append((cells[0], dict(zip(header, cells))))
    assert rows, "表格一行都没解析出来"
    return header, rows


def _cell_values(cell):
    """一格 → 它声明的取值列表。

    格式（文档里写明了）：`／` 分隔的候选，每个候选的**第一个反引号词**是取值，
    括号里是条件；不含反引号词的候选必须写「留空」。
    """
    out = []
    for alt in cell.split("／"):
        m = re.search(r"`([^`]+)`", alt)
        out.append(m.group(1) if m else ("留空" if "留空" in alt else alt.strip()))
    return out


def test_fill_table_cells_are_all_documented_enum_values():
    """**主交付物的机器守卫**：18 行 × 6 个枚举列，每一格都必须是合法值。

    这张表此前只是散文——把 NAT 闲置行的 confidence 改成 `high`、
    window_profile 改成 `off-hours`，上一版照样全绿（review 实测）。本仓库反复验证出
    「只有散文描述的判据全部出过问题」，所以把它变成受检产物。

    每格必须是三者之一：`留空`、该列 enum 块里的合法值、或字面量「core.py 产出」。
    **它抓不到「合法但矛盾」**（例如把某行 verdict 从 excluded 改成 downsize，
    两个都是合法 verdict）——那类要靠文档里的逐格理由，别把本断言读成"表全对了"。
    """
    header, rows = _fill_table()
    enums = dict(_documented_enums())
    enums["verdict"] = {v.strip() for v in
                        _fenced("verdict-enum").replace("\n", "|").split("|") if v.strip()}
    for col in TABLE_ENUM_COLS:
        assert col in header, f"表里没有 {col} 列（表头 {header}）"
    bad = []
    for name, row in rows:
        for col in TABLE_ENUM_COLS:
            for v in _cell_values(row[col]):
                if v == "留空" or v == CORE_FILLED or v in enums[col]:
                    continue
                bad.append(f"「{name}」的 {col} 格里的 {v!r} 不是合法值")
    assert not bad, ("填法表里有不在枚举里的取值：\n  " + "\n  ".join(bad))


# 填法表必须有的**每一行**，逐行一个键。**这份清单是穷举的，不是最小集**，
# 且**刻意手写、不从表里生成**——从被查的表里推出期望值就是循环论证。
#
# 为什么按行而不是按资源类型：上一版的键是资源"类型"（`NAT`、`ALB`），
# 于是同一类型的两行只要还剩一行就匹配得上，删掉「NAT 闲置」照样全绿（review 实测，
# 「NAT 活跃」里也含 "NAT"）。而对 NAT / ALB 来说那两行**就是闲置与活跃两个状态**，
# 三态判定正是本轮立起来的规矩之一（`RequestCount` 缺失而 `ActiveConnectionCount`
# 非零不得读成闲置）。删掉闲置那一行，「闲置 NAT 进桶 B」这条规则就无声消失。
REQUIRED_ROWS = (
    "EC2 running（判据行",
    "EC2 running 且命中闲置",
    "EC2 `state=stopped`",
    "EBS 卷 `gp2` 且可转 `gp3`",
    "EBS 卷 `state=available`",
    "EBS 卷挂在 `state=stopped` 实例上",
    "EBS 卷 其他",
    "快照",
    "NAT 闲置",
    "NAT 活跃",
    "ALB / NLB 闲置",
    "ALB / NLB 活跃",
    "EIP 未关联",
    "EKS 节点池（聚合行）",
    "EKS 节点（成员行）",
    "EKS 控制面",
    "桶 E pod request 调优",
    "RDS / ElastiCache / MSK（判据行",
)


def test_fill_table_covers_every_required_row():
    """删掉、改名、或悄悄多加表里任何**一行**都必须红。

    三级失效史，每一级都是靠变异上一级发现的、没有一级是读出来的：
    ① 这张表原本一个机器守卫都没有；
    ② 加了逐格枚举校验后，**删掉一整行仍然全绿**——剩下的格子全都合法；
    ③ 加了按"资源类型"的覆盖断言后，**删掉同类型两行中的一行仍然全绿**——
       另一行的名字里含同一个子串。

    所以这一版按行钉，并且**要求每个键恰好命中一行**：
    - 命中 0 行 ⇒ 该行被删了或被改名了；
    - 命中 2 行 ⇒ 这个键不具区分性，也就是 ③ 那个缺陷本身（键写松了立刻红，
      而不是悄悄放过一整行）。
    再加一条行数断言，挡住「删一行同时改另一行的名字来凑数」以及
    「新增一行而不写进本清单」。
    """
    _, rows = _fill_table()
    names = [n for n, _ in rows]
    bad = []
    for key in REQUIRED_ROWS:
        hits = [n for n in names if key in n]
        if len(hits) != 1:
            bad.append(f"键 {key!r} 命中 {len(hits)} 行"
                       + (f"（{hits}）—— 键不具区分性，同类型的另一行被删也测不出"
                          if hits else " —— 该行被删或被改名"))
    assert not bad, ("填法表的逐行覆盖断言失败：\n  " + "\n  ".join(bad)
                     + f"\n  现有 {len(rows)} 行")
    assert len(rows) == len(REQUIRED_ROWS), (
        f"表里有 {len(rows)} 行，清单里有 {len(REQUIRED_ROWS)} 个键。"
        "新增资源类型时必须同时写进 REQUIRED_ROWS——否则新行没有任何守卫；"
        f"现有行：{names}")


# 少数几行的**取值**本身就是本轮的裁定，改掉它们等于把规则删掉，
# 所以这几格单独钉住。**刻意只钉这几行**：把 18×10 全抄进测试就是把表复制一份，
# 那才是本仓库最怕的"同一真值两处存"。其余行靠逐格合法性 + 文档里的逐格理由。
#
# 选这四行的理由：NAT / ALB 的「闲置 vs 活跃」是本轮立起来的三态判定
# （`RequestCount` 缺失而 `ActiveConnectionCount` 非零**不是**闲置）。
# 闲置那一侧决定钱进桶 B、活跃那一侧决定不进，两者的 bucket / action_type
# 一旦被改成对方，报告会把活跃资源报成可删除——上一轮真实运行就出过这个错（$16.43）。
#
# `sample_points` 也钉进来：这四行的 `window_profile` 钉在 `full-window`，而
# `sample_points` 此前被定义成 `biz-hours` 档的点数 ⇒ 同一行的两个钉住事实用了
# 两个窗口，而这四行里两行的 action_type 是 `delete`。两列必须同档。
PINNED_CELLS = {
    "NAT 闲置":      {"bucket": "idle",     "action_type": "delete",
                     "window_profile": "full-window", "sample_points": "full-window"},
    "NAT 活跃":      {"bucket": "excluded", "action_type": "none",
                     "window_profile": "full-window", "sample_points": "full-window"},
    "ALB / NLB 闲置": {"bucket": "idle",     "action_type": "delete",
                     "window_profile": "full-window", "sample_points": "full-window"},
    "ALB / NLB 活跃": {"bucket": "excluded", "action_type": "none",
                     "window_profile": "full-window", "sample_points": "full-window"},
}


def test_fill_table_pins_the_idle_versus_active_rows():
    """闲置行与活跃行的取值必须逐格对上，不只是"这一行还在"。

    为什么光有覆盖断言不够（**实测**）：删掉「NAT 闲置」那一行、再伪造一行同名的
    （内容抄自「EKS 控制面」），行数仍是 18、键仍恰好命中一行、每一格也都是合法值
    ⇒ 覆盖断言与逐格合法性断言**双双全绿**，而「闲置 NAT 进桶 B、活跃 NAT 不进」
    这条规则已经没了。存在性守不住内容。

    这条只钉四行十二格，覆盖面有限，别读成"表的内容全验过了"。
    """
    _, rows = _fill_table()
    by_name = {n: r for n, r in rows}
    bad = []
    for key, want in PINNED_CELLS.items():
        hit = [n for n in by_name if key in n]
        if len(hit) != 1:
            bad.append(f"{key!r} 命中 {len(hit)} 行，先看 REQUIRED_ROWS 那条断言")
            continue
        row = by_name[hit[0]]
        for col, expect in want.items():
            got = _cell_values(row[col])
            if got != [expect]:
                bad.append(f"「{hit[0]}」的 {col} 应为 {expect!r}，实际 {got}")
    assert not bad, ("闲置/活跃行的取值被改了——三态判定就靠这几格：\n  "
                     + "\n  ".join(bad))


def test_fill_table_sample_points_share_the_window_with_window_profile():
    """同一行的 `sample_points` 与 `window_profile` 必须同档，逐行查。

    这条守的是「一行的两个钉住事实用了两个窗口」这种矛盾，而不是某个具体取值：
    `window_profile` 说这一行的证据取自哪一档，`sample_points` 说那一档取到几个点。
    NAT / ALB 四行钉在 `full-window`，而 `sample_points` 曾被定义成 `biz-hours` 档的
    点数——两种填法都能自证合法，而全窗口点数天然大于同一资源的 biz-hours 点数，
    拿它去比 `min_biz_hours_points` 是**偏松**的比较，偏偏这四行里两行的动作是删除。

    `PINNED_CELLS` 只钉住那四行的取值；这条覆盖**全部** 18 行的一致性，
    所以新增资源类型时不用回来改清单也守得住。
    """
    header, rows = _fill_table()
    for col in ("sample_points", "window_profile"):
        assert col in header, f"填法表缺 {col} 列（表头 {header}）"
        assert col in _documented_columns(), f"契约列清单缺 {col}"
    bad = [f"「{n}」sample_points={_cell_values(r['sample_points'])}"
           f" ≠ window_profile={_cell_values(r['window_profile'])}"
           for n, r in rows
           if _cell_values(r["sample_points"]) != _cell_values(r["window_profile"])]
    assert not bad, (
        "有行的 sample_points 与 window_profile 不同档——同一行的两个钉住事实"
        "就不能再互相印证，而全窗口档的行动作是 delete：\n  " + "\n  ".join(bad))


# ALB/NLB 闲置判据的**唯一真值源**是 `cli-recipes.md §2.6`（判定矩阵 + 可执行 jq
# 同屏）。这里不复制那条判据——复制一份就成了第四份。只查另两处是不是**指针形状**。
IDLE_METRIC_NAMES = ("RequestCount", "ActiveConnectionCount",
                     "ProcessedBytes", "ActiveFlowCount")


def _thresholds_idle_row(resource):
    """thresholds.md「闲置判据」表里以 `| <resource> |` 开头的那一行。"""
    sec = (ROOT / "references" / "thresholds.md").read_text().split("## 闲置判据", 1)
    assert len(sec) == 2, "thresholds.md 缺少「闲置判据」一节"
    hits = [l for l in sec[1].splitlines() if l.startswith(f"| {resource} |")]
    assert len(hits) == 1, (
        f"闲置判据表里以 `| {resource} |` 开头的行有 {len(hits)} 条，应当恰好 1 条")
    return hits[0]


def _report_template_bullet(lead):
    """report-template.md 里 `- **<lead>` 开头的那一整条 bullet（含缩进续行）。"""
    lines = DOC.read_text().splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith(f"- **{lead}")]
    assert len(starts) == 1, (
        f"report-template.md 里 `- **{lead}` 开头的 bullet 有 {len(starts)} 条，应当恰好 1 条")
    out = [lines[starts[0]]]
    for l in lines[starts[0] + 1:]:
        if not l.startswith("  ") or not l.strip():
            break
        out.append(l)
    return "\n".join(out)


def test_alb_idle_criterion_is_a_pointer_outside_cli_recipes():
    """ALB/NLB 闲置判据在 `thresholds.md` 与 `report-template.md` 里必须是**指针**。

    为什么需要这条：这条判据一度在三个文件各写一份、三份互不相同、三种风险
    （一份把序列缺失当"恒 0"⇒把活跃 LB 报成可删除；一份要求连接序列缺失⇒真闲置的
    LB 永远进不了桶 B；一份语义对但没实现）。八轮 review 没抓到，因为**没有任何测试
    读 `cli-recipes.md`**，而另两处各自看都合法。

    这条**不查判据内容**——查内容就等于把矩阵抄第四份。只查指针形状：
    指向 `cli-recipes`、且不含指标名 / 不含自己的 `bucket=idle` 成立条件。
    指针里一出现指标名，就是第二份判据的开头。
    """
    bad = []
    row = _thresholds_idle_row("ALB/NLB")
    if "cli-recipes" not in row:
        bad.append("thresholds.md 的 ALB/NLB 行没有指向 cli-recipes："
                   f"{row.strip()}")
    named = [m for m in IDLE_METRIC_NAMES if m in row]
    if named:
        bad.append(f"thresholds.md 的 ALB/NLB 行又写出了指标名 {named}——"
                   f"这一格是两列的「资源 | 条件」，装不下三态矩阵：{row.strip()}")
    # NAT 那行**必须**留着条件：它是单指标单状态，一格装得下，不是本条要拆的对象。
    nat = _thresholds_idle_row("NAT")
    if "ActiveConnectionCount" not in nat:
        bad.append("thresholds.md 的 NAT 行丢了它的条件——NAT 是单指标单状态，"
                   f"不该被一起改成指针：{nat.strip()}")
    # SKILL.md 是第五处。实测过：它regrow 出「`act` 序列不存在才进桶 B」那条退役条件，
    # 上一版的本断言照样全绿——因为本断言当时根本没读这个文件。
    skill = (ROOT / "SKILL.md").read_text()
    vpc = skill.split("### VPC（本版本仅闲置资源）", 1)
    if len(vpc) != 2:
        bad.append("SKILL.md 缺少「### VPC（本版本仅闲置资源）」一节")
    else:
        vpc = vpc[1].split("\n## ", 1)[0]
        alb = [l for l in vpc.splitlines() if "ALB/NLB" in l]
        if not alb:
            bad.append("SKILL.md 的 VPC 小节里没有 ALB/NLB 那条")
        if "cli-recipes.md §2.6" not in vpc:
            bad.append("SKILL.md 的 VPC 小节没把 ALB/NLB 判据交给 cli-recipes §2.6")
        if "本文不复述判据" not in vpc:
            bad.append("SKILL.md 的 VPC 小节没声明「本文不复述判据」——"
                       "少了这句话，下一个人会在这里再写一份条件")
        # 退役条件的两种写法：要求连接序列**不存在**才进桶 B。
        for phrase in ("序列不存在」才进桶 B", "序列不存在才进桶 B"):
            if phrase in vpc:
                bad.append(f"SKILL.md 的 VPC 小节又长出了退役的判据「{phrase}」——"
                           "「act 序列不存在」不是进桶 B 的条件，"
                           "两个指标都无活动才是（见 cli-recipes.md §2.6）")
    bullet = _report_template_bullet("空序列的 ALB 不等于可删除")
    if "bucket=idle" in bullet:
        bad.append("report-template.md「空序列的 ALB」那条 bullet 又写了 "
                   "bucket=idle 的成立条件；它只该留「零 HTTP 请求 ≠ 零连接」这条理由")
    if "cli-recipes" not in bullet:
        bad.append("report-template.md「空序列的 ALB」那条 bullet 没把判据交给 "
                   "cli-recipes §2.6")
    # metrics-catalog.md 是第四处（review 只点了三处）。它此前把
    # 「RequestCount 全窗口恒 0 **或序列不存在** ⇒ 闲置」写成表格行并标「已实测」,
    # 是所有版本里最危险的一句——照字面执行就是上一轮那个错。
    # 只查**表格行**：行文里引用这句错话并说明它错，是本轮刻意留的病历。
    for i, line in enumerate(
            (ROOT / "references" / "metrics-catalog.md").read_text().splitlines(), 1):
        # 筛选用的是已经声明好的 IDLE_METRIC_NAMES，不是只筛 RequestCount：
        # 上一版写死 `"RequestCount" not in line`，于是 NLB 那两行
        # （`ProcessedBytes` / `ActiveFlowCount`）regrow 出「全窗口为 0 ⇒ 闲置」
        # 照样全绿——而那正是第一次真实 NLB 运行会走的路径。
        named = [m for m in IDLE_METRIC_NAMES if m in line]
        if not line.startswith("|") or not named:
            continue
        # 单指标下「⇒ 闲置」的结论**只允许自我声明的例外**：NAT 那一行必须写出
        # 「单指标单状态」才有资格这么写。这样例外是显式的、有理由的，
        # 而不是靠测试里维护一份行清单（清单会漂）。
        if "⇒ 闲置" in line and "单指标单状态" not in line:
            bad.append(f"metrics-catalog.md:{i} 的表格行拿 {named} 直接下"
                       f"「⇒ 闲置」的结论，又没声明自己是单指标单状态——"
                       f"ALB/NLB 是两个指标的三态判定：{line.strip()}")
        # 只有真的谈到闲置的行才要求指针；纯单指标语义行（NLB 那张表）不要求，
        # 它们的表头已经写明「不是闲置判定」。
        if "闲置" in line and "cli-recipes" not in line:
            bad.append(f"metrics-catalog.md:{i} 提到 {named} 与闲置却没把判定"
                       f"交给 cli-recipes §2.6：{line.strip()}")
    assert not bad, ("ALB/NLB 闲置判据又长出了第二份：\n  " + "\n  ".join(bad))


def test_fill_table_covers_the_new_savings_column():
    """`other_save_mo` 必须在表里，且只有两行带值、其余留空。

    两条互补的理由，缺一不可：
    - `bucket=idle` 的行若也填它，同一笔钱会同时进桶 B 合计与采集侧合计。
    - `bucket=excluded` 的行若填它，**口径块的 allowlist
      （`over bucket == "downsize"`）会漏掉那笔钱，而 `cli-recipes.md §6 ③` 的
      denylist（`bucket != "idle"`）会算进去**——两种写法从此不等价，
      两次运行的头条数字不同。判据行那一侧的同一条不变式由
      `test_regression_fleet.py` 的 `test_excluded_rows_never_carry_savings`
      在真实机队上查。
    """
    header, rows = _fill_table()
    assert "other_save_mo" in header, f"填法表缺 other_save_mo 列（表头 {header}）"
    assert "other_save_mo" in _documented_columns(), "契约列清单缺 other_save_mo"
    filled = [n for n, r in rows if "留空" not in r["other_save_mo"]]
    assert len(filled) == 2, (
        f"应当恰好两行带 other_save_mo（gp2→gp3 与 EKS 节点池聚合行），实际 {filled}")
    for n, r in rows:
        bucket = _cell_values(r["bucket"])[0]
        if bucket in ("idle", "excluded"):
            assert "留空" in r["other_save_mo"], (
                f"「{n}」是 bucket={bucket} 却带了 other_save_mo —— "
                "idle 行的钱已经以全额 cur_cost_mo 记进桶 B 合计；"
                "excluded 行带钱会让口径块的 allowlist 与 §6 ③ 的 denylist 不再等价")


def test_totals_routes_fence_pins_all_four_routes():
    """四条口径必须在 totals-routes 块里，且带作用域。

    R5 的裁定（桶 B 合计取 `cur_cost_mo` 而不是 `nb_save_mo`）此前没有任何断言看过；
    路线一/二漏掉作用域是本仓库已经犯过两次的错（`cli-recipes.md §6 ③`）。
    """
    fence = _fenced("totals-routes")
    for need in ('路线一', '路线二', '桶 B 合计', '采集侧合计',
                 'Σ cur_cost_mo over bucket == "idle"',
                 'Σ other_save_mo over bucket == "downsize"'):
        assert need in fence, f"totals-routes 块里缺 {need!r}"
    # 两条降配路线都必须带作用域，否则读者会按全表求和
    for line in fence.splitlines():
        if line.startswith("路线"):
            assert "over bucket" in line, f"降配路线没写作用域：{line.strip()}"

    # 契约要四个头条数字，而 `cli-recipes.md §6` 只算得出三个（`core.py` 按设计
    # 不产出 `other_save_mo`，第四条只能在 findings.csv 上算）。§6 必须**写明**
    # 第四条在下游，否则照它执行的 agent 会交出三个数、而这里要求四条口径。
    # **必须锚在 §6 的那一段里**，不是"全文件出现过就算"：后者被文件任何角落的
    # 一次提及满足，而这条要保证的是**照着 §6 执行的人**能就地看到第四条在哪。
    step = _cli_recipes_step("⑤ 采集侧合计", "```")
    for need in ("other_save_mo", "findings.csv", "report-template.md"):
        assert need in step, (
            f"cli-recipes.md §6 ⑤ 那段里缺 {need!r} —— §6 只算得出三条口径而契约要四条，"
            f"缺的那条必须在 §6 就地说明它为什么只能在 findings.csv 上算、算式在哪；"
            f"当前那段是：{step[:160]!r}")


def _cli_recipes_step(marker, stop):
    """`cli-recipes.md` 里以 `# <marker>` 开头、到 `# <stop>` 之前的那一段命令。

    锚必须带注释正文，不能只写 `# ③` —— ①②③④ 在这个文件里到处都是
    （实测裸 `# ③` 命中 3 行）。
    """
    txt = (ROOT / "references" / "cli-recipes.md").read_text().splitlines()
    starts = [i for i, l in enumerate(txt) if l.startswith(f"# {marker}")]
    assert len(starts) == 1, (
        f"cli-recipes.md 里以 `# {marker}` 开头的行有 {len(starts)} 条，应当恰好 1 条"
        "（这一段被改名或被删了，先看它还在不在）")
    out = []
    for l in txt[starts[0]:]:
        # stop 是 "```" 时按围栏结束收尾，否则按 `# <marker>` 注释行收尾。
        # 这两种边界不能混：早先这里只认 `# {stop}`，而调用方传的是 "```"，
        # 于是找一行以 "# ```" 开头 —— 永不存在 ⇒ 一直抽到文件末尾，
        # 392 行当成 5 行用。当时之所以没出错，只是因为要找的两个标识符
        # 恰好没在那 392 行里别处出现过，即「精确纯属偶然」。
        if out and (l.strip() == stop if stop == "```" else l.startswith(f"# {stop}")):
            break
        out.append(l)
    # 抽取器必须自证边界：一段自检步骤不该有几十行。上界给得宽，
    # 只为拦住「stop 从没命中、把后半个文件都吞进来」这一类。
    assert len(out) <= 40, (
        f"从 `# {marker}` 抽出了 {len(out)} 行，超出一段自检步骤的合理长度——"
        f"stop 标记 {stop!r} 很可能从未命中，抽取范围吞掉了后面的内容")
    return "\n".join(out)


def test_cli_recipes_denylist_carries_the_idle_exclusion():
    """`§6 ③` 的两条降配路线必须**在 denylist 上**求和，与 allowlist 侧对称。

    上一条断言钉的是 allowlist（口径块里每条 `路线` 都带 `over bucket`）。
    denylist 那一半此前**一个断言都没有**——`cli-recipes.md` 根本没有测试读过。
    删掉 `§6 ③` 的 `select(.bucket!="idle")`，全部断言照样全绿，而那正是本分支
    已经修过一次的缺陷：实测同一支机队路线一被抬高 65%（aggressive）到
    80%（conservative），因为一台闲置资源的 `nb_save_mo` 与它整台的
    `cur_cost_mo` 被同时计入。等价性是两边的，守卫不能只守一边。

    这里**不复制口径算式**（算式的唯一真值源是 `report-template.md` 的
    totals-routes 块），只查两件事：过滤器还在，且两条路线都从过滤后的集合取数。
    """
    step = _cli_recipes_step("③ 两条降配路线的合计", "④ 桶 B 合计")
    # 只看命令，注释要剥掉：那段注释里也写着「路线一/二」，不剥的话路线计数是 3
    # 而不是 2，断言会因为一个跟被守行为无关的原因失败（实测踩到）。
    cmd = "\n".join(l for l in step.splitlines() if not l.lstrip().startswith("#"))
    flat = re.sub(r"\s+", "", cmd)
    bad = []
    if '.bucket!="idle"' not in flat:
        bad.append("§6 ③ 少了 `select(.bucket!=\"idle\")` —— 闲置行的 nb_save_mo "
                   "会和它整台的 cur_cost_mo 同时进合计，同一笔钱算两遍")
    # 两条路线各自的求和表达式：从本路线名到下一路线名（或段尾）之间那一截。
    marks = [m.start() for m in re.finditer(r"路线[一二]", flat)]
    assert len(marks) == 2, f"§6 ③ 的命令里应当恰好两条路线，实际 {len(marks)} 条：{cmd}"
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(flat)
        expr, name = flat[start:end], flat[start:start + 3]
        if "$D[]" not in expr:
            bad.append(f"{name} 没有从过滤后的 $D 取数：{expr[:80]}")
        if "[.[]|" in expr:
            bad.append(f"{name} 直接对全表 `.[]` 求和，绕过了 idle 排除：{expr[:80]}")
    assert not bad, ("§6 ③ 的 denylist 被削弱了——它与口径块的 allowlist "
                     "必须等价，否则同一份数据出两个头条数字：\n  " + "\n  ".join(bad))


# ---- §2.6 的判据本体（矩阵 + jq）本身也要被守 ----------------------------
# 此前**没有任何测试读 §2.6 的 jq**（`grep -rn "vpc-idle\|quiet(" tests/` 返回空）。
# 于是五种改动都能让 83/83 全绿，其中一种是「NAT 序列不存在 ⇒ 可删除」——
# 正是本分支为之立项的那个 $16.43 级错误。本分支自己的诊断是「相邻不等于守卫」，
# 而上一轮把三个指针守住了、把承载全部规则的那份**副本**留在没人看的地方。
#
# 这里用**行为**而不是形状来守：把 §2.6 的 heredoc 原样抽出来，喂合成 agg 跑真 jq。
# 形状断言能在语义被改坏时照样通过（删掉覆盖度比较、或把 null 判断挪到 quiet 之后，
# 文本里该出现的词都还在）；行为断言不会。
# `jq` 是本 skill 的硬性前置（preflight 缺它即 FAIL），所以缺失时**报错而不是跳过**
# ——跳过正是守卫悄悄停止守卫的方式，本分支反复吃过这个教训。

def _vpc_idle_jq():
    """把 §2.6 的 `vpc-idle.jq` heredoc 原样抽出来。"""
    txt = (ROOT / "references" / "cli-recipes.md").read_text()
    m = re.search(r"cat > \$M/vpc-idle\.jq <<'JQ'\n(.*?)\nJQ\n", txt, re.S)
    assert m, ("cli-recipes.md 里找不到 `cat > $M/vpc-idle.jq <<'JQ'` heredoc —— "
               "§2.6 的判据实现被改名或删了，先确认它还在")
    return m.group(1)


def _agg_rows(rid, metric, stat, n, mx):
    """按 agg.jq 的输出形状造行：三档 + 一个 full-window 档。

    **full-window 那一行不是装饰。** agg.jq 现在真的输出它（供否决项的 p95 与
    下限型判据的 min 用），而 §2.6 的 `series()` 是把点数**相加**的 ——
    忘了排除 full-window 就会把 n 算两遍（实测 465 → 930），覆盖不足的序列
    看起来满覆盖 ⇒ `quiet()` 放行 ⇒ **活跃 LB 被报成可删除**。
    fixture 必须带上它，否则那个排除条件被删掉时全套断言照样绿。
    """
    if n is None:
        return []
    share = [("biz-hours", 242), ("off-hours", 286), ("weekend", 192)]
    total = sum(c for _, c in share)
    out, left = [], n
    for i, (band, cap) in enumerate(share):
        k = left if i == len(share) - 1 else round(n * cap / total)
        left -= k
        out.append({"rid": f"{rid}@{metric}", "itype": "t", "stat": stat,
                    "bucket": band, "n": k, "mean": 0, "p95": 0,
                    "max": (mx if i == 0 else 0), "min": 0})
    out.append({"rid": f"{rid}@{metric}", "itype": "t", "stat": stat,
                "bucket": "full-window", "n": n, "mean": 0, "p95": 0,
                "max": (mx if mx is not None else 0), "min": 0})
    return out


def _run_vpc_idle(kind, inventory, agg, win=720):
    """原样跑 §2.6 的 jq，返回逐资源的 state 列表。"""
    prog = _vpc_idle_jq()
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "p.jq").write_text(prog)
        (d / "agg.json").write_text(json.dumps(agg))
        (d / "inv.json").write_text(json.dumps(inventory))
        r = subprocess.run(["jq", "-c", "--slurpfile", "agg", str(d / "agg.json"),
                            "--argjson", "win", str(win), "--arg", "kind", kind,
                            "-f", str(d / "p.jq"), str(d / "inv.json")],
                           capture_output=True, text=True)
    assert r.returncode == 0, f"§2.6 的 jq 跑不起来（kind={kind}）：{r.stderr}"
    return [row["state"] for row in json.loads(r.stdout)]


def _elb_state(req_n, req_max, act_n, act_max, stat="Sum", win=720):
    inv = [{"id": "D", "name": "lb", "type": "application"}]
    agg = (_agg_rows("D", "RequestCount", stat, req_n, req_max)
           + _agg_rows("D", "ActiveConnectionCount", stat, act_n, act_max))
    return _run_vpc_idle("elb", inv, agg, win)[0]


def _nat_state(n, mx, stat="Maximum", win=720):
    return _run_vpc_idle("nat", [{"id": "D", "vpc": "v"}],
                         _agg_rows("D", "ActiveConnectionCount", stat, n, mx), win)[0]


def test_vpc_idle_jq_honours_the_rulings_it_is_the_only_copy_of():
    """§2.6 的 jq 必须在**行为上**守住本轮的四条裁定。

    每条都对应一个已验证可以静默通过全套断言的改动：

    1. `无活动 × 有活动` ⇒ 候选而不是桶 B（零 HTTP 请求 ≠ 零连接，实测 LB ②）。
    2. 覆盖度门槛真的比较点数：n = `$win` ⇒ idle，n = `$win - 1` ⇒ 候选。
       删掉 `quiet()` 里的 `.n >= $win` 会让一台 3 小时的 LB 被判可删除。
    3. **NAT 的序列不存在 ⇒ `no-data`，不是 `idle`。** NAT 是单指标单状态，
       所以必须先判 null 再套 `quiet()`（`quiet()` 对 null 返回真）。
       把这一步删掉就是「指标从未发布的 NAT 网关 ⇒ 可删除」。
    4. 两条路径都把 stat 钉死（ELB=Sum / NAT=Maximum）：采成别的 stat ⇒ `no-data`，
       而不是拿错 stat 静默算出结论。
    """
    bad = []

    def chk(what, got, want):
        if got != want:
            bad.append(f"{what}：得到 {got!r}，应为 {want!r}")

    # ① 争议格与它的两个邻居
    chk("ELB 无活动×无活动（req 全窗口 0 + act 缺失）", _elb_state(720, 0, None, None), "idle")
    chk("ELB 无活动×有活动（req 全窗口 0 + act max>0）",
        _elb_state(720, 0, 720, 84), "candidate-manual")
    chk("ELB 缺失×有活动（实测 LB ②）", _elb_state(None, None, 720, 84), "candidate-manual")
    # 本轮把「两条序列都在且都全窗口 0」裁成 idle（旧写法要求 act 缺席才敢判）。
    # 这一格恰恰是行为守卫原先唯一没跑到的：恢复退役的 `.act == null` 写法
    # 曾让全部断言保持绿。争议格不被覆盖等于那条裁定没有守卫。
    # n=0 观测：ALB 对零连接的小时不发布点，所以这一格在当前 ALB 代次上属外推，
    # 见 §2.6 的标注——但正因为它是外推，改动它更不该静默通过。
    chk("ELB 无活动×无活动（两条都在且都全 0，本轮裁定的争议格）",
        _elb_state(720, 0, 720, 0), "idle")
    chk("ELB 有活动×任意 ⇒ 活跃", _elb_state(720, 10397, 720, 1035), "active")
    # ② 覆盖度门槛的边界：差一个点就不算证据
    chk("ELB 覆盖不足（n = win-1，全 0）", _elb_state(719, 0, None, None), "candidate-manual")
    chk("ELB 刚好覆盖（n = win，全 0）", _elb_state(720, 0, None, None), "idle")
    # ③ 两条序列都不存在 ⇒ no-data，**不进桶 B**
    chk("ELB 两条序列都不存在", _elb_state(None, None, None, None), "no-data")
    # ④ NAT：序列不存在不是闲置；门槛同样咬
    chk("NAT 序列不存在", _nat_state(None, None), "no-data")
    chk("NAT 全窗口恒 0", _nat_state(720, 0), "idle")
    chk("NAT 覆盖不足（n = win-1）", _nat_state(719, 0), "candidate-manual")
    chk("NAT 有连接", _nat_state(720, 541), "active")
    # ⑤ stat 钉死：采错 stat 一律 no-data（fail closed），不是拿错 stat 出结论
    chk("ELB 采成 Average", _elb_state(720, 0, None, None, stat="Average"), "no-data")
    chk("NAT 采成 Sum", _nat_state(720, 0, stat="Sum"), "no-data")

    assert not bad, ("§2.6 的 jq 行为变了——它是这条判据的唯一真值源，"
                     "改它就是改判据：\n  " + "\n  ".join(bad))


def test_vpc_idle_matrix_awards_bucket_b_to_exactly_one_cell():
    """§2.6 的 3×3 矩阵只许有**一格**判桶 B，且必须把「两条都不存在」摘出去。

    这条守文档那一侧（上一条守实现那一侧）。**不逐格复制矩阵**——理由与填法表只钉
    四行相同：抄一份就是"同一真值两处存"。只钉那个唯一的裁定：
    桶 B 恰好一格，且 `无活动 × 无活动` 那格带 ※ 例外说明「两条都不存在不进桶 B」。

    把任何一格改成桶 B（实测：`无活动 × 有活动` 改成桶 B，其余 83 条断言全绿）
    都会在这里红。
    """
    txt = (ROOT / "references" / "cli-recipes.md").read_text()
    sec = txt.split("#### ALB / NLB 的闲置判定是三态", 1)
    assert len(sec) == 2, "cli-recipes.md 缺少 §2.6 的三态小节"
    # 本节有两张表都以这三个词起行：单指标状态定义表（行头 + 定义，2 格）
    # 与 3×3 组合矩阵（行头 + 三格，4 格）。按格数分开，别按词分。
    heads = ("| **无活动**", "| **覆盖不足**", "| **有活动**")
    parsed = [[x.strip() for x in l.strip().strip("|").split("|")]
              for l in sec[1].splitlines() if l.startswith(heads)]
    cells = [c for c in parsed if len(c) == 4]
    defs = {c[0]: c[1] for c in parsed if len(c) == 2}
    assert len(cells) == 3, (
        f"三态矩阵应当恰好 3 个数据行（无活动/覆盖不足/有活动），实际 {len(cells)}："
        f"{[c[0] for c in cells]}")
    # 单指标状态表里「覆盖不足」的定义必须真的带点数比较 —— 那是矩阵这一侧的门槛。
    assert "覆盖不足" in " ".join(defs), f"单指标状态表缺「覆盖不足」那一态：{list(defs)}"
    cov = next(v for k, v in defs.items() if "覆盖不足" in k)
    assert "$win" in cov and "<" in cov, (
        f"「覆盖不足」的定义里没有对 `$win` 的点数比较：{cov!r} —— "
        "门槛从矩阵里消失了，jq 那一侧就没有对照物")
    # 「判桶 B」不是「提到桶 B」——「活跃，不进桶 B」也含这两个字。
    def awards_b(cell):
        return "桶 B" in cell and "不进桶 B" not in cell
    b = [(cells[i][0], j) for i in range(3) for j in (1, 2, 3) if awards_b(cells[i][j])]
    assert len(b) == 1, (
        f"矩阵里判桶 B 的格子应当恰好 1 个（`无活动 × 无活动`），实际 {len(b)} 个：{b}。"
        "多一格就是把一类活跃/证据不足的资源报成可删除")
    assert b[0][0].startswith("| **无活动**".lstrip("| ")) or "无活动" in b[0][0], (
        f"判桶 B 的那一行不是「无活动」，而是 {b[0][0]!r}")
    assert b[0][1] == 1, (
        f"判桶 B 的那一格不在「无活动」列（列号 {b[0][1]}）—— "
        "只有两个指标都无活动才进桶 B")
    assert "※" in cells[0][1], (
        "`无活动 × 无活动` 那格没有 ※ 例外标记 —— "
        "「两条序列都不存在」也落这一格，但它是 no-data、**不进桶 B**")
    tail = sec[1].split("\n\n**为什么", 1)[0]
    assert "都不存在" in tail and "不进桶 B" in tail, (
        "矩阵下方缺「两条序列都不存在 ⇒ 不进桶 B」那条例外说明")


if __name__ == "__main__":
    # 与其余七个文件同一形状：逐个 try/except + 计数器。原来第一个失败就
    # sys.exit(1)，退出码对但后面的失败看不见（Minor 5 的形状）。
    tests = [test_every_output_key_is_documented,
             test_no_documented_column_is_fabricated,
             test_derived_columns_match_the_document,
             test_stop_candidate_four_states_are_each_documented,
             test_stop_candidate_column_survives_allow_stop_off,
             test_literal_null_rendering_rule_is_in_the_document,
             test_documented_enums_cover_every_produced_value,
             test_empty_stop_candidate_is_report_layer_only,
             test_every_produced_verdict_is_documented,
             test_window_profile_enum_has_the_full_window_value,
             test_savings_ratio_formula_exists_in_exactly_one_place,
             test_fill_table_cells_are_all_documented_enum_values,
             test_fill_table_covers_every_required_row,
             test_fill_table_pins_the_idle_versus_active_rows,
             test_fill_table_sample_points_share_the_window_with_window_profile,
             test_alb_idle_criterion_is_a_pointer_outside_cli_recipes,
             test_fill_table_covers_the_new_savings_column,
             test_totals_routes_fence_pins_all_four_routes,
             test_cli_recipes_denylist_carries_the_idle_exclusion,
             test_vpc_idle_jq_honours_the_rulings_it_is_the_only_copy_of,
             test_vpc_idle_matrix_awards_bucket_b_to_exactly_one_cell]
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
