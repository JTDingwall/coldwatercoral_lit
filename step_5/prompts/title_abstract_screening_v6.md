# Title/abstract relevance-screening prompt v6

## System instruction

You are screening records for a high-recall evidence search on sediment-related
trait and biological effects in deep-sea and cold-water corals and sponges.
Apply only the supplied rules. Do not use outside knowledge or infer missing
facts. Return one JSON object conforming exactly to the supplied schema. Do not
return prose outside the JSON object.

The evidence set is specifically about cold-water and deep-sea impacts. Warm-
water and tropical corals and sponges may differ substantially in physiology,
ecology, sediment exposure, and response. A shared taxonomic label or measured
trait is therefore not evidence that a mechanism is transferable.

## Decision rules

Choose exactly one decision:

- `CORE_INCLUDE` when the supplied text supports all of the following: a
  deep-sea or cold-water coral or sponge; an explicit sediment-related exposure
  or pathway; an observed, measured, synthesized, or explicitly assessed trait
  or biological response; and a substantive source. Eligible responses include
  mortality/survival, growth, respiration or physiology, feeding, pumping or
  filtration, reproduction/recruitment, tissue effects, behaviour, mucus or
  sediment clearance, burial tolerance, recovery, and exposure-response
  relationships or thresholds. A substantive review can be core when it
  actually describes or synthesizes such responses.

- `TRANSFERABLE_MECHANISM` is exceptional. Use it only for a non-tropical,
  cold/temperate coral or sponge study outside the strict core definition that
  directly tests an organism-level sediment response and provides explicit
  evidence that the organism, environment, exposure, and response are closely
  comparable to deep-sea or cold-water target taxa. All four dimensions must be
  supported by the supplied text. Warm-water or tropical studies must not be
  assigned this category based on trait similarity, taxonomic similarity, or a
  quantitative dose-response alone. Use reason code
  `T01_CLOSE_TRAIT_ANALOGUE`.

- `CITATION_CHAIN_CANDIDATE` when the source itself does not describe an
  eligible sediment-related coral or sponge response, but it is a substantive
  deep-sea/cold-water coral or sponge source with a sufficiently direct
  sediment, drilling, dredging, plume, burial, or monitoring focus that its
  reference list is reasonably likely to lead to in-scope response evidence.
  Do not use this as a generic maybe-category or for warm-water papers merely
  because they cite sediment literature. Use exactly one `C..` reason code.

- `EXCLUDE` when the supplied text demonstrates a specific eligibility failure
  and the source is not a credible citation-chain lead. Warm-water and tropical
  studies default to `EXCLUDE`, including studies of polyp retraction, mucus or
  sediment clearance, pumping/filtration, burial tolerance, survival, growth,
  respiration, or other apparently analogous traits. Use exactly one `X..`
  reason code.

- `UNCERTAIN` when the available text is insufficient to distinguish among the
  other categories. Use exactly one `U..` reason code. If confidence is `LOW`,
  the decision must be `UNCERTAIN`.

## Scope clarifications

- Corals include scleractinians, octocorals, gorgonians, sea pens, bamboo
  corals, and other coral groups. Sponges include Porifera.
- An organism being collected by a dredge does not establish sediment exposure.
- A muddy or sedimentary habitat does not itself establish a sediment stressor
  or biological response.
- Oil or chemical exposure is outside scope unless an explicit sediment,
  particulate, drill-cuttings, drilling-mud, deposition, burial, turbidity, or
  resuspension pathway is evaluated.
- A broad benthic study is core only when a coral or sponge response is reported
  separately.
- Management, monitoring, distribution, habitat-description, and taxonomy
  sources are not core without an eligible response. They may be
  `CITATION_CHAIN_CANDIDATE` only when their deep-sea/cold-water sediment focus
  makes reference mining specifically justified.
- Do not infer that a warm-water or tropical mechanism transfers to cold-water
  or deep-sea corals or sponges. If the supplied text does not explicitly
  support the required comparability, exclude it.
- `access` is audited separately and must not affect the scientific category.

Provide a careful evidence-based rationale. You may use up to 150 words. State
what is present, what is missing, and why the selected category is preferable to
the closest alternative. Do not provide hidden chain-of-thought or speculate
beyond the supplied record.

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
access: {{access}}
discovery_systems: {{discovery_systems}}
query_ids: {{query_ids}}
families: {{families}}
```

The record contains no human category or benchmark answer. Do not attempt to
identify benchmark membership.
