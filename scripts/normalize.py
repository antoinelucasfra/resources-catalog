"""
normalize.py — bring resources.txt metadata back to the documented schema.

Deterministic, offline fixes only (no HTTP): URL cleanup, duplicate removal,
`type` remap onto the current vocabulary, facet de-duplication, description
cleanup that hands broken text back to backfill.py, and date validation.

Run from scripts/:

    uv run python normalize.py            # dry run: report only
    uv run python normalize.py --apply    # rewrite resources.txt

Exit code is 0 unless the file could not be parsed. Network work belongs to
backfill.py (`--mode both`); this script must stay safe to re-run any time.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import utils
from utils import DATE_RE, DESC_MAX_LEN, KNOWN_LANGUAGES, KNOWN_TYPES

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_PATH = Path(os.environ.get("RESOURCES_PATH", ROOT / "resources.txt"))

# Previous `type` values remapped onto the 12-value vocabulary in utils.py.
# A "Book hosted on GitHub" stays a Book: only the kind of resource decides the
# type, never the host.
LEGACY_TYPE_MAP = {
    "Social": "Community",
    "Forum": "Community",
    "Conference": "Community",
    "Newsletter": "Blog",
    "Magazine": "Blog",
    "App": "Tool",
    "Platform": "Tool",
    "Tutorial": "Course",
    "Workshop": "Course",
    "Guide": "Documentation",
    "Cheatsheet": "Documentation",
    "Slides": "Documentation",
    "Journal": "Paper",
    "Game": "Other",
    "Gallery": "Other",
}

WHITESPACE = re.compile(r"\s+")
# Complete tags, plus a tag cut in half by a length cap ("...production<str").
HTML_TAG = re.compile(r"<[^>]*>?")
# A parked/expired domain says nothing about the resource.
DOI_JUNK = re.compile(
    r"(domain (may be|is) for sale|buy this domain|this domain has expired|sedo)",
    re.IGNORECASE,
)


def split_values(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(";") if part.strip()]


def clean_description(description: str) -> str:
    # A scrape that double-escaped its quotes stores \" and renders as \" on
    # the card; the parsed value only ever needs the quote itself.
    text = description.replace('\\"', '"')
    text = WHITESPACE.sub(" ", HTML_TAG.sub(" ", text)).strip()
    if len(text) < 20 or DOI_JUNK.search(text):
        return ""
    if len(text) > DESC_MAX_LEN:
        # Cut on a word boundary instead of mid-token; no ellipsis, so the
        # truncated-description report stays reserved for scraped mid-sentences.
        text = text[: DESC_MAX_LEN + 1]
        cut = text.rfind(" ")
        text = (text[:cut] if cut > 0 else text[:DESC_MAX_LEN]).rstrip(",;:")
    return text


def clean_text(value: str) -> str:
    return WHITESPACE.sub(" ", value).strip()


def normalize_entry(entry: dict[str, str], changes: defaultdict[str, int]) -> dict[str, str]:
    out = dict(entry)

    out["title"] = clean_text(out["title"])

    original_link = out["link"].strip()
    out["link"] = utils.clean_url(out["link"])
    if out["link"] != original_link:
        changes["url: normalized"] += 1

    raw_type = out["type"].strip()
    mapped = LEGACY_TYPE_MAP.get(raw_type, raw_type)
    if mapped not in KNOWN_TYPES:
        # Unknown value: keep it loud in the report instead of guessing.
        changes["type: UNKNOWN (left as-is)"] += 1
    elif mapped != raw_type:
        changes[f"type: {raw_type} -> {mapped}"] += 1
    out["type"] = mapped

    languages = []
    for token in split_values(out["language"]):
        canonical = next((known for known in KNOWN_LANGUAGES if known.lower() == token.lower()), None)
        if canonical is None:
            changes["language: UNKNOWN (left as-is)"] += 1
            canonical = token
        if canonical not in languages:
            languages.append(canonical)
    out["language"] = ";".join(languages)

    categories = []
    for token in split_values(out["category"]):
        if token not in categories:
            categories.append(token)
    out["category"] = ";".join(categories) or "General"

    before = out["description"]
    out["description"] = clean_description(before)
    if out["description"] != before.strip():
        changes["description: cleaned"] += 1
    if out["description"].endswith("..."):
        # Mid-sentence scrape. Blanking it here would lose the fragment if the
        # refetch fails, so report it and let `backfill.py --force --urls`
        # replace it only when a better description comes back.
        changes["description: truncated (refetch with --force)"] += 1

    date = out["date"].strip()
    if date and not DATE_RE.match(date):
        changes["date: malformed (cleared)"] += 1
        date = ""
    out["date"] = date

    return out


def main() -> int:
    utils.enable_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", metavar="PATH", help=f"resources.txt (default: {RESOURCES_PATH})")
    parser.add_argument("--apply", action="store_true", help="rewrite the file instead of reporting")
    parser.add_argument("--check", action="store_true", help="exit 1 when the file is not normalized (CI gate)")
    args = parser.parse_args()

    path = Path(args.path) if args.path else RESOURCES_PATH
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1

    blocks = utils.parse_resources(path)
    print(f"Resources file: {path}")
    print(f"Entries: {len(blocks)}")

    changes: defaultdict[str, int] = defaultdict(int)
    normalized = []
    for entry in blocks:
        new = normalize_entry(entry, changes)
        if any(new[f] != entry[f] for f in ("language", "category", "description", "date")):
            changes["entry: facet field changed"] += 1
        normalized.append(new)

    # Duplicate URLs: keep the entry carrying the most metadata, then the longest
    # description, then the earliest occurrence (stable output).
    seen: dict[str, int] = {}
    kept: list[dict[str, str]] = []
    dropped_rows: list[tuple[str, str]] = []
    for entry in normalized:
        key = utils.catalog_dedupe_key(entry["link"])
        if key not in seen:
            seen[key] = len(kept)
            kept.append(entry)
            continue
        index = seen[key]
        incumbent = kept[index]
        score_new = (sum(1 for v in entry.values() if v), len(entry["description"]))
        score_old = (sum(1 for v in incumbent.values() if v), len(incumbent["description"]))
        if score_new > score_old:
            dropped_rows.append((incumbent["title"], incumbent["link"]))
            kept[index] = entry
        else:
            dropped_rows.append((entry["title"], entry["link"]))
    if dropped_rows:
        changes["link: duplicate rows merged"] += len(dropped_rows)

    print("\n=== Changes ===")
    if not changes:
        print("  nothing to do")
    for label, count in sorted(changes.items()):
        print(f"  {count:5d}  {label}")
    if dropped_rows:
        print("\n  merged duplicates (dropped -> kept the other row):")
        for title, link in dropped_rows[:25]:
            print(f"    {link}")
        if len(dropped_rows) > 25:
            print(f"    ... and {len(dropped_rows) - 25} more")

    print(f"\nResult: {len(kept)} entries (was {len(blocks)})")

    if args.check:
        changed = len(kept) != len(blocks) or any(
            new != old for new, old in zip(kept, blocks, strict=False)
        )
        if changed:
            print("Not normalized: run `uv run python normalize.py --apply`.")
            return 1
        print("Normalized.")
        return 0

    if not args.apply:
        print("Dry run: pass --apply to rewrite the file.")
        return 0

    utils.write_resources(path, kept)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
