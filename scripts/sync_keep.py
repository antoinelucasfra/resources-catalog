"""
sync_keep.py — manual sync of a Google Keep curation note into resources.txt.

Run it yourself when you have a batch of resources to add; there is no scheduled
Actions job.

Reads a designated Google Keep note, parses each line as a resource entry,
fetches a real description via trafilatura, deduplicates against the existing
resources.txt, appends new entries, then clears processed lines from the note.

Environment variables (export before running):
    KEEP_EMAIL          Gmail address used for authentication
    KEEP_MASTER_TOKEN   Master token obtained via gpsoauth (see CONTRIBUTING.md)
    KEEP_NOTE_TITLE     Exact title of the Keep note used as the curation inbox
    RESOURCES_PATH      Absolute path to resources.txt
                        (e.g. ../resources.txt when run from scripts/)

Keep note line format (one resource per line, 5 fields separated by " - "):
    https://example.com - Resource Title - Book - R - Statistics;Tutorial

Lines that are malformed or reference unknown types are left in the note so
they can be fixed manually on the next run.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import gkeepapi
import trafilatura

from utils import (
    KNOWN_TYPES,
    append_blocks,
    existing_links,
    fetch_date,
    fetch_description,
    make_block,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEPARATOR = " - "


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: environment variable {name!r} is not set.", file=sys.stderr)
        sys.exit(1)
    return value


def _parse_line(line: str) -> dict[str, str] | None:
    """
    Parse one Keep note line into a resource dict.

    Returns None if the line is malformed (wrong field count, bad URL, unknown type).
    Returns a dict with keys: url, title, type, language, category,
    plus 'error' if invalid (so the caller knows to keep it in the note).
    """
    parts = [p.strip() for p in line.split(SEPARATOR)]
    if len(parts) != 5:
        return {
            "error": f"expected 5 fields separated by ' - ', got {len(parts)}",
            "raw": line,
        }

    url, title, rtype, language, category = parts

    if not url.lower().startswith("http"):
        return {"error": f"field 1 does not look like a URL: {url!r}", "raw": line}

    if rtype not in KNOWN_TYPES:
        known = ", ".join(sorted(KNOWN_TYPES))
        return {"error": f"unknown type {rtype!r}. Valid values: {known}", "raw": line}

    return {
        "url": url,
        "title": title,
        "type": rtype,
        "language": language,
        "category": category,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    email = _env("KEEP_EMAIL")
    master_token = _env("KEEP_MASTER_TOKEN")
    note_title = _env("KEEP_NOTE_TITLE")
    resources_path = Path(_env("RESOURCES_PATH"))

    if not resources_path.exists():
        print(f"ERROR: resources file not found: {resources_path}", file=sys.stderr)
        sys.exit(1)

    # -- Authenticate --------------------------------------------------------
    print("Authenticating with Google Keep ...")
    keep = gkeepapi.Keep()
    try:
        keep.authenticate(email, master_token)
    except Exception as exc:
        print(f"ERROR: authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # -- Find the note -------------------------------------------------------
    results = list(keep.find(query=note_title, archived=False, trashed=False))
    note = next((n for n in results if n.title.strip() == note_title), None)

    if note is None:
        print(f"ERROR: no Keep note with title {note_title!r} found.", file=sys.stderr)
        sys.exit(1)

    raw_text = (note.text or "").strip()
    if not raw_text:
        print("Note is empty — nothing to do.")
        return

    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    print(f"Found {len(lines)} line(s) in note '{note_title}'")

    # -- Load existing links for dedup ---------------------------------------
    known = existing_links(resources_path)

    # -- Process each line ---------------------------------------------------
    kept_lines: list[str] = []  # lines that stay in the note (invalid)
    new_blocks: list[dict[str, str]] = []

    for line in lines:
        parsed = _parse_line(line)

        # Malformed line — keep in note, report
        if parsed is None or "error" in parsed:
            kept_lines.append(line)
            print(f"  SKIP  {line!r} — {(parsed or {}).get('error', 'parse error')}")
            continue

        url = parsed["url"]

        # Duplicate — silently drop from note (already in catalog)
        if url in known:
            print(f"  DUP   {url}")
            continue

        # Fetch page once — reuse downloaded HTML for both description and date
        print(f"  FETCH {url}")
        try:
            downloaded = trafilatura.fetch_url(url)
        except Exception:
            downloaded = None
        time.sleep(0.5)  # polite delay

        new_blocks.append(
            make_block(
                title=parsed["title"],
                type=parsed["type"],
                link=url,
                language=parsed["language"],
                category=parsed["category"],
                description=fetch_description(url, downloaded=downloaded),
                date=fetch_date(url, downloaded=downloaded),
            )
        )
        known.add(url)  # prevent within-run duplicates

    # -- Append new entries --------------------------------------------------
    if new_blocks:
        print(
            f"\nAppending {len(new_blocks)} new entry/entries to {resources_path} ..."
        )
        append_blocks(resources_path, new_blocks)
    else:
        print("\nNo new entries to append.")

    # -- Update the Keep note ------------------------------------------------
    note.text = "\n".join(kept_lines)
    keep.sync()
    remaining = len(kept_lines)
    print(f"Keep note updated — {remaining} line(s) remaining (invalid/unfixed).")


if __name__ == "__main__":
    main()
