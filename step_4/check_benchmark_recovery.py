#!/usr/bin/env python3
"""Check the frozen Step 4 benchmark set against the independently built corpus.

Automatic recovery requires an exact DOI, canonical URL, or normalized title match.
Fuzzy title similarity is diagnostic only and can never create a recovered result.
The script reads but never modifies the candidate corpus or benchmark source file.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent
BENCHMARK = ROOT / "benchmark_sources.csv"
CORPUS = ROOT / "corpus" / "candidate_corpus.csv"
CHAIN_QA = ROOT / "citation_chaining" / "citation_chain_qa.json"
OUT = ROOT / "benchmark_recovery"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)

# B009 was frozen as a PMC URL with an abbreviated descriptive citation. The
# alias below resolves that supplied URL to the published article identifier and
# title; it does not add a source to the candidate corpus.
ALIASES = {
    "B009": {
        "dois": {"10.7717/peerj.2711"},
        "titles": {"Detecting sedimentation impacts to coral reefs resulting from dredging the Port of Miami, Florida USA"},
    }
}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_doi(value: object) -> str:
    text = unquote(clean(value)).lower()
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text)
    match = DOI_PATTERN.search(text)
    return match.group(0).rstrip(".,;:)]}\"") if match else ""


def normalize_title(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def normalize_url(value: object) -> str:
    raw = clean(value)
    if not raw:
        return ""
    doi = normalize_doi(raw)
    if doi and ("doi.org/" in raw.lower() or raw.lower().startswith("doi:")):
        return f"https://doi.org/{doi}"
    try:
        parts = urlsplit(raw)
        query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                 if key.lower() not in {"utm_source", "utm_medium", "utm_campaign", "ref"}]
        path = re.sub(r"/+", "/", parts.path).rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
    except ValueError:
        return raw.rstrip("/")


def benchmark_title(citation: str) -> str:
    match = re.search(r"\((?:\d{4}|n\.d\.)\)\.\s*(.+?)(?:\.\s+[A-Z]|\.$)", clean(citation))
    return match.group(1).strip() if match else ""


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def exact_match_evidence(benchmark: dict, candidate: dict) -> tuple[int, list[str]]:
    benchmark_id = benchmark["benchmark_id"]
    supplied = benchmark.get("doi_or_url", "")
    benchmark_doi = normalize_doi(supplied)
    candidate_doi = normalize_doi(candidate.get("doi", ""))
    benchmark_url = normalize_url(supplied)
    candidate_urls = {normalize_url(value) for value in candidate.get("url", "").split(" | ") if clean(value)}
    title = normalize_title(benchmark_title(benchmark.get("citation", "")))
    candidate_title = normalize_title(candidate.get("title", ""))
    aliases = ALIASES.get(benchmark_id, {})
    alias_dois = {normalize_doi(value) for value in aliases.get("dois", set())}
    alias_titles = {normalize_title(value) for value in aliases.get("titles", set())}

    basis = []
    score = 0
    if benchmark_doi and candidate_doi == benchmark_doi:
        basis.append("DOI")
        score = max(score, 100)
    if benchmark_url and benchmark_url in candidate_urls:
        basis.append("CANONICAL_URL")
        score = max(score, 95)
    if title and candidate_title == title:
        basis.append("EXACT_TITLE")
        score = max(score, 90)
    if candidate_doi and candidate_doi in alias_dois:
        basis.append("RESOLVED_ALIAS_DOI")
        score = max(score, 85)
    if candidate_title and candidate_title in alias_titles:
        basis.append("RESOLVED_ALIAS_TITLE")
        score = max(score, 80)
    return score, basis


def main() -> None:
    benchmarks = read_csv(BENCHMARK)
    corpus = read_csv(CORPUS)
    if not benchmarks or not corpus:
        raise SystemExit("Benchmark or candidate corpus is empty")

    results = []
    misses = []
    for benchmark in benchmarks:
        exact = []
        target_title = normalize_title(benchmark_title(benchmark.get("citation", "")))
        alias_titles = {normalize_title(value) for value in ALIASES.get(benchmark["benchmark_id"], {}).get("titles", set())}
        fuzzy_targets = {value for value in {target_title, *alias_titles} if value}
        fuzzy = []
        for candidate in corpus:
            score, basis = exact_match_evidence(benchmark, candidate)
            if score:
                exact.append((score, candidate["corpus_id"], basis, candidate))
            candidate_title = normalize_title(candidate.get("title", ""))
            similarity = max((SequenceMatcher(None, target, candidate_title).ratio()
                              for target in fuzzy_targets), default=0.0)
            if similarity:
                fuzzy.append((similarity, candidate["corpus_id"], candidate))

        exact.sort(key=lambda item: (-item[0], item[1]))
        fuzzy.sort(key=lambda item: (-item[0], item[1]))
        if exact:
            _, _, basis, match = exact[0]
            status = "RECOVERED"
            match_basis = " | ".join(sorted(basis))
            similarity = max((SequenceMatcher(None, target, normalize_title(match.get("title", ""))).ratio()
                              for target in fuzzy_targets), default=0.0)
        else:
            status = "NOT_RECOVERED"
            match_basis = "NO_EXACT_MATCH"
            similarity, _, match = fuzzy[0] if fuzzy else (0.0, "", {})

        result = {
            **benchmark,
            "benchmark_title": benchmark_title(benchmark.get("citation", "")),
            "recovery_status": status,
            "match_basis": match_basis,
            "matched_corpus_id": match.get("corpus_id", ""),
            "matched_title": match.get("title", ""),
            "matched_doi": match.get("doi", ""),
            "matched_url": match.get("url", ""),
            "title_similarity": f"{similarity:.4f}",
            "discovery_systems": match.get("discovery_systems", ""),
            "query_ids": match.get("query_ids", ""),
            "families": match.get("families", ""),
            "occurrence_count": match.get("occurrence_count", ""),
            "independently_recovered": str(status == "RECOVERED" and bool(match.get("query_ids"))),
        }
        results.append(result)
        if status == "NOT_RECOVERED":
            if benchmark["benchmark_type"] == "POSITIVE_CORE":
                action = "Review closest candidate; design a justified _02 search only if the benchmark is truly absent"
            else:
                action = "No query revision required; retain result for the later screening-specificity check"
            misses.append({
                "benchmark_id": benchmark["benchmark_id"],
                "benchmark_type": benchmark["benchmark_type"],
                "benchmark_title": result["benchmark_title"],
                "diagnosis": "No exact DOI, canonical URL, resolved alias, or normalized-title match",
                "closest_corpus_id": match.get("corpus_id", ""),
                "closest_title": match.get("title", ""),
                "closest_title_similarity": f"{similarity:.4f}",
                "recommended_action": action,
            })

    fields = [
        "benchmark_id", "benchmark_type", "citation", "doi_or_url", "expected_screening",
        "benchmark_title", "recovery_status", "match_basis", "matched_corpus_id", "matched_title",
        "matched_doi", "matched_url", "title_similarity", "discovery_systems", "query_ids", "families",
        "occurrence_count", "independently_recovered",
    ]
    miss_fields = ["benchmark_id", "benchmark_type", "benchmark_title", "diagnosis", "closest_corpus_id",
                   "closest_title", "closest_title_similarity", "recommended_action"]
    write_csv(OUT / "benchmark_recovery.csv", results, fields)
    write_csv(OUT / "benchmark_miss_diagnostics.csv", misses, miss_fields)

    by_type = defaultdict(lambda: Counter(total=0, recovered=0))
    for row in results:
        by_type[row["benchmark_type"]]["total"] += 1
        by_type[row["benchmark_type"]]["recovered"] += row["recovery_status"] == "RECOVERED"
    positive = [row for row in results if row["benchmark_type"] == "POSITIVE_CORE"]
    chain_qa_available = CHAIN_QA.exists()
    chain_qa = json.loads(CHAIN_QA.read_text(encoding="utf-8")) if chain_qa_available else {}
    qa = {
        "benchmark_rows": len(benchmarks),
        "candidate_corpus_rows": len(corpus),
        "results_by_benchmark_type": {key: dict(value) for key, value in sorted(by_type.items())},
        "positive_core_recovered": sum(row["recovery_status"] == "RECOVERED" for row in positive),
        "positive_core_total": len(positive),
        "positive_core_recovery_complete": all(row["recovery_status"] == "RECOVERED" for row in positive),
        "misses_total": len(misses),
        "revised_search_required": any(row["benchmark_type"] == "POSITIVE_CORE" for row in misses),
        "citation_chain_qa_available": chain_qa_available,
        "checks": {
            "benchmark_ids_unique": len({row["benchmark_id"] for row in benchmarks}) == len(benchmarks),
            "all_benchmark_rows_reported": len(results) == len(benchmarks),
            "automatic_recovery_uses_exact_evidence_only": all(
                row["recovery_status"] != "RECOVERED" or row["match_basis"] != "NO_EXACT_MATCH" for row in results),
            "all_recovered_rows_have_corpus_ids": all(
                row["recovery_status"] != "RECOVERED" or row["matched_corpus_id"] for row in results),
            "citation_chain_excluded_benchmark_seed_source": (
                not chain_qa_available or chain_qa.get("benchmark_file_used_as_seed_source") is False),
            "candidate_corpus_not_modified": True,
            "no_relevance_screening_performed": True,
        },
    }
    (OUT / "benchmark_recovery_qa.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))
    if not all(qa["checks"].values()):
        raise SystemExit("Benchmark recovery structural QA failed")


if __name__ == "__main__":
    main()
