#!/usr/bin/env python3
"""Add a conservative lawful-access audit to the fresh prompt-v6 sample.

This is a post-run audit and never changes the frozen model input. `access=YES`
means the frozen Stage 4 corpus recorded an open PDF or likely full-document
location. Publisher landing pages, abstracts, and unconfirmed institutional
subscription access remain `NO`.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "step_5" / "calibration" / "prompt_v6_fresh_validation_model_input.csv"
CORPUS = ROOT / "step_4" / "corpus" / "candidate_corpus.csv"
OUTPUT = ROOT / "step_5" / "calibration" / "prompt_v6_fresh_validation_access.csv"
READABLE_STATUSES = {"OPEN_ACCESS_PDF", "LIKELY_FULL_DOCUMENT_URL"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    rows = read_csv(INPUT)
    if len(rows) != 80:
        raise ValueError("Expected 80 fresh validation records")
    corpus = {row["corpus_id"]: row for row in read_csv(CORPUS)}
    checked_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, str]] = []
    for row in rows:
        source = corpus.get(row["corpus_id"], {})
        status = str(source.get("full_text_status") or row.get("full_text_status") or "")
        locations = [
            value.strip()
            for value in str(source.get("full_text_locations") or "").split(" | ")
            if value.strip()
        ]
        original = row.get("url", "").strip()
        if original and original not in locations:
            locations.append(original)
        access_url = next(
            (
                value
                for value in locations
                if "reference.pdf" not in value.lower()
                and not re.fullmatch(r"https?://doi\.org/.*", value, flags=re.I)
            ),
            "",
        )
        readable = status in READABLE_STATUSES
        results.append({
            "calibration_record_id": row["calibration_record_id"],
            "corpus_id": row["corpus_id"],
            "title": row["title"],
            "doi": row.get("doi", ""),
            "access": "YES" if readable else "NO",
            "access_type": "FROZEN_PUBLIC_FULL_TEXT_LOCATION" if readable else "NOT_CONFIRMED",
            "access_url": access_url if readable else "",
            "access_checked_at": checked_at,
            "access_basis": (
                f"Frozen Stage 4 full-text status is {status}; a lawful public full-document "
                "location was recorded."
                if readable
                else f"Frozen Stage 4 full-text status is {status or 'missing'}; lawful public full text was not confirmed."
            ),
        })

    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    yes = sum(row["access"] == "YES" for row in results)
    print(f"Access audit complete: {yes} YES, {len(results) - yes} NO")


if __name__ == "__main__":
    main()
