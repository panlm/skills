#!/usr/bin/env python3
"""按屏幕顺序列出可寻址的 Claude Code session，并标出哪些序数够不到。

    roster.py           人读的表
    roster.py --json    机器读

两套注册表，一个 join key：

  herdr agent list          只有 herdr pane 里的 session，带 tokens.sname
  ~/.claude/sessions/*.json 本机所有活着的 claude 进程，是 ListAgents 的源，带 name

`tokens.sname` == `name` == `SendMessage({to})` 的地址。差集（在 sessions 里但不在
herdr 里）是 orca 或裸终端起的，屏幕上没有对应 pane，序数指代够不到。

排序 = session.json 的 workspaces[] 数组顺序 → tab 公开号 → pane 公开号，
也就是屏幕上从左到右、从上到下。不要用 session.json 里的**内部** pane key，
那是 public_pane_numbers 映射前的值（实测内部 3/4 对应公开 1/2）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERDR_STATE = os.path.expanduser("~/.config/herdr/session.json")
SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")


def workspace_order() -> list[str]:
    """屏幕上 workspace 的先后，取自 herdr 自己的状态文件。"""
    try:
        with open(HERDR_STATE) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for ws in state.get("workspaces", []):
        wid = ws.get("id") or ws.get("workspace_id")
        if wid:
            out.append(wid)
    return out


def herdr_agents() -> list[dict]:
    try:
        raw = subprocess.run(
            ["herdr", "agent", "list"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if raw.returncode != 0:
        return []
    try:
        doc = json.loads(raw.stdout)
    except ValueError:
        return []
    return doc.get("result", {}).get("agents") or doc.get("agents") or []


def public_num(ident: str, prefix: str) -> int:
    """`w1A:p2` + 'p' -> 2。取不到就排最后。"""
    m = re.search(rf"{prefix}(\d+)$", ident or "")
    return int(m.group(1)) if m else 1 << 30


def live_sessions() -> dict[str, dict]:
    """name -> 注册表记录。这是 ListAgents 的源。"""
    out: dict[str, dict] = {}
    try:
        names = os.listdir(SESSIONS_DIR)
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, fn)) as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        name = rec.get("name")
        if name:
            out[name] = rec
    return out


def build() -> dict:
    order = workspace_order()

    def sort_key(a: dict) -> tuple:
        wid = a.get("workspace_id") or ""
        widx = order.index(wid) if wid in order else 1 << 30
        return (widx, public_num(a.get("tab_id", ""), "t"), public_num(a.get("pane_id", ""), "p"))

    me = os.environ.get("HERDR_PANE_ID")
    sessions = live_sessions()

    rows = []
    for i, a in enumerate(sorted(herdr_agents(), key=sort_key), start=1):
        sname = (a.get("tokens") or {}).get("sname")
        rec = sessions.get(sname, {})
        rows.append({
            "n": i,
            "pane": a.get("pane_id"),
            "kind": a.get("agent"),
            "sname": sname,
            "status": a.get("agent_status"),
            "title": a.get("terminal_title_stripped") or "",
            "cwd": a.get("cwd") or rec.get("cwd") or "",
            "session_id": (a.get("agent_session") or {}).get("value") or rec.get("sessionId"),
            "pid": rec.get("pid"),
            "is_self": a.get("pane_id") == me,
        })

    self_index = next((r["n"] for r in rows if r["is_self"]), None)

    visible = {r["sname"] for r in rows if r["sname"]}
    outside = [
        {
            "sname": name,
            "status": rec.get("status"),
            "cwd": rec.get("cwd"),
            "session_id": rec.get("sessionId"),
            "pid": rec.get("pid"),
        }
        for name, rec in sorted(sessions.items())
        if name not in visible
    ]
    return {
        "agents": rows,
        "outside_herdr": outside,
        "self_pane": me,
        "self_index": self_index,
    }


def main() -> int:
    data = build()
    if "--json" in sys.argv:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if not data["self_pane"]:
        print("⚠️  HERDR_PANE_ID 未设 —— 不在 herdr pane 里跑，is_self 判据整个失效。")
        print("    任何序数解析都必须回去问人，别自己认。")
        print()

    rows = data["agents"]
    if not rows:
        print("herdr 里没有可寻址的 agent（herdr 没跑，或这里不在 herdr pane 内）")
    else:
        print("%-3s %-9s %-8s %-11s %-9s %s" % ("#", "pane", "kind", "sname", "状态", "标题"))
        print("-" * 94)
        for r in rows:
            mark = "  ← 你在这" if r["is_self"] else ""
            # 非 claude 的 pane 没有 sname（sname 来自 Claude Code 自己的注册表），
            # 只能用 pane_id 寻址，且 SendMessage 到不了它。
            sname = r["sname"] or "—(无)"
            print("%-3s %-9s %-8s %-11s %-9s %s%s" % (
                r["n"], r["pane"] or "?", r["kind"] or "?", sname, r["status"] or "?", r["title"], mark))
        if any(not r["sname"] for r in rows):
            print()
            print("标 —(无) 的不是 Claude Code：没有 sname，SendMessage 到不了，只能用 pane_id 走 herdr。")

    si = data["self_index"]
    if si is not None:
        print()
        print("你自己排在 #%d。人说「第 N 个」且 N >= %d 时，" % (si, si))
        print("「含自己数」和「除自己数」会指向不同的 session —— 必须先问清，别自己认。")

    if data["outside_herdr"]:
        print()
        print("herdr 之外（在 ListAgents 里，屏幕上没有 pane，序数够不到；要发必须显式点名）：")
        for r in data["outside_herdr"]:
            print("    %-11s %-9s pid=%-7s %s" % (
                r["sname"], r["status"] or "?", r["pid"] or "?", r["cwd"] or ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
