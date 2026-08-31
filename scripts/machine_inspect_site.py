from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import posixpath
import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
from xml.etree import ElementTree


JST = timezone(timedelta(hours=9))
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".xml", ".txt", ".map", ".svg"}
URL_ATTRIBUTES = {
    "href",
    "src",
    "poster",
    "action",
    "data-src",
    "data-href",
    "data-pagefind-manifest",
}
EXPECTED_TOP_LEVEL = {
    ".nojekyll",
    "404.html",
    "assets",
    "category",
    "disclaimer",
    "index.html",
    "law",
    "laws",
    "pagefind",
    "robots.txt",
    "search",
    "search-partitions.json",
    "sitemap.xml",
    "sitemap.xml.gz",
}
ENVIRONMENT_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SOURCE_SUFFIXES = {
    ".md",
    ".markdown",
    ".py",
    ".pyc",
    ".yml",
    ".yaml",
    ".toml",
    ".lock",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".zip",
    ".tar",
    ".tgz",
}
HIGH_CONFIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("github-fine-grained-token", re.compile(rb"github_pat_[A-Za-z0-9_]{20,255}")),
    ("github-legacy-token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("aws-access-key", re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("google-api-key", re.compile(rb"AIza[0-9A-Za-z_-]{30,}")),
    ("slack-token", re.compile(rb"xox[baprs]-[0-9A-Za-z-]{20,}")),
    ("stripe-live-key", re.compile(rb"(?:sk|rk)_live_[0-9A-Za-z]{16,}")),
    ("openai-or-anthropic-key", re.compile(rb"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}")),
    ("jwt", re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)
FORBIDDEN_MARKERS: tuple[tuple[str, bytes], ...] = (
    ("private-tree-marker", b"_private/"),
    ("host-data-path", b"/opt/data/"),
    ("file-url", b"file:///"),
)
LOCAL_PATH_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("linux-home-path", re.compile(rb"/home/[A-Za-z0-9._-]+/(?:[^\x00\r\n\"'<> ]+)?")),
    ("mac-home-path", re.compile(rb"/Users/[A-Za-z0-9._-]+/(?:[^\x00\r\n\"'<> ]+)?")),
    ("temporary-path", re.compile(rb"/tmp/[A-Za-z0-9._-]+(?:/[^\x00\r\n\"'<> ]*)?")),
    (
        "windows-drive-path",
        re.compile(
            rb"(?<![A-Za-z0-9])[A-Za-z]:\\(?:Users|Windows|Program Files|Documents and Settings|work|runner|src|repo)\\"
            rb"(?:[^\x00\r\n\"'<>|]+)"
        ),
    ),
)
GENERIC_CREDENTIAL_RE = re.compile(
    r"(?i)\b(api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password|passwd)\b"
    r"\s*[:=]\s*[\"']([^\"'\r\n]{8,200})[\"']"
)
CSS_URL_RE = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)", re.IGNORECASE)
PERCENT_ERROR_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff々〆ヵヶ]")


@dataclass(frozen=True)
class Reference:
    source: str
    line: int
    attribute: str
    url: str


@dataclass(frozen=True)
class BrokenReference:
    source: str
    line: int
    attribute: str
    url: str
    reason: str


class PageParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.references: list[Reference] = []
        self.ids: set[str] = set()
        self.canonicals: list[str] = []
        self.base_hrefs: list[str] = []
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.lang = ""
        self.charset = ""
        self._in_title = False
        self._h1_depth = 0
        self._have_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        normalized = {name.lower(): value for name, value in attrs}
        if tag == "html" and normalized.get("lang"):
            self.lang = normalized["lang"] or ""
        if tag == "meta" and normalized.get("charset"):
            self.charset = (normalized["charset"] or "").lower()
        if tag == "title":
            self._in_title = True
        if tag == "h1" and not self._have_h1:
            self._h1_depth = 1
            self._have_h1 = True
        elif self._h1_depth:
            self._h1_depth += 1
        for key in ("id", "name"):
            if normalized.get(key):
                self.ids.add(normalized[key] or "")
        line, _ = self.getpos()
        for name, value in attrs:
            attr = name.lower()
            if not value:
                continue
            if attr in URL_ATTRIBUTES:
                self.references.append(Reference(self.source, line, attr, value))
            elif attr == "srcset":
                for candidate in value.split(","):
                    candidate_url = candidate.strip().split()[0] if candidate.strip() else ""
                    if candidate_url:
                        self.references.append(Reference(self.source, line, "srcset", candidate_url))
            elif attr == "style":
                for match in CSS_URL_RE.finditer(value):
                    self.references.append(Reference(self.source, line, "style-url", match.group(2)))
        if tag == "link" and normalized.get("rel"):
            rel_values = {part.lower() for part in (normalized["rel"] or "").split()}
            href = normalized.get("href")
            if "canonical" in rel_values and href:
                self.canonicals.append(href)
        if tag == "base" and normalized.get("href"):
            self.base_hrefs.append(normalized["href"] or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._h1_depth:
            self._h1_depth -= 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if self._h1_depth:
            self._h1_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._h1_depth:
            self.h1_parts.append(data)

    @property
    def title(self) -> str:
        return normalize_text("".join(self.title_parts))

    @property
    def h1(self) -> str:
        return normalize_text("".join(self.h1_parts).replace("¶", ""))


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def relative_site_url(relative_file: str) -> str:
    if relative_file == "index.html":
        return ""
    if relative_file.endswith("/index.html"):
        return relative_file[: -len("index.html")]
    return relative_file


def expected_canonical(relative_file: str, public_origin: str, base_path: str) -> str:
    return public_origin.rstrip("/") + base_path + relative_site_url(relative_file)


def validate_url_syntax(reference: Reference) -> list[str]:
    errors: list[str] = []
    url = reference.url
    parsed = urlsplit(url)
    if parsed.scheme.lower() in {"mailto", "tel", "javascript", "data", "blob"}:
        return errors
    if any(char.isspace() for char in url):
        errors.append("whitespace in URL")
    if "\\" in url:
        errors.append("backslash in URL")
    if PERCENT_ERROR_RE.search(url):
        errors.append("invalid percent escape")
    if any(ord(char) > 127 for char in url):
        errors.append("raw non-ASCII URL")
    return errors


def resolve_internal_reference(
    site_root: Path,
    reference: Reference,
    base_path: str,
    public_origin: str,
) -> tuple[Path | None, str, bool]:
    """Return target, error reason, and whether the URL is an internal reference."""
    raw_url = reference.url.strip()
    parsed = urlsplit(raw_url)
    origin = urlsplit(public_origin)
    scheme = parsed.scheme.lower()
    if scheme in {"mailto", "tel", "javascript", "data", "blob"}:
        return None, "", False
    if parsed.netloc:
        same_public_host = parsed.netloc.lower() == origin.netloc.lower()
        same_public_scheme = not parsed.scheme or parsed.scheme.lower() == origin.scheme.lower()
        if not (same_public_host and same_public_scheme):
            return None, "", False
    elif parsed.scheme:
        return None, "", False

    decoded_path = unquote(parsed.path)
    normalized_base = "/" + base_path.strip("/") + "/"
    source_relative = reference.source
    if parsed.netloc or decoded_path.startswith("/"):
        if not decoded_path.startswith(normalized_base):
            return None, "project-host/root URL outside configured base path", True
        relative_url = decoded_path[len(normalized_base) :]
    elif decoded_path:
        source_directory = posixpath.dirname(source_relative)
        relative_url = posixpath.normpath(posixpath.join(source_directory, decoded_path))
    else:
        relative_url = source_relative

    relative_url = relative_url.lstrip("/")
    target = (site_root / relative_url).resolve()
    if not target.is_relative_to(site_root):
        return None, "path escapes generated site root", True
    if decoded_path.endswith("/") or target.is_dir():
        target = target / "index.html"
    elif not target.suffix:
        target = target / "index.html"
    if not target.is_file():
        return target, "target file does not exist", True
    fragment = unquote(parsed.fragment)
    if fragment and target.suffix.lower() == ".html":
        return target, fragment, True
    return target, "", True


def redact_candidate(value: str) -> str:
    if len(value) <= 8:
        return "<redacted>"
    return value[:4] + "…" + value[-4:] + f" ({len(value)} chars)"


def scan_artifact_files(site_root: Path, large_threshold: int, oversized_threshold: int) -> dict[str, Any]:
    files = sorted(path for path in site_root.rglob("*") if path.is_file())
    directories = sorted(path for path in site_root.rglob("*") if path.is_dir())
    top_level = sorted(path.name for path in site_root.iterdir())
    unexpected_top_level = sorted(set(top_level) - EXPECTED_TOP_LEVEL)
    symlinks = sorted(path.relative_to(site_root).as_posix() for path in site_root.rglob("*") if path.is_symlink())
    forbidden_paths: list[str] = []
    environment_files: list[str] = []
    source_like_files: list[str] = []
    hidden_paths: list[str] = []
    decode_errors: list[str] = []
    replacement_characters: list[dict[str, Any]] = []
    marker_findings: list[dict[str, Any]] = []
    local_path_findings: list[dict[str, Any]] = []
    high_confidence_secrets: list[dict[str, Any]] = []
    heuristic_secret_candidates: list[dict[str, Any]] = []
    suffix_counts: Counter[str] = Counter()

    for path in files:
        relative = path.relative_to(site_root).as_posix()
        parts_lower = [part.lower() for part in path.relative_to(site_root).parts]
        name_lower = path.name.lower()
        suffix_lower = path.suffix.lower()
        suffix_counts["".join(path.suffixes).lower() or "<none>"] += 1
        if "_private" in parts_lower:
            forbidden_paths.append(relative)
        if name_lower in ENVIRONMENT_NAMES or name_lower.startswith(".env."):
            environment_files.append(relative)
        if suffix_lower in SOURCE_SUFFIXES:
            source_like_files.append(relative)
        if any(
            part.startswith(".") and part not in {".nojekyll", ".finlaws-pagefind-generated"}
            for part in path.relative_to(site_root).parts
        ):
            hidden_paths.append(relative)

        payload = path.read_bytes()
        for label, marker in FORBIDDEN_MARKERS:
            for match in re.finditer(re.escape(marker), payload):
                marker_findings.append({"path": relative, "pattern": label, "offset": match.start()})
        for label, pattern in LOCAL_PATH_PATTERNS:
            for match in pattern.finditer(payload):
                local_path_findings.append({
                    "path": relative,
                    "pattern": label,
                    "offset": match.start(),
                    "value": redact_candidate(match.group(0).decode("utf-8", errors="replace")),
                })
        for label, pattern in HIGH_CONFIDENCE_PATTERNS:
            for match in pattern.finditer(payload):
                high_confidence_secrets.append({
                    "path": relative,
                    "pattern": label,
                    "offset": match.start(),
                    "value": redact_candidate(match.group(0).decode("ascii", errors="replace")),
                })

        if suffix_lower in TEXT_SUFFIXES:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                decode_errors.append(f"{relative}: {error}")
                continue
            replacement_count = text.count("\ufffd")
            if replacement_count:
                replacement_characters.append({"path": relative, "count": replacement_count})
            for match in GENERIC_CREDENTIAL_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                heuristic_secret_candidates.append({
                    "path": relative,
                    "line": line,
                    "key": match.group(1),
                    "value": redact_candidate(match.group(2)),
                })

    largest_files = sorted(
        ({"path": path.relative_to(site_root).as_posix(), "bytes": path.stat().st_size} for path in files),
        key=lambda item: (-item["bytes"], item["path"]),
    )
    large_files = [item for item in largest_files if item["bytes"] >= large_threshold]
    oversized_files = [item for item in largest_files if item["bytes"] >= oversized_threshold]
    return {
        "file_count": len(files),
        "directory_count": len(directories),
        "total_bytes": sum(path.stat().st_size for path in files),
        "top_level_entries": top_level,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "largest_files_top_20": largest_files[:20],
        "large_file_threshold_bytes": large_threshold,
        "large_files": large_files,
        "oversized_threshold_bytes": oversized_threshold,
        "oversized_files": oversized_files,
        "unexpected_top_level": unexpected_top_level,
        "symlinks": symlinks,
        "forbidden_private_paths": forbidden_paths,
        "environment_files": environment_files,
        "source_like_files": source_like_files,
        "hidden_paths": hidden_paths,
        "utf8_decode_errors": decode_errors,
        "replacement_characters": replacement_characters,
        "forbidden_marker_findings": marker_findings,
        "local_absolute_path_findings": local_path_findings,
        "high_confidence_secret_findings": high_confidence_secrets,
        "heuristic_secret_candidates": heuristic_secret_candidates,
    }


def collect_css_references(site_root: Path) -> list[Reference]:
    references: list[Reference] = []
    for path in sorted(site_root.rglob("*.css")):
        relative = path.relative_to(site_root).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in CSS_URL_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            references.append(Reference(relative, line, "css-url", match.group(2)))
    return references


def collect_sitemap_references(site_root: Path) -> tuple[list[Reference], list[str]]:
    references: list[Reference] = []
    errors: list[str] = []
    for relative in ("sitemap.xml", "sitemap.xml.gz"):
        path = site_root / relative
        if not path.is_file():
            errors.append(f"missing {relative}")
            continue
        try:
            payload = gzip.decompress(path.read_bytes()) if relative.endswith(".gz") else path.read_bytes()
            root = ElementTree.fromstring(payload)
            locs = [element.text.strip() for element in root.iter() if element.tag.endswith("loc") and element.text]
            for index, url in enumerate(locs, start=1):
                references.append(Reference(relative, index, "sitemap-loc", url))
        except (OSError, ElementTree.ParseError) as error:
            errors.append(f"{relative}: {error}")
    return references, errors


def inspect_html_and_links(site_root: Path, base_path: str, public_origin: str) -> dict[str, Any]:
    html_paths = sorted(site_root.rglob("*.html"))
    pages: dict[str, PageParser] = {}
    references: list[Reference] = []
    html_decode_errors: list[str] = []
    for path in html_paths:
        relative = path.relative_to(site_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            html_decode_errors.append(f"{relative}: {error}")
            continue
        parser = PageParser(relative)
        parser.feed(text)
        pages[relative] = parser
        references.extend(parser.references)

    css_references = collect_css_references(site_root)
    sitemap_references, sitemap_errors = collect_sitemap_references(site_root)
    references.extend(css_references)
    references.extend(sitemap_references)

    id_cache = {relative: parser.ids for relative, parser in pages.items()}
    broken: list[BrokenReference] = []
    syntax_findings: list[dict[str, Any]] = []
    reference_classes: Counter[str] = Counter()
    internal_checked = 0
    fragment_checked = 0
    percent_encoded = 0
    raw_non_ascii = 0

    for reference in references:
        parsed = urlsplit(reference.url.strip())
        if "%" in reference.url:
            percent_encoded += 1
        if any(ord(char) > 127 for char in reference.url):
            raw_non_ascii += 1
        syntax_errors = validate_url_syntax(reference)
        if syntax_errors:
            syntax_findings.append({**asdict(reference), "errors": syntax_errors})
        if parsed.scheme:
            reference_classes["scheme_absolute"] += 1
        elif parsed.netloc:
            reference_classes["protocol_relative"] += 1
        elif parsed.path.startswith("/"):
            reference_classes["root_absolute"] += 1
        elif parsed.path:
            reference_classes["relative"] += 1
        elif parsed.fragment:
            reference_classes["fragment_only"] += 1
        else:
            reference_classes["empty_or_query_only"] += 1

        target, reason_or_fragment, is_internal = resolve_internal_reference(
            site_root, reference, base_path, public_origin
        )
        if not is_internal:
            reference_classes["external_or_nonfetch"] += 1
            continue
        internal_checked += 1
        if target is None:
            broken.append(BrokenReference(**asdict(reference), reason=reason_or_fragment))
            continue
        if reason_or_fragment == "target file does not exist":
            broken.append(BrokenReference(**asdict(reference), reason=reason_or_fragment))
            continue
        if reason_or_fragment:
            fragment_checked += 1
            target_relative = target.relative_to(site_root).as_posix()
            if reason_or_fragment not in id_cache.get(target_relative, set()):
                broken.append(BrokenReference(**asdict(reference), reason="fragment id does not exist"))

    canonical_missing: list[str] = []
    canonical_mismatches: list[dict[str, Any]] = []
    base_elements: list[dict[str, Any]] = []
    language_mismatches: list[dict[str, str]] = []
    charset_mismatches: list[dict[str, str]] = []
    for relative, page in pages.items():
        if relative != "404.html":
            expected = expected_canonical(relative, public_origin, base_path)
            if not page.canonicals:
                canonical_missing.append(relative)
            elif page.canonicals != [expected]:
                canonical_mismatches.append({"path": relative, "expected": expected, "actual": page.canonicals})
        if page.base_hrefs:
            base_elements.append({"path": relative, "base_hrefs": page.base_hrefs})
        if page.lang.lower() != "ja":
            language_mismatches.append({"path": relative, "lang": page.lang})
        if page.charset != "utf-8":
            charset_mismatches.append({"path": relative, "charset": page.charset})

    return {
        "html_files": len(html_paths),
        "html_utf8_decode_errors": html_decode_errors,
        "references_total": len(references),
        "html_references": len(references) - len(css_references) - len(sitemap_references),
        "css_references": len(css_references),
        "sitemap_references": len(sitemap_references),
        "reference_classes": dict(sorted(reference_classes.items())),
        "internal_references_checked": internal_checked,
        "fragment_references_checked": fragment_checked,
        "broken_internal_references": [asdict(item) for item in broken],
        "broken_internal_count": len(broken),
        "url_syntax_findings": syntax_findings,
        "url_syntax_finding_count": len(syntax_findings),
        "percent_encoded_reference_count": percent_encoded,
        "raw_non_ascii_reference_count": raw_non_ascii,
        "canonical_missing": canonical_missing,
        "canonical_mismatches": canonical_mismatches,
        "base_elements": base_elements,
        "language_mismatches": language_mismatches,
        "charset_mismatches": charset_mismatches,
        "sitemap_errors": sitemap_errors,
        "pages": pages,
    }


def inspect_manifests_and_content(
    site_root: Path,
    pages: dict[str, PageParser],
    base_path: str,
    public_origin: str,
) -> dict[str, Any]:
    source_manifest_path = site_root / "search-partitions.json"
    pagefind_manifest_path = site_root / "pagefind/manifest.json"
    errors: list[str] = []
    try:
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        source_manifest = {}
        errors.append(f"search-partitions.json: {error}")
    try:
        pagefind_manifest = json.loads(pagefind_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        pagefind_manifest = {}
        errors.append(f"pagefind/manifest.json: {error}")

    normalized_base = "/" + base_path.strip("/") + "/"
    for label, manifest in (("search", source_manifest), ("pagefind", pagefind_manifest)):
        if manifest.get("base_path") != normalized_base:
            errors.append(f"{label} manifest base_path mismatch: {manifest.get('base_path')!r}")

    partitions = source_manifest.get("partitions") if isinstance(source_manifest, dict) else None
    pagefind_partitions = pagefind_manifest.get("partitions") if isinstance(pagefind_manifest, dict) else None
    if not isinstance(partitions, list):
        partitions = []
        errors.append("search manifest partitions missing or invalid")
    if not isinstance(pagefind_partitions, list):
        pagefind_partitions = []
        errors.append("pagefind manifest partitions missing or invalid")

    routes: list[str] = []
    categories: list[dict[str, Any]] = []
    category_page_findings: list[dict[str, Any]] = []
    expected_slugs: set[str] = set()
    pagefind_by_name = {
        entry.get("name"): entry for entry in pagefind_partitions if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    for partition in partitions:
        if not isinstance(partition, dict):
            errors.append("invalid search partition entry")
            continue
        category = partition.get("category")
        name = partition.get("name")
        partition_routes = partition.get("routes")
        if not isinstance(category, str) or not isinstance(name, str) or not isinstance(partition_routes, list):
            errors.append(f"invalid search partition: {partition!r}")
            continue
        expected_slugs.add(name)
        routes.extend(route for route in partition_routes if isinstance(route, str))
        category_path = f"category/{name}/index.html"
        page = pages.get(category_path)
        page_route_targets: set[str] = set()
        if page:
            for reference in page.references:
                target, reason, internal = resolve_internal_reference(site_root, reference, base_path, public_origin)
                if internal and target is not None and not reason:
                    relative_target = target.relative_to(site_root).as_posix()
                    match = re.fullmatch(r"law/([0-9A-Za-z]+)/index\.html", relative_target)
                    if match:
                        page_route_targets.add(match.group(1))
        category_issues: list[str] = []
        if page is None:
            category_issues.append("category page missing")
        else:
            if page.h1 != category:
                category_issues.append(f"heading mismatch: {page.h1!r}")
            missing = sorted(set(partition_routes) - page_route_targets)
            unexpected = sorted(page_route_targets - set(partition_routes))
            if missing:
                category_issues.append(f"missing {len(missing)} law links")
            if unexpected:
                category_issues.append(f"unexpected {len(unexpected)} law links")
            if missing or unexpected:
                category_page_findings.append({
                    "category": category,
                    "slug": name,
                    "missing_routes": missing,
                    "unexpected_routes": unexpected,
                })
        pagefind_entry = pagefind_by_name.get(name, {})
        categories.append({
            "category": category,
            "slug": name,
            "law_count": len(partition_routes),
            "category_page_law_links": len(page_route_targets),
            "indexed_pages": pagefind_entry.get("pages"),
            "issues": category_issues,
        })

    route_duplicates = sorted(route for route, count in Counter(routes).items() if count > 1)
    law_page_findings: list[dict[str, Any]] = []
    law_names: list[dict[str, str]] = []
    for route in sorted(set(routes)):
        relative = f"law/{route}/index.html"
        page = pages.get(relative)
        issues: list[str] = []
        if page is None:
            issues.append("law landing page missing")
            title = ""
            h1 = ""
        else:
            title = page.title.removesuffix(" - Finlaws")
            h1 = page.h1
            if not title or not h1:
                issues.append("empty Japanese law name")
            if title != h1:
                issues.append(f"title/H1 mismatch: {title!r} != {h1!r}")
            if not JAPANESE_RE.search(title):
                issues.append(f"title lacks Japanese characters: {title!r}")
            expected = expected_canonical(relative, public_origin, base_path)
            if page.canonicals != [expected]:
                issues.append(f"law canonical mismatch: {page.canonicals!r}")
        if issues:
            law_page_findings.append({"law_id": route, "path": relative, "issues": issues})
        else:
            law_names.append({"law_id": route, "name": title})

    navigation_findings: list[dict[str, Any]] = []
    for relative, page in pages.items():
        resolved_slugs: set[str] = set()
        for reference in page.references:
            target, reason, internal = resolve_internal_reference(site_root, reference, base_path, public_origin)
            if not internal or target is None or reason:
                continue
            target_relative = target.relative_to(site_root).as_posix()
            match = re.fullmatch(r"category/([^/]+)/index\.html", target_relative)
            if match:
                resolved_slugs.add(match.group(1))
        missing_slugs = sorted(expected_slugs - resolved_slugs)
        if missing_slugs:
            navigation_findings.append({"path": relative, "missing_category_slugs": missing_slugs})

    partition_names = sorted(expected_slugs)
    pagefind_names = sorted(pagefind_by_name)
    if partition_names != pagefind_names:
        errors.append(f"partition name mismatch: search={partition_names}, pagefind={pagefind_names}")
    for name in expected_slugs:
        pagefind_entry = pagefind_by_name.get(name)
        if not pagefind_entry:
            continue
        bundle = pagefind_entry.get("bundle")
        if not isinstance(bundle, str) or bundle.startswith(("/", ".")) or ".." in Path(bundle).parts:
            errors.append(f"invalid Pagefind bundle for {name}: {bundle!r}")
            continue
        if not (site_root / "pagefind" / bundle / "pagefind.js").is_file():
            errors.append(f"missing Pagefind bundle for {name}: {bundle}pagefind.js")

    return {
        "manifest_errors": errors,
        "partition_count": len(partitions),
        "pagefind_partition_count": len(pagefind_partitions),
        "indexed_pages": sum(
            entry.get("pages", 0) for entry in pagefind_partitions if isinstance(entry, dict) and isinstance(entry.get("pages"), int)
        ),
        "law_route_count": len(routes),
        "unique_law_route_count": len(set(routes)),
        "duplicate_law_routes": route_duplicates,
        "law_name_pass_count": len(law_names),
        "law_page_findings": law_page_findings,
        "category_checks": categories,
        "category_page_findings": category_page_findings,
        "category_navigation_pages_checked": len(pages),
        "category_navigation_findings": navigation_findings,
    }


class MountedStaticHandler(BaseHTTPRequestHandler):
    site_root: Path
    base_path: str

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlsplit(self.path)
        decoded = unquote(parsed.path)
        if not decoded.startswith(self.base_path):
            self.send_error(404)
            return
        relative = decoded[len(self.base_path) :].lstrip("/")
        target = (self.site_root / relative).resolve()
        if not target.is_relative_to(self.site_root):
            self.send_error(404)
            return
        if decoded.endswith("/") or target.is_dir():
            target = target / "index.html"
        elif not target.suffix:
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def http_smoke(site_root: Path, base_path: str, routes: list[str], categories: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_base = "/" + base_path.strip("/") + "/"
    handler = type(
        "FinlawsStaticHandler",
        (MountedStaticHandler,),
        {"site_root": site_root.resolve(), "base_path": normalized_base},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_address[1]
    sample_route = sorted(routes)[0] if routes else ""
    chapter_candidates = sorted(site_root.glob("law/*/*/index.html"))
    sample_chapter = ""
    if chapter_candidates:
        sample_chapter = chapter_candidates[0].relative_to(site_root).parent.as_posix() + "/"
    checks: list[tuple[str, int]] = [
        (normalized_base, 200),
        (normalized_base + "search/", 200),
        (normalized_base + "laws/", 200),
        (normalized_base + "404.html", 200),
        (normalized_base + "pagefind/manifest.json", 200),
        (normalized_base + "assets/finlaws-search.js", 200),
        (normalized_base + "not-a-page-machine-qa/", 404),
    ]
    checks.extend((normalized_base + f"category/{item['slug']}/", 200) for item in categories)
    if sample_route:
        checks.append((normalized_base + f"law/{sample_route}/", 200))
    if sample_chapter:
        checks.append((normalized_base + sample_chapter, 200))

    results: list[dict[str, Any]] = []
    try:
        for path, expected_status in checks:
            actual_status = 0
            try:
                with urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
                    response.read(1)
                    actual_status = response.status
            except HTTPError as error:
                actual_status = error.code
            except OSError as error:
                results.append({"path": path, "expected": expected_status, "actual": None, "error": str(error)})
                continue
            results.append({"path": path, "expected": expected_status, "actual": actual_status})
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    failures = [result for result in results if result.get("actual") != result["expected"]]
    return {
        "mount_path": normalized_base,
        "checks": results,
        "check_count": len(results),
        "failures": failures,
        "failure_count": len(failures),
    }


def build_check_statuses(
    artifact: dict[str, Any],
    links: dict[str, Any],
    content: dict[str, Any],
    http: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, failures: list[Any], evidence: Any) -> None:
        checks[name] = {"status": "pass" if not failures else "fail", "failure_count": len(failures), "evidence": evidence}

    add("generated_tree_present", [] if artifact["file_count"] else ["empty"], {"files": artifact["file_count"]})
    add("404_static_and_http", http["failures"], {"http_checks": http["checks"]})
    add("internal_links", links["broken_internal_references"], {"checked": links["internal_references_checked"]})
    add(
        "base_url",
        links["canonical_missing"] + links["canonical_mismatches"] + links["base_elements"] + content["manifest_errors"],
        {"canonical_pages": links["html_files"] - 1, "manifest_errors": content["manifest_errors"]},
    )
    add("url_encoding", links["url_syntax_findings"], {"references": links["references_total"]})
    add("japanese_law_names", content["law_page_findings"], {"checked": content["unique_law_route_count"]})
    add("category_navigation", content["category_navigation_findings"] + content["category_page_findings"], {"pages": content["category_navigation_pages_checked"]})
    safety_failures: list[Any] = []
    for key in (
        "unexpected_top_level",
        "symlinks",
        "forbidden_private_paths",
        "environment_files",
        "source_like_files",
        "hidden_paths",
        "utf8_decode_errors",
        "replacement_characters",
        "forbidden_marker_findings",
        "local_absolute_path_findings",
        "high_confidence_secret_findings",
        "oversized_files",
    ):
        safety_failures.extend(artifact[key])
    add("publication_safety", safety_failures, {"files_scanned": artifact["file_count"]})
    add("http_mount_under_finlaws", http["failures"], {"mount_path": http["mount_path"], "checks": http["check_count"]})
    return checks


def run(arguments: argparse.Namespace) -> tuple[dict[str, Any], int]:
    site_root = arguments.site.resolve()
    normalized_base = "/" + arguments.base_path.strip("/") + "/"
    artifact = scan_artifact_files(site_root, arguments.large_threshold, arguments.oversized_threshold)
    links = inspect_html_and_links(site_root, normalized_base, arguments.public_origin.rstrip("/"))
    pages = links.pop("pages")
    content = inspect_manifests_and_content(site_root, pages, normalized_base, arguments.public_origin.rstrip("/"))
    route_ids: list[str] = []
    manifest_path = site_root / "search-partitions.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        route_ids = [
            route
            for partition in manifest.get("partitions", [])
            if isinstance(partition, dict)
            for route in partition.get("routes", [])
            if isinstance(route, str)
        ]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    http = http_smoke(site_root, normalized_base, route_ids, content["category_checks"])
    checks = build_check_statuses(artifact, links, content, http)
    failed_checks = sorted(name for name, check in checks.items() if check["status"] == "fail")
    report = {
        "schema_version": 1,
        "generated_at_jst": datetime.now(JST).isoformat(timespec="seconds"),
        "command": (
            f"python scripts/machine_inspect_site.py --site {arguments.site} "
            f"--base-path {normalized_base} --public-origin {arguments.public_origin.rstrip('/')} "
            f"--output {arguments.output}"
        ),
        "configuration": {
            "site": str(site_root),
            "base_path": normalized_base,
            "public_origin": arguments.public_origin.rstrip("/"),
            "public_base_url": arguments.public_origin.rstrip("/") + normalized_base,
            "large_threshold_bytes": arguments.large_threshold,
            "oversized_threshold_bytes": arguments.oversized_threshold,
        },
        "status": "pass" if not failed_checks else "fail",
        "exit_code": 0 if not failed_checks else 1,
        "failed_checks": failed_checks,
        "checks": checks,
        "artifact": artifact,
        "links_and_urls": links,
        "content_and_navigation": content,
        "http": http,
    }
    return report, report["exit_code"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Exhaustively inspect a generated Finlaws static-site tree")
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--base-path", default="/finlaws/")
    parser.add_argument("--public-origin", default="https://zkscio.github.io")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--large-threshold", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--oversized-threshold", type=int, default=25 * 1024 * 1024)
    arguments = parser.parse_args()
    if not arguments.site.is_dir():
        parser.error(f"site directory does not exist: {arguments.site}")
    report, exit_code = run(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "exit_code": exit_code,
        "output": str(arguments.output),
        "files": report["artifact"]["file_count"],
        "html": report["links_and_urls"]["html_files"],
        "references": report["links_and_urls"]["references_total"],
        "internal_checked": report["links_and_urls"]["internal_references_checked"],
        "broken": report["links_and_urls"]["broken_internal_count"],
        "failed_checks": report["failed_checks"],
    }, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
