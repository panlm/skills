"""本 repo 公开 —— 隐私规则必须有闸门，不能只有文字。

`AGENTS.md` / `CLAUDE.md` 早就禁止 AWS 账号 ID、本机绝对路径等，但 2026-09-13
仍有 4 个 commit 把一个真实账号 ID 写进 `core.py` 注释、一份 spec、一份 plan 与
一个测试 docstring —— 当时那条规则**已经在 main 上**。原因不是没规则，是
「批量脱敏是一次性动作、之后没有任何检查」：ID 被当成"这条实测教训来自哪支机队"
的出处标签写进散文，形态上不像配置，没人（也没有工具）拦它。

所以本文件把隐私规则变成断言。扫描范围是**整个 repo 的 git 跟踪文件 + 未忽略的
未跟踪文件** —— 后者不可省：新写的文件在第一次 commit 前就该被拦住。

例外写法：在该行加注 `privacy-exempt`（与 `SKILL.md` 自检的 `selfcheck-exempt`
同一约定）。加这个标记等同于声明"我核实过这行不含真实身份"。
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXTS = {".md", ".py", ".json", ".jq", ".sh", ".yaml", ".yml", ".txt",
        ".toml", ".html", ".htm"}  # .html：面向客户的说明文档也是公开内容
EXEMPT = "privacy-exempt"

# 允许的占位账号 ID（docs/README.md 的脱敏约定）
PLACEHOLDER_ACCOUNTS = {"123456789012", "000000000000", "111122223333"}

PATTERNS = [
    # ① 12 位数字 = AWS 账号 ID 形态。前后不得紧邻数字，避免误伤长数字串。
    ("aws-account-id", re.compile(r"(?<!\d)\d{12}(?!\d)"),
     lambda m: m.group(0) not in PLACEHOLDER_ACCOUNTS),
    # ② 本机绝对路径（含用户名）。文档一律写 `~/` 或相对路径。
    ("local-home-path", re.compile(r"/(?:Users|home)/[a-z_][a-z0-9_-]*"),
     lambda m: not m.group(0).endswith(("/Users/", "/home/"))),
    # ③ 真实 EC2 实例 ID 是 `i-` + 17 位十六进制；占位符（i-0abc123def）短得多。
    ("ec2-instance-id", re.compile(r"\bi-[0-9a-f]{17}\b"), lambda m: True),
    # ④ AWS 长期/临时 access key id。
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
     lambda m: True),
]


def _scan_files():
    """git 跟踪 + 未忽略的未跟踪文件。用 git 列而不是 glob:.gitignore 要生效。"""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True, text=True, check=True).stdout.splitlines()
    files = []
    for rel in out:
        p = ROOT / rel
        if p.suffix.lower() in EXTS and p.is_file():
            files.append(p)
    return files


def _hits(kind, rx, keep):
    bad = []
    for p in _scan_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if EXEMPT in line:
                continue
            for m in rx.finditer(line):
                if keep(m):
                    rel = p.relative_to(ROOT)
                    bad.append(f"{rel}:{i} [{kind}] {m.group(0)}"
                               f"  ← {line.strip()[:60]}")
    return bad


def test_no_real_aws_account_ids():
    kind, rx, keep = PATTERNS[0]
    bad = _hits(kind, rx, keep)
    assert not bad, ("疑似真实 AWS 账号 ID（本 repo 公开）。占位符用 "
                     "123456789012：\n  " + "\n  ".join(bad))


def test_no_local_absolute_paths():
    kind, rx, keep = PATTERNS[1]
    bad = _hits(kind, rx, keep)
    assert not bad, ("含用户名的本机绝对路径。改写成 `~/` 或相对路径，"
                     "或用 `$(git rev-parse --show-toplevel)`：\n  "
                     + "\n  ".join(bad))


def test_no_real_instance_ids():
    kind, rx, keep = PATTERNS[2]
    bad = _hits(kind, rx, keep)
    assert not bad, ("真实 EC2 实例 ID。示例用 i-0abc123def 这类占位：\n  "
                     + "\n  ".join(bad))


def test_no_aws_access_keys():
    kind, rx, keep = PATTERNS[3]
    bad = _hits(kind, rx, keep)
    assert not bad, ("疑似 AWS access key id —— 若为真实凭证，"
                     "改掉不够，必须立即吊销：\n  " + "\n  ".join(bad))


def test_scanner_actually_sees_files():
    """空扫描集 = 常绿的假安全，是本 repo 另一条 lint 栽过的坑。"""
    files = _scan_files()
    assert len(files) > 50, f"扫描集只有 {len(files)} 个文件，疑似路径算错"
    names = {p.name for p in files}
    assert "SKILL.md" in names, "扫描集里没有任何 SKILL.md，路径算错了"


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
