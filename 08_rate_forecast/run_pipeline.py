#!/usr/bin/env python3
"""Build grid artifacts, fit two baselines, write summaries. No ML training."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from rate_forecast_lib import (
    HOLDOUT_END,
    KERNEL_CUTOFF_KM,
    KERNEL_SIGMA_KM,
    KERNEL_TAU_DAYS,
    LOCK_COUNTS,
    PROB_FLOOR,
    ROOT,
    SPLIT_BOUNDS,
    assign_events,
    boundary_event_counts,
    build_cell_mask,
    build_windows,
    calibration_table,
    clip_prob,
    kernel_scores,
    load_and_verify_catalog,
    longterm_rates,
    methodology_record,
    mark_historical_activity,
    pack_panel,
    score_panel,
    summarize_counts,
    train_constant,
    write_json,
    CountMismatchError,
    _region_cell_mask,
    _region_hist_col,
)

OUT = ROOT
FIG = ROOT / "figures"


def sha256_ids(df: pd.DataFrame) -> str:
    payload = ("\n".join(df.sort_values("id")["id"].astype(str)) + "\n").encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)

    try:
        ev_main, ev_hold = load_and_verify_catalog()
    except CountMismatchError as exc:
        print("STOP: count mismatch — not redefining the region.", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 2

    ev_all = pd.concat([ev_main, ev_hold], ignore_index=True)
    print("catalog ok", LOCK_COUNTS, "holdout union", int(ev_hold["in_union"].sum()))
    print("main id-list sha256", sha256_ids(ev_main))

    windows = build_windows()
    cells = build_cell_mask()
    ev = assign_events(ev_all, windows)
    cells = mark_historical_activity(cells, ev)

    # Union events must land in the union mask
    ev_u = ev.loc[ev["in_union"]]
    missing_mask = ev_u.loc[~ev_u["cell_id"].isin(set(cells.loc[cells["in_union_mask"], "cell_id"]))]
    if len(missing_mask):
        print("STOP: union events assigned outside the mask", file=sys.stderr)
        print(missing_mask[["id", "latitude", "longitude", "cell_id", "china_rectangle", "PB_Pacific"]].head(20), file=sys.stderr)
        return 2

    counts = summarize_counts(ev, windows, cells)
    bounds = boundary_event_counts(ev, windows)

    ev_main_out = ev.loc[ev["catalog_role"] == "main_1965_2024"].copy()
    ev_hold_out = ev.loc[ev["catalog_role"] == "later_holdout_2025_2026"].copy()
    ev_union = ev.loc[ev["in_union"]].copy()

    windows.to_csv(OUT / "windows.csv", index=False)
    cells.to_csv(OUT / "cells_mask.csv", index=False)
    ev_union.to_csv(OUT / "events_union_assigned.csv", index=False)
    counts.to_csv(OUT / "prevalence_by_split_region.csv", index=False)
    bounds.to_csv(OUT / "boundary_window_event_counts.csv", index=False)

    rates = longterm_rates(ev, windows, cells)
    pd.concat(rates.values(), ignore_index=True).to_csv(OUT / "longterm_cell_rates.csv", index=False)

    kernel = {}
    for region in ["china_rectangle", "pacific", "union"]:
        print("kernel", region, "...")
        kernel[region] = kernel_scores(ev, windows, cells, region)
        print("  alpha", kernel[region]["alpha"], "n_train_events", kernel[region]["n_train_events"])

    metric_rows = []
    cal_rows = []
    train_diag = []
    panel_meta = []

    for region in ["china_rectangle", "pacific", "union"]:
        kres = kernel[region]
        csub = kres["cells"]
        hist_col = _region_hist_col(region)
        hist_mask_arr = csub[hist_col].to_numpy()
        for eval_set, hmask in [("all_mask_cells", None), ("historically_active", hist_mask_arr)]:
            const = train_constant(kres, rates[region], windows, hmask)
            train_diag.append(
                {
                    "region": region,
                    "eval_set": eval_set,
                    "p_const_train": const["p_const"],
                    "lambda_const_train": const["lambda_const"],
                    "kernel_alpha": kres["alpha"],
                    "n_train_events_region": kres["n_train_events"],
                    "sum_s_train": kres["sum_s_train"],
                    "n_train_pos": const["n_pos"],
                    "n_train_cw": const["n_cw"],
                }
            )
            for split in ["val", "test", "holdout"]:
                panel = pack_panel(windows, kres, rates[region], split, hmask)
                p_const = np.full(panel["y"].shape, const["p_const"], dtype=float)
                for model, parr in [
                    ("longterm_empirical", panel["p_empirical"]),
                    ("longterm_poisson", panel["p_poisson"]),
                    ("recent_kernel", panel["p_kernel"]),
                    ("constant_prevalence", p_const),
                ]:
                    sc = score_panel(panel["y"], parr, p_const, model)
                    sc.update({"region": region, "split": split, "eval_set": eval_set})
                    sc["n_cells"] = panel["n_cells"]
                    sc["n_windows"] = panel["n_windows"]
                    sc["n_events"] = panel["n_events"]
                    sc["mean_predicted"] = float(clip_prob(parr).mean())
                    if model == "recent_kernel":
                        sc["mean_lambda"] = float(panel["lambda_kernel"].mean())
                        sc["mean_observed_count"] = panel["n_events"] / (panel["n_windows"] * panel["n_cells"]) if panel["n_cells"] else np.nan
                    else:
                        sc["mean_lambda"] = np.nan
                        sc["mean_observed_count"] = panel["n_events"] / (panel["n_windows"] * panel["n_cells"]) if panel["n_cells"] else np.nan
                    metric_rows.append(sc)
                    cal = calibration_table(panel["y"], parr)
                    cal["region"] = region
                    cal["split"] = split
                    cal["eval_set"] = eval_set
                    cal["model"] = model
                    cal_rows.append(cal)
                panel_meta.append(
                    {
                        "region": region,
                        "split": split,
                        "eval_set": eval_set,
                        "n_cells": panel["n_cells"],
                        "n_windows": panel["n_windows"],
                        "n_events": panel["n_events"],
                        "n_positive": int(panel["y"].sum()),
                    }
                )

    metrics = pd.DataFrame(metric_rows)
    # stable column order
    front = ["region", "split", "eval_set", "model"]
    metrics = metrics[front + [c for c in metrics.columns if c not in front]]
    metrics.to_csv(OUT / "metrics_baselines.csv", index=False)
    pd.concat(cal_rows, ignore_index=True).to_csv(OUT / "calibration_bins.csv", index=False)
    pd.DataFrame(train_diag).to_csv(OUT / "train_baseline_diagnostics.csv", index=False)
    pd.DataFrame(panel_meta).to_csv(OUT / "eval_panel_sizes.csv", index=False)

    split_counts = windows.groupby("split").size().to_dict()
    note_counts = windows.groupby("boundary_note").size().to_dict()
    summary = {
        "locked_main_counts_verified": LOCK_COUNTS,
        "holdout_verified": {"all": int(len(ev_hold)), "union": int(ev_hold["in_union"].sum())},
        "main_id_list_sha256": sha256_ids(ev_main),
        "official_table_sha256_documented": "1018e3856fcf15c791f4136fb833f0b4937868e3e6c1f54ead6503529289f265",
        "official_table_present_on_box": False,
        "grid": {
            "degree": 2,
            "window_days": 30,
            "time_origin": str(SPLIT_BOUNDS["train"][0]),
            "holdout_end": str(HOLDOUT_END),
            "n_cells_union": int(cells["in_union_mask"].sum()),
            "n_cells_rectangle": int(cells["intersects_rectangle"].sum()),
            "n_cells_pacific": int(cells["intersects_pacific"].sum()),
            "n_cells_overlap_geometry": int((cells["intersects_rectangle"] & cells["intersects_pacific"]).sum()),
            "n_hist_active_union": int(cells["historically_active_union"].sum()),
            "n_hist_active_rectangle": int(cells["historically_active_rectangle"].sum()),
            "n_hist_active_pacific": int(cells["historically_active_pacific"].sum()),
        },
        "windows": {
            "n_generated": int(len(windows)),
            "by_split": {k: int(v) for k, v in split_counts.items()},
            "by_boundary_note": {k: int(v) for k, v in note_counts.items()},
            "straddle_or_incomplete": windows.loc[
                windows["split"] == "none",
                ["window_id", "window_start", "window_end", "boundary_note"],
            ].to_dict(orient="records"),
        },
        "kernel": {
            "tau_days": KERNEL_TAU_DAYS,
            "sigma_km": KERNEL_SIGMA_KM,
            "cutoff_km": KERNEL_CUTOFF_KM,
            "alpha": {r: kernel[r]["alpha"] for r in kernel},
            "n_train_events": {r: kernel[r]["n_train_events"] for r in kernel},
        },
        "probability_floor": PROB_FLOOR,
        "prevalence": counts.to_dict(orient="records"),
        "boundary_events": bounds.to_dict(orient="records"),
        "methodology": methodology_record(),
    }
    write_json(OUT / "counts_summary.json", summary)
    write_json(OUT / "methodology.json", methodology_record())

    # compact window-level observed positives for plots
    recs = []
    for region in ["china_rectangle", "pacific", "union"]:
        kres = kernel[region]
        for split in ["train", "val", "test", "holdout"]:
            for wid in windows.loc[windows["split"] == split, "window_id"].astype(int):
                cnt = kres["stored_count"][wid]
                recs.append(
                    {
                        "region": region,
                        "split": split,
                        "window_id": int(wid),
                        "n_events": int(cnt.sum()),
                        "n_positive_cells": int((cnt > 0).sum()),
                    }
                )
    pd.DataFrame(recs).to_csv(OUT / "window_observed_series.csv", index=False)

    print("windows by split", split_counts)
    print("cells", summary["grid"])
    print("wrote artifacts to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
