#!/usr/bin/env python3
"""Create a strictly label-free model input for benchmark validation."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "step_5" / "calibration" / "benchmark_validation_blinded_adjudicated.csv"
OUTPUT = ROOT / "step_5" / "calibration" / "benchmark_model_input_adjudicated.csv"

MODEL_FIELDS = [
    "calibration_record_id",
    "split",
    "corpus_id",
    "title",
    "authors",
    "year",
    "source_title_or_issuer",
    "document_type",
    "doi",
    "url",
    "language",
    "screening_text",
    "text_truncated",
    "full_text_status",
    "discovery_systems",
    "query_ids",
    "families",
    "primary_family",
    "system_stratum",
    "signal_tier",
    "metadata_stratum",
]
LABEL_FIELDS = {
    "expected_screening",
    "expected_category",
    "benchmark_type",
    "human_decision",
    "human_reason_code",
    "human_rationale",
    "human_screening_source",
    "human_confidence",
    "human_needs_full_text",
    "reviewer",
    "review_date",
    "review_notes",
    "final_category",
}


def main() -> None:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 9:
        raise ValueError(f"Expected nine benchmark rows; found {len(rows)}")
    if len({row["calibration_record_id"] for row in rows}) != 9:
        raise ValueError("Benchmark calibration IDs are not unique")
    if len({row["corpus_id"] for row in rows}) != 9:
        raise ValueError("Benchmark corpus IDs are not unique")
    if any(row["split"] != "BENCHMARK_VALIDATION" for row in rows):
        raise ValueError("Unexpected split in benchmark source")
    for field in LABEL_FIELDS & set(rows[0]):
        if any((row.get(field) or "").strip() for row in rows):
            raise ValueError(f"Blinded source contains a populated label field: {field}")

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MODEL_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MODEL_FIELDS})
    print(OUTPUT)


if __name__ == "__main__":
    main()
