# Grey-literature production searches

Grey-literature discovery uses the same eight conceptual families as the frozen
Web of Science searches, translated into shorter web-search expressions. There
is no date cutoff.

The workflow has two ordered phases:

1. two unrestricted public-web queries per conceptual family, emphasizing reports,
   technical documents, monitoring reports, assessments, theses, dissertations,
   proceedings, regulatory submissions, and operator reports; and
2. the same eight families searched within each active institutional target in
   `grey_institutional_targets.csv`.

The initial agreed targets are Fisheries and Oceans Canada, C-NLOER (including
the legacy C-NLOPB domain), the Impact Assessment Agency of Canada, Norwegian
regulatory and marine-research repositories, OSPAR, and ICES. Any institution or
report series added after inspecting the broad-web results must first be added
to the target manifest with its discovery basis, and only then searched.

The first broad pass surfaced additional relevant institutional sources. NOAA,
USGS, Canada's Environmental Studies Research Fund, offshore operator public
report portals, FAO, AIMS, the UK JNCC/NERC repositories, MBARI, and the UN
World Ocean Assessment were recorded in both the target manifest and the search
log before targeted searching.

Tavily Search API performs retrieval with advanced search depth and up to 20
results per query. Results remain separate by query ID and are neither screened
nor deduplicated at this stage. DeepSeek adds only unverified descriptive
metadata (document type, issuing organization, apparent year/language, and
whether the hit appears to be a full document). Model output is not treated as
source evidence and does not control retention.

Direct source-document archiving is conservative. The candidate ledger retains
all URLs, while `documents/` contains only official U.S. federal reports from
this search for which public electronic distribution is clear. The document
manifest records source URLs, discovery queries, and SHA-256 checksums. Other
candidate documents remain linked rather than rehosted until sharing rights are
confirmed.

Run from the repository root, supplying a local credential file that is outside
the repository:

```bash
python step_4/run_grey_literature_searches.py broad --env-file /path/to/.env.md
python step_4/run_grey_literature_searches.py discover-domains
# Record justified institutional additions in grey_institutional_targets.csv.
python step_4/run_grey_literature_searches.py targeted --env-file /path/to/.env.md
python step_4/run_grey_literature_searches.py enrich --env-file /path/to/.env.md
python step_4/run_grey_literature_searches.py update-log
python step_4/run_grey_literature_searches.py qa
```

The credential file must never be copied into or committed to this repository.
