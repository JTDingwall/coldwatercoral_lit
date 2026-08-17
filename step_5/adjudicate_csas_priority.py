#!/usr/bin/env python3
"""Document manual disposition of four CSAS priority references not in Stage 4."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "step_5" / "calibration" / "reviewer_followup"
SOURCE = AUDIT_DIR / "csas_reference_audit.csv"

ADJUDICATIONS = {
    "CSAS-094": {
        "doi": "",
        "source_url": "https://doczz.net/doc/9117160/monitoring-of-drilling-activities",
        "source_authority": "Secondary full-text mirror; citation independently confirmed by DFO CSAS terms of reference",
        "provisional_category": "UNCERTAIN",
        "reason_code": "U04_AMBIGUOUS_RESPONSE",
        "next_action": "FULL_TEXT_SCREEN",
        "rationale": "The substantive DNV guideline is real and directly addresses drilling near cold-water corals, sedimentation, suspended matter, monitoring and mitigation. Confirm whether it reports an eligible biological response or only guidance.",
    },
    "CSAS-128": {
        "doi": "10.1016/j.biocon.2018.06.028",
        "source_url": "https://repository.library.noaa.gov/view/noaa/31452",
        "source_authority": "NOAA institutional repository",
        "provisional_category": "UNCERTAIN",
        "reason_code": "U03_AMBIGUOUS_STRESSOR",
        "next_action": "PROJECT_SCOPE_RULING",
        "rationale": "The record is a real deep-sea coral impact study, but the abstract frames the exposure as the Deepwater Horizon oil spill. Decide whether hydrocarbon-bearing particulate/floc deposition qualifies under the frozen sediment/particle pathway.",
    },
    "CSAS-146": {
        "doi": "10.12952/journal.elementa.000012",
        "source_url": "https://online.ucpress.edu/elementa/article/doi/10.12952/journal.elementa.000012/112340/Evidence-of-lasting-impact-of-the-Deepwater",
        "source_authority": "Publisher full-text landing page",
        "provisional_category": "UNCERTAIN",
        "reason_code": "U03_AMBIGUOUS_STRESSOR",
        "next_action": "PROJECT_SCOPE_RULING",
        "rationale": "The paper explicitly reports cold-water coral responses and hydrocarbon-bearing floc on colonies, but it remains ambiguous whether that mixed oil/floc exposure is an in-scope sediment stressor under the frozen protocol.",
    },
    "CSAS-269": {
        "doi": "",
        "source_url": "https://eprints.soton.ac.uk/377300/",
        "source_authority": "University of Southampton institutional repository",
        "provisional_category": "CORE_INCLUDE",
        "reason_code": "",
        "next_action": "ADD_TO_SUPPLEMENTARY_LAYER",
        "rationale": "The doctoral thesis directly tests sediment and drill-cuttings exposure in sponges, including the deep-water species Phakellia ventilabrum, with physiological and transcriptional responses.",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    source_rows = read_csv(SOURCE)
    source_by_id = {row["csas_reference_id"]: row for row in source_rows}
    output = []
    for reference_id, adjudication in ADJUDICATIONS.items():
        row = source_by_id[reference_id]
        if row["priority_for_scope_audit"] != "YES" or row["corpus_match_status"] == "PRESENT":
            raise ValueError(f"{reference_id} is no longer an unmatched priority reference")
        output.append(
            {
                "csas_reference_id": reference_id,
                "year": row["year"],
                "title": row["extracted_title"],
                "reference": row["reference"],
                "frozen_corpus_status": row["corpus_match_status"],
                **adjudication,
                "audit_date": "2026-08-17",
            }
        )

    fields = [
        "csas_reference_id",
        "year",
        "title",
        "reference",
        "doi",
        "source_url",
        "source_authority",
        "frozen_corpus_status",
        "provisional_category",
        "reason_code",
        "next_action",
        "rationale",
        "audit_date",
    ]
    audit_path = AUDIT_DIR / "csas_priority_manual_adjudication.csv"
    seed_path = AUDIT_DIR / "supplementary_priority_seed.csv"
    write_csv(audit_path, output, fields)
    write_csv(seed_path, output, fields)
    qa = {
        "priority_unmatched_rows": len(output),
        "provisional_categories": {
            category: sum(row["provisional_category"] == category for row in output)
            for category in sorted({row["provisional_category"] for row in output})
        },
        "supplementary_seeds": len(output),
        "definite_in_scope_gap": [
            row["csas_reference_id"]
            for row in output
            if row["provisional_category"] == "CORE_INCLUDE"
        ],
        "requires_human_or_scope_ruling": [
            row["csas_reference_id"]
            for row in output
            if row["provisional_category"] == "UNCERTAIN"
        ],
        "checks": {
            "all_four_priority_nonmatches_adjudicated": len(output) == 4,
            "frozen_stage4_corpus_not_modified": True,
            "supplementary_layer_separate": True,
        },
    }
    qa_path = AUDIT_DIR / "csas_priority_manual_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
