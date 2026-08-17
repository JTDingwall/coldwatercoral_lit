#!/usr/bin/env python3
"""Run the one-time DeepSeek screen on the 100-record locked validation split.

This runner deliberately imports only the blinded calibration sample, frozen
prompt metadata, schema, and benchmark QA. It never opens human-label or
benchmark-key files. A completed locked-validation manifest prevents rerunning.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from run_development_screening import (
    OUTPUT_FIELDS,
    PRINT_LOCK,
    load_env_file,
    request_one,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CALIBRATION = STEP5 / "calibration" / "calibration_sample.csv"
FREEZE = STEP5 / "calibration" / "development_prompt_freeze.json"
BENCHMARK_QA = STEP5 / "calibration" / "benchmark_adjudication_qa.json"
SCHEMA = STEP5 / "schemas" / "screening_output.schema.json"
RUNS_DIR = STEP5 / "runs"
EXPECTED_PROMPT = STEP5 / "prompts" / "title_abstract_screening_v3.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def completed_validation_runs(runs_dir: Path) -> list[str]:
    completed = []
    if not runs_dir.exists():
        return completed
    for manifest_path in runs_dir.glob("*/run_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            manifest.get("mode") == "locked_validation_screening"
            and manifest.get("status") in {"completed", "completed_with_failures"}
        ):
            completed.append(str(manifest_path.parent))
    return sorted(completed)


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    benchmark_qa = json.loads(BENCHMARK_QA.read_text(encoding="utf-8"))
    expected_hash = freeze.get("prompt_sha256")
    observed_hash = sha256_file(EXPECTED_PROMPT)
    if freeze.get("status") != "DEVELOPMENT_GATE_PASSED":
        raise ValueError("Development gate is not passed")
    if freeze.get("locked_validation_status") != "NOT_RUN":
        raise ValueError("Freeze record does not authorize a first validation run")
    if expected_hash != observed_hash:
        raise ValueError("Frozen prompt hash mismatch")
    if freeze.get("prompt_file") != "step_5/prompts/title_abstract_screening_v3.md":
        raise ValueError("Unexpected frozen prompt path")
    if benchmark_qa.get("status") != "PASS":
        raise ValueError("Benchmark adjudication QA has not passed")
    if not all(benchmark_qa.get("checks", {}).values()):
        raise ValueError("One or more benchmark adjudication checks failed")

    prior_runs = completed_validation_runs(args.runs_dir)
    if prior_runs:
        raise ValueError(f"Locked validation was already run: {prior_runs}")

    all_rows = read_csv(CALIBRATION)
    rows = [row for row in all_rows if row["split"] == "VALIDATION"]
    if len(all_rows) != 400 or len(rows) != 100:
        raise ValueError(
            f"Expected 400 blinded calibration rows and 100 validation rows; "
            f"found {len(all_rows)} and {len(rows)}"
        )
    if any(row["split"] != "VALIDATION" for row in rows):
        raise ValueError("Non-validation row reached model input")
    if len({row["calibration_record_id"] for row in rows}) != 100:
        raise ValueError("Validation IDs are not unique")

    schema_text = SCHEMA.read_text(encoding="utf-8").strip()
    system_prompt = (
        EXPECTED_PROMPT.read_text(encoding="utf-8").split("## Record template", 1)[0].strip()
        + "\n\n## Required JSON schema\n\n"
        + schema_text
        + "\n\nReturn every required property exactly as named. Do not add properties."
    )
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "validation-deepseek-v3-%Y%m%dT%H%M%SZ"
    )
    run_dir = args.runs_dir / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True)

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "locked_validation_screening",
        "one_time_run": True,
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(CALIBRATION.relative_to(ROOT)),
        "input_sha256": sha256_file(CALIBRATION),
        "input_split": "VALIDATION",
        "input_rows_available": 100,
        "input_rows_selected": len(rows),
        "development_rows_loaded": 0,
        "benchmark_rows_loaded": 0,
        "benchmark_key_loaded": False,
        "human_labels_loaded": False,
        "prompt_file": str(EXPECTED_PROMPT.relative_to(ROOT)),
        "prompt_sha256": observed_hash,
        "frozen_prompt_sha256": expected_hash,
        "prompt_hash_matches_freeze": observed_hash == expected_hash,
        "schema_file": str(SCHEMA.relative_to(ROOT)),
        "schema_sha256": sha256_file(SCHEMA),
        "benchmark_qa_file": str(BENCHMARK_QA.relative_to(ROOT)),
        "benchmark_qa_sha256": sha256_file(BENCHMARK_QA),
        "parameters": {
            "temperature": 0,
            "max_tokens": 1200,
            "thinking": "disabled",
            "response_format": "json_object",
            "workers": args.workers,
            "max_retries": args.max_retries,
            "timeout_seconds": args.timeout,
        },
        "status": "prepared" if args.dry_run else "running",
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (run_dir / "input_ids.txt").write_text(
        "\n".join(row["calibration_record_id"] for row in rows) + "\n",
        encoding="utf-8",
    )
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                request_one,
                row,
                api_key=api_key,
                base_url=base_url,
                model=model,
                system_prompt=system_prompt,
                timeout=args.timeout,
                max_retries=args.max_retries,
            ): row
            for row in rows
        }
        completed = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            (response_dir / f"{result['calibration_record_id']}.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            completed += 1
            if completed == 1 or completed % 25 == 0 or completed == len(rows):
                with PRINT_LOCK:
                    succeeded = sum(item["status"] == "succeeded" for item in results)
                    print(
                        f"progress {completed}/{len(rows)} succeeded={succeeded} "
                        f"failed={completed-succeeded}",
                        flush=True,
                    )

    results.sort(key=lambda item: str(item["calibration_record_id"]))
    parsed_path = run_dir / "parsed_decisions.csv"
    parsed_fields = ["calibration_record_id"] + OUTPUT_FIELDS + [
        "attempts",
        "request_sha256",
        "response_sha256",
    ]
    with parsed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=parsed_fields)
        writer.writeheader()
        for result in results:
            if result["status"] != "succeeded":
                continue
            parsed = dict(result["parsed"])
            parsed["needs_full_text"] = str(parsed["needs_full_text"])
            writer.writerow(
                {
                    "calibration_record_id": result["calibration_record_id"],
                    **parsed,
                    "attempts": result["attempts"],
                    "request_sha256": result["request_sha256"],
                    "response_sha256": result["response_sha256"],
                }
            )

    failures = [result for result in results if result["status"] != "succeeded"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for result in results:
        provider_usage = (result.get("provider_response") or {}).get("usage", {})
        for key in usage:
            usage[key] += int(provider_usage.get(key, 0) or 0)
    manifest.update(
        {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed" if not failures else "completed_with_failures",
            "succeeded_rows": len(results) - len(failures),
            "failed_rows": len(failures),
            "failed_calibration_record_ids": [
                result["calibration_record_id"] for result in failures
            ],
            "usage": usage,
            "parsed_decisions_sha256": sha256_file(parsed_path),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": manifest["status"],
                "succeeded_rows": manifest["succeeded_rows"],
                "failed_rows": manifest["failed_rows"],
                "usage": usage,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
