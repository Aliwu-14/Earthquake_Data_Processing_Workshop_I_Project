"""DI-3 grid and baseline library for USGS 1965-2024 M>=5.5 rate forecasting.

Does not modify catalogs under 07_external/ or official recount files under
07_ml_readiness/. No ML model is trained here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.validation import make_valid
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss

ROOT = Path("/workspace/08_rate_forecast")
CATALOG_DIR = Path("/workspace/07_external/catalogs")
READY_DIR = Path("/workspace/07_ml_readiness")
PB_SHP = Path("/workspace/07_external/context/tectonicplates/PB2002_plates.shp")

T0 = pd.Timestamp("1965-01-01T00:00:00Z")
SPLIT_BOUNDS = {
    "train": (pd.Timestamp("1965-01-01T00:00:00Z"), pd.Timestamp("2009-01-01T00:00:00Z")),
    "val": (pd.Timestamp("2009-01-01T00:00:00Z"), pd.Timestamp("2017-01-01T00:00:00Z")),
    "test": (pd.Timestamp("2017-01-01T00:00:00Z"), pd.Timestamp("2025-01-01T00:00:00Z")),
    "holdout": (pd.Timestamp("2025-01-01T00:00:00Z"), pd.Timestamp("2026-11-26T07:43:30Z")),
}
WINDOW_DAYS = 30
HOLDOUT_END = SPLIT_BOUNDS["holdout"][1]
LOCK_COUNTS = {"all": 28044, "china_rectangle": 4220, "PB_Pacific": 2188, "overlap": 74, "union": 6334}
HOLDOUT_LOCK = {"all": 949, "union": 190}
PROB_FLOOR = 1e-6
KERNEL_TAU_DAYS = 3.0 * 365.25  # 3 years
KERNEL_SIGMA_KM = 200.0
KERNEL_CUTOFF_KM = 4.0 * KERNEL_SIGMA_KM  # 800 km
EARTH_RADIUS_KM = 6371.0
HALF_OPEN_EPS = 1e-12

WINDOW_SOURCES = [
    "07_usgs_quakes_m55_1965_2016.csv",
    "07_usgs_quakes_m5_2017_2021.csv",
    "07_usgs_quakes_m5_2022_2023.csv",
    "07_usgs_quakes_m5_2024_now.csv",
]


class CountMismatchError(RuntimeError):
    """Locked 1965-2024 region counts were not reproduced; stop rather than redefine the region."""


def wrap_lon(lon: np.ndarray | pd.Series | float) -> np.ndarray:
    """Map longitude to [-180, 180). 180 is wrapped to -180."""
    x = np.asarray(lon, dtype=float)
    return np.mod(x + 180.0, 360.0) - 180.0


def cell_west(lon: np.ndarray | pd.Series | float) -> np.ndarray:
    """West edge of the 2-degree cell containing lon: [2k, 2k+2)."""
    return np.floor(wrap_lon(lon) / 2.0) * 2.0


def cell_south(lat: np.ndarray | pd.Series | float) -> np.ndarray:
    """South edge of the 2-degree cell containing lat: [2k, 2k+2)."""
    return np.floor(np.asarray(lat, dtype=float) / 2.0) * 2.0


def cell_id_from_edges(west: np.ndarray, south: np.ndarray) -> np.ndarray:
    west = np.asarray(west, dtype=int)
    south = np.asarray(south, dtype=int)
    return np.char.add(np.char.add("C", west.astype(str)), np.char.add("_", south.astype(str)))


def haversine_km(lon1, lat1, lon2, lat2) -> np.ndarray:
    """Great-circle distance in km. Longitude difference is wrapped across the dateline."""
    lon1 = np.radians(wrap_lon(lon1))
    lon2 = np.radians(wrap_lon(lon2))
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    dlon = lon2 - lon1
    dlon = np.arctan2(np.sin(dlon), np.cos(dlon))
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def clip_prob(p: np.ndarray, floor: float = PROB_FLOOR) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), floor, 1.0 - floor)


def load_and_verify_catalog() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconstruct 1965-2024 from local USGS windows and attach recount flags.

    2025-2026 events are loaded only from the official holdout flags file.
    """
    frames = []
    for i, name in enumerate(WINDOW_SOURCES):
        d = pd.read_csv(CATALOG_DIR / name, low_memory=False)
        d["id"] = d["id"].astype(str)
        d["mag"] = pd.to_numeric(d["mag"], errors="coerce")
        d["time_utc"] = pd.to_datetime(d["time"], utc=True, format="mixed", errors="coerce")
        d["_src"] = i
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)
    t0, t1 = SPLIT_BOUNDS["train"][0], SPLIT_BOUNDS["test"][1]
    is_eq = raw["type"].astype(str).str.lower() == "earthquake"
    in_time = raw["time_utc"].notna() & (raw["time_utc"] >= t0) & (raw["time_utc"] < t1)
    cand = raw.loc[in_time & is_eq & raw["mag"].ge(5.5)].copy()
    cand = cand.sort_values(["id", "time_utc", "_src"], kind="mergesort")
    cand = cand.drop_duplicates("id", keep="first")

    flags = pd.read_csv(READY_DIR / "usgs2024_event_membership.csv")
    flags["id"] = flags["id"].astype(str)
    n = len(cand)
    n_flag = len(flags)
    if n != LOCK_COUNTS["all"] or n_flag != LOCK_COUNTS["all"]:
        raise CountMismatchError(
            f"Reconstructed n={n}, membership n={n_flag}, locked all={LOCK_COUNTS['all']}"
        )
    if set(cand["id"]) != set(flags["id"]):
        missing = set(flags["id"]) - set(cand["id"])
        extra = set(cand["id"]) - set(flags["id"])
        raise CountMismatchError(
            f"id set mismatch vs membership flags: missing={len(missing)} extra={len(extra)}"
        )

    keep = [
        "id",
        "time_utc",
        "latitude",
        "longitude",
        "depth",
        "mag",
        "magType",
        "type",
        "place",
    ]
    ev = cand[keep].merge(
        flags[
            [
                "id",
                "region",
                "PB2002_plate",
                "PB_Pacific",
                "comparison_membership",
            ]
        ],
        on="id",
        how="inner",
        validate="one_to_one",
    )
    ev = ev.rename(columns={"region": "china_rectangle"})
    ev["china_rectangle"] = ev["china_rectangle"].astype(bool)
    ev["PB_Pacific"] = ev["PB_Pacific"].astype(bool)
    ev["in_union"] = ev["china_rectangle"] | ev["PB_Pacific"]
    ev["catalog_role"] = "main_1965_2024"

    got = {
        "all": int(len(ev)),
        "china_rectangle": int(ev["china_rectangle"].sum()),
        "PB_Pacific": int(ev["PB_Pacific"].sum()),
        "overlap": int((ev["china_rectangle"] & ev["PB_Pacific"]).sum()),
        "union": int(ev["in_union"].sum()),
    }
    if got != LOCK_COUNTS:
        raise CountMismatchError(f"Locked 1965-2024 counts not reproduced: got={got} locked={LOCK_COUNTS}")

    hold = pd.read_csv(CATALOG_DIR / "07_usgs_quakes_m55_2025_2026_holdout_flags.csv")
    hold["id"] = hold["id"].astype(str)
    hold["mag"] = pd.to_numeric(hold["mag"], errors="coerce")
    hold["time_utc"] = pd.to_datetime(hold["time"], utc=True, format="mixed", errors="coerce")
    hold["china_rectangle"] = hold["china_rectangle"].astype(bool)
    hold["PB_Pacific"] = hold["PB_Pacific"].astype(bool)
    hold["in_union"] = hold["in_union"].astype(bool)
    if "comparison_membership" not in hold.columns:
        hold["comparison_membership"] = np.where(
            hold["china_rectangle"] & hold["PB_Pacific"],
            "overlap",
            np.where(
                hold["china_rectangle"],
                "china_rectangle_only",
                np.where(hold["PB_Pacific"], "pacific_only", "neither"),
            ),
        )
    hold["catalog_role"] = "later_holdout_2025_2026"
    hgot = {"all": int(len(hold)), "union": int(hold["in_union"].sum())}
    if hgot != HOLDOUT_LOCK:
        raise CountMismatchError(f"Holdout counts not reproduced: got={hgot} locked={HOLDOUT_LOCK}")
    # holdout must not leak into the main table
    if set(hold["id"]) & set(ev["id"]):
        raise CountMismatchError("Holdout ids overlap the 1965-2024 main table")
    if (hold["time_utc"] < SPLIT_BOUNDS["holdout"][0]).any() or (hold["time_utc"] >= HOLDOUT_END).any():
        raise CountMismatchError("Holdout event time is outside [2025-01-01, fetch end)")

    cols = [
        "id",
        "time_utc",
        "latitude",
        "longitude",
        "depth",
        "mag",
        "magType",
        "type",
        "place",
        "china_rectangle",
        "PB_Pacific",
        "in_union",
        "comparison_membership",
        "PB2002_plate",
        "catalog_role",
    ]
    # PB2002_plate may exist in holdout
    if "PB2002_plate" not in hold.columns:
        hold["PB2002_plate"] = pd.NA
    ev = ev[cols].sort_values(["time_utc", "id"], kind="mergesort").reset_index(drop=True)
    hold = hold[cols].sort_values(["time_utc", "id"], kind="mergesort").reset_index(drop=True)
    return ev, hold


def build_windows() -> pd.DataFrame:
    """Fixed 30-day bins from 1965-01-01T00:00:00Z. A split owns a window only if it is entirely inside."""
    rows = []
    i = 0
    max_start = HOLDOUT_END
    while True:
        start = T0 + pd.Timedelta(days=WINDOW_DAYS * i)
        end = T0 + pd.Timedelta(days=WINDOW_DAYS * (i + 1))
        if start >= max_start:
            break
        split = "none"
        for name, (a, b) in SPLIT_BOUNDS.items():
            if (start >= a) and (end <= b):
                split = name
                break
        # classify straddle / leftover for documentation
        note = split
        if split == "none":
            if end > SPLIT_BOUNDS["train"][1] and start < SPLIT_BOUNDS["train"][1] and start >= SPLIT_BOUNDS["train"][0]:
                note = "straddle_train_val"
            elif end > SPLIT_BOUNDS["val"][1] and start < SPLIT_BOUNDS["val"][1] and start >= SPLIT_BOUNDS["val"][0]:
                note = "straddle_val_test"
            elif end > SPLIT_BOUNDS["test"][1] and start < SPLIT_BOUNDS["test"][1] and start >= SPLIT_BOUNDS["test"][0]:
                note = "straddle_test_holdout"
            elif start >= SPLIT_BOUNDS["holdout"][0] and end > HOLDOUT_END:
                note = "incomplete_holdout"
            else:
                note = "outside_or_gap"
        rows.append(
            {
                "window_id": i,
                "window_start": start,
                "window_end": end,
                "split": split,
                "boundary_note": note,
                "entirely_in_split": split != "none",
            }
        )
        i += 1
        if i > 10000:
            raise RuntimeError("window generation did not terminate")
    w = pd.DataFrame(rows)
    return w


def _even_range_closed(vmin: float, vmax: float) -> np.ndarray:
    """Even-degree west/south edges of half-open cells that receive any point of closed [vmin, vmax]."""
    w0 = int(np.floor(vmin / 2.0) * 2)
    w1 = int(np.floor(vmax / 2.0) * 2)
    if w1 < w0:
        return np.array([], dtype=int)
    return np.arange(w0, w1 + 2, 2, dtype=int)


def load_pacific_polygon():
    gdf = gpd.read_file(PB_SHP)
    gdf = gdf.to_crs("EPSG:4326")
    gdf["geometry"] = gdf.geometry.map(make_valid)
    diss = gdf.dissolve(by="PlateName")
    if "Pacific" not in diss.index:
        raise RuntimeError(f"Pacific plate not found in PB2002. Names={list(diss.index)}")
    geom = make_valid(diss.loc["Pacific"].geometry)
    return geom


def build_cell_mask() -> pd.DataFrame:
    """Global 2-degree even-aligned cells that can receive a union-region point.

    Assignment rule (documented):
    - lon is wrapped to [-180, 180); 180 maps to -180.
    - cell west = 2*floor(lon/2), south = 2*floor(lat/2), half-open [edge, edge+2).
    - A cell is in the rectangle mask iff some point of the closed rectangle
      70<=lon<=145, 10<=lat<=60 would be assigned to it.
    - A cell is in the Pacific mask iff the half-open cell box intersects a
      PB2002 Pacific polygon part (parts are already split at the dateline;
      [178, 180) and [-180, -178) stay separate cells).
    - Union mask = rectangle or Pacific.
    """
    # Rectangle cells from the assignment rule (closed inclusive region).
    rec_west = _even_range_closed(70.0, 145.0)
    rec_south = _even_range_closed(10.0, 60.0)
    rec_pairs = {(int(w), int(s)) for w in rec_west for s in rec_south}

    pacific = load_pacific_polygon()
    parts = list(pacific.geoms) if pacific.geom_type == "MultiPolygon" else [pacific]
    pac_pairs = set()
    for part in parts:
        minx, miny, maxx, maxy = part.bounds
        # Keep coordinates in [-180, 180]; a maxx slightly above 180 is the antimeridian
        minx = max(-180.0, minx)
        maxx = min(180.0, maxx)
        # lon=180 is wrapped to -180 and belongs to cell [-180,-178), already covered by the west part.
        lon_vmax = 180.0 - HALF_OPEN_EPS if maxx >= 180.0 else maxx
        for w in _even_range_closed(minx, lon_vmax):
            if w < -180 or w > 178:
                continue
            for s in _even_range_closed(miny, maxy):
                # half-open test box, so the east/north edges belong to the next cell
                poly = box(float(w), float(s), float(w) + 2.0 - HALF_OPEN_EPS, float(s) + 2.0 - HALF_OPEN_EPS)
                if part.intersects(poly):
                    pac_pairs.add((int(w), int(s)))

    all_pairs = sorted(rec_pairs | pac_pairs)
    rows = []
    for w, s in all_pairs:
        rows.append(
            {
                "cell_id": f"C{w}_{s}",
                "lon_west": w,
                "lon_east": w + 2,
                "lat_south": s,
                "lat_north": s + 2,
                "lon_center": w + 1.0,
                "lat_center": s + 1.0,
                "intersects_rectangle": (w, s) in rec_pairs,
                "intersects_pacific": (w, s) in pac_pairs,
            }
        )
    cells = pd.DataFrame(rows)
    cells["in_union_mask"] = cells["intersects_rectangle"] | cells["intersects_pacific"]
    return cells


def assign_events(events: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    ev = events.copy()
    ev["lon_wrapped"] = wrap_lon(ev["longitude"].to_numpy())
    ev["lon_west"] = cell_west(ev["lon_wrapped"]).astype(int)
    ev["lat_south"] = cell_south(ev["latitude"].to_numpy()).astype(int)
    ev["cell_id"] = [f"C{w}_{s}" for w, s in zip(ev["lon_west"], ev["lat_south"], strict=True)]
    delta_days = (ev["time_utc"] - T0) / pd.Timedelta(days=1)
    ev["window_id"] = np.floor(delta_days.to_numpy() / WINDOW_DAYS).astype(int)
    wmeta = windows[["window_id", "window_start", "window_end", "split", "boundary_note", "entirely_in_split"]]
    ev = ev.merge(wmeta, on="window_id", how="left", validate="many_to_one")
    ev["in_train_period"] = (ev["time_utc"] >= SPLIT_BOUNDS["train"][0]) & (
        ev["time_utc"] < SPLIT_BOUNDS["train"][1]
    )
    return ev


def mark_historical_activity(cells: pd.DataFrame, ev_assigned: pd.DataFrame) -> pd.DataFrame:
    """Historically active: at least one event in [1965-01-01, 2009-01-01) in that region and cell."""
    out = cells.copy()
    train_ev = ev_assigned.loc[ev_assigned["in_train_period"]].copy()
    for col, flag in [
        ("historically_active_union", "in_union"),
        ("historically_active_rectangle", "china_rectangle"),
        ("historically_active_pacific", "PB_Pacific"),
    ]:
        ids = set(train_ev.loc[train_ev[flag], "cell_id"])
        out[col] = out["cell_id"].isin(ids)
    return out


def _region_event_mask(df: pd.DataFrame, region: str) -> pd.Series:
    if region == "union":
        return df["in_union"].astype(bool)
    if region == "china_rectangle":
        return df["china_rectangle"].astype(bool)
    if region == "pacific":
        return df["PB_Pacific"].astype(bool)
    raise ValueError(region)


def _region_cell_mask(cells: pd.DataFrame, region: str) -> pd.Series:
    if region == "union":
        return cells["in_union_mask"].astype(bool)
    if region == "china_rectangle":
        return cells["intersects_rectangle"].astype(bool)
    if region == "pacific":
        return cells["intersects_pacific"].astype(bool)
    raise ValueError(region)


def _region_hist_col(region: str) -> str:
    return {
        "union": "historically_active_union",
        "china_rectangle": "historically_active_rectangle",
        "pacific": "historically_active_pacific",
    }[region]


def summarize_counts(ev: pd.DataFrame, windows: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    rows = []
    regions = ["china_rectangle", "pacific", "union"]
    splits = ["train", "val", "test", "holdout"]
    for region in regions:
        csub = cells.loc[_region_cell_mask(cells, region)]
        ev_r = ev.loc[_region_event_mask(ev, region)]
        hist_col = _region_hist_col(region)
        n_cells = int(len(csub))
        n_hist = int(csub[hist_col].sum())
        for split in splits:
            wids = windows.loc[windows["split"] == split, "window_id"]
            n_win = int(len(wids))
            ev_s = ev_r.loc[ev_r["split"] == split]
            # events whose assigned window is entirely in the split
            n_events = int(len(ev_s))
            # positive cell-windows
            pos = ev_s.groupby(["window_id", "cell_id"]).size().reset_index(name="n")
            # keep positives only if the cell is in the region mask (should always hold for union events)
            pos = pos[pos["cell_id"].isin(set(csub["cell_id"]))]
            n_pos = int(len(pos))
            n_cw = n_cells * n_win
            n_pos_hist = int(pos[pos["cell_id"].isin(set(csub.loc[csub[hist_col], "cell_id"]))].shape[0])
            n_cw_hist = n_hist * n_win
            rows.append(
                {
                    "region": region,
                    "split": split,
                    "n_cells_all": n_cells,
                    "n_windows": n_win,
                    "n_cell_windows_all": n_cw,
                    "n_events_in_complete_windows": n_events,
                    "n_positive_cell_windows_all": n_pos,
                    "prevalence_all": (n_pos / n_cw) if n_cw else np.nan,
                    "n_cells_hist_active": n_hist,
                    "n_cell_windows_hist_active": n_cw_hist,
                    "n_positive_cell_windows_hist_active": n_pos_hist,
                    "prevalence_hist_active": (n_pos_hist / n_cw_hist) if n_cw_hist else np.nan,
                    "n_unique_positive_cells_in_split": int(pos["cell_id"].nunique()) if len(pos) else 0,
                }
            )
    return pd.DataFrame(rows)


def boundary_event_counts(ev: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    notes = windows[["window_id", "boundary_note", "split", "window_start", "window_end"]]
    ev_u = ev.loc[ev["in_union"]].merge(notes, on="window_id", how="left", suffixes=("", "_w"))
    rows = []
    for note, g in ev_u.groupby("boundary_note"):
        rows.append(
            {
                "boundary_note": note,
                "n_union_events": int(len(g)),
                "n_rectangle": int(g["china_rectangle"].sum()),
                "n_pacific": int(g["PB_Pacific"].sum()),
                "window_ids": ",".join(str(i) for i in sorted(g["window_id"].unique())),
            }
        )
    return pd.DataFrame(rows).sort_values("boundary_note")


def longterm_rates(ev: pd.DataFrame, windows: pd.DataFrame, cells: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Static per-cell empirical P(N>=1) and Poisson 1-exp(-lambda) from complete train windows only."""
    train_wids = windows.loc[windows["split"] == "train", "window_id"]
    n_win = int(len(train_wids))
    out = {}
    for region in ["china_rectangle", "pacific", "union"]:
        csub = cells.loc[_region_cell_mask(cells, region), ["cell_id"]].copy()
        ev_s = ev.loc[_region_event_mask(ev, region) & (ev["split"] == "train")]
        grp = ev_s.groupby(["cell_id", "window_id"]).size().reset_index(name="n")
        pos = grp.groupby("cell_id").agg(n_pos_windows=("window_id", "nunique"), n_events=("n", "sum"))
        tab = csub.merge(pos, on="cell_id", how="left")
        tab["n_pos_windows"] = tab["n_pos_windows"].fillna(0).astype(int)
        tab["n_events"] = tab["n_events"].fillna(0).astype(int)
        tab["n_train_windows"] = n_win
        tab["p_empirical"] = tab["n_pos_windows"] / n_win
        tab["lambda_poisson"] = tab["n_events"] / n_win
        tab["p_poisson"] = 1.0 - np.exp(-tab["lambda_poisson"])
        tab["region"] = region
        out[region] = tab
    return out


def _spatial_weights(events_region: pd.DataFrame, cells_region: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """For each event, (cell_local_index array, gaussian weights) within cutoff."""
    clon = cells_region["lon_center"].to_numpy()
    clat = cells_region["lat_center"].to_numpy()
    elon = events_region["longitude"].to_numpy()
    elat = events_region["latitude"].to_numpy()
    weights = []
    sigma2 = KERNEL_SIGMA_KM ** 2
    # Block over events to keep memory bounded
    # n_cells is a few thousand; compute all distances per event-chunk
    n_e = len(events_region)
    chunk = 500
    all_idx = [None] * n_e
    all_w = [None] * n_e
    for a in range(0, n_e, chunk):
        b = min(a + chunk, n_e)
        # distances (b-a, n_cells)
        d = haversine_km(elon[a:b, None], elat[a:b, None], clon[None, :], clat[None, :])
        for i in range(b - a):
            near = np.where(d[i] <= KERNEL_CUTOFF_KM)[0]
            if near.size == 0:
                all_idx[a + i] = np.array([], dtype=int)
                all_w[a + i] = np.array([], dtype=float)
            else:
                all_idx[a + i] = near.astype(int)
                all_w[a + i] = np.exp(-(d[i, near] ** 2) / (2.0 * sigma2))
    return list(zip(all_idx, all_w, strict=True))


def kernel_scores(
    ev: pd.DataFrame,
    windows: pd.DataFrame,
    cells: pd.DataFrame,
    region: str,
) -> dict:
    """Operational space-time smoothing. History uses only origin times strictly before window start.

    s_c(T) = sum_{e: t_e < T.start} exp(-(T.start-t_e)/tau) * exp(-d(c,e)^2 / (2 sigma^2))
    alpha is a single Poisson scale fit on complete train windows only:
        alpha = N_train / sum_{c,T in train} s_c(T)
    lambda = alpha * s,  P = 1 - exp(-lambda).
    """
    csub = cells.loc[_region_cell_mask(cells, region)].reset_index(drop=True)
    ev_r = ev.loc[_region_event_mask(ev, region)].sort_values("time_utc", kind="mergesort").reset_index(drop=True)
    cell_index = {cid: i for i, cid in enumerate(csub["cell_id"])}
    n_cells = len(csub)
    weights = _spatial_weights(ev_r, csub)
    ev_times = ev_r["time_utc"].to_numpy()
    ev_wids = ev_r["window_id"].to_numpy()

    # all windows in time order (including non-scored) to update history
    w_all = windows.sort_values("window_id", kind="mergesort").reset_index(drop=True)
    # map window_id -> list of event indices
    ev_by_win: dict[int, np.ndarray] = {}
    for i, wid in enumerate(ev_wids):
        ev_by_win.setdefault(int(wid), []).append(i)
    ev_by_win = {k: np.asarray(v, dtype=int) for k, v in ev_by_win.items()}

    tau = KERNEL_TAU_DAYS
    decay_step = np.exp(-WINDOW_DAYS / tau)
    s = np.zeros(n_cells, dtype=float)
    # store scores for every entirely-in-split window
    stored_s: dict[int, np.ndarray] = {}
    stored_count: dict[int, np.ndarray] = {}  # observed counts per cell (for train alpha and diagnostics)

    ev_cells = ev_r["cell_id"].to_numpy()
    ev_cell_loc = np.array([cell_index.get(cid, -1) for cid in ev_cells], dtype=int)

    for row in w_all.itertuples(index=False):
        wid = int(row.window_id)
        start = row.window_start
        # s is already at 'start'
        if row.split != "none":
            stored_s[wid] = s.copy()
            counts = np.zeros(n_cells, dtype=int)
            for ei in ev_by_win.get(wid, np.array([], dtype=int)):
                loc = ev_cell_loc[ei]
                if loc >= 0:
                    counts[loc] += 1
            stored_count[wid] = counts
        # advance to next window start: decay, then add events from this window
        next_start = row.window_end  # next window starts where this one ends
        s *= decay_step
        for ei in ev_by_win.get(wid, np.array([], dtype=int)):
            dt_days = (next_start - ev_r.at[ei, "time_utc"]) / pd.Timedelta(days=1)
            # ev time is in [start, end); next_start = end, so dt in (0, 30]
            k_t = np.exp(-float(dt_days) / tau)
            idx, wgt = weights[ei]
            if idx.size:
                s[idx] += wgt * k_t

    train_wids = windows.loc[windows["split"] == "train", "window_id"].astype(int).tolist()
    sum_s = 0.0
    n_obs = 0
    for wid in train_wids:
        sum_s += float(stored_s[wid].sum())
        n_obs += int(stored_count[wid].sum())
    alpha = (n_obs / sum_s) if sum_s > 0 else 0.0
    return {
        "region": region,
        "cells": csub,
        "stored_s": stored_s,
        "stored_count": stored_count,
        "alpha": float(alpha),
        "n_train_events": n_obs,
        "sum_s_train": float(sum_s),
        "n_cells": n_cells,
    }


def pack_panel(windows: pd.DataFrame, kernel_res: dict, rates: pd.DataFrame, split: str, hist_mask: np.ndarray | None):
    """Build y, p_empirical, p_poisson, p_kernel, p_const for a split (optionally hist-active cells)."""
    wids = windows.loc[windows["split"] == split, "window_id"].astype(int).tolist()
    cells = kernel_res["cells"]
    if hist_mask is None:
        col_idx = np.arange(len(cells))
    else:
        col_idx = np.where(hist_mask)[0]
    n_c = len(col_idx)
    n_w = len(wids)
    y = np.zeros((n_w, n_c), dtype=np.int8)
    s = np.zeros((n_w, n_c), dtype=float)
    for i, wid in enumerate(wids):
        y[i] = (kernel_res["stored_count"][wid][col_idx] > 0).astype(np.int8)
        s[i] = kernel_res["stored_s"][wid][col_idx]
    lam = kernel_res["alpha"] * s
    p_kernel = 1.0 - np.exp(-lam)
    # align long-term rates to kernel cell order then subset
    rtab = rates.set_index("cell_id").loc[cells["cell_id"].to_numpy()]
    p_emp = np.repeat(rtab["p_empirical"].to_numpy()[col_idx][None, :], n_w, axis=0)
    p_pois = np.repeat(rtab["p_poisson"].to_numpy()[col_idx][None, :], n_w, axis=0)
    yf = y.ravel()
    # constant prevalence from TRAIN for this evaluation set
    # computed outside if provided; placeholder here
    return {
        "wids": wids,
        "col_idx": col_idx,
        "y": y,
        "lambda_kernel": lam,
        "p_kernel": p_kernel,
        "p_empirical": p_emp,
        "p_poisson": p_pois,
        "n_windows": n_w,
        "n_cells": n_c,
        "n_events": int(sum(int(kernel_res["stored_count"][wid][col_idx].sum()) for wid in wids)),
    }


def train_constant(kernel_res: dict, rates: pd.DataFrame, windows: pd.DataFrame, hist_mask: np.ndarray | None) -> dict:
    """Train-set prevalence and mean Poisson lambda for a cell subset."""
    wids = windows.loc[windows["split"] == "train", "window_id"].astype(int).tolist()
    cells = kernel_res["cells"]
    col_idx = np.arange(len(cells)) if hist_mask is None else np.where(hist_mask)[0]
    n_pos = 0
    n_cw = len(wids) * len(col_idx)
    n_events = 0
    for wid in wids:
        cnt = kernel_res["stored_count"][wid][col_idx]
        n_pos += int((cnt > 0).sum())
        n_events += int(cnt.sum())
    p = n_pos / n_cw if n_cw else np.nan
    lam = n_events / n_cw if n_cw else np.nan
    return {"p_const": p, "lambda_const": lam, "n_pos": n_pos, "n_cw": n_cw, "n_events": n_events}


def score_panel(y: np.ndarray, p: np.ndarray, p_ref: np.ndarray, name: str, floor: float = PROB_FLOOR) -> dict:
    yt = np.asarray(y).ravel().astype(int)
    pt = clip_prob(np.asarray(p).ravel(), floor)
    pr = clip_prob(np.asarray(p_ref).ravel(), floor)
    n = yt.size
    n_pos = int(yt.sum())
    brier = float(np.mean((pt - yt) ** 2))
    brier_ref = float(np.mean((pr - yt) ** 2))
    ll = float(np.sum(yt * np.log(pt) + (1 - yt) * np.log(1 - pt)))
    ll_ref = float(np.sum(yt * np.log(pr) + (1 - yt) * np.log(1 - pr)))
    # sklearn log_loss is mean log-loss; keep both
    mean_logloss = float(-ll / n) if n else np.nan
    try:
        prauc = float(average_precision_score(yt, pt)) if n_pos > 0 else float("nan")
    except ValueError:
        prauc = float("nan")
    return {
        "model": name,
        "n_cell_windows": n,
        "n_positive": n_pos,
        "prevalence": n_pos / n if n else np.nan,
        "brier": brier,
        "brier_const": brier_ref,
        "brier_skill_vs_const": (1.0 - brier / brier_ref) if brier_ref > 0 else np.nan,
        "log_likelihood": ll,
        "log_likelihood_const": ll_ref,
        "rel_log_likelihood_vs_const": ll - ll_ref,
        "mean_log_loss": mean_logloss,
        "mean_log_loss_const": float(-ll_ref / n) if n else np.nan,
        "pr_auc": prauc,
    }


def calibration_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    yt = np.asarray(y).ravel().astype(int)
    pt = clip_prob(np.asarray(p).ravel())
    # equal-width bins on [0,1] plus a dedicated near-zero bin is messy when most mass is tiny;
    # use quantile bins of predicted probability, unique edges.
    qs = np.quantile(pt, np.linspace(0, 1, n_bins + 1))
    qs = np.unique(qs)
    if len(qs) < 3:
        qs = np.array([0.0, 0.5, 1.0])
    qs[0], qs[-1] = 0.0, 1.0
    # right-closed except first
    bins = pd.cut(pt, bins=qs, include_lowest=True, duplicates="drop")
    recs = []
    for cat in bins.categories:
        m = bins == cat
        if not m.any():
            continue
        recs.append(
            {
                "bin": str(cat),
                "n": int(m.sum()),
                "n_positive": int(yt[m].sum()),
                "mean_predicted": float(pt[m].mean()),
                "observed_frequency": float(yt[m].mean()),
            }
        )
    return pd.DataFrame(recs)


def methodology_record() -> dict:
    return {
        "target": "For each 2-degree x 30-day cell, P(at least one M>=5.5 earthquake in the study region subset assigned to that cell-window).",
        "main_catalog": "Reconstructed USGS 1965-2024 M>=5.5 earthquakes from local four-window files, flags from usgs2024_event_membership.csv. Official B table sha256 1018e3856fcf15c791f4136fb833f0b4937868e3e6c1f54ead6503529289f265 was not present as a file on the box; counts were required to match 28044/4220/2188/74/6334.",
        "study_region": "Union of closed rectangle 70<=lon<=145, 10<=lat<=60 and PB2002 Pacific point-in-polygon (within only, no nearest fill). Intersection events counted once.",
        "spatial_grid": "Global 2-degree grid aligned to even degrees. lon wrapped to [-180, 180). Cell [2k, 2k+2) x [2m, 2m+2). Cells [178,180) and [-180,-178) remain distinct; dateline adjacency is handled in the spherical kernel, not by merging cells. Mask = cells that can receive at least one union-region point (rectangle assignment rule and/or half-open intersection with Pacific polygon parts already split at the dateline).",
        "time_windows": "Fixed 30-day bins starting 1965-01-01T00:00:00Z, not calendar months. A window belongs to a split only if [start,end) lies entirely inside the split interval. Events assigned by origin time in [window_start, window_end).",
        "splits": {
            "train": "[1965-01-01, 2009-01-01)",
            "val": "[2009-01-01, 2017-01-01)",
            "test": "[2017-01-01, 2025-01-01)",
            "holdout": "[2025-01-01, 2026-11-26T07:43:30Z] official fetch end",
        },
        "historical_activity": "A cell is historically active for a region if at least one region event has origin time in [1965-01-01, 2009-01-01) and is assigned to that cell (includes events in the train/val straddling window that still fall before 2009-01-01).",
        "baseline_1_longterm": "Per-cell empirical fraction of complete train windows with >=1 region event, p = n_pos_windows / n_train_windows. Secondary Poisson diagnostic p = 1-exp(-lambda) with lambda = n_train_events / n_train_windows. Both use train windows only. No 2025-2026 data enter these estimates.",
        "baseline_2_recent": {
            "formula": "s_c(T)=sum_{e: t_e < T.start} exp(-(T.start-t_e)/tau) * exp(-d_gc(c,e)^2 / (2 sigma^2)); lambda=alpha*s; P=1-exp(-lambda). d_gc is haversine distance to the cell center with wrapped longitude (not Euclidean lon/lat; no StandardScaler).",
            "tau_days": KERNEL_TAU_DAYS,
            "sigma_km": KERNEL_SIGMA_KM,
            "cutoff_km": KERNEL_CUTOFF_KM,
            "alpha": "Single Poisson scale per region, MLE on complete train windows: alpha = N_train / sum_{c,T in train} s_c(T). Not refit on val/test/holdout.",
            "leakage": "For window T, only events with origin time strictly before T.start. Scoring val may use train history; test may use train+val+earlier test; holdout may use everything before T including 2017-2024 and earlier holdout windows.",
        },
        "constant_baseline": "Global-constant prevalence estimated on the same train cell-windows as the evaluation set (all mask cells, or historically active cells). Same p for every cell and window in that evaluation.",
        "probability_floor": f"Metrics clip p to [{PROB_FLOOR}, {1-PROB_FLOOR}] so log-loss is finite when a baseline predicts 0.",
        "evaluation": "Never report accuracy as a headline metric. Metrics: Brier, log-likelihood and mean log-loss, relative log-likelihood vs the constant prevalence baseline, PR-AUC (sklearn average_precision_score), plus a quantile-bin calibration table.",
        "region_scoring": "China rectangle, Pacific, and union are scored separately: region mask cells, region events as labels, and baselines estimated from that region's train events/cells.",
    }


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
