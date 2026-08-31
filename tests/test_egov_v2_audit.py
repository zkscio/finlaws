from __future__ import annotations

import unittest

from integrity_support import egov_v2_audit


class OfficialV2LeafAuditTests(unittest.TestCase):
    def test_detects_a_missing_repeated_paragraph_caption_in_sequence(self) -> None:
        payload = {
            "law_full_text": {
                "tag": "Law",
                "attr": {},
                "children": [
                    {
                        "tag": "LawBody",
                        "attr": {},
                        "children": [
                            {
                                "tag": "LawTitle",
                                "attr": {},
                                "children": ["試験政令"],
                            },
                            {
                                "tag": "SupplProvision",
                                "attr": {},
                                "children": [
                                    {
                                        "tag": "Paragraph",
                                        "attr": {"Num": "1"},
                                        "children": [
                                            {
                                                "tag": "ParagraphCaption",
                                                "attr": {},
                                                "children": ["（施行期日）"],
                                            },
                                            {
                                                "tag": "ParagraphSentence",
                                                "attr": {},
                                                "children": [
                                                    {
                                                        "tag": "Sentence",
                                                        "attr": {},
                                                        "children": ["第一の附則本文。"],
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                    {
                                        "tag": "Paragraph",
                                        "attr": {"Num": "1"},
                                        "children": [
                                            {
                                                "tag": "ParagraphCaption",
                                                "attr": {},
                                                "children": ["（施行期日）"],
                                            },
                                            {
                                                "tag": "ParagraphSentence",
                                                "attr": {},
                                                "children": [
                                                    {
                                                        "tag": "Sentence",
                                                        "attr": {},
                                                        "children": ["第二の附則本文。"],
                                                    }
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        }

        official = egov_v2_audit.official_body_leaf_texts(payload)
        self.assertNotIn("試験政令", official)
        self.assertEqual(official.count("（施行期日）"), 2)
        self.assertEqual(
            egov_v2_audit.official_tag_texts(payload, "ParagraphCaption"),
            ["（施行期日）", "（施行期日）"],
        )

        incomplete = "## 附　則\n_（施行期日）_\n第一の附則本文。\n第二の附則本文。"
        missing = egov_v2_audit.missing_official_leaves(official, incomplete)
        self.assertEqual(missing, [{"index": 2, "text": "（施行期日）"}])

        complete = (
            "## 附　則\n_（施行期日）_\n第一の附則本文。\n"
            "## 附　則\n_（施行期日）_\n第二の附則本文。"
        )
        self.assertEqual(egov_v2_audit.missing_official_leaves(official, complete), [])

        reordered = (
            "## 附　則\n_（施行期日）_\n第二の附則本文。\n"
            "## 附　則\n_（施行期日）_\n第一の附則本文。"
        )
        self.assertEqual(
            egov_v2_audit.missing_official_leaves(official, reordered),
            [{"index": 2, "text": "（施行期日）", "reason": "out_of_order"}],
        )

        misplaced_repeated_caption = (
            "## 附　則\n_（施行期日）_\n_（施行期日）_\n"
            "第一の附則本文。\n第二の附則本文。"
        )
        self.assertEqual(
            egov_v2_audit.missing_official_leaves(official, misplaced_repeated_caption),
            [{"index": 2, "text": "（施行期日）", "reason": "out_of_order"}],
        )


if __name__ == "__main__":
    unittest.main()
