"""
Read-only audit of the `category` field across resources.txt.

Outputs:
  - scripts/reports/tags-report.csv : one row per distinct category value
    (count, share of entries, whether it collides with a KNOWN_TYPES value)
  - stdout: concise summary (counts, variant-group detection, "General"-only
    entries, type-shaped leak list)

Does not modify resources.txt or any other file.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from utils import KNOWN_TYPES, parse_resources

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_PATH = ROOT / "resources.txt"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
REPORT_CSV = REPORT_DIR / "tags-report.csv"


def split_categories(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(";") if p.strip()]


def normalize_key(tag: str) -> str:
    """Collapse case/punctuation/plural variants onto one key for grouping."""
    key = tag.lower()
    key = re.sub(r"[-_/]+", " ", key)
    key = re.sub(r"[^a-z0-9 ]", "", key)
    key = re.sub(r"\s+", " ", key).strip()
    if key.endswith("ies") and len(key) > 4:
        key = key[:-3] + "y"
    elif key.endswith("s") and not key.endswith("ss") and len(key) > 3:
        key = key[:-1]
    return key


def main() -> None:
    records = parse_resources(RESOURCES_PATH)
    total_entries = len(records)

    tag_counts: Counter[str] = Counter()
    only_general = 0
    general_with_others = 0
    empty_category = 0

    for rec in records:
        raw_cat = rec.get("category", "")
        tags = split_categories(raw_cat)
        if not tags:
            empty_category += 1
            continue
        if tags == ["General"]:
            only_general += 1
        elif "General" in tags:
            general_with_others += 1
        for t in tags:
            tag_counts[t] += 1

    distinct_tags = len(tag_counts)
    singletons = sum(1 for c in tag_counts.values() if c == 1)

    # variant groups: normalize_key collisions among >=2 distinct raw tags
    groups: dict[str, list[str]] = defaultdict(list)
    for tag in tag_counts:
        groups[normalize_key(tag)].append(tag)
    variant_groups = {k: v for k, v in groups.items() if len(v) > 1}

    # type-shaped leaks: category values that equal (case-insensitively) a
    # KNOWN_TYPES entry
    known_types_lower = {t.lower(): t for t in KNOWN_TYPES}
    type_leaks = {
        tag: count
        for tag, count in tag_counts.items()
        if tag.lower() in known_types_lower
    }

    # language-leak check: "French" appears both as category and as a
    # language value
    language_values: Counter[str] = Counter()
    for rec in records:
        lang_raw = rec.get("language", "")
        for lang in split_categories(lang_raw):
            language_values[lang] += 1

    # --- write CSV ---
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["category", "count", "share_of_entries", "is_type_shaped", "variant_group"])
        for tag, count in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            share = count / total_entries if total_entries else 0.0
            is_type = tag.lower() in known_types_lower
            group_key = normalize_key(tag)
            group = ";".join(sorted(variant_groups.get(group_key, []))) if group_key in variant_groups else ""
            writer.writerow([tag, count, f"{share:.4f}", is_type, group])

    # --- stdout summary ---
    print(f"Total entries parsed        : {total_entries}")
    print(f"Entries with empty category : {empty_category}")
    print(f"Distinct category values    : {distinct_tags}")
    print(f"  used exactly once         : {singletons}")
    print(f'Entries whose ONLY tag is "General"       : {only_general}')
    print(f'Entries with "General" + other tag(s)     : {general_with_others}')
    print()
    print("Top categories:")
    for tag, count in tag_counts.most_common(15):
        print(f"  {tag!r:28s} x{count}")
    print()
    print(f"Variant groups detected ({len(variant_groups)}):")
    for key, variants in sorted(variant_groups.items(), key=lambda kv: -sum(tag_counts[v] for v in kv[1]))[:30]:
        counts_str = ", ".join(f"{v!r}={tag_counts[v]}" for v in sorted(variants, key=lambda v: -tag_counts[v]))
        print(f"  [{key}] {counts_str}")
    print()
    print(f"Type-shaped category leaks ({len(type_leaks)} distinct, i.e. category values that duplicate a `type`):")
    for tag, count in sorted(type_leaks.items(), key=lambda kv: -kv[1]):
        print(f"  {tag!r:16s} x{count}")
    print()
    french_cat = tag_counts.get("French", 0)
    french_lang = language_values.get("French", 0)
    other_lang = language_values.get("Other", 0)
    print(f'"French" as category: {french_cat}   "French" as language: {french_lang}')
    print(f'"Other" as language : {other_lang}')
    empty_desc = sum(1 for rec in records if not rec.get("description", "").strip())
    print(f"Entries with empty description: {empty_desc}")


if __name__ == "__main__":
    main()
