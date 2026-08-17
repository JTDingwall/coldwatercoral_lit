#!/usr/bin/env python3
"""Apply the three approved post-run benchmark adjudications.

Historical inputs, predictions, and the pre-adjudication key are preserved.
This script writes a post-run key for the exact inputs the model saw, an audit
log, an adjudicated evaluation, and an abstract-enriched B004 replacement
candidate for future validation.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CAL = STEP5 / "calibration"
RUN = STEP5 / "runs" / "benchmark-deepseek-v4-flash-v3-20260817"
DATE = "2026-08-17"
RELEVANT = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def main() -> None:
    key = read_csv(CAL / "benchmark_key_adjudicated.csv")
    comparison = read_csv(RUN / "benchmark_comparison.csv")
    if len(key) != 9 or len(comparison) != 9:
        raise ValueError("Expected nine benchmark key and comparison rows")

    post_key = [dict(row) for row in key]
    for row in post_key:
        if row["benchmark_id"] == "B004":
            row["expected_screening"] = "UNCERTAIN"
        elif row["benchmark_id"] == "B006":
            row["expected_screening"] = "TRANSFERABLE_MECHANISM"
        elif row["benchmark_id"] == "B009":
            row["expected_screening"] = "TRANSFERABLE_MECHANISM"

    expected_by_id = {row["calibration_record_id"]: row for row in post_key}
    post_comparison = []
    for row in comparison:
        expected = expected_by_id[row["calibration_record_id"]]
        revised = dict(row)
        revised["pre_adjudication_expected_screening"] = row["expected_screening"]
        revised["expected_screening"] = expected["expected_screening"]
        revised["exact_agreement"] = str(
            revised["expected_screening"] == revised["model_decision"]
        )
        revised["postrun_status"] = (
            "AGREES"
            if revised["exact_agreement"] == "True"
            else "GENUINE_MODEL_FAILURE"
        )
        post_comparison.append(revised)

    log = [
        {
            "adjudication_id": "BA-POST-001",
            "benchmark_id": "B009",
            "action": "KEEP_EXPECTED_CATEGORY_MODEL_FALSE_NEGATIVE",
            "old_expected_screening": "TRANSFERABLE_MECHANISM",
            "new_expected_screening": "TRANSFERABLE_MECHANISM",
            "decision_basis": (
                "Approved: Port of Miami remains the explicit project example of "
                "transferable dredging-related sediment accumulation and burial impacts."
            ),
            "decision_date": DATE,
        },
        {
            "adjudication_id": "BA-POST-002",
            "benchmark_id": "B004",
            "action": "TITLE_ONLY_INPUT_TO_UNCERTAIN_AND_ADD_ENRICHED_REPLACEMENT",
            "old_expected_screening": "TRANSFERABLE_MECHANISM",
            "new_expected_screening": "UNCERTAIN",
            "decision_basis": (
                "Approved: the exact model input had no abstract and cannot support a "
                "defensible transferable decision under conservative screening rules."
            ),
            "decision_date": DATE,
        },
        {
            "adjudication_id": "BA-POST-003",
            "benchmark_id": "B006",
            "action": "RELABEL_TO_TRANSFERABLE_MECHANISM",
            "old_expected_screening": "EXCLUDE",
            "new_expected_screening": "TRANSFERABLE_MECHANISM",
            "decision_basis": (
                "Approved: the abstract separately evaluates sedimentation and turbidity "
                "against coral growth, survival, reproduction, and recruitment."
            ),
            "decision_date": DATE,
        },
    ]

    replacement = [{
        "replacement_id": "B004R",
        "supersedes_benchmark_id": "B004",
        "calibration_record_id": "PENDING_NEW_VALIDATION_ID",
        "corpus_id": "CWC-104B2C5A7924",
        "title": "Sediment impacts on marine sponges",
        "authors": "James J. Bell | Emily McGrath | Andrew Biggerstaff | Tracey Bates | Holly Bennett | Joseph Marlow | Megan Shaffer",
        "year": "2015",
        "source_title_or_issuer": "Marine Pollution Bulletin",
        "document_type": "review",
        "doi": "10.1016/j.marpolbul.2015.03.030",
        "url": "https://pubmed.ncbi.nlm.nih.gov/25841888/",
        "language": "en",
        "screening_text": (
            "Review of settled and suspended sediment effects on marine sponges, "
            "including tolerance, physiology, adaptive responses, mechanisms, "
            "thresholds, and early life stages."
        ),
        "screening_text_basis": "Paraphrase of PubMed abstract, PMID 25841888",
        "expected_screening": "TRANSFERABLE_MECHANISM",
        "status": "REPLACEMENT_CANDIDATE_NOT_YET_MODEL_TESTED",
    }]

    key_path = CAL / "benchmark_key_postrun_adjudicated.csv"
    comparison_path = RUN / "benchmark_comparison_postrun_adjudicated.csv"
    log_path = CAL / "benchmark_postrun_adjudication_log.csv"
    replacement_path = CAL / "benchmark_replacement_candidates.csv"
    write_csv(key_path, post_key, list(post_key[0]))
    write_csv(comparison_path, post_comparison, list(post_comparison[0]))
    write_csv(log_path, log, list(log[0]))
    write_csv(replacement_path, replacement, list(replacement[0]))

    relevant = [r for r in post_comparison if r["expected_screening"] in RELEVANT]
    core = [r for r in post_comparison if r["expected_screening"] == "CORE_INCLUDE"]
    negatives = [r for r in post_comparison if r["expected_screening"] == "EXCLUDE"]
    silent = [r for r in relevant if r["model_decision"] == "EXCLUDE"]
    exact = sum(r["exact_agreement"] == "True" for r in post_comparison)
    core_hits = sum(r["model_decision"] == "CORE_INCLUDE" for r in core)
    relevant_hits = sum(r["model_decision"] in RELEVANT for r in relevant)
    negative_hits = sum(r["model_decision"] == "EXCLUDE" for r in negatives)
    metrics = {
        "exact_agreement": ratio(exact, 9),
        "core_include_recall": ratio(core_hits, len(core)),
        "combined_core_or_transferable_recall": ratio(relevant_hits, len(relevant)),
        "relevant_benchmarks_silently_excluded": len(silent),
        "negative_control_specificity": ratio(negative_hits, len(negatives)),
        "core_n": len(core),
        "core_or_transferable_n": len(relevant),
        "negative_control_n": len(negatives),
    }
    expected_counts = Counter(r["expected_screening"] for r in post_key)
    failures = [r for r in post_comparison if r["exact_agreement"] != "True"]
    report = {
        "status": "FAIL_GENUINE_MODEL_FALSE_NEGATIVE",
        "adjudication_date": DATE,
        "approved_recommendations_applied": 3,
        "historical_model_run_preserved": True,
        "postrun_expected_category_counts": dict(sorted(expected_counts.items())),
        "metrics": metrics,
        "genuine_model_failure_count": len(failures),
        "genuine_model_failures": [
            {
                "benchmark_id": r["benchmark_id"],
                "calibration_record_id": r["calibration_record_id"],
                "expected_screening": r["expected_screening"],
                "model_decision": r["model_decision"],
                "title": r["title"],
            }
            for r in failures
        ],
        "replacement_candidate_file": str(replacement_path.relative_to(ROOT)),
        "replacement_candidate_tested": False,
        "production_screening_approved": False,
    }
    report_path = RUN / "benchmark_evaluation_postrun_adjudicated.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    freeze_path = CAL / "development_prompt_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze.update({
        "benchmark_status": "POSTRUN_ADJUDICATED_GENUINE_MODEL_FAILURE",
        "benchmark_conflicts": [],
        "benchmark_genuine_model_failure_count": len(failures),
        "benchmark_postrun_key_file": str(key_path.relative_to(ROOT)),
        "benchmark_postrun_key_sha256": sha256(key_path),
        "benchmark_postrun_evaluation_file": str(report_path.relative_to(ROOT)),
        "benchmark_postrun_evaluation_sha256": sha256(report_path),
        "production_screening_approved": False,
        "next_gate": (
            "Develop prompt v4 from the single genuine Port of Miami false negative, "
            "obtain independent human labels for a fresh positive-enriched set, and "
            "validate v4 without reusing the failed benchmark as validation evidence."
        ),
    })
    freeze_path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
