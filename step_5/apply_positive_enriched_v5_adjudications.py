#!/usr/bin/env python3
"""Apply the completed human review to the positive-enriched v5 model output.

The original DeepSeek classifications remain immutable. This script creates a
separate adjudicated table, decision log, retrieval queue, and evaluation so
the model output and human policy decisions remain independently auditable.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "step_5" / "runs" / "positive-enriched-deepseek-v5-20260817"
INPUT = RUN_DIR / "positive_enriched_v5_classifications.csv"
OUTPUT = RUN_DIR / "positive_enriched_v5_classifications_adjudicated.csv"
LOG = RUN_DIR / "positive_enriched_v5_adjudication_log.csv"
RETRIEVAL = RUN_DIR / "positive_enriched_v5_lawful_retrieval_queue_adjudicated.csv"
EVALUATION = RUN_DIR / "positive_enriched_v5_evaluation_adjudicated.json"

OVERRIDES = {
    "PEV-006": (
        "EXCLUDE",
        "X02_TROPICAL_NOT_CLOSELY_TRANSFERABLE",
        "Warm-water Great Barrier Reef sponge evidence is not sufficiently transferable to cold-water/deep-sea coral or sponge impacts.",
    ),
    "PEV-017": (
        "EXCLUDE",
        "X02_TROPICAL_NOT_CLOSELY_TRANSFERABLE",
        "Tropical Caribbean coral polyp responses are not sufficiently transferable to cold-water/deep-sea coral impacts.",
    ),
    "PEV-019": (
        "EXCLUDE",
        "X02_TROPICAL_NOT_CLOSELY_TRANSFERABLE",
        "Tropical Montastraea growth and sediment-rejection responses are not sufficiently transferable to cold-water/deep-sea coral impacts.",
    ),
    "PEV-022": (
        "EXCLUDE",
        "X05_RESPONSE_OUT_OF_SCOPE",
        "The title describes tropical coral-reef sedimentology and does not report an eligible cold-water coral or sponge biological response.",
    ),
    "PEV-024": (
        "EXCLUDE",
        "X04_SEDIMENT_PATHWAY_NOT_EXPLICIT",
        "Sediment is a carbonate-budget component rather than an explicit sediment stressor or exposure pathway affecting cold-water corals or sponges.",
    ),
    "PEV-029": (
        "EXCLUDE",
        "X02_TROPICAL_NOT_CLOSELY_TRANSFERABLE",
        "The tropical Porites turbidity-growth association is not sufficiently transferable to cold-water/deep-sea coral impacts.",
    ),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_csv(INPUT)
    if len(rows) != 36:
        raise ValueError("Expected 36 v5 classifications")
    ids = {row["validation_record_id"] for row in rows}
    if len(ids) != 36 or not set(OVERRIDES).issubset(ids):
        raise ValueError("Classification identifiers do not reconcile")

    adjudicated: list[dict[str, str]] = []
    log: list[dict[str, str]] = []
    for row in rows:
        record_id = row["validation_record_id"]
        model_category = row["final_category"]
        model_reason = row["reason_code"]
        final_category, final_reason, reviewer_note = OVERRIDES.get(
            record_id,
            (model_category, model_reason, "Accepted without change during completed human review."),
        )
        changed = record_id in OVERRIDES
        updated = {
            **row,
            "model_category": model_category,
            "model_reason_code": model_reason,
            "final_category": final_category,
            "reason_code": final_reason,
            "adjudication_status": "OVERRIDDEN" if changed else "ACCEPTED_AS_MODELLED",
            "human_review_complete": "True",
            "review_required": "False",
            "reviewer_note": reviewer_note,
        }
        adjudicated.append(updated)
        if changed:
            log.append({
                "validation_record_id": record_id,
                "corpus_id": row["corpus_id"],
                "title": row["title"],
                "model_category": model_category,
                "model_reason_code": model_reason,
                "final_category": final_category,
                "final_reason_code": final_reason,
                "reviewer_note": reviewer_note,
            })

    write_csv(OUTPUT, adjudicated)
    write_csv(LOG, log)
    retrieval = [
        row for row in adjudicated
        if row["access"] == "NO"
        and row["final_category"] in {"CORE_INCLUDE", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN"}
    ]
    write_csv(RETRIEVAL, retrieval)

    categories = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN", "EXCLUDE"]
    counts = Counter(row["final_category"] for row in adjudicated)
    result = {
        "split": "POSITIVE_ENRICHED_VALIDATION_V5_ADJUDICATED",
        "created_at": "2026-08-17",
        "rows": len(adjudicated),
        "human_review_complete": True,
        "model_output_preserved": True,
        "overrides": len(log),
        "classification_counts": {category: counts[category] for category in categories},
        "accepted_policy": {
            "all_core_includes_trusted": True,
            "warm_water_or_tropical_default": "EXCLUDE",
            "warm_water_trait_similarity_alone_transferable": False,
            "uncertain_records_retained": ["PEV-009", "PEV-023", "PEV-033", "PEV-036"],
            "citation_chain_candidates_retained": ["PEV-007", "PEV-030"],
        },
        "outstanding_classification_review_rows": 0,
        "lawful_retrieval_queue_rows": len(retrieval),
        "production_screening_approved": False,
        "production_hold_reason": "Prompt v6 incorporates the completed review but has not yet been independently validated for production.",
        "outputs": {
            "adjudicated_classifications": OUTPUT.name,
            "adjudication_log": LOG.name,
            "lawful_retrieval_queue": RETRIEVAL.name,
        },
    }
    EVALUATION.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
