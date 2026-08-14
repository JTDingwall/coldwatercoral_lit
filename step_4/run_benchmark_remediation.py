#!/usr/bin/env python3
"""Run the documented benchmark-driven remediation search for B005.

This query is intentionally separated from independent production discovery.
Any result is labeled benchmark remediation and must not be counted as initial
independent benchmark recovery.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "benchmark_recovery"
SEARCH_LOG = ROOT / "search_log.csv"
QUERY_ID = "GL_USGS_SED_DRILLING_02"
QUERY = '"International team studies impacts of oil and gas drilling on cold-water corals"'
TARGET_TITLE = "International team studies impacts of oil and gas drilling on cold-water corals"
TARGET_URL = "https://www.usgs.gov/centers/spcmsc/news/international-team-studies-impacts-oil-and-gas-drilling-cold-water-corals"
TODAY = datetime.now(ZoneInfo("America/Vancouver")).date().isoformat()


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def normalize_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value.strip())
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def append_search_log(result_count: int) -> None:
    fields = ["query_id", "system", "date_searched", "family", "query_or_scope",
              "result_count", "output_file", "notes"]
    with SEARCH_LOG.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get("query_id") != QUERY_ID]
    rows.append({
        "query_id": QUERY_ID,
        "system": "Tavily Search API",
        "date_searched": TODAY,
        "family": "SED_DRILLING",
        "query_or_scope": f'{QUERY} [domains: usgs.gov]',
        "result_count": result_count,
        "output_file": "step_4/benchmark_recovery/remediation_search_results.csv",
        "notes": "benchmark-driven remediation after B005 independent-recovery miss; not counted as initial recovery",
    })
    write_csv(SEARCH_LOG, rows, fields)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_env(args.env_file)
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise SystemExit("TAVILY_API_KEY is not set")
    endpoint = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com").rstrip("/") + "/search"
    payload = {
        "api_key": api_key,
        "query": QUERY,
        "topic": "general",
        "search_depth": os.environ.get("TAVILY_SEARCH_DEPTH", "advanced"),
        "max_results": 10,
        "include_domains": ["usgs.gov"],
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_usage": True,
    }
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.load(response)
    retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = []
    exact = []
    for rank, item in enumerate(data.get("results") or [], 1):
        title = item.get("title") or ""
        url = item.get("url") or ""
        exact_title = normalize_text(title) == normalize_text(TARGET_TITLE)
        exact_url = normalize_url(url) == normalize_url(TARGET_URL)
        row = {
            "query_id": QUERY_ID,
            "benchmark_id": "B005",
            "system": "Tavily Search API",
            "date_searched": date.today().isoformat(),
            "retrieved_at_utc": retrieved,
            "query": QUERY,
            "include_domains": "usgs.gov",
            "result_rank": rank,
            "title": title,
            "url": url,
            "score": item.get("score", ""),
            "published_date": item.get("published_date") or "",
            "content": re.sub(r"\s+", " ", item.get("content") or "").strip()[:800],
            "exact_target_title": str(exact_title),
            "exact_target_url": str(exact_url),
        }
        rows.append(row)
        if exact_title or exact_url:
            exact.append(row)
    fields = ["query_id", "benchmark_id", "system", "date_searched", "retrieved_at_utc", "query",
              "include_domains", "result_rank", "title", "url", "score", "published_date", "content",
              "exact_target_title", "exact_target_url"]
    write_csv(OUT / "remediation_search_results.csv", rows, fields)
    candidate_fields = ["query_id", "benchmark_id", "system", "date_searched", "title", "url",
                        "remediation_basis", "initial_independent_recovery"]
    candidates = [{
        "query_id": QUERY_ID,
        "benchmark_id": "B005",
        "system": "Benchmark remediation",
        "date_searched": row["date_searched"],
        "title": row["title"],
        "url": row["url"],
        "remediation_basis": "EXACT_TITLE" if row["exact_target_title"] == "True" else "EXACT_URL",
        "initial_independent_recovery": "False",
    } for row in exact[:1]]

    extract_summary = {"url": TARGET_URL, "validated": False, "resolved_title": "", "content_characters": 0}
    if not candidates:
        extract_payload = {"api_key": api_key, "urls": [TARGET_URL], "extract_depth": "advanced",
                           "include_images": False}
        extract_request = urllib.request.Request(
            endpoint.rsplit("/", 1)[0] + "/extract",
            data=json.dumps(extract_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(extract_request, timeout=180) as response:
            extract_data = json.load(response)
        extracted = (extract_data.get("results") or [{}])[0]
        raw_content = extracted.get("raw_content") or ""
        lines = [re.sub(r"[#*_`>\[\]()]", " ", line).strip()
                 for line in raw_content.splitlines() if line.strip()]
        target_norm = normalize_text(TARGET_TITLE)
        resolved_title = max(lines, key=lambda line: SequenceMatcher(
            None, target_norm, normalize_text(line)).ratio(), default="")
        similarity = SequenceMatcher(None, target_norm, normalize_text(resolved_title)).ratio()
        validated = (target_norm in normalize_text(resolved_title) and
                     urllib.parse.urlsplit(extracted.get("url") or TARGET_URL).netloc.endswith("usgs.gov"))
        extract_summary = {
            "url": extracted.get("url") or TARGET_URL,
            "validated": validated,
            "resolved_title": resolved_title,
            "title_similarity": round(similarity, 4),
            "content_characters": len(raw_content),
        }
        if validated:
            candidates = [{
                "query_id": QUERY_ID,
                "benchmark_id": "B005",
                "system": "Benchmark remediation",
                "date_searched": TODAY,
                "title": resolved_title,
                "url": extracted.get("url") or TARGET_URL,
                "remediation_basis": "FROZEN_URL_EXTRACT_TITLE_MATCH",
                "initial_independent_recovery": "False",
            }]
    write_csv(OUT / "remediation_candidate.csv", candidates, candidate_fields)
    (OUT / "remediation_extract_validation.json").write_text(
        json.dumps(extract_summary, indent=2) + "\n", encoding="utf-8")
    append_search_log(len(rows))
    summary = {
        "query_id": QUERY_ID,
        "benchmark_id": "B005",
        "date_searched": TODAY,
        "query": QUERY,
        "include_domains": ["usgs.gov"],
        "result_count": len(rows),
        "exact_target_matches": len(exact),
        "validated_target_extract": extract_summary["validated"],
        "candidate_created": bool(candidates),
        "initial_independent_recovery": False,
        "classification": "BENCHMARK_REMEDIATION",
    }
    (OUT / "remediation_search_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
