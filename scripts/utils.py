"""
Shared utilities for sync_keep.py, backfill.py and make_covers.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import trafilatura
import trafilatura.settings
import yaml
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "Blog",
        "Book",
        "Community",
        "Course",
        "Documentation",
        "Other",
        "Package",
        "Paper",
        "Repository",
        "Tool",
        "Video",
        "Website",
    }
)

KNOWN_LANGUAGES: frozenset[str] = frozenset(
    {"R", "Python", "Other", "French", "Julia", "JavaScript"}
)

# Query parameters that only track the visitor; they never identify the resource.
TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|igshid|ref_src|ref_url|_hsenc|_hsmi)$",
    re.IGNORECASE,
)

# Pasted-markdown accident: "https://a.org](https://a.org/)".
MARKDOWN_LINK = re.compile(r"^(https?://[^\s\]]+)\]\((https?://[^\s)]+)\)$")

FIELD_ORDER = ("title", "type", "link", "language", "category", "description", "date")
OPTIONAL_FIELDS = ("description", "date")

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


def enable_utf8_output() -> None:
    """Windows consoles default to cp1252: printing a title with an em dash then
    raises UnicodeEncodeError and kills a long-running run. Call from main()."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# Bounded fetch: trafilatura defaults to a 30 s timeout, a 20 MB cap and a 5 s
# politeness sleep per request, so one unreachable host costs a minute and one
# large PDF more than the rest of the run. Callers that want spacing do it
# themselves (backfill.py --workers and _FETCH_DELAY).
_FETCH_CONFIG = trafilatura.settings.use_config()
_FETCH_CONFIG.set("DEFAULT", "DOWNLOAD_TIMEOUT", "10")
_FETCH_CONFIG.set("DEFAULT", "MAX_FILE_SIZE", "2000000")
_FETCH_CONFIG.set("DEFAULT", "SLEEP_TIME", "0")


def fetch_page(url: str) -> bytes | str | None:
    """Download *url* under the bounded timeout and size (see _FETCH_CONFIG)."""
    try:
        return trafilatura.fetch_url(url, config=_FETCH_CONFIG)
    except Exception:
        return None


# Sent to the fetchers to mean "no page was attempted yet", as opposed to None
# which means "the attempt already failed, do not try again".
_NO_DOWNLOAD = object()


def _fetch_page(url: str, downloaded: object = _NO_DOWNLOAD) -> bytes | str | None:
    if downloaded is not _NO_DOWNLOAD:
        return downloaded  # type: ignore[return-value]
    return fetch_page(url)


def is_placeholder(desc: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(desc.strip().strip('"')))


def fetch_description(url: str, downloaded: object = _NO_DOWNLOAD) -> str:
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


def fetch_date(url: str, downloaded: object = _NO_DOWNLOAD) -> str:
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
    """Render one entry dict as a YAML block string (without trailing newline).

    Required fields are always written; optional ones (description, date) are
    omitted while empty, which is how the pre-existing entries are formatted.
    """
    lines = ["---"]
    for field in FIELD_ORDER:
        value = entry.get(field, "")
        if field in OPTIONAL_FIELDS and not value.strip():
            continue
        # Escape backslashes first so later quote-escaping can't turn a literal
        # backslash into a YAML escape sequence (e.g. C:\temp → "C:\itemp").
        value = value.replace("\\", "\\\\")
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
    # newline="\n": the repo is LF-only; text mode would write CRLF on Windows
    # and churn every line of the file.
    path.write_text(content, encoding="utf-8", newline="\n")


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
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(chunk)


def existing_links(path: Path) -> set[str]:
    """Return the set of all link values already in *path*."""
    return {b["link"] for b in parse_resources(path)}


def catalog_dedupe_key(url: str) -> str:
    """Identity of a resource for duplicate detection: scheme, `www.`, a
    trailing slash and the fragment are presentation, not identity."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query)))
    return f"{host}{path}{'?' + query if query else ''}"


def clean_url(url: str) -> str:
    """Strip tracking parameters and repair pasted-markdown links. Returns the
    input unchanged when it does not parse as an absolute URL."""
    url = MARKDOWN_LINK.sub(r"\2", url.strip())
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.scheme or not parsed.netloc:
        return url
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            urlencode(kept),
            parsed.fragment,
        )
    )
