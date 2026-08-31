from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from scripts import build_pages_source
except ModuleNotFoundError:
    build_pages_source = None

iter_public_markdown = getattr(build_pages_source, "iter_public_markdown", None)
parse_law_index = getattr(build_pages_source, "parse_law_index", None)
build_site_source = getattr(build_pages_source, "build_site_source", None)
rewrite_internal_links = getattr(build_pages_source, "rewrite_internal_links", None)
rewrite_egov_law_links = getattr(build_pages_source, "rewrite_egov_law_links", None)
search_page_markdown = getattr(build_pages_source, "search_page_markdown", None)


class PublicSourceSelectionTests(unittest.TestCase):
    def test_selects_only_publishable_markdown_and_excludes_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "INDEX.md").write_text("# index", encoding="utf-8-sig")
            public = root / "法律" / "01_資金決済法" / "00_全文.md"
            public.parent.mkdir(parents=True)
            public.write_text("# 資金決済法", encoding="utf-8-sig")
            private = root / "_private" / "secret.md"
            private.parent.mkdir()
            private.write_text("token", encoding="utf-8-sig")
            generated = root / "site" / "leak.md"
            generated.parent.mkdir()
            generated.write_text("generated", encoding="utf-8-sig")

            self.assertIsNotNone(iter_public_markdown, "source selector is not implemented")
            selected = {path.relative_to(root).as_posix() for path in iter_public_markdown(root)}

            self.assertEqual(selected, {"INDEX.md", "法律/01_資金決済法/00_全文.md"})
            self.assertFalse(any("_private" in path for path in selected))

    def test_public_source_iterator_rejects_root_markdown_symlinks(self) -> None:
        selector = iter_public_markdown
        self.assertIsNotNone(selector, "source selector is not implemented")
        assert selector is not None
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "source"
            root.mkdir()
            outside = workspace / "outside.md"
            outside.write_text("QA_PRIVATE_SYMLINK_LEAK", encoding="utf-8-sig")
            root.joinpath("README.md").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symlink|escapes"):
                list(selector(root))


class SourceMarkdownBoundaryTests(unittest.TestCase):
    def test_rejects_fulltext_symlink_that_escapes_the_source_root(self) -> None:
        builder = build_site_source
        self.assertIsNotNone(builder, "site source builder is not implemented")
        assert builder is not None
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "source"
            output = workspace / "docs"
            root.mkdir()
            root.joinpath("INDEX.md").write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 境界試験法 | 法律 | 999AA0000000000 | `法律/01_境界試験法/` |\n",
                encoding="utf-8-sig",
            )
            law_dir = root / "法律" / "01_境界試験法"
            law_dir.mkdir(parents=True)
            outside = workspace / "outside.md"
            outside.write_text(
                "# 境界試験法\n\n> e-Gov 法令検索から公式APIで取得（Law ID: 999AA0000000000）\n",
                encoding="utf-8-sig",
            )
            law_dir.joinpath("00_全文.md").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symlink|escapes"):
                builder(root, output)

    def test_rejects_chapter_symlink_into_private_source_content(self) -> None:
        builder = build_site_source
        self.assertIsNotNone(builder, "site source builder is not implemented")
        assert builder is not None
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "source"
            output = workspace / "docs"
            root.mkdir()
            root.joinpath("INDEX.md").write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 境界試験法 | 法律 | 999AA0000000000 | `法律/01_境界試験法/` |\n",
                encoding="utf-8-sig",
            )
            law_dir = root / "法律" / "01_境界試験法"
            law_dir.mkdir(parents=True)
            law_dir.joinpath("00_全文.md").write_text(
                "# 境界試験法\n\n> e-Gov 法令検索から公式APIで取得（Law ID: 999AA0000000000）\n",
                encoding="utf-8-sig",
            )
            private = root / "_private" / "secret.md"
            private.parent.mkdir()
            private.write_text("## 秘密章\n\nQA_PRIVATE_SYMLINK_LEAK\n", encoding="utf-8-sig")
            law_dir.joinpath("01_第一章.md").symlink_to(private)

            with self.assertRaisesRegex(ValueError, "symlink|escapes"):
                builder(root, output)


class LawIndexParsingTests(unittest.TestCase):
    def test_parses_bom_japanese_index_rows_into_law_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "INDEX.md"
            index.write_text(
                "# index\n\n"
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 資金決済法 | 法律 | 421AC0000000059 | `法律/01_資金決済法/` |\n",
                encoding="utf-8-sig",
            )

            self.assertIsNotNone(parse_law_index, "law index parser is not implemented")
            records = parse_law_index(index)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].number, "01")
            self.assertEqual(records[0].name, "資金決済法")
            self.assertEqual(records[0].category, "法律")
            self.assertEqual(records[0].law_id, "421AC0000000059")
            self.assertEqual(records[0].source_dir.as_posix(), "法律/01_資金決済法")

    def test_parses_extension_rows_with_ext_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "INDEX.md"
            index.write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| ext | 休眠預金活用法律附則第二条第三項命令 | 命令 | 428AC1000000101 | `命令/ext_休眠預金活用法律附則第二条第三項命令/` |\n",
                encoding="utf-8-sig",
            )

            self.assertIsNotNone(parse_law_index, "law index parser is not implemented")
            records = parse_law_index(index)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].number, "ext")
            self.assertEqual(records[0].law_id, "428AC1000000101")

    def test_rejects_unsafe_law_ids_and_source_paths(self) -> None:
        parser = parse_law_index
        self.assertIsNotNone(parser, "law index parser is not implemented")
        assert parser is not None
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "INDEX.md"
            index.write_text(
                "| 01 | 危険な法令 | 法律 | ../../escape | `../../outside/` |\n",
                encoding="utf-8-sig",
            )

            with self.assertRaisesRegex(ValueError, "invalid law_id|unsafe source path"):
                parser(index)

            index.write_text(
                "| 01 | 危険な法令 | 法律 | 421AC0000000059 | `../../outside/` |\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "unsafe source path"):
                parser(index)


class NavigationGenerationTests(unittest.TestCase):
    def test_builds_home_category_law_and_chapter_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            output = Path(tmp) / "docs"
            root.mkdir()
            root.joinpath("INDEX.md").write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 資金決済法 | 法律 | 421AC0000000059 | `法律/01_資金決済法/` |\n",
                encoding="utf-8-sig",
            )
            law_dir = root / "法律" / "01_資金決済法"
            law_dir.mkdir(parents=True)
            law_dir.joinpath("_INDEX.md").write_text(
                "# 資金決済法 — 章インデックス\n\n- `00_全文.md`\n- `01_第一章_総則.md`\n",
                encoding="utf-8-sig",
            )
            law_dir.joinpath("00_全文.md").write_text(
                "# 資金決済に関する法律\n\n"
                "> e-Gov 法令検索から公式APIで取得（Law ID: 421AC0000000059）\n",
                encoding="utf-8-sig",
            )
            law_dir.joinpath("01_第一章_総則.md").write_text(
                '## 第一章 <a href="/law/OTHER">総則</a>\n', encoding="utf-8-sig"
            )

            self.assertIsNotNone(build_site_source, "site source builder is not implemented")
            manifest = build_site_source(root, output)

            expected = {
                "index.md",
                "laws/index.md",
                "disclaimer.md",
                "category/act/index.md",
                "law/421AC0000000059/index.md",
                "law/421AC0000000059/fulltext.md",
                "law/421AC0000000059/01.md",
            }
            generated = {path.relative_to(output).as_posix() for path in output.rglob("*.md")}
            self.assertTrue(expected.issubset(generated))
            self.assertEqual(manifest["laws"], 1)
            self.assertEqual(manifest["chapters"], 2)
            law_landing = output.joinpath("law/421AC0000000059/index.md").read_text(encoding="utf-8-sig")
            self.assertIn('href="https://laws.e-gov.go.jp/law/OTHER"', law_landing)
            self.assertNotIn('href="/law/', law_landing)
            self.assertIn("data-pagefind-body", law_landing)
            self.assertIn("markdown>", law_landing)
            self.assertIn('<aside class="finlaws-source-note" markdown>', law_landing)
            chapter_text = output.joinpath("law/421AC0000000059/01.md").read_text(encoding="utf-8-sig")
            self.assertIn('title: "資金決済法 — 第一章 <a href=', chapter_text)
            self.assertIn('class="finlaws-law-text" markdown>', chapter_text)
            backlink = chapter_text.index("[← 資金決済法の目次]")
            indexed_body = chapter_text.index("data-pagefind-body")
            indexed_body_end = chapter_text.index("</article>", indexed_body)
            source_note = chapter_text.index('<aside class="finlaws-source-note"')
            self.assertLess(backlink, indexed_body, "back navigation must not enter the Pagefind excerpt")
            self.assertLess(indexed_body_end, source_note, "source metadata must not enter the Pagefind excerpt")
            self.assertIn("[資金決済法](../../law/421AC0000000059/index.md)", output.joinpath("category/act/index.md").read_text(encoding="utf-8-sig"))
            home_text = output.joinpath("index.md").read_text(encoding="utf-8-sig")
            self.assertIn("[法令を検索](search/index.md)", home_text)
            self.assertIn('<div class="finlaws-actions" markdown>', home_text)
            self.assertIn("1法令をカテゴリ・法令名・条文全文から探せる", home_text)
            self.assertNotIn("canonical", home_text)
            self.assertTrue(output.joinpath("assets/finlaws.css").is_file())
            self.assertTrue(output.joinpath("assets/finlaws-search.js").is_file())
            self.assertTrue(output.joinpath("assets/finlaws-search.css").is_file())
            search_partitions = json.loads(output.joinpath("search-partitions.json").read_text(encoding="utf-8"))
            self.assertEqual(search_partitions["base_path"], "/finlaws/")
            act_partition = next(item for item in search_partitions["partitions"] if item["name"] == "act")
            self.assertEqual(act_partition["routes"], ["421AC0000000059"])

    def test_rejects_conflicting_laws_when_source_reuses_a_law_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            output = Path(tmp) / "docs"
            root.mkdir()
            root.joinpath("INDEX.md").write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 第一法 | 法律 | 999AA0000000000 | `法律/01_第一法/` |\n"
                "| 02 | 第二法 | 政令 | 999AA0000000000 | `政令/02_第二法/` |\n",
                encoding="utf-8-sig",
            )
            for category, folder, title in (("法律", "01_第一法", "第一法"), ("政令", "02_第二法", "第二法")):
                law_dir = root / category / folder
                law_dir.mkdir(parents=True)
                law_dir.joinpath("_INDEX.md").write_text(f"# {title}\n", encoding="utf-8-sig")
                law_dir.joinpath("00_全文.md").write_text(
                    f"# {title}\n\n> e-Gov 法令検索から公式APIで取得（Law ID: 999AA0000000000）\n",
                    encoding="utf-8-sig",
                )

            self.assertIsNotNone(build_site_source, "site source builder is not implemented")
            with self.assertRaisesRegex(ValueError, "conflicting source content for law_id"):
                build_site_source(root, output)

    def test_preserves_identical_alias_records_for_one_official_law(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            output = Path(tmp) / "docs"
            root.mkdir()
            root.joinpath("INDEX.md").write_text(
                "| # | 法令名 | 種別 | e-Gov law_id | フォルダ |\n"
                "|---|---|---|---|---|\n"
                "| 01 | 正式法令名 | 内閣府令 | 999AA0000000000 | `内閣府令/01_正式法令名/` |\n"
                "| 02 | 正式法令名 | 内閣府令 | 999AA0000000000 | `内閣府令/02_正式法令名/` |\n",
                encoding="utf-8-sig",
            )
            canonical = "# 正式法令名\n\n> e-Gov 法令検索から公式APIで取得（Law ID: 999AA0000000000）\n"
            for folder in ("01_正式法令名", "02_正式法令名"):
                law_dir = root / "内閣府令" / folder
                law_dir.mkdir(parents=True)
                law_dir.joinpath("_INDEX.md").write_text("# 正式法令名\n", encoding="utf-8-sig")
                law_dir.joinpath("00_全文.md").write_text(canonical, encoding="utf-8-sig")

            self.assertIsNotNone(build_site_source, "site source builder is not implemented")
            manifest = build_site_source(root, output)

            self.assertEqual(manifest["laws"], 2)
            self.assertEqual(manifest["url_collisions"], 1)
            self.assertTrue(output.joinpath("law/999AA0000000000/index.md").is_file())
            self.assertTrue(output.joinpath("law/999AA0000000000-02/index.md").is_file())


class InternalLinkTests(unittest.TestCase):
    def test_rewrites_source_chapter_links_to_generated_targets(self) -> None:
        self.assertIsNotNone(rewrite_internal_links, "internal link rewriter is not implemented")
        source = "[総則](01_第一章_総則.md#第一条) / [全文](00_全文.md) / [e-Gov](https://laws.e-gov.go.jp/)"
        mapping = {"01_第一章_総則.md": "01.md", "00_全文.md": "fulltext.md"}

        rewritten = rewrite_internal_links(source, mapping)

        self.assertEqual(
            rewritten,
            "[総則](./01.md#第一条) / [全文](./fulltext.md) / [e-Gov](https://laws.e-gov.go.jp/)",
        )

    def test_rewrites_root_law_references_to_egov(self) -> None:
        self.assertIsNotNone(rewrite_egov_law_links, "e-Gov law link rewriter is not implemented")
        source = (
            '<a href="/law/405AC0000000088">行政手続法</a> / '
            "[会社法](/law/417AC0000000086#Mp-At_1)"
        )

        rewritten = rewrite_egov_law_links(source)

        self.assertIn('href="https://laws.e-gov.go.jp/law/405AC0000000088"', rewritten)
        self.assertIn("(https://laws.e-gov.go.jp/law/417AC0000000086#Mp-At_1)", rewritten)
        self.assertNotIn('href="/law/', rewritten)
        self.assertNotIn("](/law/", rewritten)


class SearchPageTests(unittest.TestCase):
    def test_search_page_loads_partitioned_pagefind_indexes_under_project_base_path(self) -> None:
        self.assertIsNotNone(search_page_markdown, "Pagefind search page is not implemented")

        page = search_page_markdown()

        self.assertIn('id="search"', page)
        self.assertIn("data-finlaws-search", page)
        self.assertIn('data-pagefind-manifest="../pagefind/manifest.json"', page)
        self.assertIn('type="search"', page)
        self.assertIn("data-search-results", page)
        self.assertNotIn("PagefindUI", page)
        self.assertNotIn("algolia", page.lower())


class PagesConfigurationTests(unittest.TestCase):
    def test_mkdocs_uses_github_project_site_url_and_generated_docs(self) -> None:
        config = Path(__file__).parents[1] / "mkdocs.yml"
        self.assertTrue(config.is_file(), "mkdocs.yml is not implemented")
        text = config.read_text(encoding="utf-8-sig")

        self.assertIn("site_url: https://zkscio.github.io/finlaws/", text)
        self.assertIn("docs_dir: docs_generated", text)
        self.assertIn("site_dir: site", text)
        self.assertIn("use_directory_urls: true", text)
        self.assertIn("assets/finlaws-search.css", text)
        self.assertIn("assets/finlaws-search.js", text)

    def test_project_contains_light_theme_404_and_pages_workflow(self) -> None:
        project = Path(__file__).parents[1]
        required = [
            project / "site_assets" / "finlaws.css",
            project / "overrides" / "main.html",
            project / "overrides" / "404.html",
            project / ".github" / "workflows" / "pages.yml",
        ]
        missing = [path.relative_to(project).as_posix() for path in required if not path.is_file()]
        self.assertEqual(missing, [], f"missing site essentials: {missing}")

        workflow = required[-1].read_text(encoding="utf-8")
        self.assertIn("actions/configure-pages", workflow)
        self.assertIn("actions/upload-pages-artifact", workflow)
        self.assertIn("actions/deploy-pages", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("pagefind", workflow)
        self.assertIn("python scripts/build_search_indexes.py", workflow)
        self.assertNotIn("npx pagefind --site site", workflow)

    def test_pages_workflow_hashes_the_committed_python_lockfile_for_pip_cache(self) -> None:
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

        self.assertIn("cache: pip", workflow)
        self.assertIn("cache-dependency-path: requirements.lock.txt", workflow)

    def test_workflow_discovered_tests_do_not_import_host_only_modules(self) -> None:
        project = Path(__file__).parents[1]
        offenders = []
        for test_path in sorted((project / "tests").glob("test_*.py")):
            if test_path == Path(__file__):
                continue
            text = test_path.read_text(encoding="utf-8")
            if 'sys.path.insert(0, "/opt/data/scripts")' in text:
                offenders.append(test_path.name)

        self.assertEqual(offenders, [], f"host-only test imports: {offenders}")

    def test_long_header_topic_is_constrained_inside_the_desktop_viewport(self) -> None:
        css = (Path(__file__).parents[1] / "site_assets" / "finlaws.css").read_text(encoding="utf-8")

        self.assertIn(".md-header__title {\n  min-width: 0;", css)
        self.assertIn(
            '.md-header__topic[data-md-component="header-topic"] {\n  max-width: calc(100% - 1.25rem);',
            css,
        )


if __name__ == "__main__":
    unittest.main()
