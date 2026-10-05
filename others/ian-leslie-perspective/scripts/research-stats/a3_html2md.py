#!/usr/bin/env python3
"""把 Substack/报刊正文 HTML 转成纯文本 markdown（标准库 html.parser）。"""
import re
from html.parser import HTMLParser
from html import unescape

BLOCK = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'li', 'blockquote', 'figcaption', 'pre', 'div', 'br', 'hr', 'ul', 'ol', 'tr'}
SKIP = {'script', 'style', 'button', 'form', 'svg', 'noscript', 'iframe', 'select', 'nav', 'footer'}


class H2M(HTMLParser):
    def __init__(self, skip_classes=(), exact=False):
        super().__init__(convert_charrefs=True)
        self.exact = exact
        self.out = []
        self.cur = []
        self.skip_depth = 0
        self.stack = []
        self.prefix = ''
        self.bq = 0
        self.skip_classes = skip_classes
        self.in_li = 0
        self.ol_counter = []

    def flush(self):
        t = ''.join(self.cur)
        t = re.sub(r'[ \t\r\f\v]+', ' ', t).strip()
        if t:
            self.out.append(('> ' * self.bq) + self.prefix + t)
        self.cur = []
        self.prefix = ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get('class', '') or ''
        if self.skip_depth:
            if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'source'):
                self.skip_depth += 1
            return
        if tag in SKIP or (any(c in cls.split() for c in self.skip_classes) if self.exact else any(c in cls for c in self.skip_classes)):
            if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'source'):
                self.skip_depth = 1
            return
        if tag in BLOCK:
            self.flush()
        if tag == 'blockquote':
            self.bq += 1
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5'):
            self.prefix = '#' * min(int(tag[1]) + 1, 6) + ' '
        if tag == 'ol':
            self.ol_counter.append(0)
        if tag == 'ul':
            self.ol_counter.append(None)
        if tag == 'li':
            if self.ol_counter and self.ol_counter[-1] is not None:
                self.ol_counter[-1] += 1
                self.prefix = f'{self.ol_counter[-1]}. '
            else:
                self.prefix = '- '
        if tag in ('em', 'i'):
            self.cur.append('*')
        if tag in ('strong', 'b'):
            self.cur.append('**')
        if tag == 'hr':
            self.out.append('---')

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in ('em', 'i'):
            self.cur.append('*')
        if tag in ('strong', 'b'):
            self.cur.append('**')
        if tag in BLOCK:
            self.flush()
        if tag == 'blockquote':
            self.bq = max(0, self.bq - 1)
        if tag in ('ol', 'ul') and self.ol_counter:
            self.ol_counter.pop()

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.cur.append(data)

    def text(self):
        self.flush()
        lines = []
        for l in self.out:
            l = l.replace('****', '').replace('** **', ' ')
            l = re.sub(r'\*\s+\*', ' ', l)
            if l.strip() in ('*', '**', '> '):
                continue
            lines.append(l)
        return '\n\n'.join(lines)


def html2md(html, skip_classes=('subscription-widget', 'subscribe-widget', 'button-wrapper', 'paywall', 'share', 'image-link-expand', 'footnote-anchor'), exact=False):
    p = H2M(skip_classes=skip_classes, exact=exact)
    p.feed(html)
    return p.text()


if __name__ == '__main__':
    import sys
    print(html2md(open(sys.argv[1], encoding='utf-8').read()))
