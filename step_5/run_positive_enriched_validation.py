#!/usr/bin/env python3
"""Run frozen prompt v4 on the fresh 36-record positive-enriched validation set."""

from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from run_development_screening import OUTPUT_FIELDS, PRINT_LOCK, load_env_file, request_one, sha256_file


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
CAL = STEP5 / "calibration"
INPUT = CAL / "positive_enriched_validation_model_input.csv"
FREEZE = CAL / "positive_enriched_prompt_v4_freeze.json"
PROMPT = STEP5 / "prompts" / "title_abstract_screening_v4.md"
SCHEMA = STEP5 / "schemas" / "screening_output.schema.json"
RUNS_DIR = STEP5 / "runs"
FORBIDDEN = {"final_category", "reviewer_note", "human_decision", "expected_screening"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def prior_completed(runs_dir: Path) -> list[str]:
    found = []
    for path in runs_dir.glob("*/run_manifest.json") if runs_dir.exists() else []:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if manifest.get("mode") == "positive_enriched_validation_screening" and manifest.get("status") in {"completed", "completed_with_failures"}:
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
    if freeze["prompt_sha256"] != sha256_file(PROMPT):
        raise ValueError("Prompt v4 hash differs from frozen hash")
    if freeze["model_input_sha256"] != sha256_file(INPUT):
        raise ValueError("Model input hash differs from frozen hash")
    if not args.dry_run and freeze.get("external_transfer_authorized") is not True:
        raise ValueError("External transfer authorization is not recorded")
    prior = prior_completed(args.runs_dir)
    if prior:
        raise ValueError(f"Positive-enriched validation already ran: {prior}")
    rows, columns = read_csv(INPUT)
    if len(rows) != 36 or len({r["calibration_record_id"] for r in rows}) != 36:
        raise ValueError("Expected 36 unique validation rows")
    if FORBIDDEN & set(columns):
        raise ValueError(f"Forbidden label columns in model input: {sorted(FORBIDDEN & set(columns))}")
    if any(r["split"] != "POSITIVE_ENRICHED_VALIDATION" for r in rows):
        raise ValueError("Unexpected input split")

    schema_text = SCHEMA.read_text(encoding="utf-8").strip()
    system_prompt = PROMPT.read_text(encoding="utf-8").split("## Record template", 1)[0].strip() + "\n\n## Required JSON schema\n\n" + schema_text + "\n\nReturn every required property exactly as named. Do not add properties."
    run_id = args.run_id or datetime.now(timezone.utc).strftime("positive-enriched-v4-%Y%m%dT%H%M%SZ")
    run_dir = args.runs_dir / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "positive_enriched_validation_screening",
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(INPUT.relative_to(ROOT)),
        "input_sha256": sha256_file(INPUT),
        "input_split": "POSITIVE_ENRICHED_VALIDATION",
        "input_rows_selected": 36,
        "human_labels_loaded": False,
        "benchmark_key_loaded": False,
        "prior_calibration_rows_loaded": 0,
        "forbidden_columns_present": False,
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256_file(PROMPT),
        "frozen_prompt_sha256": freeze["prompt_sha256"],
        "prompt_hash_matches_freeze": True,
        "parameters": {"temperature": 0, "max_tokens": 1200, "thinking": "disabled", "response_format": "json_object", "workers": args.workers, "max_retries": args.max_retries, "timeout_seconds": args.timeout},
        "status": "prepared" if args.dry_run else "running",
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (run_dir / "input_ids.txt").write_text("\n".join(r["calibration_record_id"] for r in rows) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(request_one, row, api_key=api_key, base_url=base_url, model=model, system_prompt=system_prompt, timeout=args.timeout, max_retries=args.max_retries): row for row in rows}
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            (response_dir / f"{result['calibration_record_id']}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            with PRINT_LOCK:
                succeeded = sum(r["status"] == "succeeded" for r in results)
                print(f"progress {completed}/36 succeeded={succeeded} failed={completed-succeeded}", flush=True)
    results.sort(key=lambda r: str(r["calibration_record_id"]))
    parsed_path = run_dir / "parsed_decisions.csv"
    fields = ["calibration_record_id"] + OUTPUT_FIELDS + ["attempts", "request_sha256", "response_sha256"]
    with parsed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            if result["status"] != "succeeded":
                continue
            parsed = dict(result["parsed"])
            parsed["needs_full_text"] = str(parsed["needs_full_text"])
            writer.writerow({"calibration_record_id": result["calibration_record_id"], **parsed, "attempts": result["attempts"], "request_sha256": result["request_sha256"], "response_sha256": result["response_sha256"]})
    failures = [r for r in results if r["status"] != "succeeded"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for result in results:
        provider_usage = (result.get("provider_response") or {}).get("usage", {})
        for key in usage:
            usage[key] += int(provider_usage.get(key, 0) or 0)
    manifest.update({"completed_at": datetime.now(timezone.utc).isoformat(), "status": "completed" if not failures else "completed_with_failures", "succeeded_rows": len(results)-len(failures), "failed_rows": len(failures), "failed_calibration_record_ids": [r["calibration_record_id"] for r in failures], "usage": usage, "parsed_decisions_sha256": sha256_file(parsed_path)})
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "status": manifest["status"], "usage": usage}, indent=2))


if __name__ == "__main__":
    main()
