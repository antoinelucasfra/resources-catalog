"""
backfill.py — manage resources.txt: validate entries, backfill missing
dates/descriptions, add new URLs (fetch metadata, classify, dedupe, append).

Run from scripts/:

    cd scripts/
    uv sync
    uv run python backfill.py --help

Usage, options and examples: `uv run python backfill.py --help`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import trafilatura

from utils import (
    DATE_RE,
    FIELD_ORDER,
    KNOWN_TYPES,
    append_blocks,
    existing_links,
    fetch_date,
    fetch_description,
    is_placeholder,
    make_block,
    parse_resources,
    write_resources,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Polite delay between HTTP requests (seconds)
_FETCH_DELAY = 0.4

# ---------------------------------------------------------------------------
# Auto-classification heuristics for new URLs
# ---------------------------------------------------------------------------

# Maps (domain_fragment, path_fragment) → (type, language, category)
# Rules are checked in order; first match wins.
_CLASSIFICATION_RULES: list[tuple[str, str, str, str, str]] = [
    # (domain_contains, path_contains, type, language, category)
    # --- Repositories / code hosts ---
    ("gist.github.com", "", "Repository", "Other", "General"),
    ("github.com", "", "Repository", "Other", "General"),
    ("gitlab.com", "", "Repository", "Other", "General"),
    # --- HuggingFace ---
    ("huggingface.co", "/spaces/", "Website", "Python", "Machine Learning"),
    ("huggingface.co", "/blog/", "Blog", "Python", "Machine Learning"),
    ("huggingface.co", "/docs/", "Website", "Python", "Machine Learning"),
    ("huggingface.co", "", "Website", "Python", "Machine Learning"),
    # --- App stores ---
    ("apps.apple.com", "", "Website", "Other", "General"),
    # --- VSCode marketplace ---
    ("marketplace.visualstudio.com", "", "Website", "Other", "Development"),
    # --- R-specific blog / documentation sites ---
    ("r-bloggers.com", "", "Blog", "R", "General"),
    ("rviews.rstudio.com", "", "Blog", "R", "General"),
    ("posit.co", "/blog/", "Blog", "R", "General"),
    ("posit.co", "", "Website", "R", "General"),
    ("tidyverse.org", "", "Website", "R", "General"),
    ("rstudio.com", "", "Website", "R", "General"),
    ("rfortherestofus.com", "", "Blog", "R", "General"),
    ("r-project.org", "", "Website", "R", "General"),
    ("thinkr.fr", "", "Blog", "R", "General"),
    ("r-lib.org", "", "Website", "R", "General"),
    ("emilyriederer.com", "", "Blog", "R", "General"),
    ("dominicroye.github.io", "", "Website", "R", "Visualization"),
    ("walker-data.com", "", "Website", "R", "GIS"),
    ("productive-r-workflow.com", "", "Website", "R", "Tutorial"),
    ("lindeloev.github.io", "", "Website", "R", "Statistics"),
    ("cynkra.github.io", "", "Website", "R", "General"),
    ("futurize.futureverse.org", "", "Website", "R", "General"),
    ("ragnar.tidyverse.org", "", "Website", "R", "General"),
    ("indrajeetpatil.github.io", "", "Website", "R", "Packages"),
    ("rwarehouse.netlify.app", "", "Website", "R", "General"),
    ("ggsql.org", "", "Website", "R", "General"),
    # --- Python-specific ---
    ("py-pkgs.org", "", "Book", "Python", "Packages"),
    ("docs.langchain.com", "", "Website", "Python", "Machine Learning"),
    ("probabl.ai", "", "Blog", "Python", "Machine Learning"),
    # --- Posit/Quarto/R tooling ---
    ("posit-dev.github.io", "", "Website", "R", "General"),
    ("quarto.org", "", "Website", "Other", "General"),
    ("opencode.ai", "", "Website", "Other", "Development"),
    # --- Shiny ---
    ("shinyapps.io", "", "Website", "R", "Shiny"),
    ("connect.posit.cloud", "", "Website", "R", "Shiny"),
    ("pub.current.posit.team", "", "Website", "R", "Shiny"),
    ("blockr.cloud", "", "Website", "R", "Shiny"),
    ("bristolmyerssquibb.github.io", "", "Website", "R", "Shiny"),
    # --- Data science / ML ---
    ("developer.nvidia.com", "", "Website", "Other", "Machine Learning"),
    ("databrickslabs.github.io", "", "Website", "Python", "Machine Learning"),
    ("agents.md", "", "Website", "Other", "Machine Learning"),
    ("modelcontextprotocol.io", "", "Website", "Other", "Machine Learning"),
    ("bmad-method.org", "", "Website", "Other", "Machine Learning"),
    # --- French tech blogs ---
    ("korben.info", "", "Blog", "Other", "General"),
    ("mathieugrenier.fr", "", "Blog", "Other", "General"),
    ("sspcloud.fr", "", "Website", "R", "General"),
    ("ssm-agriculture.github.io", "", "Website", "R", "General"),
    # --- Communities / forums ---
    ("lobste.rs", "", "Community", "Other", "Development"),
    ("news.ycombinator.com", "", "Community", "Other", "General"),
    ("reddit.com", "", "Community", "Other", "General"),
    # --- Personal / portfolio sites ---
    ("henry.codes", "", "Blog", "Other", "General"),
    ("mbuffett.com", "", "Blog", "Other", "General"),
    ("bioinfo.kaibitz.com", "", "Website", "Other", "Bioinformatics"),
    ("gexijin.github.io", "", "Website", "R", "Bioinformatics"),
    # --- Data / art / other ---
    ("data-to-art.com", "", "Website", "Other", "Visualization"),
    ("datanovia.com", "", "Website", "R", "Statistics"),
    # --- Tools / apps ---
    ("vert.sh", "", "Website", "Other", "Development"),
    ("openapps.sh", "", "Website", "Other", "Development"),
    ("wizwand.com", "", "Website", "Other", "Machine Learning"),
    ("zeroclawlabs.ai", "", "Website", "Other", "Machine Learning"),
    ("zensical.org", "", "Website", "Other", "Development"),
    ("smallweb.cc", "", "Website", "Other", "Development"),
    ("chat.z.ai", "", "Website", "Other", "Machine Learning"),
    # --- Documentation / learning ---
    ("loreabad6.github.io", "", "Website", "R", "GIS"),
    ("ivelasq-r-pharma", "", "Website", "R", "General"),
    ("m.canouil.dev", "", "Website", "R", "General"),
    # --- Catch-all GitHub Pages (after specific rules above) ---
    (".github.io", "", "Website", "Other", "General"),
    # --- Codecentric / enterprise blogs ---
    ("codecentric.de", "", "Blog", "Other", "General"),
    ("blog.", "", "Blog", "Other", "General"),
    ("davisvaughan.com", "", "Blog", "R", "General"),
]


def _classify_url(url: str) -> tuple[str, str, str]:
    """
    Infer (type, language, category) for a URL using domain/path heuristics.

    Returns ('Website', 'Other', 'General') as the fallback.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    path = parsed.path.lower()

    for domain_frag, path_frag, rtype, lang, cat in _CLASSIFICATION_RULES:
        if domain_frag in domain and (not path_frag or path_frag in path):
            return rtype, lang, cat

    # Heuristic: if the path looks like a blog post (has a date or /posts/ /blog/)
    if re.search(r"/(posts?|blog|articles?|writing)/", path):
        return "Blog", "Other", "General"

    return "Website", "Other", "General"


def _infer_title(url: str, downloaded: bytes | str | None) -> str:
    """Extract page title from downloaded HTML, falling back to the domain."""
    if downloaded:
        try:
            meta = trafilatura.extract_metadata(downloaded)
            if meta and meta.title:
                title = meta.title.strip()
                if title:
                    return title[:120]
        except Exception as exc:
            print(
                f"  WARNING: trafilatura.extract_metadata failed: {exc}",
                file=sys.stderr,
            )

    # Fallback: domain + path fragment
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if path_parts:
        slug = path_parts[-1].replace("-", " ").replace("_", " ").title()
        return f"{domain} — {slug}"[:120]
    return domain[:120]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_url(url: str) -> str:
    """Strip trailing slashes and fragment-only anchors for dedup comparison."""
    url = url.strip().rstrip("/")
    # Preserve fragments that are part of the actual URL identity
    return url


def _extract_urls_from_args(raw: list[str]) -> list[str]:
    """
    Extract URLs from argument tokens: bare URLs, or `@path` to read one URL per
    line from a file (blank lines and # comments ignored). Order preserved, dupes
    dropped.
    """
    tokens: list[str] = []
    for token in raw:
        token = token.strip().strip(".,")
        if token.startswith("@"):
            tokens.extend(_read_urls_file(token[1:]))
        elif token.startswith(("http://", "https://")):
            tokens.append(token)

    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        norm = _normalise_url(token)
        if norm not in seen:
            seen.add(norm)
            result.append(token)  # keep original for fetching
    return result


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _read_urls_file(path: str) -> list[str]:
    """Read URLs from a file (one per line, blank lines and # comments ignored)."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: URL file not found: {p}", file=sys.stderr)
        sys.exit(1)
    lines = p.read_text(encoding="utf-8").splitlines()
    urls: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")):
            urls.append(line)
        else:
            print(f"  WARNING: ignoring non-URL line: {line!r}")
    return urls


def _resolve_path(path_arg: str | None) -> Path:
    if path_arg:
        p = Path(path_arg)
    else:
        env = os.environ.get("RESOURCES_PATH")
        if env:
            p = Path(env)
        else:
            p = Path(__file__).parent.parent / "resources.txt"
    if not p.exists():
        print(f"ERROR: resources file not found: {p}", file=sys.stderr)
        sys.exit(1)
    return p.resolve()


# ---------------------------------------------------------------------------
# Validation / check
# ---------------------------------------------------------------------------


def _check_resources(
    blocks: list[dict[str, str]],
    fix_dupes: bool,
    dry_run: bool,
) -> list[dict[str, str]]:
    """
    Validate all entries.  Print a report.  If fix_dupes is True, remove
    duplicates (keep first occurrence) and return the cleaned list.

    Returns the (possibly modified) list of blocks.
    """
    print("\n=== Validation Report ===")

    # ── Duplicate links ──────────────────────────────────────────────────
    link_positions: dict[str, list[int]] = {}
    for idx, block in enumerate(blocks, start=1):
        link = _normalise_url(block.get("link", ""))
        link_positions.setdefault(link, []).append(idx)

    dupe_links = {
        link: positions
        for link, positions in link_positions.items()
        if len(positions) > 1
    }

    if dupe_links:
        print(f"\nDuplicate URLs ({len(dupe_links)} links appear more than once):")
        for link, positions in sorted(dupe_links.items()):
            print(f"  {link}")
            print(f"    → entries: {positions} (keeping #{positions[0]})")
    else:
        print("\nNo duplicate URLs found.")

    # ── Missing / invalid fields ─────────────────────────────────────────
    issues: list[tuple[int, str, str]] = []  # (entry_num, field, message)
    for idx, block in enumerate(blocks, start=1):
        for field in FIELD_ORDER:
            val = block.get(field, "")
            if field == "link" and not val:
                issues.append((idx, field, f"missing required field: {field}"))
            elif field == "type":
                if not val:
                    issues.append((idx, field, "type is empty"))
                elif val not in KNOWN_TYPES:
                    issues.append(
                        (
                            idx,
                            field,
                            f"unknown type {val!r} — valid: {sorted(KNOWN_TYPES)}",
                        )
                    )
            elif field == "date" and val and not DATE_RE.match(val):
                issues.append(
                    (
                        idx,
                        field,
                        f"malformed date {val!r} (expected YYYY, YYYY-MM, or YYYY-MM-DD)",
                    )
                )

    if issues:
        print(f"\nField issues ({len(issues)} problems):")
        for idx, field, msg in issues:
            link = blocks[idx - 1].get("link", f"<entry #{idx}>")
            print(f"  [{idx:>4}] {link}")
            print(f"          {field}: {msg}")
    else:
        print("No field issues found.")

    print(f"\nTotal entries: {len(blocks)}")
    if dupe_links:
        print(
            f"Duplicate groups: {len(dupe_links)} ({sum(len(v) - 1 for v in dupe_links.values())} extra copies)"
        )
    print("=========================\n")

    # ── Apply fix-dupes ───────────────────────────────────────────────────
    if fix_dupes and dupe_links:
        if dry_run:
            print("DRY RUN: would remove duplicate entries (keeping first occurrence).")
        else:
            kept_indices: set[int] = set()
            for positions in link_positions.values():
                kept_indices.add(positions[0])
            original_count = len(blocks)
            blocks = [b for i, b in enumerate(blocks, start=1) if i in kept_indices]
            removed = original_count - len(blocks)
            print(
                f"Removed {removed} duplicate entries (kept first occurrence of each)."
            )

    return blocks


# ---------------------------------------------------------------------------
# Backfill mode
# ---------------------------------------------------------------------------


def _backfill(
    blocks: list[dict[str, str]],
    mode: str,
    force: bool,
    dry_run: bool,
    limit: int | None,
    url_filter: set[str] | None,
) -> tuple[list[dict[str, str]], int, int]:
    """
    Backfill dates and/or descriptions on *blocks* in place.

    Returns (updated_blocks, updated_count, failed_count).
    """

    def _needs_date(b: dict) -> bool:
        if force:
            return True
        return not b.get("date", "").strip()

    def _needs_desc(b: dict) -> bool:
        if force:
            return True
        desc = b.get("description", "").strip()
        return not desc or is_placeholder(desc)

    if mode == "dates":
        to_process = [b for b in blocks if _needs_date(b)]
    elif mode == "descriptions":
        to_process = [b for b in blocks if _needs_desc(b)]
    else:  # both
        to_process = [b for b in blocks if _needs_date(b) or _needs_desc(b)]

    if url_filter:
        to_process = [
            b for b in to_process if _normalise_url(b.get("link", "")) in url_filter
        ]

    total = len(to_process)
    already_done = len(blocks) - total
    force_note = " (--force: re-fetching all)" if force else ""

    print(f"\n=== Backfill ({mode}) ===")
    print(f"  {len(blocks)} entries total{force_note}")
    if not force:
        print(f"  {already_done} already complete (skipped)")
    print(f"  {total} entries to process")
    if url_filter:
        print(f"  (filtered to {len(url_filter)} URL(s) via --urls)")
    if limit is not None:
        to_process = to_process[:limit]
        print(f"  --limit {limit}: processing only the first {limit}")
    print()

    if not to_process:
        print("Nothing to do.")
        return blocks, 0, 0

    if dry_run:
        print("DRY RUN — no changes will be written.\n")

    updated = 0
    failed = 0

    # Build a lookup for in-place mutation
    block_by_link: dict[str, dict] = {b["link"]: b for b in blocks}

    for i, block in enumerate(to_process, start=1):
        url = block["link"]
        prefix = f"[{i:>4}/{len(to_process)}]"

        needs_d = mode in ("dates", "both") and _needs_date(block)
        needs_desc = mode in ("descriptions", "both") and _needs_desc(block)

        # Fetch page once for both date and description
        try:
            downloaded = trafilatura.fetch_url(url)
        except Exception:
            downloaded = None

        changed = False

        if needs_d:
            date_str = fetch_date(url, downloaded=downloaded)
            if date_str:
                if not dry_run:
                    block_by_link[url]["date"] = date_str
                print(f"{prefix} date  OK   {url}")
                print(f"         → {date_str}")
                changed = True
            else:
                if not dry_run:
                    block_by_link[url]["date"] = ""
                print(f"{prefix} date  SKIP {url} (no date found)")

        if needs_desc:
            desc_str = fetch_description(url, downloaded=downloaded)
            if desc_str:
                if not dry_run:
                    block_by_link[url]["description"] = desc_str
                short = desc_str[:80] + ("…" if len(desc_str) > 80 else "")
                print(f"{prefix} desc  OK   {url}")
                print(f"         → {short}")
                changed = True
            else:
                if not dry_run:
                    block_by_link[url]["description"] = ""
                print(f"{prefix} desc  SKIP {url} (no description found)")

        if changed:
            updated += 1
        else:
            failed += 1

        time.sleep(_FETCH_DELAY)

    print(f"\n  Updated: {updated}  |  Could not improve: {failed}")
    print("=========================\n")

    return blocks, updated, failed


# ---------------------------------------------------------------------------
# Add-URLs mode
# ---------------------------------------------------------------------------


def _add_urls(
    urls: list[str],
    resources_path: Path,
    dry_run: bool,
) -> int:
    """
    Fetch metadata for *urls*, deduplicate, and append to resources_path.

    Returns the number of entries actually appended.
    """
    print(f"\n=== Add URLs ({len(urls)} provided) ===")

    # Load existing links for dedup
    known = existing_links(resources_path)

    # Deduplicate within the provided list (preserve order)
    seen_in_batch: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        norm = _normalise_url(url)
        if norm in seen_in_batch:
            print(f"  SKIP (dup in batch)  {url}")
            continue
        seen_in_batch.add(norm)
        deduped.append(url)

    # Split into new vs. already-known
    new_urls = []
    for url in deduped:
        norm = _normalise_url(url)
        # Check both the exact URL and the normalised form
        if norm in {_normalise_url(k) for k in known}:
            print(f"  SKIP (already exists) {url}")
        else:
            new_urls.append(url)

    print(
        f"  {len(urls)} provided → {len(deduped)} after batch dedup → {len(new_urls)} new"
    )
    print()

    if not new_urls:
        print("Nothing to add.")
        return 0

    if dry_run:
        print("DRY RUN — no changes will be written.\n")

    new_blocks: list[dict[str, str]] = []

    for i, url in enumerate(new_urls, start=1):
        prefix = f"[{i:>4}/{len(new_urls)}]"
        print(f"{prefix} FETCH {url}")

        try:
            downloaded = trafilatura.fetch_url(url)
        except Exception:
            downloaded = None

        title = _infer_title(url, downloaded)
        description = fetch_description(url, downloaded=downloaded)
        date = fetch_date(url, downloaded=downloaded)
        rtype, language, category = _classify_url(url)

        print(f"         title : {title[:70]}")
        print(f"         type  : {rtype}  lang: {language}  cat: {category}")
        if date:
            print(f"         date  : {date}")
        if description:
            short = description[:70] + ("…" if len(description) > 70 else "")
            print(f"         desc  : {short}")

        new_blocks.append(
            make_block(
                title=title,
                type=rtype,
                link=url,
                language=language,
                category=category,
                description=description,
                date=date,
            )
        )
        time.sleep(_FETCH_DELAY)

    if not dry_run and new_blocks:
        print(f"\nAppending {len(new_blocks)} entries to {resources_path} ...")
        append_blocks(resources_path, new_blocks)

    print(f"\n  Added: {len(new_blocks)}  |  Skipped: {len(urls) - len(new_blocks)}")
    print("=========================\n")

    return len(new_blocks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill.py",
        description=(
            "Manage resources.txt: validate entries, backfill missing dates/"
            "descriptions, and add new URLs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "path",
        nargs="?",
        metavar="PATH",
        help="Path to resources.txt (default: ../resources.txt or $RESOURCES_PATH)",
    )

    # ── Modes ──────────────────────────────────────────────────────────────
    mode_group = p.add_argument_group("Backfill mode")
    mode_group.add_argument(
        "--mode",
        choices=["dates", "descriptions", "both"],
        default=None,
        help="Which fields to backfill. Without it, the run only validates.",
    )
    mode_group.add_argument(
        "--add-urls",
        nargs="+",
        metavar="URL|@FILE",
        dest="add_urls",
        help=(
            "Add new URLs: fetch metadata, classify, deduplicate, append. "
            "@FILE reads one URL per line (blank lines and # comments ignored)."
        ),
    )

    # ── Validation ─────────────────────────────────────────────────────────
    val_group = p.add_argument_group("Validation")
    val_group.add_argument(
        "--fix-dupes",
        action="store_true",
        dest="fix_dupes",
        help="Remove duplicate entries (keep first occurrence).",
    )

    # ── Filters ────────────────────────────────────────────────────────────
    filter_group = p.add_argument_group("Filtering")
    filter_group.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="Restrict --mode backfill to only these URLs.",
    )

    # ── Fetch control ──────────────────────────────────────────────────────
    fetch_group = p.add_argument_group("Fetch control")
    fetch_group.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even entries that already have a value.",
    )
    fetch_group.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print what would change without writing anything.",
    )
    fetch_group.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Stop after fetching N URLs.",
    )

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    resources_path = _resolve_path(args.path)
    print(f"Resources file: {resources_path}")

    # ── Load and always validate ──────────────────────────────────────────
    print("Loading entries ...")
    blocks = parse_resources(resources_path)

    # Validation runs on every invocation
    blocks = _check_resources(
        blocks,
        fix_dupes=args.fix_dupes,
        dry_run=args.dry_run,
    )

    # After fix-dupes, write the cleaned file before doing anything else
    if args.fix_dupes and not args.dry_run:
        print(f"Writing cleaned file to {resources_path} ...")
        write_resources(resources_path, blocks)

    # Actions: validation ran above; each flag adds one more step.
    if args.add_urls:
        clean_urls = _extract_urls_from_args(args.add_urls)
        if not clean_urls:
            print("WARNING: --add-urls given but no valid URLs were parsed.")
        else:
            _add_urls(clean_urls, resources_path, dry_run=args.dry_run)

    if args.mode is None:
        if not args.add_urls and not args.fix_dupes:
            print("Validation only. Pass --mode {dates,descriptions,both} to backfill.")
        return

    url_filter: set[str] | None = None
    if args.urls:
        url_filter = {_normalise_url(u) for u in args.urls}

    blocks, updated, _failed = _backfill(
        blocks,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
        limit=args.limit,
        url_filter=url_filter,
    )

    if not args.dry_run and updated > 0:
        print(f"Writing {resources_path} ...")
        write_resources(resources_path, blocks)
        print("Done. Review changes with: git diff resources.txt\n")


if __name__ == "__main__":
    main()
