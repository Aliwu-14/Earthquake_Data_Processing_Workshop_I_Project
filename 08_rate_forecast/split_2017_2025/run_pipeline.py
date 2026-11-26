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



PREV_DIR = Path("/workspace/08_rate_forecast")


def write_split_comparison(counts: pd.DataFrame, metrics: pd.DataFrame, windows: pd.DataFrame, ev: pd.DataFrame) -> Path:
    """Compare this 2017-2025 test split with the previous 2017-2024 snapshot. Reads old files only."""
    old_counts = pd.read_csv(PREV_DIR / "prevalence_by_split_region.csv")
    old_metrics = pd.read_csv(PREV_DIR / "metrics_baselines.csv")
    old_windows = pd.read_csv(PREV_DIR / "windows.csv")

    rows = []
    def add(item, old, new, note=""):
        rows.append({"item": item, "old_test_2017_2024_holdout_2025_2026": old, "new_test_2017_2025_holdout_2026": new, "note": note})

    old_w = old_windows.groupby("split").size().to_dict()
    new_w = windows.groupby("split").size().to_dict()
    add("n_windows_train", old_w.get("train"), new_w.get("train"), "should be unchanged")
    add("n_windows_val", old_w.get("val"), new_w.get("val"), "should be unchanged")
    add("n_windows_test", old_w.get("test"), new_w.get("test"), "includes former 2024-12-17 to 2025-01-16 window and all 2025 complete windows")
    add("n_windows_holdout", old_w.get("holdout"), new_w.get("holdout"), "2026 complete windows only")

    for region in ["union", "china_rectangle", "pacific"]:
        for split in ["train", "val", "test", "holdout"]:
            o = old_counts[(old_counts.region == region) & (old_counts.split == split)].iloc[0]
            n = counts[(counts.region == region) & (counts.split == split)].iloc[0]
            add(f"{region}_{split}_events", int(o.n_events_in_complete_windows), int(n.n_events_in_complete_windows))
            add(f"{region}_{split}_pos_all", int(o.n_positive_cell_windows_all), int(n.n_positive_cell_windows_all))
            add(f"{region}_{split}_prevalence_all", float(o.prevalence_all), float(n.prevalence_all))
            add(f"{region}_{split}_pos_hist", int(o.n_positive_cell_windows_hist_active), int(n.n_positive_cell_windows_hist_active))
            add(f"{region}_{split}_prevalence_hist", float(o.prevalence_hist_active), float(n.prevalence_hist_active))

    models = ["longterm_empirical", "recent_kernel", "constant_prevalence"]
    for region in ["union", "china_rectangle", "pacific"]:
        for eval_set in ["all_mask_cells", "historically_active"]:
            for split in ["val", "test", "holdout"]:
                for model in models:
                    o = old_metrics[(old_metrics.region == region) & (old_metrics.eval_set == eval_set) & (old_metrics.split == split) & (old_metrics.model == model)]
                    n = metrics[(metrics.region == region) & (metrics.eval_set == eval_set) & (metrics.split == split) & (metrics.model == model)]
                    if o.empty or n.empty:
                        continue
                    o, n = o.iloc[0], n.iloc[0]
                    tag = f"{region}_{split}_{eval_set}_{model}"
                    add(f"{tag}_brier", float(o.brier), float(n.brier))
                    add(f"{tag}_relLL", float(o.rel_log_likelihood_vs_const), float(n.rel_log_likelihood_vs_const))
                    add(f"{tag}_pr_auc", float(o.pr_auc), float(n.pr_auc))

    out = pd.DataFrame(rows)
    path = ROOT / "comparison_old_2017_2024_vs_new_2017_2025.csv"
    out.to_csv(path, index=False)

    # compact key table for the page / report
    key_rows = []
    for region in ["union", "china_rectangle", "pacific"]:
        for split, old_name, new_name in [
            ("test", "old_test_2017_2024", "new_test_2017_2025"),
            ("holdout", "old_holdout_2025_2026", "new_holdout_2026"),
        ]:
            o = old_counts[(old_counts.region == region) & (old_counts.split == split)].iloc[0]
            n = counts[(counts.region == region) & (counts.split == split)].iloc[0]
            rec = {
                "region": region,
                "panel": split,
                "old_label": old_name,
                "new_label": new_name,
                "old_n_windows": int(o.n_windows),
                "new_n_windows": int(n.n_windows),
                "old_events": int(o.n_events_in_complete_windows),
                "new_events": int(n.n_events_in_complete_windows),
                "old_pos_all": int(o.n_positive_cell_windows_all),
                "new_pos_all": int(n.n_positive_cell_windows_all),
                "old_prev_all": float(o.prevalence_all),
                "new_prev_all": float(n.prevalence_all),
                "old_pos_hist": int(o.n_positive_cell_windows_hist_active),
                "new_pos_hist": int(n.n_positive_cell_windows_hist_active),
                "old_prev_hist": float(o.prevalence_hist_active),
                "new_prev_hist": float(n.prevalence_hist_active),
            }
            for model, mlab in [("longterm_empirical", "emp"), ("recent_kernel", "kernel"), ("constant_prevalence", "const")]:
                for eval_set, elab in [("all_mask_cells", "all"), ("historically_active", "hist")]:
                    om = old_metrics[(old_metrics.region == region) & (old_metrics.eval_set == eval_set) & (old_metrics.split == split) & (old_metrics.model == model)].iloc[0]
                    nm = metrics[(metrics.region == region) & (metrics.eval_set == eval_set) & (metrics.split == split) & (metrics.model == model)].iloc[0]
                    rec[f"old_{elab}_{mlab}_brier"] = float(om.brier)
                    rec[f"new_{elab}_{mlab}_brier"] = float(nm.brier)
                    rec[f"old_{elab}_{mlab}_relLL"] = float(om.rel_log_likelihood_vs_const)
                    rec[f"new_{elab}_{mlab}_relLL"] = float(nm.rel_log_likelihood_vs_const)
                    rec[f"old_{elab}_{mlab}_prauc"] = float(om.pr_auc)
                    rec[f"new_{elab}_{mlab}_prauc"] = float(nm.pr_auc)
            key_rows.append(rec)
    # also val (should be nearly unchanged)
    for region in ["union", "china_rectangle", "pacific"]:
        o = old_counts[(old_counts.region == region) & (old_counts.split == "val")].iloc[0]
        n = counts[(counts.region == region) & (counts.split == "val")].iloc[0]
        rec = {
            "region": region,
            "panel": "val",
            "old_label": "old_val_2009_2016",
            "new_label": "new_val_2009_2016",
            "old_n_windows": int(o.n_windows),
            "new_n_windows": int(n.n_windows),
            "old_events": int(o.n_events_in_complete_windows),
            "new_events": int(n.n_events_in_complete_windows),
            "old_pos_all": int(o.n_positive_cell_windows_all),
            "new_pos_all": int(n.n_positive_cell_windows_all),
            "old_prev_all": float(o.prevalence_all),
            "new_prev_all": float(n.prevalence_all),
            "old_pos_hist": int(o.n_positive_cell_windows_hist_active),
            "new_pos_hist": int(n.n_positive_cell_windows_hist_active),
            "old_prev_hist": float(o.prevalence_hist_active),
            "new_prev_hist": float(n.prevalence_hist_active),
        }
        for model, mlab in [("longterm_empirical", "emp"), ("recent_kernel", "kernel"), ("constant_prevalence", "const")]:
            for eval_set, elab in [("all_mask_cells", "all"), ("historically_active", "hist")]:
                om = old_metrics[(old_metrics.region == region) & (old_metrics.eval_set == eval_set) & (old_metrics.split == "val") & (old_metrics.model == model)].iloc[0]
                nm = metrics[(metrics.region == region) & (metrics.eval_set == eval_set) & (metrics.split == "val") & (metrics.model == model)].iloc[0]
                rec[f"old_{elab}_{mlab}_brier"] = float(om.brier)
                rec[f"new_{elab}_{mlab}_brier"] = float(nm.brier)
                rec[f"old_{elab}_{mlab}_relLL"] = float(om.rel_log_likelihood_vs_const)
                rec[f"new_{elab}_{mlab}_relLL"] = float(nm.rel_log_likelihood_vs_const)
                rec[f"old_{elab}_{mlab}_prauc"] = float(om.pr_auc)
                rec[f"new_{elab}_{mlab}_prauc"] = float(nm.pr_auc)
        key_rows.append(rec)
    key = pd.DataFrame(key_rows)
    key_path = ROOT / "comparison_key_counts_and_scores.csv"
    key.to_csv(key_path, index=False)
    return key_path


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
    ev_y2025 = ev.loc[ev["catalog_role"] == "year_2025_in_test"].copy()
    ev_y2026 = ev.loc[ev["catalog_role"] == "year_2026_holdout"].copy()
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
        "later_catalog_verified": {"all": int(len(ev_hold)), "union": int(ev_hold["in_union"].sum())},
        "year_2025_in_test": {
            "all": int((ev_hold["catalog_role"] == "year_2025_in_test").sum()) if "catalog_role" in ev_hold.columns else int((ev_hold.time_utc.dt.year == 2025).sum()),
            "union": int(ev_y2025["in_union"].sum()),
            "china_rectangle": int(ev_y2025["china_rectangle"].sum()),
            "PB_Pacific": int(ev_y2025["PB_Pacific"].sum()),
        },
        "year_2026_holdout": {
            "all": int((ev_hold["catalog_role"] == "year_2026_holdout").sum()) if "catalog_role" in ev_hold.columns else int((ev_hold.time_utc.dt.year == 2026).sum()),
            "union": int(ev_y2026["in_union"].sum()),
            "china_rectangle": int(ev_y2026["china_rectangle"].sum()),
            "PB_Pacific": int(ev_y2026["PB_Pacific"].sum()),
        },
        "protocol_2025_already_seen": "2025 was previously scored as part of the 2025-2026 later holdout and those baseline numbers were already shown to the user; it is no longer an unseen later check.",
        "split_scheme": "train 1965-2008, val 2009-2016, test 2017-2025, holdout 2026-to-fetch-end",
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

    comparison_path = write_split_comparison(counts, metrics, windows, ev)
    print("windows by split", split_counts)
    print("cells", summary["grid"])
    print("wrote artifacts to", OUT)
    print("comparison table", comparison_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
