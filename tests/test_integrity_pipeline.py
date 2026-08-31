from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from integrity_support import egov_api
from integrity_support import egov_render_full as renderer
from integrity_support import laws_splitter as splitter


class CompleteObjectSelectionTests(unittest.TestCase):
    def test_selects_enact_statement_main_content_and_suppl_provision_containers(self) -> None:
        toc = {
            "result": {
                "Toc_Data": {
                    "EnactStatement": {"-ObjectId": "#EnactStatement_1"},
                    "MainProvision": {
                        "-ObjectId": "#MainProvision",
                        "Paragraph": [
                            {"-ObjectId": "#Mp-Pr_1"},
                            {"-ObjectId": "#Mp-Pr_2"},
                        ],
                    },
                    "AppdxTable": {
                        "-ObjectId": "#Mpat_1",
                        "-Xpath": "/Law/LawBody/AppdxTable[1]",
                    },
                    "AppdxStyle": {
                        "-ObjectId": "#Mpas_1",
                        "-Xpath": "/Law/LawBody/AppdxStyle[1]",
                    },
                    "SupplProvision": {
                        "-ObjectId": "#316IO0000000363-Sp",
                        "Paragraph": {"-ObjectId": "#316IO0000000363-Sp-Pr_1"},
                    },
                    "AmendSupplProvision": {
                        "-ObjectId": "#AmendSupplProvision",
                        "SupplProvision": [
                            {"-ObjectId": "#415CO0000000117-Sp"},
                            {"-ObjectId": "#417CO0000000366-Sp"},
                        ],
                    },
                }
            }
        }
        with mock.patch.object(egov_api, "post", return_value=toc):
            selected = egov_api.get_object_ids("316IO0000000363", 565062, "1")

        self.assertEqual(
            selected,
            [
                "#EnactStatement_1",
                "#Mp-Pr_1",
                "#Mp-Pr_2",
                "#Mpat_1",
                "#Mpas_1",
                "#316IO0000000363-Sp",
                "#415CO0000000117-Sp",
                "#417CO0000000366-Sp",
            ],
        )

    def test_hydrates_empty_internal_arith_formula_from_official_v2_ordinal(self) -> None:
        items = [
            (
                "AppdxTable",
                "#Mpat_1",
                {
                    "Item": [
                        {
                            "ItemSentence": {
                                "Sentence": [
                                    {"#childs": [{"ArithFormula": []}]},
                                ]
                            }
                        }
                    ]
                },
            )
        ]

        egov_api.hydrate_empty_arith_formulas(items, ["Ｎ×公式算式"])

        content = items[0][2]
        formula = content["Item"][0]["ItemSentence"]["Sentence"][0]["#childs"][0]["ArithFormula"]
        self.assertEqual(formula, {"#text": "Ｎ×公式算式"})

        with self.assertRaisesRegex(ValueError, "count"):
            egov_api.hydrate_arith_formulas_from_v2(items, {"law_full_text": {}})


class CompleteRenderingTests(unittest.TestCase):
    @staticmethod
    def paragraph(text: str, number: str = "", caption: str = "") -> dict[str, object]:
        paragraph: dict[str, object] = {
            "ParagraphNum": number,
            "ParagraphSentence": {
                "Sentence": [{"#text": [text]}],
            },
        }
        if caption:
            paragraph["ParagraphCaption"] = caption
        return paragraph

    def test_renders_enact_statement_top_level_paragraph_and_suppl_provision(self) -> None:
        items = [
            (
                "EnactStatement",
                "#EnactStatement_1",
                {
                    "#text": [
                        '内閣は、<a href="/law/TEST" class="link-disabled">根拠法</a>に基づき、この政令を制定する。'
                    ]
                },
            ),
            ("Paragraph", "#Mp-Pr_1", self.paragraph("本則第一項。")),
            ("Paragraph", "#Mp-Pr_2", self.paragraph("本則第二項。", "２")),
            (
                "EnactSupplProvision",
                "#TEST-Sp",
                {
                    "SupplProvisionLabel": "附　則",
                    "Paragraph": [
                        self.paragraph(
                            "この命令は、公布の日から施行する。",
                            caption="（施行期日）",
                        )
                    ],
                },
            ),
        ]

        rendered = renderer.build_law_md(items)

        self.assertIn("内閣は、根拠法に基づき、この政令を制定する。", rendered)
        self.assertIn("本則第一項。", rendered)
        self.assertIn("２\n\n本則第二項。", rendered)
        self.assertIn("## 附　則", rendered)
        self.assertIn("_（施行期日）_", rendered)
        self.assertIn("この命令は、公布の日から施行する。", rendered)
        self.assertNotIn("<a ", rendered)

    def test_renders_part_and_appendix_table_and_style_content(self) -> None:
        listed_paragraph = self.paragraph("次の算式による。")
        listed_paragraph["List"] = [
            {
                "ListSentence": {
                    "Sentence": [
                        {
                            "#childs": [
                                {"ArithFormula": {"#text": "（額面－発行価額）×年数"}},
                                {"#text": "「認定する。」"},
                            ]
                        }
                    ]
                }
            }
        ]
        items = [
            ("Part", "#Mp-Pt_1", {"PartTitle": "第一編　総則"}),
            ("Paragraph", "#Mp-Pr_1", listed_paragraph),
            (
                "AppdxTable",
                "#Mpat_1",
                {
                    "AppdxTableTitle": "別表第一",
                    "RelatedArticleNum": "（第一条関係）",
                    "TableStruct": [
                        {
                            "Table": [
                                {
                                    "TableRow": [
                                        {
                                            "TableColumn": [
                                                {"#text": "項目"},
                                                {"#text": "公式別表本文"},
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                },
            ),
            (
                "AppdxStyle",
                "#Mpas_1",
                {"AppdxStyleTitle": "別記様式第一号"},
            ),
        ]

        rendered = renderer.build_law_md(items)

        self.assertIn("## 第一編　総則", rendered)
        self.assertIn("（額面－発行価額）×年数", rendered)
        self.assertIn("「認定する。」", rendered)
        self.assertIn("## 別表第一", rendered)
        self.assertIn("（第一条関係）", rendered)
        self.assertIn("公式別表本文", rendered)
        self.assertIn("## 別記様式第一号", rendered)


class CompleteSplittingTests(unittest.TestCase):
    def test_splits_short_law_suppl_provision_and_uses_relative_search_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "01_試験法令.md"
            source.write_text(
                "# 試験法令\n\n"
                "> 出典: https://laws.e-gov.go.jp/law/TEST\n\n"
                "本則本文。\n\n"
                "## 附　則\n\n"
                "この法令は、公布の日から施行する。\n",
                encoding="utf-8-sig",
            )
            previous = splitter.LAWS
            splitter.LAWS = str(root)
            try:
                outdir, _filename, _chapters = splitter.split_one(str(source))
            finally:
                splitter.LAWS = previous

            folder = Path(outdir)
            self.assertTrue((folder / "01_本則.md").is_file())
            self.assertTrue((folder / "99_附則.md").is_file())
            index = (folder / "_INDEX.md").read_text(encoding="utf-8-sig")
            self.assertIn("`99_附則.md`", index)
            self.assertNotIn(str(root), index)
            self.assertNotIn("/opt/data/", index)


if __name__ == "__main__":
    unittest.main()
