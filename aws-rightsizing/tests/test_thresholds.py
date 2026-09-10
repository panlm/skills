"""thresholds.json 与 core.py 之间的双向覆盖。

两个方向都必须查，各自防一类缺陷：
  正向（core.py 读的键 → JSON 必须有）——缺键会在运行时才炸，而且只在
    走到那条分支的资源上炸，可能整个 region 都不触发。
  反向（JSON 里的键 → core.py 必须读）——**孤儿键**。实测过一次：
    `reserved_memory_pct_default` 在 JSON 里躺着、`core.py` 把 25 写死在代码里，
    测试断言"这个键存在"于是常绿，而改 JSON 的值结果一毫米都不动。
    新增阈值键时如果忘了接线，这条断言必须响。

键清单**从 core.py 源码抽取**，不手写。手写清单会和真值源一起漂移——
`test_no_duplicated_constants.py` 的守护清单就这么退化成两条死条目过。
"""
import json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "references"))
import core

REF = pathlib.Path(__file__).parent.parent / "references"
CORE_SRC = (REF / "core.py").read_text()

# core.py 里读阈值只有一种写法：t["键名"]（f-string 内是 t['键名']）。
#
# 这个正则**不能**当成"没人改回 .get()"的守卫：实测过——把 evaluate() 里的
# `t["min_biz_hours_points"]` 换成 `t.get(..., 0)` 后本文件全绿，因为
# is_idle / is_stop_candidate 里还有别的下标读法，键照样被抽到。
# 守 .get() 回退的是 tests/test_fail_closed_contracts.py 的
# test_injected_thresholds_missing_sampling_floor_raises（同一处改动会让它失败）。
# 本文件只守键集覆盖，别的别指望。
THRESHOLD_READ = re.compile(r"""\bt\[["']([a-z_0-9]+)["']\]""")


def _keys_read_by_core():
    return set(THRESHOLD_READ.findall(CORE_SRC))


def _profiles():
    return json.loads((REF / "thresholds.json").read_text())["profiles"]


def test_every_key_core_reads_exists_in_both_profiles():
    read = _keys_read_by_core()
    assert read, "没从 core.py 抽到任何 t[\"...\"] 读取——正则失效了"
    profiles = _profiles()
    for name in ("aggressive", "conservative"):
        missing = sorted(read - set(profiles[name]))
        assert not missing, f"{name} 缺少 core.py 会读的键: {missing}"


def test_no_orphan_keys_in_thresholds_json():
    """JSON 里的每个键都必须真的被 core.py 读到，否则它是死键。"""
    read = _keys_read_by_core()
    for name, p in _profiles().items():
        orphans = sorted(k for k in p if not k.startswith("_") and k not in read)
        assert not orphans, (
            f"{name} 里这些键没有任何 core.py 代码读取，是孤儿键: {orphans}。"
            "要么接线，要么删掉——留着会让「改 JSON 就能改行为」这个承诺变成假的")


def test_both_profiles_have_the_same_key_set():
    """两个 profile 的键集必须一致，否则换 profile 会在运行时缺键。"""
    a, c = _profiles()["aggressive"], _profiles()["conservative"]
    assert set(a) == set(c), sorted(set(a) ^ set(c))


def test_load_thresholds_returns_profile():
    t = core.load_thresholds(profile="conservative")
    assert t["target_cpu_p95"] == 40
    assert t["max_reduction_ratio"] == 2


def test_load_thresholds_rejects_unknown_profile():
    try:
        core.load_thresholds(profile="nope")
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("未知 profile 必须抛 ValueError，不得静默回退默认值")


if __name__ == "__main__":
    tests = [
        test_every_key_core_reads_exists_in_both_profiles,
        test_no_orphan_keys_in_thresholds_json,
        test_both_profiles_have_the_same_key_set,
        test_load_thresholds_returns_profile,
        test_load_thresholds_rejects_unknown_profile,
    ]
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
