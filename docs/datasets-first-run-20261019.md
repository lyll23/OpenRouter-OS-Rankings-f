# 2026-10-19 首批数据覆盖核验

核验提交：dcf93baa0104c81169ef7e43fcd6f3f86c4d46d2。449 个 HTTP 200 响应的原始与 gzip SHA-256 均验证通过。请求成功与返回时间序列覆盖完整分别记录。

## 模型榜实际源日期

25 个切片均已请求 2025、2026 年窗口与近期窗口；下列缺失标签仅表示 API 当次没有返回，不能记为零，也未证明永久不可恢复。用途/语言为抽样放大估计的周度数据。

|切片|请求年份|首个源标签|末个源标签|已返回标签数|未返回标签数|
|---|---|---|---|---:|---:|
|category=academia, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=academia, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=finance, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=finance, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=health, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=health, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=legal, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=legal, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=marketing, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=marketing, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=marketing/seo, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=marketing/seo, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=programming, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=programming, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=roleplay, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=roleplay, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=science, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=science, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=technology, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=technology, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=translation, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=translation, period=week|2026|2025-12-29|2026-10-12|42|0|
|category=trivia, period=week|2025|2025-05-19|2025-12-29|33|20|
|category=trivia, period=week|2026|2025-12-29|2026-10-12|42|0|
|context_bucket=100K, period=day|2025|2025-01-01|2025-12-31|363|2|
|context_bucket=100K, period=day|2026|2026-01-01|2026-10-18|291|0|
|context_bucket=10K, period=day|2025|2025-01-01|2025-12-31|363|2|
|context_bucket=10K, period=day|2026|2026-01-01|2026-10-18|291|0|
|context_bucket=10M, period=day|2025|2025-01-01|2025-12-31|362|3|
|context_bucket=10M, period=day|2026|2026-01-01|2026-10-18|291|0|
|context_bucket=1K, period=day|2025|2025-01-01|2025-12-31|363|2|
|context_bucket=1K, period=day|2026|2026-01-01|2026-10-18|291|0|
|context_bucket=1M, period=day|2025|2025-01-01|2025-12-31|363|2|
|context_bucket=1M, period=day|2026|2026-01-01|2026-10-18|291|0|
|language_type=natural, period=week|2025|2025-08-18|2025-12-29|18|35|
|language_type=natural, period=week|2026|2025-12-29|2026-10-12|42|0|
|language_type=programming, period=week|2025|2025-09-15|2025-12-29|16|37|
|language_type=programming, period=week|2026|2025-12-29|2026-10-12|42|0|
|modality=audio, period=day|2025|2025-02-05|2025-12-31|328|37|
|modality=audio, period=day|2026|2026-01-01|2026-10-18|291|0|
|modality=image, period=day|2025|2025-01-01|2025-12-31|363|2|
|modality=image, period=day|2026|2026-01-01|2026-10-18|291|0|
|modality=image_output, period=day|2025|2025-08-26|2025-12-31|128|237|
|modality=image_output, period=day|2026|2026-01-01|2026-10-18|291|0|
|modality=text, period=day|2025|2025-01-01|2025-12-31|363|2|
|modality=text, period=day|2026|2026-01-01|2026-10-18|291|0|
|modality=tool_calling, period=day|2025|2025-01-18|2025-12-31|346|19|
|modality=tool_calling, period=day|2026|2026-01-01|2026-10-18|291|0|
|period=day|2025|2025-01-01|2025-12-31|363|2|
|period=day|2026|2026-01-01|2026-10-18|291|0|

详细缺失标签清单见同目录 datasets-first-run-20261019.json。2025 总榜缺 2025-06-15、2025-07-15；不能把这两天总量归零。各切片不同起始日期也不代表模型在那些日期才上线。

## 应用榜与会话成本

- 应用榜 2026-10-11 至 2026-10-18 每天 40 个过滤/排序切片已尝试；2026-10-10 已返回 20 个切片，另一个仅排队，尚未发送请求。更早日期仍待回补。
- 24 个切片为空，已单独标记 source_empty；9 个热门总榜触及可访问的 200 名分页上限，不能称作全应用用量。
- 会话成本 653 个聚合单元、两页一致；源窗口 30 天，截至 2026-10-18。该端点没有历史日期参数，历史只能从开始采集后逐期积累。

## 后续与解释

- 每日新增与未尝试历史优先；已有空源慢速复查，避免挤掉首次回补。
- 当前年度模型榜每天重新请求年度窗口，能够保留源修订。2025 年已成功请求窗口中的缺日已列出；已安排在后续有预算的运行中分别单日复核，尚未声称补齐。
- 所有重查均保存新原始响应和抓取时间；缺失、未尝试、分页截断分别记录。
