"""
link_health.py — monthly liveness check of every resource URL in resources.txt.

Report-only: results are data, never build status. Exit code is 0 unless the
script itself falls apart. Retiring a dead link is a manual decision made via
scripts/retire.py.

Checks (single HEAD, GET fallback on 405/501, <=5 redirects, 15 s timeout,
one retry on connection errors, realistic User-Agent, 3 concurrent threads
with 250 ms between submissions) and classifies each URL:

    OK            any 2xx/3xx
    DEAD          404 or 410
    BLOCKED       403 (likely bot/antivirus block — NOT dead, listed separately)
    RATE_LIMITED  429 (NOT dead, skip-with-note)
    TIMEOUT       request timed out (after retry)
    DNS           name resolution failed
    ERROR         anything else (5xx, TLS, malformed URL, ...)

Outputs:
  - CSV (title, link, status, http_code, checked_at) written to
    scripts/reports/link-health.csv by default (--csv)
  - optional human-readable markdown report grouped by category (--output)

Run from scripts/:
    uv run python link_health.py --help
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.error import URLError
from urllib.parse import urlparse

import utils
from utils import parse_resources

ROOT = Path(__file__).resolve().parent.parent

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT_S = 15
MAX_REDIRECTS = 5
MAX_WORKERS = 3
SUBMIT_INTERVAL_S = 0.25

CATEGORIES_BY_PRIORITY = ("DEAD", "BLOCKED", "TIMEOUT", "DNS", "RATE_LIMITED", "ERROR", "OK")


def _classify_http(code: int) -> str:
    if code in (404, 410):
        return "DEAD"
    if code == 429:
        return "RATE_LIMITED"
    if code == 403:
        return "BLOCKED"
    if code < 400:
        return "OK"
    return "ERROR"


def _is_dns_failure(exc: BaseException) -> bool:
    while exc is not None:
        if isinstance(exc, socket.gaierror):
            return True
        msg = str(exc)
        if "getaddrinfo failed" in msg or "Name or service not known" in msg or "nodename nor servname" in msg:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def check_url(url: str) -> tuple[str, int | None]:
    """Check one URL. Returns (status, http_code|None). One retry on
    connection-level errors (timeouts, DNS blips, refused connections)."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            return _request_once(url, method="HEAD")
        except urlerror.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (405, 501) and attempt == 1:
                # Method not allowed / not implemented: retry once with GET
                # (handled via the loop: force method switch below).
                try:
                    return _request_once(url, method="GET")
                except urlerror.HTTPError as exc2:
                    code = exc2.code
                    exc2.close()
                    return _classify_http(code), code
                except (URLError, TimeoutError, OSError) as exc2:
                    last_exc = exc2
            else:
                return _classify_http(code), code
        except (URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == 1:
                time.sleep(1)
    # All attempts failed at the connection level
    assert last_exc is not None
    if isinstance(last_exc, TimeoutError) or isinstance(last_exc, socket.timeout):
        return "TIMEOUT", None
    if _is_dns_failure(last_exc):
        return "DNS", None
    return "ERROR", None


def _request_once(url: str, method: str) -> tuple[str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"invalid URL: {url!r}")
    req = urlrequest.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    opener = urlrequest.build_opener(urlrequest.HTTPRedirectHandler())
    with opener.open(req, timeout=TIMEOUT_S) as resp:
        code = resp.status
        resp.close()
        return _classify_http(code), code


def check_entry(entry: dict[str, str]) -> dict[str, str]:
    link = entry["link"]
    try:
        status, code = check_url(link)
    except Exception as exc:  # malformed URL etc. — data, not a crash
        status, code = "ERROR", None
        return _row(entry, status, code, note=str(exc))
    return _row(entry, status, code)


def _row(entry: dict[str, str], status: str, code: int | None, note: str = "") -> dict[str, str]:
    return {
        "title": entry["title"],
        "link": entry["link"],
        "status": status,
        "http_code": "" if code is None else str(code),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **({"note": note} if note else {}),
    }


def build_report(rows: list[dict[str, str]], checked_at: str) -> str:
    counts = {cat: 0 for cat in CATEGORIES_BY_PRIORITY}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    lines = [
        "# Link health report",
        "",
        f"Checked {len(rows)} URLs on {checked_at}.",
        "",
        "| Status | Count |",
        "|--------|------:|",
    ]
    for cat in CATEGORIES_BY_PRIORITY:
        if counts[cat]:
            lines.append(f"| {cat} | {counts[cat]} |")
    lines.append("")

    def section(title: str, cats: tuple[str, ...], blurb: str) -> list[str]:
        entries = [r for r in rows if r["status"] in cats]
        if not entries:
            return []
        out = [f"## {title} ({len(entries)})", "", blurb, ""]
        out += [f"- {r['title']} — {r['link']} ({r['http_code'] or r['status']})" for r in entries]
        out.append("")
        return out

    lines += section("Dead links", ("DEAD",), "HTTP 404/410 — likely retired. Manual decision via `scripts/retire.py`.")
    lines += section("Blocked (bot detection)", ("BLOCKED",), "HTTP 403 — probably blocking our User-Agent, not dead. Verify by hand.")
    lines += section("Timeout / DNS failures", ("TIMEOUT", "DNS"), "Could not connect (after retry) — may be transient.")
    lines += section("Rate-limited", ("RATE_LIMITED",), "HTTP 429 — skipped, NOT dead. Will likely pass next run.")
    lines += section("Other errors", ("ERROR",), "5xx, TLS or malformed-URL failures.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check all resource URLs for liveness (report-only).")
    parser.add_argument(
        "--path",
        default=os.environ.get("RESOURCES_PATH", str(ROOT / "resources.txt")),
        help="path to resources.txt (default: RESOURCES_PATH env or repo root)",
    )
    parser.add_argument(
        "--csv",
        default=str(Path(__file__).resolve().parent / "reports" / "link-health.csv"),
        help="CSV output path (default: scripts/reports/link-health.csv)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="write a human-readable markdown report to this path",
    )
    args = parser.parse_args()

    resources_path = Path(args.path)
    entries = [e for e in parse_resources(resources_path) if e["link"]]
    if not entries:
        print(f"ERROR: no entries with links parsed from {resources_path}", file=sys.stderr)
        return 1
    print(f"Checking {len(entries)} URLs ({MAX_WORKERS} workers, {SUBMIT_INTERVAL_S:.2f}s between submissions)...")

    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    rows: dict[str, dict[str, str]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for i, entry in enumerate(entries):
            if i:
                time.sleep(SUBMIT_INTERVAL_S)
            futures[pool.submit(check_entry, entry)] = entry
        for future in as_completed(futures):
            row = future.result()
            rows[row["link"]] = row
            done += 1
            if row["status"] != "OK" or done % 100 == 0:
                print(f"  [{done}/{len(entries)}] {row['status']:12} {row['http_code']:>4} {row['link']}")

    ordered_rows = [rows[e["link"]] for e in entries if e["link"] in rows]
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["title", "link", "status", "http_code", "checked_at", "note"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered_rows)

    counts = {cat: 0 for cat in CATEGORIES_BY_PRIORITY}
    for r in ordered_rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = ", ".join(f"{cat}={counts[cat]}" for cat in CATEGORIES_BY_PRIORITY if counts[cat])
    print(f"\nSummary: {summary}")
    print(f"CSV written to {csv_path}")

    if args.output:
        Path(args.output).write_text(build_report(ordered_rows, checked_at), encoding="utf-8")
        print(f"Markdown report written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
