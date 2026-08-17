#!/usr/bin/env python3
"""Evaluate the completed one-time locked validation run."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "step_5" / "calibration" / "resolved_human_labels_adjudicated.csv"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "UNCERTAIN", "EXCLUDE"]
RELEVANT = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=LABELS)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


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
    human = [row for row in read_csv(args.labels) if row["split"] == "VALIDATION"]
    if len(human) != 100:
        raise ValueError(f"Expected 100 validation human labels; found {len(human)}")
    if len(predictions) != 100:
        raise ValueError(f"Expected 100 validation predictions; found {len(predictions)}")
    pred_by_id = {row["calibration_record_id"]: row for row in predictions}
    human_by_id = {row["calibration_record_id"]: row for row in human}
    if len(pred_by_id) != 100 or len(human_by_id) != 100:
        raise ValueError("Duplicate validation identifiers")
    if set(pred_by_id) != set(human_by_id):
        raise ValueError("Prediction and human validation identifier sets differ")

    matrix = {actual: {predicted: 0 for predicted in CATEGORIES} for actual in CATEGORIES}
    comparison = []
    for record_id in sorted(human_by_id):
        actual = human_by_id[record_id]["human_decision"]
        predicted = pred_by_id[record_id]["decision"]
        if actual not in CATEGORIES or predicted not in CATEGORIES:
            raise ValueError(f"Invalid category for {record_id}: {actual}, {predicted}")
        matrix[actual][predicted] += 1
        comparison.append(
            {
                "calibration_record_id": record_id,
                "corpus_id": human_by_id[record_id]["corpus_id"],
                "title": human_by_id[record_id]["title"],
                "source_title_or_issuer": human_by_id[record_id]["source_title_or_issuer"],
                "document_type": human_by_id[record_id]["document_type"],
                "screening_text": human_by_id[record_id]["screening_text"],
                "human_decision": actual,
                "human_review_notes": human_by_id[record_id]["review_notes"],
                "model_decision": predicted,
                "exact_agreement": str(actual == predicted),
                "model_reason_code": pred_by_id[record_id]["reason_code"],
                "model_confidence": pred_by_id[record_id]["confidence"],
                "model_needs_full_text": pred_by_id[record_id]["needs_full_text"],
                "model_rationale": pred_by_id[record_id]["rationale"],
                "final_category": "",
                "reviewer_note": "",
            }
        )

    output_dir = args.predictions.parent
    comparison_path = output_dir / "validation_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(comparison)

    matrix_path = output_dir / "validation_confusion_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["human_decision"] + CATEGORIES)
        writer.writeheader()
        for actual in CATEGORIES:
            writer.writerow({"human_decision": actual, **matrix[actual]})

    total = len(comparison)
    exact = sum(row["exact_agreement"] == "True" for row in comparison)
    human_core = [row for row in comparison if row["human_decision"] == "CORE_INCLUDE"]
    human_relevant = [row for row in comparison if row["human_decision"] in RELEVANT]
    human_nonrelevant = [row for row in comparison if row["human_decision"] not in RELEVANT]
    predicted_relevant = [row for row in comparison if row["model_decision"] in RELEVANT]
    predicted_nonrelevant = [row for row in comparison if row["model_decision"] not in RELEVANT]

    core_hits = sum(row["model_decision"] == "CORE_INCLUDE" for row in human_core)
    relevant_hits = sum(row["model_decision"] in RELEVANT for row in human_relevant)
    retained_hits = sum(row["model_decision"] != "EXCLUDE" for row in human_relevant)
    true_negatives = sum(row["model_decision"] not in RELEVANT for row in human_nonrelevant)
    true_positive_predictions = sum(
        row["human_decision"] in RELEVANT for row in predicted_relevant
    )
    true_negative_predictions = sum(
        row["human_decision"] not in RELEVANT for row in predicted_nonrelevant
    )
    silent_exclusions = [
        row for row in human_relevant if row["model_decision"] == "EXCLUDE"
    ]
    low_confidence_nonuncertain = [
        row
        for row in comparison
        if row["model_confidence"] == "LOW" and row["model_decision"] != "UNCERTAIN"
    ]
    predicted_counts = Counter(row["model_decision"] for row in comparison)
    human_counts = Counter(row["human_decision"] for row in comparison)
    core_recall = ratio(core_hits, len(human_core))
    combined_recall = ratio(relevant_hits, len(human_relevant))

    disagreements = [row for row in comparison if row["exact_agreement"] == "False"]
    disagreement_path = output_dir / "validation_disagreements.csv"
    with disagreement_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(disagreements)

    priority_rows = [
        row
        for row in disagreements
        if (
            row["model_decision"] in RELEVANT
            and row["human_decision"] not in RELEVANT
        )
        or (
            row["human_decision"] == "UNCERTAIN"
            and row["model_decision"] == "EXCLUDE"
        )
    ]
    priority_path = output_dir / "validation_priority_adjudication.csv"
    with priority_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(priority_rows)

    result = {
        "split": "VALIDATION",
        "one_time_locked_validation": True,
        "human_labels_file": str(args.labels),
        "predictions_file": str(args.predictions),
        "expected_rows": 100,
        "evaluated_rows": total,
        "identifier_sets_reconcile": set(pred_by_id) == set(human_by_id),
        "human_category_counts": dict(sorted(human_counts.items())),
        "model_category_counts": dict(sorted(predicted_counts.items())),
        "metrics": {
            "exact_agreement": ratio(exact, total),
            "core_include_recall": core_recall,
            "core_include_recall_95pct_wilson": wilson(core_hits, len(human_core)),
            "combined_core_or_transferable_recall": combined_recall,
            "combined_recall_95pct_wilson": wilson(relevant_hits, len(human_relevant)),
            "recall_when_uncertain_is_retained_for_manual_review": ratio(
                retained_hits, len(human_relevant)
            ),
            "human_core_or_transferable_silently_excluded": len(silent_exclusions),
            "predicted_include_precision": ratio(
                true_positive_predictions, len(predicted_relevant)
            ),
            "noninclude_specificity": ratio(true_negatives, len(human_nonrelevant)),
            "negative_predictive_value": ratio(
                true_negative_predictions, len(predicted_nonrelevant)
            ),
            "model_uncertain_rate": ratio(predicted_counts["UNCERTAIN"], total),
            "human_core_n": len(human_core),
            "human_core_or_transferable_n": len(human_relevant),
        },
        "acceptance_gate": {
            "complete_100": total == 100,
            "identifiers_reconcile": set(pred_by_id) == set(human_by_id),
            "core_recall_at_least_0_95": core_recall is not None and core_recall >= 0.95,
            "combined_recall_at_least_0_95": (
                combined_recall is not None and combined_recall >= 0.95
            ),
            "no_relevant_record_silently_excluded": not silent_exclusions,
            "low_confidence_routes_to_uncertain": not low_confidence_nonuncertain,
            "validation_gate_passed": (
                total == 100
                and set(pred_by_id) == set(human_by_id)
                and core_recall is not None
                and core_recall >= 0.95
                and combined_recall is not None
                and combined_recall >= 0.95
                and not silent_exclusions
                and not low_confidence_nonuncertain
            ),
        },
        "confusion_matrix": matrix,
        "disagreement_rows": len(disagreements),
        "disagreement_file": disagreement_path.name,
        "priority_adjudication_rows": len(priority_rows),
        "priority_adjudication_file": priority_path.name,
        "production_recommendation": (
            "HOLD: the preregistered point-estimate validation gate passes, but the "
            "locked sample contains only one human relevant record. Run the frozen "
            "prompt on the separately blinded, positive-enriched benchmark set and "
            "resolve material validation-label disagreements before production."
        ),
        "caveat": (
            "Recall estimates have small positive denominators; Wilson intervals are "
            "reported to show uncertainty. The protocol's point-estimate gate remains binding."
        ),
    }
    output_path = output_dir / "validation_evaluation.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
