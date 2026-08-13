#!/usr/bin/env python3
"""Run reproducible Step 4 grey-literature searches.

Tavily performs retrieval. DeepSeek optionally adds unverified descriptive
metadata; it does not screen, rank, remove, or deduplicate search results.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GREY_DIR = ROOT / "grey"
TARGETS_PATH = ROOT / "grey_institutional_targets.csv"
SEARCH_LOG_PATH = ROOT / "search_log.csv"
SEARCH_DATE = date.today().isoformat()

ORGANISMS = (
    '(coral OR corals OR octocoral OR gorgonian OR "sea pen" OR '
    'scleractinian OR antipatharian OR "black coral" OR sponge OR sponges '
    'OR Porifera OR demosponge OR hexactinellid OR "glass sponge" '
    'OR "deep-sea sponge" OR "cold-water sponge")'
)

CORALS = (
    '(coral OR corals OR octocoral OR gorgonian OR "sea pen" OR '
    'scleractinian OR antipatharian OR "black coral")'
)

SPONGES = (
    '(sponge OR sponges OR Porifera OR demosponge OR hexactinellid '
    'OR "glass sponge" OR "deep-sea sponge" OR "cold-water sponge")'
)

FAMILIES = {
    "SED_SUSPENDED": ORGANISMS
    + ' ("suspended sediment" OR "suspended solids" OR turbidity OR '
    'resuspension OR "sediment plume")',
    "SED_DEPOSITION": ORGANISMS
    + ' ("sediment deposition" OR "sediment accumulation" OR burial OR '
    'smothering OR "sediment cover" OR "deposition rate")',
    "SED_DRILLING": ORGANISMS
    + ' ("drill cuttings" OR "drilling mud" OR "drilling fluid" OR '
    '"drilling discharge" OR "cuttings pile" OR "offshore drilling")',
    "SED_DREDGING": ORGANISMS
    + ' (dredging OR "dredge plume" OR "dredged material" OR '
    '"spoil disposal" OR "resuspended sediment")',
    "SED_TAILINGS": ORGANISMS
    + ' ("mine tailings" OR "submarine tailings" OR "deep-sea mining" '
    'OR "deep sea mining" OR "mining plume" OR "marine disposal")',
    "MECH_FEEDING_MUCUS_CORAL": CORALS
    + ' (sediment OR turbidity OR burial OR "drill cuttings") '
    + '(mucus OR mucociliary OR "sediment rejection" OR '
    '"sediment clearance" OR feeding OR "food capture" OR "polyp activity")',
    "MECH_FEEDING_PUMPING_SPONGE": SPONGES
    + ' (sediment OR turbidity OR "suspended solids" OR "drill cuttings") '
    + '(pumping OR filtration OR clogging OR "feeding current" OR '
    '"food capture" OR "clearance rate")',
    "RESP_THRESHOLD_RECOVERY": ORGANISMS
    + ' ("suspended sediment" OR "sediment deposition" OR turbidity OR '
    'burial OR smothering OR "drill cuttings" OR "sediment plume") '
    + '(threshold OR tolerance OR sensitivity OR "dose response" OR '
    '"exposure response" OR recovery OR mortality OR survival)',
}

GREY_TYPES = (
    '(report OR "technical report" OR "monitoring report" OR assessment '
    'OR "environmental impact statement" OR EIS OR thesis OR dissertation '
    'OR proceedings OR "regulatory submission" OR "operator report")'
)

GREY_TYPES_PLAIN = (
    'government regulator monitoring technical report environmental assessment '
    'thesis dissertation proceedings operator report'
)

RESULT_FIELDS = [
    "query_id",
    "family",
    "search_phase",
    "target_id",
    "target_name",
    "system",
    "date_searched",
    "retrieved_at_utc",
    "query",
    "include_domains",
    "result_rank",
    "title",
    "url",
    "domain",
    "score",
    "published_date",
    "content",
    "response_time_seconds",
    "credits_used",
]

ENRICHMENT_FIELDS = RESULT_FIELDS + [
    "deepseek_document_type",
    "deepseek_issuing_organization",
    "deepseek_publication_year",
    "deepseek_language",
    "deepseek_full_document_guess",
    "deepseek_metadata_status",
]

LOG_FIELDS = [
    "query_id",
    "system",
    "date_searched",
    "family",
    "query_or_scope",
    "result_count",
    "output_file",
    "notes",
]


def load_env_file(path: Path) -> None:
    """Load KEY=value lines without printing secrets or overriding the shell."""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            os.environ.setdefault(key, value)


def request_json(
    url: str,
    payload: dict,
    headers: dict[str, str],
    max_attempts: int = 6,
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            message = error.read().decode("utf-8", errors="replace")
            if error.code not in {429, 500, 502, 503, 504} or attempt == max_attempts - 1:
                raise RuntimeError(f"HTTP {error.code}: {message[:1000]}") from error
            retry_after = error.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(60, 2**attempt)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == max_attempts - 1:
                raise RuntimeError(f"Network request failed: {error}") from error
            time.sleep(min(60, 2**attempt))
    raise RuntimeError("Request failed after retries")


def normalized_base_url(value: str, endpoint: str) -> str:
    return value.rstrip("/") + "/" + endpoint.lstrip("/")


def url_domain(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def compact_excerpt(value: str | None, limit: int = 600) -> str:
    """Keep a short, single-line search excerpt rather than page-like content."""
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def load_targets(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        targets = list(csv.DictReader(handle))
    required = {"target_id", "target_name", "domains", "status", "basis"}
    if not targets or not required.issubset(targets[0]):
        raise RuntimeError(f"Invalid institutional target manifest: {path}")
    return [row for row in targets if row["status"].strip().lower() == "active"]


def build_searches(phase: str) -> list[dict[str, object]]:
    searches: list[dict[str, object]] = []
    if phase == "broad":
        for family, concept in FAMILIES.items():
            for variant, suffix in (
                (f"{GREY_TYPES} filetype:pdf", "01"),
                (GREY_TYPES_PLAIN, "02"),
            ):
                searches.append(
                    {
                    "query_id": f"GL_BROAD_{family}_{suffix}",
                    "family": family,
                    "search_phase": "broad_web",
                    "target_id": "BROAD_WEB",
                    "target_name": "Unrestricted public web",
                    "query": f"{concept} {variant}",
                    "domains": [],
                    }
                )
        return searches

    for target in load_targets(TARGETS_PATH):
        domains = [item.strip() for item in target["domains"].split("|") if item.strip()]
        for family, concept in FAMILIES.items():
            searches.append(
                {
                    "query_id": f"GL_{target['target_id']}_{family}_01",
                    "family": family,
                    "search_phase": "targeted_institutional",
                    "target_id": target["target_id"],
                    "target_name": target["target_name"],
                    "query": f"{concept} {GREY_TYPES}",
                    "domains": domains,
                }
            )
    return searches


def run_tavily_searches(phase: str, max_results: int) -> Path:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    base_url = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com")
    endpoint = normalized_base_url(base_url, "search")
    search_depth = os.environ.get("TAVILY_SEARCH_DEPTH", "advanced")
    output_path = GREY_DIR / f"grey_{phase}_results.csv"
    searches = build_searches(phase)
    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    GREY_DIR.mkdir(parents=True, exist_ok=True)

    for position, specification in enumerate(searches, start=1):
        print(f"[{position}/{len(searches)}] {specification['query_id']}", flush=True)
        payload = {
            "api_key": api_key,
            "query": specification["query"],
            "topic": "general",
            "search_depth": search_depth,
            "chunks_per_source": 3,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
        if specification["domains"]:
            payload["include_domains"] = specification["domains"]
        retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        response = request_json(endpoint, payload, {"Content-Type": "application/json"})
        results = response.get("results") or []
        usage = response.get("usage") or {}
        credits = usage.get("credits", "")
        response_time = response.get("response_time", "")

        for rank, result in enumerate(results, start=1):
            url = result.get("url") or ""
            rows.append(
                {
                    "query_id": specification["query_id"],
                    "family": specification["family"],
                    "search_phase": specification["search_phase"],
                    "target_id": specification["target_id"],
                    "target_name": specification["target_name"],
                    "system": "Tavily Search API",
                    "date_searched": SEARCH_DATE,
                    "retrieved_at_utc": retrieved_at,
                    "query": specification["query"],
                    "include_domains": " | ".join(specification["domains"]),
                    "result_rank": rank,
                    "title": result.get("title") or "",
                    "url": url,
                    "domain": url_domain(url),
                    "score": result.get("score", ""),
                    "published_date": result.get("published_date") or "",
                    "content": compact_excerpt(result.get("content")),
                    "response_time_seconds": response_time,
                    "credits_used": credits,
                }
            )
        summaries.append(
            {
                **specification,
                "result_count": len(results),
                "response_time_seconds": response_time,
                "credits_used": credits,
            }
        )
        time.sleep(0.2)

    temporary_path = output_path.with_suffix(".csv.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(output_path)

    summary_path = GREY_DIR / f"grey_{phase}_search_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "system": "Tavily Search API",
                "date_searched": SEARCH_DATE,
                "phase": phase,
                "search_depth": search_depth,
                "max_results_per_query": max_results,
                "notes": (
                    "No date cutoff. Results are retained by query with no relevance "
                    "screening or cross-query deduplication."
                ),
                "searches": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved {len(rows)} rows to {output_path}")
    return output_path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def discover_domains() -> None:
    path = GREY_DIR / "grey_broad_results.csv"
    rows = read_csv(path)
    counts = Counter(row["domain"] for row in rows if row["domain"])
    output = GREY_DIR / "broad_domain_frequency.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["domain", "broad_result_occurrences"])
        writer.writerows(counts.most_common())
    print(f"Saved {len(counts)} domains to {output}")


def deepseek_chat(messages: list[dict[str, str]]) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash")
    endpoint = normalized_base_url(base_url, "chat/completions")
    payload = {
        "model": model,
        "messages": messages,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 5000,
        "stream": False,
    }
    response = request_json(
        endpoint,
        payload,
        {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    content = response["choices"][0]["message"]["content"]
    return {"data": json.loads(content), "usage": response.get("usage") or {}}


def enrich_with_deepseek(batch_size: int) -> None:
    source_paths = [
        GREY_DIR / "grey_broad_results.csv",
        GREY_DIR / "grey_targeted_results.csv",
    ]
    rows = [row for path in source_paths for row in read_csv(path)]
    unique_rows_by_url: dict[str, dict[str, str]] = {}
    for row in rows:
        unique_rows_by_url.setdefault(row["url"], row)
    unique_rows = list(unique_rows_by_url.values())
    metadata_by_url: dict[str, dict[str, object]] = {}
    usage_totals: Counter = Counter()
    allowed_types = (
        "government_report, regulator_assessment, environmental_assessment, "
        "monitoring_report, operator_or_industry_report, consultancy_report, "
        "thesis_or_dissertation, conference_or_proceedings, repository_record, "
        "project_or_program_page, journal_or_publisher_page, other, uncertain"
    )

    for start in range(0, len(unique_rows), batch_size):
        batch = unique_rows[start : start + batch_size]
        print(
            f"DeepSeek metadata: {start + 1}-{start + len(batch)}/{len(unique_rows)} unique URLs",
            flush=True,
        )
        items = [
            {
                "id": str(index),
                "title": row["title"][:500],
                "url": row["url"][:1000],
                "search_snippet": row["content"][:1500],
            }
            for index, row in enumerate(batch)
        ]
        system_prompt = (
            "Return JSON only. Add descriptive metadata to every supplied web-search "
            "record. Do not judge topical relevance, remove records, or invent details. "
            "Use null when metadata is not stated or safely inferable from title, URL, "
            "or snippet. This metadata is unverified and is not evidence."
        )
        user_prompt = json.dumps(
            {
                "task": "Classify document type and extract plainly indicated metadata.",
                "allowed_document_types": allowed_types,
                "output_schema": {
                    "records": [
                        {
                            "id": "input id",
                            "document_type": "one allowed value",
                            "issuing_organization": "string or null",
                            "publication_year": "four-digit year or null",
                            "language": "language name or null",
                            "full_document_guess": "yes, no, or uncertain",
                        }
                    ]
                },
                "records": items,
            },
            ensure_ascii=False,
        )
        response = deepseek_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Produce the requested JSON.\n" + user_prompt},
            ]
        )
        for key, value in response["usage"].items():
            if isinstance(value, (int, float)):
                usage_totals[key] += value
        returned = response["data"].get("records") or []
        by_id = {str(item.get("id")): item for item in returned}
        for index, row in enumerate(batch):
            item = by_id.get(str(index), {})
            metadata_by_url[row["url"]] = {
                "deepseek_document_type": item.get("document_type") or "",
                "deepseek_issuing_organization": item.get("issuing_organization") or "",
                "deepseek_publication_year": item.get("publication_year") or "",
                "deepseek_language": item.get("language") or "",
                "deepseek_full_document_guess": item.get("full_document_guess") or "",
                "deepseek_metadata_status": (
                    "unverified_descriptive_metadata" if item else "missing_from_model_response"
                ),
            }
        time.sleep(0.2)

    output_rows = [{**row, **metadata_by_url[row["url"]]} for row in rows]

    output_path = GREY_DIR / "grey_candidates_enriched.csv"
    temporary_path = output_path.with_suffix(".csv.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ENRICHMENT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    temporary_path.replace(output_path)
    (GREY_DIR / "deepseek_metadata_summary.json").write_text(
        json.dumps(
            {
                "date_run": SEARCH_DATE,
                "record_count": len(output_rows),
                "unique_urls_submitted": len(unique_rows),
                "purpose": "Unverified descriptive metadata only; no screening or deduplication.",
                "usage": dict(usage_totals),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved {len(output_rows)} enriched rows to {output_path}")


def update_search_log() -> None:
    existing_rows = read_csv(SEARCH_LOG_PATH)
    new_rows: list[dict[str, object]] = []
    for phase in ("broad", "targeted"):
        summary_path = GREY_DIR / f"grey_{phase}_search_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        output_file = f"step_4/grey/grey_{phase}_results.csv"
        for search in summary["searches"]:
            domains = " | ".join(search.get("domains") or [])
            scope = search["query"]
            if domains:
                scope += f" [domains: {domains}]"
            new_rows.append(
                {
                    "query_id": search["query_id"],
                    "system": "Tavily Search API",
                    "date_searched": summary["date_searched"],
                    "family": search["family"],
                    "query_or_scope": scope,
                    "result_count": search["result_count"],
                    "output_file": output_file,
                    "notes": (
                        f"{search['search_phase']}; target={search['target_name']}; "
                        "no screening or cross-query deduplication"
                    ),
                }
            )
    new_ids = {str(row["query_id"]) for row in new_rows}
    existing_rows = [row for row in existing_rows if row.get("query_id") not in new_ids]
    all_rows = existing_rows + new_rows
    with SEARCH_LOG_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Added {len(new_rows)} grey-literature searches to {SEARCH_LOG_PATH}")


def qa() -> None:
    broad = read_csv(GREY_DIR / "grey_broad_results.csv")
    targeted = read_csv(GREY_DIR / "grey_targeted_results.csv")
    enriched = read_csv(GREY_DIR / "grey_candidates_enriched.csv")
    if len(enriched) != len(broad) + len(targeted):
        raise RuntimeError("Enriched row count does not match raw search rows")
    for phase, rows in (("broad", broad), ("targeted", targeted)):
        if not rows:
            raise RuntimeError(f"No {phase} results were saved")
        for row in rows:
            if not row["query_id"] or not row["url"] or not row["title"]:
                raise RuntimeError(f"Required field missing in {phase} results")
            if len(row["content"]) > 600:
                raise RuntimeError(f"Stored content excerpt exceeds 600 characters in {phase}")
            if "\n" in row["content"] or "\r" in row["content"]:
                raise RuntimeError(f"Stored content excerpt is not single-line in {phase}")
    summary = {
        "date_validated": SEARCH_DATE,
        "broad_rows": len(broad),
        "targeted_rows": len(targeted),
        "enriched_rows": len(enriched),
        "unique_urls": len({row["url"] for row in enriched}),
        "query_hits_retained_with_duplicates": True,
        "relevance_screening_performed": False,
        "cross_query_deduplication_performed": False,
        "status": "passed",
    }
    (GREY_DIR / "grey_search_qa.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("broad", "targeted", "discover-domains", "enrich", "update-log", "qa"),
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if not 1 <= args.max_results <= 20:
        parser.error("--max-results must be between 1 and 20")
    if not 1 <= args.batch_size <= 30:
        parser.error("--batch-size must be between 1 and 30")

    if args.action in {"broad", "targeted"}:
        run_tavily_searches(args.action, args.max_results)
    elif args.action == "discover-domains":
        discover_domains()
    elif args.action == "enrich":
        enrich_with_deepseek(args.batch_size)
    elif args.action == "update-log":
        update_search_log()
    elif args.action == "qa":
        qa()


if __name__ == "__main__":
    main()
