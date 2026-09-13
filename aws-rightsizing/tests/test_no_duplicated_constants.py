import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).parent.parent
REF = ROOT / "references"

# 守护清单**从 thresholds.json 生成**，不得手写。
# 手写清单本身就是这条 lint 要防的那种重复真值：它在本次修复前退化成
# ["168", "0.70"] 两条，而这两个数字在散文里一处都不出现——18 个阈值里
# 守了 0 个，测试却常绿。清单必须随真值源一起变。
#
# 两道断言，分工不同（单靠任何一道都不够）：
#   ① 键名 + 该键的值同行  —— 精确抓「表格/行文里把键和值一起写出来」这种复述。
#      不产生假阳性：只有提到键名才检查，"5 分钟" 之类的 5 不会被误判。
#   ② 可辨识的值单独出现  —— 抓不带键名的复述（如 `DBLoad p95 < 0.5 × vCPU`）。
#      只守「可辨识」的值：带小数点或 3 位以上数字。裸的 1/2/3/5/8 在散文里
#      合法出现的次数远多于复述（"5 分钟"、"5 MB"、"2 x"、"3 个必填项"），
#      守它们会把整份文档淹在假阳性里，最终结果就是被注释掉——那正是 ①②
#      之前那份手写清单的下场。实测依据：把四个 .jq 对全部阈值取值（含小整数）
#      穷举一遍，17 处命中里只有 1 处是真复述，其余全是撞值——`UTC+8`、
#      正则里的 `[0-9]{2}`、`agg.jq` 的 `$h < 20`（钟点 20:00，与
#      `stop_candidate_peak_cpu_max` 撞值）、`×60` 秒、broker ID `1`、
#      `m1+m2` 的 `2`、Label 的三段。谁要收紧 ② 到整数，先看这份清单。
#   ②' 再从 ② 里剔掉 baseline-pct.json 也用的值：T 系列基线 0.20 与
#      burstable_baseline_headroom 0.20 数值相同、含义无关，
#      instance-specs.md 的基线表写 0.2 是本义，不是复述。


def _variants(v):
    """一个阈值在散文里可能被写成的形式。0.2 也会写成 0.20，须都守。"""
    if isinstance(v, float):
        return {repr(v), f"{v:g}", f"{v:.2f}"}
    return {str(v)}


def _threshold_values():
    """{键名: {该键值的所有写法}}，两个 profile 合并。"""
    profiles = json.loads((REF / "thresholds.json").read_text())["profiles"]
    out = {}
    for prof in profiles.values():
        for k, v in prof.items():
            out.setdefault(k, set()).update(_variants(v))
    return out


def _baseline_values():
    return {s for v in json.loads((REF / "baseline-pct.json").read_text()).values()
            for s in _variants(v)}


def _distinctive():
    """可辨识的阈值写法：带小数点或 >= 3 位有效数字，且不与 T 系列基线撞值。"""
    base = _baseline_values()
    out = {}
    for k, vs in _threshold_values().items():
        for s in vs:
            if s in base:
                continue
            if "." in s or len(s.lstrip("0.")) >= 3:
                out.setdefault(s, set()).add(k)
    return out


# 允许的例外：实测证据里引用数值是有价值的，但必须带「实测」二字同行。
EVIDENCE_MARK = re.compile(r"实测|verified|证据")


def _prose_files():
    """散文 + 采集侧的 .jq。

    `.jq` 必须在扫描范围内：它们的注释同样会复述阈值，而 jq 代码里写死阈值
    和 Python 里写死一样是缺陷。`.jq` 没有 ``` 围栏，所以两道断言都会扫到
    它的每一行，包括注释与代码。

    **扩大文件集与「散文改成写键名」两步是共同必要的，缺一不可。** 实测：
    `agg.jq` 原写「最小值 < 实例内存 15%」，只扩大文件集**抓不到它**——
    该行没写键名，①（键名+值同行）看不见；`15` 是小整数，②（可辨识值）
    按设计不守。是把数字改成 `rds_freeable_mem_floor_pct` 才把这行拉进 ① 的
    覆盖范围，而扩大文件集才让 ① 去看这个文件。
    后来加文件类型的人别以为扩大文件集本身就够。
    """
    return ([ROOT / "SKILL.md"] + sorted(REF.glob("*.md"))
            + sorted(REF.glob("*.jq")))


def _num_re(s):
    return re.compile(rf"(?<![\d.]){re.escape(s)}(?![\d.])")


def _lines(prose_only=False):
    """带 ``` 围栏状态的行迭代。

    prose_only=True 时跳过代码块内部：围栏里是命令与**实测输出**，里面的数字是
    产物而不是复述（实测的 `req_cpu: 0.5` 与 `rds_dbload_ratio` 撞值属巧合）。
    「键名 + 值同行」那道断言仍然扫围栏内部——命令里写死阈值必须抓到。
    """
    for f in _prose_files():
        in_code = False
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if prose_only and in_code:
                continue
            if EVIDENCE_MARK.search(line):
                continue
            yield f.name, i, line


def test_threshold_key_and_value_not_restated_together():
    """散文提到阈值键名时，不得同行写出它的值——那就是第二个真值源。"""
    vals = _threshold_values()
    bad = []
    for name, i, line in _lines():
        for k, vs in vals.items():
            if k not in line:
                continue
            for s in vs:
                if _num_re(s).search(line):
                    bad.append(f"{name}:{i} 同行复述了 {k} 的值 {s}: {line.strip()[:70]}")
    assert not bad, ("散文把 thresholds.json 的键与值一起写出来了，"
                     "改成只引用键名：\n" + "\n".join(bad))


def test_distinctive_threshold_values_not_restated_in_prose():
    """可辨识的阈值数值不得出现在散文里，即便没写键名。"""
    bad = []
    for s, keys in _distinctive().items():
        rx = _num_re(s)
        for name, i, line in _lines(prose_only=True):
            if rx.search(line):
                bad.append(f"{name}:{i} 复述了 {sorted(keys)} 的值 {s}: {line.strip()[:70]}")
    assert not bad, "散文复述了 thresholds.json 的数值：\n" + "\n".join(bad)


def test_thresholds_md_points_at_json():
    txt = (REF / "thresholds.md").read_text()
    assert "thresholds.json" in txt, "thresholds.md 必须指向 thresholds.json 作为真值源"


def test_code_fences_are_balanced():
    """每份散文文件的 ``` 围栏必须配对。

    `_lines(prose_only=True)` 靠围栏奇偶性判断「在不在代码块里」。少一个收尾围栏，
    它之后的**所有代码块都会被当成散文**——本文件的两条断言于是开始报假阳性
    （实测：漏一个围栏后，`§4` 里一份 EKS 预订率实测输出里的 `req_cpu: 0.5`
    被当成复述了 `rds_dbload_ratio`）。反方向更糟：多一个围栏会让真正的散文
    被当成代码块**跳过扫描**，这道 lint 就静默失效了，而它是唯一守着
    「thresholds.json 是唯一真值源」的东西。
    """
    bad = []
    for f in _prose_files():
        n = sum(1 for line in f.read_text().splitlines()
                if line.lstrip().startswith("```"))
        if n % 2:
            bad.append(f"{f.name}: {n} 个围栏，奇数 ⇒ 有一处没配对")
    assert not bad, ("代码围栏不配对，prose_only 的扫描范围会整段错位：\n"
                     + "\n".join(bad))


def test_guard_list_is_generated_and_non_empty():
    """守护清单必须真的守到东西。空清单 = 常绿的假安全，是本 lint 的历史故障模式。"""
    assert _threshold_values(), "从 thresholds.json 生成的键值表为空"
    assert _distinctive(), "可辨识值清单为空——阈值全被 baseline 撞值剔掉了？"


if __name__ == "__main__":
    # 退出码必须随失败非零：SKILL.md 的自检是 `python3 "$t" || exit 1`，
    # 打印 ❌ 后仍 exit 0 会让唯一守护「thresholds.json 是唯一真值源」的
    # 断言完全不设防——门禁看不到它失败。
    tests = [test_threshold_key_and_value_not_restated_together,
             test_distinctive_threshold_values_not_restated_in_prose,
             test_thresholds_md_points_at_json,
             test_code_fences_are_balanced,
             test_guard_list_is_generated_and_non_empty]
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


def test_pi_unsupported_list_lives_in_exactly_one_file():
    """PI 不支持的实例类只能来自 rds-pi-unsupported.json。

    写死在 core.py 里等于第二个真值源：AWS 扩了 PI 的支持范围后，
    报告仍会向客户断言旧列表，并继续把本可选的更便宜机型排除在外。
    """
    data = json.loads((REF / "rds-pi-unsupported.json").read_text(encoding="utf-8"))
    classes = data["classes"]
    assert classes == sorted(classes), "列表须排序，便于 diff"
    assert len(classes) == len(set(classes)), "列表有重复项"
    assert data["_source"].startswith("https://"), "须留来源 URL"
    for k in ("_recheck", "_why", "_scope"):
        assert data[k].strip(), f"{k} 不得为空——这张表是人工维护的，须写清怎么复查"

    src = (REF / "core.py").read_text(encoding="utf-8")
    for cls in classes:
        assert cls not in src, (
            f"{cls} 硬编码进了 core.py；唯一真值源是 rds-pi-unsupported.json，"
            f"读它用 load_pi_unsupported()")


def test_pi_unsupported_list_is_not_restated_in_prose():
    """散文里可以解释这条规则，但不得把类名清单再抄一份。"""
    bad = []
    data = json.loads((REF / "rds-pi-unsupported.json").read_text(encoding="utf-8"))
    for name, i, line in _lines(prose_only=True):
        hits = [c for c in data["classes"] if c in line]
        if len(hits) >= 3:
            bad.append(f"{name}:{i} 复述了 PI 不支持清单 {hits}: {line.strip()[:70]}")
    assert not bad, "散文复述了 rds-pi-unsupported.json 的清单：\n" + "\n".join(bad)
