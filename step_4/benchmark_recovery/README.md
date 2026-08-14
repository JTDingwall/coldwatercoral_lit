# Positive benchmark recovery

This folder records the post-discovery check of the frozen benchmark set against
the final candidate corpus. The benchmark file was not used to seed production
searches or citation chaining.

- `benchmark_recovery.csv`: one result per frozen benchmark, with exact match
  basis and independent discovery provenance.
- `benchmark_miss_diagnostics.csv`: closest-title diagnostics for every miss;
  fuzzy similarity never counts as recovery.
- `benchmark_recovery_qa.json`: recovery totals and structural QA checks.
- `remediation_search_results.csv`: the documented `_02` USGS search results.
- `remediation_search_summary.json`: remediation query settings and outcome.
- `remediation_extract_validation.json`: validation of the frozen USGS URL
  without storing or reproducing the page text.
- `remediation_candidate.csv`: the explicitly labeled post-benchmark record.

Rebuild with:

```bash
python step_4/check_benchmark_recovery.py
```

Automatic recovery requires an exact normalized DOI, canonical URL, resolved
identifier alias, or normalized title. The check does not perform relevance
screening. Sources recovered only through a benchmark-driven `_02` search are
reported as `RECOVERED_AFTER_REMEDIATION`, never as initial independent recovery.
