"""门禁必须真的执行每个测试文件里的每条断言。

`SKILL.md` 的门禁是 `for t in tests/test_*.py; do python3 "$t" || exit 1; done`。
没有 `__main__` runner 的文件在这条命令下**退出码 0 而执行 0 条断言** ——
本机默认 python3 不带 pytest，`python3 tests/test_x.py` 只是 import 一遍模块，
断言全留在没被调用的函数体里。实测三个文件（`test_rds_criteria` /
`test_managed_target_selection` / `test_regression_managed`）因此从未在门禁里跑过，
而门禁逐个成功返回、退出码 0。

runner 用手写清单枚举 `test_*` 是同一漏洞的细粒度版本：新增的函数不写进清单
就永远不跑，门禁照样全绿。所以本守卫不查「有没有 runner」，
查的是「runner 报告跑了几条」与「文件里定义了几条」是否相等。
"""
import ast
import pathlib
import re
import subprocess
import sys

TESTS = pathlib.Path(__file__).resolve().parent
SELF = pathlib.Path(__file__).resolve()
COUNT_RE = re.compile(r"(\d+)/(\d+) passed")


def _module_level_test_functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


def _peer_files():
    return sorted(p for p in TESTS.glob("test_*.py") if p.resolve() != SELF)


def test_every_file_reports_running_all_of_its_tests():
    bad = []
    for p in _peer_files():
        want = len(_module_level_test_functions(p))
        r = subprocess.run([sys.executable, str(p)],
                           capture_output=True, text=True)
        m = COUNT_RE.search(r.stdout)
        if r.returncode != 0:
            bad.append(f"{p.name}: 退出码 {r.returncode}（门禁会中断）")
        elif m is None:
            bad.append(f"{p.name}: 定义了 {want} 条 test_*，门禁下没有打印 "
                       f"`n/n passed` ⇒ 一条都没执行（缺 __main__ runner）")
        elif int(m.group(2)) != want:
            bad.append(f"{p.name}: runner 只枚举了 {m.group(2)} 条，"
                       f"文件里定义了 {want} 条")
        elif int(m.group(1)) != want:
            bad.append(f"{p.name}: {m.group(1)}/{want} 通过")
    assert not bad, ("门禁没有覆盖到下列文件的断言：\n  " + "\n  ".join(bad))


def test_this_guard_itself_runs_under_the_gate():
    """守卫自己也必须被门禁执行，否则它是一条自我豁免的规则。"""
    src = SELF.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert any(isinstance(n, ast.If)
               and ast.unparse(n.test).startswith("__name__")
               for n in tree.body), "本文件缺 __main__ runner"
    assert "passed" in src, "本文件的 runner 必须打印 `n/n passed`"


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
