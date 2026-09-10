"""agg.jq 必须产出真正的 full-window 档。

§2.6 此前用 jq 把三档的 n 相加、max 取 max 来近似全窗口。这对 n 与 max
成立，**对 p95 与 mean 不成立**：并集的 p95 不等于各档 p95 的 max。
否决项改判持续态后需要真正的全窗口 p95，所以这一档必须由 agg.jq 出。
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).parent.parent
AGG = ROOT / "references" / "agg.jq"

# tz = UTC+8。本地 09:00–19:59 是 biz-hours，其余是 off-hours（周末另算）。
#   UTC 01:00–11:00 → 本地 09:00–19:00 ⇒ biz-hours
#   UTC 12:00–15:00 → 本地 20:00–23:00 ⇒ off-hours
# 2026-08-10 与 08-11 都是工作日（周一、周二）。
#
# 数据刻意构造成能抓住「并集 p95 ≠ 各档 p95 的 max」：
#   biz-hours 20 个点全 1.0        ⇒ p95 = 1.0
#   off-hours 4 个点 50/60/70/80   ⇒ p95 = 70.0（下标 floor(3×0.95)=2）
#   各档 p95 的 max = 70.0
#   并集 24 个点，p95 下标 floor(23×0.95)=21 ⇒ 60.0
# 即近似式把 p95 **高估**了（70 vs 60）——方向恰好是「把危险实例判成安全」
# 的反面，但两个数不同这件事本身就说明近似式不成立。
_BIZ = ([f"2026-08-10T{h:02d}:00:00Z" for h in range(1, 12)]      # 11 点
        + [f"2026-08-11T{h:02d}:00:00Z" for h in range(1, 10)])   # 9 点 → 共 20
_OFF = [f"2026-08-10T{h:02d}:00:00Z" for h in range(12, 16)]      # 4 点
PAYLOAD = {"MetricDataResults": [{
    "Label": "r-1|t3.medium|Average",
    "Timestamps": _BIZ + _OFF,
    "Values": [1.0] * len(_BIZ) + [50.0, 60.0, 70.0, 80.0]}]}


def _run():
    p = subprocess.run(["jq", "-r", "--argjson", "tz", "28800", "-f", str(AGG)],
                       input=json.dumps(PAYLOAD), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_full_window_bucket_is_emitted():
    rows = {r["bucket"]: r for r in _run()}
    assert "full-window" in rows, f"缺 full-window 档：{sorted(rows)}"
    fw = rows["full-window"]
    assert fw["n"] == 24, fw
    assert fw["max"] == 80.0 and fw["min"] == 1.0, fw
    assert abs(fw["mean"] - (20 * 1.0 + 260.0) / 24) < 1e-9, fw


def test_full_window_p95_is_not_the_max_of_per_band_p95():
    """本不变式是这一档存在的理由：并集 p95 ≠ 各档 p95 的 max。"""
    rows = {r["bucket"]: r for r in _run()}
    per_band_max = max(rows["biz-hours"]["p95"], rows["off-hours"]["p95"])
    assert per_band_max == 70.0, rows
    assert rows["full-window"]["p95"] == 60.0, rows["full-window"]
    assert rows["full-window"]["p95"] != per_band_max, (
        "并集 p95 与各档 p95 的 max 相等，本 fixture 证明不了近似式不成立")


def test_three_bands_unchanged():
    rows = {r["bucket"]: r for r in _run()}
    assert rows["biz-hours"]["n"] == 20 and rows["off-hours"]["n"] == 4, rows
    assert "weekend" not in rows, "无 weekend 点时不应凭空产出该档"


def test_identity_fields_survive_on_every_bucket():
    """rid / itype / stat 在四档上都要在，否则下游 join 不回资源。"""
    for r in _run():
        assert r["rid"] == "r-1" and r["itype"] == "t3.medium", r
        assert r["stat"] == "Average", r


if __name__ == "__main__":
    tests = [test_full_window_bucket_is_emitted,
             test_full_window_p95_is_not_the_max_of_per_band_p95,
             test_three_bands_unchanged,
             test_identity_fields_survive_on_every_bucket]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"✓ {fn.__name__}")
        except Exception as e:
            print(f"✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
