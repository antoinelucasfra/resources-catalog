"""
retire.py — remove one resource entry from resources.txt by its link.

Used by maintainers after a link-health report confirms a URL is dead
(matching is trailing-slash and case-insensitive, like lint.py's
normalize_link). Deletes the whole `---` block in place and prints
`REMOVED "<title>" <link>`; exit 0. Unknown link → `NOT_FOUND <link>`,
exit 1. Never touches anything else in the file.

Run from scripts/:
    uv run python retire.py --link "https://example.com/dead-page"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_link(link: str) -> str:
    return link.strip().rstrip("/").lower()


def find_block_line_ranges(text: str) -> list[tuple[int, int, dict[str, str]]]:
    """Return (start_index, end_index_exclusive, fields) for each `---` block.
    Indices are 0-based line indexes into text.split('\\n')."""
    lines = text.split("\n")
    blocks: list[tuple[int, int, dict[str, str]]] = []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip() != "---":
            i += 1
            continue
        start = i
        i += 1
        fields: dict[str, str] = {}
        while i < n and lines[i].strip() != "---":
            stripped = lines[i].strip()
            if ":" in stripped:
                key, _, rest = stripped.partition(":")
                rest = rest.strip()
                if rest.startswith('"') and rest.endswith('"') and len(rest) >= 2:
                    rest = rest[1:-1]
                fields[key.strip()] = rest.replace('\\"', '"')
            i += 1
        if i < n and lines[i].strip() == "---":
            end = i + 1
            blocks.append((start, end, fields))
            i += 1
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one resource block from resources.txt by link.")
    parser.add_argument("--link", required=True, help="link of the entry to remove (trailing-slash-insensitive)")
    parser.add_argument(
        "--path",
        default=os.environ.get("RESOURCES_PATH", str(ROOT / "resources.txt")),
        help="path to resources.txt (default: RESOURCES_PATH env or repo root)",
    )
    args = parser.parse_args()

    path = Path(args.path)
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    target = normalize_link(args.link)
    matching = [
        (start, end, fields)
        for start, end, fields in find_block_line_ranges(text)
        if normalize_link(fields.get("link", "")) == target
    ]
    if not matching:
        print(f"NOT_FOUND {args.link}")
        return 1
    if len(matching) > 1:
        print(f"ERROR: {len(matching)} blocks match {args.link}; refusing to delete more than one.", file=sys.stderr)
        return 1

    start, end, fields = matching[0]
    title = fields.get("title", "<untitled>")
    del lines[start:end]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f'REMOVED "{title}" {args.link}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
