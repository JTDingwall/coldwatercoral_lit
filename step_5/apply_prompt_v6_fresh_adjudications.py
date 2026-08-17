#!/usr/bin/env python3
"""Apply the completed human review to the fresh prompt-v6 validation run."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "step_5" / "calibration"
RUN = ROOT / "step_5" / "runs" / "prompt-v6-fresh-deepseek-20260817"
MODEL = RUN / "prompt_v6_fresh_classifications.csv"
REVIEW_PACKET = RUN / "prompt_v6_fresh_human_review.csv"
COMPLETED = CAL / "prompt_v6_fresh_human_review_completed.csv"
ADJUDICATED = RUN / "prompt_v6_fresh_classifications_adjudicated.csv"
LOG = RUN / "prompt_v6_fresh_adjudication_log.csv"
RETAINED = RUN / "prompt_v6_fresh_retained_sources_adjudicated.csv"
EVALUATION = RUN / "prompt_v6_fresh_evaluation_adjudicated.json"
FREEZE = CAL / "prompt_v6_fresh_validation_freeze.json"
CATEGORIES = {
    "CORE_INCLUDE",
    "TRANSFERABLE_MECHANISM",
    "CITATION_CHAIN_CANDIDATE",
    "UNCERTAIN",
    "EXCLUDE",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"Cannot write an empty table: {path}")
    fieldnames = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    model = read_csv(MODEL)
    packet = read_csv(REVIEW_PACKET)
    completed = read_csv(COMPLETED)
    if len(model) != 80 or len(packet) != 21 or len(completed) != 21:
        raise ValueError("Expected 80 model rows and two matching 21-row review tables")
    if len({row["validation_record_id"] for row in completed}) != 21:
        raise ValueError("Completed review identifiers are not unique")
    if any(row["final_category"] not in CATEGORIES for row in completed):
        raise ValueError("Every completed review row must contain one allowed final category")

    packet_by_id = {row["validation_record_id"]: row for row in packet}
    completed_by_id = {row["validation_record_id"]: row for row in completed}
    if set(packet_by_id) != set(completed_by_id):
        raise ValueError("Completed review identifiers do not match the frozen review packet")
    protected = [field for field in completed[0] if field not in {"final_category", "reviewer_note"}]
    for record_id, row in completed_by_id.items():
        original = packet_by_id[record_id]
        for field in protected:
            if row[field] != original[field]:
                raise ValueError(f"Protected field changed for {record_id}: {field}")

    adjudicated: list[dict[str, str]] = []
    log: list[dict[str, str]] = []
    for row in model:
        record_id = row["validation_record_id"]
        reviewed = completed_by_id.get(record_id)
        if reviewed:
            final = reviewed["final_category"]
            note = reviewed["reviewer_note"]
            basis = "FOCUSED_HUMAN_REVIEW"
            log.append({
                "validation_record_id": record_id,
                "corpus_id": row["corpus_id"],
                "title": row["title"],
                "selection_stratum": row["selection_stratum"],
                "model_category": row["model_category"],
                "final_category": final,
                "changed": str(final != row["model_category"]),
                "reviewer_note": note,
                "adjudication_date": "2026-08-17",
            })
        else:
            final = row["model_category"]
            note = ""
            basis = (
                "TRUSTED_CORE_INCLUDE_POLICY"
                if final == "CORE_INCLUDE"
                else "UNCHANGED_OUTSIDE_FOCUSED_REVIEW"
            )
        adjudicated.append({
            **{field: value for field, value in row.items() if field not in {"final_category", "reviewer_note"}},
            "final_category": final,
            "adjudication_basis": basis,
            "reviewer_note": note,
        })

    write_csv(ADJUDICATED, adjudicated)
    write_csv(LOG, log)
    retained = [row for row in adjudicated if row["final_category"] != "EXCLUDE"]
    retained_fields = [
        "validation_record_id",
        "corpus_id",
        "title",
        "authors",
        "year",
        "source_title_or_issuer",
        "document_type",
        "doi",
        "url",
        "access",
        "access_type",
        "access_url",
        "screening_text",
        "final_category",
        "adjudication_basis",
        "reviewer_note",
    ]
    write_csv(
        RETAINED,
        [{field: row[field] for field in retained_fields} for row in retained],
        retained_fields,
    )

    reviewed_agreement = sum(row["changed"] == "False" for row in log)
    reviewed_citation = [row for row in log if row["model_category"] == "CITATION_CHAIN_CANDIDATE"]
    final_counts = Counter(row["final_category"] for row in adjudicated)
    tropical = [row for row in adjudicated if row["selection_stratum"] == "WARM_TROPICAL_HARD_NEGATIVE"]
    result = {
        "split": "PROMPT_V6_FRESH_VALIDATION_ADJUDICATED",
        "rows": len(adjudicated),
        "human_review_complete": True,
        "review_rows": len(log),
        "review_overrides": sum(row["changed"] == "True" for row in log),
        "review_exact_agreement": {
            "n": reviewed_agreement,
            "denominator": len(log),
            "proportion": round(reviewed_agreement / len(log), 4),
        },
        "final_classification_counts": {
            category: final_counts[category]
            for category in [
                "CORE_INCLUDE",
                "TRANSFERABLE_MECHANISM",
                "CITATION_CHAIN_CANDIDATE",
                "UNCERTAIN",
                "EXCLUDE",
            ]
        },
        "focused_review_findings": {
            "citation_chain_candidates_reviewed": len(reviewed_citation),
            "citation_chain_candidates_retained": sum(
                row["final_category"] == "CITATION_CHAIN_CANDIDATE" for row in reviewed_citation
            ),
            "citation_chain_candidates_rejected": sum(
                row["final_category"] == "EXCLUDE" for row in reviewed_citation
            ),
            "uncertain_rows_resolved_to_exclude": sum(
                row["model_category"] == "UNCERTAIN" and row["final_category"] == "EXCLUDE"
                for row in log
            ),
            "deepcold_response_exclusions_affirmed": sum(
                row["selection_stratum"] == "DEEPCOLD_RESPONSE"
                and row["model_category"] == "EXCLUDE"
                and row["final_category"] == "EXCLUDE"
                for row in log
            ),
            "retained_citation_chain_record_ids": [
                row["validation_record_id"]
                for row in log
                if row["final_category"] == "CITATION_CHAIN_CANDIDATE"
            ],
        },
        "policy_checks": {
            "all_18_core_includes_trusted": final_counts["CORE_INCLUDE"] == 18,
            "all_25_tropical_hard_negatives_excluded": len(tropical) == 25
            and all(row["final_category"] == "EXCLUDE" for row in tropical),
            "no_transferable_mechanism_rows": final_counts["TRANSFERABLE_MECHANISM"] == 0,
            "no_unresolved_uncertain_rows": final_counts["UNCERTAIN"] == 0,
            "all_four_focused_exclusions_affirmed": sum(
                row["selection_stratum"] == "DEEPCOLD_RESPONSE"
                and row["model_category"] == "EXCLUDE"
                and row["final_category"] == "EXCLUDE"
                for row in log
            ) == 4,
        },
        "prompt_v6_boundary_assessment": "PASS_CONSERVATIVE_SCOPE_BOUNDARY",
        "production_screening_approved": False,
        "production_hold_reason": (
            "Prompt v6 overused CITATION_CHAIN_CANDIDATE: 14 of 15 reviewed assignments were rejected. "
            "Tighten the citation-chain rule and validate the revision on a new zero-overlap sample before production."
        ),
        "outputs": {
            "completed_review": str(COMPLETED.relative_to(ROOT)),
            "adjudication_log": LOG.name,
            "adjudicated_classifications": ADJUDICATED.name,
            "retained_sources": RETAINED.name,
        },
    }
    EVALUATION.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    freeze["status"] = "HUMAN_REVIEW_COMPLETED_PROMPT_REFINEMENT_REQUIRED"
    freeze["adjudication"] = {
        "completed_date": "2026-08-17",
        "completed_review_sha256": sha256(COMPLETED),
        "adjudication_log_sha256": sha256(LOG),
        "adjudicated_classifications_sha256": sha256(ADJUDICATED),
        "retained_sources_sha256": sha256(RETAINED),
        "adjudicated_evaluation_sha256": sha256(EVALUATION),
        "final_counts": result["final_classification_counts"],
        "production_screening_approved": False,
    }
    freeze["next_gate"] = {
        "human_review_required": False,
        "human_review_rows": 0,
        "production_screening_approved": False,
        "required_action": "Tighten CITATION_CHAIN_CANDIDATE for prompt v7 and validate it on a new zero-overlap sample.",
    }
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
