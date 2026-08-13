#!/usr/bin/env python3
"""Run the eight frozen query families against Semantic Scholar.

Uses only the Python standard library. Results remain separate by query family;
this script does not screen or deduplicate across families.
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path


API_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
SEARCH_DATE = date.today().isoformat()
OUTPUT_DIR = Path(__file__).resolve().parent / "semantic_scholar"
FIELDS = (
    "paperId,corpusId,externalIds,title,abstract,authors,venue,year,"
    "publicationDate,publicationTypes,url,isOpenAccess,openAccessPdf,"
    "citationCount,referenceCount,influentialCitationCount,fieldsOfStudy,"
    "s2FieldsOfStudy"
)

ORGANISMS = (
    '(coral* | octocoral* | gorgonian* | "sea pen*" | pennatula* | '
    'scleractinian* | antipatharian* | "black coral*" | Porifera | '
    'poriferan* | demosponge* | hexactinellid* | "glass sponge*" | '
    '"deep-sea sponge*" | "deep sea sponge*" | "cold-water sponge*" | '
    '"cold water sponge*")'
)

CORALS = (
    '(coral* | octocoral* | gorgonian* | "sea pen*" | pennatula* | '
    'scleractinian* | antipatharian* | "black coral*")'
)

SPONGES = (
    '(Porifera | poriferan* | demosponge* | hexactinellid* | '
    '"glass sponge*" | "deep-sea sponge*" | "deep sea sponge*" | '
    '"cold-water sponge*" | "cold water sponge*")'
)

QUERIES = {
    "SS_SED_SUSPENDED_01": {
        "family": "SED_SUSPENDED",
        "query": ORGANISMS
        + ' + ("suspended sediment*" | "suspended solid*" | '
        '"suspended particle*" | turbidity | resuspension | '
        '"particle concentration*" | "sediment plume*")',
    },
    "SS_SED_DEPOSITION_01": {
        "family": "SED_DEPOSITION",
        "query": ORGANISMS
        + ' + ("sediment deposition" | "sediment accumulation" | '
        '"sediment load*" | burial | smother* | "sediment cover*" | '
        '"sediment thickness" | "deposition rate*")',
    },
    "SS_SED_DRILLING_01": {
        "family": "SED_DRILLING",
        "query": ORGANISMS
        + ' + ("drill cutting*" | "drilling mud*" | "drilling fluid*" | '
        '"drilling discharge*" | "drilling waste*" | "cuttings pile*" | '
        '("offshore drilling" + (sediment* | bentonite | barite | '
        'particulate* | discharge*)))',
    },
    "SS_SED_DREDGING_01": {
        "family": "SED_DREDGING",
        "query": ORGANISMS
        + ' + (dredg* | "dredge plume*" | "dredging plume*" | '
        'resuspension | "resuspended sediment*" | "sediment plume*" | '
        '"spoil disposal" | "dredged material")',
    },
    "SS_SED_TAILINGS_01": {
        "family": "SED_TAILINGS",
        "query": ORGANISMS
        + ' + ("mine tailing*" | "mining tailing*" | '
        '"submarine tailing*" | "deep-sea mining" | "deep sea mining" | '
        '"seafloor massive sulphide*" | "seafloor massive sulfide*" | '
        '"mining plume*" | "marine disposal" | "particulate waste*")',
    },
    "SS_MECH_FEEDING_MUCUS_CORAL_01": {
        "family": "MECH_FEEDING_MUCUS_CORAL",
        "query": CORALS
        + ' + (sediment* | turbidity | "suspended solid*" | '
        '"suspended particle*" | burial | smother* | bentonite | barite | '
        '"drill cutting*") + (mucus | mucous | mucociliary | '
        '"sediment rejection" | "sediment clearance" | '
        '"particle rejection" | feeding | "food capture" | "prey capture" | '
        '"polyp activity" | "tentacle activity")',
    },
    "SS_MECH_FEEDING_PUMPING_SPONGE_01": {
        "family": "MECH_FEEDING_PUMPING_SPONGE",
        "query": SPONGES
        + ' + (sediment* | turbidity | "suspended solid*" | '
        '"suspended particle*" | bentonite | barite | "drill cutting*") + '
        '(pumping | filtration | "feeding current*" | "food capture" | '
        'clogging | "particle clearance" | "clearance rate*")',
    },
    "SS_RESP_THRESHOLD_RECOVERY_01": {
        "family": "RESP_THRESHOLD_RECOVERY",
        "query": ORGANISMS
        + ' + ("suspended sediment*" | "sediment deposition" | '
        '"sediment accumulation" | "sediment load*" | turbidity | burial | '
        'smother* | "drill cutting*" | "drilling mud*" | '
        '"drilling discharge*" | "resuspended sediment*" | '
        '"sediment plume*") + (threshold* | tolerance | sensitiv* | '
        '"dose-response" | "dose response" | "exposure-response" | '
        '"exposure response" | recovery | mortality | survival | '
        '"chronic exposure" | "acute exposure")',
    },
}

CSV_FIELDS = [
    "query_id",
    "family",
    "source",
    "date_searched",
    "paper_id",
    "corpus_id",
    "title",
    "authors",
    "year",
    "publication_date",
    "venue",
    "publication_types",
    "doi",
    "arxiv_id",
    "pubmed_id",
    "url",
    "is_open_access",
    "open_access_pdf_url",
    "citation_count",
    "reference_count",
    "influential_citation_count",
    "fields_of_study",
    "s2_fields_of_study",
    "abstract",
]


def request_json(params: dict[str, str], max_attempts: int = 8) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "coldwatercoral_lit/1.0"}
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    for attempt in range(max_attempts):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = error.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else min(60.0, 5.0 * 2**attempt)
            print(f"HTTP {error.code}; retrying in {wait:.0f} s")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts - 1:
                raise
            wait = min(60.0, 5.0 * 2**attempt)
            print(f"Network error; retrying in {wait:.0f} s")
            time.sleep(wait)
    raise RuntimeError("Semantic Scholar request failed after retries")


def scalar_list(values) -> str:
    if not values:
        return ""
    return "; ".join(str(value) for value in values)


def paper_to_row(query_id: str, family: str, paper: dict) -> dict[str, object]:
    external_ids = paper.get("externalIds") or {}
    authors = paper.get("authors") or []
    open_access_pdf = paper.get("openAccessPdf") or {}
    s2_fields = paper.get("s2FieldsOfStudy") or []
    return {
        "query_id": query_id,
        "family": family,
        "source": "Semantic Scholar Academic Graph API",
        "date_searched": SEARCH_DATE,
        "paper_id": paper.get("paperId"),
        "corpus_id": paper.get("corpusId"),
        "title": paper.get("title"),
        "authors": "; ".join(author.get("name", "") for author in authors),
        "year": paper.get("year"),
        "publication_date": paper.get("publicationDate"),
        "venue": paper.get("venue"),
        "publication_types": scalar_list(paper.get("publicationTypes")),
        "doi": external_ids.get("DOI"),
        "arxiv_id": external_ids.get("ArXiv"),
        "pubmed_id": external_ids.get("PubMed"),
        "url": paper.get("url"),
        "is_open_access": paper.get("isOpenAccess"),
        "open_access_pdf_url": open_access_pdf.get("url"),
        "citation_count": paper.get("citationCount"),
        "reference_count": paper.get("referenceCount"),
        "influential_citation_count": paper.get("influentialCitationCount"),
        "fields_of_study": scalar_list(paper.get("fieldsOfStudy")),
        "s2_fields_of_study": "; ".join(
            field.get("category", "") for field in s2_fields
        ),
        "abstract": paper.get("abstract"),
    }


def run_query(query_id: str, family: str, query: str) -> dict[str, object]:
    print(f"Running {query_id}")
    params = {"query": query, "fields": FIELDS, "sort": "paperId:asc"}
    papers: list[dict] = []
    reported_total = None
    token = None

    while True:
        if token:
            params["token"] = token
        payload = request_json(params)
        if reported_total is None:
            reported_total = payload.get("total")
        batch = payload.get("data") or []
        papers.extend(batch)
        token = payload.get("token")
        print(f"  retrieved {len(papers)} (reported total {reported_total})")
        if not token:
            break
        time.sleep(1.1)

    paper_ids = [paper.get("paperId") for paper in papers]
    if len(paper_ids) != len(set(paper_ids)):
        raise RuntimeError(f"Duplicate paper IDs returned within {query_id}")

    output_path = OUTPUT_DIR / f"{query_id}.csv"
    temporary_path = output_path.with_suffix(".csv.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for paper in papers:
            writer.writerow(paper_to_row(query_id, family, paper))
    temporary_path.replace(output_path)

    return {
        "query_id": query_id,
        "family": family,
        "query": query,
        "reported_total": reported_total,
        "retrieved_count": len(papers),
        "output_file": output_path.relative_to(OUTPUT_DIR.parent.parent).as_posix(),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for query_id, specification in QUERIES.items():
        summaries.append(run_query(query_id, **specification))
        time.sleep(1.1)

    summary_path = OUTPUT_DIR / "semantic_scholar_search_summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "system": "Semantic Scholar Academic Graph API",
                "endpoint": API_URL,
                "date_searched": SEARCH_DATE,
                "notes": (
                    "No date or publication-type filters. Results are retained separately "
                    "by query family; no cross-family screening or deduplication."
                ),
                "searches": summaries,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")


if __name__ == "__main__":
    main()
