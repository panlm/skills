#!/usr/bin/env python3
"""逐字核对引文：从 stdin 读每行一条引文，在当前目录（references/sources）下所有 .txt/.md 里查找。
用法: cd references/sources && python3 ../../scripts/quote_check.py < quotes.txt
会统一弯引号/破折号/空白再比较。"""
import sys, pathlib, re
root = pathlib.Path('.')
def norm(s):
    s = s.replace('’',"'").replace('‘',"'").replace('“','"').replace('”','"').replace('—','-').replace('–','-')
    s = re.sub(r'\s+', ' ', s)
    return s.lower()
corpus = {}
for p in root.rglob('*'):
    if p.is_file() and p.suffix in ('.txt','.md'):
        try: corpus[str(p)] = norm(p.read_text(encoding='utf-8', errors='ignore'))
        except Exception: pass
qs = [l.strip() for l in sys.stdin if l.strip()]
for q in qs:
    nq = norm(q)
    hits = [k for k,v in corpus.items() if nq in v]
    print(('OK  ' if hits else 'MISS'), q[:70], '->', ', '.join(h.split('/')[-1] for h in hits[:2]))
