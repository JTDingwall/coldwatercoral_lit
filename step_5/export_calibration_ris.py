#!/usr/bin/env python3
"""Export the Stage 5 human-calibration records as Covidence-compatible RIS."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = ROOT / "step_5" / "calibration" / "human_labels.csv"
DEFAULT_BENCHMARKS = (
    ROOT / "step_5" / "calibration" / "benchmark_validation_blinded.csv"
)
DEFAULT_OUTPUT = (
    ROOT / "step_5" / "calibration" / "stage5_covidence_calibration.ris"
)
ORDER_SEED = "coldwatercoral-stage5-covidence-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(value: str) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())


def ris_type(document_type: str) -> str:
    value = clean(document_type).lower()
    if value in {"dissertation", "thesis_or_dissertation", "thesis"}:
        return "THES"
    if value in {"book"}:
        return "BOOK"
    if value in {"book-chapter", "chapter"}:
        return "CHAP"
    if "conference" in value or value == "cpaper":
        return "CPAPER"
    if value in {
        "government_report",
        "monitoring_report",
        "regulator_assessment",
        "report",
    }:
        return "RPRT"
    if value in {
        "government_webpage",
        "journal_or_publisher_page",
        "news_article",
        "project_or_program_page",
        "repository_record",
    }:
        return "ELEC"
    if value == "dataset":
        return "DATA"
    if value in {
        "article",
        "jour",
        "journalarticle",
        "review",
        "review; journalarticle",
        "preprint",
    }:
        return "JOUR"
    return "GEN"


def split_pipe(value: str) -> list[str]:
    return [clean(part) for part in (value or "").split("|") if clean(part)]


def stable_order(row: dict[str, str]) -> str:
    return hashlib.sha256(
        f"{ORDER_SEED}|{row['corpus_id']}".encode("utf-8")
    ).hexdigest()


def tag(lines: list[str], name: str, value: str) -> None:
    value = clean(value)
    if value:
        lines.append(f"{name}  - {value}")


def record_to_ris(row: dict[str, str]) -> str:
    lines: list[str] = []
    tag(lines, "TY", ris_type(row.get("document_type", "")))
    title = clean(row.get("title", "")) or f"[Untitled record {row['corpus_id']}]"
    tag(lines, "TI", title)
    for author in split_pipe(row.get("authors", "")):
        tag(lines, "AU", author)
    tag(lines, "PY", row.get("year", ""))
    tag(lines, "JO", row.get("source_title_or_issuer", ""))
    tag(lines, "DO", row.get("doi", ""))
    tag(lines, "UR", row.get("url", ""))
    tag(lines, "LA", row.get("language", ""))
    tag(lines, "AB", row.get("screening_text", ""))
    for family in split_pipe(row.get("families", "")):
        tag(lines, "KW", family)
    tag(lines, "AN", row.get("corpus_id", ""))
    tag(lines, "DB", "coldwatercoral_lit Stage 5 calibration")
    tag(lines, "N1", f"corpus_id={row.get('corpus_id', '')}")
    tag(lines, "N1", f"full_text_status={row.get('full_text_status', '')}")
    lines.append("ER  -")
    return "\r\n".join(lines)


def main() -> None:
    args = parse_args()
    calibration = read_csv(args.calibration)
    benchmarks = read_csv(args.benchmarks)
    rows = calibration + benchmarks

    if len(calibration) != 400:
        raise ValueError(f"Expected 400 calibration rows; found {len(calibration)}")
    if len(benchmarks) != 9:
        raise ValueError(f"Expected 9 blinded benchmark rows; found {len(benchmarks)}")

    corpus_ids = [row.get("corpus_id", "") for row in rows]
    if any(not corpus_id for corpus_id in corpus_ids):
        raise ValueError("Every RIS record must have a corpus_id")
    if len(set(corpus_ids)) != len(corpus_ids):
        raise ValueError("Duplicate corpus_id values found in RIS inputs")

    records = [record_to_ris(row) for row in sorted(rows, key=stable_order)]
    output = "\r\n\r\n".join(records) + "\r\n"
    forbidden = [
        "expected_screening",
        "benchmark_id",
        "positive_core",
        "negative_tropical",
        "benchmark_validation",
    ]
    lowered = output.lower()
    leaked = [term for term in forbidden if term in lowered]
    if leaked:
        raise ValueError(f"Blinding terms leaked into RIS: {leaked}")
    if output.count("TY  - ") != 409 or output.count("ER  -") != 409:
        raise ValueError("RIS record markers do not reconcile to 409 records")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output.encode("utf-8"))
    digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
    print(f"records=409")
    print(f"sha256={digest}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
