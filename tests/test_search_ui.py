from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


class SearchUiCoreTests(unittest.TestCase):
    @staticmethod
    def run_core(expression: str) -> object:
        asset = Path(__file__).parents[1] / "site_assets" / "finlaws-search.js"
        script = (
            f"const core = require({json.dumps(str(asset))});\n"
            f"process.stdout.write(JSON.stringify({expression}));\n"
        )
        completed = subprocess.run(
            ["node"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"search core failed to load: {completed.stderr}")
        return json.loads(completed.stdout)

    def test_normalizes_arabic_article_numbers_to_official_kanji_notation(self) -> None:
        values = self.run_core(
            "['第2条', '第10条', '第21条の2'].map(core.normalizeLegalQuery)"
        )

        self.assertEqual(values, ["第二条", "第十条", "第二十一条の二"])

    def test_removes_navigation_markers_from_the_start_of_display_text(self) -> None:
        values = self.run_core(
            "['¶ 規則', '` ← 資金決済法の目次', '← 法令本文'].map(core.cleanDisplayText)"
        )

        self.assertEqual(values, ["規則", "資金決済法の目次", "法令本文"])


if __name__ == "__main__":
    unittest.main()
