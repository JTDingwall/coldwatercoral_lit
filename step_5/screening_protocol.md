# Stage 5 screening protocol, version 1

## Purpose

Screen the fixed Stage 4 candidate corpus for document-level relevance while
preserving recall, provenance, and a complete audit trail. The output is a
criteria-selected source list, not a scientific synthesis.

## Eligibility logic

Assign `CORE_INCLUDE` only when the available screening text supports all four
requirements:

1. **Organism:** coral or sponge. Broader benthic-community studies qualify only
   when coral or sponge findings are separately reported.
2. **Stressor:** sediment deposition, burial or smothering, suspended sediment,
   total suspended solids, turbidity, particle loading, drill cuttings, drilling
   mud/fluid/discharge, dredging, resuspension, sediment plumes, seabed disturbance
   with an explicit sediment pathway, or relevant mine tailings/disposal.
3. **Response:** mortality, survival, growth, respiration or other physiology,
   feeding, reproduction, recruitment, tissue damage, behaviour, sediment
   clearance, burial tolerance, recovery, population/community change, or an
   exposure-response relationship or threshold. Feeding mechanisms include mucus
   production, mucociliary feeding or clearing, feeding inhibition, energetic
   costs, filtration/pumping impairment, clogging, feeding-current arrest, and
   reduced food capture.
4. **Source:** a substantive peer-reviewed article, review, thesis/dissertation,
   government report, regulatory assessment, monitoring report, EIS/EA,
   operator/industry technical report, consultancy report, international
   scientific-body report, or substantive proceedings/conference material.

There is no geographic or date cutoff.

## Tropical and non-core evidence

Tropical studies are not part of the core evidence set. Assign
`TRANSFERABLE_MECHANISM` only when the available text explicitly identifies a
sediment-related mechanism, morphology-response relationship, physical burial
process, or exposure-response pattern with clear transferability to cold-water
corals or sponges. Otherwise assign `EXCLUDE` with
`X02_TROPICAL_NO_TRANSFER`. If transferability is plausible but not demonstrable
from the available text, assign `UNCERTAIN` with
`U05_AMBIGUOUS_TRANSFERABILITY`.

## Conservative decision rules

- Use only the supplied title, abstract/snippet, and bibliographic metadata.
- Do not infer unreported organisms, exposures, pathways, responses, climates, or
  study locations.
- Missing evidence is not evidence of exclusion. Use `UNCERTAIN` when a required
  dimension cannot be evaluated.
- `LOW` confidence is never compatible with a final include or exclude decision;
  route it to `UNCERTAIN`.
- Use one primary exclusion or uncertainty reason. Additional failed dimensions
  may be described in the rationale.
- Do not change Stage 4 metadata or deduplication.
- Never show benchmark type or expected decision to the screening model.

## Calibration design

`build_calibration_sample.py` selects 400 non-benchmark records using a fixed
SHA-256 ordering and coverage strata derived from discovery route, query family,
document type, metadata/full-text availability, and simple organism/stressor text
signals. It assigns 300 records to `DEVELOPMENT` and 100 to a locked `VALIDATION`
split. Nine benchmarks are placed in a separate blinded validation file.

A human reviewer independently labels the 400-record sample and the blinded
benchmark set before seeing model decisions. Prompt revisions may use only the
development split. After the prompt is frozen, the validation split is run once.

## Calibration acceptance gate

Production screening is blocked unless all of the following hold:

- every calibration input has one valid human label;
- every positive-core benchmark is `CORE_INCLUDE`;
- every tropical negative control is `EXCLUDE`;
- the Port of Miami benchmark is `TRANSFERABLE_MECHANISM`;
- `CORE_INCLUDE` recall on the locked validation set is at least 0.95;
- combined `CORE_INCLUDE` plus `TRANSFERABLE_MECHANISM` recall is at least 0.95;
- no known in-scope record is silently excluded;
- all low-confidence, malformed, or insufficient-information cases route to
  `UNCERTAIN`; and
- all input/output counts and identifiers reconcile.

Precision, specificity, negative predictive value, category agreement, and the
confusion matrix must also be reported. They inform prompt revision but do not
override the recall-first stop rules.

## Production plan after approval

Use the low-cost DeepSeek model configured through environment variables for the
first structured pass. A stronger configured model may review uncertain records,
conflicts, and a reproducible QA sample. Save raw responses, parsed decisions,
model/provider identifiers, prompt version, parameters, dates, batch IDs, retry
history, and response hashes. Never store API keys.

## Stop boundary

Stage 5 ends with document categories, reasons, QA, and a reproducible selected
source list. Do not extract study results, interpret evidence, synthesize claims,
code traits, estimate thresholds, or score vulnerability.
