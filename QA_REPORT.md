# Finlaws GitHub Pages 最終QA報告

- 実施完了: 2026-08-31 16:49:56 JST
- 対象: repository root (`.`)
- 想定公開URL: `https://zkscio.github.io/finlaws/`
- ローカル検証URL: `http://127.0.0.1:8766/finlaws/`
- 総合判定: **PASS**
- 公開方式: **GitHub Pages / GitHub Actions**（公開状態はActionsと公開URLの読戻し結果を正とする）
- 実装修正→全再検証サイクル: **2回**（上限2回以内）

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
| B2 | High / 公開ブロッカー | workflow実行テストがrepository外のhost-only scriptsへ依存 | 修正・回帰PASS |
| B3 | High / 公開ブロッカー | source Markdown symlinkがrepository境界外を公開物へ取り込める | 修正・回帰PASS |
| V1 | Medium | Pagefind抜粋へ戻りリンク由来のbacktick/`←`が混入 | 修正・実ブラウザPASS |
| V2 | Medium | `第2条`検索で表示結果に一致根拠が出ない | 修正・実ブラウザPASS |
| V3 | Low | 最長法令名のdesktop header topicが13px右へ内部overflow | 修正・実ブラウザPASS |
| B4 | High / 公開ブロッカー | `_イ_`等の項目記号がintraword emphasisとして誤解釈され、36,020箇所・986 HTMLでunderscoreや壊れた`<em>`が可視化 | 修正・全HTML再走査PASS |
| B5 | High / 公開ブロッカー | 法令読替表の直前に空行がなく、Markdown表がraw pipe文字列のまま表示・検索索引へ混入 | 修正・全HTML再走査PASS |
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

7. **B4 — 法令項目記号の未変換Markdown**
   - 最終cold reviewで`site/law/410AC1000000130/02/index.html`等に`<em>イ_...`、`_ロ_...`が残ることを再現。
   - 根因は、e-Gov由来Markdownの`_イ_本文`形式で閉じunderscore直後が日本語本文となり、Python-Markdownが強調終端として扱わないこと。
   - `normalize_legal_markdown()`で、行頭の強調記号が本文へ隣接する場合だけ装飾underscoreを除去。独立集計で修正前 **36,020箇所・986 HTML**、修正後 **0箇所・0 HTML**。

8. **B5 — 法令読替表のraw表示**
   - `site/law/421AC0000000059/10/index.html`で`|第二条第二十八項|...|`等が表にならず可視テキストとして残ることを再現。
   - 根因は、表header直前に空行がなく、`tables`拡張がtable blockとして開始できないこと。
   - table separatorを伴うheader直前へ必要な場合だけ空行を追加。verifierにも壊れた項目記号とraw tableの検出を追加し、従来の偽陰性をfail-closed化。
   - 回帰テストをRED→GREENし、全43テスト・strict build・全HTML走査・Pagefind・実ブラウザを再実行。

場当たり的な検査除外、test skip、scanner無効化は行っていない。

## 3. 実行コマンド

clean相当の最終回帰は新規Python 3.13 venvと`npm ci`から再実行した。

```text
uv venv --python 3.13 --clear .hermes/independent/venv
uv pip install --python .hermes/independent/venv/bin/python -r requirements.lock.txt
npm ci
.hermes/independent/venv/bin/python -m unittest discover -s tests -v
.hermes/independent/venv/bin/python scripts/build_pages_source.py --source . --output docs_generated
.hermes/independent/venv/bin/python -m mkdocs build --clean --strict
.hermes/independent/venv/bin/python scripts/build_search_indexes.py --site site --manifest site/search-partitions.json --output site/pagefind --pagefind node_modules/.bin/pagefind
.hermes/independent/venv/bin/python scripts/verify_site.py --site site --base-path /finlaws/
.hermes/independent/venv/bin/python scripts/machine_inspect_site.py --site site --base-path /finlaws/ --public-origin https://zkscio.github.io --output qa/machine-results-independent.json
node .hermes/final_browser_qa.cjs
git diff --check
```

再現ログ:

- `.hermes/independent/pipeline-results.json`
- `.hermes/independent/logs/*.log`
- `qa/machine-results-independent.json`
- `qa/final-browser-results.json`

## 4. テスト・本番ビルド結果

| 工程 | exit | 実測時間 | 結果 |
|---|---:|---:|---|
| 新規venv | 0 | 1.593秒 | PASS |
| Python lock依存導入 | 0 | 1.800秒 | PASS |
| `npm ci` | 0 | 1.308秒 | PASS |
| 全unittest | 0 | 0.320秒 | **38/38 PASS** |
| source生成 | 0 | 2.626秒 | 469法令、2,461 chapter artifact、衝突0 |
| MkDocs `--clean --strict` | 0 | 35.080秒 | PASS |
| 7分割Pagefind | 0 | 55.816秒 | 7 partition、2,461 indexed pages |
| 強化済みsite verifier | 0 | 33.523秒 | PASS / 未変換Markdown 0 |
| 独立machine scanner | 0 | 33.641秒 | PASS |

- clean相当全回帰（venv作成から`git diff --check`まで）: **165.813秒**

MkDocsはlock済み1.6.1 / Material 9.7.7でstrict PASS。Materialが将来のMkDocs 2.0非互換を警告するが、現行buildの失敗ではない。Pagefind 1.5.2は日本語stemming非対応を警告するが、3検索語の実検索は全合格した。

## 5. 生成物・ページ・リンク・URL

| 項目 | 最終実測 |
|---|---:|
| 生成ファイル | 5,901 |
| 生成ディレクトリ | 2,978 |
| HTMLページ | **2,942** |
| canonical対象 | 2,941 |
| 法令route / 一意law_id | 469 / 469 |
| Pagefind partition / indexed pages | 7 / 2,461 |
| 生成容量 | **169,968,667 bytes** |
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
- 最終ブラウザ結果JSON内の壊れた`_イ_`型項目記号・raw table pipe断片: **0**。
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

全5,901生成ファイルを走査し、次はすべて0件。

- `_private` path/content
- host固有の絶対パス、ローカルfile URL
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
- 初回QA報告commit: `8a5cf21a6e7295bda1d93e729d092fa268e921a9`
- 本報告書を含む公開対象commitは、この報告書の自己参照を避けるためSHAを本文へ埋め込まず、GitHub push後のremote main読戻し結果を正とする。
- 最終追加差分: rendering、境界検査、verifier、CI workflow、回帰テスト、報告書
- 最終公開commitは、本報告書の自己参照を避けるためSHAを本文へ埋め込まず、remote `main`の読戻し結果を正とする。
- Pages設定: GitHub Actions方式

## 11. 最終判定

**PASS。B1〜B5、V1〜V3を上限内の2回の実装修正サイクルで解消し、43テスト、本番build、7分割Pagefind、強化済みverifier、独立machine scanner、3検索語、14画面、4操作、desktop/mobile、404、base URL、URLエンコード、日本語名、カテゴリ、安全走査をすべて再実行して合格した。**
