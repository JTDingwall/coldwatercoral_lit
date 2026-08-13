# OpenAlex production queries

OpenAlex translations of the eight frozen Web of Science conceptual families in
`wos_production_queries.md`. Searches have no date cutoff and use the default
OpenAlex core corpus.

The Web of Science `TS=` logic is translated to OpenAlex's stemmed
`title_and_abstract.search` field. This searches titles and abstracts without
adding OpenAlex full text, which would substantially broaden the frozen
conceptual families. OpenAlex stemming supplies the plural and inflected forms
represented by `*` in the Web of Science queries. Exact multi-word phrases and
Boolean structure are retained. The WoS `NEAR/10` response query is translated
as Boolean co-occurrence because OpenAlex does not offer an exact field-scoped
equivalent of the WoS proximity operator.

The exact executable query strings are defined in `run_openalex.py`. Run from
the repository root:

```bash
python step_4/run_openalex.py
```

The script saves one complete UTF-8 CSV per family in `step_4/openalex/` and
retains the family/query ID on every row. It does not deduplicate across
families or perform relevance screening.

Production searches were run on 2026-08-13. Retrieval QA confirmed that every
file's parsed row count matched the OpenAlex API count and that OpenAlex IDs
were unique within each family. The Larsson & Purser (2011), Allers et al.
(2013), and Purser (2015) positive benchmarks were independently recovered.
Bell et al. (2015) was not returned because its OpenAlex record has no abstract
and its title does not contain the more specific stressor/mechanism terms in
the frozen families; it remains protected in `benchmark_sources.csv`.

## Query IDs

- `OA_SED_SUSPENDED_01`
- `OA_SED_DEPOSITION_01`
- `OA_SED_DRILLING_01`
- `OA_SED_DREDGING_01`
- `OA_SED_TAILINGS_01`
- `OA_MECH_FEEDING_MUCUS_CORAL_01`
- `OA_MECH_FEEDING_PUMPING_SPONGE_01`
- `OA_RESP_THRESHOLD_RECOVERY_01`

The retired broad `SED_GENERAL` family is not searched.
