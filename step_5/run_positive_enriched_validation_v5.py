#!/usr/bin/env python3
"""Run conservative prompt v5 on the 36-record positive-enriched set.

The request payload never contains human categories, v4 decisions, benchmark
keys, or the later core-lock table. Public-access status is included as metadata
but is explicitly prohibited from affecting the scientific category.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from run_development_screening import PRINT_LOCK, load_env_file, sha256_bytes, sha256_file


ROOT = Path(__file__).resolve().parents[1]
STEP5 = ROOT / "step_5"
INPUT = STEP5 / "calibration" / "positive_enriched_validation_model_input_v5.csv"
FREEZE = STEP5 / "calibration" / "positive_enriched_prompt_v5_freeze.json"
PROMPT = STEP5 / "prompts" / "title_abstract_screening_v5.md"
SCHEMA = STEP5 / "schemas" / "screening_output_v5.schema.json"
RUNS_DIR = STEP5 / "runs"
FORBIDDEN = {"final_category", "reviewer_note", "human_decision", "expected_screening", "model_decision"}
VALID_DECISIONS = {"CORE_INCLUDE", "TRANSFERABLE_MECHANISM", "CITATION_CHAIN_CANDIDATE", "EXCLUDE", "UNCERTAIN"}
VALID_REASONS = {
    None,
    "T01_CLOSE_TRAIT_ANALOGUE",
    "C01_DEEP_COLD_CONTEXT_NO_RESPONSE",
    "C02_REVIEW_OR_MONITORING_LEAD",
    "C03_STRESSOR_OR_TRAIT_LEAD",
    "X01_ORGANISM_OUT_OF_SCOPE",
    "X02_TROPICAL_NOT_CLOSELY_TRANSFERABLE",
    "X03_STRESSOR_OUT_OF_SCOPE",
    "X04_SEDIMENT_PATHWAY_NOT_EXPLICIT",
    "X05_RESPONSE_OUT_OF_SCOPE",
    "X06_SOURCE_NOT_SUBSTANTIVE",
    "X07_NOT_A_SOURCE",
    "X08_OTHER_SCOPE_FAILURE",
    "U01_MISSING_ABSTRACT",
    "U02_AMBIGUOUS_ORGANISM",
    "U03_AMBIGUOUS_STRESSOR",
    "U04_AMBIGUOUS_RESPONSE",
    "U05_AMBIGUOUS_TRANSFERABILITY",
    "U06_CONFLICTING_METADATA",
}
VALID_SOURCES = {"TITLE_ONLY", "TITLE_ABSTRACT", "LANDING_PAGE", "FULL_TEXT"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
OUTPUT_FIELDS = [
    "corpus_id",
    "decision",
    "reason_code",
    "organism_evidence",
    "stressor_evidence",
    "response_evidence",
    "transferability_basis",
    "citation_chain_basis",
    "screening_source",
    "confidence",
    "needs_full_text",
    "rationale",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id")
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


def make_record_text(row: dict[str, str]) -> str:
    fields = [
        ("corpus_id", row["corpus_id"]),
        ("title", row["title"]),
        ("authors", row["authors"]),
        ("year", row["year"]),
        ("source_title_or_issuer", row["source_title_or_issuer"]),
        ("document_type", row["document_type"]),
        ("language", row["language"]),
        ("abstract_or_snippet", row["screening_text"]),
        ("full_text_status", row["full_text_status"]),
        ("access", row["access"]),
        ("discovery_systems", row["discovery_systems"]),
        ("query_ids", row["query_ids"]),
        ("families", row["families"]),
    ]
    return "\n".join(f"{name}: {value}" for name, value in fields)


def validate_output(value: object, expected_corpus_id: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Response is not a JSON object")
    missing = set(OUTPUT_FIELDS) - set(value)
    extra = set(value) - set(OUTPUT_FIELDS)
    if missing or extra:
        raise ValueError(f"Schema keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    if value["corpus_id"] != expected_corpus_id:
        raise ValueError("corpus_id does not match request")
    decision = value["decision"]
    reason = value["reason_code"]
    if decision not in VALID_DECISIONS or reason not in VALID_REASONS:
        raise ValueError("invalid decision or reason_code")
    required_prefix = {"TRANSFERABLE_MECHANISM": "T", "CITATION_CHAIN_CANDIDATE": "C", "EXCLUDE": "X", "UNCERTAIN": "U"}.get(str(decision))
    if required_prefix and not str(reason).startswith(required_prefix):
        raise ValueError(f"{decision} requires a {required_prefix} reason")
    if decision == "CORE_INCLUDE" and reason is not None:
        raise ValueError("CORE_INCLUDE requires null reason_code")
    if value["screening_source"] not in VALID_SOURCES or value["confidence"] not in VALID_CONFIDENCE:
        raise ValueError("invalid screening source or confidence")
    if not isinstance(value["needs_full_text"], bool):
        raise ValueError("needs_full_text must be boolean")
    for field in ("organism_evidence", "stressor_evidence", "response_evidence", "rationale"):
        if not isinstance(value[field], str):
            raise ValueError(f"{field} must be a string")
    for field in ("transferability_basis", "citation_chain_basis"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError(f"{field} must be string or null")
    if decision == "TRANSFERABLE_MECHANISM" and not value["transferability_basis"]:
        raise ValueError("TRANSFERABLE_MECHANISM requires transferability_basis")
    if decision == "CITATION_CHAIN_CANDIDATE" and not value["citation_chain_basis"]:
        raise ValueError("CITATION_CHAIN_CANDIDATE requires citation_chain_basis")
    if value["confidence"] == "LOW" and decision != "UNCERTAIN":
        raise ValueError("LOW confidence must route to UNCERTAIN")
    if len(str(value["rationale"]).split()) > 150:
        raise ValueError("rationale exceeds 150 words")
    return value


def request_one(row: dict[str, str], *, api_key: str, base_url: str, model: str, system_prompt: str, timeout: int, max_retries: int, max_tokens: int, thinking: str) -> dict[str, object]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Screen this record and return exactly one JSON object.\n\n" + make_record_text(row)},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "thinking": {"type": thinking},
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_hash = sha256_bytes(payload_bytes)
    errors: list[str] = []
    attempts: list[dict[str, object]] = []
    started = datetime.now(timezone.utc).isoformat()
    for attempt in range(1, max_retries + 2):
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=payload_bytes,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "coldwatercoral-stage5-v5/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_bytes = response.read()
                response_json = json.loads(response_bytes.decode("utf-8", errors="replace"))
            content = response_json["choices"][0]["message"]["content"]
            parsed = validate_output(json.loads(content), row["corpus_id"])
            attempts.append({"attempt": attempt, "http_status": 200, "response_sha256": sha256_bytes(response_bytes)})
            return {"status": "succeeded", "calibration_record_id": row["calibration_record_id"], "corpus_id": row["corpus_id"], "attempts": attempt, "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "request_sha256": request_hash, "response_sha256": sha256_bytes(response_bytes), "provider_response": response_json, "parsed": parsed, "errors": errors, "attempt_audit": attempts}
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    detail = f"HTTPError {exc.code}: {exc.read(2000).decode('utf-8', errors='replace')}"
                except Exception:
                    pass
            errors.append(detail)
            attempts.append({"attempt": attempt, "error": detail})
            if attempt > max_retries:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    return {"status": "failed", "calibration_record_id": row["calibration_record_id"], "corpus_id": row["corpus_id"], "attempts": max_retries + 1, "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "request_sha256": request_hash, "response_sha256": "", "provider_response": None, "parsed": None, "errors": errors, "attempt_audit": attempts}


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["prompt_sha256"] != sha256_file(PROMPT) or freeze["model_input_sha256"] != sha256_file(INPUT):
        raise ValueError("Prompt or input hash differs from v5 freeze")
    if not args.dry_run and freeze.get("external_transfer_authorized") is not True:
        raise ValueError("External transfer authorization is not recorded")
    rows, columns = read_csv(INPUT)
    if len(rows) != 36 or len({row["calibration_record_id"] for row in rows}) != 36:
        raise ValueError("Expected 36 unique validation rows")
    if FORBIDDEN & set(columns):
        raise ValueError(f"Forbidden label columns in model input: {sorted(FORBIDDEN & set(columns))}")
    if any(row["split"] != "POSITIVE_ENRICHED_VALIDATION" for row in rows):
        raise ValueError("Unexpected input split")

    schema_text = SCHEMA.read_text(encoding="utf-8").strip()
    system_prompt = PROMPT.read_text(encoding="utf-8").split("## Record template", 1)[0].strip() + "\n\n## Required JSON schema\n\n" + schema_text + "\n\nReturn every required property exactly as named. Do not add properties."
    run_id = args.run_id or datetime.now(timezone.utc).strftime("positive-enriched-deepseek-v5-%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        raise ValueError(f"Run directory already exists: {run_dir}")
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "positive_enriched_validation_screening_v5",
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(INPUT.relative_to(ROOT)),
        "input_sha256": sha256_file(INPUT),
        "input_rows_selected": 36,
        "human_labels_loaded_for_requests": False,
        "prior_model_decisions_loaded_for_requests": False,
        "benchmark_key_loaded": False,
        "forbidden_columns_present": False,
        "access_metadata_included": True,
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256_file(PROMPT),
        "schema_file": str(SCHEMA.relative_to(ROOT)),
        "schema_sha256": sha256_file(SCHEMA),
        "parameters": {"temperature": 0, "max_tokens": args.max_tokens, "thinking": args.thinking, "response_format": "json_object", "workers": args.workers, "max_retries": args.max_retries, "timeout_seconds": args.timeout},
        "external_transfer_authorization": freeze["external_transfer_authorization_scope"],
        "status": "prepared" if args.dry_run else "running",
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (run_dir / "input_ids.txt").write_text("\n".join(row["calibration_record_id"] for row in rows) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(request_one, row, api_key=api_key, base_url=base_url, model=model, system_prompt=system_prompt, timeout=args.timeout, max_retries=args.max_retries, max_tokens=args.max_tokens, thinking=args.thinking): row for row in rows}
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            (response_dir / f"{result['calibration_record_id']}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            with PRINT_LOCK:
                succeeded = sum(result["status"] == "succeeded" for result in results)
                print(f"progress {completed}/36 succeeded={succeeded} failed={completed-succeeded}", flush=True)
    results.sort(key=lambda result: str(result["calibration_record_id"]))
    by_id = {row["calibration_record_id"]: row for row in rows}
    parsed_path = run_dir / "parsed_decisions.csv"
    fields = ["calibration_record_id"] + OUTPUT_FIELDS + ["access", "access_type", "access_url", "attempts", "request_sha256", "response_sha256"]
    with parsed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            if result["status"] != "succeeded":
                continue
            parsed = dict(result["parsed"])
            parsed["needs_full_text"] = str(parsed["needs_full_text"])
            source = by_id[str(result["calibration_record_id"])]
            writer.writerow({"calibration_record_id": result["calibration_record_id"], **parsed, "access": source["access"], "access_type": source["access_type"], "access_url": source["access_url"], "attempts": result["attempts"], "request_sha256": result["request_sha256"], "response_sha256": result["response_sha256"]})
    failures = [result for result in results if result["status"] != "succeeded"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for result in results:
        provider_usage = (result.get("provider_response") or {}).get("usage", {})
        for key in usage:
            usage[key] += int(provider_usage.get(key, 0) or 0)
    manifest.update({"completed_at": datetime.now(timezone.utc).isoformat(), "status": "completed" if not failures else "completed_with_failures", "succeeded_rows": len(results) - len(failures), "failed_rows": len(failures), "failed_calibration_record_ids": [result["calibration_record_id"] for result in failures], "usage": usage, "parsed_decisions_sha256": sha256_file(parsed_path)})
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "status": manifest["status"], "usage": usage}, indent=2))


if __name__ == "__main__":
    main()
