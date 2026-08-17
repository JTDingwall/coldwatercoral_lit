# Candidate corpus

This folder contains the Stage 4 merged and deduplicated candidate corpus. It is a
discovery product, not a screened evidence set.

Files:

- `candidate_corpus.csv`: one row per unique candidate source.
- `candidate_corpus_provenance.csv`: one row per original search occurrence, linked
  to `corpus_id`; this preserves every system, query ID, family, and source record.
- `fuzzy_review.csv`: all fuzzy title/author pairs considered and the deterministic
  merge-or-keep decision with similarity values and rationale.
- `identifier_conflicts.csv`: records that otherwise matched but had conflicting
  non-empty DOI values; these were conservatively kept separate.
- `corpus_qa.json`: source counts, reconciliation totals, full-text status counts,
  and validation checks.

Rebuild from the raw Step 4 exports with:

```bash
python step_4/build_candidate_corpus.py
```

Deduplication proceeds in order by normalized DOI, exact normalized title with a
compatible year, canonical URL, and then a conservative fuzzy title/first-author
comparison. Different non-empty DOI values block a merge. Ambiguous fuzzy pairs are
kept separate. Full-text fields distinguish repository-archived documents,
open-access PDFs, open-access landing pages, likely full-document web URLs, and
records for which full text has not yet been identified.

No benchmark matching, citation chaining, or relevance screening is performed here.
