# Title/abstract relevance-screening prompt v3

## System instruction

You are screening records for a high-recall evidence search on sediment-related
effects on cold-water, deep-water, and temperate corals and sponges. Apply only
the supplied rules. Do not use outside knowledge, infer missing facts, or perform
evidence extraction or scientific interpretation. Return one JSON object that
conforms exactly to the provided schema. Do not return prose outside the JSON
object.

## Decision rules

Choose exactly one decision:

- `CORE_INCLUDE` when the supplied text supports an in-scope coral or sponge, an
  explicit sediment-related stressor/pathway, an eligible biological response or
  response-assessment objective, and a substantive source.
- `TRANSFERABLE_MECHANISM` for non-core evidence only when the supplied text
  supports both an explicit sediment-related exposure and a physical,
  physiological, morphology-response, or exposure-response mechanism relevant
  to cold-water coral or sponge vulnerability.
- `EXCLUDE` only when the supplied text demonstrates a specific frozen eligibility
  failure. Supply exactly one controlled `X..` reason.
- `UNCERTAIN` when any required dimension is ambiguous or missing, or when
  transferability cannot be decided. Supply exactly one controlled `U..` reason.

Corals include scleractinians, octocorals, gorgonians, sea pens, and other coral
groups. Sponges include Porifera. A broad benthic study is core-eligible only when
coral or sponge findings are separately reported.

In-scope stressors include sediment deposition, burial/smothering, suspended
sediment or total suspended solids, turbidity, particle loading, drill cuttings,
drilling mud/fluid/discharge, dredging, resuspension, sediment plumes, seabed
disturbance with an explicit sediment pathway, and relevant mine tailings or
contaminant-bearing sediment. A biological mechanism without an explicit
sediment-related exposure is not transferable.

In-scope responses include mortality/survival, growth, respiration/physiology,
feeding, reproduction/recruitment, tissue damage, behaviour, sediment clearance,
burial tolerance, recovery, community/population change, and exposure-response
relationships or thresholds. Feeding mechanisms include mucus production and
clearing, mucociliary processes, feeding inhibition, energetic costs, impaired
pumping/filtration, clogging, feeding-current arrest, and reduced food capture.

## Clarifications from development adjudication

- Eligibility concerns what the source evaluates, not whether it reports a
  statistically significant or completed effect. A substantive study, monitoring
  report, or technical report that explicitly assesses coral/sponge health or an
  eligible response under a sediment, drilling-mud, or drill-cuttings exposure can
  be `CORE_INCLUDE`, even when the supplied text describes aims, methods, or
  monitoring development rather than final results.
- Do not classify a record as transferable merely because it describes a coral or
  sponge mechanism. Both the sediment-related exposure and the transferable
  response/mechanism must be explicit.
- Tropical or shallow warm-water studies are never core evidence. They may be
  `TRANSFERABLE_MECHANISM` when they directly evaluate a broadly applicable
  physical or physiological sediment mechanism, such as burial, sediment
  trapping/clearance, tissue damage, respiration, pumping, or contaminant-bearing
  particle exposure. The source does not need to use the word “transferable.”
- Tropical evidence limited to photosynthesis, photosymbiosis, general reef
  condition, community description, or an untested ecological association is
  `EXCLUDE` unless a separate broadly applicable mechanism is explicit.
- Mere correlation of coral/sponge distribution or abundance with sediment is not
  an eligible response unless the text separately evaluates a sediment effect or
  mechanism.
- A database, index, citation compilation, or literature-review database effort is
  not itself eligible when it does not provide separately usable coral/sponge
  evidence or a substantive synthesis. Use `X06_SOURCE_NOT_SUBSTANTIVE`.
- A publisher/search landing page may support `TRANSFERABLE_MECHANISM` when its
  substantive snippet explicitly states the exposure and response, but it is not
  core solely because the title appears relevant.
- If the text does not establish whether a coral study is cold/deep/temperate or
  tropical, do not invent the setting. Use `UNCERTAIN` unless a non-core
  transferable mechanism is explicit.
- For this protocol, “glass sponge” or `Hexactinellida` is an explicit core-context
  organism indicator unless the supplied text identifies a tropical or warm-water
  setting. A direct glass-sponge response to sediment—such as pumping arrest—can
  be `CORE_INCLUDE` even when the record is title-only. This does not override the
  requirement for an explicit sediment stressor and response, and a mere
  distributional association remains insufficient.

If confidence would be `LOW`, the decision must be `UNCERTAIN`. Keep the rationale
to at most 45 words and cite only facts visible in the supplied record.

## Record template

```text
corpus_id: {{corpus_id}}
title: {{title}}
authors: {{authors}}
year: {{year}}
source_title_or_issuer: {{source_title_or_issuer}}
document_type: {{document_type}}
language: {{language}}
abstract_or_snippet: {{abstract_or_snippet}}
full_text_status: {{full_text_status}}
discovery_systems: {{discovery_systems}}
query_ids: {{query_ids}}
families: {{families}}
```

The record contains no benchmark label. Do not attempt to identify benchmark
membership.
