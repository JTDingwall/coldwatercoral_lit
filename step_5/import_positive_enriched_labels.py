#!/usr/bin/env python3
"""Import and QA the user's 36-record positive-enriched labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CAL = STEP5 / "calibration"
SOURCE = CAL / "positive_enriched_validation_review.csv"
PROMPT = STEP5 / "prompts" / "title_abstract_screening_v4.md"
FROZEN_COMMIT = "9fcb4f3834cbb15c43ac8a1f23dab6142e68185d"
FROZEN_CORPUS_PATH = "step_4/corpus/candidate_corpus.csv"
VALID = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "UNCERTAIN", "EXCLUDE"}
NORMALIZE = {"TRANSFERRABLE_MECHANISM": "TRANSFERABLE_MECHANISM"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completed", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_corpus() -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["git", "show", f"{FROZEN_COMMIT}:{FROZEN_CORPUS_PATH}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {row["corpus_id"]: row for row in csv.DictReader(result.stdout.splitlines())}


def main() -> None:
    args = parse_args()
    source = read_csv(SOURCE)
    completed = read_csv(args.completed)
    if len(source) != 36 or len(completed) != 36:
        raise ValueError("Expected 36 source and 36 completed rows")
    source_by_id = {row["validation_record_id"]: row for row in source}
    completed_by_id = {row["validation_record_id"]: row for row in completed}
    if len(source_by_id) != 36 or len(completed_by_id) != 36:
        raise ValueError("Validation record IDs are not unique")
    if set(source_by_id) != set(completed_by_id):
        raise ValueError("Completed and source ID sets differ")
    metadata_fields = [
        "corpus_id", "title", "authors", "year", "source_title_or_issuer",
        "document_type", "doi", "url", "language", "screening_text",
        "full_text_status",
    ]
    mismatches = []
    labels = []
    normalizations = []
    for record_id in sorted(source_by_id):
        original = source_by_id[record_id]
        returned = completed_by_id[record_id]
        for field in metadata_fields:
            if original[field] != returned[field]:
                mismatches.append({"validation_record_id": record_id, "field": field})
        raw = returned["final_category"].strip()
        category = NORMALIZE.get(raw, raw)
        if raw != category:
            normalizations.append({
                "validation_record_id": record_id,
                "submitted_category": raw,
                "normalized_category": category,
                "reason": "Mechanical correction to frozen controlled vocabulary",
            })
        if category not in VALID:
            raise ValueError(f"Invalid category for {record_id}: {raw!r}")
        row = dict(original)
        row["final_category"] = category
        row["reviewer_note"] = returned["reviewer_note"].strip()
        labels.append(row)
    if mismatches:
        raise ValueError(f"Returned metadata differs from source: {mismatches[:10]}")

    labels_path = CAL / "positive_enriched_validation_labels.csv"
    write_csv(labels_path, labels, list(labels[0]))
    norm_path = CAL / "positive_enriched_validation_label_normalizations.csv"
    norm_fields = ["validation_record_id", "submitted_category", "normalized_category", "reason"]
    write_csv(norm_path, normalizations, norm_fields)

    corpus = frozen_corpus()
    model_rows = []
    for row in labels:
        frozen = corpus[row["corpus_id"]]
        model_rows.append({
            "calibration_record_id": row["validation_record_id"],
            "split": "POSITIVE_ENRICHED_VALIDATION",
            "corpus_id": row["corpus_id"],
            "title": row["title"],
            "authors": row["authors"],
            "year": row["year"],
            "source_title_or_issuer": row["source_title_or_issuer"],
            "document_type": row["document_type"],
            "doi": row["doi"],
            "url": row["url"],
            "language": row["language"],
            "screening_text": row["screening_text"],
            "full_text_status": row["full_text_status"],
            "discovery_systems": frozen["discovery_systems"],
            "query_ids": frozen["query_ids"],
            "families": frozen["families"],
        })
    model_path = CAL / "positive_enriched_validation_model_input.csv"
    write_csv(model_path, model_rows, list(model_rows[0]))

    counts = Counter(row["final_category"] for row in labels)
    relevant_n = counts["CORE_INCLUDE"] + counts["TRANSFERABLE_MECHANISM"]
    qa = {
        "status": "PASS_WITH_MISSING_REVIEWER_NOTES" if any(not row["reviewer_note"] for row in labels) else "PASS",
        "import_date": str(date.today()),
        "rows": len(labels),
        "unique_validation_ids": len({row["validation_record_id"] for row in labels}),
        "unique_corpus_ids": len({row["corpus_id"] for row in labels}),
        "metadata_mismatches": len(mismatches),
        "normalized_category_rows": len(normalizations),
        "blank_reviewer_notes": sum(not row["reviewer_note"] for row in labels),
        "category_counts": dict(sorted(counts.items())),
        "human_relevant_n": relevant_n,
        "model_input_has_human_label_columns": False,
        "labels_file": str(labels_path.relative_to(ROOT)),
        "labels_sha256": sha(labels_path),
        "model_input_file": str(model_path.relative_to(ROOT)),
        "model_input_sha256": sha(model_path),
        "prompt_v4_file": str(PROMPT.relative_to(ROOT)),
        "prompt_v4_sha256": sha(PROMPT),
    }
    qa_path = CAL / "positive_enriched_validation_human_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    freeze = {
        "status": "FROZEN_AWAITING_API_AUTHORIZATION",
        "freeze_date": str(date.today()),
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha(PROMPT),
        "human_labels_file": str(labels_path.relative_to(ROOT)),
        "human_labels_sha256": sha(labels_path),
        "model_input_file": str(model_path.relative_to(ROOT)),
        "model_input_sha256": sha(model_path),
        "rows": 36,
        "human_relevant_n": relevant_n,
        "external_transfer_authorized": False,
        "model_run_status": "NOT_RUN",
    }
    (CAL / "positive_enriched_prompt_v4_freeze.json").write_text(
        json.dumps(freeze, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
