from __future__ import annotations

import argparse
import json
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"id", "name"} and value:
                self.ids.add(value)
        attribute = "href" if tag in {"a", "link"} else "src" if tag in {"img", "script"} else None
        if attribute is None:
            return
        for name, value in attrs:
            if name == attribute and value:
                self.links.append(value)


def _target_file(site_root: Path, source_html: Path, url: str, base_path: str) -> Path | None:
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or url.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    path = unquote(parsed.path)
    if not path:
        return source_html if parsed.fragment else None
    normalized_base = "/" + base_path.strip("/") + "/"
    if path.startswith("/"):
        if not path.startswith(normalized_base):
            return site_root / "__outside_project_base__"
        relative_url = path[len(normalized_base) :]
    else:
        source_relative = source_html.relative_to(site_root).as_posix()
        source_url_dir = posixpath.dirname(source_relative)
        relative_url = posixpath.normpath(posixpath.join(source_url_dir, path))
    relative_url = relative_url.lstrip("/")
    target = (site_root / relative_url).resolve()
    if not target.is_relative_to(site_root):
        return site_root / "__outside_project_base__"
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    elif not target.suffix:
        target = target / "index.html"
    return target


def find_broken_links(site_root: Path, base_path: str) -> list[tuple[str, str]]:
    """Return local href/src targets or fragments that do not resolve."""
    site_root = site_root.resolve()
    broken: list[tuple[str, str]] = []
    id_cache: dict[Path, set[str]] = {}
    for html_path in sorted(site_root.rglob("*.html")):
        parser = _LinkCollector()
        parser.feed(html_path.read_text(encoding="utf-8"))
        for url in parser.links:
            target = _target_file(site_root, html_path, url, base_path)
            if target is not None and not target.is_file():
                broken.append((html_path.relative_to(site_root).as_posix(), url))
                continue
            fragment = unquote(urlsplit(url).fragment)
            if target is not None and fragment and target.suffix.lower() == ".html":
                target = target.resolve()
                if target not in id_cache:
                    target_parser = _LinkCollector()
                    target_parser.feed(target.read_text(encoding="utf-8"))
                    id_cache[target] = target_parser.ids
                if fragment not in id_cache[target]:
                    broken.append((html_path.relative_to(site_root).as_posix(), url))
    return broken


class _VisibleTextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "pre", "code"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "pre", "code"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


_UNRENDERED_MARKDOWN_PATTERNS = (
    re.compile(r"\[[^\]\n]+\]\([^\)\n]+\.md(?:#[^\)\n]+)?\)"),
    re.compile(r"(?:^|\n)[ \t]*#{1,6}[ \t]+\S", re.MULTILINE),
)


def find_unrendered_markdown(site_root: Path) -> list[str]:
    """Return HTML pages whose visible text still contains source Markdown."""
    findings: list[str] = []
    for html_path in sorted(site_root.rglob("*.html")):
        parser = _VisibleTextCollector()
        parser.feed(html_path.read_text(encoding="utf-8"))
        visible_text = "\n".join(parser.parts)
        if any(pattern.search(visible_text) for pattern in _UNRENDERED_MARKDOWN_PATTERNS):
            findings.append(html_path.relative_to(site_root).as_posix())
    return findings


_FORBIDDEN_MARKERS = (
    "_private/",
    "/opt/data/",
    "github_pat_",
    "ghp_",
    "xoxb-",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
)
_TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".xml", ".txt", ".map"}
_SECRET_PATTERNS = (
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"sk_live_[0-9A-Za-z]{16,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
)


def scan_forbidden_content(site_root: Path) -> list[tuple[str, str]]:
    """Return publishable text files containing private paths or secret shapes."""
    site_root = site_root.resolve()
    findings: list[tuple[str, str]] = []
    for path in sorted(site_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in _FORBIDDEN_MARKERS:
            if marker in text:
                findings.append((path.relative_to(site_root).as_posix(), marker))
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                findings.append((path.relative_to(site_root).as_posix(), pattern.pattern))
    return findings


def verify_built_site(site_root: Path, base_path: str) -> dict[str, object]:
    """Run fail-closed structural, link, base-path, and publication-safety checks."""
    site_root = site_root.resolve()
    html_paths = sorted(site_root.rglob("*.html")) if site_root.is_dir() else []
    broken_links = find_broken_links(site_root, base_path) if html_paths else []
    unrendered_markdown = find_unrendered_markdown(site_root) if html_paths else []
    forbidden_content = scan_forbidden_content(site_root) if site_root.is_dir() else []
    forbidden_paths = [
        path.relative_to(site_root).as_posix()
        for path in sorted(site_root.rglob("*"))
        if "_private" in path.relative_to(site_root).parts
    ] if site_root.is_dir() else []
    normalized_base_path = "/" + base_path.strip("/") + "/"
    pagefind_dir = site_root / "pagefind"
    pagefind_manifest_path = pagefind_dir / "manifest.json"
    missing_pagefind: list[str] = []
    pagefind_manifest_error = ""
    pagefind_partitions = 0
    if not pagefind_manifest_path.is_file():
        missing_pagefind.append("pagefind/manifest.json")
    else:
        try:
            pagefind_manifest = json.loads(pagefind_manifest_path.read_text(encoding="utf-8"))
            if pagefind_manifest.get("base_path") != normalized_base_path:
                pagefind_manifest_error = "Pagefind manifest base_path mismatch"
            partition_entries = pagefind_manifest.get("partitions")
            if not isinstance(partition_entries, list) or not partition_entries:
                pagefind_manifest_error = "Pagefind manifest has no partitions"
            else:
                for entry in partition_entries:
                    bundle = entry.get("bundle") if isinstance(entry, dict) else None
                    if not isinstance(bundle, str) or bundle.startswith(("/", ".")) or ".." in Path(bundle).parts:
                        pagefind_manifest_error = "Pagefind manifest has invalid bundle path"
                        continue
                    bundle_script = (pagefind_dir / bundle / "pagefind.js").resolve()
                    if not bundle_script.is_relative_to(pagefind_dir.resolve()) or not bundle_script.is_file():
                        missing_pagefind.append(f"pagefind/{bundle}pagefind.js")
                pagefind_partitions = len(partition_entries)
        except (json.JSONDecodeError, OSError, AttributeError) as error:
            pagefind_manifest_error = f"invalid Pagefind manifest: {error}"
    replacement_characters = sum(
        path.read_text(encoding="utf-8", errors="replace").count("\ufffd") for path in html_paths
    )
    oversized_files = [
        path.relative_to(site_root).as_posix()
        for path in sorted(site_root.rglob("*"))
        if path.is_file() and path.stat().st_size > 25 * 1024 * 1024
    ] if site_root.is_dir() else []
    site_bytes = sum(path.stat().st_size for path in site_root.rglob("*") if path.is_file()) if site_root.is_dir() else 0

    errors: list[str] = []
    if not site_root.is_dir():
        errors.append("site directory does not exist")
    if not html_paths:
        errors.append("no HTML files")
    if not (site_root / "404.html").is_file():
        errors.append("missing 404.html")
    if missing_pagefind:
        errors.append("missing Pagefind assets")
    if pagefind_manifest_error:
        errors.append(pagefind_manifest_error)
    if broken_links:
        errors.append("broken internal links")
    if unrendered_markdown:
        errors.append("unrendered Markdown in HTML")
    if forbidden_content:
        errors.append("forbidden content")
    if forbidden_paths:
        errors.append("forbidden _private paths")
    if replacement_characters:
        errors.append("replacement characters in HTML")
    if oversized_files:
        errors.append("oversized files in site artifact")
    if site_bytes > 900 * 1024 * 1024:
        errors.append("site artifact exceeds 900 MiB safety limit")

    report: dict[str, object] = {
        "status": "pass" if not errors else "fail",
        "site": str(site_root),
        "base_path": normalized_base_path,
        "html_files": len(html_paths),
        "pagefind_partitions": pagefind_partitions,
        "pagefind_files": sum(1 for path in pagefind_dir.rglob("*") if path.is_file()) if pagefind_dir.is_dir() else 0,
        "site_bytes": site_bytes,
        "broken_links": broken_links,
        "unrendered_markdown": unrendered_markdown,
        "forbidden_content": forbidden_content,
        "forbidden_paths": forbidden_paths,
        "missing_pagefind": missing_pagefind,
        "pagefind_manifest_error": pagefind_manifest_error,
        "replacement_characters": replacement_characters,
        "oversized_files": oversized_files,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a built Finlaws static site")
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--base-path", default="/finlaws/")
    arguments = parser.parse_args()
    report = verify_built_site(arguments.site, arguments.base_path)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
