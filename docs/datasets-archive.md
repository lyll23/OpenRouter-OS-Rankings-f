# Public OpenRouter Datasets archive

Source: OpenRouter, https://openrouter.ai/apps and https://openrouter.ai/rankings, as of the `meta.as_of` value in each response. Dataset content is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This collection adds no private account usage or individual sessions.

## Coverage

The independent `collect-datasets.yml` workflow uses the existing `OPENROUTER_API_KEY` Actions secret. It does not change the original dashboard or `refresh.yml`.

* `app-rankings`: one UTC source day per request, from 2025-01-01 through yesterday. Both `popular` and `trending`, each with unfiltered scope, four category groups, and fifteen documented subcategories (40 slices/day). Filters are independent, not a Cartesian product. Hidden/private apps are excluded by OpenRouter; related aliases are merged upstream. Trending is **absolute excess growth** against three preceding equally sized periods, not percentage growth. Daily observations are not whole-market traffic. Provider tokenizers differ.
* `rankings-daily`: overall plus five modality and five context-bucket slices at daily period; twelve category and two language-type slices at weekly period. Category and language-type token totals come from sampled, upsampled estimates, not the exact daily dataset. Text/image_output refer to output modality; image/audio refer to input modality; tool_calling selects rows with tool calls. Context buckets concern request context length, not a model's advertised maximum. Do not sum overlapping slices into a platform total. No unsupported category × modality combinations. Yearly windows respect the 366-day limit. Also stores recent 14-day windows. Weekly labels and trailing weeks can extend past requested bounds; they do not represent independent daily usage. Month is a derived aggregation of source weeks and is not separately downloaded. Existing dashboard remains unchanged.
* `session-cost`: daily retrieval of the full available unfiltered paginated response. Source refreshes **weekly**, typically describing a rolling window (`window_days`, `window_end_date`). Median session cost is not per-token price or cost per successful task. No historical date parameter exists: only snapshots observed from collection start can be retained. Apps are not pooled. Four turn ranges are retained as returned. A changing `as_of` alone is not proof of a new immutable source snapshot.

App pagination permits offsets 0 and 100 with limit 100 (at most 200 visible ranked rows/slice); session pagination permits offsets 0..5000 with limit 500 (at most 5500 cells). A full final allowed page is recorded `pagination_cap`, never claimed complete. Empty data is `source_empty`, not zero use, and is revisited after 14 days for recent dates or 90 days for source dates more than 30 days old. Source rejection is retried after seven days; transient errors after one day. Old successful app responses are preserved; current-year rankings are refreshed with new date windows, and all previous raw responses remain available. Apps may be revised upstream after their first successful collection: this archive does not assert they are immutable or automatically refresh all historical app dates.

## Scheduling and bounded backfill

The daily schedule is 07:45 UTC (GitHub may delay it). Most recent source day and current session snapshot have priority, followed by rankings windows, then previously unattempted app history newest-first with all slices interleaved per day, then due historical retries. Historical empty-result retries cannot starve the initial backfill. Production is disabled initially in `config/datasets.json`: the initial run is a maximum 12-request contract probe. After reviewing actual responses, set `production_enabled` to true to enable bounded daily backfill.

On 2026-10-19 the plan contains 26,240 app slices, 75 rankings windows, and one current session snapshot, before pagination. This is **not** an assertion these dates/cells all exist. At 450 requests/day minus ongoing current collection, history requires roughly 2–5 months depending on pagination, emptiness, errors and rate limits. Two additional exact-day probes are queued for 2025-06-15 and 2025-07-15, absent in the first annual response. They are subject to the same budget and do not assert permanent source loss. Exact pending counts are in `latest-report.json`. Do not label initial partial backfill complete.

Requests are spaced at least 2.2 seconds apart, below the documented 30/minute/key ceiling. A durable lease reserves up to 450 requests/day **and commits that reservation before any API calls**. Fifty requests are left for the existing yearly refresh (currently two daily calls) and manual reruns. This bounds this collector, not all uses of the account: calls from other repositories or tools are not observable. HTTP 429 immediately stops requests until at least the next UTC day and honors a longer Retry-After. Every attempted call consumes a reservation, including HTTP/network errors. A hard-cancelled job can waste the unused reserved budget but cannot reclaim it and overrun the same day's collector cap. The original and new jobs share concurrency group `refresh` to avoid competing writes. A failed final Git push fails the workflow and retains a short-lived recovery artifact; a successful API call alone is not durable collection.

## Evidence and use

* `data/datasets/raw/<endpoint>/<fetch-date>/<sha256>.json.gz`: exact successful JSON bytes, losslessly compressed, content-addressed.
* `attempts/<UTC-date>/<ordinal>.json`: request parameters, HTTP status, timestamp, byte length, SHA-256 of uncompressed and compressed response, raw path, returned metadata and rows. Error response bodies and all headers are intentionally excluded to prevent credential reflection.
* `checkpoint.json`: task identities and page references, source states, next retry date, daily budget and leases. Source dates are in request params; fetch dates are separate.
* `reports/` and `latest-report.json`: run counts, remaining work and budget state.

Use only the page list for a particular task result when combining pages, and verify both SHA-256 values. Preserve the response metadata. Never concatenate every raw file: successive windows and snapshots intentionally overlap. Weekly observations crossing yearly query windows can also repeat. Deduplicate for analysis by source endpoint, slice, source period/date, and identity, with a declared revision-selection rule; retain previous versions and provenance. This archive is deliberately raw, not a silently harmonized research panel. Completeness flags describe the API pagination, not the entire platform. Individual source failures, unavailable historical dates, and exclusions must be reported explicitly.

Run offline tests: `python -m unittest discover -s tests -v`. Show the query plan without credentials: `python scripts/collect-datasets.py --plan`. Never put keys into source, command arguments, logs, or exported files.

Documentation checked 2026-10-19:
- https://openrouter.ai/docs/api/api-reference/datasets/top-apps-by-token-usage
- https://openrouter.ai/docs/api/api-reference/datasets/daily-token-totals-for-top-50-models
- https://openrouter.ai/docs/api/api-reference/datasets/cost-per-session-by-harness-and-model
