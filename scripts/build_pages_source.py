from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ALLOWED_CATEGORIES = ("法律", "政令", "内閣府令", "府省令", "命令", "規則", "省令")
ROOT_MARKDOWN = ("README.md", "INDEX.md", "COVERAGE.md", "CHANGELOG.md")
CATEGORY_SLUGS = {
    "法律": "act",
    "政令": "cabinet-order",
    "内閣府令": "cabinet-office-ordinance",
    "府省令": "joint-ministerial-ordinance",
    "命令": "order",
    "規則": "rule",
    "省令": "ministerial-ordinance",
}
SNAPSHOT_DATE = "2026-08-31"
LAW_ID_PATTERN = re.compile(r"[0-9A-Z]{15}")


@dataclass(frozen=True)
class LawRecord:
    number: str
    name: str
    category: str
    law_id: str
    source_dir: Path
    url_id: str = ""


def _validate_source_markdown(path: Path, source_root: Path, allowed_root: Path) -> Path:
    """Fail closed when a publishable Markdown source crosses a trust boundary."""
    if path.is_symlink():
        raise ValueError(f"source Markdown symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    source_root = source_root.resolve()
    allowed_root = allowed_root.resolve()
    if not resolved.is_relative_to(source_root) or not resolved.is_relative_to(allowed_root):
        raise ValueError(f"source Markdown escapes allowed root: {path}")
    if not resolved.is_file():
        raise FileNotFoundError(f"missing source Markdown: {path}")
    return resolved


def iter_public_markdown(source_root: Path) -> Iterator[Path]:
    """Yield only source Markdown that is eligible for publication."""
    source_root = source_root.resolve()
    for name in ROOT_MARKDOWN:
        candidate = source_root / name
        if candidate.is_file() or candidate.is_symlink():
            _validate_source_markdown(candidate, source_root, source_root)
            yield candidate

    for category in ALLOWED_CATEGORIES:
        category_root = source_root / category
        if not category_root.is_dir():
            continue
        for path in sorted(category_root.rglob("*.md")):
            relative = path.relative_to(source_root)
            if any(part == "_private" or part.startswith(".") for part in relative.parts):
                continue
            _validate_source_markdown(path, source_root, category_root)
            yield path


def parse_law_index(index_path: Path) -> list[LawRecord]:
    """Parse the canonical law table from the BOM-safe root INDEX.md."""
    records: list[LawRecord] = []
    for line in index_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("|"):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) != 5 or columns[2] not in ALLOWED_CATEGORIES:
            continue
        number, name, category, law_id, source = columns
        source = source.strip("`").rstrip("/")
        if not re.fullmatch(r"(?:\d+|ext)", number) or not law_id or not source:
            continue
        source_path = Path(source)
        if not LAW_ID_PATTERN.fullmatch(law_id):
            raise ValueError(f"invalid law_id in INDEX: {law_id!r}")
        if source_path.is_absolute() or any(part in {"", ".", ".."} for part in source_path.parts):
            raise ValueError(f"unsafe source path in INDEX: {source!r}")
        if (
            len(source_path.parts) < 2
            or source_path.parts[0] != category
            or any(part == "_private" or part.startswith(".") for part in source_path.parts)
        ):
            raise ValueError(f"source path does not match public category in INDEX: {source!r}")
        records.append(
            LawRecord(
                number=number,
                name=name,
                category=category,
                law_id=law_id,
                source_dir=source_path,
            )
        )
    return records


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = rewrite_egov_law_links(content)
    path.write_text(content.rstrip() + "\n", encoding="utf-8-sig")


def _page_title(source_path: Path) -> str:
    for line in source_path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return source_path.stem.replace("_", " ")


def _chapter_slug(source_path: Path, used: set[str]) -> str:
    if source_path.stem == "00_全文":
        base = "fulltext"
    else:
        groups = re.findall(r"(?:^|_)(\d{2})(?=_|$)", source_path.stem)
        base = "-".join(groups) if groups else "part"
    slug = base
    if slug in used:
        digest = hashlib.sha1(source_path.name.encode("utf-8")).hexdigest()[:7]
        slug = f"{base}-{digest}"
    used.add(slug)
    return slug


def rewrite_internal_links(markdown: str, target_map: dict[str, str]) -> str:
    """Rewrite same-law Markdown links to their generated short URL targets."""
    pattern = re.compile(r"(?P<prefix>\]\()(?P<target>[^)#\s]+\.md)(?P<anchor>#[^)\s]+)?(?P<suffix>\))")

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        mapped = target_map.get(target.removeprefix("./"))
        if mapped is None:
            return match.group(0)
        anchor = match.group("anchor") or ""
        return f"](./{mapped}{anchor})"

    return pattern.sub(replace, markdown)


def rewrite_egov_law_links(markdown: str) -> str:
    """Keep source cross-law references valid by routing them to e-Gov."""
    egov_base = "https://laws.e-gov.go.jp/law/"
    return (
        markdown.replace('href="/law/', f'href="{egov_base}')
        .replace("href='/law/", f"href='{egov_base}")
        .replace("](/law/", f"]({egov_base}")
    )


_INTRAWORD_LEGAL_EMPHASIS = re.compile(r"(?m)^_([^_\n]{1,40})_(?=\S)")
_TABLE_SEPARATOR = re.compile(r"^\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")


def normalize_legal_markdown(markdown: str) -> str:
    """Make e-Gov-derived legal Markdown render as visible legal text."""
    markdown = _INTRAWORD_LEGAL_EMPHASIS.sub(r"\1", markdown)
    had_trailing_newline = markdown.endswith("\n")
    lines = markdown.splitlines()
    normalized: list[str] = []
    for index, line in enumerate(lines):
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if (
            line.strip().startswith("|")
            and _TABLE_SEPARATOR.fullmatch(next_line)
            and normalized
            and normalized[-1].strip()
        ):
            normalized.append("")
        normalized.append(line)
    result = "\n".join(normalized)
    return result + "\n" if had_trailing_newline else result


def search_page_markdown() -> str:
    return """---
title: "法令検索"
description: "Finlawsの日本語全文検索"
---

# 法令検索

法令名、制度名、条番号を入力してください。7カテゴリの分割索引を端末内で横断し、外部検索APIへ送信しません。

<div id="search" class="finlaws-search" data-finlaws-search data-pagefind-manifest="../pagefind/manifest.json">
  <form class="finlaws-search__form" role="search">
    <label class="finlaws-search__label" for="finlaws-search-input">法令名・条文を検索</label>
    <input class="finlaws-search__input" id="finlaws-search-input" name="q" type="search" inputmode="search" autocomplete="off" placeholder="例：資金決済法、電子決済等代行業、第2条">
    <button class="finlaws-search__button" type="submit">検索</button>
  </form>
  <p class="finlaws-search__status" data-search-status role="status" aria-live="polite">法令名、制度名、条番号を入力してください。</p>
  <ol class="finlaws-search__results" data-search-results aria-label="検索結果"></ol>
</div>
"""


def _front_matter(title: str, description: str) -> str:
    safe_title = title.replace('"', "'")
    safe_description = description.replace('"', "'")
    return f'---\ntitle: "{safe_title}"\ndescription: "{safe_description}"\n---\n\n'


def _legal_notice(record: LawRecord) -> str:
    return (
        "\n\n---\n\n"
        '<aside class="finlaws-source-note" markdown>\n'
        f"**出典・確認**: [e-Gov法令検索の正本](https://laws.e-gov.go.jp/law/{record.law_id})"
        f" / law_id `{record.law_id}` / スナップショット {SNAPSHOT_DATE} JST  \n"
        "このサイトは検索・参照用コピーであり、法的助言ではありません。\n"
        "</aside>\n"
    )


def _prepare_output(output_root: Path) -> None:
    marker = output_root / ".finlaws-generated"
    if output_root.exists():
        if not marker.is_file():
            raise RuntimeError(f"refusing to replace unmarked output directory: {output_root}")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    marker.write_text("generated by scripts/build_pages_source.py\n", encoding="utf-8")


def build_site_source(source_root: Path, output_root: Path) -> dict[str, int]:
    """Generate BOM-safe MkDocs source from the canonical repository corpus."""
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    _prepare_output(output_root)

    parsed_records = parse_law_index(source_root / "INDEX.md")
    records: list[LawRecord] = []
    law_id_occurrences: dict[str, int] = {}
    law_id_fingerprints: dict[str, str] = {}
    used_url_ids: set[str] = set()
    url_collisions = 0
    for record in parsed_records:
        raw_source_dir = source_root / record.source_dir
        if raw_source_dir.is_symlink():
            raise ValueError(f"law source directory symlink is not allowed: {record.source_dir}")
        source_dir = raw_source_dir.resolve()
        category_root = (source_root / record.category).resolve()
        if not source_dir.is_relative_to(source_root) or not source_dir.is_relative_to(category_root):
            raise ValueError(f"law source escapes repository root: {record.source_dir}")
        if not source_dir.is_dir():
            raise FileNotFoundError(f"missing law directory: {record.source_dir}")
        fulltext_path = source_dir / "00_全文.md"
        if not fulltext_path.is_file():
            raise FileNotFoundError(f"missing canonical full text: {record.source_dir}/00_全文.md")
        _validate_source_markdown(fulltext_path, source_root, source_dir)
        fulltext = fulltext_path.read_text(encoding="utf-8-sig")
        if f"Law ID: {record.law_id}" not in fulltext:
            raise ValueError(f"source law_id mismatch for {record.source_dir}: {record.law_id}")
        fingerprint = hashlib.sha256(fulltext.encode("utf-8")).hexdigest()
        previous_fingerprint = law_id_fingerprints.setdefault(record.law_id, fingerprint)
        if previous_fingerprint != fingerprint:
            raise ValueError(f"conflicting source content for law_id {record.law_id}: {record.source_dir}")
        occurrence = law_id_occurrences.get(record.law_id, 0) + 1
        law_id_occurrences[record.law_id] = occurrence
        if occurrence == 1:
            url_id = record.law_id
        else:
            url_collisions += 1
            suffix = re.sub(r"[^A-Za-z0-9_-]+", "-", record.number).strip("-") or f"copy-{occurrence}"
            url_id = f"{record.law_id}-{suffix}"
        if url_id in used_url_ids:
            digest = hashlib.sha1(record.source_dir.as_posix().encode("utf-8")).hexdigest()[:7]
            url_id = f"{url_id}-{digest}"
        used_url_ids.add(url_id)
        records.append(
            LawRecord(
                number=record.number,
                name=record.name,
                category=record.category,
                law_id=record.law_id,
                source_dir=record.source_dir,
                url_id=url_id,
            )
        )

    categories: dict[str, list[LawRecord]] = {category: [] for category in ALLOWED_CATEGORIES}
    for record in records:
        categories[record.category].append(record)

    home_lines = [
        _front_matter("Finlaws", "日本の金融関連法令を高速に検索・閲覧"),
        "# 金融法令を、迷わず引ける。\n",
        f'<p class="finlaws-lead">{len(records)}法令をカテゴリ・法令名・条文全文から探せる静的法令ライブラリです。</p>\n',
        '<div class="finlaws-actions" markdown>[法令を検索](search/index.md){ .md-button .md-button--primary } [全法令を見る](laws/index.md){ .md-button }</div>\n',
        "## カテゴリから探す\n",
        '<div class="grid cards" markdown>\n',
    ]
    for category in ALLOWED_CATEGORIES:
        slug = CATEGORY_SLUGS[category]
        home_lines.append(f'-   **{category}**\n\n    {len(categories[category])}法令を収録\n\n    [一覧を開く](category/{slug}/index.md)\n')
    home_lines.extend(
        [
            "</div>\n",
            "## このサイトについて\n",
            f"e-Gov法令検索の公式データを {SNAPSHOT_DATE} JST に整合性再検証した参照用コピーです。正本ではありません。\n",
        ]
    )
    _write_markdown(output_root / "index.md", "\n".join(home_lines))
    _write_markdown(output_root / "search" / "index.md", search_page_markdown())
    _write_markdown(
        output_root / "disclaimer.md",
        _front_matter("免責・出典", "Finlawsの出典、更新日、免責事項")
        + "# 免責・出典\n\n"
        + "## 正本について\n\n"
        + "Finlawsは[e-Gov法令検索](https://laws.e-gov.go.jp/)の現在施行版をMarkdownへ変換した検索・参照用コピーです。"
        + "条文の正本ではありません。契約、許認可、届出、訴訟、規制対応などの判断では、必ずe-Govの最新条文と専門家の確認を経てください。\n\n"
        + f"## スナップショット\n\n取得日: **{SNAPSHOT_DATE} JST**\n\n"
        + "## 法的助言ではありません\n\n本サイトの情報は一般的な調査を支援するもので、法的助言を構成しません。\n",
    )
    asset_root = Path(__file__).resolve().parents[1] / "site_assets"
    for asset_name in ("finlaws.css", "finlaws-search.js", "finlaws-search.css"):
        asset_source = asset_root / asset_name
        if not asset_source.is_file():
            raise FileNotFoundError(f"missing site asset: {asset_source}")
        asset_target = output_root / "assets" / asset_name
        asset_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset_source, asset_target)

    search_partitions = {
        "base_path": "/finlaws/",
        "partitions": [
            {
                "name": CATEGORY_SLUGS[category],
                "category": category,
                "routes": [record.url_id for record in categories[category]],
            }
            for category in ALLOWED_CATEGORIES
        ],
    }
    (output_root / "search-partitions.json").write_text(
        json.dumps(search_partitions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    all_laws = [
        _front_matter("全法令", "Finlaws収録法令の一覧"),
        "# 全法令\n",
        f"{len(records)}件のcanonical法令を掲載しています。\n",
        "| # | 法令名 | 種別 | law_id |\n|---:|---|---|---|",
    ]
    for record in records:
        all_laws.append(
            f"| {record.number} | [{record.name}](../law/{record.url_id}/index.md) | {record.category} | `{record.law_id}` |"
        )
    _write_markdown(output_root / "laws" / "index.md", "\n".join(all_laws))

    for category in ALLOWED_CATEGORIES:
        slug = CATEGORY_SLUGS[category]
        lines = [
            _front_matter(f"{category}の法令", f"{category}カテゴリの法令一覧"),
            f"# {category}\n",
            f"{len(categories[category])}件を収録しています。\n",
        ]
        for record in categories[category]:
            lines.append(f"- [{record.name}](../../law/{record.url_id}/index.md)  `{record.law_id}`")
        _write_markdown(output_root / "category" / slug / "index.md", "\n".join(lines))

    chapter_count = 0
    for record in records:
        source_dir = source_root / record.source_dir
        output_dir = output_root / "law" / record.url_id
        used_slugs: set[str] = set()
        chapters: list[tuple[str, str, Path]] = []
        for source_path in sorted(source_dir.glob("*.md")):
            if source_path.name == "_INDEX.md" or source_path.name.endswith("._INDEX.md"):
                continue
            _validate_source_markdown(source_path, source_root, source_dir)
            slug = _chapter_slug(source_path, used_slugs)
            title = _page_title(source_path)
            chapters.append((slug, title, source_path))
        target_map = {source_path.name: f"{slug}.md" for slug, _, source_path in chapters}

        landing = [
            _front_matter(record.name, f"{record.name}の目次と条文"),
            (
                f'<article data-pagefind-body data-pagefind-filter="category:{html.escape(record.category, quote=True)}" '
                f'data-pagefind-meta="law_id:{record.law_id}" markdown>'
            ),
            f"# {record.name}\n",
            f"**{record.category}** · law_id `{record.law_id}` · 更新 {SNAPSHOT_DATE} JST\n",
            "## 目次\n",
        ]
        for slug, title, _ in chapters:
            label = "全文" if slug == "fulltext" else title
            landing.append(f"- [{label}](./{slug}.md)")
        landing.extend([_legal_notice(record), "</article>"])
        _write_markdown(output_dir / "index.md", "\n".join(landing))

        for slug, title, source_path in chapters:
            source_text = source_path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
            source_text = normalize_legal_markdown(source_text)
            source_text = rewrite_internal_links(source_text, target_map)
            source_text = rewrite_egov_law_links(source_text)
            if slug == "fulltext":
                open_tag = '<article data-pagefind-ignore="all" class="finlaws-law-text" markdown>'
            else:
                open_tag = (
                    f'<article data-pagefind-body data-pagefind-filter="category:{html.escape(record.category, quote=True)}" '
                    f'data-pagefind-meta="law_id:{record.law_id}" '
                    'class="finlaws-law-text" markdown>'
                )
            page = (
                _front_matter(f"{record.name} — {title}", f"{record.name} — {title}")
                + f'[← {record.name}の目次](./index.md)\n\n'
                + open_tag
                + "\n\n"
                + source_text.rstrip()
                + "\n</article>"
                + _legal_notice(record)
            )
            _write_markdown(output_dir / f"{slug}.md", page)
            chapter_count += 1

    return {
        "source_laws": len(parsed_records),
        "laws": len(records),
        "aliases": 0,
        "url_collisions": url_collisions,
        "chapters": chapter_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate MkDocs source for Finlaws Pages")
    parser.add_argument("--source", type=Path, default=Path.cwd(), help="Finlaws repository root")
    parser.add_argument("--output", type=Path, default=Path("docs_generated"), help="Generated MkDocs docs directory")
    arguments = parser.parse_args()
    result = build_site_source(arguments.source, arguments.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
