#!/usr/bin/env python3
"""Build the v5 classification audit without reusing obsolete v4 accuracy gates."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "step_5" / "calibration" / "positive_enriched_validation_model_input_v5.csv"
CATEGORIES = ["CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN", "EXCLUDE"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    predictions = read_csv(args.predictions)
    inputs = read_csv(INPUT)
    if len(predictions) != 36 or len(inputs) != 36:
        raise ValueError("Expected 36 predictions and 36 inputs")
    pred = {row["calibration_record_id"]: row for row in predictions}
    source = {row["calibration_record_id"]: row for row in inputs}
    if len(pred) != 36 or set(pred) != set(source):
        raise ValueError("Prediction and input identifier sets do not reconcile")

    final: list[dict[str, str]] = []
    for record_id in sorted(pred):
        model = pred[record_id]
        record = source[record_id]
        decision = model["decision"]
        if decision not in CATEGORIES:
            raise ValueError(f"Invalid v5 category for {record_id}: {decision}")
        expected_prefix = {"TRANSFERABLE_MECHANISM": "T", "CITATION_CHAIN_CANDIDATE": "C", "EXCLUDE": "X", "UNCERTAIN": "U"}.get(decision)
        if expected_prefix and not model["reason_code"].startswith(expected_prefix):
            raise ValueError(f"Invalid reason prefix for {record_id}")
        if decision == "CORE_INCLUDE" and model["reason_code"]:
            raise ValueError(f"CORE_INCLUDE must have null/blank reason for {record_id}")
        review_required = decision in {"TRANSFERABLE_MECHANISM", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN"}
        final.append({
            "validation_record_id": record_id,
            "corpus_id": record["corpus_id"],
            "title": record["title"],
            "doi": record["doi"],
            "url": record["url"],
            "final_category": decision,
            "core_include_trusted": str(decision == "CORE_INCLUDE"),
            "review_required": str(review_required),
            "reason_code": model["reason_code"],
            "confidence": model["confidence"],
            "needs_full_text": model["needs_full_text"],
            "rationale": model["rationale"],
            "organism_evidence": model["organism_evidence"],
            "stressor_evidence": model["stressor_evidence"],
            "response_evidence": model["response_evidence"],
            "transferability_basis": model["transferability_basis"],
            "citation_chain_basis": model["citation_chain_basis"],
            "access": model["access"],
            "access_type": model["access_type"],
            "access_url": model["access_url"],
        })

    out = args.predictions.parent
    final_path = out / "positive_enriched_v5_classifications.csv"
    write_csv(final_path, final)
    review = [row for row in final if row["review_required"] == "True"]
    write_csv(out / "positive_enriched_v5_review_queue.csv", review)
    lawful_retrieval = [
        row for row in final
        if row["access"] == "NO" and row["final_category"] in {"CORE_INCLUDE", "CITATION_CHAIN_CANDIDATE", "UNCERTAIN"}
    ]
    write_csv(out / "positive_enriched_v5_lawful_retrieval_queue.csv", lawful_retrieval)

    counts = Counter(row["final_category"] for row in final)
    access_counts = Counter(row["access"] for row in final)
    core = [row for row in final if row["final_category"] == "CORE_INCLUDE"]
    result = {
        "split": "POSITIVE_ENRICHED_VALIDATION_V5",
        "rows": len(final),
        "identifier_sets_reconcile": True,
        "classification_counts": {category: counts[category] for category in CATEGORIES},
        "access_counts": dict(sorted(access_counts.items())),
        "core_include_policy": {
            "trusted_without_additional_adjudication": True,
            "core_rows": len(core),
            "core_with_access_yes": sum(row["access"] == "YES" for row in core),
            "core_with_access_no": sum(row["access"] == "NO" for row in core),
        },
        "noncore_review": {
            "transferable_mechanism_rows": counts["TRANSFERABLE_MECHANISM"],
            "citation_chain_candidate_rows": counts["CITATION_CHAIN_CANDIDATE"],
            "uncertain_rows": counts["UNCERTAIN"],
            "review_queue_rows": len(review),
        },
        "lawful_retrieval_queue_rows": len(lawful_retrieval),
        "qa": {
            "complete_36": len(final) == 36,
            "one_category_per_record": len({row["validation_record_id"] for row in final}) == 36,
            "access_present_for_every_record": all(row["access"] in {"YES", "NO"} for row in final),
            "all_core_includes_trusted": all(row["review_required"] == "False" for row in core),
            "legacy_v4_accuracy_gate_applicable": False,
            "production_screening_approved": False,
        },
        "production_hold_reason": "Prompt v5 changes the taxonomy and transferability policy. The 12 non-core edge cases require review before the prompt is frozen for production; legacy v4 human labels are not a valid accuracy denominator for the new category system.",
        "access_caveat": "access=YES uses frozen public full-text discovery status. Direct publisher rechecking was blocked in this runtime. access=NO means no lawful public full text was confirmed, not that the source is irrelevant or unavailable through an institutional library.",
        "outputs": {
            "classifications": final_path.name,
            "review_queue": "positive_enriched_v5_review_queue.csv",
            "lawful_retrieval_queue": "positive_enriched_v5_lawful_retrieval_queue.csv",
        },
    }
    (out / "positive_enriched_v5_evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
