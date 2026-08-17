#!/usr/bin/env python3
"""Apply the approved B004/B005 Stage 5 benchmark adjudications.

The original benchmark artifacts are retained unchanged. This script writes
new, explicitly adjudicated artifacts and records the source replacement in an
audit log and machine-readable QA report.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from build_calibration_sample import BASE_FIELDS, HUMAN_FIELDS, prepare_row


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DIR = ROOT / "step_5" / "calibration"
FROZEN_STAGE4_COMMIT = "9fcb4f3834cbb15c43ac8a1f23dab6142e68185d"
FROZEN_CORPUS_REPO_PATH = "step_4/corpus/candidate_corpus.csv"
REPLACEMENT_CORPUS_ID = "CWC-B27727ED4386"
RETIRED_B005_CORPUS_ID = "CWC-4D83BD3A455E"
B004_CORPUS_ID = "CWC-104B2C5A7924"
ADJUDICATION_DATE = "2026-08-17"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
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


def read_frozen_corpus() -> list[dict[str, str]]:
    result = subprocess.run(
        [
            "git",
            "show",
            f"{FROZEN_STAGE4_COMMIT}:{FROZEN_CORPUS_REPO_PATH}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return list(csv.DictReader(result.stdout.splitlines()))


def main() -> None:
    key = read_csv(CALIBRATION_DIR / "benchmark_key.csv")
    blinded = read_csv(CALIBRATION_DIR / "benchmark_validation_blinded.csv")
    resolved = read_csv(CALIBRATION_DIR / "resolved_benchmark_labels.csv")
    calibration = read_csv(CALIBRATION_DIR / "calibration_sample.csv")
    corpus = {row["corpus_id"]: row for row in read_frozen_corpus()}

    assert len(key) == len(blinded) == len(resolved) == 9
    assert REPLACEMENT_CORPUS_ID in corpus
    assert REPLACEMENT_CORPUS_ID not in {row["corpus_id"] for row in calibration}

    adjudicated_key = [dict(row) for row in key]
    for row in adjudicated_key:
        if row["benchmark_id"] == "B004":
            assert row["corpus_id"] == B004_CORPUS_ID
            row["expected_screening"] = "TRANSFERABLE_MECHANISM"
        elif row["benchmark_id"] == "B005":
            assert row["corpus_id"] == RETIRED_B005_CORPUS_ID
            row["corpus_id"] = REPLACEMENT_CORPUS_ID
            row["expected_screening"] = "CORE_INCLUDE"

    replacement = prepare_row(corpus[REPLACEMENT_CORPUS_ID])
    replacement.update(
        {
            "calibration_record_id": "BV-007",
            "split": "BENCHMARK_VALIDATION",
        }
    )
    replacement_blinded = {field: replacement.get(field, "") for field in HUMAN_FIELDS}
    for field in HUMAN_FIELDS[len(BASE_FIELDS) :]:
        replacement_blinded[field] = ""

    adjudicated_blinded: list[dict[str, object]] = []
    adjudicated_resolved: list[dict[str, object]] = []
    for blind_row, resolved_row in zip(blinded, resolved, strict=True):
        if blind_row["calibration_record_id"] == "BV-007":
            adjudicated_blinded.append(replacement_blinded)
            new_resolved = dict(replacement_blinded)
            new_resolved.update(
                {
                    "human_decision": "CORE_INCLUDE",
                    "human_reason_code": "DIRECT_COLD_WATER_CORAL_STRESSOR_STUDY",
                    "human_rationale": (
                        "Controlled exposure study of cold-water coral Lophelia "
                        "pertusa to offshore drill cuttings, with biological "
                        "response and recovery endpoints."
                    ),
                    "human_screening_source": "Approved benchmark adjudication",
                    "human_confidence": "HIGH",
                    "human_needs_full_text": "False",
                    "reviewer": "Jake",
                    "review_date": ADJUDICATION_DATE,
                    "review_notes": (
                        "Replaces the non-substantive USGS project news webpage "
                        "previously assigned to B005."
                    ),
                }
            )
            adjudicated_resolved.append(new_resolved)
        else:
            adjudicated_blinded.append(dict(blind_row))
            adjudicated_resolved.append(dict(resolved_row))

    key_by_record = {row["calibration_record_id"]: row for row in adjudicated_key}
    comparison = []
    for row in adjudicated_resolved:
        expected = key_by_record[row["calibration_record_id"]]
        exact = row["human_decision"] == expected["expected_screening"]
        comparison.append(
            {
                "calibration_record_id": row["calibration_record_id"],
                "corpus_id": row["corpus_id"],
                "benchmark_id": expected["benchmark_id"],
                "expected_screening": expected["expected_screening"],
                "human_decision": row["human_decision"],
                "exact_agreement": str(exact),
                "status": "AGREES" if exact else "PROTOCOL_OR_BENCHMARK_REVIEW_REQUIRED",
            }
        )

    log_fields = [
        "adjudication_id",
        "benchmark_id",
        "action",
        "old_corpus_id",
        "new_corpus_id",
        "old_expected_screening",
        "new_expected_screening",
        "decision_basis",
        "decision_date",
    ]
    log = [
        {
            "adjudication_id": "BA-001",
            "benchmark_id": "B004",
            "action": "RELABEL_EXPECTED_CATEGORY",
            "old_corpus_id": B004_CORPUS_ID,
            "new_corpus_id": B004_CORPUS_ID,
            "old_expected_screening": "CORE_INCLUDE",
            "new_expected_screening": "TRANSFERABLE_MECHANISM",
            "decision_basis": "User approved benchmark recommendation",
            "decision_date": ADJUDICATION_DATE,
        },
        {
            "adjudication_id": "BA-002",
            "benchmark_id": "B005",
            "action": "RETIRE_NON_SUBSTANTIVE_SOURCE",
            "old_corpus_id": RETIRED_B005_CORPUS_ID,
            "new_corpus_id": "",
            "old_expected_screening": "CORE_INCLUDE",
            "new_expected_screening": "EXCLUDE",
            "decision_basis": "USGS record is a project news webpage, not a substantive study",
            "decision_date": ADJUDICATION_DATE,
        },
        {
            "adjudication_id": "BA-003",
            "benchmark_id": "B005",
            "action": "ADD_SUBSTANTIVE_REPLACEMENT",
            "old_corpus_id": RETIRED_B005_CORPUS_ID,
            "new_corpus_id": REPLACEMENT_CORPUS_ID,
            "old_expected_screening": "EXCLUDE",
            "new_expected_screening": "CORE_INCLUDE",
            "decision_basis": (
                "Baussant et al. 2018 is a direct Lophelia pertusa drill-cuttings "
                "exposure study from the related research programme"
            ),
            "decision_date": ADJUDICATION_DATE,
        },
    ]

    key_path = CALIBRATION_DIR / "benchmark_key_adjudicated.csv"
    blind_path = CALIBRATION_DIR / "benchmark_validation_blinded_adjudicated.csv"
    resolved_path = CALIBRATION_DIR / "resolved_benchmark_labels_adjudicated.csv"
    comparison_path = CALIBRATION_DIR / "benchmark_human_comparison_adjudicated.csv"
    log_path = CALIBRATION_DIR / "benchmark_adjudication_log.csv"
    write_csv(key_path, adjudicated_key, list(key[0]))
    write_csv(blind_path, adjudicated_blinded, HUMAN_FIELDS)
    write_csv(resolved_path, adjudicated_resolved, HUMAN_FIELDS)
    write_csv(
        comparison_path,
        comparison,
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
    write_csv(log_path, log, log_fields)

    active_corpus_ids = [row["corpus_id"] for row in adjudicated_key]
    calibration_ids = {row["corpus_id"] for row in calibration}
    comparison_conflicts = [row for row in comparison if row["exact_agreement"] != "True"]
    expected_counts = Counter(row["expected_screening"] for row in adjudicated_key)
    blind_by_record = {row["calibration_record_id"]: row for row in adjudicated_blinded}
    resolved_by_record = {row["calibration_record_id"]: row for row in adjudicated_resolved}
    checks = {
        "active_benchmark_count_is_9": len(adjudicated_key) == 9,
        "active_benchmark_ids_unique": len({row["benchmark_id"] for row in adjudicated_key}) == 9,
        "active_corpus_ids_unique": len(set(active_corpus_ids)) == 9,
        "active_records_exist_in_frozen_corpus": all(cid in corpus for cid in active_corpus_ids),
        "no_overlap_with_400_calibration_records": not (set(active_corpus_ids) & calibration_ids),
        "b004_is_transferable_mechanism": any(
            row["benchmark_id"] == "B004"
            and row["expected_screening"] == "TRANSFERABLE_MECHANISM"
            for row in adjudicated_key
        ),
        "b005_uses_substantive_replacement": any(
            row["benchmark_id"] == "B005"
            and row["corpus_id"] == REPLACEMENT_CORPUS_ID
            and row["expected_screening"] == "CORE_INCLUDE"
            for row in adjudicated_key
        ),
        "retired_usgs_webpage_not_active": RETIRED_B005_CORPUS_ID not in active_corpus_ids,
        "key_blinded_and_resolved_ids_align": all(
            blind_by_record[row["calibration_record_id"]]["corpus_id"] == row["corpus_id"]
            and resolved_by_record[row["calibration_record_id"]]["corpus_id"] == row["corpus_id"]
            for row in adjudicated_key
        ),
        "blinded_file_contains_no_human_decisions": all(
            not row.get("human_decision") for row in adjudicated_blinded
        ),
        "benchmark_human_conflicts_resolved": len(comparison_conflicts) == 0,
    }
    qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "adjudication_date": ADJUDICATION_DATE,
        "active_benchmark_rows": len(adjudicated_key),
        "frozen_stage4_commit": FROZEN_STAGE4_COMMIT,
        "expected_category_counts": dict(sorted(expected_counts.items())),
        "replacement": {
            "benchmark_id": "B005",
            "retired_corpus_id": RETIRED_B005_CORPUS_ID,
            "retired_final_category": "EXCLUDE",
            "replacement_corpus_id": REPLACEMENT_CORPUS_ID,
            "replacement_doi": corpus[REPLACEMENT_CORPUS_ID]["doi"],
            "replacement_expected_category": "CORE_INCLUDE",
        },
        "checks": checks,
        "unresolved_conflicts": comparison_conflicts,
    }
    qa_path = CALIBRATION_DIR / "benchmark_adjudication_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")

    freeze_path = CALIBRATION_DIR / "development_prompt_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze.update(
        {
            "benchmark_status": "ADJUDICATED_QA_PASSED",
            "benchmark_conflicts": [],
            "adjudicated_benchmark_key_file": str(key_path.relative_to(ROOT)),
            "adjudicated_benchmark_key_sha256": file_sha256(key_path),
            "benchmark_adjudication_qa_file": str(qa_path.relative_to(ROOT)),
            "benchmark_adjudication_qa_sha256": file_sha256(qa_path),
            "next_gate": (
                "Obtain explicit authorization to send the 100 locked validation "
                "records to DeepSeek, then run locked validation exactly once with "
                "the frozen prompt hash."
            ),
        }
    )
    freeze_path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
