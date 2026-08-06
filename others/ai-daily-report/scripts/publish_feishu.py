#!/usr/bin/env python3
"""把日报段落写进当月飞书文档，倒序插在分割线之后。

替代 SKILL.md Step 3 的手工 block 操作：定位/备份/删旧段/插新段/回读校验。
整篇 write 覆盖会撞输出上限被截断(2026-07-07 事故)，所以只 insert 报告日一段。

**先跑 check_coverage.py 并通过，才准跑本脚本。** 本脚本用 --coverage-ok 标记
文件强制这个顺序：核对脚本 exit 0 时才写该文件，本脚本读不到就拒绝执行。

用法:
    python3 check_coverage.py ... && touch /tmp/cov.ok
    python3 publish_feishu.py --report daily.md --doc <document_id> \
        --coverage-ok /tmp/cov.ok --backup /tmp/old.md

凭证从环境变量读，脚本不含也不打印任何 token:
    FEISHU_USER_TOKEN   飞书 user_access_token(docx scope)

退出码:
    0  写入成功且回读校验通过
    2  覆盖核对标记缺失 —— 拒绝写入
    3  配置/网络/结构错误
    4  写入后回读校验失败(内容可能不完整，需人工检查)
"""

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://open.feishu.cn/open-apis/docx/v1/documents"
DIVIDER_TYPE = 22
HEADING2_TYPE = 4
BULLET_TYPE = 12


def die(msg, code=3):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def token():
    t = os.environ.get("FEISHU_USER_TOKEN", "")
    if not t:
        die(
            "缺少环境变量 FEISHU_USER_TOKEN。\n"
            "  取法见 SKILL.md「Step 0b 准备凭证」——user_access_token 只有 2 小时有效期，\n"
            "  先跑本机的 lark refresh 脚本刷新，再从 lark-mcp 的 storageManager 读出来\n"
            "  export 进环境变量。不要写进任何脚本或提交进仓库。"
        )
    return t


def call(method, path, tok, body=None, query=""):
    req = urllib.request.Request(
        f"{API}{path}{query}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            # 飞书大响应走 chunked，直接 read() 会 IncompleteRead —— 分块读到 EOF。
            buf = []
            while True:
                try:
                    chunk = r.read(65536)
                except http.client.IncompleteRead as e:
                    buf.append(e.partial)
                    break
                if not chunk:
                    break
                buf.append(chunk)
            d = json.loads(b"".join(buf))
    except urllib.error.HTTPError as e:
        die(f"{method} {path} HTTP {e.code}: {e.read().decode()[:300]}")
    except Exception as e:
        die(f"{method} {path} 失败: {type(e).__name__}: {e}")
    if d.get("code") != 0:
        if d.get("code") in (99991677, 99991668):
            die(f"飞书 token 无效或过期 (code {d['code']})。刷新 FEISHU_USER_TOKEN 后重试。")
        die(f"{method} {path} 返回 code={d.get('code')} msg={d.get('msg')}")
    return d.get("data", {})


def block_text(b):
    for k in ("text", "heading1", "heading2", "heading3", "bullet", "code", "quote"):
        if b.get(k, {}).get("elements"):
            return "".join(e.get("text_run", {}).get("content", "") for e in b[k]["elements"])
    return ""


def md_to_blocks(md_path):
    """日报 markdown -> 飞书 block payload。加粗前缀转 bold text_run。"""
    try:
        lines = open(md_path, encoding="utf-8").read().splitlines()
    except OSError as e:
        die(f"读不到日报 {md_path}: {e}")
    blocks, heading = [], None
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
            blocks.append({
                "block_type": HEADING2_TYPE,
                "heading2": {"elements": [{"text_run": {"content": heading}}], "style": {}},
            })
        elif line.startswith("- "):
            body = line[2:].strip()
            m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", body, re.S)
            els = (
                [{"text_run": {"content": m.group(1), "text_element_style": {"bold": True}}},
                 {"text_run": {"content": " " + m.group(2)}}]
                if m else [{"text_run": {"content": body}}]
            )
            blocks.append({"block_type": BULLET_TYPE, "bullet": {"elements": els, "style": {}}})
    if not heading:
        die(f"{md_path} 缺少 `## YYYY-MM-DD 周X` 标题行")
    if len(blocks) < 2:
        die(f"{md_path} 只解析出 {len(blocks)} 个 block，至少要标题+1 条 bullet")
    return heading, blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--doc", required=True, help="完整 document_id，禁止用 … 省略")
    ap.add_argument("--coverage-ok", required=True, help="check_coverage.py 通过后创建的标记文件")
    ap.add_argument("--backup", default="/tmp/feishu-old-section.md")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做的操作，不写入")
    args = ap.parse_args()

    if not os.path.exists(args.coverage_ok):
        die(
            f"覆盖核对标记 {args.coverage_ok} 不存在 —— 拒绝写入飞书。\n"
            f"  先跑: python3 check_coverage.py --activity ... --report {args.report} --map ... "
            f"&& touch {args.coverage_ok}",
            code=2,
        )
    if "…" in args.doc or len(args.doc) < 20:
        die(f"document_id 看起来被截断了: {args.doc}")

    tok = token()
    heading, new_blocks = md_to_blocks(args.report)
    print(f"日报段: {heading}  ({len(new_blocks)} block = 1 标题 + {len(new_blocks) - 1} bullet)")

    children = call("GET", f"/{args.doc}/blocks/{args.doc}/children", tok,
                    query="?page_size=500").get("items", [])
    if not children:
        die("文档根节点没有子 block，请人工确认 document_id 是否正确")
    ids = [b["block_id"] for b in children]

    div = next((i for i, b in enumerate(children) if b.get("block_type") == DIVIDER_TYPE), None)
    if div is None:
        die("文档里找不到分割线(block_type=22)，无法确定倒序插入位置")

    # 定位同日旧段: 标题 + 其后连续 bullet
    old_start = next(
        (i for i, b in enumerate(children)
         if b.get("block_type") == HEADING2_TYPE and block_text(b).strip() == heading),
        None,
    )
    if old_start is not None:
        old_end = old_start + 1
        while old_end < len(children) and children[old_end].get("block_type") == BULLET_TYPE:
            old_end += 1
        with open(args.backup, "w", encoding="utf-8") as f:
            for b in children[old_start:old_end]:
                f.write(f"[{b['block_type']}] {b['block_id']}\n{block_text(b)}\n\n")
        print(f"发现同日旧段 {old_end - old_start} 个 block(索引 {old_start}..{old_end - 1})，"
              f"已备份到 {args.backup}")
    else:
        old_end = None
        print("文档里没有同日旧段，直接插入")

    if args.dry_run:
        print(f"[dry-run] 将删除索引 [{old_start},{old_end}) 并在索引 {div + 1} 插入 "
              f"{len(new_blocks)} 个 block")
        return

    if old_start is not None:
        call("DELETE", f"/{args.doc}/blocks/{args.doc}/children/batch_delete", tok,
             {"start_index": old_start, "end_index": old_end})
        print(f"已删除旧段 {old_end - old_start} 个 block")
        # 删除后索引位移，重新定位分割线
        children = call("GET", f"/{args.doc}/blocks/{args.doc}/children", tok,
                        query="?page_size=500").get("items", [])
        div = next((i for i, b in enumerate(children) if b.get("block_type") == DIVIDER_TYPE), None)
        if div is None:
            die("删除旧段后找不到分割线，文档可能已被并发修改，请人工检查")

    data = call("POST", f"/{args.doc}/blocks/{args.doc}/children", tok,
                {"index": div + 1, "children": new_blocks},
                query="?document_revision_id=-1")
    added = len(data.get("children") or [])
    print(f"insert 成功 blocks_added={added}")

    # --- 回读校验: 内容真的在文档里,且 bullet 条数对得上 ---
    after = call("GET", f"/{args.doc}/blocks/{args.doc}/children", tok,
                 query="?page_size=500").get("items", [])
    h = next((i for i, b in enumerate(after)
              if b.get("block_type") == HEADING2_TYPE and block_text(b).strip() == heading), None)
    if h is None:
        print(f"回读校验失败: 文档里找不到标题 {heading}", file=sys.stderr)
        sys.exit(4)
    n = h + 1
    while n < len(after) and after[n].get("block_type") == BULLET_TYPE:
        n += 1
    got, want = n - h - 1, len(new_blocks) - 1
    if got != want:
        print(f"回读校验失败: 期望 {want} 条 bullet，文档里实际 {got} 条", file=sys.stderr)
        sys.exit(4)
    if added != len(new_blocks):
        print(f"回读校验失败: blocks_added={added} != 预期 {len(new_blocks)}", file=sys.stderr)
        sys.exit(4)

    print(f"回读校验通过: 标题在索引 {h}，其下 {got} 条 bullet 与日报一致。")
    print(f"文档: https://my.feishu.cn/docx/{args.doc}")


if __name__ == "__main__":
    main()
