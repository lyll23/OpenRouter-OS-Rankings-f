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

## Session-cost 版本与研究筛选（2026-10-30）

所有安全且通过响应级校验的原始分页继续保留在 `raw/`，每次请求记录仍在
`attempts/`，不覆盖或删除旧版本。不通过安全校验的响应体仍不入库，防止凭据或
私人字段泄露；保留请求状态与哈希，不能声称这种响应体已归档。

新增 `versions/session-cost/<batch_id>.json` 为派生索引，每次计划采集结束自动更新。
它从原有 attempts/raw 离线重建，包含同一查询及抓取日内从 offset=0 开始的一批
请求；再次 offset=0 即新批次，跨抓取日不拼接。相同正文可以共享内容寻址 raw，
但各次请求、抓取时间和批次仍独立记录。中断批次续页时，同一批次索引可更新，
原始 attempts/raw 不变。旧数据没有新标签时可离线生成，不需要补抓。

每页索引包含：请求时间、源 `as_of`/`version`/窗口、offset/limit、attempt/raw 路径、
原始体与 gzip SHA256、长度、行数和完整性校验结果。批次包含源版本一致性、
分页完整性、`status`、`research_eligible` 和原因。`observed_rows` 是各页观测数，
不表示可合并的完整截面。例如 A 版本第一页500条加 B 版本第二页137条会标
`inconsistent`、完整性 `unconfirmed`、`research_eligible=false`；不会被包装为
两版完整数据或同一版637条。匹配窗口但不同 as_of 也不放行。

离线重建标签（不调用 API、不改 checkpoint/历史 raw）：

    python scripts/collect-datasets.py --root data/datasets --index-session-cost

研究导出（只读、无需密钥；完整历史批次，不盲目只保留最新版）：

    python scripts/collect-datasets.py --root data/datasets --session-cost-research > session-cost-research.json

导出重新验证每个原始 gzip/正文哈希、长度、schema、身份、页码连续性、所有页面
meta 完全一致及末页少于500条。只有非空且完整的批次进入 `complete_batches`。
不同查询分组不合并。每组同时保留 `latest_attempt` 和 `latest_complete_batch_id`；
若新批失败而旧完整批存在，`last_complete_is_older_attempt=true`，不冒充当前新鲜数据。
没有完整批次时导出空列表，不把缺失变0。使用者应保留 manifest 的源日/抓取日/
批次ID，不能自行把不同批次扁平拼为同一截面。该视图不代表完整UTC日用量。

此次没有增加 API 请求/重试、改变450请求预算、删除历史或放宽 Action 失败门禁。
因此源站持续跨页版本不一致时 Action 仍可失败，但原始片段与其标签均可追溯。

首次上线仅新增10月28日、29日两个已核验批次的派生标签；两批均为跨页版本不一致，
不进入完整研究视图。其他旧日期在下次正常计划运行结束时自动生成索引；离线研究
导出本身也会直接从全部本地 attempts/raw 重验，不依赖标签是否已经落盘。
