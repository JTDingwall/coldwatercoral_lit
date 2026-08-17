# Citation chaining

This folder contains the two-generation OpenAlex citation-chain outputs. The
benchmark file was not used to choose seeds.

- `seed_manifest.csv`: frozen generation-0 sources and the objective seed basis.
- `citation_edges.csv`: parent–child provenance for backward references, forward
  citations, and related works.
- `citation_candidates.csv`: normalized metadata for every discovered work.
- `citation_chain_qa.json`: route counts, generation counts, API usage, and QA.

Rebuild with:

```bash
python step_4/run_citation_chaining.py --max-generation 2
python step_4/build_candidate_corpus.py
```

The runner keeps an exact generation-1 edge checkpoint if interrupted and
removes it after successful QA. Bibliographic metadata is fetched in bounded,
rate-limited batches; detailed parent-child provenance remains in the edge table.

Primary seeds explicitly mention an in-scope organism and sediment-related
stressor or mechanism in the title and were recovered by at least two systems or
at least three search occurrences. Generation-2 seeds must meet the same title
rule and have at least two parent sources or two discovery routes. This is a
discovery-prioritization rule, not relevance screening.
