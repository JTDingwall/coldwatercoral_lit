#!/usr/bin/env python3
"""Evaluate sealed benchmark predictions against the adjudicated answer key."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "step_5" / "calibration" / "benchmark_key_adjudicated.csv"
INPUT = ROOT / "step_5" / "calibration" / "benchmark_model_input_adjudicated.csv"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "UNCERTAIN", "EXCLUDE"]
RELEVANT = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> None:
    args = parse_args()
    predictions = read_csv(args.predictions)
    key = read_csv(KEY)
    inputs = read_csv(INPUT)
    if not (len(predictions) == len(key) == 9):
        raise ValueError("Expected exactly nine predictions and nine key rows")
    pred_by_id = {row["calibration_record_id"]: row for row in predictions}
    key_by_id = {row["calibration_record_id"]: row for row in key}
    input_by_id = {row["calibration_record_id"]: row for row in inputs}
    if not (len(pred_by_id) == len(key_by_id) == len(input_by_id) == 9):
        raise ValueError("Duplicate benchmark identifiers")
    if not (set(pred_by_id) == set(key_by_id) == set(input_by_id)):
        raise ValueError("Prediction, key, and input identifier sets differ")

    matrix = {actual: {pred: 0 for pred in CATEGORIES} for actual in CATEGORIES}
    rows = []
    for record_id in sorted(key_by_id):
        expected = key_by_id[record_id]["expected_screening"]
        predicted = pred_by_id[record_id]["decision"]
        if expected not in CATEGORIES or predicted not in CATEGORIES:
            raise ValueError(f"Invalid category for {record_id}")
        matrix[expected][predicted] += 1
        rows.append(
            {
                "calibration_record_id": record_id,
                "benchmark_id": key_by_id[record_id]["benchmark_id"],
                "corpus_id": key_by_id[record_id]["corpus_id"],
                "title": input_by_id[record_id]["title"],
                "expected_screening": expected,
                "model_decision": predicted,
                "exact_agreement": str(expected == predicted),
                "model_reason_code": pred_by_id[record_id]["reason_code"],
                "model_confidence": pred_by_id[record_id]["confidence"],
                "model_needs_full_text": pred_by_id[record_id]["needs_full_text"],
                "model_rationale": pred_by_id[record_id]["rationale"],
                "final_category": "",
                "reviewer_note": "",
            }
        )

    out_dir = args.predictions.parent
    comparison_path = out_dir / "benchmark_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    matrix_path = out_dir / "benchmark_confusion_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["expected_screening"] + CATEGORIES)
        writer.writeheader()
        for expected in CATEGORIES:
            writer.writerow({"expected_screening": expected, **matrix[expected]})

    disagreements = [row for row in rows if row["exact_agreement"] != "True"]
    disagreement_path = out_dir / "benchmark_priority_adjudication.csv"
    with disagreement_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(disagreements)

    core = [row for row in rows if row["expected_screening"] == "CORE_INCLUDE"]
    relevant = [row for row in rows if row["expected_screening"] in RELEVANT]
    negatives = [row for row in rows if row["expected_screening"] == "EXCLUDE"]
    exact = sum(row["exact_agreement"] == "True" for row in rows)
    core_hits = sum(row["model_decision"] == "CORE_INCLUDE" for row in core)
    relevant_hits = sum(row["model_decision"] in RELEVANT for row in relevant)
    retained_hits = sum(row["model_decision"] != "EXCLUDE" for row in relevant)
    negative_hits = sum(row["model_decision"] == "EXCLUDE" for row in negatives)
    silent = [row for row in relevant if row["model_decision"] == "EXCLUDE"]
    low_bad = [
        row
        for row in rows
        if row["model_confidence"] == "LOW" and row["model_decision"] != "UNCERTAIN"
    ]
    predicted_counts = Counter(row["model_decision"] for row in rows)
    expected_counts = Counter(row["expected_screening"] for row in rows)
    core_recall = ratio(core_hits, len(core))
    combined_recall = ratio(relevant_hits, len(relevant))
    negative_specificity = ratio(negative_hits, len(negatives))
    gate = (
        len(rows) == 9
        and core_recall is not None
        and core_recall >= 0.95
        and combined_recall is not None
        and combined_recall >= 0.95
        and negative_specificity == 1.0
        and not silent
        and not low_bad
    )
    result = {
        "split": "BENCHMARK_VALIDATION",
        "one_time_benchmark_validation": True,
        "expected_rows": 9,
        "evaluated_rows": len(rows),
        "identifier_sets_reconcile": True,
        "expected_category_counts": dict(sorted(expected_counts.items())),
        "model_category_counts": dict(sorted(predicted_counts.items())),
        "metrics": {
            "exact_agreement": ratio(exact, len(rows)),
            "core_include_recall": core_recall,
            "combined_core_or_transferable_recall": combined_recall,
            "recall_when_uncertain_is_retained_for_manual_review": ratio(
                retained_hits, len(relevant)
            ),
            "relevant_benchmarks_silently_excluded": len(silent),
            "negative_control_specificity": negative_specificity,
            "core_n": len(core),
            "core_or_transferable_n": len(relevant),
            "negative_control_n": len(negatives),
        },
        "acceptance_gate": {
            "complete_9": len(rows) == 9,
            "identifiers_reconcile": True,
            "core_recall_at_least_0_95": core_recall is not None and core_recall >= 0.95,
            "combined_recall_at_least_0_95": (
                combined_recall is not None and combined_recall >= 0.95
            ),
            "all_negative_controls_excluded": negative_specificity == 1.0,
            "no_relevant_benchmark_silently_excluded": not silent,
            "low_confidence_routes_to_uncertain": not low_bad,
            "benchmark_gate_passed": gate,
        },
        "confusion_matrix": matrix,
        "disagreement_rows": len(disagreements),
        "disagreement_file": disagreement_path.name,
        "production_recommendation": (
            "BLOCK: the frozen prompt silently excluded one expected transferable "
            "benchmark and failed the combined-recall and negative-control gates. "
            "Adjudicate the three benchmark conflicts, then design a new independent "
            "positive-enriched validation set before changing or approving the workflow."
        ),
    }
    (out_dir / "benchmark_evaluation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
