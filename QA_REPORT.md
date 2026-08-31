# Finlaws GitHub Pages 最終QA報告

- 実施完了: 2026-08-31 16:04 JST
- 対象: `/opt/data/finlaws-pages`
- 想定公開URL: `https://zkscio.github.io/finlaws/`
- ローカル検証URL: `http://127.0.0.1:8766/finlaws/`
- 総合判定: **PASS**
- 本番公開・push・Pages有効化・GitHub書き込み: **0件（未実施）**
- 実装修正→全再検証サイクル: **1回**（上限2回以内）

## 1. レビュー範囲

次を精査し、検出事項を重要度別に再現して根因を特定した。

- `qa/baseline-review.md`
- `qa/machine-results.md`
- `qa/visual-results.md`
- 必須4画像および補助画像
- `.github/workflows/pages.yml`
- `scripts/build_pages_source.py`
- `scripts/build_search_indexes.py`
- `scripts/verify_site.py`
- `scripts/machine_inspect_site.py`
- `site_assets/finlaws-search.js`
- `site_assets/finlaws.css`
- 全テスト、MkDocs設定、Pagefind設定、生成サイト全ツリー

検出事項の初期分類:

| ID | 重要度 | 内容 | 最終状態 |
|---|---|---|---|
| B1 | High / 公開ブロッカー | setup-pythonのpip cacheが`requirements.lock.txt`をhashしない | 修正・回帰PASS |
| B2 | High / 公開ブロッカー | workflow実行テストがhost-only `/opt/data/scripts`へ依存 | 修正・回帰PASS |
| B3 | High / 公開ブロッカー | source Markdown symlinkがrepository境界外を公開物へ取り込める | 修正・回帰PASS |
| V1 | Medium | Pagefind抜粋へ戻りリンク由来のbacktick/`←`が混入 | 修正・実ブラウザPASS |
| V2 | Medium | `第2条`検索で表示結果に一致根拠が出ない | 修正・実ブラウザPASS |
| V3 | Low | 最長法令名のdesktop header topicが13px右へ内部overflow | 修正・実ブラウザPASS |
| E1 | Informational | SimpleHTTPのmissing URLは汎用404を返す | 環境差。生成`404.html`は正常 |

## 2. 必要最小限の修正

1. **B1 — clean CIのpip cache**
   - `actions/setup-python`へ`cache-dependency-path: requirements.lock.txt`を追加。
   - exact lockfileをcache keyへ使用する回帰テストを追加。

2. **B2 — repository自己完結テスト**
   - データ整合性回帰に必要な純粋helperを`integrity_support/`へrepository-local化。
   - `tests/test_integrity_pipeline.py`と`tests/test_egov_v2_audit.py`をrepository相対importへ変更。
   - workflow discover対象テストにhost-only importがないことを機械検査。

3. **B3 — source Markdown fail-closed**
   - `00_全文.md`、章Markdown、`iter_public_markdown()`へ共通境界検査を追加。
   - terminal symlinkを拒否し、`resolve(strict=True)`後にsource rootと対象法令/category root配下であることを検証。
   - repository外fulltext symlink、`_private`章symlink、root Markdown symlinkのRED→GREEN回帰を追加。

4. **V1 — 検索抜粋の不要記号**
   - 戻りナビゲーションと出典noteを`data-pagefind-body`の外へ移動し、法令本文だけを索引対象化。
   - 表示層でも抜粋先頭のbacktick/矢印を除去する防御を追加。

5. **V2 — 条番号検索の一致根拠**
   - `第2条`、`第10条`、`第21条の2`等をe-Gov本文表記の`第二条`、`第十条`、`第二十一条の二`へ正規化して検索。
   - Node実行による純粋関数回帰テストを追加。

6. **V3 — 最長header topic**
   - `.md-header__title`へ`min-width: 0`。
   - 1.25remのtransition offsetを持つheader topicを`max-width: calc(100% - 1.25rem)`へ制約。
   - 実測でdocument width **1453→1440px**、header topic right **1453→1428px**。

場当たり的な検査除外、test skip、scanner無効化は行っていない。

## 3. 実行コマンド

clean相当の最終回帰は新規Python 3.13 venvと`npm ci`から実行した。

```text
uv venv --python 3.13 --clear .hermes/final/venv
uv pip install --python .hermes/final/venv/bin/python -r requirements.lock.txt
npm ci
.hermes/final/venv/bin/python -m unittest discover -s tests -v
.hermes/final/venv/bin/python scripts/build_pages_source.py --source . --output docs_generated
.hermes/final/venv/bin/python -m mkdocs build --clean --strict
.hermes/final/venv/bin/python scripts/build_search_indexes.py --site site --manifest site/search-partitions.json --output site/pagefind --pagefind node_modules/.bin/pagefind
.hermes/final/venv/bin/python scripts/verify_site.py --site site --base-path /finlaws/
.hermes/final/venv/bin/python scripts/machine_inspect_site.py --site site --base-path /finlaws/ --public-origin https://zkscio.github.io --output qa/machine-results-final.json
node .hermes/final_browser_qa.cjs
git diff --check
```

再現ログ:

- `.hermes/final/build-metrics.json`
- `.hermes/final/logs/*.log`
- `qa/machine-results-final.json`
- `qa/final-browser-results.json`

## 4. テスト・本番ビルド結果

| 工程 | exit | 実測時間 | 結果 |
|---|---:|---:|---|
| 新規venv | 0 | 0.053秒 | PASS |
| Python lock依存導入 | 0 | 0.825秒 | PASS |
| `npm ci` | 0 | 2.115秒 | PASS / audit脆弱性0 |
| 全unittest | 0 | 0.276秒 | **34/34 PASS** |
| source生成 | 0 | 3.498秒 | 469法令、2,461 chapter artifact、衝突0 |
| MkDocs `--clean --strict` | 0 | 35.631秒 | PASS |
| 7分割Pagefind | 0 | 45.750秒 | 7 partition、2,461 indexed pages |
| 既存site verifier | 0 | 30.252秒 | PASS |
| 独立machine scanner | 0 | 32.599秒 | PASS |

- production pipeline（source生成＋MkDocs＋Pagefind＋verify）: **115.131秒**
- clean相当全回帰（venvからmachine scannerまで）: **150.999秒**

MkDocsはlock済み1.6.1 / Material 9.7.7でstrict PASS。Materialが将来のMkDocs 2.0非互換を警告するが、現行buildの失敗ではない。Pagefind 1.5.2は日本語stemming非対応を警告するが、3検索語の実検索は全合格した。

## 5. 生成物・ページ・リンク・URL

| 項目 | 最終実測 |
|---|---:|
| 生成ファイル | 5,902 |
| 生成ディレクトリ | 2,978 |
| HTMLページ | **2,942** |
| canonical対象 | 2,941 |
| 法令route / 一意law_id | 469 / 469 |
| Pagefind partition / indexed pages | 7 / 2,461 |
| 生成容量 | **169,485,515 bytes** |
| URL参照総数 | 106,519 |
| 内部参照検査 | 96,880 |
| fragment参照検査 | 20,349 |
| broken内部リンク・fragment | **0** |
| percent-encoded参照 | 42（全件解決） |
| raw非ASCII URL | 0 |
| URL構文異常 | 0 |
| base URL / canonical不一致 | 0 |
| U+FFFD | 0 |
| 未変換Markdown | 0 |

`/finlaws/` mountのHTTP検査は**16/16一致**。home、search、全法令、7カテゴリ、代表法令、章、404成果物、manifest、JSが200、存在しないURLが404だった。469日本語法令名、全2,942ページのカテゴリナビゲーション、URLエンコード、base URLを全件検証し不一致0。

## 6. 3検索語の実ブラウザ検証

Chrome 151.0.7922.71、desktop 1440×900で実行。

| 検索語 | 表示件数 | 表示上の一致根拠 | 不要記号 | 選択link | 判定 |
|---|---:|---:|---:|---:|---|
| `資金決済法` | 20 | 13件 | 0 | HTTP 200・本文根拠あり | PASS |
| `電子決済等代行業` | 20 | 17件 | 0 | HTTP 200・本文根拠あり | PASS |
| `第2条`→`第二条` | 20 | 4件 | 0 | HTTP 200・本文に第二条 | PASS |

- 60表示URLはすべて`/finlaws/law/`配下。
- title/excerpt先頭の`¶`・backtick・`←`・`→`: **0**。
- `第2条`は正規化後、結果画面で`第二条`を明示確認できた。
- 検索console error、page error、request failure、通常asset 4xx/5xx: **0**。

## 7. desktop / mobile表示確認

- 画面: **14/14 PASS**
  - home、カテゴリ、最長法令名、第二条を含む条文、検索、カスタム404、missing URL
  - desktop 1440×900 / mobile 390×844
- 操作: **4/4 PASS**
  - home CTA desktop/mobile、法律カテゴリlink、mobile drawer
- 実横スクロール: 0画面
- 可視DOM右端overflow: 0画面
- 最長84文字法令名: desktop header内部overflow 0、mobile H1全文折返し表示
- 文字化け、生Markdown、base逸脱、broken image: 0

必須4画像は最終buildから再撮影した。

| ファイル | 寸法 | bytes | SHA-256 |
|---|---:|---:|---|
| `qa/desktop-home.png` | 1440×900 | 81,189 | `99e6d516ae687582d34012fffb30501efc77f9eef8a5bcadca367e43f8dbf8da` |
| `qa/mobile-home.png` | 390×844 | 44,969 | `8c0a386341201c4ed78b29e47973288e83f5a18b966dc63f0dc3c9ea389693fb` |
| `qa/mobile-law.png` | 390×844 | 68,627 | `240466da340c954a62578453de402f932d03f2eefbb179efcc942be85fa9a47c` |
| `qa/search-results.png` | 1440×900 | 102,304 | `598bc8be2a5ef6c916a740448d075ca603ac508ad4f8e218f03a3cd7c95a5b7c` |

## 8. 公開安全走査

全5,902生成ファイルを走査し、次はすべて0件。

- `_private` path/content
- `/opt/data/`、`file:///`、`/home`、`/Users`、`/tmp`等のlocal path
- private key、GitHub/AWS/Google/Slack/Stripe/OpenAI/Anthropic token形状
- JWT / generic credential代入候補
- `.env`・credential・秘密鍵系ファイル
- source-like file、想定外hidden path、symlink、想定外top-level entry
- UTF-8 decode error、U+FFFD
- 5MiB以上の巨大ファイル、25MiB以上の公開阻害ファイル

`git diff --check`: exit 0。Actionsの固定SHA、最小権限、`persist-credentials: false`、build/deploy権限分離は維持した。

## 9. 残存問題

**公開を阻害する残存問題は0件。**

非ブロッキングの既知事項:

1. MkDocs Materialの将来MkDocs 2.0互換性警告。現行lock版には影響なし。
2. Pagefindの日本語stemming非対応。今回の3検索語は実ブラウザで20件・一致根拠・link 200を確認済み。
3. Python SimpleHTTPはmissing URLで汎用404を返す。生成`site/404.html`自体はdesktop/mobileで正常であり、GitHub Pages用成果物に問題なし。

## 10. git status / commit

- 修正前HEAD: `76d1da6ebc7568c2693d6cf48f20b5a0a3a579aa`
- commit前作業ツリー: 334 status entries（140 D / 91 M / 103 untracked）
- 実装・QA基準commit: `1c777b633510be21859a4f265db51c3a0ea684ca`
- 本報告書を含む公開対象commitは、この報告書の自己参照を避けるためSHAを本文へ埋め込まず、GitHub push後のremote main読戻し結果を正とする。
- 本報告書commit直前の未commit差分: `QA_REPORT.md` 1件のみ
- ローカルcommit数: 2件（実装・QA成果物1件、最終報告書1件）
- push / 外部公開 / Pages有効化 / GitHub書き込み: **未実施**

## 11. 最終判定

**PASS。B1〜B3、V1〜V3を1回の実装修正サイクルで解消し、clean相当34テスト、本番build、7分割Pagefind、既存verifier、独立machine scanner、3検索語、14画面、4操作、desktop/mobile、404、base URL、URLエンコード、日本語名、カテゴリ、安全走査をすべて再実行して合格した。**
