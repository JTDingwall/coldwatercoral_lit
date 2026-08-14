#!/usr/bin/env python3
"""Build the reproducible Stage 5 human calibration and benchmark sets.

This script samples metadata only. It does not call an AI model and does not
perform relevance screening.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "step_4" / "corpus" / "candidate_corpus.csv"
PROVENANCE_PATH = ROOT / "step_4" / "corpus" / "candidate_corpus_provenance.csv"
BENCHMARK_RECOVERY_PATH = (
    ROOT / "step_4" / "benchmark_recovery" / "benchmark_recovery.csv"
)
OUTPUT_DIR = ROOT / "step_5" / "calibration"
SEED = "coldwatercoral-stage5-calibration-v1"
SAMPLE_SIZE = 400
VALIDATION_SIZE = 100
EXPECTED_CORPUS_ROWS = 43307
EXPECTED_PROVENANCE_ROWS = 58398
MAX_SCREENING_TEXT_CHARS = 1200

FAMILY_ORDER = [
    "SED_SUSPENDED",
    "SED_DEPOSITION",
    "SED_DRILLING",
    "SED_DREDGING",
    "SED_TAILINGS",
    "MECH_FEEDING_MUCUS_CORAL",
    "MECH_FEEDING_PUMPING_SPONGE",
    "RESP_THRESHOLD_RECOVERY",
]

ORGANISM_RE = re.compile(
    r"\b(coral|corals|octocoral|gorgonian|sea pen|sea pens|pennatul|"
    r"scleractin|lophelia|desmophyllum|madrepora|solenosmilia|"
    r"sponge|sponges|porifera)\b",
    re.IGNORECASE,
)
STRESSOR_RE = re.compile(
    r"\b(sediment|sedimentation|suspended solids|turbidity|turbid|"
    r"burial|buried|smother|dredg|drill cuttings|drilling mud|"
    r"resuspension|resuspended|tailings|particle loading|sediment plume)\b",
    re.IGNORECASE,
)

BASE_FIELDS = [
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
HUMAN_FIELDS = BASE_FIELDS + [
    "human_decision",
    "human_reason_code",
    "human_rationale",
    "human_screening_source",
    "human_confidence",
    "human_needs_full_text",
    "reviewer",
    "review_date",
    "review_notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Allow stale local Stage 4 counts and missing benchmark corpus rows.",
    )
    return parser.parse_args()


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_pipe(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def choose_primary_family(row: dict[str, str]) -> str:
    observed = set(split_pipe(row.get("families", "")))
    valid = [family for family in FAMILY_ORDER if family in observed]
    if not valid:
        return "OTHER"
    return min(
        valid,
        key=lambda family: digest_text(
            f"{SEED}|family|{row['corpus_id']}|{family}"
        ),
    )


def system_stratum(row: dict[str, str]) -> str:
    systems = set(split_pipe(row.get("discovery_systems", "")))
    if "Grey literature" in systems:
        return "GREY_LITERATURE"
    if "Web of Science" in systems:
        return "WEB_OF_SCIENCE"
    if "Citation chaining" in systems:
        return "CITATION_CHAINING"
    if "OpenAlex" in systems and "Semantic Scholar" in systems:
        return "MULTI_SCHOLARLY"
    if "OpenAlex" in systems:
        return "OPENALEX"
    if "Semantic Scholar" in systems:
        return "SEMANTIC_SCHOLAR"
    return "OTHER"


def signal_tier(row: dict[str, str]) -> str:
    text = f"{row.get('title', '')} {row.get('abstract_or_snippet', '')}"
    organism = bool(ORGANISM_RE.search(text))
    stressor = bool(STRESSOR_RE.search(text))
    if organism and stressor:
        return "ORGANISM_AND_STRESSOR"
    if organism:
        return "ORGANISM_ONLY"
    if stressor:
        return "STRESSOR_ONLY"
    return "NEITHER_SIGNAL"


def prepare_row(row: dict[str, str]) -> dict[str, object]:
    abstract = (row.get("abstract_or_snippet") or "").strip()
    screening_text = abstract[:MAX_SCREENING_TEXT_CHARS]
    return {
        **row,
        "screening_text": screening_text,
        "text_truncated": len(abstract) > len(screening_text),
        "primary_family": choose_primary_family(row),
        "system_stratum": system_stratum(row),
        "signal_tier": signal_tier(row),
        "metadata_stratum": "TITLE_ABSTRACT" if abstract else "TITLE_ONLY",
        "full_text_bin": (
            "NOT_IDENTIFIED"
            if row.get("full_text_status") == "NOT_IDENTIFIED"
            else "IDENTIFIED"
        ),
        "document_type_stratum": (row.get("document_type") or "MISSING")
        .strip()
        .upper()[:60],
    }


def stable_order(rows: list[dict[str, object]], salt: str) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: digest_text(f"{SEED}|{salt}|{row['corpus_id']}"),
    )


def ensure_levels(
    rows: list[dict[str, object]],
    selected: dict[str, dict[str, object]],
    field: str,
    minimum: int,
    allowed_levels: set[str] | None = None,
) -> None:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        level = str(row[field])
        if allowed_levels is None or level in allowed_levels:
            groups[level].append(row)
    for level in sorted(groups):
        current = sum(1 for row in selected.values() if str(row[field]) == level)
        for row in stable_order(groups[level], f"ensure|{field}|{level}"):
            if current >= minimum or len(selected) >= SAMPLE_SIZE:
                break
            corpus_id = str(row["corpus_id"])
            if corpus_id not in selected:
                selected[corpus_id] = row
                current += 1


def select_sample(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    ensure_levels(rows, selected, "primary_family", 8, set(FAMILY_ORDER))
    ensure_levels(rows, selected, "system_stratum", 8)
    ensure_levels(rows, selected, "signal_tier", 20)
    ensure_levels(rows, selected, "metadata_stratum", 20)
    ensure_levels(rows, selected, "full_text_bin", 15)

    document_counts = Counter(str(row["document_type_stratum"]) for row in rows)
    common_documents = {
        label
        for label, _ in sorted(
            document_counts.items(), key=lambda item: (-item[1], item[0])
        )[:12]
    }
    ensure_levels(rows, selected, "document_type_stratum", 5, common_documents)

    buckets: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = "|".join(
            str(row[field])
            for field in (
                "primary_family",
                "system_stratum",
                "signal_tier",
                "metadata_stratum",
                "full_text_bin",
            )
        )
        buckets[key].append(row)
    for key in buckets:
        buckets[key] = stable_order(buckets[key], f"bucket|{key}")

    bucket_keys = sorted(buckets, key=lambda key: digest_text(f"{SEED}|{key}"))
    positions = {key: 0 for key in bucket_keys}
    round_number = 0
    while len(selected) < SAMPLE_SIZE:
        added = 0
        for key in bucket_keys:
            bucket = buckets[key]
            while positions[key] < len(bucket):
                row = bucket[positions[key]]
                positions[key] += 1
                corpus_id = str(row["corpus_id"])
                if corpus_id not in selected:
                    selected[corpus_id] = row
                    added += 1
                    break
            if len(selected) >= SAMPLE_SIZE:
                break
        if added == 0:
            for row in stable_order(rows, f"fallback|{round_number}"):
                corpus_id = str(row["corpus_id"])
                if corpus_id not in selected:
                    selected[corpus_id] = row
                    added += 1
                    if len(selected) >= SAMPLE_SIZE:
                        break
        if added == 0:
            raise RuntimeError("Unable to fill calibration sample")
        round_number += 1

    return stable_order(list(selected.values()), "final-sample")


def output_row(
    row: dict[str, object], record_id: str, split: str
) -> dict[str, object]:
    return {
        "calibration_record_id": record_id,
        "split": split,
        **{field: row.get(field, "") for field in BASE_FIELDS if field not in {"calibration_record_id", "split"}},
    }


def counts(rows: list[dict[str, object]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def main() -> None:
    args = parse_args()
    corpus = read_csv(CORPUS_PATH)
    provenance_rows = read_csv(PROVENANCE_PATH)
    benchmark_recovery = read_csv(BENCHMARK_RECOVERY_PATH)

    if not args.smoke_test:
        if len(corpus) != EXPECTED_CORPUS_ROWS:
            raise ValueError(
                f"Expected {EXPECTED_CORPUS_ROWS} corpus rows; found {len(corpus)}"
            )
        if len(provenance_rows) != EXPECTED_PROVENANCE_ROWS:
            raise ValueError(
                f"Expected {EXPECTED_PROVENANCE_ROWS} provenance rows; "
                f"found {len(provenance_rows)}"
            )

    corpus_by_id = {row["corpus_id"]: row for row in corpus}
    benchmark_by_corpus = {
        row["matched_corpus_id"]: row
        for row in benchmark_recovery
        if row.get("matched_corpus_id")
    }
    benchmark_ids = set(benchmark_by_corpus)
    missing_benchmarks = sorted(benchmark_ids - set(corpus_by_id))
    if missing_benchmarks and not args.smoke_test:
        raise ValueError(f"Benchmark corpus rows missing: {missing_benchmarks}")

    eligible = [
        prepare_row(row) for row in corpus if row["corpus_id"] not in benchmark_ids
    ]
    if len(eligible) < SAMPLE_SIZE:
        raise ValueError("Not enough non-benchmark records for calibration")

    selected = select_sample(eligible)
    validation_ids = {
        str(row["corpus_id"])
        for row in stable_order(selected, "validation-split")[:VALIDATION_SIZE]
    }
    sample_rows: list[dict[str, object]] = []
    for index, row in enumerate(selected, start=1):
        split = "VALIDATION" if str(row["corpus_id"]) in validation_ids else "DEVELOPMENT"
        sample_rows.append(output_row(row, f"CAL-{index:04d}", split))

    human_rows = [
        {
            **row,
            "human_decision": "",
            "human_reason_code": "",
            "human_rationale": "",
            "human_screening_source": "",
            "human_confidence": "",
            "human_needs_full_text": "",
            "reviewer": "",
            "review_date": "",
            "review_notes": "",
        }
        for row in sample_rows
    ]

    benchmark_blinded: list[dict[str, object]] = []
    benchmark_key: list[dict[str, object]] = []
    available_benchmarks = [
        (corpus_id, benchmark_by_corpus[corpus_id])
        for corpus_id in sorted(benchmark_ids)
        if corpus_id in corpus_by_id
    ]
    available_benchmarks.sort(
        key=lambda item: digest_text(f"{SEED}|benchmark|{item[0]}")
    )
    for index, (corpus_id, benchmark) in enumerate(available_benchmarks, start=1):
        record_id = f"BV-{index:03d}"
        prepared = prepare_row(corpus_by_id[corpus_id])
        blinded = output_row(prepared, record_id, "BENCHMARK_VALIDATION")
        blinded.update(
            {
                "human_decision": "",
                "human_reason_code": "",
                "human_rationale": "",
                "human_screening_source": "",
                "human_confidence": "",
                "human_needs_full_text": "",
                "reviewer": "",
                "review_date": "",
                "review_notes": "",
            }
        )
        benchmark_blinded.append(blinded)
        benchmark_key.append(
            {
                "calibration_record_id": record_id,
                "corpus_id": corpus_id,
                "benchmark_id": benchmark["benchmark_id"],
                "expected_screening": benchmark["expected_screening"],
            }
        )

    write_csv(OUTPUT_DIR / "calibration_sample.csv", sample_rows, BASE_FIELDS)
    write_csv(OUTPUT_DIR / "human_labels.csv", human_rows, HUMAN_FIELDS)
    write_csv(
        OUTPUT_DIR / "benchmark_validation_blinded.csv",
        benchmark_blinded,
        HUMAN_FIELDS,
    )
    write_csv(
        OUTPUT_DIR / "benchmark_key.csv",
        benchmark_key,
        [
            "calibration_record_id",
            "corpus_id",
            "benchmark_id",
            "expected_screening",
        ],
    )

    qa = {
        "seed": SEED,
        "input": {
            "candidate_corpus_rows": len(corpus),
            "candidate_corpus_sha256": file_sha256(CORPUS_PATH),
            "provenance_rows": len(provenance_rows),
            "provenance_sha256": file_sha256(PROVENANCE_PATH),
            "benchmark_rows": len(benchmark_recovery),
        },
        "calibration": {
            "sample_rows": len(sample_rows),
            "development_rows": sum(row["split"] == "DEVELOPMENT" for row in sample_rows),
            "validation_rows": sum(row["split"] == "VALIDATION" for row in sample_rows),
            "benchmark_validation_rows": len(benchmark_blinded),
            "by_primary_family": counts(sample_rows, "primary_family"),
            "by_system_stratum": counts(sample_rows, "system_stratum"),
            "by_signal_tier": counts(sample_rows, "signal_tier"),
            "by_metadata_stratum": counts(sample_rows, "metadata_stratum"),
            "by_full_text_status": counts(sample_rows, "full_text_status"),
            "by_document_type": counts(sample_rows, "document_type"),
        },
        "checks": {
            "authoritative_corpus_count": len(corpus) == EXPECTED_CORPUS_ROWS,
            "authoritative_provenance_count": len(provenance_rows) == EXPECTED_PROVENANCE_ROWS,
            "sample_size_400": len(sample_rows) == SAMPLE_SIZE,
            "development_size_300": sum(row["split"] == "DEVELOPMENT" for row in sample_rows) == 300,
            "validation_size_100": sum(row["split"] == "VALIDATION" for row in sample_rows) == 100,
            "sample_corpus_ids_unique": len({row["corpus_id"] for row in sample_rows}) == len(sample_rows),
            "benchmarks_excluded_from_calibration": not (
                {str(row["corpus_id"]) for row in sample_rows} & benchmark_ids
            ),
            "all_benchmarks_in_blinded_set": len(benchmark_blinded) == len(benchmark_recovery),
            "benchmark_expected_labels_absent_from_blinded_file": all(
                "expected_screening" not in row and "benchmark_id" not in row
                for row in benchmark_blinded
            ),
            "human_labels_blank": all(not row["human_decision"] for row in human_rows),
            "no_relevance_screening_performed": True,
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "calibration_qa.json").open("w", encoding="utf-8") as handle:
        json.dump(qa, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    if not args.smoke_test and not all(qa["checks"].values()):
        failed = [name for name, passed in qa["checks"].items() if not passed]
        raise RuntimeError(f"Calibration QA failed: {failed}")

    print(
        json.dumps(
            {
                "sample_rows": len(sample_rows),
                "development_rows": qa["calibration"]["development_rows"],
                "validation_rows": qa["calibration"]["validation_rows"],
                "benchmark_validation_rows": len(benchmark_blinded),
                "smoke_test": args.smoke_test,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
