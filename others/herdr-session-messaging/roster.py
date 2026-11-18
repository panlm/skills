#!/usr/bin/env python3
"""按屏幕顺序列出可寻址的 session，同时支持两套终端管理：

  * herdr（旧 TUI）        `herdr agent list`，自己是 $HERDR_PANE_ID
  * herdr-core + herdr-app `hc ls` + `herdr-app ls`，自己是 $HC_TERMINAL_ID

    roster.py            人读的表（只看本机，不连远端）
    roster.py --remote   再连到远端机器列一次（hc exec / ssh，只读）
    roster.py --json     机器读（可和 --remote 一起用）

SendMessage 的地址是 Claude Code 自己注册表里的 name（~/.claude/sessions/<pid>.json，
也是 ListAgents 的源）。两套后端各有一条路通到它：

  herdr      tokens.sname 逐字等于 name
  hc         terminal → `hc get` 的 foreground.pid → 往下找子孙进程里有
             sessions/<pid>.json 的那个 claude → 它的 name

排序：
  herdr      session.json 的 workspaces[] 顺序 → tab 公开号 → pane 公开号
  herdr-app  `herdr-app ls` 里 spaces → tabs → terminals 的先后（实测同一个 tab
             里就是从左到右）。窗口没开时只能退回 `hc ls` 的顺序，不代表屏幕位置。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

HERDR_STATE = os.path.expanduser("~/.config/herdr/session.json")
SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")


def run_json(argv: list[str], timeout: int = 10):
    try:
        # argv 永远是列表、不经 shell；元素是常量，或者 hc 自己输出的 terminal 地址。
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)  # nosemgrep: dangerous-subprocess-use-audit
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


# ---------------------------------------------------------------- claude 注册表

def live_sessions() -> tuple[dict[str, dict], dict[int, dict]]:
    """(name -> 记录, pid -> 记录)。这是 ListAgents 的源。"""
    by_name: dict[str, dict] = {}
    by_pid: dict[int, dict] = {}
    try:
        names = os.listdir(SESSIONS_DIR)
    except OSError:
        return by_name, by_pid
    for fn in names:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, fn), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        name = rec.get("name")
        if name:
            by_name[name] = rec
        try:
            by_pid[int(fn[:-5])] = rec
        except ValueError:
            pass
    return by_name, by_pid


def children_map() -> dict[int, list[int]]:
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    kids: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    return kids


def claude_under(pid: int | None, kids: dict[int, list[int]], by_pid: dict[int, dict]) -> dict | None:
    """pid 自己或它的子孙里，第一个在 ~/.claude/sessions 里登记过的进程。"""
    if not pid:
        return None
    todo, seen = [pid], set()
    while todo:
        p = todo.pop(0)
        if p in seen:
            continue
        seen.add(p)
        if p in by_pid:
            return by_pid[p]
        todo.extend(kids.get(p, []))
    return None


# ---------------------------------------------------------------- 旧 herdr

def public_num(ident: str, prefix: str) -> int:
    """`w1A:p2` + 'p' -> 2。取不到就排最后。"""
    m = re.search(rf"{prefix}(\d+)$", ident or "")
    return int(m.group(1)) if m else 1 << 30


def herdr_rows(sessions: dict[str, dict]) -> tuple[list[dict], bool]:
    doc = run_json(["herdr", "agent", "list"])
    if doc is None:
        return [], False
    agents = doc.get("result", {}).get("agents") or doc.get("agents") or []
    try:
        with open(HERDR_STATE, encoding="utf-8") as fh:
            order = [w.get("id") or w.get("workspace_id") for w in json.load(fh).get("workspaces", [])]
    except (OSError, ValueError):
        order = []

    def key(a: dict) -> tuple:
        wid = a.get("workspace_id") or ""
        return (order.index(wid) if wid in order else 1 << 30,
                public_num(a.get("tab_id", ""), "t"), public_num(a.get("pane_id", ""), "p"))

    me = os.environ.get("HERDR_PANE_ID")
    rows = []
    for a in sorted(agents, key=key):
        sname = (a.get("tokens") or {}).get("sname")
        rec = sessions.get(sname, {})
        rows.append({
            "backend": "herdr",
            "address": a.get("pane_id"),
            "pane": a.get("pane_id"),
            "group": a.get("tab_id"),
            "where": a.get("terminal_title_stripped") or "",
            "kind": a.get("agent"),
            "sname": sname,
            "status": a.get("agent_status"),
            "cwd": a.get("cwd") or rec.get("cwd") or "",
            "session_id": (a.get("agent_session") or {}).get("value") or rec.get("sessionId"),
            "pid": rec.get("pid"),
            "is_self": bool(me) and a.get("pane_id") == me,
        })
    return rows, True


# ---------------------------------------------------------------- herdr-core + app

def hc_rows(by_pid: dict[int, dict]) -> tuple[list[dict], bool, bool]:
    """(行, hc 在不在, 有没有屏幕顺序)。"""
    doc = run_json(["hc", "ls", "--json"])
    if doc is None:
        return [], False, False
    terms = {t["address"]: t for t in doc.get("terminals", []) if t.get("address")}

    # 屏幕顺序：herdr-app ls（窗口开着才有）
    placed: list[tuple[str, str, str, str, str]] = []  # (terminal, pane, space, tab_id, tab_name)
    app = run_json(["herdr-app", "ls"])
    if app:
        for sp in app.get("spaces", []):
            for tb in sp.get("tabs", []):
                for t in tb.get("terminals", []):
                    if t.get("terminal"):
                        placed.append((t["terminal"], t.get("pane") or "", sp.get("name") or "",
                                       tb.get("id") or "", tb.get("name") or ""))
    on_screen = bool(placed)
    order = [p[0] for p in placed] or sorted(terms)
    meta = {p[0]: p for p in placed}

    kids = children_map()
    me = os.environ.get("HC_TERMINAL_ID")
    rows = []
    for addr in order:
        t = terms.get(addr, {})
        if not t and addr not in meta:
            continue
        rec = None
        kind = t.get("agent")
        if kind == "claude-code":
            got = run_json(["hc", "get", addr, "--json"]) or {}
            rec = claude_under((got.get("foreground") or {}).get("pid"), kids, by_pid)
        _, pane, space, tab_id, tab_name = meta.get(addr, (addr, "", "", "", ""))
        rows.append({
            "backend": "hc",
            "address": addr,
            "pane": pane,
            "group": tab_id,
            "where": t.get("where") or (f"{space} / {tab_name}" if space or tab_name else ""),
            "kind": kind,
            "sname": (rec or {}).get("name"),
            "status": t.get("status"),
            "cwd": t.get("cwd") or (rec or {}).get("cwd") or "",
            "session_id": (rec or {}).get("sessionId"),
            "pid": (rec or {}).get("pid"),
            "is_self": bool(me) and addr == me,
            "on_screen": addr in meta,
        })
    return rows, True, on_screen


# ---------------------------------------------------------------- 远端机器

HERDR_ENDPOINTS = os.path.expanduser("~/.local/state/herdr/client/endpoints.json")
HERDR_SSH_META = os.path.expanduser("~/.local/state/herdr/client/ssh-metadata")

# 机器名、ssh 目标、endpoint id 都来自本机配置文件，拿去拼命令行和路径之前先校验：
# 不许以 - 开头（会被当成 ssh/hc 的选项），不许带 / 和 ..（会拼出别的路径）。
SAFE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._@:-]*")
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


def safe(value, pattern=SAFE_NAME) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def remote_exe(exe: str) -> str:
    """给远端 shell 用的 herdr 路径：加引号防注入，但保留开头 ~/ 的展开。"""
    if exe.startswith("~/"):
        return '"$HOME"/' + shlex.quote(exe[2:])
    return shlex.quote(exe)


def json_from(text: str):
    """ssh 的 ProxyCommand 会往输出里混警告：从第一个 { 开始解析。"""
    i = (text or "").find("{")
    if i < 0:
        return None
    try:
        return json.loads(text[i:])
    except ValueError:
        return None


def remote_machines() -> list[dict]:
    """两套后端各自挂的远端机器。只读本机配置，不连过去。"""
    out = []
    doc = run_json(["hc", "machine", "ls", "--json"]) or {}
    for m in doc.get("machines", []):
        out.append({"backend": "hc", "name": m.get("name"), "target": m.get("target"),
                    "state": m.get("state")})
    try:
        with open(HERDR_ENDPOINTS, encoding="utf-8") as fh:
            eps = json.load(fh).get("ssh", [])
    except (OSError, ValueError):
        eps = []
    for e in eps:
        if not e.get("enabled"):
            continue
        exe = "herdr"
        eid = safe(e.get("id"), SAFE_ID)
        if eid:
            try:
                # eid 已经过 SAFE_ID 整串校验（只有字母数字、_、-），拼不出 ../ 或别的目录。
                with open(os.path.join(HERDR_SSH_META, eid + ".json"), encoding="utf-8") as fh:  # nosemgrep: hooks-path-traversal-python, hooks-sensitive-file-access-python
                    exe = (json.load(fh).get("metadata") or {}).get("executable") or exe
            except (OSError, ValueError):
                pass
        out.append({"backend": "herdr", "name": e.get("label"), "target": e.get("target"),
                    "state": "enabled", "executable": exe})
    return out


def remote_rows(machines: list[dict]) -> list[dict]:
    """--remote 时才跑：连到每台远端机器列一次（都是只读命令）。"""
    rows = []
    for m in machines:
        if m["backend"] == "hc":
            if m.get("state") != "connected":
                m["error"] = f"state={m.get('state')}"
                continue
            if not safe(m.get("name")):
                m["error"] = "机器名不合规，没连"
                continue
            try:
                r = subprocess.run(["hc", "exec", "--on", m["name"], "hc", "ls", "--json"],
                                   capture_output=True, text=True, timeout=30)
                doc = json_from(r.stdout)
            except (OSError, subprocess.TimeoutExpired):
                doc = None
            if doc is None:
                m["error"] = "hc exec 没拿到 JSON"
                continue
            for t in doc.get("terminals", []):
                rows.append({"backend": "hc", "machine": m["name"],
                             "address": f"{m['name']}/{t.get('address')}",
                             "where": t.get("where") or "", "kind": t.get("agent"),
                             "status": t.get("status"), "name": t.get("name")})
        else:
            if not safe(m.get("target")):
                m["error"] = "ssh 目标不合规，没连"
                continue
            exe = remote_exe(m.get("executable") or "herdr")
            try:
                r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "--", m["target"],
                                    f"command -v herdr >/dev/null && herdr agent list || {exe} agent list"],
                                   capture_output=True, text=True, timeout=40)
                doc = json_from(r.stdout)
            except (OSError, subprocess.TimeoutExpired):
                doc = None
            if doc is None:
                m["error"] = "ssh 没拿到 JSON"
                continue
            for a in doc.get("result", {}).get("agents") or doc.get("agents") or []:
                rows.append({"backend": "herdr", "machine": m["name"],
                             "address": a.get("pane_id"),
                             "where": a.get("terminal_title_stripped") or "", "kind": a.get("agent"),
                             "status": a.get("agent_status"), "name": a.get("name")})
    return rows


# ---------------------------------------------------------------- 汇总

def build(remote: bool = False) -> dict:
    by_name, by_pid = live_sessions()
    hrows, herdr_up = herdr_rows(by_name)
    crows, hc_up, on_screen = hc_rows(by_pid)
    machines = remote_machines()
    rrows = remote_rows(machines) if remote else []

    rows = crows + hrows  # herdr-app 在前：它是现在用的
    for i, r in enumerate(rows, start=1):
        r["n"] = i
    self_row = next((r for r in rows if r["is_self"]), None)
    neighbors = [r for r in rows if self_row and r is not self_row
                 and r["backend"] == self_row["backend"] and r["group"] and r["group"] == self_row["group"]]

    visible = {r["sname"] for r in rows if r["sname"]}
    outside = [{"sname": n, "status": rec.get("status"), "cwd": rec.get("cwd"),
                "session_id": rec.get("sessionId"), "pid": rec.get("pid")}
               for n, rec in sorted(by_name.items()) if n not in visible]
    return {
        "backends": {"herdr": herdr_up, "hc": hc_up, "herdr_app_window": on_screen},
        "self_env": {"HC_TERMINAL_ID": os.environ.get("HC_TERMINAL_ID"),
                     "HERDR_PANE_ID": os.environ.get("HERDR_PANE_ID")},
        "self_index": self_row["n"] if self_row else None,
        "self": self_row,
        "same_tab": neighbors,
        "agents": rows,
        "outside": outside,
        "machines": machines,
        "remote_checked": remote,
        "remote_agents": rrows,
    }


def main() -> int:
    data = build(remote="--remote" in sys.argv)
    if "--json" in sys.argv:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    b = data["backends"]
    print("后端：herdr-core/app %s%s；旧 herdr %s" % (
        "在" if b["hc"] else "不在",
        "" if not b["hc"] else ("（窗口开着，有屏幕顺序）" if b["herdr_app_window"] else "（窗口没开，下面只是 hc 的顺序）"),
        "在" if b["herdr"] else "不在"))
    env = data["self_env"]
    if not data["self"]:
        print("⚠️  认不出自己：HC_TERMINAL_ID=%s，HERDR_PANE_ID=%s。" % (env["HC_TERMINAL_ID"], env["HERDR_PANE_ID"]))
        print("    「第 N 个」「右边」这类说法都必须回去问人，别自己认。")
    print()

    rows = data["agents"]
    if not rows:
        print("两套后端里都没有可寻址的 terminal/pane")
    else:
        print("%-3s %-6s %-9s %-26s %-12s %-11s %-8s" % ("#", "后端", "地址", "位置", "kind", "sname", "状态"))
        print("-" * 96)
        for r in rows:
            mark = "  ← 你在这" if r["is_self"] else ""
            if r in data["same_tab"]:
                mark = "  ← 和你同一个 tab"
            if r["backend"] == "hc" and not r.get("on_screen", True):
                mark += "（窗口里没有）"
            print("%-3s %-6s %-9s %-26s %-12s %-11s %-8s%s" % (
                r["n"], r["backend"], r["address"] or "?", (r["where"] or "")[:26], r["kind"] or "?",
                r["sname"] or "—(无)", r["status"] or "?", mark))
        if any(not r["sname"] for r in rows):
            print()
            print("—(无) 的不是 Claude Code（或没登记）：SendMessage 到不了，只能用地址走 hc / herdr。")

    if data["self_index"] is not None:
        print()
        print("你自己排在 #%d。人说「第 N 个」且 N >= %d 时，「含自己数」和「除自己数」指向不同的 session，先问清。"
              % (data["self_index"], data["self_index"]))
    if data["same_tab"]:
        print("「右边/旁边」最可能指同一个 tab 里的：%s" % "、".join(
            "%s（%s）" % (r["address"], r["sname"] or r["kind"] or "?") for r in data["same_tab"]))

    if data["outside"]:
        print()
        print("两套后端之外（ListAgents 里有，屏幕上没有；要发必须由人显式点名）：")
        for r in data["outside"]:
            print("    %-11s %-9s pid=%-7s %s" % (r["sname"], r["status"] or "?", r["pid"] or "?", r["cwd"] or ""))

    if data["machines"]:
        print()
        print("远端机器（上面的表不含它们；SendMessage 到不了，人说「最下面那个」「远程那个」时多半指这里）：")
        for m in data["machines"]:
            print("    %-6s %-14s target=%-14s %s%s" % (
                m["backend"], m["name"] or "?", m["target"] or "?", m.get("state") or "?",
                ("  ⚠️ " + m["error"]) if m.get("error") else ""))
        if not data["remote_checked"]:
            print("    要列它们上面的 agent：roster.py --remote（会 ssh / hc exec 过去，只读）")
        elif data["remote_agents"]:
            print()
            print("    %-6s %-12s %-18s %-22s %-12s %-8s" % ("后端", "机器", "地址", "位置", "kind", "状态"))
            for r in data["remote_agents"]:
                print("    %-6s %-12s %-18s %-22s %-12s %-8s" % (
                    r["backend"], r["machine"], r["address"] or "?", (r["where"] or "")[:22],
                    r["kind"] or "?", r["status"] or "?"))
            print("    远端 herdr 的 pane 号要连机器一起说（远端 w1:p1 ≠ 本机 w1:p1）；hc 的地址自带机器名。")
        else:
            print("    （连过去看了，远端没有可寻址的 terminal/pane）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
