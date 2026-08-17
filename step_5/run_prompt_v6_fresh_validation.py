#!/usr/bin/env python3
"""Run the authorized prompt-v6 batch on the fresh 80-record validation set."""

from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from run_development_screening import PRINT_LOCK, load_env_file, sha256_file
from run_positive_enriched_validation_v5 import OUTPUT_FIELDS, request_one


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
INPUT = STEP5 / "calibration" / "prompt_v6_fresh_validation_model_input.csv"
FREEZE = STEP5 / "calibration" / "prompt_v6_fresh_validation_freeze.json"
PROMPT = STEP5 / "prompts" / "title_abstract_screening_v6.md"
SCHEMA = STEP5 / "schemas" / "screening_output_v5.schema.json"
RUNS = STEP5 / "runs"
FORBIDDEN = {"final_category", "reviewer_note", "human_decision", "expected_screening", "model_decision"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id", default="prompt-v6-fresh-deepseek-20260817")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--thinking", choices=["enabled", "disabled"], default="enabled")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")

    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_AUTHORIZED_NOT_RUN":
        raise ValueError("Fresh v6 validation is not in the authorized pre-run state")
    if freeze["input_sha256"] != sha256_file(INPUT):
        raise ValueError("Fresh validation input differs from its freeze hash")
    if freeze["prompt_sha256"] != sha256_file(PROMPT):
        raise ValueError("Prompt v6 differs from its freeze hash")
    if freeze["schema_sha256"] != sha256_file(SCHEMA):
        raise ValueError("Schema differs from its freeze hash")
    if freeze.get("external_transfer_authorized") is not True and not args.dry_run:
        raise ValueError("External transfer is not authorized")

    rows, columns = read_csv(INPUT)
    if len(rows) != 80 or len({row["calibration_record_id"] for row in rows}) != 80:
        raise ValueError("Expected 80 unique fresh validation rows")
    if FORBIDDEN & set(columns):
        raise ValueError(f"Forbidden label columns present: {sorted(FORBIDDEN & set(columns))}")
    if any(row["split"] != "PROMPT_V6_FRESH_VALIDATION" for row in rows):
        raise ValueError("Unexpected split in fresh v6 model input")

    system_prompt = (
        PROMPT.read_text(encoding="utf-8").split("## Record template", 1)[0].strip()
        + "\n\n## Required JSON schema\n\n"
        + SCHEMA.read_text(encoding="utf-8").strip()
        + "\n\nReturn every required property exactly as named. Do not add properties."
    )
    run_dir = RUNS / args.run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True)
    manifest = {
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "prompt_v6_fresh_validation_screening",
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(INPUT.relative_to(ROOT)),
        "input_sha256": sha256_file(INPUT),
        "input_rows_selected": len(rows),
        "human_labels_loaded_for_requests": False,
        "prior_model_decisions_loaded_for_requests": False,
        "benchmark_key_loaded": False,
        "forbidden_columns_present": False,
        "full_text_included": False,
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256_file(PROMPT),
        "schema_file": str(SCHEMA.relative_to(ROOT)),
        "schema_sha256": sha256_file(SCHEMA),
        "parameters": {
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "thinking": args.thinking,
            "response_format": "json_object",
            "workers": args.workers,
            "max_retries": args.max_retries,
            "timeout_seconds": args.timeout,
        },
        "external_transfer_authorization": freeze["external_transfer_authorization_scope"],
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
                max_tokens=args.max_tokens,
                thinking=args.thinking,
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
                    f"progress {completed}/80 succeeded={succeeded} failed={completed-succeeded}",
                    flush=True,
                )

    results.sort(key=lambda item: str(item["calibration_record_id"]))
    by_id = {row["calibration_record_id"]: row for row in rows}
    parsed_path = run_dir / "parsed_decisions.csv"
    fields = [
        "calibration_record_id",
        *OUTPUT_FIELDS,
        "attempts",
        "request_sha256",
        "response_sha256",
    ]
    with parsed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for result in results:
            if result["status"] != "succeeded":
                continue
            parsed = dict(result["parsed"])
            parsed["needs_full_text"] = str(parsed["needs_full_text"])
            writer.writerow({
                "calibration_record_id": result["calibration_record_id"],
                **parsed,
                "attempts": result["attempts"],
                "request_sha256": result["request_sha256"],
                "response_sha256": result["response_sha256"],
            })

    failures = [result for result in results if result["status"] != "succeeded"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for result in results:
        provider_usage = (result.get("provider_response") or {}).get("usage", {})
        for key in usage:
            usage[key] += int(provider_usage.get(key, 0) or 0)
    manifest.update({
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if not failures else "completed_with_failures",
        "succeeded_rows": len(results) - len(failures),
        "failed_rows": len(failures),
        "failed_calibration_record_ids": [result["calibration_record_id"] for result in failures],
        "usage": usage,
        "parsed_decisions_sha256": sha256_file(parsed_path),
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "status": manifest["status"], "usage": usage}, indent=2))


if __name__ == "__main__":
    main()
