# Step 4

Shared workspace for production literature searches.

Folders:
- `wos/`
- `openalex/`
- `semantic_scholar/`
- `crossref/`
- `grey/`
- `documents/`

Files:
- `benchmark_sources.csv`
- `search_log.csv`
- `wos_production_queries.md`
- `openalex_production_queries.md`
- `run_openalex.py`
- `semantic_scholar_queries.md`
- `run_semantic_scholar_searches.py`
- `run_crossref_resolution.py`

Crossref is used only to resolve missing DOI and publication metadata for
unresolved records present in the frozen Web of Science production exports.
Before querying, exact normalized title/year matches are checked across Web of
Science, OpenAlex, and Semantic Scholar so Crossref is called only when none of
the systems supplies a DOI. It is not used as an additional discovery search.
Automatic DOI assignments are limited to conservative title/year/author
matches; uncertain matches stay flagged for review in
`crossref/crossref_resolutions.csv`.

Use the GitHub issue `Step 4 production search tracker` as the sequenced checklist.
