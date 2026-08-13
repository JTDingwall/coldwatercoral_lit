# Semantic Scholar production searches

The eight frozen Step 3 conceptual families were translated to the Semantic Scholar Academic Graph API and searched on 2026-08-13. Searches used the bulk paper-search endpoint with no date, publication-type, open-access, citation-count, venue, or field-of-study filters.

## Results

| Query ID | Family | Retrieved records | Output |
|---|---|---:|---|
| `SS_SED_SUSPENDED_01` | `SED_SUSPENDED` | 2,143 | `semantic_scholar/SS_SED_SUSPENDED_01.csv` |
| `SS_SED_DEPOSITION_01` | `SED_DEPOSITION` | 1,490 | `semantic_scholar/SS_SED_DEPOSITION_01.csv` |
| `SS_SED_DRILLING_01` | `SED_DRILLING` | 72 | `semantic_scholar/SS_SED_DRILLING_01.csv` |
| `SS_SED_DREDGING_01` | `SED_DREDGING` | 1,064 | `semantic_scholar/SS_SED_DREDGING_01.csv` |
| `SS_SED_TAILINGS_01` | `SED_TAILINGS` | 75 | `semantic_scholar/SS_SED_TAILINGS_01.csv` |
| `SS_MECH_FEEDING_MUCUS_CORAL_01` | `MECH_FEEDING_MUCUS_CORAL` | 715 | `semantic_scholar/SS_MECH_FEEDING_MUCUS_CORAL_01.csv` |
| `SS_MECH_FEEDING_PUMPING_SPONGE_01` | `MECH_FEEDING_PUMPING_SPONGE` | 20 | `semantic_scholar/SS_MECH_FEEDING_PUMPING_SPONGE_01.csv` |
| `SS_RESP_THRESHOLD_RECOVERY_01` | `RESP_THRESHOLD_RECOVERY` | 794 | `semantic_scholar/SS_RESP_THRESHOLD_RECOVERY_01.csv` |

The API's reported total equalled the number of records retrieved for every family. Results remain separate by family; no screening or cross-family deduplication was performed.

## Database-specific translation

- Semantic Scholar bulk search matches terms against titles and abstracts. It does not reproduce the wider Web of Science `TS=` field set.
- Web of Science `AND` and `OR` operators were translated to Semantic Scholar `+` and `|`. Parentheses, quoted phrases, and prefix wildcards were retained.
- The Web of Science `NEAR/10` relationship in `RESP_THRESHOLD_RECOVERY` cannot be applied between two synonym groups in Semantic Scholar. It was translated to a document-level `AND` between the sediment-exposure and response groups to retain high recall. This broader relationship accounts for much of the larger Semantic Scholar result set for that family.
- The exact expanded API query for every family is stored in `semantic_scholar/semantic_scholar_search_summary.json` and in `run_semantic_scholar_searches.py`.

## Reproduction

Run from the repository root:

```bash
python3 step_4/run_semantic_scholar_searches.py
```

The script uses the public bulk endpoint and accepts an optional `S2_API_KEY` environment variable. It writes UTF-8 CSV files containing query provenance, Semantic Scholar identifiers, bibliographic metadata, external identifiers, citation counts, open-access links, fields of study, and abstracts where available.

