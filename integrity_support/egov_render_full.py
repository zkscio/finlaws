#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e-Gov公式データ→現行md形式の完全レンダラー。

制定文・前文・本則（章/条/トップレベル項）・制定/改正附則と、
Paragraph/Item/Subitem1/Subitem2/Column/Table を処理する。
"""
import html
import re

def clean_inline(s):
    s = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', s, flags=re.DOTALL)
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s).replace('\r','').replace('\n','')

def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]

def collect_text(node):
    parts=[]
    def add_text(value):
        if isinstance(value, str):
            parts.append(clean_inline(value))
        elif isinstance(value, list):
            for item in value:
                add_text(item)
    def walk(o):
        if isinstance(o,dict):
            if '#text' in o:
                add_text(o['#text'])
            for key, value in o.items():
                if key == '#text' or key.startswith('-') or value is None:
                    continue
                if isinstance(value, str):
                    add_text(value)
                else:
                    walk(value)
        elif isinstance(o,list):
            for x in o: walk(x)
    walk(node)
    return ''.join(parts)

def render_table(table_list):
    """Table をMarkdownテーブル化（ヘッダー+セパレータ+行）"""
    if not table_list: return ''
    out=[]
    for t in table_list:
        rows = as_list(t.get('TableRow'))
        if not rows: continue
        all_rows=[]
        for row in rows:
            cells=[]
            for col in as_list(row.get('TableColumn')):
                cells.append(collect_text(col))
            all_rows.append(cells)
        ncols = max(len(r) for r in all_rows) if all_rows else 0
        if ncols==0: continue
        # 1行目をヘッダー、2行目をセパレータ、残りをボディ
        out.append('|' + '|'.join('     ' for _ in range(ncols)) + '|')
        out.append('|' + '|'.join(' --- ' for _ in range(ncols)) + '|')
        for r in all_rows:
            padded = r + ['']*(ncols-len(r))
            out.append('|' + '|'.join(padded) + '|')
    return '\n'.join(out)

def render_sentence_container(node):
    """Sentence/Column/Table を含むノードをレンダリング"""
    if not isinstance(node, dict): return ''
    parts=[]
    if 'Sentence' in node:
        for s in as_list(node['Sentence']):
            parts.append(collect_text(s))
    if 'Column' in node:
        for c in as_list(node['Column']):
            parts.append(collect_text(c))
    if 'Table' in node:
        parts.append(render_table(node['Table']))
    return ''.join(parts)

def render_subitem(sub):
    """Subitem1..Subitem10 を可変深度でレンダリング"""
    title_key = next((key for key in sub if re.fullmatch(r'Subitem\d+Title', key)), '')
    sentence_key = next((key for key in sub if re.fullmatch(r'Subitem\d+Sentence', key)), '')
    title = sub.get(title_key, '') if title_key else ''
    body = render_sentence_container(sub.get(sentence_key, {})) if sentence_key else ''
    out = [f'_{title}_{body}']
    for key, children in sub.items():
        if re.fullmatch(r'Subitem\d+', key):
            for child in as_list(children):
                out.append('\n'+render_subitem(child))
    return ''.join(out)

def render_item(it):
    """1号（Item）をレンダリング"""
    title = it.get('ItemTitle','')
    body = render_sentence_container(it.get('ItemSentence',{}))
    parts=[f'{title}{body}']
    for key, children in it.items():
        if re.fullmatch(r'Subitem\d+', key):
            for child in as_list(children):
                parts.append('\n'+render_subitem(child))
    return ''.join(parts)

def render_paragraph(para, idx):
    body_parts=[]
    if 'ParagraphSentence' in para:
        body_parts.append(render_sentence_container(para['ParagraphSentence']))
    if 'TableStruct' in para:
        # TableStruct: [{Table: [...]}, ...]
        tables = []
        for ts in para['TableStruct']:
            if isinstance(ts, dict) and 'Table' in ts:
                tables.extend(ts['Table'] if isinstance(ts['Table'], list) else [ts['Table']])
        body_parts.append('\n'+render_table(tables)+'\n')
    if 'Item' in para:
        for it in as_list(para['Item']):
            body_parts.append('\n'+render_item(it))
    for key in ('List', 'AmendProvision', 'Class', 'FigStruct', 'StyleStruct'):
        if key in para:
            extra = collect_text(para[key])
            if extra:
                body_parts.append('\n'+extra)
    body=''.join(body_parts)
    if not body: return []
    caption_value=para.get('ParagraphCaption','')
    caption=(clean_inline(caption_value) if isinstance(caption_value,str)
             else collect_text(caption_value))
    caption_line=''
    if caption:
        cap=caption if caption.startswith('（') else f'（{caption}）'
        caption_line=f'\n_{cap}_'
    if idx>0:
        pnum=para.get('ParagraphNum','')
        return [f'{caption_line}\n{pnum}\n\n{body}']
    return [f'{caption_line}\n{body}']

def render_article(content):
    title=content.get('ArticleTitle','')
    caption=content.get('ArticleCaption','')
    lines=[]
    if caption:
        cap = caption if caption.startswith('（') else f'（{caption}）'
        lines.append(f'_{cap}_')
    lines.append(f'{title}')
    if 'Paragraph' in content:
        for idx,para in enumerate(as_list(content['Paragraph'])):
            lines.extend(render_paragraph(para, idx))
    return '\n'.join(lines)

def render_preamble(content):
    lines=['## 前文']
    paragraphs = as_list(content.get('Paragraph')) if isinstance(content, dict) else []
    if paragraphs:
        for idx, para in enumerate(paragraphs):
            lines.extend(render_paragraph(para, idx))
    else:
        text = collect_text(content)
        if text:
            lines.append(text)
    return '\n'.join(lines)

def render_suppl_provision(content):
    label = content.get('SupplProvisionLabel', '附　則')
    lines=[f'## {label}']
    for article in as_list(content.get('Article')):
        lines.append(render_article(article))
    for idx, paragraph in enumerate(as_list(content.get('Paragraph'))):
        lines.extend(render_paragraph(paragraph, idx))
    return '\n'.join(lines)

def render_appendix(content, typ):
    title_keys = (
        f'{typ}Title',
        'AppdxTableTitle',
        'AppdxNoteTitle',
        'AppdxStyleTitle',
        'AppdxFigTitle',
        'AppdxFormatTitle',
    )
    title = next((content.get(key) for key in title_keys if content.get(key)), typ)
    related = content.get('RelatedArticleNum', '')
    excluded = set(title_keys) | {'RelatedArticleNum'}
    body = collect_text({key: value for key, value in content.items() if key not in excluded})
    rendered_title = clean_inline(title) if isinstance(title, str) else collect_text(title)
    lines = [f'## {rendered_title}']
    if related:
        lines.append(clean_inline(related) if isinstance(related, str) else collect_text(related))
    if body:
        lines.append(body)
    return '\n'.join(lines)

def build_law_md(items):
    lines=[]
    loose_paragraph_index=0
    for typ, oid, content in items:
        if typ=='EnactStatement':
            text=collect_text(content)
            if text: lines.append(text)
        elif typ=='Preamble': lines.append(render_preamble(content))
        elif typ=='Part': lines.append(f'## {content.get("PartTitle","")}\n')
        elif typ=='Chapter': lines.append(f'## {content.get("ChapterTitle","")}\n')
        elif typ=='Section': lines.append(f'### {content.get("SectionTitle","")}\n')
        elif typ=='Subsection': lines.append(f'#### {content.get("SubsectionTitle","")}\n')
        elif typ=='Division': lines.append(f'##### {content.get("DivisionTitle","")}\n')
        elif typ=='Article': lines.append(render_article(content))
        elif typ=='Paragraph':
            lines.extend(render_paragraph(content, loose_paragraph_index))
            loose_paragraph_index += 1
        elif typ in ('EnactSupplProvision', 'AmendSupplProvision', 'SupplProvision'):
            lines.append(render_suppl_provision(content))
        elif typ.startswith('Appdx'):
            lines.append(render_appendix(content, typ))
    return '\n'.join(part for part in lines if part).strip() + ('\n' if lines else '')

if __name__=='__main__':
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import egov_api
    law_id=sys.argv[1]; out=sys.argv[2]
    items,ld,sub,amend=egov_api.full_text_of_law(law_id)
    md=build_law_md(items)
    pathlib.Path(out).write_text('\ufeff'+md, encoding='utf-8')
    print(f'生成 {out} ({len(md)}字, {len(items)}項目)')
