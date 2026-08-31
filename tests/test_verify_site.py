from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from scripts import verify_site
except ImportError:
    verify_site = None

find_broken_links = getattr(verify_site, "find_broken_links", None)
find_unrendered_markdown = getattr(verify_site, "find_unrendered_markdown", None)
scan_forbidden_content = getattr(verify_site, "scan_forbidden_content", None)
verify_built_site = getattr(verify_site, "verify_built_site", None)


class InternalLinkVerificationTests(unittest.TestCase):
    def test_reports_missing_internal_target_under_project_base_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            site.joinpath("index.html").write_text(
                '<a href="/finlaws/missing/">missing</a><a href="https://example.com/">external</a>',
                encoding="utf-8",
            )

            self.assertIsNotNone(find_broken_links, "site link verifier is not implemented")
            broken = find_broken_links(site, "/finlaws/")

            self.assertEqual(len(broken), 1)
            self.assertEqual(broken[0][1], "/finlaws/missing/")

    def test_reports_relative_path_that_escapes_site_even_if_target_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            site.mkdir()
            root.joinpath("outside.html").write_text("outside", encoding="utf-8")
            site.joinpath("index.html").write_text('<a href="../outside.html">outside</a>', encoding="utf-8")

            self.assertIsNotNone(find_broken_links, "site link verifier is not implemented")
            broken = find_broken_links(site, "/finlaws/")

            self.assertEqual(broken, [("index.html", "../outside.html")])

    def test_reports_missing_same_page_fragment(self) -> None:
        verifier = find_broken_links
        self.assertIsNotNone(verifier, "site link verifier is not implemented")
        assert verifier is not None
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            site.joinpath("index.html").write_text(
                '<h1 id="present">Home</h1><a href="#missing">missing fragment</a>',
                encoding="utf-8",
            )

            broken = verifier(site, "/finlaws/")

            self.assertEqual(broken, [("index.html", "#missing")])


class RenderedContentTests(unittest.TestCase):
    def test_reports_visible_source_markdown_left_in_html(self) -> None:
        verifier = find_unrendered_markdown
        self.assertIsNotNone(verifier, "rendered-content verifier is not implemented")
        assert verifier is not None
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            site.joinpath("index.html").write_text(
                '<main>[法令を検索](search/index.md){ .md-button }</main>',
                encoding="utf-8",
            )

            findings = verifier(site)

            self.assertEqual(findings, ["index.html"])


class PublicationSafetyTests(unittest.TestCase):
    def test_reports_private_paths_local_paths_and_secret_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            site.joinpath("index.html").write_text(
                "<p>safe</p><p>_private/secret.md</p><p>/opt/data/laws</p>",
                encoding="utf-8",
            )
            site.joinpath("app.js").write_text("const token = 'github_pat_example';", encoding="utf-8")

            self.assertIsNotNone(scan_forbidden_content, "publication safety scanner is not implemented")
            findings = scan_forbidden_content(site)

            markers = {marker for _, marker in findings}
            self.assertEqual(markers, {"_private/", "/opt/data/", "github_pat_"})


class BuiltSiteGateTests(unittest.TestCase):
    def test_requires_404_and_pagefind_assets_before_passing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            site.joinpath("index.html").write_text("<h1>Finlaws</h1>", encoding="utf-8")
            pagefind = site / "pagefind"
            pagefind.joinpath("act").mkdir(parents=True)
            pagefind.joinpath("act/pagefind.js").write_text("safe", encoding="utf-8")
            pagefind.joinpath("manifest.json").write_text(
                '{"base_path":"/finlaws/","partitions":[{"name":"act","bundle":"act/","pages":1}]}',
                encoding="utf-8",
            )

            self.assertIsNotNone(verify_built_site, "built-site verification gate is not implemented")
            missing_404 = verify_built_site(site, "/finlaws/")
            self.assertEqual(missing_404["status"], "fail")
            self.assertIn("missing 404.html", missing_404["errors"])

            site.joinpath("404.html").write_text("<h1>404</h1>", encoding="utf-8")
            passing = verify_built_site(site, "/finlaws/")
            self.assertEqual(passing["status"], "pass")
            self.assertEqual(passing["html_files"], 2)
            self.assertEqual(passing["broken_links"], [])
            self.assertEqual(passing["forbidden_content"], [])


if __name__ == "__main__":
    unittest.main()
