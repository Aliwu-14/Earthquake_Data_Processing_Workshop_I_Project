# Feature QA (2017-2025 split)

- All-mask rows: 2,695,500
- Historically-active rows: 403,500
- Feature columns (19): lat_center, lon_sin, lon_cos, in_china_rectangle, in_pacific, in_overlap, region_label, p_empirical_train, historically_active, dist_to_plate_boundary_km, n_m55_cell_30d, n_m55_cell_90d, n_m55_cell_365d, kernel_s, kernel_lambda, days_since_last_m55_cell, no_prior_m55_in_cell, any_m6_800km_365d, n_m6_800km_365d
- Plate-boundary distance: included from `PB2002_boundaries.shp` (great-circle km, 2 km densify).
- Prevalence match vs locked baseline: True
- Leakage check passed: True (value checks 720, kernel recomputes 30, mismatches 0)
- First train window fraction with no prior event in-cell: 1.0000
- `features_all_mask.parquet` sha256: 1c5ee7666711cae4c191029eb2a1a4fde5715efcb7439ce168bb23dca78ebbed
- `features_hist_active.parquet` sha256: 81d8b9aece08a8f897d81d6128a2458d5c8e40127a4c1bb6a83d817df448c890

Event-derived features use only origin times strictly before window_start. No model was trained.
