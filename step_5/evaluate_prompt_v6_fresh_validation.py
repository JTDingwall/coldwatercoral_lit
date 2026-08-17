#!/usr/bin/env python3
"""Evaluate prompt-v6 behaviour and build the focused human review packet."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "step_5" / "calibration"
RUN = ROOT / "step_5" / "runs" / "prompt-v6-fresh-deepseek-20260817"
INPUT = CAL / "prompt_v6_fresh_validation_model_input.csv"
PROVENANCE = CAL / "prompt_v6_fresh_validation_provenance.csv"
PREDICTIONS = RUN / "parsed_decisions.csv"
ACCESS = CAL / "prompt_v6_fresh_validation_access.csv"
CLASSIFICATIONS = RUN / "prompt_v6_fresh_classifications.csv"
REVIEW = RUN / "prompt_v6_fresh_human_review.csv"
REVIEW_COMPACT = RUN / "prompt_v6_fresh_human_review_compact.csv"
EVALUATION = RUN / "prompt_v6_fresh_evaluation.json"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN", "EXCLUDE"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    inputs = {row["calibration_record_id"]: row for row in read_csv(INPUT)}
    provenance = {row["calibration_record_id"]: row for row in read_csv(PROVENANCE)}
    predictions = {row["calibration_record_id"]: row for row in read_csv(PREDICTIONS)}
    access = {row["calibration_record_id"]: row for row in read_csv(ACCESS)}
    if not (len(inputs) == len(provenance) == len(predictions) == len(access) == 80):
        raise ValueError("Expected four 80-record validation tables")
    if set(inputs) != set(provenance) or set(inputs) != set(predictions) or set(inputs) != set(access):
        raise ValueError("Expected four reconciled 80-record tables")

    rows: list[dict[str, str]] = []
    for record_id in sorted(inputs):
        source = inputs[record_id]
        prov = provenance[record_id]
        model = predictions[record_id]
        access_row = access[record_id]
        decision = model["decision"]
        if decision not in CATEGORIES:
            raise ValueError(f"Invalid category for {record_id}: {decision}")
        priority_review = (
            decision in {"CITATION_CHAIN_CANDIDATE", "UNCERTAIN"}
            or (
                prov["selection_stratum"] == "DEEPCOLD_RESPONSE"
                and decision == "EXCLUDE"
            )
        )
        review_basis = ""
        if decision == "CITATION_CHAIN_CANDIDATE":
            review_basis = "Confirm that reference mining is specifically justified."
        elif decision == "UNCERTAIN":
            review_basis = "Resolve if the supplied title/abstract is sufficient; otherwise retain UNCERTAIN."
        elif priority_review:
            review_basis = "Audit possible silent exclusion from the deep/cold response-enriched stratum."
        rows.append({
            "validation_record_id": record_id,
            "corpus_id": source["corpus_id"],
            "selection_stratum": prov["selection_stratum"],
            "title": source["title"],
            "authors": source["authors"],
            "year": source["year"],
            "source_title_or_issuer": source["source_title_or_issuer"],
            "document_type": source["document_type"],
            "doi": source["doi"],
            "url": source["url"],
            "access": access_row["access"],
            "access_type": access_row["access_type"],
            "access_url": access_row["access_url"],
            "screening_text": source["screening_text"],
            "model_category": decision,
            "model_reason_code": model["reason_code"],
            "model_confidence": model["confidence"],
            "model_needs_full_text": model["needs_full_text"],
            "model_rationale": model["rationale"],
            "model_organism_evidence": model["organism_evidence"],
            "model_stressor_evidence": model["stressor_evidence"],
            "model_response_evidence": model["response_evidence"],
            "model_transferability_basis": model["transferability_basis"],
            "model_citation_chain_basis": model["citation_chain_basis"],
            "core_include_trusted": str(decision == "CORE_INCLUDE"),
            "priority_human_review": str(priority_review),
            "review_basis": review_basis,
            "final_category": "",
            "reviewer_note": "",
        })

    write_csv(CLASSIFICATIONS, rows)
    review = [row for row in rows if row["priority_human_review"] == "True"]
    write_csv(REVIEW, review)
    compact_fields = [
        "validation_record_id", "corpus_id", "selection_stratum", "title",
        "model_category", "model_reason_code", "model_confidence", "review_basis",
        "final_category", "reviewer_note", "model_rationale", "screening_text",
        "access", "access_type", "access_url", "document_type", "doi", "url",
    ]
    compact = [{field: row[field] for field in compact_fields} for row in review]
    write_csv(REVIEW_COMPACT, compact)
    counts = Counter(row["model_category"] for row in rows)
    by_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_stratum[row["selection_stratum"]][row["model_category"]] += 1
    tropical = [row for row in rows if row["selection_stratum"] == "WARM_TROPICAL_HARD_NEGATIVE"]
    deep_response_excludes = [
        row for row in rows
        if row["selection_stratum"] == "DEEPCOLD_RESPONSE" and row["model_category"] == "EXCLUDE"
    ]
    result = {
        "split": "PROMPT_V6_FRESH_VALIDATION",
        "rows": len(rows),
        "all_model_responses_valid": True,
        "classification_counts": {category: counts[category] for category in CATEGORIES},
        "counts_by_selection_stratum": {
            stratum: {category: counter[category] for category in CATEGORIES}
            for stratum, counter in sorted(by_stratum.items())
        },
        "critical_policy_checks": {
            "transferable_mechanism_rows": counts["TRANSFERABLE_MECHANISM"],
            "all_25_tropical_hard_negatives_excluded": all(row["model_category"] == "EXCLUDE" for row in tropical),
            "tropical_core_or_transferable_rows": sum(
                row["model_category"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"} for row in tropical
            ),
            "deepcold_response_stratum_excludes_for_audit": len(deep_response_excludes),
            "all_core_includes_trusted_by_user_policy": True,
        },
        "human_review": {
            "status": "REQUIRED",
            "rows": len(review),
            "citation_chain_candidates": counts["CITATION_CHAIN_CANDIDATE"],
            "uncertain": counts["UNCERTAIN"],
            "deepcold_response_exclusions": len(deep_response_excludes),
            "instructions": "Fill only final_category and reviewer_note. Keep UNCERTAIN when the supplied text is insufficient.",
        },
        "access_audit": {
            "yes": sum(row["access"] == "YES" for row in rows),
            "no": sum(row["access"] == "NO" for row in rows),
            "meaning": "YES confirms a frozen lawful public full-document location; NO does not test university subscription access.",
        },
        "production_screening_approved": False,
        "production_hold_reason": "The focused 21-record human review must be completed before prompt v6 can be frozen for production.",
        "outputs": {
            "classifications": CLASSIFICATIONS.name,
            "human_review": REVIEW.name,
            "human_review_compact": REVIEW_COMPACT.name,
        },
    }
    EVALUATION.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
