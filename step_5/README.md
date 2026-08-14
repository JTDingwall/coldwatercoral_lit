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

The production AI run must not begin until the human labels are complete and the
calibration gate is approved. The AI screening runner must never load
`benchmark_key.csv` or benchmark types.

## Protocol files

- `screening_protocol.md`: frozen decision logic, validation plan, and stop rules.
- `prompts/title_abstract_screening_v1.md`: versioned title/abstract prompt.
- `schemas/screening_output.schema.json`: required structured output contract.
- `input_manifest.json`: frozen Stage 4 lineage.

Use GitHub issue #8 as the sequenced Stage 5 tracker.
