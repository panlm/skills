import pathlib, re, subprocess, sys, json
ROOT = pathlib.Path(__file__).parent.parent

def test_sample_solve_reproduces_its_four_documented_verdicts():
    """sample-solve.md 记录的四个 verdict 必须由当前 core.py 重新产生。

    少任何一个都说明这四条里有分支不可达——本 skill 曾因 jq 生成器语义
    让 spec-unknown 分支完全死掉，未知机型静默从报告消失。

    **只覆盖这四个**，不是 core.py 的十个 verdict。原名叫
    ..._all_reachable，听起来像覆盖了全部可达性。其余六个的覆盖在
    test_managed_dispatch.py（downsize-candidate / upsize-candidate / blocked）、
    test_fail_closed_contracts.py（price-unknown / excluded）与
    test_regression_fleet.py（已合理配置）。
    """
    doc = (ROOT / "references" / "sample-solve.md").read_text()
    m = re.search(r"```json\n(\[.*?\])\n```", doc, re.S)
    assert m, "sample-solve.md 缺少输入 JSON 块"
    resources = json.loads(m.group(1))
    ctx = {"sizing_profile": "aggressive",
           "specs": [{"t": "m5.large", "vcpu": 2, "gib": 8, "burst": False,
                      "arch": "x86_64", "store": False, "ebs": 81.25, "curgen": True},
                     {"t": "m5.xlarge", "vcpu": 4, "gib": 16, "burst": False,
                      "arch": "x86_64", "store": False, "ebs": 143.75, "curgen": True}],
           "prices": {"m5.large|RunInstances": 0.124, "m5.xlarge|RunInstances": 0.248},
           "baseline_pct": {}, "categories": {"m5.large": "General purpose",
                                              "m5.xlarge": "General purpose"},
           "offerings": ["m5.large", "m5.xlarge"], "legacy_families": [],
           "resources": resources}
    out = subprocess.run([sys.executable, str(ROOT / "references" / "core.py")],
                         input=json.dumps(ctx), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    findings = json.loads(out.stdout)
    assert len(findings) == len(resources), "输入输出行数不等：存在静默丢行"
    got = {f["verdict"] for f in findings}
    assert got == {"downsize", "metric-missing", "spec-unknown", "insufficient-data"}, got

if __name__ == "__main__":
    tests = [test_sample_solve_reproduces_its_four_documented_verdicts]
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
