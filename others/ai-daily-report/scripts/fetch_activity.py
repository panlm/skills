#!/usr/bin/env python3
"""取报告日(Asia/Shanghai 整天)的 agent 活动，并跑完整性闸门。

替代 SKILL.md Step 0 + Step 1 的全部手工步骤：窗口计算、timeline 分页、
dedup、facts 判空、时段分布。直连 agentmemory REST，不经过 MCP —— 所以在
Mac claude / EC2 openclaw / cron claude -p 上取数结果完全一致。

用法:
    python3 fetch_activity.py                     # 报告日 = 昨天(北京)
    python3 fetch_activity.py --date 2026-08-05   # 指定报告日
    python3 fetch_activity.py --json out.json     # 同时落盘完整数据

凭证从环境变量读，脚本不含也不打印任何 secret:
    AGENTMEMORY_URL     如 https://agentmemory.example.com
    AGENTMEMORY_SECRET  Bearer token

退出码:
    0  闸门通过
    2  闸门未通过(取数可疑，不准往下写日报)
    3  配置/网络错误
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SH = timezone(timedelta(hours=8))

# 闸门阈值。M/N 偏低不一定是漏，但必须给出排除证据才能往下走。
MIN_OBS = 50
MIN_SESSIONS = 3
PAGE_SIZE = 400
MAX_PAGES = 20


def die(msg, code=3):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config():
    url = os.environ.get("AGENTMEMORY_URL", "").rstrip("/")
    secret = os.environ.get("AGENTMEMORY_SECRET", "")
    if not url:
        die(
            "缺少环境变量 AGENTMEMORY_URL。\n"
            "  取法见 SKILL.md「Step 0b 准备凭证」——通常在 agentmemory 的本地 env 文件里，\n"
            "  用 `set -a; . <env 文件>; set +a` 载入当前 shell 后重跑本脚本。"
        )
    if not secret:
        die(
            "缺少环境变量 AGENTMEMORY_SECRET。\n"
            "  同上：从 agentmemory 的本地 env 文件载入，不要写进任何脚本或提交进仓库。"
        )
    return url, secret


def post(url, secret, path, payload):
    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        if e.code in (401, 403):
            die(f"认证失败 ({e.code})。AGENTMEMORY_SECRET 可能不对或已轮换。")
        die(f"{path} 返回 HTTP {e.code}: {body}")
    except Exception as e:
        die(f"请求 {path} 失败: {type(e).__name__}: {e}")


def window(date_str):
    """报告日 -> (D, DOW, YM, START, END)，窗口 = 北京时区完整一天。"""
    if date_str:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        d = (datetime.now(SH) - timedelta(days=1)).date()
    start = datetime(d.year, d.month, d.day, tzinfo=SH)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (
        d.isoformat(),
        start.isoweekday(),
        d.strftime("%Y%m"),
        start.astimezone(timezone.utc).strftime(fmt),
        end.astimezone(timezone.utc).strftime(fmt),
    )


def fetch_timeline(url, secret, start, end):
    """分页拉 timeline 直到覆盖 END 之后。返回 (dedup 后全集, 首页条数, 页数)。"""
    seen, anchor, first_page_count, pages = {}, start, None, 0
    while pages < MAX_PAGES:
        data = post(
            url, secret, "/agentmemory/timeline",
            {"anchor": anchor, "before": 0, "after": PAGE_SIZE},
        )
        entries = data.get("entries") or []
        pages += 1
        if first_page_count is None:
            first_page_count = len(entries)
        if not entries:
            break

        fresh = 0
        for x in entries:
            o = x.get("observation", x)
            if o.get("id") and o["id"] not in seen:
                seen[o["id"]] = o
                fresh += 1

        page_max = max(
            (x.get("observation", x).get("timestamp", "") for x in entries),
            default="",
        )
        # 覆盖到 END 之后即可停；无新增说明已到库尾。
        if page_max >= end or fresh == 0:
            break
        anchor = page_max
    return seen, first_page_count, pages


def buckets(obs):
    """北京时间 4 段 observation 分布。"""
    out = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
    for o in obs:
        h = datetime.fromisoformat(
            o["timestamp"].replace("Z", "+00:00")
        ).astimezone(SH).hour
        lo = h // 6 * 6
        out[f"{lo:02d}-{lo + 6:02d}"] += 1
    return out


def max_zero_run(b):
    run = best = 0
    for k in ["00-06", "06-12", "12-18", "18-24"]:
        run = run + 1 if b[k] == 0 else 0
        best = max(best, run)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告日 YYYY-MM-DD，默认昨天(北京)")
    ap.add_argument("--json", help="把完整取数结果落盘到该路径")
    args = ap.parse_args()

    url, secret = load_config()
    d, dow, ym, start, end = window(args.date)
    print(f"报告日 {d} 周{'一二三四五六日'[dow - 1]}  飞书文档 工作日报-{ym}")
    print(f"窗口(UTC) [{start}, {end})\n")

    allobs, first_page, pages = fetch_timeline(url, secret, start, end)
    win = [o for o in allobs.values() if start <= o["timestamp"] < end]
    win.sort(key=lambda o: o["timestamp"])

    ts = sorted(o["timestamp"] for o in allobs.values())
    span = (ts[0], ts[-1]) if ts else ("-", "-")
    sessions = sorted({o["sessionId"] for o in win})
    substantive = [o for o in win if len(o.get("facts") or []) >= 1]
    empty = [o for o in win if not (o.get("facts") or [])]
    b = buckets(win)

    print(f"分页 {pages} 页，首页返回 {first_page} 条(上限 {PAGE_SIZE})")
    print(f"dedup 全集 {len(allobs)} 条，覆盖 {span[0]} -> {span[1]}")
    print(f"窗口内 N={len(sessions)} session  M={len(win)} observation")
    print(f"  facts>=1(有实质内容) {len(substantive)} 条 / facts==0(真空心跳) {len(empty)} 条")
    print(f"北京时段分布 {b}   最长连续 0 段 = {max_zero_run(b)}\n")

    print("=== 窗口内 observation(facts>=1 的每条都必须进 bullet) ===")
    for o in win:
        nf = len(o.get("facts") or [])
        bj = datetime.fromisoformat(
            o["timestamp"].replace("Z", "+00:00")
        ).astimezone(SH).strftime("%m-%d %H:%M")
        flag = " " if nf else "×"
        print(f"{flag} {bj} 京 | {o['sessionId'][:8]} | facts={nf:<3}| {o['title'][:70]}")

    # ---- 闸门 ----
    fails = []
    if max_zero_run(b) >= 2:
        fails.append(
            f"北京时段连续 {max_zero_run(b)} 段为 0 —— 通常是 timeline 没拉够，回去多拉几页"
        )
    low = []
    if len(win) < MIN_OBS:
        low.append(f"M={len(win)} < {MIN_OBS}")
    if len(sessions) < MIN_SESSIONS:
        low.append(f"N={len(sessions)} < {MIN_SESSIONS}")
    if low:
        # 库里本来就少 != 取数漏了。首页未打满是"库里少"的硬证据。
        if first_page is not None and first_page < PAGE_SIZE:
            print(
                f"\n注意 {' 且 '.join(low)}，但首页 after={PAGE_SIZE} 只返回 {first_page} 条 —— "
                f"证明 START 之后库里总量就只有 {first_page} 条，是库里少不是分页截断。"
                f"\n     Step 4 汇报里必须写明该证据 + 上面的时段分布。"
            )
        else:
            fails.append(
                f"{' 且 '.join(low)}，且首页已打满 {PAGE_SIZE} 条 —— 极可能还有没拉到的记录"
            )

    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                {
                    "date": d, "dow": dow, "ym": ym, "start": start, "end": end,
                    "n_sessions": len(sessions), "m_obs": len(win),
                    "buckets": b, "first_page_count": first_page,
                    "dedup_total": len(allobs), "span": span,
                    "observations": win,
                },
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n完整数据已落盘 {args.json}")

    if fails:
        print("\n闸门未通过，不准往下写日报:", file=sys.stderr)
        for x in fails:
            print(f"  - {x}", file=sys.stderr)
        sys.exit(2)

    print(f"\n闸门通过。下一步: 为上面 {len(substantive)} 条 facts>=1 的记录写 bullet。")


if __name__ == "__main__":
    main()
