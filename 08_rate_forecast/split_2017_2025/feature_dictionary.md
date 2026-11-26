# Feature dictionary (2017-2025 split)

Locked spatiotemporal rate-forecasting features. Every event-derived feature for window T uses only earthquakes with origin time strictly before `window_start`. Time-invariant cell attributes may use train-period statistics. `y` and `diag_n_events_in_window` are not features. Kernel hyperparameters were not searched on val/test.

| column | role | dtype | definition |
| --- | --- | --- | --- |
| `cell_id` | identifier | category | 2-degree cell id from even-degree half-open edges, C{lon_west}_{lat_south}. |
| `window_id` | identifier | int16 | Index of the 30-day bin starting 1965-01-01T00:00:00Z. |
| `window_start` | identifier | datetime64[ns, UTC] | Window start (UTC). History features use only origin times strictly earlier than this instant. |
| `window_end` | identifier | datetime64[ns, UTC] | Window end (UTC, exclusive). |
| `split` | identifier | category | train / val / test / holdout for complete in-split windows only. |
| `y` | label | int8 | 1 if at least one union-region M>=5.5 earthquake has origin time in [window_start, window_end) and is assigned to this cell. Not a feature. |
| `diag_n_events_in_window` | diagnostic_not_a_feature | int16 | Count of union M>=5.5 events in this cell-window. Uses events inside T, so it must not be used as a model feature. |
| `lon_center` | cell_metadata_not_euclidean_feature | float32 | Cell-center longitude in [-180, 180). Stored for maps and distance checks. Do not treat raw lon/lat as Euclidean ML features; use lon_sin and lon_cos. |
| `lat_center` | feature | float32 | Cell-center latitude in degrees. Time-invariant. |
| `lon_sin` | feature | float32 | sin(lon_center in radians), spherical longitude encoding. Time-invariant. |
| `lon_cos` | feature | float32 | cos(lon_center in radians), spherical longitude encoding so cells near +/-180 stay close. Time-invariant. |
| `in_china_rectangle` | feature | bool | Cell intersects the closed 70-145E, 10-60N rectangle under the assignment rule. |
| `in_pacific` | feature | bool | Cell half-open box intersects a PB2002 Pacific polygon part. |
| `in_overlap` | feature | bool | in_china_rectangle and in_pacific. |
| `region_label` | feature | category | rectangle_only, pacific_only, or overlap. |
| `p_empirical_train` | feature | float32 | Baseline 1 union long-term empirical P(N>=1): fraction of the 535 complete train windows with at least one union event in this cell. Static, train windows only. No 2025-2026 data. |
| `historically_active` | feature | bool | True if at least one union event in this cell has origin time in [1965-01-01, 2009-01-01). Same rule as the baseline historically-active evaluation set. |
| `dist_to_plate_boundary_km` | feature | float32 | Great-circle distance (km, R=6371.0) from the cell center to the nearest point on PB2002_boundaries.shp, after densifying lines at 2.0 km along the sphere. Time-invariant. Source: /workspace/07_external/context/tectonicplates/PB2002_boundaries.shp. |
| `n_m55_cell_30d` | feature | int16 | Count of union M>=5.5 events assigned to this cell with origin time in [T.start-30d, T.start). |
| `n_m55_cell_90d` | feature | int16 | Same as n_m55_cell_30d with a 90-day lookback. |
| `n_m55_cell_365d` | feature | int16 | Same as n_m55_cell_30d with a 365-day lookback. |
| `kernel_s` | feature | float32 | Neighborhood recent-activity kernel at T.start, identical to baseline 2: sum over union events with t_e < T.start of exp(-(T.start-t_e)/tau) * exp(-d_gc^2 / (2 sigma^2)) for d_gc <= cutoff. tau=1095.75 d, sigma=200.0 km, cutoff=800.0 km, haversine with wrapped longitude. Not refit on val/test. |
| `kernel_lambda` | feature | float32 | alpha * kernel_s, with alpha=0.005506486521694776 estimated by Poisson MLE on complete train windows only (same as the baseline). |
| `days_since_last_m55_cell` | feature | float32 | Days from the most recent union M>=5.5 in this cell with t < T.start, to T.start. Null (not 0) if no such prior event. |
| `no_prior_m55_in_cell` | feature | bool | Censored/missing flag: True when no union M>=5.5 in this cell exists before T.start. Use together with days_since_last_m55_cell; do not silently fill the delay with 0. |
| `any_m6_800km_365d` | feature | bool | True if at least one union event with mag>=6 occurred within 800 km (haversine to the cell center) in [T.start-365d, T.start). |
| `n_m6_800km_365d` | feature | int16 | Count of those mag>=6 union events within 800 km in the previous 365 days. |
