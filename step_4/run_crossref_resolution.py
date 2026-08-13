#!/usr/bin/env python3
"""Resolve missing DOI and publication metadata with Crossref.

Crossref is used only as a resolver for records already retrieved from Web of
Science, OpenAlex, or Semantic Scholar. This script does not use Crossref as a
separate discovery search and never adds a record that was not already present
in one of those source exports.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


API_URL = "https://api.crossref.org/works"
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "crossref"
PROGRESS_FILE = OUTPUT_DIR / ".crossref_resolution_progress.jsonl"
RESULT_FILE = OUTPUT_DIR / "crossref_resolutions.csv"
SUMMARY_FILE = OUTPUT_DIR / "crossref_resolution_summary.json"

OUTPUT_FIELDS = [
    "resolution_id",
    "input_title",
    "input_year",
    "input_authors",
    "input_venue",
    "source_systems",
    "source_query_ids",
    "source_record_ids",
    "source_record_count",
    "resolution_status",
    "resolution_reason",
    "crossref_doi",
    "crossref_title",
    "crossref_year",
    "crossref_authors",
    "crossref_container_title",
    "crossref_type",
    "crossref_publisher",
    "crossref_url",
    "crossref_score",
    "title_similarity",
    "title_token_jaccard",
    "year_difference",
    "first_author_match",
    "queried_at_utc",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_doi(value: object) -> str:
    doi = clean(value).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.rstrip(" .;,")


def normalize_title(value: object) -> str:
    title = unicodedata.normalize("NFKD", clean(value))
    title = title.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def year_text(value: object) -> str:
    match = re.search(r"(?:18|19|20|21)\d{2}", clean(value))
    return match.group(0) if match else ""


def first_author_surname(value: object) -> str:
    text = clean(value)
    if not text:
        return ""
    first = re.split(r"\s*[;|]\s*", text, maxsplit=1)[0].strip()
    if "," in first:
        surname = first.split(",", 1)[0]
    else:
        parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", first)
        surname = parts[-1] if parts else ""
    return normalize_title(surname).replace(" ", "")


def crossref_authors(item: dict) -> str:
    names = []
    for author in item.get("author") or []:
        name = " ".join(
            part for part in [clean(author.get("given")), clean(author.get("family"))] if part
        )
        if name:
            names.append(name)
    return "; ".join(names)


def crossref_year(item: dict) -> str:
    for field in ("published-print", "published-online", "issued", "created"):
        date_parts = (item.get(field) or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            year = year_text(date_parts[0][0])
            if year:
                return year
    return ""


def first(values: object) -> str:
    if isinstance(values, list):
        return clean(values[0]) if values else ""
    return clean(values)


def read_ris(path: Path) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    record: dict[str, list[str]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if line == "ER  -":
            records.append(dict(record))
            record = defaultdict(list)
            continue
        if "  - " in line:
            tag, value = line.split("  - ", 1)
            record[tag].append(value)
    return records


def source_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in sorted((ROOT / "openalex").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                records.append(
                    {
                        "system": "OpenAlex",
                        "query_id": clean(row.get("query_id")),
                        "record_id": clean(row.get("openalex_id")),
                        "doi": normalize_doi(row.get("doi")),
                        "title": clean(row.get("title")),
                        "year": year_text(row.get("publication_year")),
                        "authors": clean(row.get("authors")),
                        "venue": clean(row.get("primary_source")),
                    }
                )
    for path in sorted((ROOT / "semantic_scholar").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                records.append(
                    {
                        "system": "Semantic Scholar",
                        "query_id": clean(row.get("query_id")),
                        "record_id": clean(row.get("paper_id")),
                        "doi": normalize_doi(row.get("doi")),
                        "title": clean(row.get("title")),
                        "year": year_text(row.get("year")),
                        "authors": clean(row.get("authors")),
                        "venue": clean(row.get("venue")),
                    }
                )
    for path in sorted((ROOT / "wos").glob("*.ris")):
        for index, row in enumerate(read_ris(path), start=1):
            authors = row.get("AU") or row.get("A1") or []
            records.append(
                {
                    "system": "Web of Science",
                    "query_id": path.stem,
                    "record_id": first(row.get("UT")) or f"{path.name}#{index}",
                    "doi": normalize_doi(first(row.get("DO")) or first(row.get("DI"))),
                    "title": first(row.get("TI")) or first(row.get("T1")),
                    "year": year_text(first(row.get("PY")) or first(row.get("Y1"))),
                    "authors": "; ".join(authors),
                    "venue": (
                        first(row.get("JO"))
                        or first(row.get("JF"))
                        or first(row.get("T2"))
                    ),
                }
            )
    return records


def choose_representative(records: list[dict[str, str]]) -> dict[str, str]:
    def most_informative(field: str) -> str:
        values = [record[field] for record in records if record[field]]
        return max(values, key=lambda value: (len(value), value)) if values else ""

    return {
        "title": most_informative("title"),
        "year": most_informative("year"),
        "authors": most_informative("authors"),
        "venue": most_informative("venue"),
    }


def unresolved_groups(records: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for record in records:
        grouped[(normalize_title(record["title"]), record["year"])].append(record)

    groups = []
    for (normalized_title, year), members in grouped.items():
        if any(member["doi"] for member in members):
            continue
        # The DOI-resolution pass is intentionally limited to records present
        # in the frozen Web of Science production exports. OpenAlex- or
        # Semantic Scholar-only records retain their native DOI fields and are
        # handled during the later candidate-corpus merge if still incomplete.
        if not any(member["system"] == "Web of Science" for member in members):
            continue
        representative = choose_representative(members)
        key_text = f"{normalized_title}|{year}"
        resolution_id = __import__("hashlib").sha256(key_text.encode()).hexdigest()[:16]
        groups.append(
            {
                "resolution_id": resolution_id,
                "normalized_title": normalized_title,
                "title": representative["title"],
                "year": year,
                "authors": representative["authors"],
                "venue": representative["venue"],
                "systems": sorted({member["system"] for member in members}),
                "query_ids": sorted({member["query_id"] for member in members}),
                "record_ids": sorted({member["record_id"] for member in members}),
                "record_count": len(members),
            }
        )
    return sorted(groups, key=lambda group: (clean(group["year"]), clean(group["title"])))


def request_json(params: dict[str, str], max_attempts: int = 7) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(params)
    mailto = os.environ.get("CROSSREF_MAILTO")
    user_agent = "coldwatercoral_lit/1.0 (https://github.com/JTDingwall/coldwatercoral_lit)"
    if mailto:
        user_agent += f"; mailto:{mailto}"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == max_attempts - 1:
                raise
            retry_after = error.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(60.0, 2.0 * 2**attempt)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts - 1:
                raise
            time.sleep(min(60.0, 2.0 * 2**attempt))
    raise RuntimeError("Crossref request failed after retries")


def candidate_metrics(group: dict[str, object], item: dict) -> dict[str, object]:
    input_title = clean(group["title"])
    candidate_title = first(item.get("title"))
    normalized_input = normalize_title(input_title)
    normalized_candidate = normalize_title(candidate_title)
    similarity = SequenceMatcher(None, normalized_input, normalized_candidate).ratio()
    input_tokens = set(normalized_input.split())
    candidate_tokens = set(normalized_candidate.split())
    token_jaccard = (
        len(input_tokens & candidate_tokens) / len(input_tokens | candidate_tokens)
        if input_tokens | candidate_tokens
        else 0.0
    )
    input_year = year_text(group["year"])
    candidate_year = crossref_year(item)
    year_difference = (
        abs(int(input_year) - int(candidate_year)) if input_year and candidate_year else None
    )
    input_author = first_author_surname(group["authors"])
    candidate_author = first_author_surname(crossref_authors(item))
    author_match = bool(input_author and candidate_author and input_author == candidate_author)
    return {
        "item": item,
        "title": candidate_title,
        "year": candidate_year,
        "similarity": similarity,
        "token_jaccard": token_jaccard,
        "year_difference": year_difference,
        "author_match": author_match,
        "input_author_available": bool(input_author),
        "candidate_author_available": bool(candidate_author),
    }


def classify(metrics: dict[str, object]) -> tuple[str, str]:
    similarity = float(metrics["similarity"])
    token_jaccard = float(metrics["token_jaccard"])
    year_difference = metrics["year_difference"]
    author_match = bool(metrics["author_match"])
    input_author_available = bool(metrics["input_author_available"])
    exact_title = similarity == 1.0
    close_year = year_difference is not None and int(year_difference) <= 1
    exact_year = year_difference == 0

    if exact_title and close_year and (author_match or not input_author_available):
        return "accepted", "exact normalized title; year within one; author consistent if available"
    if similarity >= 0.97 and token_jaccard >= 0.90 and close_year and author_match:
        return "accepted", "very high title similarity; year within one; first author matched"
    if similarity >= 0.94 and token_jaccard >= 0.85 and exact_year and author_match:
        return "accepted", "high title similarity; exact year; first author matched"
    if similarity >= 0.90 and token_jaccard >= 0.75 and close_year:
        return "review", "plausible title/year match below automatic acceptance threshold"
    return "no_match", "best Crossref candidate failed conservative match threshold"


def reclassify_saved_row(row: dict[str, object]) -> dict[str, object]:
    """Apply the current matching policy to a stored Crossref candidate."""
    if clean(row.get("resolution_status")) in {"error", "not_queried"}:
        return row
    if not clean(row.get("crossref_doi")):
        return row
    metrics = {
        "similarity": float(clean(row.get("title_similarity")) or 0),
        "token_jaccard": float(clean(row.get("title_token_jaccard")) or 0),
        "year_difference": (
            int(clean(row.get("year_difference")))
            if clean(row.get("year_difference"))
            else None
        ),
        "author_match": clean(row.get("first_author_match")).lower() == "true",
        "input_author_available": bool(first_author_surname(row.get("input_authors"))),
        "candidate_author_available": bool(first_author_surname(row.get("crossref_authors"))),
    }
    status, reason = classify(metrics)
    row["resolution_status"] = status
    row["resolution_reason"] = reason
    return row


def resolve_group(group: dict[str, object]) -> dict[str, object]:
    title = clean(group["title"])
    year = year_text(group["year"])
    queried_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    base = {
        "resolution_id": group["resolution_id"],
        "input_title": title,
        "input_year": year,
        "input_authors": clean(group["authors"]),
        "input_venue": clean(group["venue"]),
        "source_systems": " | ".join(group["systems"]),
        "source_query_ids": " | ".join(group["query_ids"]),
        "source_record_ids": " | ".join(group["record_ids"]),
        "source_record_count": group["record_count"],
        "queried_at_utc": queried_at,
    }
    if not title or len(normalize_title(title).split()) < 3:
        return {
            **base,
            "resolution_status": "not_queried",
            "resolution_reason": "title missing or too short for reliable resolution",
        }
    if not year:
        return {
            **base,
            "resolution_status": "not_queried",
            "resolution_reason": "publication year missing",
        }

    bibliographic = " ".join(
        part for part in [title, year, clean(group["authors"]), clean(group["venue"])] if part
    )
    payload = request_json(
        {
            "query.bibliographic": bibliographic,
            "rows": "3",
            "select": (
                "DOI,title,author,published-print,published-online,issued,created,"
                "container-title,type,publisher,URL,score"
            ),
        }
    )
    items = (payload.get("message") or {}).get("items") or []
    if not items:
        return {
            **base,
            "resolution_status": "no_match",
            "resolution_reason": "Crossref returned no candidates",
        }
    metrics = [candidate_metrics(group, item) for item in items]
    best = max(
        metrics,
        key=lambda value: (
            float(value["similarity"]),
            float(value["token_jaccard"]),
            bool(value["author_match"]),
            -int(value["year_difference"]) if value["year_difference"] is not None else -9999,
            float((value["item"] or {}).get("score") or 0),
        ),
    )
    status, reason = classify(best)
    item = best["item"]
    return {
        **base,
        "resolution_status": status,
        "resolution_reason": reason,
        "crossref_doi": normalize_doi(item.get("DOI")),
        "crossref_title": best["title"],
        "crossref_year": best["year"],
        "crossref_authors": crossref_authors(item),
        "crossref_container_title": first(item.get("container-title")),
        "crossref_type": clean(item.get("type")),
        "crossref_publisher": clean(item.get("publisher")),
        "crossref_url": clean(item.get("URL")),
        "crossref_score": item.get("score", ""),
        "title_similarity": f"{float(best['similarity']):.6f}",
        "title_token_jaccard": f"{float(best['token_jaccard']):.6f}",
        "year_difference": (
            best["year_difference"] if best["year_difference"] is not None else ""
        ),
        "first_author_match": best["author_match"],
    }


def load_progress() -> dict[str, dict[str, object]]:
    completed = {}
    if not PROGRESS_FILE.exists():
        return completed
    with PROGRESS_FILE.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if clean(row.get("resolution_status")) != "error":
                    completed[clean(row["resolution_id"])] = row
    return completed


def write_outputs(rows: list[dict[str, object]], source_count: int, target_count: int) -> None:
    with RESULT_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})

    counts = Counter(clean(row.get("resolution_status")) for row in rows)
    summary = {
        "system": "Crossref REST API",
        "endpoint": API_URL,
        "completed_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": (
            "DOI and publication-metadata resolution only for unresolved records present "
            "in the frozen Web of Science production exports; not a discovery search"
        ),
        "target_definition": (
            "Unique normalized title-year groups represented in Web of Science and lacking "
            "a DOI in every matching Web of Science, OpenAlex, and Semantic Scholar record"
        ),
        "source_record_count": source_count,
        "unique_unresolved_title_year_count": target_count,
        "resolution_status_counts": dict(sorted(counts.items())),
        "accepted_doi_count": counts.get("accepted", 0),
        "output_file": RESULT_FILE.relative_to(ROOT.parent).as_posix(),
        "matching_policy": {
            "accepted": (
                "Exact or near-exact normalized title, publication year within one year, "
                "and consistent first author when both sources provide one"
            ),
            "review": "Plausible title/year match below the automatic acceptance threshold",
            "no_match": "No candidate met the review threshold",
            "not_queried": "Input lacked a sufficiently informative title or publication year",
        },
        "notes": (
            "Original source exports were not modified. Only rows marked accepted should be "
            "used for automatic DOI assignment; review rows require manual confirmation."
        ),
    }
    with SUMMARY_FILE.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def resolve_safely(group: dict[str, object], delay: float) -> dict[str, object]:
    try:
        row = resolve_group(group)
    except Exception as error:  # retain an auditable row and continue
        row = {
            "resolution_id": group["resolution_id"],
            "input_title": group["title"],
            "input_year": group["year"],
            "input_authors": group["authors"],
            "input_venue": group["venue"],
            "source_systems": " | ".join(group["systems"]),
            "source_query_ids": " | ".join(group["query_ids"]),
            "source_record_ids": " | ".join(group["record_ids"]),
            "source_record_count": group["record_count"],
            "resolution_status": "error",
            "resolution_reason": f"{type(error).__name__}: {error}",
            "queried_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
    if row.get("resolution_status") != "not_queried":
        time.sleep(max(delay, 0.0))
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Resolve only the first N pending records (for testing or resumable batches).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.10,
        help="Delay in seconds between Crossref requests (default: 0.10).",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard prior progress and start resolution from the beginning.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Concurrent Crossref requests (default: 5).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.restart and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    records = source_records()
    groups = unresolved_groups(records)
    completed = load_progress()
    pending = [group for group in groups if group["resolution_id"] not in completed]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"Source records: {len(records)}")
    print(f"Unique unresolved title-year inputs: {len(groups)}")
    print(f"Already completed: {len(completed)}")
    print(f"Resolving in this run: {len(pending)}")

    workers = max(1, args.workers)
    with PROGRESS_FILE.open("a", encoding="utf-8") as progress:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(resolve_safely, group, args.delay): group for group in pending
            }
            for index, future in enumerate(as_completed(futures), start=1):
                row = future.result()
                progress.write(json.dumps(row, ensure_ascii=False) + "\n")
                progress.flush()
                completed[clean(row["resolution_id"])] = row
                if index % 50 == 0 or index == len(pending):
                    print(f"  completed {index}/{len(pending)}")

    ordered_rows = [
        reclassify_saved_row(completed[clean(group["resolution_id"])])
        for group in groups
        if clean(group["resolution_id"]) in completed
    ]
    write_outputs(ordered_rows, len(records), len(groups))
    print(f"Wrote {RESULT_FILE.relative_to(ROOT.parent)}")
    print(f"Wrote {SUMMARY_FILE.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
