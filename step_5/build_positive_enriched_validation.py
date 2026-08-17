#!/usr/bin/env python3
"""Build a fresh, blinded 36-record validation review packet for prompt v4.

The set contains 24 unused CSAS-priority records plus 12 deterministically
selected high-signal challenge records. It excludes all 400 calibration records,
all benchmark records, and the B004 replacement candidate used during prompt
development. Human decisions are not prefilled, and selection provenance is
stored separately from the reviewer file.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CAL = STEP5 / "calibration"
FROZEN_COMMIT = "9fcb4f3834cbb15c43ac8a1f23dab6142e68185d"
FROZEN_CORPUS = "step_4/corpus/candidate_corpus.csv"
SEED = "stage5-v4-positive-enriched-validation-20260817"

ORGANISM_TERMS = (
    "coral",
    "sponge",
    "porifera",
    "lophelia",
    "desmophyllum",
    "gorgonian",
    "octocoral",
    "seapen",
    "sea pen",
)
SEDIMENT_TERMS = (
    "sediment",
    "turbid",
    "drill cutting",
    "drilling mud",
    "dredg",
    "burial",
    "smother",
    "tailing",
    "particle load",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def frozen_corpus() -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "show", f"{FROZEN_COMMIT}:{FROZEN_CORPUS}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return list(csv.DictReader(result.stdout.splitlines()))


def digest(value: str) -> str:
    return hashlib.sha256(f"{SEED}|{value}".encode()).hexdigest()


def main() -> None:
    corpus_rows = frozen_corpus()
    corpus = {row["corpus_id"]: row for row in corpus_rows}
    calibration = read_csv(CAL / "calibration_sample.csv")
    benchmarks = read_csv(CAL / "benchmark_key_adjudicated.csv")
    audit = read_csv(CAL / "reviewer_followup" / "csas_reference_audit.csv")
    used = {row["corpus_id"] for row in calibration} | {
        row["corpus_id"] for row in benchmarks
    }
    used.add("CWC-104B2C5A7924")  # B004 enriched replacement candidate.

    csas_rows = [
        row
        for row in audit
        if row["priority_for_scope_audit"] == "YES"
        and row["corpus_match_status"] == "PRESENT"
        and row["matched_corpus_id"] in corpus
        and row["matched_corpus_id"] not in used
    ]
    if len(csas_rows) != 24:
        raise ValueError(f"Expected 24 unused CSAS-priority rows; found {len(csas_rows)}")
    selected: list[tuple[dict[str, str], str, str]] = [
        (corpus[row["matched_corpus_id"]], "CSAS_PRIORITY_UNUSED", row["csas_reference_id"])
        for row in csas_rows
    ]
    selected_ids = {row[0]["corpus_id"] for row in selected}

    challenge_pool = []
    for row in corpus_rows:
        if row["corpus_id"] in used or row["corpus_id"] in selected_ids:
            continue
        text = f"{row['title']} {row['abstract_or_snippet']}".lower()
        if not any(term in text for term in ORGANISM_TERMS):
            continue
        if not any(term in text for term in SEDIMENT_TERMS):
            continue
        challenge_pool.append(row)
    with_text = sorted(
        [row for row in challenge_pool if row["abstract_or_snippet"].strip()],
        key=lambda row: digest("abstract|" + row["corpus_id"]),
    )
    title_only = sorted(
        [row for row in challenge_pool if not row["abstract_or_snippet"].strip()],
        key=lambda row: digest("title|" + row["corpus_id"]),
    )
    challenge = with_text[:8] + title_only[:4]
    if len(challenge) != 12:
        raise ValueError(f"Expected 12 challenge rows; found {len(challenge)}")
    selected.extend((row, "DETERMINISTIC_HIGH_SIGNAL_CHALLENGE", "") for row in challenge)

    selected.sort(key=lambda item: digest("shuffle|" + item[0]["corpus_id"]))
    review_rows = []
    provenance_rows = []
    for index, (row, stratum, source_reference_id) in enumerate(selected, start=1):
        record_id = f"PEV-{index:03d}"
        review_rows.append({
            "validation_record_id": record_id,
            "corpus_id": row["corpus_id"],
            "title": row["title"],
            "authors": row["authors"],
            "year": row["year"],
            "source_title_or_issuer": row["source_title_or_issuer"],
            "document_type": row["document_type"],
            "doi": row["doi"],
            "url": row["url"],
            "language": row["language"],
            "screening_text": row["abstract_or_snippet"],
            "full_text_status": row["full_text_status"],
            "final_category": "",
            "reviewer_note": "",
        })
        provenance_rows.append({
            "validation_record_id": record_id,
            "corpus_id": row["corpus_id"],
            "selection_stratum": stratum,
            "source_reference_id": source_reference_id,
            "selection_seed": SEED,
            "frozen_stage4_commit": FROZEN_COMMIT,
        })

    review_path = CAL / "positive_enriched_validation_review.csv"
    provenance_path = CAL / "positive_enriched_validation_provenance.csv"
    write_csv(review_path, review_rows, list(review_rows[0]))
    write_csv(provenance_path, provenance_rows, list(provenance_rows[0]))
    print(f"review_rows={len(review_rows)}")
    print(f"csas_priority_rows={sum(r['selection_stratum']=='CSAS_PRIORITY_UNUSED' for r in provenance_rows)}")
    print(f"challenge_rows={sum(r['selection_stratum']=='DETERMINISTIC_HIGH_SIGNAL_CHALLENGE' for r in provenance_rows)}")
    print(f"review_file={review_path}")


if __name__ == "__main__":
    main()
