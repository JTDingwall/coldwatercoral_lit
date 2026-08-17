# Positive-enriched validation review

Review all 36 records independently using only the title, screening text, and
bibliographic metadata in `positive_enriched_validation_review.csv`.

Fill in only:

- `final_category`: choose exactly one of `CORE_INCLUDE`,
  `TRANSFERABLE_MECHANISM`, `UNCERTAIN`, or `EXCLUDE`.
- `reviewer_note`: give a brief reason grounded in the supplied record.

Use `CORE_INCLUDE` only for substantive cold-, deep-, or temperate-water coral or
sponge evidence with an explicit sediment-related stressor and eligible response.
Use `TRANSFERABLE_MECHANISM` for non-core evidence that explicitly links a
sediment exposure to a transferable physical, physiological, morphology,
biological-impact, or exposure-response pattern. Use `UNCERTAIN` when the
available text is insufficient or ambiguous. Use `EXCLUDE` only when an
eligibility failure is demonstrated.

Do not alter record identifiers, titles, screening text, or metadata. Save the
completed file as `positive_enriched_validation_review_COMPLETED.csv`.

The selection provenance is stored separately and should not be used while
assigning labels. Model screening must not begin until every human category and
note is complete and the transfer of these records to the configured API is
separately authorized.
