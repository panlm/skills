#!/usr/bin/env python3
"""覆盖核对：每条 facts>=1 的 observation 是否都进了日报 bullet。

这是发布前的硬闸门，替代 SKILL.md 里 d2/d3/d4 的手工核对。d2 的
`blocks_added >= bullet 数+1` 拿写入数比自己写的 bullet 数，恒真 ——
写 4 条也过、写 8 条也过。本脚本改成跟【取数结果】对账：漏一条就退出 2。

用法:
    python3 check_coverage.py --activity act.json --report daily.md --map map.json

map.json 形如 {"2026-08-05T08:48:46": 6, ...}
  key   = observation 的 timestamp 前 19 字符(UTC，见 fetch_activity 输出)
  value = 该记录归到第几条 bullet(1-based)
多条 observation 归同一条 bullet 是允许的(同一任务的连续步骤)。

退出码:
    0  覆盖完整，可以写飞书
    2  有未归属记录或结论类 bullet 缺证据 —— 不准写飞书
    3  参数/文件错误
"""

import argparse
import json
import re
import sys

# 排除性结论关键词。这类 bullet 把"没查到"写成"本来没有"，最容易掩盖漏数。
EXCLUSION_HINTS = [
    "空会话", "心跳", "无实质内容", "无实际操作",
    "已计入", "不属于本报告日", "没有实际",
]


def die(msg, code=3):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def parse_bullets(md_path):
    """从日报 markdown 提取 bullet 文本，返回 [(序号, 文本)]。"""
    try:
        lines = open(md_path, encoding="utf-8").read().splitlines()
    except OSError as e:
        die(f"读不到日报文件 {md_path}: {e}")
    out, n = [], 0
    for line in lines:
        if line.startswith("- "):
            n += 1
            out.append((n, line[2:].strip()))
    if not out:
        die(f"{md_path} 里没找到任何 `- ` 开头的 bullet")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activity", required=True, help="fetch_activity.py --json 的输出")
    ap.add_argument("--report", required=True, help="日报 markdown")
    ap.add_argument("--map", required=True, help="observation timestamp -> bullet 序号")
    args = ap.parse_args()

    try:
        act = json.load(open(args.activity, encoding="utf-8"))
        mapping = json.load(open(args.map, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        die(f"读取输入失败: {e}")

    obs = act.get("observations") or []
    if not obs:
        die(f"{args.activity} 里没有 observations")
    bullets = parse_bullets(args.report)
    substantive = [o for o in obs if len(o.get("facts") or []) >= 1]
    empty_count = len(obs) - len(substantive)

    print(f"取数: {len(obs)} 条 observation (facts>=1: {len(substantive)}, facts==0: {empty_count})")
    print(f"日报: {len(bullets)} 条 bullet\n")

    fails = []

    # --- d3: 逐条覆盖 ---
    unmapped = []
    for o in substantive:
        key = o["timestamp"][:19]
        if key not in mapping:
            unmapped.append(o)
    if unmapped:
        fails.append(f"{len(unmapped)} 条 facts>=1 的 observation 未归属到任何 bullet")
        print("未归属记录:")
        for o in sorted(unmapped, key=lambda x: x["timestamp"]):
            print(f"  × {o['timestamp'][:19]} facts={len(o['facts'])} {o['title'][:66]}")
        print()

    # 映射里指向不存在的 bullet 序号 = 映射本身写错了
    bad = [k for k, v in mapping.items() if not isinstance(v, int) or not 1 <= v <= len(bullets)]
    if bad:
        fails.append(f"映射里 {len(bad)} 个条目指向不存在的 bullet 序号: {bad[:5]}")

    # 映射里有取数结果里不存在的 key = 映射对不上这次取数
    known = {o["timestamp"][:19] for o in obs}
    ghost = [k for k in mapping if k not in known]
    if ghost:
        fails.append(f"映射里 {len(ghost)} 个 timestamp 不在本次取数结果中: {ghost[:5]}")

    # --- 每条 bullet 都该有归属记录，否则 bullet 内容无出处 ---
    used = set(mapping.values())
    orphan = [n for n, _ in bullets if n not in used]
    if orphan:
        fails.append(f"bullet {orphan} 没有任何 observation 归属 —— 内容无出处，可能是编的")

    # --- d4: 排除性结论必须有证据 ---
    for n, text in bullets:
        hit = [w for w in EXCLUSION_HINTS if w in text]
        if not hit:
            continue
        # 有数字就算给了证据(如 "0 facts"、"18 条"、时间戳)
        has_evidence = bool(re.search(r"\d", text))
        if empty_count == 0 and any(w in text for w in ("空会话", "心跳", "无实质内容", "无实际操作")):
            fails.append(
                f"bullet {n} 写了「{hit[0]}」，但本次取数 facts==0 的条数为 0 —— "
                f"该结论不成立，删掉或改成如实写出内容"
            )
        elif not has_evidence:
            fails.append(
                f"bullet {n} 是排除性结论(含「{hit[0]}」)但没给支撑数字 —— "
                f"补上 0 facts 条数或窗口外时间戳证据"
            )

    if fails:
        print("覆盖核对未通过，禁止写入飞书:", file=sys.stderr)
        for x in fails:
            print(f"  - {x}", file=sys.stderr)
        sys.exit(2)

    print(f"覆盖核对通过: {len(substantive)} 条实质记录全部归属，"
          f"{len(bullets)} 条 bullet 均有出处。可以写飞书。")


if __name__ == "__main__":
    main()
