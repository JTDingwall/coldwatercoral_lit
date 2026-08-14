#!/usr/bin/env python3
"""Build the Step 4 candidate corpus while preserving every discovery occurrence.

Deduplication order:
1. normalized DOI;
2. normalized title plus compatible publication year;
3. canonical URL;
4. conservative fuzzy title/first-author comparison.

The script never performs relevance screening. Ambiguous fuzzy pairs are retained as
separate records and recorded in ``corpus/fuzzy_review.csv``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "corpus"
SYSTEM_PRIORITY = {"OpenAlex": 4, "Citation chaining": 4, "Semantic Scholar": 3,
                   "Web of Science": 2, "Grey literature": 1, "Benchmark remediation": 1}
TRACKING_PARAMETERS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_PATTERN = re.compile(r"\b(18|19|20)\d{2}\b")


@dataclass
class Record:
    occurrence_id: str
    system: str
    query_id: str
    family: str
    source_file: str
    source_record_id: str = ""
    title: str = ""
    authors: str = ""
    year: str = ""
    publication_date: str = ""
    source_title: str = ""
    document_type: str = ""
    doi: str = ""
    url: str = ""
    language: str = ""
    abstract_or_snippet: str = ""
    retrieved_date: str = ""
    full_text_status: str = "NOT_IDENTIFIED"
    full_text_location: str = ""
    extra_identifiers: str = ""
    normalized_title: str = field(init=False, default="")
    canonical_url: str = field(init=False, default="")
    first_author: str = field(init=False, default="")

    def finalize(self) -> None:
        self.title = clean_space(self.title)
        self.authors = clean_space(self.authors)
        self.year = normalize_year(self.year or self.publication_date)
        self.doi = normalize_doi(self.doi)
        self.url = clean_space(self.url)
        self.normalized_title = normalize_title(self.title)
        self.canonical_url = normalize_url(self.url)
        self.first_author = first_author_surname(self.authors)
        self.abstract_or_snippet = clean_space(self.abstract_or_snippet)[:8000]


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        a, b = self.find(a), self.find(b)
        if a == b:
            return False
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1
        return True


def clean_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()


def normalize_doi(value: object) -> str:
    text = unquote(clean_space(value)).strip().lower()
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi\s*:\s*", "", text)
    match = DOI_PATTERN.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}\"").lower()


def doi_from_url(value: str) -> str:
    return normalize_doi(unquote(value))


def normalize_year(value: object) -> str:
    match = YEAR_PATTERN.search(clean_space(value))
    return match.group(0) if match else ""


def normalize_title(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean_space(value)).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"^(?:the|a|an)\s+", "", clean_space(text))
    return text


def normalize_url(value: object) -> str:
    raw = clean_space(value)
    if not raw:
        return ""
    if raw.lower().startswith("doi:") or "doi.org/" in raw.lower():
        doi = normalize_doi(raw)
        return f"https://doi.org/{doi}" if doi else raw
    try:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw.rstrip("/")
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k.lower() not in TRACKING_PARAMETERS]
        path = re.sub(r"/+", "/", parts.path).rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
    except ValueError:
        return raw.rstrip("/")


def first_author_surname(authors: str) -> str:
    if not authors:
        return ""
    first = re.split(r"\s*[|;]\s*", authors)[0].strip()
    if "," in first:
        surname = first.split(",", 1)[0]
    else:
        parts = first.split()
        surname = parts[-1] if parts else ""
    return normalize_title(surname)


def compatible_year(a: str, b: str) -> bool:
    if not a or not b:
        return True
    return abs(int(a) - int(b)) <= 1


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def load_document_manifest() -> tuple[dict[str, str], dict[str, list[str]]]:
    by_url: dict[str, str] = {}
    by_query: dict[str, list[str]] = defaultdict(list)
    path = ROOT / "documents" / "document_manifest.csv"
    for row in read_csv(path):
        location = f"step_4/documents/{row['filename']}"
        by_url[normalize_url(row.get("source_url"))] = location
        for query_id in row.get("discovery_query_ids", "").split("|"):
            if query_id.strip():
                by_query[query_id.strip()].append(location)
    return by_url, by_query


def parse_ris(path: Path) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = defaultdict(list)
    last_tag = ""
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"^([A-Z0-9]{2})  - ?(.*)$", raw_line)
        if match:
            tag, value = match.groups()
            if tag == "TY" and current:
                records.append(dict(current))
                current = defaultdict(list)
            current[tag].append(value.strip())
            last_tag = tag
            if tag == "ER":
                records.append(dict(current))
                current = defaultdict(list)
                last_tag = ""
        elif raw_line.startswith("  ") and last_tag and current.get(last_tag):
            current[last_tag][-1] += " " + raw_line.strip()
    if current:
        records.append(dict(current))
    return records


def add_record(records: list[Record], **kwargs) -> None:
    kwargs["occurrence_id"] = f"OCC{len(records) + 1:06d}"
    record = Record(**kwargs)
    record.finalize()
    records.append(record)


def load_records() -> tuple[list[Record], dict[str, int]]:
    records: list[Record] = []
    input_counts: dict[str, int] = {}
    archived_by_url, archived_by_query = load_document_manifest()

    for path in sorted((ROOT / "wos").glob("WOS_*.ris")):
        rows = parse_ris(path)
        input_counts[path.relative_to(ROOT).as_posix()] = len(rows)
        query_id = path.stem
        family = query_id.removeprefix("WOS_").removesuffix("_01")
        for row in rows:
            get = lambda tag: row.get(tag, [""])[0]
            url = get("UR") or (f"https://doi.org/{normalize_doi(get('DO'))}" if normalize_doi(get("DO")) else "")
            add_record(
                records, system="Web of Science", query_id=query_id, family=family,
                source_file=path.relative_to(ROOT).as_posix(), source_record_id=get("AN"),
                title=get("TI"), authors=" | ".join(row.get("AU", [])), year=get("PY"),
                publication_date=get("DA"), source_title=get("T2") or get("JO"),
                document_type=get("TY"), doi=get("DO"), url=url, language=get("LA"),
                abstract_or_snippet=get("AB"), retrieved_date="2026-08-13",
                extra_identifiers=get("AN"),
            )

    for path in sorted((ROOT / "openalex").glob("OA_*.csv")):
        rows = list(read_csv(path))
        input_counts[path.relative_to(ROOT).as_posix()] = len(rows)
        for row in rows:
            is_oa = row.get("is_oa", "").lower() == "true"
            url = row.get("landing_page_url") or row.get("doi") or row.get("openalex_id")
            add_record(
                records, system="OpenAlex", query_id=row.get("query_id", ""), family=row.get("family", ""),
                source_file=path.relative_to(ROOT).as_posix(), source_record_id=row.get("openalex_id", ""),
                title=row.get("title", ""), authors=row.get("authors", ""), year=row.get("publication_year", ""),
                publication_date=row.get("publication_date", ""), source_title=row.get("primary_source", ""),
                document_type=row.get("work_type", ""), doi=row.get("doi", ""), url=url,
                language=row.get("language", ""), abstract_or_snippet=row.get("abstract", ""),
                retrieved_date=row.get("retrieved_at_utc", "")[:10],
                full_text_status="OPEN_ACCESS_LANDING_PAGE" if is_oa else "NOT_IDENTIFIED",
                full_text_location=url if is_oa else "",
                extra_identifiers=" | ".join(filter(None, [row.get("openalex_id", ""), row.get("primary_source_openalex_id", "")])),
            )

    for path in sorted((ROOT / "semantic_scholar").glob("SS_*.csv")):
        rows = list(read_csv(path))
        input_counts[path.relative_to(ROOT).as_posix()] = len(rows)
        for row in rows:
            pdf_url = row.get("open_access_pdf_url", "")
            add_record(
                records, system="Semantic Scholar", query_id=row.get("query_id", ""), family=row.get("family", ""),
                source_file=path.relative_to(ROOT).as_posix(), source_record_id=row.get("paper_id", ""),
                title=row.get("title", ""), authors=row.get("authors", ""), year=row.get("year", ""),
                publication_date=row.get("publication_date", ""), source_title=row.get("venue", ""),
                document_type=row.get("publication_types", ""), doi=row.get("doi", ""), url=row.get("url", ""),
                language="", abstract_or_snippet=row.get("abstract", ""), retrieved_date=row.get("date_searched", ""),
                full_text_status="OPEN_ACCESS_PDF" if pdf_url else "NOT_IDENTIFIED",
                full_text_location=pdf_url,
                extra_identifiers=" | ".join(filter(None, [row.get("paper_id", ""), row.get("corpus_id", ""), row.get("arxiv_id", ""), row.get("pubmed_id", "")])),
            )

    chain_path = ROOT / "citation_chaining" / "citation_candidates.csv"
    if chain_path.exists():
        chain_rows = list(read_csv(chain_path))
        input_counts[chain_path.relative_to(ROOT).as_posix()] = len(chain_rows)
        qa_path = ROOT / "citation_chaining" / "citation_chain_qa.json"
        chain_date = ""
        if qa_path.exists():
            chain_date = json.loads(qa_path.read_text(encoding="utf-8")).get("date_searched", "")
        for row in chain_rows:
            add_record(
                records, system="Citation chaining", query_id=row.get("query_ids", ""),
                family=row.get("families", ""), source_file=chain_path.relative_to(ROOT).as_posix(),
                source_record_id=row.get("openalex_id", ""), title=row.get("title", ""),
                authors=row.get("authors", ""), year=row.get("publication_year", ""),
                publication_date=row.get("publication_date", ""), source_title=row.get("primary_source", ""),
                document_type=row.get("work_type", ""), doi=row.get("doi", ""),
                url=row.get("landing_page_url", ""), language=row.get("language", ""),
                abstract_or_snippet=row.get("abstract", ""), retrieved_date=chain_date,
                full_text_status=row.get("full_text_status", "NOT_IDENTIFIED"),
                full_text_location=row.get("full_text_location", ""),
                extra_identifiers=" | ".join(filter(None, [
                    row.get("openalex_id", ""), row.get("parent_openalex_ids", ""),
                    row.get("parent_corpus_ids", ""),
                ])),
            )

    remediation_path = ROOT / "benchmark_recovery" / "remediation_candidate.csv"
    if remediation_path.exists():
        remediation_rows = list(read_csv(remediation_path))
        input_counts[remediation_path.relative_to(ROOT).as_posix()] = len(remediation_rows)
        for row in remediation_rows:
            add_record(
                records, system="Benchmark remediation", query_id=row.get("query_id", ""),
                family="SED_DRILLING", source_file=remediation_path.relative_to(ROOT).as_posix(),
                source_record_id=row.get("url", ""), title=row.get("title", ""), authors="",
                year="", publication_date="", source_title="U.S. Geological Survey",
                document_type="government_webpage", doi="", url=row.get("url", ""), language="en",
                abstract_or_snippet="", retrieved_date=row.get("date_searched", ""),
                full_text_status="OPEN_ACCESS_LANDING_PAGE", full_text_location=row.get("url", ""),
                extra_identifiers=" | ".join(filter(None, [
                    row.get("benchmark_id", ""), row.get("remediation_basis", ""),
                    "INITIAL_INDEPENDENT_RECOVERY_FALSE",
                ])),
            )

    grey_path = ROOT / "grey" / "grey_candidates_enriched.csv"
    grey_rows = list(read_csv(grey_path))
    input_counts[grey_path.relative_to(ROOT).as_posix()] = len(grey_rows)
    for row in grey_rows:
        url = row.get("url", "")
        canonical = normalize_url(url)
        archived = archived_by_url.get(canonical, "")
        if not archived:
            candidates = archived_by_query.get(row.get("query_id", ""), [])
            if len(set(candidates)) == 1 and canonical == normalize_url(row.get("url", "")):
                # Query membership alone is not enough to identify which returned URL was archived.
                archived = ""
        full_guess = row.get("deepseek_full_document_guess", "").strip().lower() in {"true", "yes", "y", "1"}
        status = "ARCHIVED" if archived else ("LIKELY_FULL_DOCUMENT_URL" if full_guess else "NOT_IDENTIFIED")
        location = archived or (url if full_guess else "")
        add_record(
            records, system="Grey literature", query_id=row.get("query_id", ""), family=row.get("family", ""),
            source_file=grey_path.relative_to(ROOT).as_posix(), source_record_id=url,
            title=row.get("title", ""), authors="", year=row.get("deepseek_publication_year", "") or row.get("published_date", ""),
            publication_date=row.get("published_date", ""), source_title=row.get("deepseek_issuing_organization", ""),
            document_type=row.get("deepseek_document_type", ""), doi=doi_from_url(url), url=url,
            language=row.get("deepseek_language", ""), abstract_or_snippet=row.get("content", ""),
            retrieved_date=row.get("date_searched", ""), full_text_status=status,
            full_text_location=location, extra_identifiers=row.get("target_id", ""),
        )
    return records, input_counts


def cluster_dois(indices: list[int], records: list[Record]) -> set[str]:
    return {records[i].doi for i in indices if records[i].doi}


def token_jaccard(a: str, b: str) -> float:
    aa, bb = set(a.split()), set(b.split())
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0


def fuzzy_decision(a: Record, b: Record) -> tuple[str, float, float, str]:
    ratio = SequenceMatcher(None, a.normalized_title, b.normalized_title).ratio()
    jaccard = token_jaccard(a.normalized_title, b.normalized_title)
    author_match = bool(a.first_author and b.first_author and a.first_author == b.first_author)
    author_missing = not a.first_author or not b.first_author
    if not compatible_year(a.year, b.year):
        return "KEEP_SEPARATE", ratio, jaccard, "publication years differ by more than one"
    if author_match and ratio >= 0.965 and jaccard >= 0.88:
        return "MERGE", ratio, jaccard, "very high title similarity and matching first author"
    if (author_match or author_missing) and ratio >= 0.985 and jaccard >= 0.94:
        return "MERGE", ratio, jaccard, "near-identical titles with compatible author evidence"
    return "KEEP_SEPARATE", ratio, jaccard, "similar but below conservative fuzzy-merge threshold"


def deduplicate(records: list[Record]):
    uf = UnionFind(len(records))
    edges: list[tuple[int, int, str]] = []
    conflicts: list[dict[str, str]] = []
    root_dois: dict[int, set[str]] = {i: ({record.doi} if record.doi else set()) for i, record in enumerate(records)}

    def safe_union(a: int, b: int, reason: str, key: str) -> bool:
        left_root, right_root = uf.find(a), uf.find(b)
        if left_root == right_root:
            return False
        left_dois = root_dois.get(left_root, set())
        right_dois = root_dois.get(right_root, set())
        if left_dois and right_dois and left_dois.isdisjoint(right_dois):
            conflicts.append({"match_key": key, "reason": reason,
                              "left_dois": " | ".join(sorted(left_dois)),
                              "right_dois": " | ".join(sorted(right_dois)),
                              "left_title": records[a].title, "right_title": records[b].title})
            return False
        if not uf.union(left_root, right_root):
            return False
        new_root = uf.find(left_root)
        old_root = right_root if new_root == left_root else left_root
        root_dois[new_root] = left_dois | right_dois
        root_dois.pop(old_root, None)
        edges.append((a, b, reason))
        return True

    def union_bucket(bucket: dict[str, list[int]], reason: str, year_check: bool = False) -> None:
        for key, indices in bucket.items():
            if not key or len(indices) < 2:
                continue
            anchor = indices[0]
            for other in indices[1:]:
                if year_check and not compatible_year(records[anchor].year, records[other].year):
                    continue
                safe_union(anchor, other, reason, key)

    doi_bucket: dict[str, list[int]] = defaultdict(list)
    for i, record in enumerate(records):
        if record.doi:
            doi_bucket[record.doi].append(i)
    union_bucket(doi_bucket, "DOI")

    title_bucket: dict[str, list[int]] = defaultdict(list)
    for i, record in enumerate(records):
        if len(record.normalized_title) >= 15:
            title_bucket[record.normalized_title].append(i)
    union_bucket(title_bucket, "EXACT_TITLE_YEAR", year_check=True)

    url_bucket: dict[str, list[int]] = defaultdict(list)
    for i, record in enumerate(records):
        if record.canonical_url:
            url_bucket[record.canonical_url].append(i)
    union_bucket(url_bucket, "CANONICAL_URL")

    # Build current clusters and compare representative titles in narrow blocks.
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        clusters[uf.find(i)].append(i)
    representatives = {root: best_index(indices, records, "title") for root, indices in clusters.items()}
    blocks: dict[str, list[int]] = defaultdict(list)
    for root, index in representatives.items():
        title = records[index].normalized_title
        if len(title) >= 20:
            tokens = title.split()
            block = " ".join(tokens[:2])[:28]
            blocks[block].append(root)

    fuzzy_rows: list[dict[str, str]] = []
    cluster_members = {root: list(indices) for root, indices in clusters.items()}
    for roots in blocks.values():
        for pos, left_root in enumerate(roots):
            for right_root in roots[pos + 1:]:
                left_root, right_root = uf.find(left_root), uf.find(right_root)
                if left_root == right_root:
                    continue
                left_indices = cluster_members[left_root]
                right_indices = cluster_members[right_root]
                a = records[best_index(left_indices, records, "title")]
                b = records[best_index(right_indices, records, "title")]
                ratio = SequenceMatcher(None, a.normalized_title, b.normalized_title).ratio()
                jaccard = token_jaccard(a.normalized_title, b.normalized_title)
                if ratio < 0.88 and jaccard < 0.80:
                    continue
                left_dois, right_dois = cluster_dois(left_indices, records), cluster_dois(right_indices, records)
                if left_dois and right_dois and left_dois.isdisjoint(right_dois):
                    decision, rationale = "KEEP_SEPARATE", "conflicting non-empty DOIs"
                else:
                    decision, ratio, jaccard, rationale = fuzzy_decision(a, b)
                fuzzy_rows.append({
                    "left_occurrence_id": a.occurrence_id, "right_occurrence_id": b.occurrence_id,
                    "left_title": a.title, "right_title": b.title, "left_year": a.year, "right_year": b.year,
                    "left_first_author": a.first_author, "right_first_author": b.first_author,
                    "left_dois": " | ".join(sorted(left_dois)), "right_dois": " | ".join(sorted(right_dois)),
                    "sequence_similarity": f"{ratio:.4f}", "token_jaccard": f"{jaccard:.4f}",
                    "decision": decision, "rationale": rationale,
                })
                if decision == "MERGE" and safe_union(left_indices[0], right_indices[0], "FUZZY_TITLE_AUTHOR", "fuzzy"):
                    new_root = uf.find(left_root)
                    old_root = right_root if new_root == left_root else left_root
                    cluster_members[new_root] = left_indices + right_indices
                    cluster_members.pop(old_root, None)

    final_clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        final_clusters[uf.find(i)].append(i)
    unique_conflicts: list[dict[str, str]] = []
    seen_conflicts: set[tuple[str, ...]] = set()
    for row in conflicts:
        key = tuple(row[field] for field in ("match_key", "reason", "left_dois", "right_dois", "left_title", "right_title"))
        if key not in seen_conflicts:
            seen_conflicts.add(key)
            unique_conflicts.append(row)
    return final_clusters, edges, fuzzy_rows, unique_conflicts


def best_index(indices: list[int], records: list[Record], field_name: str) -> int:
    return max(indices, key=lambda i: (SYSTEM_PRIORITY[records[i].system], len(getattr(records[i], field_name)), -i))


def choose(indices: list[int], records: list[Record], field_name: str, longest: bool = False) -> str:
    candidates = [(i, getattr(records[i], field_name)) for i in indices if getattr(records[i], field_name)]
    if not candidates:
        return ""
    if longest:
        return max(candidates, key=lambda pair: (len(pair[1]), SYSTEM_PRIORITY[records[pair[0]].system]))[1]
    return max(candidates, key=lambda pair: (SYSTEM_PRIORITY[records[pair[0]].system], len(pair[1]), -pair[0]))[1]


def joined_unique(values) -> str:
    return " | ".join(sorted({clean_space(v) for v in values if clean_space(v)}))


def make_corpus_id(indices: list[int], records: list[Record]) -> str:
    dois = sorted({records[i].doi for i in indices if records[i].doi})
    if dois:
        key = "doi:" + dois[0]
    else:
        best = records[best_index(indices, records, "title")]
        key = f"title:{best.normalized_title}|year:{best.year}|url:{best.canonical_url}"
    return "CWC-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12].upper()


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_outputs(records: list[Record], input_counts: dict[str, int]) -> dict:
    clusters, edges, fuzzy_rows, conflicts = deduplicate(records)
    reason_by_member: dict[int, set[str]] = defaultdict(set)
    for left, right, reason in edges:
        reason_by_member[left].add(reason)
        reason_by_member[right].add(reason)

    ordered_clusters = sorted(clusters.values(), key=lambda ix: min(ix))
    corpus_rows: list[dict] = []
    provenance_rows: list[dict] = []
    cluster_rows: list[dict] = []
    corpus_ids: set[str] = set()
    for indices in ordered_clusters:
        corpus_id = make_corpus_id(indices, records)
        if corpus_id in corpus_ids:
            corpus_id += "-" + hashlib.sha1(str(indices).encode()).hexdigest()[:4].upper()
        corpus_ids.add(corpus_id)
        statuses = [records[i].full_text_status for i in indices]
        status_priority = ["ARCHIVED", "OPEN_ACCESS_PDF", "OPEN_ACCESS_LANDING_PAGE", "LIKELY_FULL_DOCUMENT_URL", "NOT_IDENTIFIED"]
        full_status = next((s for s in status_priority if s in statuses), "NOT_IDENTIFIED")
        full_locations = joined_unique(records[i].full_text_location for i in indices)
        all_reasons = sorted({reason for i in indices for reason in reason_by_member[i]})
        corpus_rows.append({
            "corpus_id": corpus_id,
            "title": choose(indices, records, "title"),
            "authors": choose(indices, records, "authors"),
            "year": choose(indices, records, "year"),
            "publication_date": choose(indices, records, "publication_date"),
            "source_title_or_issuer": choose(indices, records, "source_title"),
            "document_type": choose(indices, records, "document_type"),
            "doi": choose(indices, records, "doi"),
            "url": choose(indices, records, "url"),
            "language": choose(indices, records, "language"),
            "abstract_or_snippet": choose(indices, records, "abstract_or_snippet", longest=True),
            "full_text_status": full_status,
            "full_text_locations": full_locations,
            "discovery_systems": joined_unique(records[i].system for i in indices),
            "query_ids": joined_unique(records[i].query_id for i in indices),
            "families": joined_unique(records[i].family for i in indices),
            "source_record_ids": joined_unique(records[i].source_record_id for i in indices),
            "occurrence_count": len(indices),
            "deduplication_basis": " | ".join(all_reasons) if all_reasons else "SINGLETON",
        })
        for i in indices:
            r = records[i]
            provenance_rows.append({
                "corpus_id": corpus_id, "occurrence_id": r.occurrence_id, "discovery_system": r.system,
                "query_id": r.query_id, "family": r.family, "source_file": r.source_file,
                "source_record_id": r.source_record_id, "original_title": r.title, "original_authors": r.authors,
                "original_year": r.year, "original_doi": r.doi, "original_url": r.url,
                "retrieved_date": r.retrieved_date, "full_text_status": r.full_text_status,
                "full_text_location": r.full_text_location, "extra_identifiers": r.extra_identifiers,
            })
            cluster_rows.append({"corpus_id": corpus_id, "occurrence_id": r.occurrence_id,
                                 "deduplication_basis": " | ".join(sorted(reason_by_member[i])) or "SINGLETON"})

    corpus_fields = ["corpus_id", "title", "authors", "year", "publication_date", "source_title_or_issuer",
                     "document_type", "doi", "url", "language", "abstract_or_snippet", "full_text_status",
                     "full_text_locations", "discovery_systems", "query_ids", "families", "source_record_ids",
                     "occurrence_count", "deduplication_basis"]
    provenance_fields = ["corpus_id", "occurrence_id", "discovery_system", "query_id", "family", "source_file",
                         "source_record_id", "original_title", "original_authors", "original_year", "original_doi",
                         "original_url", "retrieved_date", "full_text_status", "full_text_location", "extra_identifiers"]
    fuzzy_fields = ["left_occurrence_id", "right_occurrence_id", "left_title", "right_title", "left_year", "right_year",
                    "left_first_author", "right_first_author", "left_dois", "right_dois", "sequence_similarity",
                    "token_jaccard", "decision", "rationale"]
    conflict_fields = ["match_key", "reason", "left_dois", "right_dois", "left_title", "right_title"]
    write_csv(OUT / "candidate_corpus.csv", corpus_rows, corpus_fields)
    write_csv(OUT / "candidate_corpus_provenance.csv", provenance_rows, provenance_fields)
    write_csv(OUT / "fuzzy_review.csv", fuzzy_rows, fuzzy_fields)
    write_csv(OUT / "identifier_conflicts.csv", conflicts, conflict_fields)

    system_occurrences = Counter(r.system for r in records)
    full_text_counts = Counter(row["full_text_status"] for row in corpus_rows)
    dedup_counts = Counter()
    for row in corpus_rows:
        for reason in row["deduplication_basis"].split(" | "):
            dedup_counts[reason] += 1
    qa = {
        "generated_date": max((r.retrieved_date for r in records if r.retrieved_date), default=""),
        "input_file_counts": input_counts,
        "input_occurrences_by_system": dict(sorted(system_occurrences.items())),
        "input_occurrences_total": len(records),
        "provenance_rows_total": len(provenance_rows),
        "unique_candidate_records": len(corpus_rows),
        "duplicate_occurrences_collapsed": len(records) - len(corpus_rows),
        "records_by_full_text_status": dict(full_text_counts),
        "clusters_by_deduplication_basis": dict(dedup_counts),
        "fuzzy_pairs_reviewed": len(fuzzy_rows),
        "fuzzy_pairs_merged": sum(row["decision"] == "MERGE" for row in fuzzy_rows),
        "fuzzy_pairs_kept_separate": sum(row["decision"] == "KEEP_SEPARATE" for row in fuzzy_rows),
        "identifier_conflicts_kept_separate": len(conflicts),
        "missing_title_records": sum(not row["title"] for row in corpus_rows),
        "missing_year_records": sum(not row["year"] for row in corpus_rows),
        "missing_doi_records": sum(not row["doi"] for row in corpus_rows),
        "checks": {
            "all_occurrences_preserved": len(records) == len(provenance_rows),
            "occurrence_counts_reconcile": sum(int(row["occurrence_count"]) for row in corpus_rows) == len(records),
            "occurrence_ids_unique": len({row["occurrence_id"] for row in provenance_rows}) == len(provenance_rows),
            "corpus_ids_unique": len(corpus_ids) == len(corpus_rows),
            "doi_values_unique_across_corpus": len([row["doi"] for row in corpus_rows if row["doi"]]) == len({row["doi"] for row in corpus_rows if row["doi"]}),
            "no_cluster_contains_conflicting_dois": all(len({records[i].doi for i in indices if records[i].doi}) <= 1 for indices in ordered_clusters),
            "every_provenance_row_has_corpus_id": all(row["corpus_id"] in corpus_ids for row in provenance_rows),
            "no_empty_query_ids": all(r.query_id for r in records),
            "full_text_locations_present_when_identified": all(row["full_text_status"] == "NOT_IDENTIFIED" or bool(row["full_text_locations"]) for row in corpus_rows),
            "no_relevance_screening_performed": True,
        },
    }
    (OUT / "corpus_qa.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return qa


def main() -> None:
    records, input_counts = load_records()
    qa = build_outputs(records, input_counts)
    if not all(qa["checks"].values()):
        raise SystemExit("Candidate corpus QA failed")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
