# Step 5: AI relevance screening

Stage 5 converts the frozen Stage 4 discovery corpus into a relevance-screened
source list. It does not extract evidence, interpret findings, synthesize claims,
code traits, estimate thresholds, or score vulnerability.

## Frozen input

The authoritative input is commit
`9fcb4f3834cbb15c43ac8a1f23dab6142e68185d`:

- 43,307 unique candidate records;
- 58,398 occurrence-level provenance rows; and
- nine benchmark records with frozen expected screening categories.

The Stage 4 corpus and provenance files remain unchanged. See
`input_manifest.json` for paths, Git blob identifiers, expected counts, and QA
requirements.

## Screening categories

- `CORE_INCLUDE`: directly relevant cold-water coral or sponge evidence, or a
  broader benthic-community study that reports an in-scope coral or sponge result
  separately.
- `TRANSFERABLE_MECHANISM`: non-core evidence with an explicit, clearly relevant
  mechanism, morphology-response relationship, or exposure-response pattern that
  can inform cold-water coral or sponge vulnerability.
- `EXCLUDE`: the record is demonstrably outside the frozen scope.
- `UNCERTAIN`: available metadata is insufficient for a defensible decision.

The controlled exclusion reasons are defined in
`controlled_vocabulary.csv`. `UNCERTAIN` is required when evidence is missing or
ambiguous; it is not a soft exclusion.

## Calibration gate

Run:

```bash
python step_5/build_calibration_sample.py
```

This creates:

- `calibration/calibration_sample.csv`: 400 non-benchmark records, split into
  300 development and 100 locked validation records;
- `calibration/human_labels.csv`: the independent human-review template;
- `calibration/benchmark_validation_blinded.csv`: nine benchmarks without their
  expected decisions;
- `calibration/benchmark_key.csv`: the separately stored benchmark answer key;
  and
- `calibration/calibration_qa.json`: reproducibility and coverage checks.
- `calibration/stage5_human_calibration_review.xlsx`: formatted reviewer workbook
  containing the calibration and blinded-benchmark sheets, dropdown controls,
  progress counts, instructions, and the controlled vocabulary. The answer key is
  intentionally omitted.
- `calibration/stage5_covidence_calibration.ris`: Covidence-ready RIS containing
  all 400 calibration records and nine blinded benchmarks in a deterministic
  shuffled order. Expected decisions, benchmark types, and split labels are
  intentionally omitted; `corpus_id` is retained as the accession number for
  reconciliation after screening.

Regenerate the Covidence import with:

```bash
python step_5/export_calibration_ris.py
```

The production AI run must not begin until the human labels are complete and the
calibration gate is approved. The AI screening runner must never load
`benchmark_key.csv` or benchmark types.

## Completed human calibration reconciliation

The corrected Covidence export and 15-record reviewer follow-up are reconciled
with:

```bash
python step_5/reconcile_human_labels.py \
  --covidence /path/to/Covidence_calibration_407_with_decisions.csv \
  --followup-json /path/to/final_followup_rows.json
```

The command creates resolved 400-record human labels, resolved 9-record blinded
benchmark labels, a combined 409-record label file, an adjudication log, a
human-label QA report, and a separate benchmark comparison. It does not change
the reviewer's decisions. Benchmark disagreements are surfaced for protocol or
benchmark review.

The four high-priority CSAS references not found in frozen Stage 4 are documented
and retained as a separate supplementary layer by:

```bash
python step_5/adjudicate_csas_priority.py
```

## Development-only DeepSeek run

Prepare a no-network dry run:

```bash
python step_5/run_development_screening.py \
  --env-file /path/to/.env.md \
  --dry-run
```

After explicitly authorizing transfer of the 300 development records' titles,
abstracts/snippets, and bibliographic metadata to the configured DeepSeek API,
run:

```bash
python step_5/run_development_screening.py \
  --env-file /path/to/.env.md
```

The runner asserts a 300-record `DEVELOPMENT` input, never loads the 100 locked
validation records or any benchmark file, and saves redacted manifests, raw
responses, parsed decisions, usage, retries, and hashes under `step_5/runs/`.

Evaluate a completed development run with:

```bash
python step_5/evaluate_development_screening.py \
  --predictions step_5/runs/<run-id>/parsed_decisions.csv
```

## Approved benchmark adjudication

After the development prompt was frozen, apply the approved B004/B005 benchmark
decisions with:

```bash
python step_5/adjudicate_benchmarks.py
```

This preserves the original benchmark artifacts and writes separately named
adjudicated versions. B004 is categorized as `TRANSFERABLE_MECHANISM`. The B005
USGS project-news webpage is retired as `EXCLUDE` and replaced by the substantive
Baussant et al. (2018) drill-cuttings exposure study (`CWC-B27727ED4386`, DOI
`10.1080/15287394.2018.1444375`) as `CORE_INCLUDE`. The replacement is present in
the frozen Stage 4 corpus and does not overlap the 400 calibration records.

`calibration/benchmark_adjudication_qa.json` must report `PASS` before locked
validation. Sending the 100 locked validation records to an external API requires
separate explicit authorization; the development-set authorization does not cover
that transfer.

## Locked validation result

The authorized one-time locked validation run completed on 2026-08-17 using
frozen prompt v3. All 100 records produced valid responses, no relevant record
was excluded, and the preregistered point-estimate recall gate passed. The
validation sample contained only one human-labelled relevant record, however,
so production remains on hold. The next QA step is to run the same frozen prompt
on the separately blinded nine-record benchmark set after explicit authorization
and resolve the ten material validation-label disagreements without revising the
prompt.

The authorized benchmark run subsequently completed with nine valid responses
and no leakage of the answer key. It recovered all four core benchmarks but
failed the benchmark gate: combined core-or-transferable recall was 4/6, one
expected transferable benchmark was excluded, and only two of three tropical
negative controls were excluded. Production therefore remains blocked pending
adjudication of the three benchmark conflicts and a new independent,
positive-enriched validation set.

## Post-run benchmark adjudication and prompt v4

The three approved post-run adjudications preserve the historical run and reduce
the unresolved result to one genuine false negative: the Port of Miami
dredging-impact study. The title-only Bell et al. sponge benchmark is treated as
`UNCERTAIN` for the exact input the model saw, with an abstract-enriched
replacement retained as an untested candidate. The Fabricius runoff review is
`TRANSFERABLE_MECHANISM` under the current protocol.

Prompt v4 is a draft, not a frozen or validated production prompt. A fresh
36-record validation packet contains 24 unused CSAS-priority records and 12
deterministically selected high-signal challenge records. It has zero overlap
with the 400 calibration records or nine historical benchmarks. Human labels and
separate API-transfer authorization are required before any v4 model run.

The authorized prompt-v4 run completed on 2026-08-17 with 36 valid responses
and no failures. It did not pass: core recall was 80.0%, combined core-or-
transferable recall was 88.2%, and one human-labelled relevant record was
classified `EXCLUDE`. Production remains blocked. Eleven priority disagreements
require human adjudication before any further prompt revision or production run.

Do not run the locked validation split until the development prompt has been
reviewed and frozen. Do not run production screening until the full acceptance
gate in `screening_protocol.md` is satisfied.

## Protocol files

- `screening_protocol.md`: frozen decision logic, validation plan, and stop rules.
- `prompts/title_abstract_screening_v1.md`: versioned title/abstract prompt.
- `schemas/screening_output.schema.json`: required structured output contract.
- `input_manifest.json`: frozen Stage 4 lineage.

Use GitHub issue #8 as the sequenced Stage 5 tracker.
