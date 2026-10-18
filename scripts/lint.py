"""
Validate resources.txt against the tag vocabulary in scripts/tags.toml and
basic structural rules.

Taxonomy rules (required fields present, `type` in the controlled list,
`language` in the controlled list, `category` non-empty and every value a
tags.toml topic, no language-shaped value in `category`) are hard errors:
exit code 1 on any violation, in default mode and --strict alike.

Pre-existing data-hygiene rules (empty/overlong `description`, duplicate
`link`) are printed as warnings and do not affect the exit code in default
mode; pass --strict to treat them as errors too (used once the hygiene
backfill/dedup workstream has cleaned the data).

Each line is printed as:
  line <n> of block starting <line>: <rule> — <value>
(warnings are prefixed with "WARNING: ")

Does not modify resources.txt or any other file.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_PATH = ROOT / "resources.txt"
TAGS_TOML_PATH = Path(__file__).resolve().parent / "tags.toml"

REQUIRED_FIELDS = ("title", "type", "link", "language", "category", "description")
HARD_REQUIRED_FIELDS = ("title", "type", "link", "language", "category")
OPTIONAL_FIELDS = ("date",)
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

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

KNOWN_LANGUAGES: frozenset[str] = frozenset({"R", "Python", "Other", "French", "JavaScript", "Julia"})
LANGUAGE_SHAPED_CATEGORY_VALUES: frozenset[str] = frozenset({"R", "Python", "French"})

DESC_MAX_LEN = 300


def split_semicolon(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(";") if p.strip()]


def unescape(value: str) -> str:
    return value.replace('\\"', '"')


def parse_blocks(text: str) -> list[dict]:
    """Parse resources.txt into blocks, each carrying its 1-indexed start line
    and a dict of field -> (value, line_number)."""
    lines = text.split("\n")
    blocks: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() != "---":
            i += 1
            continue
        start_line = i + 1  # 1-indexed
        i += 1
        fields: dict[str, tuple[str, int]] = {}
        while i < n and lines[i].strip() != "---":
            line = lines[i]
            stripped = line.strip()
            if stripped:
                if ":" in stripped:
                    key, _, rest = stripped.partition(":")
                    key = key.strip()
                    rest = rest.strip()
                    if rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
                        rest = rest[1:-1]
                    fields[key] = (unescape(rest), i + 1)
            i += 1
        # consume closing "---"
        if i < n and lines[i].strip() == "---":
            i += 1
        blocks.append({"start_line": start_line, "fields": fields})
    return blocks


def normalize_link(link: str) -> str:
    return link.strip().rstrip("/").lower()


def main() -> int:
    with TAGS_TOML_PATH.open("rb") as fh:
        tags = tomllib.load(fh)
    known_topics: set[str] = set(tags.get("topics", {}).keys())

    text = RESOURCES_PATH.read_text(encoding="utf-8")
    blocks = parse_blocks(text)

    violations: list[str] = []
    warnings: list[str] = []
    seen_links: dict[str, int] = {}

    for block in blocks:
        start = block["start_line"]
        fields = block["fields"]

        def error(line: int, rule: str, value: str) -> None:
            violations.append(f"line {line} of block starting {start}: {rule} — {value}")

        def warn(line: int, rule: str, value: str) -> None:
            warnings.append(f"line {line} of block starting {start}: {rule} — {value}")

        # --- taxonomy rules: hard errors, always enforced ---
        for field in HARD_REQUIRED_FIELDS:
            if field not in fields or not fields[field][0].strip():
                error(start, f"missing/empty required field '{field}'", "<empty>")

        if "type" in fields:
            value, line = fields["type"]
            if value and value not in KNOWN_TYPES:
                error(line, "type not in controlled list", value)

        if "language" in fields:
            value, line = fields["language"]
            for lang in split_semicolon(value):
                if lang not in KNOWN_LANGUAGES:
                    error(line, "language value not allowed", lang)

        if "category" in fields:
            value, line = fields["category"]
            cats = split_semicolon(value)
            if not cats:
                error(line, "category must be non-empty", "<empty>")
            for cat in cats:
                if cat in LANGUAGE_SHAPED_CATEGORY_VALUES:
                    error(line, "category contains language-shaped value (belongs in language)", cat)
                elif cat not in known_topics:
                    error(line, "category value not in tags.toml topics", cat)

        # --- pre-existing data-hygiene rules: warnings by default, errors in --strict ---
        if "description" not in fields or not fields["description"][0].strip():
            warn(start, "missing/empty field 'description'", "<empty>")
        elif len(fields["description"][0]) > DESC_MAX_LEN:
            value, line = fields["description"]
            warn(line, f"description exceeds {DESC_MAX_LEN} chars", f"{len(value)} chars")

        if "link" in fields:
            value, line = fields["link"]
            if value:
                key = normalize_link(value)
                if key in seen_links:
                    warn(
                        line,
                        f"duplicate link (first seen at block starting {seen_links[key]})",
                        value,
                    )
                else:
                    seen_links[key] = start

    strict = "--strict" in sys.argv[1:]

    for v in violations:
        print(v)
    for w in warnings:
        print(f"WARNING: {w}")

    if violations:
        print(f"\n{len(violations)} error(s), {len(warnings)} warning(s).", file=sys.stderr)
        return 1
    if warnings:
        print(f"\n0 errors, {len(warnings)} warning(s) (pre-existing data hygiene, not taxonomy).", file=sys.stderr)
        if strict:
            return 1
        return 0

    print(f"OK: {len(blocks)} entries, 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
