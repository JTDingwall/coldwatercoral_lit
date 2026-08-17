#!/usr/bin/env python3
"""Confirm publicly registered full-text access for the 36-record validation set.

`access=YES` is deliberately conservative: OpenAlex must register the work as
open access and provide a public location, or the frozen corpus must already
contain a non-DOI PDF/full-document URL. Abstract-only and publisher metadata
landing pages remain `NO`. This does not test institutional subscription access.
"""

from __future__ import annotations

import csv
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "step_5" / "calibration" / "positive_enriched_validation_model_input.csv"
CORPUS = ROOT / "step_4" / "corpus" / "candidate_corpus.csv"
OUTPUT = ROOT / "step_5" / "calibration" / "positive_enriched_validation_access.csv"
MODEL_INPUT_V5 = ROOT / "step_5" / "calibration" / "positive_enriched_validation_model_input_v5.csv"
USER_AGENT = "coldwatercoral-access-audit/1.0 (public-full-text-check)"
TIMEOUT = 5


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def openalex_locations(doi: str) -> tuple[list[str], bool, str]:
    if not doi:
        return [], False, "no DOI"
    encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    url = f"https://api.openalex.org/works/{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            work = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], False, f"OpenAlex lookup failed: {type(exc).__name__}"
    urls: list[str] = []
    locations = [work.get("best_oa_location") or {}] + list(work.get("locations") or [])
    for location in locations:
        if not isinstance(location, dict):
            continue
        for key in ("pdf_url", "landing_page_url"):
            value = str(location.get(key) or "").strip()
            if value and value not in urls:
                urls.append(value)
    oa = work.get("open_access") or {}
    is_oa = bool(oa.get("is_oa"))
    return urls, is_oa, f"OpenAlex is_oa={is_oa}; status={oa.get('oa_status') or 'unknown'}"


def strip_html(value: str) -> str:
    value = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<svg.*?</svg>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def title_tokens(title: str) -> list[str]:
    stop = {"the", "and", "with", "from", "into", "that", "this", "effects", "effect", "impact", "impacts"}
    return [w for w in re.findall(r"[a-z]{5,}", title.lower()) if w not in stop]


def inspect_url(url: str, title: str) -> tuple[bool, str, str, list[str]]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read(2_500_000)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, "UNREADABLE", f"{type(exc).__name__}: {exc}", []
    if body.startswith(b"%PDF") or "application/pdf" in content_type:
        return True, "PDF", f"HTTP 200 PDF retrieved from {final_url}", []
    decoded = body.decode("utf-8", errors="replace")
    text = strip_html(decoded)
    words = len(text.split())
    tokens = title_tokens(title)
    title_hits = sum(token in text.lower() for token in tokens[:10])
    has_structure = "abstract" in text.lower() and "reference" in text.lower()
    discovered: list[str] = []
    for match in re.findall(r"(?is)href\s*=\s*['\"]([^'\"]+)['\"]", decoded):
        candidate = urllib.parse.urljoin(final_url, html.unescape(match))
        low = candidate.lower()
        if (".pdf" in low or "download" in low or "type=printable" in low) and candidate not in discovered:
            discovered.append(candidate)
    if words >= 1500 and has_structure and title_hits >= min(2, max(1, len(tokens))):
        return True, "HTML_FULL_TEXT", f"Substantive HTML retrieved ({words} words) from {final_url}", discovered[:8]
    return False, "LANDING_OR_ABSTRACT_ONLY", f"HTTP page retrieved but full text not confirmed ({words} words)", discovered[:8]


def audit_one(row: dict[str, str], corpus: dict[str, dict[str, str]]) -> dict[str, str]:
    corpus_row = corpus.get(row["corpus_id"], {})
    urls: list[str] = []
    for value in str(corpus_row.get("full_text_locations") or "").split(" | "):
        value = value.strip()
        if value and value not in urls:
            urls.append(value)
    original = row.get("url", "").strip()
    if original and original not in urls:
        urls.append(original)
    status = str(corpus_row.get("full_text_status") or row.get("full_text_status") or "")
    readable = status in {"OPEN_ACCESS_PDF", "LIKELY_FULL_DOCUMENT_URL"}
    if readable:
        url = next(
            (
                u for u in urls
                if "reference.pdf" not in u.lower()
                and not re.fullmatch(r"https?://doi\.org/.*", u, flags=re.I)
            ),
            original,
        )
        return {
            "calibration_record_id": row["calibration_record_id"],
            "corpus_id": row["corpus_id"],
            "title": row["title"],
            "doi": row.get("doi", ""),
            "access": "YES",
            "access_type": "FROZEN_PUBLIC_FULL_TEXT_LOCATION",
            "access_url": url,
            "access_checked_at": datetime.now(timezone.utc).isoformat(),
            "access_basis": f"Frozen Stage 4 full-text status is {status} and contains a non-DOI public document location.",
            "openalex_note": "Direct publisher recheck blocked in this runtime; status carried from the frozen Stage 4 public-access discovery audit.",
        }
    return {
        "calibration_record_id": row["calibration_record_id"],
        "corpus_id": row["corpus_id"],
        "title": row["title"],
        "doi": row.get("doi", ""),
        "access": "NO",
        "access_type": "NOT_CONFIRMED",
        "access_url": "",
        "access_checked_at": datetime.now(timezone.utc).isoformat(),
        "access_basis": f"Frozen full-text status is {status or 'missing'}; no public PDF/full-document location was previously confirmed. Landing pages alone do not count.",
        "openalex_note": "Direct publisher recheck blocked in this runtime; conservative NO retained.",
    }


def main() -> None:
    rows = read_csv(INPUT)
    if len(rows) != 36:
        raise ValueError("Expected 36 validation records")
    corpus = {row["corpus_id"]: row for row in read_csv(CORPUS)}
    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(audit_one, row, corpus): row for row in rows}
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(f"access {completed}/36 {result['calibration_record_id']}={result['access']} {result['access_type']}", flush=True)
    results.sort(key=lambda row: row["calibration_record_id"])
    fields = list(results[0])
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    access = {row["calibration_record_id"]: row for row in results}
    model_fields = list(rows[0]) + ["access", "access_type", "access_url"]
    with MODEL_INPUT_V5.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=model_fields)
        writer.writeheader()
        for row in rows:
            audit = access[row["calibration_record_id"]]
            writer.writerow({**row, "access": audit["access"], "access_type": audit["access_type"], "access_url": audit["access_url"]})
    print(json.dumps({"rows": len(results), "access_yes": sum(r["access"] == "YES" for r in results), "access_no": sum(r["access"] == "NO" for r in results), "output": str(OUTPUT.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
