#!/usr/bin/env python3
"""A3 表达DNA：英文一手语料统计（Ruffian / Guardian / Aeon / Utne 书摘）。
清洗：去元数据头、> 引用块（含 catch-up 列表与长引文）、抽出引语、推广段、标题、图片说明、脚注编号、问卷条目；
作者口吻指标在去掉引号内文字后计算。"""
import re, json, sys, glob, collections
from pathlib import Path

D = Path(__file__).resolve().parents[2] / 'references' / 'sources' / 'articles'

GENRE = {
    'a3-ruffian-2023-01-25-answer-machines.md': ('R-essay', 'Answer Machines (2023)'),
    'a3-ruffian-2022-12-10-the-struggle-to-be-human.md': ('R-essay', 'The Struggle To Be Human (2022)'),
    'a3-ruffian-2021-01-02-the-problem-with-experts.md': ('R-roundup', 'The problem with experts (2021)'),
    'a3-ruffian-2021-02-13-good-fights.md': ('R-roundup', 'Good fights (2021)'),
    'a3-ruffian-2021-10-02-in-praise-of-sheeple.md': ('R-essay', 'In Praise of Sheeple (2021)'),
    'a3-ruffian-2023-03-25-red-carpet-blues.md': ('R-essay', 'Red Carpet Blues (2023)'),
    'a3-ruffian-2025-03-19-the-surest-way-to-make-an-ai-lie.md': ('R-essay', 'Surest Way To Make an AI Lie (2025)'),
    'a3-ruffian-2025-10-21-why-are-llms-fixated-on-the-number.md': ('R-essay', 'LLMs Fixated On 7 (2025)'),
    'a3-ruffian-2026-08-29-why-introverts-make-the-best-extroverts.md': ('R-essay', 'Introverts/Extroverts (2026)'),
    'a3-ruffian-2026-07-04-notes-on-acquired-taste.md': ('R-essay', 'Notes on Acquired Taste (2026)'),
    'a3-ruffian-2024-06-01-the-renaissance-redux.md': ('R-essay', 'The Renaissance Redux (2024)'),
    'a3-ruffian-2024-02-10-42-reflections-on-the-meaning-of.md': ('R-list', '42 Reflections (2014/2024)'),
    'a3-ruffian-2026-09-12-seven-rules-of-good-conversation-preview.md': ('R-list', 'Seven Rules of Good Conversation (2026, 预览)'),
    'a3-ruffian-2026-01-17-how-not-to-use-ai-preview.md': ('R-list', 'How Not To Use AI (2026, 预览)'),
    'a3-ruffian-2024-01-06-leslies-razors-preview.md': ('R-list', "Leslie's Razors (2024, 预览)"),
    'a3-guardian-2016-04-07-the-sugar-conspiracy.md': ('Longform', 'Guardian: The sugar conspiracy (2016)'),
    'a3-guardian-2017-10-13-scientists-persuading-terrorists.md': ('Longform', 'Guardian: Persuading terrorists (2017)'),
    'a3-aeon-2021-07-12-why-disagreement-is-vital.md': ('Longform', 'Aeon: Why disagreement is vital (2021)'),
    'a3-utne-2014-10-31-curious-intro-excerpt-en.md': ('Book', 'Curious 引言英文原文节选 (2014)'),
}

PROMO = re.compile(r'pre-?order|subscri|paid sub|share this|BUY MY BOOK|Catch-up|tickets|free to read|sign-up|sign up|spread the word|Rattle Bag|book me|Hiring me|HIRING ME|my website|Paid subscriptions|After the jump|God Tier|magic link|marketing department|superspreaders|catch-up', re.I)
CAPTION = re.compile(r'Credit|Photograph|Pic:|via |©|Illustration|CC BY|courtesy|Image', re.I)


def body_paras(fn):
    t = (D / fn).read_text(encoding='utf-8')
    t = t.split('\n---\n', 1)[1] if '\n---\n' in t else t
    t = t.replace('[付费墙：以下内容未获取]', '')
    paras = [p.strip() for p in t.split('\n\n') if p.strip()]
    out = []
    for i, p in enumerate(paras):
        if p.startswith('>') or p.startswith('[抽出引语]') or p.startswith('#') or p == '---':
            continue
        if re.fullmatch(r'\d+', p):
            continue
        if PROMO.search(p) and len(p) < 900:
            continue
        if i < 2 and len(p) < 220 and (CAPTION.search(p) or not re.search(r'[.!?]["”’)]?$', p.strip('* '))):
            continue
        if re.fullmatch(r'[A-Z0-9 ’\'&?!:,.\-*]+', p.strip('* ')):  # 全大写栏目名
            continue
        if fn.startswith('a3-utne') and re.match(r'\d+\. ', p):
            continue
        if fn.startswith('a3-utne') and p.startswith('*The web is easier'):
            continue
        if p.startswith('*Excerpted from'):
            continue
        out.append(p)
    return out


def clean_text(p):
    p = re.sub(r'\*+', '', p)
    p = re.sub(r'\s+', ' ', p)
    return p.strip()


ABBR = r'(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\bvs)(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bU\.S)(?<!\bNo)(?<!\bProf)'


def sentences(text):
    text = re.sub(r'\.{3}|…', ' … ', text)
    parts = re.split(ABBR + r'(?<=[.!?])["”’)]*\s+(?=["“‘(]?[A-Z0-9])', text)
    return [s.strip() for s in parts if len(re.findall(r"[A-Za-z0-9’']+", s)) >= 1]


def words(s):
    return re.findall(r"[A-Za-z0-9]+(?:[’'][A-Za-z]+)?", s)


def strip_quotes(t):
    t = re.sub(r'“[^”]*”', ' ', t)
    t = re.sub(r'"[^"]*"', ' ', t)
    t = re.sub(r"(?<![A-Za-z])‘[^’]{12,}’(?![A-Za-z])", ' ', t)  # 长单引号引语
    return t


FP = r"\b(?:I|I[’']m|I[’']ve|I[’']d|I[’']ll|me|my|myself|mine)\b"
WE = r"\b(?:we|We|us|our|Our|ourselves|we[’']re|We[’']re|we[’']ve|We[’']ve)\b"
YOU = r"\b(?:you|You|your|Your|yourself|you[’']re|You[’']re|you[’']ve|you[’']ll|you[’']d)\b"

HEDGE_1P = ["I think", "I suspect", "I guess", "my guess", "I'm not sure", "I am not sure", "I'm not certain", "I'm less certain",
            "I don't know", "I may be wrong", "I might be wrong", "I doubt", "I wonder", "to my mind", "in my view", "I believe",
            "I suppose", "I'd say", "I'm wary", "I don't think", "I'm less sure", "I'm sceptical", "I'm skeptical", "I'm not convinced"]
HEDGE_GEN = ["perhaps", "maybe", "probably", "possibly", "it seems", "seems to", "seem to", "seemed to", "might", "may", "arguably",
             "sort of", "kind of", "a little", "a bit", "somewhat", "in a sense", "in a way", "to some extent", "up to a point",
             "loosely", "more or less", "tend to", "tends to", "often", "usually", "rarely", "not necessarily", "at least"]
CERTAIN = ["clearly", "obviously", "of course", "certainly", "surely", "undoubtedly", "no doubt", "in fact", "in truth",
           "the truth is", "the point is", "precisely", "exactly", "simply", "never", "always", "must", "definitely",
           "absolutely", "plainly", "indeed", "the fact is", "it is clear", "it's clear", "without doubt", "there is no", "nothing"]
ANALOGY = ["like a ", "like an ", "like the ", "as if", "as though", "akin to", "the equivalent of", "imagine", "think of",
           "analogy", "metaphor", "similar to", "just as", "is like", "it's like", "a kind of", "a sort of"]
COLLOQ = ["OK", "Well,", "you know", "I mean", "frankly", "honestly", "pretty ", "stuff", "guy", "yeah", "Anyway", "So,", "Oh ",
          "Sure", "a lot", "huge", "super", "bloody", "crap", "bullshit", "fuck", "damn", "zip it", "Yes,", "No,", "ahem", "Ooof", "Hey"]
SIGNPOST = ["Here's", "In other words", "That is,", "that is,", "To be clear", "In short", "The point is", "It turns out",
            "As it turns out", "Note that", "Note,", "To put it another way", "Put another way", "on to something", "Having said that",
            "It's not that", "The answer is", "So what", "Why?", "The reason?", "the trouble is", "The trouble",
            "The problem is", "the problem is", "First,", "Second,", "Third,", "One reason", "Another reason", "Then again"]
CONTRAST_START = ["But ", "Yet ", "However", "Still,", "Though ", "Although ", "On the other hand", "Then again", "Even so"]
PRAISE = ["fascinating", "brilliant", "excellent", "terrific", "superb", "wonderful", "lovely", "great", "interesting", "beautiful",
          "remarkable", "striking", "incredible", "amazing", "intriguing", "clever", "smart"]


WB_WORDS = {'may', 'might', 'must', 'never', 'always', 'often', 'usually', 'rarely', 'nothing', 'simply', 'clearly', 'indeed',
            'perhaps', 'maybe', 'probably', 'possibly', 'certainly', 'surely', 'obviously', 'precisely', 'exactly', 'definitely',
            'absolutely', 'plainly', 'undoubtedly', 'arguably', 'somewhat', 'loosely', 'imagine', 'analogy', 'metaphor',
            'frankly', 'honestly', 'stuff', 'guy', 'yeah', 'huge', 'super', 'bloody', 'crap', 'bullshit', 'damn', 'ahem',
            'fascinating', 'brilliant', 'excellent', 'terrific', 'superb', 'wonderful', 'lovely', 'great', 'interesting',
            'beautiful', 'remarkable', 'striking', 'incredible', 'amazing', 'intriguing', 'clever', 'smart'}
CASE_SENS = {'OK', 'So,', 'Sure', 'Yes,', 'No,', 'Hey', 'Oh ', 'Well,', 'Anyway', 'Ooof', 'may'}


def to_pat(ph):
    APO = '\x00'
    s = ph.replace("'", APO).replace('\u2019', APO)
    s = re.escape(s).replace(re.escape(APO), APO).replace(APO, "['\u2019]")
    return s


def cnt(phrases, t, case=False):
    res = {}
    for ph in phrases:
        if ph == 'fuck':
            n = len(re.findall(r'f[u*]ck', t, re.I))
        else:
            body = to_pat(ph)
            if ph in WB_WORDS:
                pat = r'\b' + body + r'\b'
            else:
                pat = r'(?<![A-Za-z])' + body
            flags = 0 if (ph in CASE_SENS or ph[0].isupper()) else re.I
            n = len(re.findall(pat, t, flags))
        if n:
            res[ph] = n
    return res


def stats(paras):
    raw = ' '.join(clean_text(p) for p in paras)
    auth = strip_quotes(raw)
    ss = sentences(raw)
    ss_auth = sentences(auth)
    wl = [len(words(s)) for s in ss]
    nw = len(words(raw))
    nwa = len(words(auth))
    k = nwa / 1000
    q_auth = [s for s in ss_auth if s.rstrip('"”’) ').endswith('?')]
    starts = collections.Counter()
    for s in ss_auth:
        for c in CONTRAST_START:
            if s.startswith(c):
                starts[c.strip()] += 1
    h1 = cnt(HEDGE_1P, auth); hg = cnt(HEDGE_GEN, auth); ce = cnt(CERTAIN, auth); an = cnt(ANALOGY, auth)
    co = cnt(COLLOQ, auth); sp = cnt(SIGNPOST, auth); pr = cnt(PRAISE, auth)
    wl_sorted = sorted(wl)
    return dict(
        words=nw, words_auth=nwa, sents=len(ss),
        avg_wps=round(nw / max(len(ss), 1), 1), median_wps=wl_sorted[len(wl_sorted) // 2] if wl_sorted else 0,
        short_pct=round(sum(1 for x in wl if x <= 8) / max(len(wl), 1) * 100, 1),
        long_pct=round(sum(1 for x in wl if x >= 30) / max(len(wl), 1) * 100, 1),
        q_pct=round(len(q_auth) / max(len(ss_auth), 1) * 100, 1), q_n=len(q_auth),
        fp_pk=round(len(re.findall(FP, auth)) / k, 1), we_pk=round(len(re.findall(WE, auth)) / k, 1),
        you_pk=round(len(re.findall(YOU, auth)) / k, 1),
        h1_pk=round(sum(h1.values()) / k, 2), hg_pk=round(sum(hg.values()) / k, 2), ce_pk=round(sum(ce.values()) / k, 2),
        an_pk=round(sum(an.values()) / k, 2), co_pk=round(sum(co.values()) / k, 2), sp_pk=round(sum(sp.values()) / k, 2),
        paren_pk=round(raw.count('(') / k, 2), dash_pk=round(len(re.findall(r' [-–—] |—', raw)) / k, 2),
        contrast_start_pk=round(sum(starts.values()) / k, 2),
        h1=h1, hg=hg, ce=ce, an=an, co=co, sp=sp, pr=pr, starts=dict(starts),
    )


def main():
    rows = []
    bygenre = collections.defaultdict(list)
    allp = []
    for fn, (g, label) in GENRE.items():
        ps = body_paras(fn)
        st = stats(ps)
        st.update(file=fn, genre=g, label=label)
        rows.append(st)
        bygenre[g] += ps
        allp += ps
    agg = {g: stats(ps) for g, ps in bygenre.items()}
    agg['ALL'] = stats(allp)
    agg['Ruffian'] = stats(bygenre['R-essay'] + bygenre['R-roundup'] + bygenre['R-list'])
    json.dump(dict(rows=rows, agg=agg), sys.stdout, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
