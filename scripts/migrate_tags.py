"""
One-shot migration of resources.txt `category` (and, where needed,
`language`) values onto the finalized vocabulary in scripts/tags.toml.

Steps (see scripts/tags.toml for the vocabulary and PR description for the
full design):
  1. Parse resources.txt preserving the raw text of every block, so blocks
     that end up unchanged are re-emitted byte-identical.
  2. Per entry: drop category values that duplicate the `type` field
     (recording any type/category conflict), drop/move language-shaped
     category values (French/R/Python), drop pure-noise values, then map
     every remaining raw category value onto its canonical topic and dedupe.
  3. If an entry is left with no category (or only "General"), run a
     deterministic keyword scorer over title+description to assign the
     best-matching topic, falling back to "General" below the confidence bar.
  4. Write scripts/reports/tag-assignment-review.csv for every entry whose
     category was touched by the type-conflict or auto-classification path.
  5. Rewrite resources.txt.

Run: cd scripts && uv run python migrate_tags.py
"""

from __future__ import annotations

import csv
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_PATH = ROOT / "resources.txt"
TAGS_TOML_PATH = Path(__file__).resolve().parent / "tags.toml"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
REVIEW_CSV = REPORT_DIR / "tag-assignment-review.csv"

# Score a topic needs to clear to be assigned instead of falling back to
# "General". A single short (1-word) alias hit scores 1 and is not enough on
# its own; two single-word hits, or one multi-word alias hit, clears the bar.
CONFIDENCE_THRESHOLD = 2


def split_semicolon(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(";") if p.strip()]


def dedupe(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def unescape(value: str) -> str:
    return value.replace('\\"', '"')


def escape(value: str) -> str:
    return value.replace('"', '\\"')


# ---------------------------------------------------------------------------
# Raw-text-preserving parser
# ---------------------------------------------------------------------------


class Block:
    def __init__(self, lines: list[str], field_line_idx: dict[str, int]):
        self.lines = lines  # original lines, "---" ... "---" inclusive
        self.field_line_idx = field_line_idx  # field name -> index into self.lines

    def get(self, field: str) -> str:
        idx = self.field_line_idx.get(field)
        if idx is None:
            return ""
        line = self.lines[idx].strip()
        _, _, rest = line.partition(":")
        rest = rest.strip()
        if rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
            rest = rest[1:-1]
        return unescape(rest)

    def set(self, field: str, value: str) -> None:
        idx = self.field_line_idx.get(field)
        if idx is None:
            return
        self.lines[idx] = f'{field}: "{escape(value)}"'

    def render(self) -> str:
        return "\n".join(self.lines)


def parse_blocks(text: str) -> list[Block]:
    lines = text.split("\n")
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() != "---":
            i += 1
            continue
        block_lines = [lines[i]]
        field_line_idx: dict[str, int] = {}
        i += 1
        while i < n and lines[i].strip() != "---":
            stripped = lines[i].strip()
            if stripped and ":" in stripped:
                key = stripped.split(":", 1)[0].strip()
                field_line_idx[key] = len(block_lines)
            block_lines.append(lines[i])
            i += 1
        if i < n and lines[i].strip() == "---":
            block_lines.append(lines[i])
            i += 1
        blocks.append(Block(block_lines, field_line_idx))
    return blocks


# ---------------------------------------------------------------------------
# Keyword auto-classifier
# ---------------------------------------------------------------------------


def build_topic_keywords(topics: dict[str, list[str]]) -> dict[str, list[tuple[re.Pattern, int]]]:
    keywords: dict[str, list[tuple[re.Pattern, int]]] = {}
    for topic, aliases in topics.items():
        if topic == "General":
            continue
        phrases = dedupe([topic, *aliases])
        patterns = []
        for phrase in phrases:
            if not phrase.strip():
                continue
            weight = 2 if " " in phrase.strip() else 1
            pattern = re.compile(r"\b" + re.escape(phrase.lower()) + r"\b")
            patterns.append((pattern, weight))
        keywords[topic] = patterns
    return keywords


def classify(text: str, topic_keywords: dict[str, list[tuple[re.Pattern, int]]]) -> tuple[str, int]:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for topic, patterns in topic_keywords.items():
        score = sum(weight for pattern, weight in patterns if pattern.search(text_lower))
        if score:
            scores[topic] = score
    if not scores:
        return "General", 0
    best_score = max(scores.values())
    candidates = sorted(t for t, s in scores.items() if s == best_score)
    return candidates[0], best_score


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def main() -> None:
    with TAGS_TOML_PATH.open("rb") as fh:
        tags = tomllib.load(fh)

    topics: dict[str, list[str]] = tags["topics"]
    type_migrations: dict[str, dict] = tags["type_migrations"]
    language_migrations: dict[str, dict] = tags["language_migrations"]
    drop_values: set[str] = set(tags["drop"].keys())

    alias_to_topic: dict[str, str] = {}
    for topic, aliases in topics.items():
        alias_to_topic[topic] = topic
        for alias in aliases:
            alias_to_topic[alias] = topic

    topic_keywords = build_topic_keywords(topics)

    text = RESOURCES_PATH.read_text(encoding="utf-8")
    blocks = parse_blocks(text)

    review_rows: list[dict[str, str]] = []
    n_changed = 0
    n_general_entries = 0
    n_general_reassigned = 0
    n_general_kept = 0

    for block in blocks:
        title = block.get("title")
        link = block.get("link")
        desc = block.get("description")
        type_val = block.get("type")
        lang_val = block.get("language")
        cat_val = block.get("category")

        cats = split_semicolon(cat_val)
        is_general_only = cats == ["General"]
        if is_general_only:
            n_general_entries += 1

        # 1. type_migrations: drop any category value that duplicates (or
        #    conflicts with) the `type` field; never overwrite an existing
        #    non-empty type.
        after_type: list[str] = []
        for c in cats:
            if c in type_migrations:
                target = type_migrations[c]["type"]
                if type_val != target:
                    review_rows.append(
                        {
                            "link": link,
                            "title": title,
                            "old_category": cat_val,
                            "new_category": f"(kept type={type_val}, dropped tag '{c}')",
                            "score": "",
                            "confident": "n/a",
                            "reason": "type_conflict",
                        }
                    )
                continue  # duplicate or conflict: drop the tag either way
            after_type.append(c)

        # 2. language_migrations: move/drop language-shaped category values.
        lang_list = dedupe(split_semicolon(lang_val))
        after_lang: list[str] = []
        add_french = False
        for c in after_type:
            if c in language_migrations:
                if language_migrations[c]["action"] == "move_to_language":
                    add_french = True
                continue
            after_lang.append(c)
        if add_french and "French" not in lang_list:
            lang_list.append("French")

        # 3. drop pure-noise values.
        after_drop = [c for c in after_lang if c not in drop_values]

        # 4. map remaining raw values onto canonical topics, dedupe.
        final_cats = dedupe(alias_to_topic.get(c, c) for c in after_drop)

        # 5. auto-classify if the entry has no tag, or only the fallback tag.
        if not final_cats or final_cats == ["General"]:
            best_topic, score = classify(f"{title} {desc}", topic_keywords)
            confident = score >= CONFIDENCE_THRESHOLD
            new_topic = best_topic if confident else "General"
            review_rows.append(
                {
                    "link": link,
                    "title": title,
                    "old_category": cat_val,
                    "new_category": new_topic,
                    "score": str(score),
                    "confident": "yes" if confident else "no",
                    "reason": "auto_classify",
                }
            )
            if is_general_only:
                if new_topic != "General":
                    n_general_reassigned += 1
                else:
                    n_general_kept += 1
            final_cats = [new_topic]

        new_cat_val = ";".join(final_cats)
        new_lang_val = ";".join(lang_list)

        if new_cat_val != cat_val or new_lang_val != lang_val:
            n_changed += 1
            if new_cat_val != cat_val:
                block.set("category", new_cat_val)
            if new_lang_val != lang_val:
                block.set("language", new_lang_val)

    # --- write resources.txt ---
    new_text = "\n".join(block.render() for block in blocks) + "\n"
    RESOURCES_PATH.write_text(new_text, encoding="utf-8")

    # --- write review csv ---
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["link", "title", "old_category", "new_category", "score", "confident", "reason"],
        )
        writer.writeheader()
        writer.writerows(review_rows)

    print(f"Entries parsed               : {len(blocks)}")
    print(f"Entries changed               : {n_changed}")
    print(f"Confidence threshold          : {CONFIDENCE_THRESHOLD}")
    print(f'"General"-only entries        : {n_general_entries}')
    print(f"  reassigned to a real topic  : {n_general_reassigned}")
    print(f"  kept as General             : {n_general_kept}")
    print(f"Review rows written           : {len(review_rows)} -> {REVIEW_CSV}")


if __name__ == "__main__":
    main()
