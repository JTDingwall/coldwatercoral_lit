#!/usr/bin/env python3
"""Apply targeted reviewer adjudications to versioned Stage 5 human labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DIR = ROOT / "step_5" / "calibration"
VALID_CATEGORIES = {
    "CORE_INCLUDE",
    "TRANSFERABLE_MECHANISM",
    "EXCLUDE",
    "UNCERTAIN",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjudications", type=Path, required=True)
    parser.add_argument("--review-date", default="2026-08-17")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    adjudications, adjudication_fields = read_csv(args.adjudications)
    if len(adjudications) != 11:
        raise ValueError(f"Expected 11 adjudications; found {len(adjudications)}")
    required = {"calibration_record_id", "corpus_id", "final_category", "reviewer_note"}
    if not required.issubset(adjudication_fields):
        raise ValueError(f"Missing adjudication fields: {sorted(required - set(adjudication_fields))}")

    adjudication_by_id: dict[str, dict[str, str]] = {}
    for row in adjudications:
        record_id = row["calibration_record_id"].strip()
        category = row["final_category"].strip()
        if not record_id or record_id in adjudication_by_id:
            raise ValueError(f"Missing or duplicate calibration_record_id: {record_id!r}")
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid final_category for {record_id}: {category!r}")
        adjudication_by_id[record_id] = row

    original_path = CALIBRATION_DIR / "resolved_human_labels.csv"
    original, human_fields = read_csv(original_path)
    if len(original) != 400:
        raise ValueError(f"Expected 400 human labels; found {len(original)}")
    original_by_id = {row["calibration_record_id"]: row for row in original}
    if not set(adjudication_by_id).issubset(original_by_id):
        raise ValueError("Adjudication contains IDs outside the frozen calibration sample")
    if any(original_by_id[record_id]["split"] != "DEVELOPMENT" for record_id in adjudication_by_id):
        raise ValueError("A non-development label was included in development adjudication")

    updated = [dict(row) for row in original]
    updated_by_id = {row["calibration_record_id"]: row for row in updated}
    log_rows: list[dict[str, str]] = []
    changed = 0
    for record_id, adjudication in adjudication_by_id.items():
        row = updated_by_id[record_id]
        if row["corpus_id"] != adjudication["corpus_id"].strip():
            raise ValueError(f"corpus_id mismatch for {record_id}")
        old = row["human_decision"]
        new = adjudication["final_category"].strip()
        note = adjudication["reviewer_note"].strip()
        if old != new:
            changed += 1
        row["human_decision"] = new
        row["review_date"] = args.review_date
        row["review_notes"] = (
            f"Development disagreement adjudication: {note}"
            if note
            else "Development disagreement adjudication confirmed final category."
        )
        row["human_needs_full_text"] = "True" if new == "UNCERTAIN" else ""
        log_rows.append(
            {
                "calibration_record_id": record_id,
                "corpus_id": row["corpus_id"],
                "title": row["title"],
                "previous_human_decision": old,
                "model_decision": adjudication["model_decision"],
                "final_human_decision": new,
                "category_changed": str(old != new),
                "reviewer_note": note,
                "review_date": args.review_date,
                "source_file": args.adjudications.name,
            }
        )

    updated_path = CALIBRATION_DIR / "resolved_human_labels_adjudicated.csv"
    write_csv(updated_path, updated, human_fields)

    benchmarks, _ = read_csv(CALIBRATION_DIR / "resolved_benchmark_labels.csv")
    combined = updated + benchmarks
    combined_path = CALIBRATION_DIR / "resolved_calibration_labels_adjudicated.csv"
    write_csv(combined_path, combined, human_fields)

    log_fields = [
        "calibration_record_id",
        "corpus_id",
        "title",
        "previous_human_decision",
        "model_decision",
        "final_human_decision",
        "category_changed",
        "reviewer_note",
        "review_date",
        "source_file",
    ]
    log_path = CALIBRATION_DIR / "development_adjudication_log.csv"
    write_csv(log_path, log_rows, log_fields)

    split_counts = {
        split: dict(sorted(Counter(
            row["human_decision"] for row in combined if row["split"] == split
        ).items()))
        for split in ("DEVELOPMENT", "VALIDATION", "BENCHMARK_VALIDATION")
    }
    qa = {
        "input_adjudication_file": str(args.adjudications),
        "input_adjudication_sha256": sha256(args.adjudications),
        "adjudicated_rows": len(adjudications),
        "changed_category_rows": changed,
        "resolved_human_rows": len(updated),
        "resolved_combined_rows": len(combined),
        "split_category_counts": split_counts,
        "all_category_counts": dict(sorted(Counter(
            row["human_decision"] for row in combined
        ).items())),
        "checks": {
            "all_11_adjudications_applied": len(log_rows) == 11,
            "all_400_human_labels_preserved": len(updated) == 400,
            "all_409_combined_labels_present": len(combined) == 409,
            "validation_labels_unchanged": all(
                updated_by_id[row["calibration_record_id"]]["human_decision"] == row["human_decision"]
                for row in original if row["split"] == "VALIDATION"
            ),
            "benchmark_labels_unchanged": len(benchmarks) == 9,
        },
    }
    qa_path = CALIBRATION_DIR / "development_adjudication_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
