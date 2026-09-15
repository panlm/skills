"""`docs/method-explained.html` 是面向客户的判据说明，会随判据漂移。

这份文档**刻意复述阈值**（它的全部价值就是把公式和数值讲给客户看），所以它不能
走 `test_no_duplicated_constants.py` 那条「散文不得复述常量」的路。取而代之：
把它显示的数值**钉到 `thresholds.json`**，以及把服务章节钉到 `core.py` 实际
判的服务上。判据一改而文档没跟着改 ⇒ 门禁失败。

两处都要钉，缺一不可：
  ① 页面上那张两档预设表（客户读的数字）
  ② 页面里那段 JS 的 `PROFILES` 字面量（交互计算器算的数字）
只钉 ① 的话，计算器会在阈值改动后继续用旧值算给客户看 —— 那比表格写错更糟，
因为它是"客户自己动手验算"的地方。
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "method-explained.html"
REF = ROOT / "references"
sys.path.insert(0, str(REF))
import core  # noqa: E402

HTML = DOC.read_text(encoding="utf-8")
PROFILES = json.loads((REF / "thresholds.json").read_text())["profiles"]
CONS, AGGR = PROFILES["conservative"], PROFILES["aggressive"]

# 表格标签 -> thresholds.json 的键
TABLE_KEYS = {
    "CPU 目标（持续项）": "target_cpu_p95",
    "CPU 上限（峰值项）": "ceiling_cpu_max",
    "内存目标（持续项）": "target_mem_p95",
    "内存上限（峰值项）": "ceiling_mem_max",
    "单次降幅上限": "max_reduction_ratio",
    "MSK CPU 目标": "msk_target_cpu_p95",
    "采样点分档线": "min_biz_hours_points",
}
# JS PROFILES 的字段 -> thresholds.json 的键
JS_KEYS = {"ct": "target_cpu_p95", "cc": "ceiling_cpu_max",
           "mt": "target_mem_p95", "mc": "ceiling_mem_max",
           "ratio": "max_reduction_ratio"}
CELL_RE = re.compile(r'<td[^>]*>\s*([\d.]+)')


def _row(label):
    """取该标签所在 <tr> 的前两个数值单元格（保守档、激进档）。"""
    m = re.search(rf"<tr>\s*<td[^>]*>{re.escape(label)}</td>(.*?)</tr>",
                  HTML, re.S)
    assert m, f"文档里找不到预设表的「{label}」这一行"
    vals = CELL_RE.findall(m.group(1))
    assert len(vals) >= 2, f"「{label}」这一行取不到两个数值单元格: {vals}"
    return float(vals[0]), float(vals[1])


def test_threshold_table_matches_thresholds_json():
    bad = []
    for label, key in TABLE_KEYS.items():
        got_c, got_a = _row(label)
        if got_c != float(CONS[key]) or got_a != float(AGGR[key]):
            bad.append(f"{label}: 文档 {got_c}/{got_a}，"
                       f"thresholds.json {CONS[key]}/{AGGR[key]}")
    assert not bad, ("面向客户的说明与 thresholds.json 不一致（判据改了、"
                     "文档没跟）：\n  " + "\n  ".join(bad))


def test_calculator_profiles_match_thresholds_json():
    m = re.search(r"const PROFILES = \{(.+?)\};", HTML, re.S)
    assert m, "文档里找不到 JS 的 PROFILES 字面量"
    block = m.group(1)
    bad = []
    for prof_js, table in (("c", CONS), ("a", AGGR)):
        pm = re.search(rf"{prof_js}:\s*\{{(.+?)\}}", block, re.S)
        assert pm, f"PROFILES 里找不到 `{prof_js}`"
        fields = dict(re.findall(r"(\w+)\s*:\s*([\d.]+)", pm.group(1)))
        for js_key, key in JS_KEYS.items():
            assert js_key in fields, f"PROFILES.{prof_js} 缺字段 {js_key}"
            if float(fields[js_key]) != float(table[key]):
                bad.append(f"PROFILES.{prof_js}.{js_key} = {fields[js_key]}，"
                           f"thresholds.json {key} = {table[key]}")
    assert not bad, ("交互计算器用的是过期阈值（客户会拿它验算）：\n  "
                     + "\n  ".join(bad))


def test_every_judged_service_has_a_chapter():
    """`core.py` 判哪些服务，文档就得有对应章节。"""
    ids = set(re.findall(r'<h2 id="([^"]+)"', HTML))
    want = {"ec2": "ec2", "rds": "rds", "elasticache": "redis", "msk": "msk"}
    missing = [f"{svc} ⇒ 期望章节 id `{cid}`"
               for svc, cid in want.items()
               if (svc == "ec2" or svc in core.MANAGED_EVALUATORS)
               and cid not in ids]
    assert not missing, ("新增了判据服务但文档没有对应章节：\n  "
                         + "\n  ".join(missing))
    assert core.MANAGED_EVALUATORS.keys() <= set(want), (
        f"core.py 新增了托管服务 {set(core.MANAGED_EVALUATORS) - set(want)}，"
        f"本测试的章节映射与文档都要补")


def test_toc_links_resolve():
    ids = set(re.findall(r'<h2 id="([^"]+)"', HTML))
    links = set(re.findall(r'<a href="#([^"]+)"', HTML))
    assert links <= ids, f"目录里有悬空链接: {sorted(links - ids)}"
    assert ids <= links, f"有章节没进目录: {sorted(ids - links)}"


def test_no_real_identifiers():
    """本仓库公开：文档里不得留真实账号 ID 或客户资源名。

    `test_no_private_data.py` 扫的是形态（账号 ID / 路径 / 实例 ID / 密钥），
    这里补的是**这份文档特有**的历史残留：它最初是从一次真实交付改写来的。
    """
    banned = re.findall(
        r"(?i)(wukong|3podelta|bossfoundation|deltaglobal|otamysql|ninjaeks|"
        r"ranchereks|raven|asiainfo|hkwk|itsmalert|hk-staging|hk-situat|"
        r"aws-stg-|aws-pt-|aws-sit-|aws-uat-)", HTML)
    assert not banned, f"文档残留真实机队标识: {sorted(set(banned))}"


if __name__ == "__main__":
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
