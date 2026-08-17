#!/usr/bin/env python3
"""Run frozen prompt v3 once on nine strictly blinded benchmark records."""

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
INPUT = STEP5 / "calibration" / "benchmark_model_input_adjudicated.csv"
PROMPT = STEP5 / "prompts" / "title_abstract_screening_v3.md"
SCHEMA = STEP5 / "schemas" / "screening_output.schema.json"
FREEZE = STEP5 / "calibration" / "development_prompt_freeze.json"
BENCHMARK_QA = STEP5 / "calibration" / "benchmark_adjudication_qa.json"
RUNS_DIR = STEP5 / "runs"
FORBIDDEN_COLUMNS = {
    "expected_screening",
    "expected_category",
    "benchmark_type",
    "human_decision",
    "human_reason_code",
    "human_rationale",
    "human_confidence",
    "reviewer",
    "review_notes",
    "final_category",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_input() -> tuple[list[dict[str, str]], list[str]]:
    with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    return rows, columns


def completed_runs(runs_dir: Path) -> list[str]:
    found = []
    for path in runs_dir.glob("*/run_manifest.json") if runs_dir.exists() else []:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            manifest.get("mode") == "benchmark_validation_screening"
            and manifest.get("status") in {"completed", "completed_with_failures"}
        ):
            found.append(str(path.parent))
    return sorted(found)


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    qa = json.loads(BENCHMARK_QA.read_text(encoding="utf-8"))
    prompt_hash = sha256_file(PROMPT)
    if freeze.get("prompt_sha256") != prompt_hash:
        raise ValueError("Frozen prompt hash mismatch")
    if qa.get("status") != "PASS" or not all(qa.get("checks", {}).values()):
        raise ValueError("Benchmark adjudication QA has not passed")
    prior = completed_runs(args.runs_dir)
    if prior:
        raise ValueError(f"Benchmark validation was already run: {prior}")

    rows, columns = read_input()
    if len(rows) != 9:
        raise ValueError(f"Expected nine benchmark rows; found {len(rows)}")
    if FORBIDDEN_COLUMNS & set(columns):
        raise ValueError(
            f"Benchmark model input contains forbidden columns: "
            f"{sorted(FORBIDDEN_COLUMNS & set(columns))}"
        )
    if any(row["split"] != "BENCHMARK_VALIDATION" for row in rows):
        raise ValueError("Non-benchmark row reached model input")
    if len({row["calibration_record_id"] for row in rows}) != 9:
        raise ValueError("Benchmark IDs are not unique")

    schema_text = SCHEMA.read_text(encoding="utf-8").strip()
    system_prompt = (
        PROMPT.read_text(encoding="utf-8").split("## Record template", 1)[0].strip()
        + "\n\n## Required JSON schema\n\n"
        + schema_text
        + "\n\nReturn every required property exactly as named. Do not add properties."
    )
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "benchmark-deepseek-v3-%Y%m%dT%H%M%SZ"
    )
    run_dir = args.runs_dir / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True)

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "benchmark_validation_screening",
        "one_time_run": True,
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(INPUT.relative_to(ROOT)),
        "input_sha256": sha256_file(INPUT),
        "input_split": "BENCHMARK_VALIDATION",
        "input_rows_selected": 9,
        "development_rows_loaded": 0,
        "validation_rows_loaded": 0,
        "benchmark_key_loaded": False,
        "human_labels_loaded": False,
        "forbidden_columns_present": False,
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": prompt_hash,
        "frozen_prompt_sha256": freeze["prompt_sha256"],
        "prompt_hash_matches_freeze": prompt_hash == freeze["prompt_sha256"],
        "schema_file": str(SCHEMA.relative_to(ROOT)),
        "schema_sha256": sha256_file(SCHEMA),
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
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            (response_dir / f"{result['calibration_record_id']}.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with PRINT_LOCK:
                succeeded = sum(item["status"] == "succeeded" for item in results)
                print(
                    f"progress {completed}/9 succeeded={succeeded} "
                    f"failed={completed-succeeded}",
                    flush=True,
                )

    results.sort(key=lambda item: str(item["calibration_record_id"]))
    parsed_path = run_dir / "parsed_decisions.csv"
    fields = ["calibration_record_id"] + OUTPUT_FIELDS + [
        "attempts",
        "request_sha256",
        "response_sha256",
    ]
    with parsed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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
    print(json.dumps({"run_dir": str(run_dir), "status": manifest["status"], "usage": usage}, indent=2))


if __name__ == "__main__":
    main()
