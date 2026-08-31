#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e-Gov公式APIから全文テキストを取得するモジュール"""
import urllib.request, json, re, time

BASE = 'https://laws.e-gov.go.jp/internal-api'
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
      'Content-Type':'application/json',
      'Accept':'application/json, text/plain, */*',
      'Accept-Language':'ja,en-US;q=0.9,en;q=0.8',
      'Origin':'https://laws.e-gov.go.jp',
      'Referer':'https://laws.e-gov.go.jp/',
      'sec-ch-ua':'"Chromium";v="151", "Not A(Brand";v="24", "Google Chrome";v="151"',
      'sec-ch-ua-mobile':'?0',
      'sec-ch-ua-platform':'"macOS"',
      'sec-fetch-dest':'empty',
      'sec-fetch-mode':'cors',
      'sec-fetch-site':'same-origin'}

def post(path, payload, retries=5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE+path, data=json.dumps(payload).encode(), headers=UA, method='POST')
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            if raw[:1] in (b'<', b'\r', b'\n') or raw.lstrip().startswith(b'<!DOCTYPE') or raw.lstrip().startswith(b'<html'):
                raise ValueError(f'HTML bot-block response ({len(raw)} bytes)')
            return json.loads(raw.decode('utf-8'))
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise last

def get_current_revision(law_id):
    """現在施行版の (LawDataId, SubRevision, AmendmentId) を返す"""
    hist = post('/SelectLawRevisionData.json', {'law_id': law_id})
    cur = [h for h in hist['result']['Amendment_History'] if h.get('IsCurrentEnforcement')]
    if not cur:
        raise ValueError(f'法令 {law_id} に現在施行版なし')
    info = cur[0]
    return info['LawDataId'], info['SubRevision'], info.get('AmendmentId')

def get_object_ids(law_id, law_data_id, subrev):
    """制定文・前文・本則・附則を重複なく取得するObjectIdを収集。"""
    toc = post('/SelectLawTocData.json', {'law_data_id':law_data_id, 'subRevision':subrev})
    t = toc['result']['Toc_Data']
    ids = []
    seen = set()
    suppl_container = re.compile(r'^#[0-9A-Z]+-Sp$')

    def add(object_id):
        if object_id not in seen:
            seen.add(object_id)
            ids.append(object_id)

    def walk(o):
        if isinstance(o, dict):
            object_id = str(o.get('-ObjectId', ''))
            xpath = str(o.get('-Xpath', ''))
            if (
                object_id.startswith('#EnactStatement_')
                or xpath.endswith('/Preamble')
                or object_id.startswith('#Mp-')
                or xpath.startswith('/Law/LawBody/Appdx')
                or suppl_container.fullmatch(object_id)
            ):
                add(object_id)
            for k,v in o.items():
                if not k.startswith('-'): walk(v)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(t)
    return ids

def fetch_text(law_id, law_data_id, subrev, object_ids, occasion='2026/08/13'):
    """全条文の公式テキストを取得。返す: [ {Type, ObjectId, text} ]"""
    sel = [i.lstrip('#') for i in object_ids]
    txt = post('/SelectLawTextData.json', {'law_id':law_id,'law_data_id':law_data_id,
                                           'subRevision':subrev,'selTextList':sel,'occasion':occasion})
    arr = txt['result']['searchResult_array']
    out = []
    for item in arr:
        out.append((item['Type'], item['ObjectId'], item['Content']))
    return out

def hydrate_empty_arith_formulas(items, official_formulas):
    """internal APIの空ArithFormulaを公式v2の同一ordinalから補完。"""
    ordinal = 0
    hydrated = 0

    def walk(node):
        nonlocal ordinal, hydrated
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key == 'ArithFormula':
                    if ordinal >= len(official_formulas):
                        raise ValueError('official ArithFormula count is smaller than internal API count')
                    official = official_formulas[ordinal]
                    ordinal += 1
                    if value in (None, '', [], {}) and official:
                        node[key] = {'#text': official}
                        hydrated += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for _item_type, _object_id, content in items:
        walk(content)
    if ordinal != len(official_formulas):
        raise ValueError(
            f'ArithFormula count mismatch: internal={ordinal} official={len(official_formulas)}'
        )
    return hydrated

def hydrate_arith_formulas_from_v2(items, v2_payload):
    """公式v2 Formula列と必ず個数照合し、空internal値だけを補完。"""
    try:
        from . import egov_v2_audit
    except ImportError:
        import egov_v2_audit
    formulas = egov_v2_audit.official_tag_texts(
        v2_payload,
        'ArithFormula',
        include_empty=True,
    )
    return hydrate_empty_arith_formulas(items, formulas)

def extract_sentence_text(node):
    """Paragraph 内の Sentence から #text を抽出（引用リンクは元々含まれない）"""
    texts = []
    def walk(o):
        if isinstance(o, dict):
            if '#text' in o and isinstance(o['#text'], str):
                texts.append(o['#text'])
            for v in o.values():
                if v is not None: walk(v)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(node)
    return ''.join(texts)

def full_text_of_law(law_id):
    """法令全体の公式テキスト（章・条・項 の構造つき）を返す"""
    ld, sub, amend = get_current_revision(law_id)
    ids = get_object_ids(law_id, ld, sub)
    items = fetch_text(law_id, ld, sub, ids)
    try:
        from . import egov_v2_audit
    except ImportError:
        import egov_v2_audit
    payload = egov_v2_audit.fetch_law_data(law_id)
    hydrate_arith_formulas_from_v2(items, payload)
    return items, ld, sub, amend
