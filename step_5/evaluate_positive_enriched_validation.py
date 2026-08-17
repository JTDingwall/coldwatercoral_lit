#!/usr/bin/env python3
"""Evaluate prompt v4 on the fresh 36-record positive-enriched validation set."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "step_5" / "calibration" / "positive_enriched_validation_labels.csv"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "UNCERTAIN", "EXCLUDE"]
RELEVANT = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if not total:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def main() -> None:
    args = parse_args()
    predictions = read_csv(args.predictions)
    labels = read_csv(LABELS)
    if len(predictions) != 36 or len(labels) != 36:
        raise ValueError("Expected 36 predictions and 36 labels")
    pred = {r["calibration_record_id"]: r for r in predictions}
    human = {r["validation_record_id"]: r for r in labels}
    if len(pred) != 36 or len(human) != 36 or set(pred) != set(human):
        raise ValueError("Prediction and human identifier sets do not reconcile")

    matrix = {a: {p: 0 for p in CATEGORIES} for a in CATEGORIES}
    comparison = []
    for record_id in sorted(human):
        actual = human[record_id]["final_category"]
        predicted = pred[record_id]["decision"]
        if actual not in CATEGORIES or predicted not in CATEGORIES:
            raise ValueError(f"Invalid category for {record_id}")
        matrix[actual][predicted] += 1
        comparison.append({
            "validation_record_id": record_id,
            "corpus_id": human[record_id]["corpus_id"],
            "title": human[record_id]["title"],
            "screening_text": human[record_id]["screening_text"],
            "human_decision": actual,
            "human_reviewer_note": human[record_id]["reviewer_note"],
            "model_decision": predicted,
            "exact_agreement": str(actual == predicted),
            "model_reason_code": pred[record_id]["reason_code"],
            "model_confidence": pred[record_id]["confidence"],
            "model_needs_full_text": pred[record_id]["needs_full_text"],
            "model_rationale": pred[record_id]["rationale"],
            "final_adjudicated_category": "",
            "adjudication_note": "",
        })

    out = args.predictions.parent
    comparison_path = out / "positive_enriched_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader(); writer.writerows(comparison)
    matrix_path = out / "positive_enriched_confusion_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["human_decision"] + CATEGORIES)
        writer.writeheader()
        for actual in CATEGORIES:
            writer.writerow({"human_decision": actual, **matrix[actual]})

    core = [r for r in comparison if r["human_decision"] == "CORE_INCLUDE"]
    relevant = [r for r in comparison if r["human_decision"] in RELEVANT]
    nonrelevant = [r for r in comparison if r["human_decision"] not in RELEVANT]
    predicted_relevant = [r for r in comparison if r["model_decision"] in RELEVANT]
    predicted_nonrelevant = [r for r in comparison if r["model_decision"] not in RELEVANT]
    core_hits = sum(r["model_decision"] == "CORE_INCLUDE" for r in core)
    relevant_hits = sum(r["model_decision"] in RELEVANT for r in relevant)
    retained_hits = sum(r["model_decision"] != "EXCLUDE" for r in relevant)
    true_negatives = sum(r["model_decision"] not in RELEVANT for r in nonrelevant)
    true_positive_predictions = sum(r["human_decision"] in RELEVANT for r in predicted_relevant)
    true_negative_predictions = sum(r["human_decision"] not in RELEVANT for r in predicted_nonrelevant)
    silent = [r for r in relevant if r["model_decision"] == "EXCLUDE"]
    low_bad = [r for r in comparison if r["model_confidence"] == "LOW" and r["model_decision"] != "UNCERTAIN"]
    core_recall = ratio(core_hits, len(core))
    combined_recall = ratio(relevant_hits, len(relevant))
    counts_h = Counter(r["human_decision"] for r in comparison)
    counts_m = Counter(r["model_decision"] for r in comparison)
    disagreements = [r for r in comparison if r["exact_agreement"] != "True"]
    priority = [r for r in disagreements if r["human_decision"] in RELEVANT or (r["model_decision"] in RELEVANT and r["human_decision"] not in RELEVANT)]
    priority_path = out / "positive_enriched_priority_adjudication.csv"
    with priority_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader(); writer.writerows(priority)
    gate = (
        core_recall is not None and core_recall >= 0.95
        and combined_recall is not None and combined_recall >= 0.95
        and not silent and not low_bad
    )
    result = {
        "split": "POSITIVE_ENRICHED_VALIDATION",
        "expected_rows": 36,
        "evaluated_rows": len(comparison),
        "identifier_sets_reconcile": True,
        "human_category_counts": dict(sorted(counts_h.items())),
        "model_category_counts": dict(sorted(counts_m.items())),
        "metrics": {
            "exact_agreement": ratio(sum(r["exact_agreement"] == "True" for r in comparison), len(comparison)),
            "core_include_recall": core_recall,
            "core_include_recall_95pct_wilson": wilson(core_hits, len(core)),
            "combined_core_or_transferable_recall": combined_recall,
            "combined_recall_95pct_wilson": wilson(relevant_hits, len(relevant)),
            "recall_when_uncertain_is_retained_for_manual_review": ratio(retained_hits, len(relevant)),
            "human_core_or_transferable_silently_excluded": len(silent),
            "predicted_include_precision": ratio(true_positive_predictions, len(predicted_relevant)),
            "noninclude_specificity": ratio(true_negatives, len(nonrelevant)),
            "negative_predictive_value": ratio(true_negative_predictions, len(predicted_nonrelevant)),
            "model_uncertain_rate": ratio(counts_m["UNCERTAIN"], len(comparison)),
            "human_core_n": len(core),
            "human_core_or_transferable_n": len(relevant),
        },
        "acceptance_gate": {
            "complete_36": len(comparison) == 36,
            "core_recall_at_least_0_95": core_recall is not None and core_recall >= 0.95,
            "combined_recall_at_least_0_95": combined_recall is not None and combined_recall >= 0.95,
            "no_relevant_record_silently_excluded": not silent,
            "low_confidence_routes_to_uncertain": not low_bad,
            "positive_enriched_gate_passed": gate,
        },
        "confusion_matrix": matrix,
        "disagreement_rows": len(disagreements),
        "priority_adjudication_rows": len(priority),
        "priority_adjudication_file": priority_path.name,
        "human_label_caveat": "All 36 human reviewer-note fields were blank; evaluation uses the submitted categorical decisions without invented rationales.",
    }
    (out / "positive_enriched_evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
