# 08_rate_forecast

本文件夹是 USGS **M≥5.5** 时空发生率工作，网格为 **2° × 30 天**。只收录已经算好的快照，不在这里训练模型。

当前锁定划分：

- 训练：1965–2008
- 验证：2009–2016
- 测试：2017–2025
- 之后留出：仅 2026

`08_rate_forecast/` 根目录里、`split_2017_2025/` 以外的文件，是较早的「测试 2017–2024 / 留出 2025–2026」快照，保留作对照。当前特征表和当前划分的笔记本在 `split_2017_2025/`：

- `features_all_mask.parquet`
- `features_hist_active.parquet`

2025 年此前被当作后期留出计分，现在不再是未见过的后期检验。

请勿把这些文件混入 1965–2024 主目录。

## English

This folder is the USGS M≥5.5 spatiotemporal occurrence-rate work on 2° × 30-day cells. The locked split is train 1965–2008, validation 2009–2016, test 2017–2025, and a later holdout of 2026 only. Files in the parent `08_rate_forecast/` directory, other than `split_2017_2025/`, are the earlier 2017–2024 test / 2025–2026 holdout snapshot, kept for comparison. Current feature tables and current-split notebooks live in `split_2017_2025/`. Year 2025 was previously scored as a later holdout and is no longer an unseen later check. Do not mix these files into the 1965–2024 main catalogs.
