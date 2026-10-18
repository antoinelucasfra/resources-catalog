"""
Shared utilities for sync_keep.py, backfill.py and make_covers.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import trafilatura
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "Blog",
        "Book",
        "Website",
        "Package",
        "Video",
        "Paper",
        "Course",
        "Community",
        "Newsletter",
        "Conference",
        "Forum",
        "Journal",
        "Repository",
        "App",
        "Cheatsheet",
        "Documentation",
        "Gallery",
        "Game",
        "Guide",
        "Magazine",
        "Platform",
        "Slides",
        "Social",
        "Tool",
        "Tutorial",
        "Workshop",
    }
)

FIELD_ORDER = ("title", "type", "link", "language", "category", "description", "date")

DESC_MAX_LEN = 300

# Matches every auto-generated placeholder description pattern found in the file.
# A description that does NOT match this regex is treated as real and left alone.
_PLACEHOLDER_RE = re.compile(
    r"""^(
        A\ (blog|book|website|video|paper|course|community|resource|
             journal|newsletter|conference|tool|cheatsheet|code\ repository)
            \ (for|covering)
        |An\ (online\ course|R/Python\ package|R\ package|Python\ package|
               interactive|open-source)
        |Personal\ (website|blog)\ by
        |A\ code\ repository
    )""",
    re.VERBOSE | re.IGNORECASE,
)

# Matches ISO-8601 dates: YYYY-MM-DD, YYYY-MM, or YYYY
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _fetch_page(url: str, downloaded: bytes | str | None = None) -> bytes | str | None:
    if downloaded is not None:
        return downloaded
    try:
        return trafilatura.fetch_url(url)
    except Exception:
        return None


def is_placeholder(desc: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(desc.strip().strip('"')))


def fetch_description(url: str, downloaded: bytes | str | None = None) -> str:
    page = _fetch_page(url, downloaded)
    if not page:
        return ""
    try:
        meta = trafilatura.extract_metadata(page)
        if meta and meta.description:
            desc = meta.description.strip().replace("\n", " ")
            if len(desc) > 20:
                return desc[:DESC_MAX_LEN]
    except Exception as exc:
        print(f"  WARNING: metadata extraction failed: {exc}", file=sys.stderr)
    try:
        text = trafilatura.extract(page)
        if text:
            sentence = text.split(".")[0].strip().replace("\n", " ")
            if len(sentence) > 20:
                return (sentence + ".")[:DESC_MAX_LEN]
    except Exception as exc:
        print(f"  WARNING: text extraction failed: {exc}", file=sys.stderr)
    return ""


def fetch_date(url: str, downloaded: bytes | str | None = None) -> str:
    page = _fetch_page(url, downloaded)
    if not page:
        return ""
    try:
        meta = trafilatura.extract_metadata(page)
        if meta and meta.date:
            date_str = str(meta.date).strip()
            if DATE_RE.match(date_str):
                return date_str
    except Exception as exc:
        print(f"  WARNING: metadata extraction failed: {exc}", file=sys.stderr)
    try:
        import htmldate

        date_str = htmldate.find_date(page, extensive_search=False)
        if date_str and DATE_RE.match(date_str):
            return date_str
    except Exception as exc:
        print(f"  WARNING: date extraction failed: {exc}", file=sys.stderr)
    return ""


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def parse_resources(path: Path) -> list[dict[str, str]]:
    raw = path.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(raw))
    return [
        {f: str(doc.get(f) or "") for f in FIELD_ORDER}
        for doc in docs
        if doc and isinstance(doc, dict)
    ]


def _format_block(entry: dict[str, str]) -> str:
    """Render one entry dict as a YAML block string (without trailing newline)."""
    lines = ["---"]
    for field in FIELD_ORDER:
        value = entry.get(field, "")
        # Escape any embedded double-quotes
        value = value.replace('"', '\\"')
        lines.append(f'{field}: "{value}"')
    lines.append("---")
    return "\n".join(lines)


def write_resources(path: Path, blocks: list[dict[str, str]]) -> None:
    """
    Write *blocks* back to *path* in the exact format of the original file:
    no blank lines between blocks, double-quoted values, fixed field order.
    """
    content = "\n".join(_format_block(b) for b in blocks) + "\n"
    path.write_text(content, encoding="utf-8")


def make_block(
    *,
    title: str,
    type: str,
    link: str,
    language: str,
    category: str,
    description: str = "",
    date: str = "",
) -> dict[str, str]:
    """Build one catalog entry in the canonical field order."""
    return dict(
        zip(
            FIELD_ORDER,
            (title, type, link, language, category, description, date),
            strict=True,
        )
    )


def append_blocks(path: Path, new_blocks: list[dict[str, str]]) -> None:
    """Append *new_blocks* to the end of *path* without rewriting the whole file."""
    if not new_blocks:
        return
    chunk = "\n" + "\n".join(_format_block(b) for b in new_blocks) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(chunk)


def existing_links(path: Path) -> set[str]:
    """Return the set of all link values already in *path*."""
    return {b["link"] for b in parse_resources(path)}
