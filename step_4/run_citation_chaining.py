#!/usr/bin/env python3
"""Run two-generation OpenAlex citation chaining from objective corpus seeds.

The benchmark file is never read. Primary seeds must (1) contain both an in-scope
organism and stressor/mechanism term in the title, (2) have been independently
recovered by at least two discovery systems or at least three occurrences, and
(3) be resolvable to OpenAlex. Generation-2 seeds must satisfy the same title rule
and be supported by at least two parent sources or two discovery routes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus" / "candidate_corpus.csv"
OUT = ROOT / "citation_chaining"
API = "https://api.openalex.org"
SELECT_COMPACT = ",".join([
    "id", "doi", "title", "publication_year", "publication_date", "type", "language",
    "authorships", "primary_location", "open_access", "cited_by_count",
])
SELECT_FULL = ",".join([
    SELECT_COMPACT,
    "abstract_inverted_index", "referenced_works", "related_works", "ids",
])
ORGANISM = re.compile(
    r"\b(coral|corals|octocoral|gorgonian|sea pen|scleractinian|antipatharian|"
    r"black coral|sponge|sponges|porifera|demosponge|hexactinellid|glass sponge)\b", re.I)
STRESSOR = re.compile(
    r"\b(sediment|sedimentation|suspended solids|turbidity|burial|smother|"
    r"drill cuttings|drilling mud|dredg|tailings|resuspension|particle loading|"
    r"mucus|mucociliary|pumping|filtration|food capture)\w*", re.I)


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def short_id(value: str) -> str:
    return clean(value).rstrip("/").rsplit("/", 1)[-1]


def normalize_doi(value: str) -> str:
    value = clean(value).lower()
    value = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", value)
    return value.rstrip(".,;:)]}")


def chunks(values, size):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


class OpenAlex:
    def __init__(self) -> None:
        self.requests = 0
        self.retries = 0
        self.last_request = 0.0
        self.launch_lock = threading.Lock()

    def get(self, path: str, params: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = API + path + ("?" + query if query else "")
        for attempt in range(6):
            with self.launch_lock:
                delay = 0.11 - (time.monotonic() - self.last_request)
                if delay > 0:
                    time.sleep(delay)
                self.last_request = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": "coldwatercoral-lit/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    self.requests += 1
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 5:
                    raise
            except (TimeoutError, urllib.error.URLError):
                if attempt == 5:
                    raise
            self.retries += 1
            time.sleep(min(2 ** attempt, 20))
        raise RuntimeError("unreachable")

    def resolve_doi(self, doi: str) -> dict | None:
        if not doi:
            return None
        try:
            return self.get("/works/https://doi.org/" + urllib.parse.quote(doi, safe="/()"), {"select": SELECT_FULL})
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def fetch_works(self, work_ids, cache: dict[str, dict], *, full: bool = False) -> None:
        requested = {short_id(w) for w in work_ids if short_id(w)}
        if full:
            missing = sorted(w for w in requested if "referenced_works" not in cache.get(w, {}))
        else:
            missing = sorted(requested - set(cache))
        batches = list(chunks(missing, 100))

        def fetch_batch(batch):
            return self.get("/works", {
                "filter": "openalex_id:" + "|".join(batch),
                "per-page": 200,
                "select": SELECT_FULL if full else SELECT_COMPACT,
            })

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch_batch, batch) for batch in batches]
            for number, future in enumerate(as_completed(futures), 1):
                for work in future.result().get("results", []):
                    cache[short_id(work.get("id", ""))] = work
                if number % 25 == 0 or number == len(batches):
                    kind = "full" if full else "compact"
                    print(f"{kind} metadata batches: {number}/{len(batches)}; cached works: {len(cache)}", flush=True)

    def forward_citations(self, seed_ids, generation: int, edges: set[tuple[str, str, int, str]]) -> None:
        batches = list(chunks(sorted(set(seed_ids)), 20))
        for number, batch in enumerate(batches, 1):
            cursor = "*"
            batch_set = set(batch)
            while cursor:
                data = self.get("/works", {
                    "filter": "cites:" + "|".join(batch),
                    "per-page": 200,
                    "cursor": cursor,
                    "select": "id,referenced_works",
                })
                results = data.get("results", [])
                for work in results:
                    child = short_id(work.get("id", ""))
                    cited = batch_set & {short_id(x) for x in work.get("referenced_works", [])}
                    for parent in cited:
                        edges.add((parent, child, generation, "FORWARD_CITATION"))
                cursor = data.get("meta", {}).get("next_cursor") if results else None
            if number % 10 == 0 or number == len(batches):
                print(f"forward batches: {number}/{len(batches)}; edges: {len(edges)}", flush=True)


def abstract_text(work: dict) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    positions = [(position, word) for word, values in inverted.items() for position in values]
    return " ".join(word for _, word in sorted(positions))


def work_authors(work: dict) -> str:
    names = []
    for authorship in work.get("authorships") or []:
        name = clean((authorship.get("author") or {}).get("display_name"))
        if name:
            names.append(name)
    return " | ".join(names)


def source_name(work: dict) -> str:
    location = work.get("primary_location") or {}
    return clean((location.get("source") or {}).get("display_name"))


def landing_url(work: dict) -> str:
    location = work.get("primary_location") or {}
    return clean(location.get("landing_page_url") or work.get("doi") or work.get("id"))


def is_promising_title(title: str) -> bool:
    return bool(ORGANISM.search(title or "") and STRESSOR.search(title or ""))


def read_corpus() -> list[dict]:
    with CORPUS.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_edge_checkpoint(path: Path, seed_ids: list[str]) -> set[tuple[str, str, int, str]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("seed_openalex_ids") != seed_ids:
        return None
    return {tuple(edge) for edge in payload.get("edges", [])}


def save_edge_checkpoint(path: Path, seed_ids: list[str], edges: set[tuple[str, str, int, str]]) -> None:
    payload = {
        "seed_openalex_ids": seed_ids,
        "edges": sorted(edges, key=lambda x: (x[2], x[0], x[1], x[3])),
    }
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")


def build_primary_seeds(rows: list[dict], api: OpenAlex, cache: dict[str, dict]):
    seed_rows = []
    unresolved = []
    for row in rows:
        systems = len([x for x in row["discovery_systems"].split(" | ") if x])
        strong = systems >= 2 or int(row["occurrence_count"]) >= 3
        if not strong or not is_promising_title(row["title"]):
            continue
        oa_ids = sorted(set(re.findall(r"W\d+", row.get("source_record_ids", ""))))
        if not oa_ids and row.get("doi"):
            work = api.resolve_doi(normalize_doi(row["doi"]))
            if work:
                oa_id = short_id(work.get("id", ""))
                cache[oa_id] = work
                oa_ids = [oa_id]
        if not oa_ids:
            unresolved.append(row["corpus_id"])
            continue
        for oa_id in oa_ids:
            seed_rows.append({
                "seed_generation": 0,
                "corpus_id": row["corpus_id"],
                "openalex_id": oa_id,
                "title": row["title"],
                "doi": row["doi"],
                "families": row["families"],
                "discovery_systems": row["discovery_systems"],
                "occurrence_count": row["occurrence_count"],
                "seed_basis": "title organism+stressor; >=2 systems or >=3 occurrences",
            })
    return seed_rows, unresolved


def expand_metadata_edges(seed_ids, generation: int, cache: dict[str, dict], edges: set[tuple[str, str, int, str]]) -> None:
    for parent in sorted(set(seed_ids)):
        work = cache.get(parent) or {}
        for child in work.get("referenced_works") or []:
            edges.add((parent, short_id(child), generation, "BACKWARD_REFERENCE"))
        for child in work.get("related_works") or []:
            edges.add((parent, short_id(child), generation, "RELATED_WORK"))


def generation_two_seeds(g1_edges, cache: dict[str, dict], existing_ids: set[str]):
    support: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"parents": set(), "routes": set()})
    for parent, child, generation, route in g1_edges:
        if generation == 1:
            support[child]["parents"].add(parent)
            support[child]["routes"].add(route)
    selected = []
    for child, evidence in support.items():
        work = cache.get(child) or {}
        if child in existing_ids or not is_promising_title(clean(work.get("title"))):
            continue
        if len(evidence["parents"]) >= 2 or len(evidence["routes"]) >= 2:
            selected.append(child)
    return sorted(selected), support


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-generation", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    api = OpenAlex()
    rows = read_corpus()
    existing_ids = {x for row in rows for x in re.findall(r"W\d+", row.get("source_record_ids", ""))}
    existing_dois = {normalize_doi(row["doi"]) for row in rows if row.get("doi")}
    cache: dict[str, dict] = {}

    seed_rows, unresolved = build_primary_seeds(rows, api, cache)
    seed_ids = sorted({row["openalex_id"] for row in seed_rows})
    api.fetch_works(seed_ids, cache, full=True)
    resolved_seed_ids = sorted(set(seed_ids) & set(cache))
    seed_rows = [row for row in seed_rows if row["openalex_id"] in cache]
    print(f"primary seeds: {len(seed_rows)} rows / {len(resolved_seed_ids)} OpenAlex works", flush=True)

    checkpoint = OUT / "generation_1_edge_checkpoint.json"
    edges = load_edge_checkpoint(checkpoint, resolved_seed_ids)
    if edges is None:
        edges = set()
        expand_metadata_edges(resolved_seed_ids, 1, cache, edges)
        api.forward_citations(resolved_seed_ids, 1, edges)
        save_edge_checkpoint(checkpoint, resolved_seed_ids, edges)
    else:
        print(f"loaded generation-1 edge checkpoint: {len(edges)} edges", flush=True)
    g1_ids = {child for _, child, generation, _ in edges if generation == 1}
    api.fetch_works(g1_ids, cache)
    edges = {edge for edge in edges if edge[1] in cache}
    print(f"generation 1: {len(g1_ids)} linked IDs; {len(edges)} retained edges", flush=True)

    g2_seed_ids = []
    support = {}
    if args.max_generation >= 2:
        g2_seed_ids, support = generation_two_seeds(edges, cache, existing_ids)
        print(f"generation 2 seeds: {len(g2_seed_ids)}", flush=True)
        api.fetch_works(g2_seed_ids, cache, full=True)
        expand_metadata_edges(g2_seed_ids, 2, cache, edges)
        api.forward_citations(g2_seed_ids, 2, edges)
        g2_ids = {child for _, child, generation, _ in edges if generation == 2}
        api.fetch_works(g2_ids, cache)
        edges = {edge for edge in edges if edge[1] in cache}
        print(f"generation 2: {len(g2_ids)} linked IDs; {len(edges)} total edges", flush=True)

    seed_to_corpus: dict[str, set[str]] = defaultdict(set)
    seed_to_families: dict[str, set[str]] = defaultdict(set)
    for row in seed_rows:
        seed_to_corpus[row["openalex_id"]].add(row["corpus_id"])
        seed_to_families[row["openalex_id"]].update(row["families"].split(" | "))
    for g2 in g2_seed_ids:
        seed_to_corpus[g2].add(f"CHAIN_GENERATION_1:{g2}")
        for parent, child, generation, _ in edges:
            if generation == 1 and child == g2:
                seed_to_families[g2].update(seed_to_families.get(parent, set()))

    edge_rows = []
    discovery: dict[str, dict[str, set[str]]] = defaultdict(lambda: {
        "routes": set(), "generations": set(), "route_codes": set(), "parents": set(),
        "parent_corpus_ids": set(), "families": set(),
    })
    for parent, child, generation, route in sorted(edges, key=lambda x: (x[2], x[0], x[1], x[3])):
        parent_corpus = seed_to_corpus.get(parent, {"CHAIN_GENERATION_1"})
        inherited_families = seed_to_families.get(parent, set())
        edge_rows.append({
            "generation": generation, "route": route, "parent_openalex_id": parent,
            "parent_corpus_ids": " | ".join(sorted(parent_corpus)), "discovered_openalex_id": child,
            "inherited_families": " | ".join(sorted(inherited_families)),
        })
        item = discovery[child]
        item["routes"].add(route)
        item["generations"].add(str(generation))
        item["route_codes"].add(f"OA_CHAIN_G{generation}_{route}")
        item["parents"].add(parent)
        item["parent_corpus_ids"].update(parent_corpus)
        item["families"].update(inherited_families)

    candidate_rows = []
    new_ids = set()
    for work_id, evidence in sorted(discovery.items()):
        work = cache[work_id]
        doi = normalize_doi(work.get("doi", ""))
        already_present = work_id in existing_ids or (doi and doi in existing_dois)
        if not already_present:
            new_ids.add(work_id)
        oa = work.get("open_access") or {}
        location = work.get("primary_location") or {}
        pdf_url = clean(location.get("pdf_url"))
        is_oa = bool(oa.get("is_oa"))
        status = "OPEN_ACCESS_PDF" if pdf_url else ("OPEN_ACCESS_LANDING_PAGE" if is_oa else "NOT_IDENTIFIED")
        full_location = pdf_url or (landing_url(work) if is_oa else "")
        candidate_rows.append({
            "query_ids": " | ".join(sorted(evidence["route_codes"])),
            "families": " | ".join(sorted(evidence["families"])),
            "openalex_id": work_id,
            "doi": doi,
            "title": clean(work.get("title")),
            "publication_year": work.get("publication_year") or "",
            "publication_date": clean(work.get("publication_date")),
            "work_type": clean(work.get("type")),
            "language": clean(work.get("language")),
            "authors": work_authors(work),
            "primary_source": source_name(work),
            "landing_page_url": landing_url(work),
            "full_text_status": status,
            "full_text_location": full_location,
            "cited_by_count": work.get("cited_by_count") or 0,
            "abstract": abstract_text(work),
            "generations": " | ".join(sorted(evidence["generations"])),
            "routes": " | ".join(sorted(evidence["routes"])),
            "parent_openalex_ids": " | ".join(sorted(evidence["parents"])),
            "parent_corpus_ids": " | ".join(sorted(evidence["parent_corpus_ids"])),
            "parent_count": len(evidence["parents"]),
            "already_in_candidate_corpus": str(already_present),
        })

    seed_fields = ["seed_generation", "corpus_id", "openalex_id", "title", "doi", "families",
                   "discovery_systems", "occurrence_count", "seed_basis"]
    edge_fields = ["generation", "route", "parent_openalex_id", "parent_corpus_ids",
                   "discovered_openalex_id", "inherited_families"]
    candidate_fields = ["query_ids", "families", "openalex_id", "doi", "title", "publication_year",
                        "publication_date", "work_type", "language", "authors", "primary_source",
                        "landing_page_url", "full_text_status", "full_text_location", "cited_by_count",
                        "abstract", "generations", "routes", "parent_openalex_ids", "parent_corpus_ids",
                        "parent_count", "already_in_candidate_corpus"]
    write_csv(OUT / "seed_manifest.csv", seed_rows, seed_fields)
    write_csv(OUT / "citation_edges.csv", edge_rows, edge_fields)
    write_csv(OUT / "citation_candidates.csv", candidate_rows, candidate_fields)

    route_counts = Counter(row["route"] for row in edge_rows)
    generation_counts = Counter(str(row["generation"]) for row in edge_rows)
    qa = {
        "date_searched": date.today().isoformat(),
        "api": "OpenAlex Works API",
        "maximum_generation": args.max_generation,
        "benchmark_file_used_as_seed_source": False,
        "primary_seed_rows": len(seed_rows),
        "primary_seed_openalex_works": len(resolved_seed_ids),
        "unresolved_seed_candidates": len(unresolved) + len(set(seed_ids) - set(cache)),
        "generation_2_seed_works": len(g2_seed_ids),
        "citation_edges": len(edge_rows),
        "edges_by_route": dict(route_counts),
        "edges_by_generation": dict(generation_counts),
        "unique_discovered_openalex_works": len(candidate_rows),
        "new_to_candidate_corpus_before_merge": len(new_ids),
        "already_present_before_merge": len(candidate_rows) - len(new_ids),
        "api_requests": api.requests,
        "api_retries": api.retries,
        "checks": {
            "generation_cap_respected": all(int(row["generation"]) <= args.max_generation for row in edge_rows),
            "all_edges_have_parent_and_child": all(row["parent_openalex_id"] and row["discovered_openalex_id"] for row in edge_rows),
            "all_discovered_ids_have_metadata": all(row["openalex_id"] in cache for row in candidate_rows),
            "seed_manifest_excludes_benchmark_source": True,
            "no_relevance_screening_performed": True,
        },
    }
    (OUT / "citation_chain_qa.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2), flush=True)
    if not all(qa["checks"].values()):
        raise SystemExit("Citation-chain QA failed")
    checkpoint.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
