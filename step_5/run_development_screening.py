#!/usr/bin/env python3
"""Run DeepSeek title/abstract screening on the 300-record development split.

The locked validation split and benchmark files are never loaded by this script.
Raw provider responses, parsed outputs, request hashes, usage, retries, and a
redacted manifest are retained for auditability. API keys are never written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION = ROOT / "step_5" / "calibration" / "calibration_sample.csv"
DEFAULT_PROMPT_PATH = ROOT / "step_5" / "prompts" / "title_abstract_screening_v1.md"
SCHEMA_PATH = ROOT / "step_5" / "schemas" / "screening_output.schema.json"
DEFAULT_RUNS_DIR = ROOT / "step_5" / "runs"

VALID_DECISIONS = {
    "CORE_INCLUDE",
    "TRANSFERABLE_MECHANISM",
    "EXCLUDE",
    "UNCERTAIN",
}
VALID_REASONS = {
    None,
    "X01_ORGANISM_OUT_OF_SCOPE",
    "X02_TROPICAL_NO_TRANSFER",
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
    "screening_source",
    "confidence",
    "needs_full_text",
    "rationale",
]
PRINT_LOCK = threading.Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_env_file(path: Path | None) -> None:
    if not path:
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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
        ("discovery_systems", row["discovery_systems"]),
        ("query_ids", row["query_ids"]),
        ("families", row["families"]),
    ]
    return "\n".join(f"{name}: {value}" for name, value in fields)


def validate_output(value: object, expected_corpus_id: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Response is not a JSON object")
    extra = set(value) - set(OUTPUT_FIELDS)
    missing = set(OUTPUT_FIELDS) - set(value)
    if extra or missing:
        raise ValueError(f"Schema keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    if value["corpus_id"] != expected_corpus_id:
        raise ValueError("corpus_id does not match request")
    if value["decision"] not in VALID_DECISIONS:
        raise ValueError("invalid decision")
    if value["reason_code"] not in VALID_REASONS:
        raise ValueError("invalid reason_code")
    if value["screening_source"] not in VALID_SOURCES:
        raise ValueError("invalid screening_source")
    if value["confidence"] not in VALID_CONFIDENCE:
        raise ValueError("invalid confidence")
    if not isinstance(value["needs_full_text"], bool):
        raise ValueError("needs_full_text must be boolean")
    for field in ("organism_evidence", "stressor_evidence", "response_evidence", "rationale"):
        if not isinstance(value[field], str):
            raise ValueError(f"{field} must be a string")
    if value["transferability_basis"] is not None and not isinstance(value["transferability_basis"], str):
        raise ValueError("transferability_basis must be string or null")
    if value["decision"] == "EXCLUDE" and not str(value["reason_code"]).startswith("X"):
        raise ValueError("EXCLUDE requires an X reason")
    if value["decision"] == "UNCERTAIN" and not str(value["reason_code"]).startswith("U"):
        raise ValueError("UNCERTAIN requires a U reason")
    if value["confidence"] == "LOW" and value["decision"] != "UNCERTAIN":
        raise ValueError("LOW confidence must route to UNCERTAIN")
    if len(value["rationale"].split()) > 45:
        raise ValueError("rationale exceeds 45 words")
    return value


def endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def request_one(
    row: dict[str, str],
    *,
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    timeout: int,
    max_retries: int,
) -> dict[str, object]:
    record_text = make_record_text(row)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Screen this record and return exactly one JSON object.\n\n" + record_text,
            },
        ],
        "temperature": 0,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_hash = sha256_bytes(payload_bytes)
    errors: list[str] = []
    attempt_audit: list[dict[str, object]] = []
    started = datetime.now(timezone.utc).isoformat()
    for attempt in range(1, max_retries + 2):
        req = urllib.request.Request(
            endpoint(base_url),
            data=payload_bytes,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "coldwatercoral-stage5/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_bytes = response.read()
                response_text = response_bytes.decode("utf-8", errors="replace")
                attempt_audit.append(
                    {
                        "attempt": attempt,
                        "http_status": response.status,
                        "response_sha256": sha256_bytes(response_bytes),
                        "response_text": response_text,
                    }
                )
                response_json = json.loads(response_text)
            content = response_json["choices"][0]["message"]["content"]
            parsed = validate_output(json.loads(content), row["corpus_id"])
            return {
                "status": "succeeded",
                "calibration_record_id": row["calibration_record_id"],
                "corpus_id": row["corpus_id"],
                "attempts": attempt,
                "started_at": started,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "request_sha256": request_hash,
                "response_sha256": sha256_bytes(response_bytes),
                "provider_response": response_json,
                "parsed": parsed,
                "errors": errors,
                "attempt_audit": attempt_audit,
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    body = exc.read(2000).decode("utf-8", errors="replace")
                    detail = f"HTTPError {exc.code}: {body}"
                except Exception:
                    pass
            errors.append(detail)
            if attempt > max_retries:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    return {
        "status": "failed",
        "calibration_record_id": row["calibration_record_id"],
        "corpus_id": row["corpus_id"],
        "attempts": max_retries + 1,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "request_sha256": request_hash,
        "response_sha256": "",
        "provider_response": None,
        "parsed": None,
        "errors": errors,
        "attempt_audit": attempt_audit,
    }


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.environ.get("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    if not api_key and not args.dry_run:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")

    all_rows = read_csv(CALIBRATION)
    rows = [row for row in all_rows if row["split"] == "DEVELOPMENT"]
    if len(rows) != 300:
        raise ValueError(f"Expected exactly 300 development rows; found {len(rows)}")
    if any(row["split"] != "DEVELOPMENT" for row in rows):
        raise ValueError("Non-development row reached model input")
    if args.ids_file:
        requested_ids = {
            value.strip()
            for value in args.ids_file.read_text(encoding="utf-8").splitlines()
            if value.strip()
        }
        available_ids = {row["calibration_record_id"] for row in rows}
        unknown_ids = requested_ids - available_ids
        if unknown_ids:
            raise ValueError(f"Requested IDs are outside development split: {sorted(unknown_ids)}")
        rows = [row for row in rows if row["calibration_record_id"] in requested_ids]
    if args.limit is not None:
        rows = rows[: args.limit]

    prompt_path = args.prompt.resolve()
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8").strip()
    system_prompt = (
        prompt_path.read_text(encoding="utf-8").split("## Record template", 1)[0].strip()
        + "\n\n## Required JSON schema\n\n"
        + schema_text
        + "\n\nReturn every required property exactly as named. Do not add properties."
    )
    run_id = args.run_id or datetime.now(timezone.utc).strftime("dev-deepseek-%Y%m%dT%H%M%SZ")
    run_dir = args.runs_dir / run_id
    response_dir = run_dir / "responses"
    response_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "development_screening",
        "provider": "DeepSeek",
        "base_url": base_url,
        "model": model,
        "api_key_written": False,
        "input_file": str(CALIBRATION.relative_to(ROOT)),
        "input_sha256": sha256_file(CALIBRATION),
        "input_split": "DEVELOPMENT",
        "input_rows_available": 300,
        "input_rows_selected": len(rows),
        "validation_rows_loaded": 0,
        "benchmark_rows_loaded": 0,
        "benchmark_key_loaded": False,
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256_file(prompt_path),
        "schema_file": str(SCHEMA_PATH.relative_to(ROOT)),
        "schema_sha256": sha256_file(SCHEMA_PATH),
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

    if args.dry_run:
        (run_dir / "input_ids.txt").write_text(
            "\n".join(row["calibration_record_id"] for row in rows) + "\n",
            encoding="utf-8",
        )
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
            response_path = response_dir / f"{result['calibration_record_id']}.json"
            response_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            completed += 1
            if completed == 1 or completed % 25 == 0 or completed == len(rows):
                with PRINT_LOCK:
                    succeeded = sum(item["status"] == "succeeded" for item in results)
                    print(f"progress {completed}/{len(rows)} succeeded={succeeded} failed={completed-succeeded}", flush=True)

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
            "failed_calibration_record_ids": [result["calibration_record_id"] for result in failures],
            "usage": usage,
            "parsed_decisions_sha256": sha256_file(parsed_path),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_dir": str(run_dir),
        "status": manifest["status"],
        "succeeded_rows": manifest["succeeded_rows"],
        "failed_rows": manifest["failed_rows"],
        "usage": usage,
    }, indent=2))


if __name__ == "__main__":
    main()
