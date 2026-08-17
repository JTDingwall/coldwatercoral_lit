#!/usr/bin/env python3
"""Build a fresh, deterministic, positive-enriched prompt-v6 validation set.

The sample is drawn from the frozen Stage 4 corpus after excluding every record
used in the 400-record calibration, blinded benchmarks, prompt-v4/v5 positive-
enriched validation, and the prior benchmark replacement. Selection uses only
metadata text signals; no human labels or prior model decisions are loaded.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CAL = STEP5 / "calibration"
CORPUS = ROOT / "step_4" / "corpus" / "candidate_corpus.csv"
OUTPUT = CAL / "prompt_v6_fresh_validation_model_input.csv"
PROVENANCE = CAL / "prompt_v6_fresh_validation_provenance.csv"
QA = CAL / "prompt_v6_fresh_validation_qa.json"
SEED = "stage5-prompt-v6-independent-validation-20260817"
TARGETS = {
    "DEEPCOLD_RESPONSE": 30,
    "WARM_TROPICAL_HARD_NEGATIVE": 25,
    "DEEPCOLD_CONTEXT_OR_CITATION": 15,
    "AMBIGUOUS_TITLE_ONLY": 10,
}

ORGANISM = (
    "coral", "sponge", "porifera", "lophelia", "desmophyllum", "gorgonian",
    "octocoral", "sea pen", "seapen", "bamboo coral", "glass sponge",
)
SEDIMENT = (
    "sediment", "turbid", "drill cutting", "drilling mud", "drilling waste",
    "dredg", "burial", "buried", "smother", "tailing", "particle load",
    "particulate", "resuspension", "deposition", "seabed disturbance",
)
DEEPCOLD = (
    "cold-water", "cold water", "deep-sea", "deep sea", "deep-water",
    "deep water", "bathyal", "abyssal", "lophelia", "desmophyllum pertusum",
    "geodia barretti", "glass sponge", "sponge reef", "arctic", "boreal",
    "norwegian margin", "continental slope",
)
WARM_TROPICAL = (
    "tropical", "coral reef", "great barrier reef", "caribbean", "shallow-water",
    "shallow water", "reef-building", "zooxanthell", "bleaching", "acropora",
    "porites", "montastraea", "fiji", "maldives", "red sea", "hawaii",
    "indonesia", "philippines",
)
RESPONSE = (
    "mortality", "survival", "growth", "respiration", "oxygen consumption",
    "feeding", "pumping", "filtration", "clog", "polyp", "mucus", "mucous",
    "clearance", "tolerance", "tissue", "necrosis", "reproduction",
    "recruitment", "recovery", "physiolog", "behavio", "dose-response",
    "dose response", "threshold", "metabolic", "stress response",
)
CONTEXT = (
    "monitor", "management", "review", "distribution", "habitat", "survey",
    "assessment", "strategy", "guideline", "mapping", "occurrence",
)
NON_SOURCE_TITLE = (
    "peer review #", "figure 1 from", "[pdf]", " - dataset", " - sciencedirect",
    "| semantic scholar", "reply on rc", "comment on egusphere",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(value: str) -> str:
    return hashlib.sha256(f"{SEED}|{value}".encode()).hexdigest()


def has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def title_key(title: str) -> str:
    value = re.sub(r"<[^>]+>", " ", title.lower())
    value = re.sub(r"\s*(?:\|| - )(?:sciencedirect|semantic scholar|dataset).*?$", "", value)
    value = re.sub(r"^\[pdf\]\s*", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def main() -> None:
    corpus = read_csv(CORPUS)
    calibration = read_csv(CAL / "calibration_sample.csv")
    benchmarks = read_csv(CAL / "benchmark_key_adjudicated.csv")
    positive = read_csv(CAL / "positive_enriched_validation_model_input_v5.csv")
    prior_rows = calibration + benchmarks + positive
    used = {row["corpus_id"] for row in prior_rows}
    used_titles = {title_key(row["title"]) for row in prior_rows if row.get("title", "").strip()}
    used_dois = {row["doi"].strip().lower() for row in prior_rows if row.get("doi", "").strip()}
    used.add("CWC-104B2C5A7924")

    eligible: list[dict[str, str]] = []
    for row in corpus:
        if (
            row["corpus_id"] in used
            or title_key(row["title"]) in used_titles
            or (row["doi"].strip() and row["doi"].strip().lower() in used_dois)
        ):
            continue
        if has(row["title"].lower(), NON_SOURCE_TITLE):
            continue
        text = f"{row['title']} {row['abstract_or_snippet']}".lower()
        if not has(text, ORGANISM) or not has(text, SEDIMENT):
            continue
        enriched = dict(row)
        enriched["_text"] = text
        enriched["_deepcold"] = str(has(text, DEEPCOLD))
        enriched["_warm"] = str(has(text, WARM_TROPICAL))
        enriched["_response"] = str(has(text, RESPONSE))
        enriched["_context"] = str(has(text, CONTEXT))
        eligible.append(enriched)

    pools = {
        "DEEPCOLD_RESPONSE": [
            row for row in eligible
            if row["abstract_or_snippet"].strip()
            and has(row["title"].lower(), ORGANISM)
            and has(row["title"].lower(), DEEPCOLD)
            and row["_response"] == "True"
            and not has(row["title"].lower(), WARM_TROPICAL)
        ],
        "WARM_TROPICAL_HARD_NEGATIVE": [
            row for row in eligible
            if row["abstract_or_snippet"].strip()
            and has(row["title"].lower(), ORGANISM)
            and has(row["title"].lower(), WARM_TROPICAL)
            and row["_response"] == "True"
            and not has(row["title"].lower(), DEEPCOLD)
        ],
        "DEEPCOLD_CONTEXT_OR_CITATION": [
            row for row in eligible
            if row["abstract_or_snippet"].strip()
            and has(row["title"].lower(), ORGANISM)
            and has(row["title"].lower(), DEEPCOLD)
            and (row["_response"] == "False" or row["_context"] == "True")
        ],
        "AMBIGUOUS_TITLE_ONLY": [
            row for row in eligible if not row["abstract_or_snippet"].strip()
        ],
    }

    selected: list[tuple[dict[str, str], str]] = []
    selected_ids: set[str] = set()
    selected_titles: set[str] = set()
    pool_counts = {name: len(rows) for name, rows in pools.items()}
    for stratum, target in TARGETS.items():
        def priority(row: dict[str, str]) -> tuple[int, str]:
            title = row["title"].lower()
            score = (
                3 * int(has(title, SEDIMENT))
                + 2 * int(has(title, RESPONSE))
                + int(has(title, CONTEXT))
            )
            return (-score, digest(f"{stratum}|{row['corpus_id']}"))

        candidates = sorted(pools[stratum], key=priority)
        chosen: list[dict[str, str]] = []
        for row in candidates:
            key = title_key(row["title"])
            if row["corpus_id"] in selected_ids or key in selected_titles:
                continue
            chosen.append(row)
            selected_titles.add(key)
            if len(chosen) == target:
                break
        if len(chosen) != target:
            raise ValueError(f"Insufficient {stratum} candidates: wanted {target}, found {len(chosen)}")
        selected.extend((row, stratum) for row in chosen)
        selected_ids.update(row["corpus_id"] for row in chosen)

    selected.sort(key=lambda item: digest("shuffle|" + item[0]["corpus_id"]))
    model_rows: list[dict[str, str]] = []
    provenance_rows: list[dict[str, str]] = []
    for index, (row, stratum) in enumerate(selected, start=1):
        record_id = f"V6V-{index:03d}"
        model_rows.append({
            "calibration_record_id": record_id,
            "split": "PROMPT_V6_FRESH_VALIDATION",
            "corpus_id": row["corpus_id"],
            "title": row["title"],
            "authors": row["authors"],
            "year": row["year"],
            "source_title_or_issuer": row["source_title_or_issuer"],
            "document_type": row["document_type"],
            "doi": row["doi"],
            "url": row["url"],
            "language": row["language"],
            "screening_text": row["abstract_or_snippet"],
            "full_text_status": row["full_text_status"],
            "discovery_systems": row["discovery_systems"],
            "query_ids": row["query_ids"],
            "families": row["families"],
            "access": "NOT_AUDITED",
            "access_type": "NOT_AUDITED",
            "access_url": "",
        })
        provenance_rows.append({
            "calibration_record_id": record_id,
            "corpus_id": row["corpus_id"],
            "selection_stratum": stratum,
            "selection_seed": SEED,
            "selection_used_human_labels": "False",
            "selection_used_prior_model_decisions": "False",
        })

    write_csv(OUTPUT, model_rows)
    write_csv(PROVENANCE, provenance_rows)
    qa = {
        "rows": len(model_rows),
        "unique_record_ids": len({row["calibration_record_id"] for row in model_rows}),
        "unique_corpus_ids": len({row["corpus_id"] for row in model_rows}),
        "selection_seed": SEED,
        "targets": TARGETS,
        "selected_by_stratum": dict(Counter(row["selection_stratum"] for row in provenance_rows)),
        "candidate_pool_by_stratum": pool_counts,
        "prior_record_ids_excluded": len(used),
        "overlap_with_prior_sets": len(selected_ids & used),
        "normalized_title_overlap_with_prior_sets": sum(
            title_key(row["title"]) in used_titles for row in model_rows
        ),
        "doi_overlap_with_prior_sets": sum(
            bool(row["doi"].strip()) and row["doi"].strip().lower() in used_dois for row in model_rows
        ),
        "human_labels_loaded": False,
        "prior_model_decisions_loaded": False,
        "model_input_contains_category_columns": any(
            key in model_rows[0] for key in ("final_category", "human_decision", "model_decision")
        ),
    }
    QA.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
