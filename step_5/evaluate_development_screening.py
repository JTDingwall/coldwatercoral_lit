#!/usr/bin/env python3
"""Evaluate DeepSeek development predictions against resolved human labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "step_5" / "calibration" / "resolved_human_labels.csv"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "UNCERTAIN", "EXCLUDE"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=LABELS)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> None:
    args = parse_args()
    predictions = read_csv(args.predictions)
    human = [row for row in read_csv(args.labels) if row["split"] == "DEVELOPMENT"]
    if len(human) != 300:
        raise ValueError(f"Expected 300 development human labels; found {len(human)}")
    pred_by_id = {row["calibration_record_id"]: row for row in predictions}
    human_by_id = {row["calibration_record_id"]: row for row in human}
    if len(pred_by_id) != len(predictions):
        raise ValueError("Duplicate prediction IDs")
    unexpected = set(pred_by_id) - set(human_by_id)
    if unexpected:
        raise ValueError(f"Predictions outside development split: {sorted(unexpected)}")

    evaluated_ids = sorted(set(pred_by_id) & set(human_by_id))
    matrix = {actual: {predicted: 0 for predicted in CATEGORIES} for actual in CATEGORIES}
    comparison_rows = []
    for record_id in evaluated_ids:
        actual = human_by_id[record_id]["human_decision"]
        predicted = pred_by_id[record_id]["decision"]
        if actual not in CATEGORIES or predicted not in CATEGORIES:
            raise ValueError(f"Invalid category for {record_id}")
        matrix[actual][predicted] += 1
        comparison_rows.append(
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
    comparison_path = output_dir / "development_comparison.csv"
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0].keys()))
        writer.writeheader()
        writer.writerows(comparison_rows)

    matrix_rows = []
    for actual in CATEGORIES:
        matrix_rows.append({"human_decision": actual, **matrix[actual]})
    matrix_path = output_dir / "development_confusion_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["human_decision"] + CATEGORIES)
        writer.writeheader()
        writer.writerows(matrix_rows)

    total = len(evaluated_ids)
    exact = sum(row["exact_agreement"] == "True" for row in comparison_rows)
    human_core = [row for row in comparison_rows if row["human_decision"] == "CORE_INCLUDE"]
    human_includes = [
        row for row in comparison_rows
        if row["human_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
    ]
    human_nonincludes = [
        row for row in comparison_rows
        if row["human_decision"] not in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
    ]
    core_recall = safe_ratio(
        sum(row["model_decision"] == "CORE_INCLUDE" for row in human_core),
        len(human_core),
    )
    combined_recall = safe_ratio(
        sum(
            row["model_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
            for row in human_includes
        ),
        len(human_includes),
    )
    specificity = safe_ratio(
        sum(
            row["model_decision"] not in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
            for row in human_nonincludes
        ),
        len(human_nonincludes),
    )
    retained_recall = safe_ratio(
        sum(row["model_decision"] != "EXCLUDE" for row in human_includes),
        len(human_includes),
    )
    predicted_includes = [
        row for row in comparison_rows
        if row["model_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
    ]
    include_precision = safe_ratio(
        sum(
            row["human_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
            for row in predicted_includes
        ),
        len(predicted_includes),
    )
    predicted_counts = Counter(row["model_decision"] for row in comparison_rows)
    human_counts = Counter(row["human_decision"] for row in comparison_rows)
    result = {
        "split": "DEVELOPMENT",
        "human_labels_file": str(args.labels),
        "locked_validation_evaluated": False,
        "benchmark_evaluated": False,
        "expected_rows": 300,
        "evaluated_rows": total,
        "missing_prediction_rows": 300 - total,
        "human_category_counts": dict(sorted(human_counts.items())),
        "model_category_counts": dict(sorted(predicted_counts.items())),
        "metrics": {
            "exact_agreement": safe_ratio(exact, total),
            "core_include_recall": core_recall,
            "combined_core_or_transferable_recall": combined_recall,
            "recall_when_uncertain_is_retained_for_manual_review": retained_recall,
            "human_core_or_transferable_silently_excluded": sum(
                row["model_decision"] == "EXCLUDE" for row in human_includes
            ),
            "predicted_include_precision": include_precision,
            "noninclude_specificity": specificity,
            "model_uncertain_rate": safe_ratio(predicted_counts["UNCERTAIN"], total),
            "human_core_n": len(human_core),
            "human_core_or_transferable_n": len(human_includes),
        },
        "development_prompt_gate": {
            "complete_300": total == 300,
            "core_recall_at_least_0_95": core_recall is not None and core_recall >= 0.95,
            "combined_recall_at_least_0_95": combined_recall is not None and combined_recall >= 0.95,
            "ready_to_freeze_prompt_and_run_locked_validation": (
                total == 300
                and core_recall is not None
                and core_recall >= 0.95
                and combined_recall is not None
                and combined_recall >= 0.95
            ),
        },
        "confusion_matrix": matrix,
        "caveat": f"Development performance is based on only {len(human_core)} human CORE_INCLUDE records and {len(human_includes) - len(human_core)} human TRANSFERABLE_MECHANISM records. Interpret rates with the small positive denominator and inspect residual disagreements before freezing the prompt.",
    }

    priority_rows = [
        row for row in comparison_rows
        if (
            row["human_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
            and row["model_decision"] != row["human_decision"]
        )
        or (
            row["model_decision"] in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
            and row["human_decision"] not in {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}
        )
        or (
            row["human_decision"] == "UNCERTAIN"
            and row["model_decision"] == "EXCLUDE"
        )
    ]
    priority_path = output_dir / "development_residual_disagreements.csv"
    with priority_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(priority_rows[0].keys()))
        writer.writeheader()
        writer.writerows(priority_rows)
    result["residual_disagreement_rows"] = len(priority_rows)
    result["residual_disagreement_file"] = priority_path.name
    output_path = output_dir / "development_evaluation.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
