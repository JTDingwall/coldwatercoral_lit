#!/usr/bin/env python3
"""Merge Covidence decisions and reviewer adjudications into Stage 5 labels.

This script never performs relevance screening. It applies the reviewer's
recorded decisions to the deterministic 400-record calibration sample and the
9-record blinded benchmark set, while preserving an audit trail for manual
adjudications and Covidence title-deduplication losses.
"""

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

# Covidence collapsed these pairs on exact/generic title during import. Both
# absent records were manually checked and are irrelevant.
DEDUPED_DECISIONS = {
    "CWC-39AEBCB813DD": (
        "EXCLUDE",
        "Covidence exact-title duplicate of CWC-BEA6991859F6; inherited NO/EXCLUDE.",
    ),
    "CWC-D3A8DA7C158A": (
        "EXCLUDE",
        "Covidence generic-title collision ('Dispatches') with CWC-86111C71AF4B; "
        "both records are irrelevant.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--covidence", type=Path, required=True)
    parser.add_argument("--followup-json", type=Path, required=True)
    parser.add_argument("--reviewer", default="Jake")
    parser.add_argument("--review-date", default="2026-08-17")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    sample_path = CALIBRATION_DIR / "calibration_sample.csv"
    benchmark_path = CALIBRATION_DIR / "benchmark_validation_blinded.csv"
    key_path = CALIBRATION_DIR / "benchmark_key.csv"
    template_path = CALIBRATION_DIR / "human_labels.csv"

    sample = read_csv(sample_path)
    benchmarks = read_csv(benchmark_path)
    benchmark_key = read_csv(key_path)
    template = read_csv(template_path)
    covidence = read_csv(args.covidence)
    followup = json.loads(args.followup_json.read_text(encoding="utf-8"))

    if len(sample) != 400 or len(benchmarks) != 9:
        raise ValueError("Expected authoritative 400-record sample and 9 benchmarks")
    if len(covidence) != 407:
        raise ValueError(f"Expected 407 Covidence decisions; found {len(covidence)}")

    all_records = sample + benchmarks
    record_by_corpus = {row["corpus_id"]: row for row in all_records}
    if len(record_by_corpus) != 409:
        raise ValueError("Calibration and benchmark corpus IDs are not unique")

    covidence_by_corpus: dict[str, dict[str, str]] = {}
    for row in covidence:
        corpus_id = row["Accession Number"].strip()
        if not corpus_id or corpus_id in covidence_by_corpus:
            raise ValueError(f"Missing or duplicate Covidence accession: {corpus_id!r}")
        if corpus_id not in record_by_corpus:
            raise ValueError(f"Covidence accession is outside frozen calibration: {corpus_id}")
        covidence_by_corpus[corpus_id] = row

    missing = set(record_by_corpus) - set(covidence_by_corpus)
    if missing != set(DEDUPED_DECISIONS):
        raise ValueError(f"Unexpected records absent from Covidence: {sorted(missing)}")

    followup_by_corpus = {row["corpus_id"]: row for row in followup}
    if len(followup_by_corpus) != 15:
        raise ValueError("Expected 15 unique follow-up records")
    for corpus_id, row in followup_by_corpus.items():
        category = str(row["final_category"]).strip()
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid or blank final category for {corpus_id}: {category}")
    if followup_by_corpus["CWC-6ABFA4BF4E10"]["final_category"] != "UNCERTAIN":
        raise ValueError("FU-06 correction to UNCERTAIN is missing")

    decisions: dict[str, str] = {}
    notes: dict[str, str] = {}
    adjudication_log: list[dict[str, str]] = []

    for corpus_id, row in covidence_by_corpus.items():
        source_decision = row["Decision"].strip().upper()
        if corpus_id in followup_by_corpus:
            followup_row = followup_by_corpus[corpus_id]
            final = str(followup_row["final_category"]).strip()
            note = str(followup_row.get("reviewer_note", "")).strip()
            basis = "REVIEWER_FOLLOWUP"
            adjudication_log.append(
                {
                    "event_id": str(followup_row["followup_id"]),
                    "calibration_record_id": record_by_corpus[corpus_id]["calibration_record_id"],
                    "corpus_id": corpus_id,
                    "source_decision": source_decision,
                    "final_category": final,
                    "resolution_basis": basis,
                    "detail": note or str(followup_row.get("followup_reason", "")),
                }
            )
        elif source_decision == "NO":
            final = "EXCLUDE"
            note = "Covidence NO mapped to EXCLUDE."
        elif source_decision == "MAYBE":
            final = "UNCERTAIN"
            note = "Covidence MAYBE mapped to UNCERTAIN."
        elif source_decision == "YES":
            raise ValueError(f"YES record lacks required four-way adjudication: {corpus_id}")
        else:
            raise ValueError(f"Unrecognized Covidence decision for {corpus_id}: {source_decision}")
        decisions[corpus_id] = final
        notes[corpus_id] = note

    for index, (corpus_id, (final, detail)) in enumerate(DEDUPED_DECISIONS.items(), start=1):
        decisions[corpus_id] = final
        notes[corpus_id] = detail
        adjudication_log.append(
            {
                "event_id": f"DEDUP-{index:02d}",
                "calibration_record_id": record_by_corpus[corpus_id]["calibration_record_id"],
                "corpus_id": corpus_id,
                "source_decision": "ABSENT_AFTER_COVIDENCE_DEDUPLICATION",
                "final_category": final,
                "resolution_basis": "MANUAL_DUPLICATE_RECONCILIATION",
                "detail": detail,
            }
        )

    if len(decisions) != 409 or set(decisions) != set(record_by_corpus):
        raise ValueError("Not all 409 frozen records received a final category")

    human_fields = list(template[0].keys())

    def resolved_row(row: dict[str, str]) -> dict[str, str]:
        corpus_id = row["corpus_id"]
        decision = decisions[corpus_id]
        output = dict(row)
        output.update(
            {
                "human_decision": decision,
                "human_screening_source": "Covidence calibration plus reviewer adjudication",
                "reviewer": args.reviewer,
                "review_date": args.review_date,
                "review_notes": notes[corpus_id],
            }
        )
        if decision == "UNCERTAIN":
            output["human_needs_full_text"] = "True"
        return output

    resolved_sample = [resolved_row(row) for row in sample]
    resolved_benchmarks = [resolved_row(row) for row in benchmarks]
    resolved_all = resolved_sample + resolved_benchmarks

    write_csv(CALIBRATION_DIR / "resolved_human_labels.csv", resolved_sample, human_fields)
    write_csv(
        CALIBRATION_DIR / "resolved_benchmark_labels.csv",
        resolved_benchmarks,
        human_fields,
    )
    write_csv(
        CALIBRATION_DIR / "resolved_calibration_labels.csv",
        resolved_all,
        human_fields,
    )
    log_fields = [
        "event_id",
        "calibration_record_id",
        "corpus_id",
        "source_decision",
        "final_category",
        "resolution_basis",
        "detail",
    ]
    write_csv(
        CALIBRATION_DIR / "calibration_adjudication_log.csv",
        adjudication_log,
        log_fields,
    )

    key_by_corpus = {row["corpus_id"]: row for row in benchmark_key}
    benchmark_comparison = []
    for row in resolved_benchmarks:
        key = key_by_corpus[row["corpus_id"]]
        benchmark_comparison.append(
            {
                "calibration_record_id": row["calibration_record_id"],
                "corpus_id": row["corpus_id"],
                "benchmark_id": key["benchmark_id"],
                "expected_screening": key["expected_screening"],
                "human_decision": row["human_decision"],
                "exact_agreement": str(
                    key["expected_screening"] == row["human_decision"]
                ),
                "status": (
                    "AGREES"
                    if key["expected_screening"] == row["human_decision"]
                    else "PROTOCOL_OR_BENCHMARK_REVIEW_REQUIRED"
                ),
            }
        )
    write_csv(
        CALIBRATION_DIR / "benchmark_human_comparison.csv",
        benchmark_comparison,
        [
            "calibration_record_id",
            "corpus_id",
            "benchmark_id",
            "expected_screening",
            "human_decision",
            "exact_agreement",
            "status",
        ],
    )

    split_counts = {
        split: dict(sorted(Counter(
            row["human_decision"] for row in resolved_all if row["split"] == split
        ).items()))
        for split in ("DEVELOPMENT", "VALIDATION", "BENCHMARK_VALIDATION")
    }
    all_counts = dict(sorted(Counter(decisions.values()).items()))
    disagreements = [row for row in benchmark_comparison if row["exact_agreement"] == "False"]
    qa = {
        "inputs": {
            "covidence_rows": len(covidence),
            "covidence_sha256": file_sha256(args.covidence),
            "followup_rows": len(followup),
            "followup_sha256": file_sha256(args.followup_json),
            "frozen_calibration_rows": len(sample),
            "frozen_benchmark_rows": len(benchmarks),
        },
        "resolved": {
            "total_rows": len(resolved_all),
            "all_category_counts": all_counts,
            "split_category_counts": split_counts,
            "covidence_deduplicated_rows_resolved": len(DEDUPED_DECISIONS),
            "manual_followup_rows": len(followup),
        },
        "benchmark_comparison": {
            "exact_agreement_count": len(benchmark_comparison) - len(disagreements),
            "disagreement_count": len(disagreements),
            "disagreements": disagreements,
        },
        "checks": {
            "all_409_records_resolved": len(resolved_all) == 409,
            "all_categories_valid": all(
                row["human_decision"] in VALID_CATEGORIES for row in resolved_all
            ),
            "fu06_is_uncertain": decisions["CWC-6ABFA4BF4E10"] == "UNCERTAIN",
            "validation_rows_not_used_for_development": sum(
                row["split"] == "DEVELOPMENT" for row in resolved_sample
            ) == 300,
            "benchmark_key_not_merged_into_model_inputs": True,
        },
    }
    qa_path = CALIBRATION_DIR / "calibration_human_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "resolved_rows": len(resolved_all),
        "category_counts": all_counts,
        "split_category_counts": split_counts,
        "benchmark_disagreements": disagreements,
        "qa": str(qa_path),
    }, indent=2))


if __name__ == "__main__":
    main()
