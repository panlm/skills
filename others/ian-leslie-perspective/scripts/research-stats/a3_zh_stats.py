#!/usr/bin/env python3
"""A3 表达DNA：中译本《好奇心》20 段取样统计。
段 = 某小标题下从第 1 段起累积到 >=800 字（最多 6 段）的连续正文段落；
剔除重复的"抽出引语"段（与相邻段完全重复的短段）、脚注标号 [n]、括号内英文原名。
"""
import re, json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / 'references' / 'sources' / 'books' / 'curious-zh'

def load_body(part):
    lines = [l.strip() for l in (BASE / f'part{part}.txt').read_text(encoding='utf-8').split('\n')]
    if '注释' in lines:
        lines = lines[:lines.index('注释')]
    return [l for l in lines if l]

def is_pullquote(paras, i):
    p = paras[i]
    for j in (i - 1, i + 1):
        if 0 <= j < len(paras) and j != i and len(paras[j]) > len(p) and p in paras[j]:
            return True
    return False

def clean(t):
    t = re.sub(r'\[\d+\]', '', t)
    t = re.sub(r'（[^（）]*[A-Za-z][^（）]*）', '', t)   # 括号内英文原名（译本特征）
    t = re.sub(r'［[^［］]*[A-Za-z][^［］]*］', '', t)
    return t

PUNCT = set('，。！？；：、“”‘’（）《》〈〉【】［］—…·•,.!?;:()"\'-–| 　')

def nchar(t):
    return sum(1 for c in t if not c.isspace() and c not in PUNCT)

def sentences(t):
    parts = re.split(r'(?<=[。！？!?])[”’」]?|……(?=[^”])', t)
    out = []
    for s in re.findall(r'[^。！？!?]+[。！？!?]+[”’」]?', t):
        if nchar(s) >= 2:
            out.append(s)
    tail = re.sub(r'.*[。！？!?][”’」]?', '', t, flags=re.S)
    if nchar(tail) >= 4:
        out.append(tail)
    return out

def strip_quotes(t):
    return re.sub(r'“[^“”]*”', '', t)

# 一条组合正则、非重叠匹配，避免"就像……一样"双计；"好像"兼有"似乎"义，单列不计入
ANALOGY = [r'(?:就像|仿佛|如同|犹如|好比|宛如|(?<![类相])似的|比作|比喻|隐喻|像[^。！？，]{1,25}(?:一样|那样|一般))']
CERTAIN = [r'显然', r'毫无疑问', r'无疑', r'必然', r'肯定', r'毋庸置疑', r'确实', r'不可能', r'必须', r'(?<!不)一定(?=是|会|要|能|得)']
HEDGE = [r'也许', r'或许', r'可能(?!性)', r'大概', r'似乎', r'恐怕', r'未必', r'不一定', r'看起来', r'某种程度', r'一定程度']
CONCEDE = [r'当然', r'事实上', r'其实', r'诚然', r'固然']
TURN = {'但是': r'但是', '但(单字)': r'但(?!是)', '然而': r'然而', '不过': r'不过', '可是': r'可是', '却': r'却'}

def count(pats, t):
    n = 0
    for p in pats:
        n += len(re.findall(p, t))
    # 避免 "不可能" 被 HEDGE 的 "可能" 重复计入
    return n

def stats(text):
    t = clean(text)
    n = nchar(t)
    ss = sentences(t)
    q = [s for s in ss if re.search(r'[？?][”’」]?$', s.strip())]
    q_auth = [s for s in sentences(strip_quotes(t)) if re.search(r'[？?]$', s.strip())]
    hedge_t = re.sub(r'不可能', '', t)
    wo_all = len(re.findall(r'我(?!们)', t))
    wo_auth = len(re.findall(r'我(?!们)', strip_quotes(t)))
    women = len(re.findall(r'我们', strip_quotes(t)))
    ni = len(re.findall(r'你(?!们)', strip_quotes(t))) + len(re.findall(r'你们', strip_quotes(t)))
    turn = {k: len(re.findall(v, t)) for k, v in TURN.items()}
    an = count(ANALOGY, t)
    ce = count(CERTAIN, t)
    he = count(HEDGE, hedge_t)
    co = count(CONCEDE, t)
    haoxiang = len(re.findall(r'好像', t))
    names = len(re.findall(r'[\u4e00-\u9fff]{1,6}[·•][\u4e00-\u9fff]{1,8}', t))
    years = len(re.findall(r'\d{3,4}年', t))
    quotes = re.findall(r'“[^“”]*”', t)
    qchars = sum(nchar(x) for x in quotes)
    attrib = len(re.findall(r'(?:说道|写道|说：|说，|指出|认为|回忆|告诉我)', t))
    k = n / 1000 if n else 1
    return dict(
        chars=n, sents=len(ss), avg_len=round(n / max(len(ss), 1), 1),
        q_ratio=round(len(q) / max(len(ss), 1) * 100, 1), q_n=len(q), q_auth_n=len(q_auth),
        analogy=an, analogy_pk=round(an / k, 2),
        wo_all=wo_all, wo_auth=wo_auth, wo_auth_pk=round(wo_auth / k, 2), women_pk=round(women / k, 2), ni_pk=round(ni / k, 2),
        certain=ce, hedge=he, certain_pk=round(ce / k, 2), hedge_pk=round(he / k, 2),
        turn=turn, turn_pk=round(sum(turn.values()) / k, 2),
        turn3_pk=round((turn['但是'] + turn['然而'] + turn['不过']) / k, 2),
        concede=co, concede_pk=round(co / k, 2), haoxiang=haoxiang,
        names_pk=round(names / k, 2), years_pk=round(years / k, 2),
        quote_share=round(qchars / max(n, 1) * 100, 1), attrib_pk=round(attrib / k, 2),
    )

# (编号, part, 小标题, 取样类型, 是否取该小节末尾)
SAMPLES = [
    ('P01', '0003', '天赋异禀的黑猩猩坎吉', '引言·开篇故事', False),
    ('P02', '0003', '劳埃德的自我救赎', '引言·人物故事', False),
    ('P03', '0003', '消遣性好奇与认识性好奇', '引言·概念论证', False),
    ('P04', '0003', '选择好奇心的理由', '引言·收尾', True),
    ('P05', '0004', '布莱恩与那把手枪的故事', '第1章·开头故事', False),
    ('P06', '0004', '为什么智人是如此具有好奇心的动物', '第1章·论证', False),
    ('P07', '0005', '婴儿大脑之谜', '第2章·开头（现场采访）', False),
    ('P08', '0006', '好奇心的衰减', '第3章·开头（引语开篇）', False),
    ('P09', '0006', '谜题与奥秘的区别', '第3章·概念论证', False),
    ('P10', '0006', '网络对好奇心的挤压', '第3章·论证（互联网）', False),
    ('P11', '0007', '被视为危险之物的时代', '第4章·开头（观念史）', False),
    ('P12', '0008', '好奇对成功的影响力', '第5章·开头（数据）', False),
    ('P13', '0009', '提问改变人生', '第6章·开头故事', False),
    ('P14', '0010', '米特拉的实验', '第7章·开头故事', False),
    ('P15', '0010', '对学习的三大常见误解', '第7章·驳论', False),
    ('P16', '0011', '虚心若愚', '第8章·方法1（对比开篇）', False),
    ('P17', '0011', '询问关键的“为什么”', '第8章·方法4', False),
    ('P18', '0011', '做一个“思想工匠”', '第8章·方法5', False),
    ('P19', '0011', '质疑你的茶匙', '第8章·方法6', False),
    ('P20', '0012', None, '后记·收尾', True),
]

def section_paras(part, heading, tail):
    body = load_body(part)
    if heading is None:
        idx0, idx1 = 1, len(body)
    else:
        idx0 = next(i for i, l in enumerate(body) if l == f'|{heading}|') + 1
        idx1 = next((i for i in range(idx0, len(body)) if body[i].startswith('|') and body[i].endswith('|')), len(body))
    paras = body[idx0:idx1]
    keep = [(idx0 + i, p) for i, p in enumerate(paras) if not is_pullquote(paras, i)]
    if tail:
        keep = keep[::-1]
    chosen, total = [], 0
    for li, p in keep:
        chosen.append((li, p))
        total += nchar(clean(p))
        if total >= 800 or len(chosen) >= 6:
            break
    if tail:
        chosen = chosen[::-1]
    return chosen

def main():
    rows = []
    alltext = []
    for sid, part, heading, kind, tail in SAMPLES:
        ch = section_paras(part, heading, tail)
        text = '\n'.join(p for _, p in ch)
        alltext.append(text)
        st = stats(text)
        st.update(id=sid, part=part, heading=heading or '后记', kind=kind,
                  paras=f'{ch[0][0] + 1}-{ch[-1][0] + 1}', head=clean(ch[0][1])[:28])
        rows.append(st)
    # 基线：全书正文（引言~后记，剔除抽出引语）
    base_text = []
    for part in ['0003', '0004', '0005', '0006', '0007', '0008', '0009', '0010', '0011', '0012']:
        body = load_body(part)
        paras = [p for p in body if not (p.startswith('|') and p.endswith('|'))]
        base_text += [p for i, p in enumerate(paras) if not is_pullquote(paras, i)]
    agg = stats('\n'.join(alltext))
    base = stats('\n'.join(base_text))
    json.dump(dict(rows=rows, agg=agg, base=base), sys.stdout, ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
