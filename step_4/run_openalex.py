#!/usr/bin/env python3
"""Run the eight frozen Step 4 OpenAlex production searches."""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ORGANISMS = (
    '(coral OR octocoral OR gorgonian OR "sea pen" OR pennatula '
    'OR scleractinian OR antipatharian OR "black coral" OR Porifera '
    'OR poriferan OR demosponge OR hexactinellid OR "glass sponge" '
    'OR "deep-sea sponge" OR "deep sea sponge" OR "cold-water sponge" '
    'OR "cold water sponge")'
)

CORALS = (
    '(coral OR octocoral OR gorgonian OR "sea pen" OR pennatula '
    'OR scleractinian OR antipatharian OR "black coral")'
)

SPONGES = (
    '(Porifera OR poriferan OR demosponge OR hexactinellid '
    'OR "glass sponge" OR "deep-sea sponge" OR "deep sea sponge" '
    'OR "cold-water sponge" OR "cold water sponge")'
)

QUERIES = {
    "OA_SED_SUSPENDED_01": {
        "family": "SED_SUSPENDED",
        "query": ORGANISMS
        + ' AND ("suspended sediment" OR "suspended solid" OR '
        '"suspended particle" OR turbidity OR resuspension OR '
        '"particle concentration" OR "sediment plume")',
    },
    "OA_SED_DEPOSITION_01": {
        "family": "SED_DEPOSITION",
        "query": ORGANISMS
        + ' AND ("sediment deposition" OR "sediment accumulation" OR '
        '"sediment load" OR burial OR smother OR "sediment cover" OR '
        '"sediment thickness" OR "deposition rate")',
    },
    "OA_SED_DRILLING_01": {
        "family": "SED_DRILLING",
        "query": ORGANISMS
        + ' AND ("drill cutting" OR "drilling mud" OR "drilling fluid" OR '
        '"drilling discharge" OR "drilling waste" OR "cuttings pile" OR '
        '("offshore drilling" AND (sediment OR bentonite OR barite OR '
        'particulate OR discharge)))',
    },
    "OA_SED_DREDGING_01": {
        "family": "SED_DREDGING",
        "query": ORGANISMS
        + ' AND (dredging OR dredge OR "dredge plume" OR "dredging plume" '
        'OR resuspension OR "resuspended sediment" OR "sediment plume" OR '
        '"spoil disposal" OR "dredged material")',
    },
    "OA_SED_TAILINGS_01": {
        "family": "SED_TAILINGS",
        "query": ORGANISMS
        + ' AND ("mine tailing" OR "mining tailing" OR "submarine tailing" '
        'OR "deep-sea mining" OR "deep sea mining" OR '
        '"seafloor massive sulphide" OR "seafloor massive sulfide" OR '
        '"mining plume" OR "marine disposal" OR "particulate waste")',
    },
    "OA_MECH_FEEDING_MUCUS_CORAL_01": {
        "family": "MECH_FEEDING_MUCUS_CORAL",
        "query": CORALS
        + ' AND (sediment OR turbidity OR "suspended solid" OR '
        '"suspended particle" OR burial OR smother OR bentonite OR barite OR '
        '"drill cutting") AND (mucus OR mucous OR mucociliary OR '
        '"sediment rejection" OR "sediment clearance" OR '
        '"particle rejection" OR feeding OR "food capture" OR '
        '"prey capture" OR "polyp activity" OR "tentacle activity")',
    },
    "OA_MECH_FEEDING_PUMPING_SPONGE_01": {
        "family": "MECH_FEEDING_PUMPING_SPONGE",
        "query": SPONGES
        + ' AND (sediment OR turbidity OR "suspended solid" OR '
        '"suspended particle" OR bentonite OR barite OR "drill cutting") '
        'AND (pumping OR filtration OR "feeding current" OR "food capture" '
        'OR clogging OR "particle clearance" OR "clearance rate")',
    },
    "OA_RESP_THRESHOLD_RECOVERY_01": {
        "family": "RESP_THRESHOLD_RECOVERY",
        "query": ORGANISMS
        + ' AND (("suspended sediment" OR "sediment deposition" OR '
        '"sediment accumulation" OR "sediment load" OR turbidity OR burial '
        'OR smother OR "drill cutting" OR "drilling mud" OR '
        '"drilling discharge" OR "resuspended sediment" OR '
        '"sediment plume") AND (threshold OR tolerance OR sensitivity OR '
        'sensitive OR "dose-response" OR "dose response" OR '
        '"exposure-response" OR "exposure response" OR recovery OR '
        'mortality OR survival OR "chronic exposure" OR "acute exposure"))',
    },
}

SELECT_FIELDS = [
    "id",
    "ids",
    "doi",
    "title",
    "publication_year",
    "publication_date",
    "type",
    "language",
    "authorships",
    "primary_location",
    "open_access",
    "cited_by_count",
    "abstract_inverted_index",
    "topics",
    "keywords",
    "concepts",
    "referenced_works",
]

FIELDNAMES = [
    "query_id",
    "family",
    "retrieved_at_utc",
    "openalex_id",
    "doi",
    "title",
    "publication_year",
    "publication_date",
    "work_type",
    "language",
    "authors",
    "author_openalex_ids",
    "primary_source",
    "primary_source_openalex_id",
    "landing_page_url",
    "is_oa",
    "oa_status",
    "cited_by_count",
    "abstract",
    "topics",
    "keywords",
    "concepts",
    "referenced_works",
]


def reconstruct_abstract(index: dict | None) -> str:
    if not index:
        return ""
    positioned = []
    for word, positions in index.items():
        positioned.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(positioned))


def joined_names(items: list[dict] | None) -> str:
    return " | ".join((item.get("display_name") or "") for item in (items or []))


def request_json(params: dict[str, object], api_key: str | None) -> tuple[dict, str | None]:
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "JTDingwall/coldwatercoral_lit"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response), response.headers.get("x-ratelimit-remaining")
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                message = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"OpenAlex HTTP {exc.code}: {message}") from exc
            wait = int(exc.headers.get("Retry-After", 2**attempt))
            time.sleep(max(wait, 1))
        except urllib.error.URLError:
            if attempt == 5:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("OpenAlex request failed after retries")


def flatten_work(work: dict, query_id: str, family: str, retrieved_at: str) -> dict:
    authorships = work.get("authorships") or []
    authors = [item.get("author") or {} for item in authorships]
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    topics = work.get("topics") or []
    keywords = work.get("keywords") or []
    concepts = work.get("concepts") or []
    return {
        "query_id": query_id,
        "family": family,
        "retrieved_at_utc": retrieved_at,
        "openalex_id": work.get("id") or "",
        "doi": work.get("doi") or "",
        "title": work.get("title") or "",
        "publication_year": work.get("publication_year") or "",
        "publication_date": work.get("publication_date") or "",
        "work_type": work.get("type") or "",
        "language": work.get("language") or "",
        "authors": joined_names(authors),
        "author_openalex_ids": " | ".join((author.get("id") or "") for author in authors),
        "primary_source": source.get("display_name") or "",
        "primary_source_openalex_id": source.get("id") or "",
        "landing_page_url": primary_location.get("landing_page_url") or "",
        "is_oa": open_access.get("is_oa", ""),
        "oa_status": open_access.get("oa_status") or "",
        "cited_by_count": work.get("cited_by_count") or 0,
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "topics": joined_names(topics),
        "keywords": joined_names(keywords),
        "concepts": joined_names(concepts),
        "referenced_works": " | ".join(work.get("referenced_works") or []),
    }


def run_family(
    query_id: str,
    family: str,
    query: str,
    output_dir: Path,
    per_page: int,
    api_key: str | None,
) -> int:
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_path = output_dir / f"{query_id}.csv"
    rows: list[dict] = []
    page = 1
    expected_count = None

    while True:
        params = {
            "filter": "title_and_abstract.search:" + query,
            "page": page,
            "per_page": per_page,
            "select": ",".join(SELECT_FIELDS),
        }
        payload, remaining = request_json(params, api_key)
        if expected_count is None:
            expected_count = payload["meta"]["count"]
        results = payload.get("results") or []
        rows.extend(flatten_work(work, query_id, family, retrieved_at) for work in results)
        print(
            f"{query_id}: page {page}, {len(rows)}/{expected_count}, "
            f"credits remaining={remaining}",
            flush=True,
        )
        if len(rows) >= expected_count or not results:
            break
        page += 1

    if len(rows) != expected_count:
        raise RuntimeError(f"{query_id}: retrieved {len(rows)} of {expected_count} records")
    ids = [row["openalex_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{query_id}: duplicate OpenAlex IDs within family")

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("step_4/openalex"))
    parser.add_argument("--per-page", type=int, default=100)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    if not 1 <= args.per_page <= 200:
        parser.error("--per-page must be between 1 and 200")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for query_id, specification in QUERIES.items():
        summary[query_id] = run_family(
            query_id,
            specification["family"],
            specification["query"],
            args.output_dir,
            args.per_page,
            args.api_key,
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
