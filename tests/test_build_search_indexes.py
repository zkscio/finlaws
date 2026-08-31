from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from scripts import build_search_indexes
except ImportError:
    build_search_indexes = None

stage_partition = getattr(build_search_indexes, "stage_partition", None)
build_partitioned_indexes = getattr(build_search_indexes, "build_partitioned_indexes", None)


class SearchPartitionStagingTests(unittest.TestCase):
    def test_stages_only_selected_law_html_with_original_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            selected = site / "law" / "LAW-A"
            unselected = site / "law" / "LAW-B"
            selected.joinpath("01").mkdir(parents=True)
            selected.joinpath("fulltext").mkdir(parents=True)
            unselected.mkdir(parents=True)
            selected.joinpath("index.html").write_text("<article data-pagefind-body>A landing</article>", encoding="utf-8")
            selected.joinpath("01/index.html").write_text("<article data-pagefind-body>A chapter</article>", encoding="utf-8")
            selected.joinpath("fulltext/index.html").write_text("<article data-pagefind-ignore='all'>A full text</article>", encoding="utf-8")
            unselected.joinpath("index.html").write_text("<article data-pagefind-body>B landing</article>", encoding="utf-8")
            staging = root / "staging"

            self.assertIsNotNone(stage_partition, "partition staging is not implemented")
            count = stage_partition(site, staging, ["LAW-A"])

            self.assertEqual(count, 2)
            self.assertIn("A landing", staging.joinpath("law/LAW-A/index.html").read_text(encoding="utf-8"))
            self.assertIn("A chapter", staging.joinpath("law/LAW-A/01/index.html").read_text(encoding="utf-8"))
            self.assertFalse(staging.joinpath("law/LAW-A/fulltext/index.html").exists())
            self.assertFalse(staging.joinpath("law/LAW-B/index.html").exists())


class PartitionedIndexBuildTests(unittest.TestCase):
    def test_builds_each_partition_and_writes_browser_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            law = site / "law" / "LAW-A"
            law.mkdir(parents=True)
            law.joinpath("index.html").write_text("<article data-pagefind-body>A</article>", encoding="utf-8")
            source_manifest = root / "search-partitions.json"
            source_manifest.write_text(
                json.dumps(
                    {
                        "base_path": "/finlaws/",
                        "partitions": [{"name": "act", "category": "法律", "routes": ["LAW-A"]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            fake_pagefind = root / "fake_pagefind.py"
            fake_pagefind.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "args = sys.argv[1:]\n"
                "site = Path(args[args.index('--site') + 1])\n"
                "output = Path(args[args.index('--output-path') + 1])\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "count = len(list(site.rglob('*.html')))\n"
                "output.joinpath('pagefind.js').write_text('export const pages = %d;' % count, encoding='utf-8')\n",
                encoding="utf-8",
            )

            self.assertIsNotNone(build_partitioned_indexes, "partitioned Pagefind builder is not implemented")
            report = build_partitioned_indexes(
                site,
                source_manifest,
                site / "pagefind",
                ["python3", str(fake_pagefind)],
            )

            self.assertEqual(report["indexed_pages"], 1)
            self.assertTrue(site.joinpath("pagefind/act/pagefind.js").is_file())
            browser_manifest = json.loads(site.joinpath("pagefind/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(browser_manifest["base_path"], "/finlaws/")
            self.assertEqual(browser_manifest["partitions"][0]["bundle"], "act/")
            self.assertEqual(browser_manifest["partitions"][0]["pages"], 1)


if __name__ == "__main__":
    unittest.main()
