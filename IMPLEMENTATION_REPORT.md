# Finlaws GitHub Pages ローカル実装報告

- 作成日時 (UTC): 2026-08-31T03:09:15Z
- 作業コピー: リポジトリ作業ディレクトリ（ローカル）
- 想定公開URL: `https://zkscio.github.io/finlaws/`
- base path: `/finlaws/`
- Git branch: `main`
- HEAD (既存公開tree): `76d1da6ebc7568c2693d6cf48f20b5a0a3a579aa`
- 本実装の commit / push: **未実施**（明示承認待ち）

## 1. 結論

Finlaws の全公開法令 **473件** を、GitHub Pages プロジェクトサイト `/finlaws/` で配信できる静的ドキュメントサイトとしてローカル実装した。

- MkDocs Material (Light Mode / Mintlify系) + 7カテゴリ分割 Pagefind + custom GitHub Actions workflow
- 全16テスト PASS
- clean build + 機械検証 PASS
- ローカルHTTPでホーム200 / 検索200 / 存在しないURL 404 を確認
- 日本語全文検索（ブラウザ内）で `資金決済法` / `電子決済等代行業` / `第2条` がヒット
- 外部検索API・Algolia・有料キー依存なし
- push / Pages有効化 / 外部公開は実施していない

## 2. アーキテクチャ

| 層 | 採用 | 役割 |
|---|---|---|
| 生成 | `scripts/build_pages_source.py` | INDEX解析、公開選別、法令/章Markdown生成、e-Govリンク正規化 |
| 静的ビルド | MkDocs Material 9.7.7 | HTML化、ナビ、404、Light Mode |
| 検索 | Pagefind 1.5.2（7分割） | カテゴリ単位索引 + ブラウザ横断検索 |
| 検証 | `scripts/verify_site.py` | リンク・禁止内容・404・検索資産・文字化けゲート |
| 配備準備 | `.github/workflows/pages.yml` | テスト→生成→build→索引→検証→Pages artifact |

### 主要URL設計

- ホーム: `/finlaws/`
- 検索: `/finlaws/search/`
- 全法令: `/finlaws/laws/`
- カテゴリ例: `/finlaws/category/act/`
- 法令例: `/finlaws/law/421AC0000000059/`
- 章例: `/finlaws/law/421AC0000000059/01/`
- 404: 存在しないパスは HTTP 404（`404.html` あり）

### 重複 law_id の扱い

ソース INDEX 上で同一 `law_id` を共有する別法令が **8件** ある。欠落させず、最初を `law/{law_id}/`、後続を `law/{law_id}-{suffix}/` の固有 `url_id` で保持した。

- `source_laws`: 473
- `laws`: 473
- `aliases`: 0
- `url_collisions`: 8

### 検索設計

単一 Pagefind 索引は約2GB環境で構築中に失敗（exit 1 / OOM相当）したため、7カテゴリ分割に変更した。

1. `search-partitions.json` にカテゴリ別対象法令を記録
2. `scripts/build_search_indexes.py` が `data-pagefind-body` 付きHTMLのみ stage
3. カテゴリごとに Pagefind 実行
4. 成果物を `site/pagefind/<partition>/` へ集約
5. `site/pagefind/manifest.json` をブラウザと検証が読む
6. `site_assets/finlaws-search.js` が全パーティションを端末内で横断検索

検索クエリは外部へ送らない。

### e-Gov 参照の正規化

原本 Markdown に含まれる root-relative `/law/...` は、GitHub Pages 上では同一ホストの壊れた内部リンクになる。生成時に `https://laws.e-gov.go.jp/law/...` へ書き換え、意味を保持した。

## 3. 実装ファイル

### 追加（未追跡 / 実装成果）

- `mkdocs.yml`
- `.github/workflows/pages.yml`
- `.gitignore`
- `requirements.in` / `requirements.lock.txt`
- `package.json` / `package-lock.json`
- `overrides/main.html` / `overrides/404.html`
- `site_assets/finlaws.css`
- `site_assets/finlaws-search.css`
- `site_assets/finlaws-search.js`
- `scripts/build_pages_source.py`
- `scripts/build_search_indexes.py`
- `scripts/verify_site.py`
- `tests/test_build_pages_source.py`
- `tests/test_build_search_indexes.py`
- `tests/test_verify_site.py`
- `IMPLEMENTATION_REPORT.md`（本ファイル）

### 生成物（.gitignore）

- `docs_generated/` … 生成Markdown
- `site/` … 最終静的サイト
- `.venv/` / `node_modules/`

## 4. 最終実測値

計測時刻 (UTC): 2026-08-31T03:09:15Z

### 4.1 テスト

- コマンド: `.venv/bin/python -m unittest discover -s tests -v`
- 結果: **16 tests OK**
- 所要: **0.395 s**
- exit: **0**

### 4.2 ソース生成

- コマンド: `.venv/bin/python scripts/build_pages_source.py --source . --output docs_generated`
- exit: **0**
- 所要: **2.588 s**
- manifest:

```json
{
  "aliases": 0,
  "chapters": 2497,
  "laws": 473,
  "source_laws": 473,
  "url_collisions": 8
}
```

- `docs_generated` 容量: **91.09 MiB** (95,516,396 bytes)

### 4.3 MkDocs strict clean build

- コマンド: `.venv/bin/mkdocs build --clean --strict`
- exit: **0**
- 所要: **11.114 s**
- HTML: **2,982**
- 法令ディレクトリ: **473**

### 4.4 分割 Pagefind

- コマンド: `.venv/bin/python scripts/build_search_indexes.py --site site --manifest site/search-partitions.json --output site/pagefind --pagefind node_modules/.bin/pagefind`
- exit: **0**
- 所要: **50.823 s**
- indexed_pages: **2497**
- partitions: **7**
- pagefind 容量: **28.57 MiB** (29,953,802 bytes)

| カテゴリ | partition | indexed pages | 容量 |
|---|---|---:|---:|
| 法律 | `act` | 1123 | 10.86 MiB |
| 政令 | `cabinet-order` | 344 | 3.31 MiB |
| 内閣府令 | `cabinet-office-ordinance` | 286 | 3.86 MiB |
| 府省令 | `joint-ministerial-ordinance` | 248 | 5.52 MiB |
| 命令 | `order` | 313 | 2.89 MiB |
| 規則 | `rule` | 177 | 1.57 MiB |
| 省令 | `ministerial-ordinance` | 6 | 573.87 KiB |

注: Pagefind は日本語 stemming 非対応の警告を出すが、完全一致・部分一致の検索は動作する。

### 4.5 サイト検証

- コマンド: `.venv/bin/python scripts/verify_site.py --site site --base-path /finlaws/`
- exit: **0**
- 所要: **14.603 s**
- status: **pass**
- html_files: **2982**
- pagefind_files: **2963**
- pagefind_partitions: **7**
- broken_links: **0**
- forbidden_content: **0**
- forbidden_paths: **0**
- missing_pagefind: **0**
- replacement_characters: **0**
- site_bytes: **177,188,525** (168.98 MiB)

### 4.6 合計時間・容量

| 工程 | 秒 |
|---|---:|
| tests | 0.395 |
| source generation | 2.588 |
| mkdocs | 11.114 |
| pagefind partitions | 50.823 |
| verify | 14.603 |
| build+verify合計（tests除く） | 79.128 |

| 成果物 | 容量 |
|---|---:|
| docs_generated | 91.09 MiB |
| site | 168.98 MiB |
| site/pagefind | 28.57 MiB |

GitHub Pages 上限（artifact 1GB / デプロイ約10分）に対し、site 約 **168.98 MiB** / build+verify 約 **79.1s** で余裕がある。

## 5. HTTP / ブラウザ実測

ローカルサーバ:

- bind: `127.0.0.1:8765`
- document root symlink: `.serve-root/finlaws` → `site`
- base: `http://127.0.0.1:8765/finlaws/`

### 5.1 HTTP status

| URL | status |
|---|---:|
| `/finlaws/` | 200 |
| `/finlaws/search/` | 200 |
| `/finlaws/not-a-page/` | 404 |
| `/finlaws/law/421AC0000000059/` | 200 |
| `/finlaws/law/421AC0000000059/01/` | 200 |
| `/finlaws/404.html` | 200 |
| `/finlaws/pagefind/manifest.json` | 200 |
| `/finlaws/pagefind/act/pagefind.js` ほか全7 partition | 200 |

### 5.2 レイアウト

Puppeteer (Chrome headless) で実測。

| 画面 | viewport | bodyScrollWidth | 横はみ出し |
|---|---:|---:|---|
| ホーム | 1440x900 | 1440 | なし |
| 資金決済法 | 1440x900 | 1440 | なし |
| ホーム | 390x844 | 390 | なし |
| 第一章 総則 | 390x844 | 390 | なし |

### 5.3 日本語検索

検索UIが7 partition の Pagefind を読み込み、結果を統合。

| クエリ | 表示件数 | 上位例 |
|---|---:|---|
| 資金決済法 | 20 | `law/421AC0000000059/01/` 第一章 総則 ほか |
| 電子決済等代行業 | 20 | `law/337CO0000000271/05/` 第五章 特定信用事業電子決済等代行業 ほか |
| 第2条 | 20 | 複数法令の第2条関連章がヒット |

pageErrors: 0

補足: Material 既定の GitHub releases API 呼び出しが `api.github.com/repos/zkscio/finlaws/releases/latest` で 404 になるが、リリース未作成のためでサイト機能には影響しない（stars/version表示の補助のみ）。

## 6. 公開安全性

公開成果物 `site/` に対する機械ゲート結果:

- 非公開ディレクトリ名の混入: 0
- ローカル作業ツリー絶対パスの混入: 0
- 秘密情報形状（GitHub PAT / Slack bot token / private key 形式）: 0
- 壊れ内部リンク: 0
- 置換文字 U+FFFD: 0
- 必須 404.html: あり
- 分割 Pagefind manifest / 各 partition `pagefind.js`: あり

## 7. TDD で直した主な欠陥

1. INDEX の `ext` 行欠落 → 拡張番号を受理
2. 公開成果物の禁止内容スキャン欠落 → verify に追加
3. site 外への相対パストラバーサル → broken 扱い
4. 404 / 検索資産なしでも通る verify → fail-closed 化
5. 重複 law_id 8件の欠落 → 固有 url_id で全473保持
6. 単一 Pagefind OOM → 7分割索引
7. 原本 `/law/...` が Pages 上で壊れる → e-Gov 絶対URL化

## 8. 未実施（意図的）

- git commit
- git push
- GitHub Pages 有効化
- 本番 deploy
- 独立QA（子タスク `t_ab79d44c`）は本報告完了後に解放

## 9. 次アクション（人間 / 独立QA）

1. 独立QAが本報告・diff・clean rebuild・検索・モバイル表示を再検証
2. 合格後のみローカル commit を検討
3. push / Pages 公開は別途の明示承認後

## 10. 再現コマンド

```bash
cd finlaws-pages
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt   # 環境により uv でも可
npm ci
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/build_pages_source.py --source . --output docs_generated
.venv/bin/mkdocs build --clean --strict
.venv/bin/python scripts/build_search_indexes.py \
  --site site \
  --manifest site/search-partitions.json \
  --output site/pagefind \
  --pagefind node_modules/.bin/pagefind
.venv/bin/python scripts/verify_site.py --site site --base-path /finlaws/
mkdir -p .serve-root && ln -sfn ../site .serve-root/finlaws
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory .serve-root
# open http://127.0.0.1:8765/finlaws/
```

## 11. git 状態（実装完了時点）

```
## main...origin/main
?? .github/
?? .gitignore
?? .hermes/
?? .serve-root/
?? mkdocs.yml
?? overrides/
?? package-lock.json
?? package.json
?? pagefind-build.log
?? requirements.in
?? requirements.lock.txt
?? scripts/
?? site_assets/
?? tests/
```

- `git diff --check`: exit 0
- 実装ファイルは未 commit（上記 untracked）
- 生成物 `docs_generated/` / `site/` は `.gitignore` 済み

---

本レポートはローカル実装の完了証跡であり、外部公開承認を意味しない。
