"""
issue_to_pr.py — turn a "Suggest a resource" issue form body into a clean
resources.txt entry.

Run from scripts/:

    uv run python issue_to_pr.py --body ../body.md

Reads the rendered GitHub issue body (one `### <Field>` header per form
field, as produced by .github/ISSUE_TEMPLATE/suggest-resource.yml), validates
it against the controlled vocabulary, fetches a real description for the
URL, and appends one entry to resources.txt.

Prints one marker line to stdout for the calling workflow to grep:
    ALREADY_PRESENT <url>      — exit 2, link already in resources.txt
    INVALID <reason>           — exit 3, a field failed validation
    DESCRIPTION_PLACEHOLDER    — printed on success when the description
                                  could not be fetched (not an error)
    ADDED "<title>" <url>      — exit 0, entry appended
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import tomllib
from pathlib import Path

from utils import (
    KNOWN_LANGUAGES,
    KNOWN_TYPES,
    append_blocks,
    existing_links,
    fetch_description,
    make_block,
)

TAGS_TOML_PATH = Path(__file__).resolve().parent / "tags.toml"

_NO_RESPONSE = {"", "_no response_", "no response"}


def _load_known_topics() -> set[str]:
    with TAGS_TOML_PATH.open("rb") as fh:
        tags = tomllib.load(fh)
    return set(tags.get("topics", {}).keys())


def _normalise_url(url: str) -> str:
    return url.strip().rstrip("/")


def parse_issue_body(body: str) -> dict[str, str]:
    """
    Split an issue-form body into {field_name_lowercase: raw_section_text}.

    Fields are delimited by GitHub's rendered `### <Label>` headers.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        header = re.match(r"^###\s+(.+?)\s*$", line)
        if header:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = header.group(1).strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_checkboxes(raw: str) -> list[str]:
    """Extract checked `- [X] Label` items from a checkboxes field section."""
    selected = []
    for line in raw.splitlines():
        m = re.match(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", line)
        if m:
            selected.append(m.group(1).strip())
    return selected


def _clean_scalar(raw: str) -> str:
    raw = raw.strip()
    if raw.lower() in _NO_RESPONSE:
        return ""
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a suggestion issue body into a resources.txt entry.")
    parser.add_argument("--body", required=True, metavar="PATH", help="Path to the issue body text file.")
    parser.add_argument("--title", default=None, help="Issue title override (unused by the parser; informational).")
    args = parser.parse_args()

    body_path = Path(args.body)
    if not body_path.exists():
        print(f"INVALID issue body file not found: {body_path}")
        return 3
    body = body_path.read_text(encoding="utf-8")

    resources_path_arg = os.environ.get("RESOURCES_PATH")
    resources_path = Path(resources_path_arg) if resources_path_arg else Path(__file__).resolve().parent.parent / "resources.txt"
    if not resources_path.exists():
        print(f"INVALID resources file not found: {resources_path}")
        return 3

    sections = parse_issue_body(body)

    url = _clean_scalar(sections.get("url", ""))
    title = _clean_scalar(sections.get("title", ""))
    rtype = _clean_scalar(sections.get("type", ""))
    languages = _parse_checkboxes(sections.get("language", ""))
    categories = _parse_checkboxes(sections.get("category", ""))

    if not url:
        print("INVALID missing required field: url")
        return 3
    if not title:
        print("INVALID missing required field: title")
        return 3
    if len(title) > 120:
        print(f"INVALID title exceeds 120 chars ({len(title)})")
        return 3
    if not rtype:
        print("INVALID missing required field: type")
        return 3
    if rtype not in KNOWN_TYPES:
        print(f"INVALID type not in controlled list: {rtype!r}")
        return 3
    if not languages:
        print("INVALID missing required field: language")
        return 3
    bad_languages = [lang for lang in languages if lang not in KNOWN_LANGUAGES]
    if bad_languages:
        print(f"INVALID language value(s) not allowed: {bad_languages}")
        return 3
    if not categories:
        print("INVALID missing required field: category")
        return 3
    known_topics = _load_known_topics()
    bad_categories = [cat for cat in categories if cat not in known_topics]
    if bad_categories:
        print(f"INVALID category value(s) not in tags.toml topics: {bad_categories}")
        return 3

    url_norm = _normalise_url(url)
    known = {_normalise_url(link) for link in existing_links(resources_path)}
    if url_norm in known:
        print(f"ALREADY_PRESENT {url}")
        return 2

    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
    except Exception:
        downloaded = None

    description = fetch_description(url, downloaded=downloaded)
    if not description:
        description = f"A {rtype.lower()} for {title}."
        print("DESCRIPTION_PLACEHOLDER")

    today = datetime.date.today().isoformat()

    block = make_block(
        title=title,
        type=rtype,
        link=url,
        language=";".join(languages),
        category=";".join(categories),
        description=description,
        date=today,
    )
    append_blocks(resources_path, [block])

    print(f'ADDED "{title}" {url}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
