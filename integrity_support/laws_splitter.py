#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laws_splitter.py — e-Gov法令原文を「章ごと」に分割し、各法令フォルダを作る。
- 形式A(8法令): 「## 第X章　…」のMarkdown見出し形式
- 形式B(金商法): 行頭「第X章　…」の平文形式
出力: laws/<法令フォルダ>/_全文.md + 各章.md + _INDEX.md
全ファイルは BOM付きUTF-8 (utf-8-sig)。
使い方: python3 laws_splitter.py [法令ファイル.md ...]   (省略時は laws/ の 0*.md 全部)
"""
import os, re, sys, glob, datetime

LAWS = os.environ.get('FINLAWS_SOURCE', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENC = 'utf-8-sig'
SRC_URL = 'https://laws.e-gov.go.jp/'

CH_A = re.compile(r'^(?:##|###)\s*((?:第[一二三四五六七八九十百]+編[^\n]*|第[一二三四五六七八九十百]+章(?:の[一二三四五六七八九十百]+)*[^\n]*|附　?則[^\n]*))')
# 形式Bの章見出し行: 行頭「第X章　…」または「第X章のY　…」で、リンク[]で始まらない短い行
CH_B = re.compile(r'^第[一二三四五六七八九十百]+章(?:の[一二三四五六七八九十百]+)*　[^\n\[\]]{1,40}$')

def read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw.decode('utf-8')
    return raw.decode('utf-8')

def write_text(path, text):
    with open(path, 'w', encoding=ENC, newline='\n') as f:
        f.write(text)

def detect_chapters(lines, fname):
    """返す: [(見出し, 開始行idx, 形式)]。編がある法令は編単位、なければ章単位。附則は先頭1件のみ記録。"""
    chaps = []
    fusoku_seen = False
    hen = re.compile(r'^##\s*(第[一二三四五六七八九十百]+編[^\n]*)')
    # 編が1つでもあるか
    has_hen = any(hen.match(ln) for ln in lines)
    for i, ln in enumerate(lines):
        # 附則は通常章より先に判定し、最初の附則以降を99_附則.mdへ統合する。
        mf = FUSOKU.match(ln)
        if mf and not ln.startswith('['):
            if not fusoku_seen:
                chaps.append((f'附則{i}', i, 'F'))
                fusoku_seen = True
            continue
        if has_hen:
            m = hen.match(ln)
            if m:
                chaps.append((m.group(1), i, 'A'))
                continue
        else:
            m = CH_A.match(ln)
            if m:
                chaps.append((m.group(1), i, 'A'))
                continue
        m2 = CH_B.match(ln)
        if m2 and '章' in ln:
            chaps.append((ln, i, 'B'))
            continue
    return chaps

def find_title_and_toc(lines):
    """タイトル行と目次セクションの範囲を探す"""
    title = ''
    toc_start = None
    toc_end = None
    for i, ln in enumerate(lines):
        if ln.startswith('# ') and not ln.startswith('## '):
            if not title:
                title = ln[2:].strip()
        if re.match(r'^##?\s*目次', ln):
            toc_start = i
        elif toc_start is not None and (re.match(r'^##\s*第', ln) or re.match(r'^第[一二三四五六七八九十百]+章　', ln)):
            toc_end = i
            break
    return title, toc_start, toc_end

def clean_fname(name):
    """章名から安全なファイル名を生成"""
    s = name.replace('　', '_').replace(' ', '_')
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    return s

SEC_A = re.compile(r'^###\s*(第[一二三四五六七八九十百]+節[^\n]*)')
SEC_B = re.compile(r'^第[一二三四五六七八九十百]+節　[^\n\[\]]{1,60}$')
KOU_B = re.compile(r'^第[一二三四五六七八九十百]+款　[^\n\[\]]{1,60}$')
FUSOKU = re.compile(r'^(?:##\s*)?(附　?則|_附　?則[^_]*_)[^\n]*')  # 附則ブロック開始
# これより大きい章は節/款まで分割する
SECTION_SPLIT_THRESHOLD = 1200

def split_sections(lines, fname):
    """大きな章を節/款で再分割。返す: [(見出し, 開始idx)] 形式A/B両対応"""
    secs = []
    for i, ln in enumerate(lines):
        m = SEC_A.match(ln)
        if m:
            secs.append((m.group(1), i, 'A'))
            continue
        m2 = SEC_B.match(ln)
        if m2:
            secs.append((ln, i, 'B'))
            continue
        m3 = KOU_B.match(ln)
        if m3:
            secs.append((ln, i, 'K'))
    return secs

def write_units(outdir, stem, lines, units, prefix, is_toc=False):
    """units: [(見出し, 開始idx, 形式)]。prefix 例:'c'章 's'節。先頭は前文。"""
    # 先頭 (最初の見出しまで) = 前文/通則
    first = units[0][1] if units else len(lines)
    head = lines[:first]
    if head:
        tag = '00_序章・目次' if is_toc else '00_通則・総則'
        write_text(os.path.join(outdir, f'{prefix}_前文.md' if False else f'{tag}.md'), '\n'.join(head).strip() + '\n')
    if not units:
        return
    for n, (name, start, fmt) in enumerate(units, 1):
        end = units[n][1] if n < len(units) else len(lines)
        body = lines[start:end]
        if not '\n'.join(body).strip():
            continue
        fo = f'{prefix}_{n:02d}_{clean_fname(name)}.md'
        write_text(os.path.join(outdir, fo), '\n'.join(body).strip() + '\n')

def split_one(path):
    fname = os.path.basename(path)
    stem = os.path.splitext(fname)[0]
    lines = read_text(path).split('\n')
    while lines and lines[-1] == '':
        lines.pop()

    title, toc_start, toc_end = find_title_and_toc(lines)
    chaps = detect_chapters(lines, fname)

    outdir = os.path.join(LAWS, stem)
    os.makedirs(outdir, exist_ok=True)
    for old in glob.glob(os.path.join(outdir, '*')):
        if os.path.basename(old) in ('_全文.md', '_INDEX.md'):
            continue
        if os.path.isfile(old):
            os.remove(old)

    # 章見出しが一切ない（短い法令）→ 全文を 01_本則.md に
    if not chaps:
        write_text(os.path.join(outdir, '01_本則.md'), '\n'.join(lines).strip() + '\n')
        idx = [f'# {stem} — 章インデックス', '',
               f'> 原文: `{fname}`（e-Gov 現在施行版）。BOM付きUTF-8。',
               '> 検索: `grep -rn "第X条" .`', '',
               '| 章 | ファイル | 行数 |',
               '|---|--------|-----|',
               f'| 本則 | `01_本則.md` | {len(lines)} |']
        write_text(os.path.join(outdir, '_INDEX.md'), '\n'.join(idx) + '\n')
        print(f'  [OK] 01_本則.md ({len(lines)}行) ※章見出しなし')
        return outdir, fname, []

    # 0. 序章・目次
    first_chap_idx = chaps[0][1]
    header = lines[:first_chap_idx]

    # 章見出しが附則のみ（本則に章がない）場合 → 本則を01_本則.mdにまとめる
    non_fusoku = [c for c in chaps if c[2] != 'F']
    if not non_fusoku:
        # 本文 = 冒頭（メタ含む）から附則開始まで
        honbun = lines[:first_chap_idx]
        if '\n'.join(honbun).strip():
            write_text(os.path.join(outdir, '01_本則.md'), '\n'.join(honbun).strip() + '\n')
            print(f'  [OK] 01_本則.md ({len(honbun)}行)')
        # 附則を処理
        for name, start, fmt in chaps:
            if fmt != 'F':
                continue
            end = len(lines)
            body = lines[start:end]
            write_text(os.path.join(outdir, '99_附則.md'), '\n'.join(body).strip() + '\n')
            print(f'  [OK] 99_附則.md ({len(body)}行)')
        # INDEX
        idx = [f'# {stem} — 章インデックス', '',
               f'> 原文: `{fname}`（e-Gov 現在施行版）。BOM付きUTF-8。',
               '> 検索: `grep -rn "第X条" .`', '']
        idx.append('| 章 | ファイル | 行数 |')
        idx.append('|---|--------|-----|')
        idx.append('| 本則 | `01_本則.md` | - |')
        idx.append('| 附則 | `99_附則.md` | - |')
        write_text(os.path.join(outdir, '_INDEX.md'), '\n'.join(idx) + '\n')
        return outdir, fname, []

    # 通常: 序章・目次
    write_text(os.path.join(outdir, '00_序章・目次.md'), '\n'.join(header).strip() + '\n')

    # 各章
    chap_files = []
    for n, (name, start, fmt) in enumerate(chaps, 1):
        end = chaps[n][1] if n < len(chaps) else len(lines)
        body = lines[start:end]
        body_str = '\n'.join(body).strip()
        if not body_str:
            continue
        # 附則ブロックは専用扱い
        if fmt == 'F':
            base = f'99_附則'
            write_text(os.path.join(outdir, f'{base}.md'), body_str + '\n')
            chap_files.append(('附則', f'{base}.md', len(body), '附則'))
            print(f'  [OK] {base}.md ({len(body)}行)')
            continue
        base = f'{n:02d}_{clean_fname(name)}'
        # 大きい章は節/款で再分割
        secs = split_sections(body, fname)
        if len(body) >= SECTION_SPLIT_THRESHOLD and secs:
            fname_out = f'{base}.md'  # 章ファイル(通則含む全体)は残さない
            os.makedirs(outdir, exist_ok=True)
            write_units(outdir, stem, body, secs, prefix=base, is_toc=False)
            nsec = len(secs) + 1
            chap_files.append((name, f'{base}/**', len(body), '節分割'))
            print(f'  [OK] {base}/ — {nsec}単位に節分割 ({len(body)}行)')
            # 章レベルの _INDEX に反映するため個別INDEXを書く
            sub_idx = [f'# {name}', '', '| # | 節/款 | ファイル |', '|---|------|--------|']
            sub_idx.append('| 前文 | 通則・総則 | `00_通則・総則.md` |')
            for sn, (sname, sstart, sfmt) in enumerate(secs, 1):
                sub_idx.append(f'| {sn} | {sname} | `{base}_{sn:02d}_{clean_fname(sname)}.md` |')
            write_text(os.path.join(outdir, f'{base}._INDEX.md'), '\n'.join(sub_idx) + '\n')
        else:
            write_text(os.path.join(outdir, f'{base}.md'), body_str + '\n')
            chap_files.append((name, f'{base}.md', len(body), ''))
            print(f'  [OK] {base}.md ({len(body)}行)')

    # _INDEX.md
    idx = [f'# {stem} — 章インデックス', '',
           f'> 原文: `{fname}`（e-Gov 現在施行版）。BOM付きUTF-8。',
           '> 検索: `grep -rn "第X条" .` または読みたい章を直接開く。', '']
    idx.append('| # | 章 | ファイル | 行数 | 備考 |')
    idx.append('|---|----|--------|-----|------|')
    for n, (name, fo, nl, note) in enumerate(chap_files, 1):
        idx.append(f'| {n} | {name} | `{fo}` | {nl} | {note} |')
    write_text(os.path.join(outdir, '_INDEX.md'), '\n'.join(idx) + '\n')
    return outdir, fname, chap_files

def gen_master_index():
    """laws/ 直下の全法令の章一覧から INDEX.md を生成"""
    rows = []
    for d in sorted(glob.glob(os.path.join(LAWS, '[0-9]*_*/')) + glob.glob(os.path.join(LAWS, 'ext_*_*/'))):
        stem = os.path.basename(d.rstrip('/'))
        idxf = os.path.join(d, '_INDEX.md')
        if not os.path.exists(idxf):
            continue
        name = stem.split('_', 1)[1] if '_' in stem else stem
        # 章一覧を読む
        chap_lines = []
        in_table = False
        for ln in open(idxf, encoding='utf-8-sig'):
            if ln.startswith('| # |'):
                in_table = True
                continue
            if in_table:
                if ln.startswith('|') and not ln.startswith('|---'):
                    chap_lines.append(ln.strip())
                elif not ln.startswith('|'):
                    in_table = False
        rows.append((stem, name, chap_lines))
    # マスターINDEX書く
    idx = ['# laws/ 法令原文インデックス', '',
           '> e-Gov 現在施行版を章/節/款/附則単位に分割。全ファイル BOM付きUTF-8。',
           '> 検索: `grep -rn "検索語" laws/` ／ 条文引く: `grep -rn "第2条" laws/01_資金決済法/`', '']
    for stem, name, chaps in rows:
        idx.append(f'## {name}  `{stem}/`')
        idx.append('')
        idx.append('| 章 | ファイル | 行数 | 備考 |')
        idx.append('|---|--------|-----|------|')
        idx.append('| 序章・目次 | `00_序章・目次.md` | - | タイトル+目次 |')
        for c in chaps:
            # 既に `| n | 章 | ファイル | 行 | 備考 |` 形式なのでそのまま
            parts = c.strip().strip('|').split('|')
            # [' n ', ' 章 ', ' ファイル ', ' 行 ', ' 備考 '] → 各要素をトリム
            if len(parts) == 5:
                n, ch, fo, nl, note = [p.strip() for p in parts]
                fo = fo.strip('`')
                idx.append(f'| {n} | {ch} | `{fo}` | {nl} | {note} |')
        idx.append('')
    write_text(os.path.join(LAWS, 'INDEX.md'), '\n'.join(idx) + '\n')
    print(f'[INDEX] laws/INDEX.md 生成 ({len(rows)}法令)')

def main():
    targets = sys.argv[1:]
    if not targets:
        targets = [t for t in sorted(glob.glob(os.path.join(LAWS, '*.md')))
                   if os.path.basename(t) not in ('INDEX.md', 'README.md')]
    print(f'=== laws 章分割 ===')
    results = []
    for t in targets:
        t = os.path.join(LAWS, t) if not os.path.isabs(t) else t
        if not os.path.exists(t):
            print(f'  [MISS] {t}')
            continue
        print(f'[{os.path.basename(t)}]')
        r = split_one(t)
        if r:
            results.append(r)
    gen_master_index()
    print(f'=== 完了: {len(results)}法令 ===')
    if results:
        print('')
        print('新法令を追加するには:')
        print('  1) e-Gov (https://laws.e-gov.go.jp/) から条文全文を取得し')
        print('     repository rootへ10_法令名.mdとして保存 (BOM付きUTF-8)')
        print('  2) python3 integrity_support/laws_splitter.py 10_法令名.md')
        print('  3) 章/節/附則に自動分割され、laws/INDEX.md が更新される')

if __name__ == '__main__':
    main()
