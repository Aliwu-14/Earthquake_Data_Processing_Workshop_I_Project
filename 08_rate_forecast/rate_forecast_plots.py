"""Plot helpers for the rate-forecast notebooks."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from shapely.geometry import box

from pathlib import Path
from rate_forecast_lib import ROOT, clip_prob, load_pacific_polygon

FIG = ROOT / "figures"
sns.set_theme(style="whitegrid", font_scale=0.95)


def plot_cell_mask(cells: pd.DataFrame, path: Path | None = None):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    pac = load_pacific_polygon()
    parts = list(pac.geoms) if pac.geom_type == "MultiPolygon" else [pac]
    for i, part in enumerate(parts):
        xs, ys = part.exterior.xy if part.geom_type == "Polygon" else (None, None)
        if part.geom_type == "Polygon":
            ax.plot(xs, ys, color="#8d6e63", lw=0.6, alpha=0.7, label="PB2002 Pacific" if i == 0 else None)
        else:
            for j, p in enumerate(part.geoms):
                xs, ys = p.exterior.xy
                ax.plot(xs, ys, color="#8d6e63", lw=0.6, alpha=0.7, label="PB2002 Pacific" if i == 0 and j == 0 else None)
    both = cells["intersects_rectangle"] & cells["intersects_pacific"]
    only_r = cells["intersects_rectangle"] & ~cells["intersects_pacific"]
    only_p = cells["intersects_pacific"] & ~cells["intersects_rectangle"]
    ax.scatter(cells.loc[only_p, "lon_center"], cells.loc[only_p, "lat_center"], s=4, c="#1f77b4", alpha=0.45, label="Pacific only")
    ax.scatter(cells.loc[only_r, "lon_center"], cells.loc[only_r, "lat_center"], s=6, c="#d62728", alpha=0.7, label="rectangle only")
    ax.scatter(cells.loc[both, "lon_center"], cells.loc[both, "lat_center"], s=12, c="#ff7f0e", alpha=0.95, label="geometry overlap")
    ax.add_patch(plt.Rectangle((70, 10), 75, 50, fill=False, ec="k", lw=1.0, ls="--", label="70-145E, 10-60N"))
    ax.set_xlim(-180, 180)
    ax.set_ylim(-70, 70)
    ax.set_xlabel("longitude (wrapped to [-180, 180))")
    ax.set_ylabel("latitude")
    ax.set_title("2-degree cells in the union mask")
    ax.legend(loc="lower left", markerscale=2, fontsize=8, frameon=True)
    ax.set_aspect("equal")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140)
    return fig


def plot_hist_active(cells: pd.DataFrame, path: Path | None = None):
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.scatter(cells["lon_center"], cells["lat_center"], s=3, c="#cccccc", alpha=0.4, label="mask, inactive in train period")
    act = cells["historically_active_union"]
    ax.scatter(cells.loc[act, "lon_center"], cells.loc[act, "lat_center"], s=10, c="#2ca02c", alpha=0.85, label="historically active (union, train period)")
    ax.add_patch(plt.Rectangle((70, 10), 75, 50, fill=False, ec="k", lw=1.0, ls="--"))
    ax.set_xlim(-180, 180)
    ax.set_ylim(-70, 70)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Historically active cells: >=1 union event in [1965-01-01, 2009-01-01)")
    ax.legend(loc="lower left", markerscale=2, fontsize=8)
    ax.set_aspect("equal")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140)
    return fig


def plot_prevalence(prev: pd.DataFrame, path: Path | None = None):
    split_order = ["train", "val", "test", "holdout"]
    region_order = ["china_rectangle", "pacific", "union"]
    recs = []
    for _, r in prev.iterrows():
        recs.append({"region": r.region, "split": r.split, "eval_set": "all mask cells", "prevalence": r.prevalence_all})
        recs.append({"region": r.region, "split": r.split, "eval_set": "historically active", "prevalence": r.prevalence_hist_active})
    d = pd.DataFrame(recs)
    d["split"] = pd.Categorical(d["split"], split_order, ordered=True)
    d["region"] = pd.Categorical(d["region"], region_order, ordered=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=False)
    for ax, evs, title in zip(axes, ["all mask cells", "historically active"], ["All masked cells", "Historically active cells"]):
        sub = d[d.eval_set == evs]
        sns.barplot(data=sub, x="split", y="prevalence", hue="region", ax=ax)
        ax.set_title(title)
        ax.set_ylabel("prevalence P(N>=1)")
        ax.set_xlabel("")
        ax.legend(fontsize=8, title="")
    fig.suptitle("Binary-target prevalence by split and region", y=1.02)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140, bbox_inches="tight")
    return fig


def plot_positive_series(series: pd.DataFrame, windows: pd.DataFrame, path: Path | None = None):
    w = windows[["window_id", "window_start"]].drop_duplicates("window_id")
    keep = ["region", "window_id", "n_positive_cells"]
    if "split" in series.columns:
        keep.append("split")
    d = series[keep].merge(w, on="window_id", how="left")
    if "split" not in d.columns:
        d = d.merge(windows[["window_id", "split"]].drop_duplicates("window_id"), on="window_id", how="left")
    fig, axes = plt.subplots(3, 1, figsize=(11, 7.2), sharex=True)
    colors = {"train": "#4c72b0", "val": "#dd8452", "test": "#55a868", "holdout": "#c44e52"}
    for ax, region in zip(axes, ["union", "china_rectangle", "pacific"]):
        sub = d[d.region == region].sort_values("window_id")
        for split, g in sub.groupby("split"):
            ax.plot(g["window_start"], g["n_positive_cells"], lw=0.9, color=colors[split], label=split)
        ax.set_ylabel("positive cells")
        ax.set_title(region)
        ax.legend(loc="upper right", ncol=4, fontsize=8)
    axes[-1].set_xlabel("window start (UTC)")
    fig.suptitle("Number of positive cells per 30-day window (complete-split windows only)", y=1.01)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140, bbox_inches="tight")
    return fig


def plot_longterm_rate_map(rates: pd.DataFrame, cells: pd.DataFrame, path: Path | None = None):
    u = rates[rates.region == "union"].merge(cells[["cell_id", "lon_center", "lat_center"]], on="cell_id")
    fig, ax = plt.subplots(figsize=(11, 5.2))
    sc = ax.scatter(
        u["lon_center"],
        u["lat_center"],
        c=u["p_empirical"],
        s=6,
        cmap="YlOrRd",
        vmin=0,
        vmax=max(0.05, float(np.quantile(u["p_empirical"], 0.99))),
    )
    cb = fig.colorbar(sc, ax=ax, shrink=0.85)
    cb.set_label("empirical P(N>=1) in a 30-day train window")
    ax.add_patch(plt.Rectangle((70, 10), 75, 50, fill=False, ec="k", lw=1.0, ls="--"))
    ax.set_xlim(-180, 180)
    ax.set_ylim(-70, 70)
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Long-term historical rate (train windows only)")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140)
    return fig


def plot_calibration(cal: pd.DataFrame, region: str, eval_set: str, path: Path | None = None):
    models = ["longterm_empirical", "recent_kernel", "constant_prevalence"]
    splits = ["val", "test", "holdout"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharex=True, sharey=True)
    sub0 = cal[(cal.region == region) & (cal.eval_set == eval_set)]
    for ax, split in zip(axes, splits):
        ax.plot([0, 1], [0, 1], ls="--", c="0.6", lw=0.8)
        for model in models:
            s = sub0[(sub0.split == split) & (sub0.model == model)]
            if s.empty:
                continue
            ax.plot(s["mean_predicted"], s["observed_frequency"], marker="o", ms=4, lw=1, label=model)
        ax.set_title(split)
        ax.set_xlabel("mean predicted")
        ax.set_xlim(0, max(0.15, float(sub0["mean_predicted"].max()) * 1.05) if len(sub0) else 1)
        ax.set_ylim(0, max(0.15, float(sub0["observed_frequency"].max()) * 1.05) if len(sub0) else 1)
        ax.set_aspect("equal", adjustable="box")
    axes[0].set_ylabel("observed frequency")
    axes[-1].legend(fontsize=7, loc="upper left")
    fig.suptitle(f"Calibration (quantile bins) — {region}, {eval_set}", y=1.03)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=140, bbox_inches="tight")
    return fig
