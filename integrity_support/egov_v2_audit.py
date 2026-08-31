#!/usr/bin/env python3
"""Independent e-Gov v2 law-body leaf audit.

This module deliberately does not import the internal-API fetcher or Markdown
renderer.  It uses the public v2 generic ``law_full_text`` tree as a separate
oracle and verifies that every official body leaf appears in the generated
Markdown in document order, including repeated captions.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from collections import Counter
from typing import Any

API_ROOT = "https://laws.e-gov.go.jp/api/2/law_data"
UA = "finlaws-v2-leaf-audit/1.0 (+https://github.com/zkscio/finlaws)"
SKIP_SUBTREES = {"LawTitle", "TOC"}
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")
MARKDOWN_SYNTAX = re.compile(r"[#_*`|]")
WHITESPACE = re.compile(r"\s+")


def fetch_law_data(law_id: str, retries: int = 5, timeout: int = 90) -> dict[str, Any]:
    """Fetch one official v2 generic law tree with bounded retries."""
    url = f"{API_ROOT}/{law_id}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or "law_full_text" not in payload:
                raise ValueError(f"{law_id}: missing law_full_text")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    assert last_error is not None
    raise RuntimeError(f"{law_id}: v2 law_data fetch failed: {last_error}") from last_error


def _find_law_body(node: object) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if node.get("tag") == "LawBody":
            return node
        for child in node.get("children", []):
            found = _find_law_body(child)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _find_law_body(child)
            if found is not None:
                return found
    return None


def official_body_leaf_texts(payload: dict[str, Any]) -> list[str]:
    """Return official LawBody string leaves in document order.

    LawTitle is metadata already checked separately, and TOC duplicates the
    normative body, so both subtrees are excluded.  Empty leaves are omitted.
    """
    body = _find_law_body(payload.get("law_full_text"))
    if body is None:
        raise ValueError("official v2 payload has no LawBody")

    leaves: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            text = html.unescape(node).strip()
            if text:
                leaves.append(text)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict) or node.get("tag") in SKIP_SUBTREES:
            return
        for child in node.get("children", []):
            walk(child)

    walk(body)
    return leaves


def official_tag_texts(
    payload: dict[str, Any],
    tag: str,
    include_empty: bool = False,
) -> list[str]:
    """Return concatenated descendant text for each matching generic-XML tag."""
    matches: list[str] = []

    def descendant_text(node: object) -> str:
        if isinstance(node, str):
            return html.unescape(node)
        if isinstance(node, list):
            return "".join(descendant_text(child) for child in node)
        if isinstance(node, dict):
            return "".join(descendant_text(child) for child in node.get("children", []))
        return ""

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("tag") == tag:
                text = descendant_text(node).strip()
                if text or include_empty:
                    matches.append(text)
            for child in node.get("children", []):
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload.get("law_full_text"))
    return matches


def normalize_for_sequence(value: str, markdown: bool = False) -> str:
    """Normalize presentation-only syntax while preserving legal characters."""
    value = html.unescape(value)
    if markdown:
        value = MARKDOWN_LINK.sub(r"\1", value)
        value = HTML_TAG.sub("", value)
        value = MARKDOWN_SYNTAX.sub("", value)
    return WHITESPACE.sub("", value)


def missing_official_leaves(
    official_leaves: list[str],
    local_markdown_body: str,
) -> list[dict[str, int | str]]:
    """Find official leaves absent from or reordered in local Markdown.

    One-character leaves (for example item numerals) are ignored because they
    are too ambiguous for a substring oracle. Repeated leaves are checked by
    occurrence count; unique leaves are additionally checked in document
    order. This prevents one missing repeated caption from stealing a later
    occurrence and causing a cascade of false positives.
    """
    local = normalize_for_sequence(local_markdown_body, markdown=True)
    normalized_leaves = [
        (index, leaf, normalize_for_sequence(leaf))
        for index, leaf in enumerate(official_leaves)
    ]
    normalized_leaves = [item for item in normalized_leaves if len(item[2]) >= 2]
    required = Counter(normalized for _index, _leaf, normalized in normalized_leaves)
    available = {normalized: local.count(normalized) for normalized in required}

    missing: list[dict[str, int | str]] = []
    seen: Counter[str] = Counter()
    for index, leaf, normalized in normalized_leaves:
        seen[normalized] += 1
        if seen[normalized] > available[normalized]:
            missing.append({"index": index, "text": leaf})

    if missing:
        return missing

    cursor = 0
    for index, leaf, normalized in normalized_leaves:
        position = local.find(normalized, cursor)
        if position < 0:
            missing.append({"index": index, "text": leaf, "reason": "out_of_order"})
            break
        cursor = position + len(normalized)
    return missing
