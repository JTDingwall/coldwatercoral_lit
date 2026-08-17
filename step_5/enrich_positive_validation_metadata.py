#!/usr/bin/env python3
"""Enrich title-only positive-validation rows from public Semantic Scholar metadata."""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "step_5" / "calibration"
INPUT = CAL / "positive_enriched_validation_review.csv"
OUTPUT = CAL / "positive_enriched_validation_review_enriched.csv"
LOG = CAL / "positive_enriched_validation_enrichment_log.csv"


def fetch(doi: str) -> dict[str, object]:
    encoded = urllib.parse.quote("DOI:" + doi, safe=":")
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/"
        + encoded
        + "?fields=title,abstract,externalIds,url"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "coldwatercoral-stage5/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_pubmed(doi: str) -> tuple[str, str]:
    query = urllib.parse.urlencode({
        "db": "pubmed",
        "term": f'"{doi}"[AID]',
        "retmode": "json",
    })
    with urllib.request.urlopen(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + query,
        timeout=20,
    ) as response:
        result = json.loads(response.read().decode("utf-8"))
    ids = result.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return "", ""
    pmid = str(ids[0])
    fetch_query = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "xml"})
    with urllib.request.urlopen(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + fetch_query,
        timeout=20,
    ) as response:
        root = ET.fromstring(response.read())
    parts = ["".join(node.itertext()).strip() for node in root.findall(".//AbstractText")]
    return " ".join(part for part in parts if part), pmid


def main() -> None:
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = list(rows[0]) + ["screening_text_source"]
    log_rows = []
    for row in rows:
        if row["screening_text"].strip():
            row["screening_text_source"] = "FROZEN_STAGE4_CORPUS"
            continue
        status = "NOT_ATTEMPTED_NO_DOI"
        abstract = ""
        paper_id = ""
        if row["doi"].strip():
            try:
                abstract, pmid = fetch_pubmed(row["doi"].strip())
                if abstract:
                    paper_id = "PMID:" + pmid
                    status = "ABSTRACT_ADDED_PUBMED"
                else:
                    result = fetch(row["doi"].strip())
                    abstract = str(result.get("abstract") or "").strip()
                    paper_id = str(result.get("paperId") or "")
                    status = (
                        "ABSTRACT_ADDED_SEMANTIC_SCHOLAR"
                        if abstract
                        else "NO_ABSTRACT_AVAILABLE"
                    )
            except Exception as exc:
                status = f"ERROR_{type(exc).__name__}"
            time.sleep(0.2)
        if abstract:
            row["screening_text"] = abstract
            row["screening_text_source"] = (
                "PUBMED_PUBLIC_METADATA"
                if paper_id.startswith("PMID:")
                else "SEMANTIC_SCHOLAR_PUBLIC_METADATA"
            )
        else:
            row["screening_text_source"] = "TITLE_ONLY"
        log_rows.append({
            "validation_record_id": row["validation_record_id"],
            "corpus_id": row["corpus_id"],
            "doi": row["doi"],
            "semantic_scholar_paper_id": paper_id,
            "status": status,
        })

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with LOG.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(log_rows[0]))
        writer.writeheader()
        writer.writerows(log_rows)
    print(f"rows={len(rows)}")
    print(f"abstracts_added={sum(r['status'].startswith('ABSTRACT_ADDED') for r in log_rows)}")
    print(f"remaining_title_only={sum(not r['screening_text'].strip() for r in rows)}")


if __name__ == "__main__":
    main()
