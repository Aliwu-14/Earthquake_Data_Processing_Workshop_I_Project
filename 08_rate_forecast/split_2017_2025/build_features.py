"""Build leakage-safe feature tables for the locked 2017-2025 rate-forecast split.

Does not train a model. Does not rewrite source catalogs or the parent
2017-2024 snapshot. Writes only under split_2017_2025/.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from rate_forecast_lib import (
    EARTH_RADIUS_KM,
    KERNEL_CUTOFF_KM,
    KERNEL_SIGMA_KM,
    KERNEL_TAU_DAYS,
    ROOT,
    haversine_km,
    kernel_scores,
    wrap_lon,
)

PREV_SNAPSHOT = Path("/workspace/08_rate_forecast")
PB_BOUNDARIES = Path("/workspace/07_external/context/tectonicplates/PB2002_boundaries.shp")
NS_PER_DAY = 86_400_000_000_000
LOOKBACKS_DAYS = (30, 90, 365)

# Columns that may be used as model features (identifiers/labels/diagnostics excluded).
FEATURE_COLS = [
    "lat_center",
    "lon_sin",
    "lon_cos",
    "in_china_rectangle",
    "in_pacific",
    "in_overlap",
    "region_label",
    "p_empirical_train",
    "historically_active",
    "dist_to_plate_boundary_km",
    "n_m55_cell_30d",
    "n_m55_cell_90d",
    "n_m55_cell_365d",
    "kernel_s",
    "kernel_lambda",
    "days_since_last_m55_cell",
    "no_prior_m55_in_cell",
    "any_m6_800km_365d",
    "n_m6_800km_365d",
]
ID_COLS = [
    "cell_id",
    "window_id",
    "window_start",
    "window_end",
    "split",
    "y",
    "diag_n_events_in_window",
    "lon_center",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lonlat_to_xyz(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lon_r = np.radians(wrap_lon(lon))
    lat_r = np.radians(np.asarray(lat, dtype=float))
    cl = np.cos(lat_r)
    return np.column_stack((cl * np.cos(lon_r), cl * np.sin(lon_r), np.sin(lat_r)))


def _xyz_to_km(xyz_a: np.ndarray, xyz_b: np.ndarray) -> np.ndarray:
    dots = np.clip(np.sum(xyz_a * xyz_b, axis=-1), -1.0, 1.0)
    return EARTH_RADIUS_KM * np.arccos(dots)


def densify_pb_boundaries(step_km: float = 2.0) -> np.ndarray:
    """Densify PB2002 boundary linestrings to ~step_km along the great circle."""
    gdf = gpd.read_file(PB_BOUNDARIES)
    if gdf.crs is not None and gdf.crs.to_string() not in ("EPSG:4326", "OGC:CRS84"):
        gdf = gdf.to_crs("EPSG:4326")
    pts = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        parts = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for part in parts:
            coords = list(part.coords)
            for i in range(1, len(coords)):
                lon1, lat1 = coords[i - 1][0], coords[i - 1][1]
                lon2, lat2 = coords[i][0], coords[i][1]
                p1 = _lonlat_to_xyz(np.array([lon1]), np.array([lat1]))[0]
                p2 = _lonlat_to_xyz(np.array([lon2]), np.array([lat2]))[0]
                cosang = float(np.clip(np.dot(p1, p2), -1.0, 1.0))
                ang = float(np.arccos(cosang))
                dist = ang * EARTH_RADIUS_KM
                n = max(1, int(np.ceil(dist / step_km)))
                if ang < 1e-12:
                    pts.append(p1)
                    continue
                s = np.sin(ang)
                for k in range(n + (i == len(coords) - 1)):
                    t = k / n
                    v = (np.sin((1.0 - t) * ang) * p1 + np.sin(t * ang) * p2) / s
                    nrm = np.linalg.norm(v)
                    if nrm > 0:
                        pts.append(v / nrm)
    xyz = np.unique(np.asarray(pts, dtype=np.float64), axis=0)
    return xyz


def cell_distance_to_boundary(cells: pd.DataFrame, step_km: float = 2.0) -> np.ndarray:
    xyz_line = densify_pb_boundaries(step_km=step_km)
    tree = cKDTree(xyz_line)
    xyz_c = _lonlat_to_xyz(cells["lon_center"].to_numpy(), cells["lat_center"].to_numpy())
    dist_eucl, idx = tree.query(xyz_c, k=1)
    # Convert Euclidean chord in unit-sphere coords to great-circle km.
    # cKDTree returns Euclidean distance between unit vectors: chord = 2 sin(theta/2).
    half = np.clip(dist_eucl / 2.0, 0.0, 1.0)
    theta = 2.0 * np.arcsin(half)
    return theta * EARTH_RADIUS_KM


def _to_utc_ns(s: pd.Series) -> np.ndarray:
    """UTC epoch nanoseconds, independent of pandas datetime resolution (us vs ns)."""
    s = pd.to_datetime(s, utc=True)
    naive = s.dt.tz_convert("UTC").dt.tz_localize(None)
    return naive.to_numpy(dtype="datetime64[ns]").astype(np.int64)


def load_inputs() -> dict:
    windows = pd.read_csv(ROOT / "windows.csv", parse_dates=["window_start", "window_end"])
    windows["window_start"] = pd.to_datetime(windows["window_start"], utc=True)
    windows["window_end"] = pd.to_datetime(windows["window_end"], utc=True)
    cells = pd.read_csv(ROOT / "cells_mask.csv")
    ev = pd.read_csv(ROOT / "events_union_assigned.csv", parse_dates=["time_utc", "window_start", "window_end"])
    ev["time_utc"] = pd.to_datetime(ev["time_utc"], utc=True)
    ev = ev.loc[ev["in_union"]].copy()
    rates = pd.read_csv(ROOT / "longterm_cell_rates.csv")
    rates_u = rates.loc[rates["region"] == "union", ["cell_id", "p_empirical"]].rename(
        columns={"p_empirical": "p_empirical_train"}
    )
    cells = cells.merge(rates_u, on="cell_id", how="left")
    if cells["p_empirical_train"].isna().any():
        raise RuntimeError("union long-term rates missing for some mask cells")
    return {"windows": windows, "cells": cells, "events": ev}


def compute_kernel_panel(ev: pd.DataFrame, windows: pd.DataFrame, cells: pd.DataFrame) -> dict:
    kres = kernel_scores(ev, windows, cells, "union")
    kcells = kres["cells"]
    index = {cid: i for i, cid in enumerate(cells["cell_id"])}
    # Map kernel cell order onto the cells table order.
    remap = np.array([index[cid] for cid in kcells["cell_id"]], dtype=int)
    if not np.array_equal(remap, np.arange(len(cells))):
        # kernel cell order differs; we will scatter into cells order
        pass
    return kres, remap


def build_arrays(inputs: dict) -> tuple[pd.DataFrame, dict]:
    windows_all = inputs["windows"]
    cells = inputs["cells"].reset_index(drop=True)
    ev = inputs["events"].sort_values("time_utc", kind="mergesort").reset_index(drop=True)
    scored = windows_all.loc[windows_all["entirely_in_split"]].sort_values("window_id", kind="mergesort").reset_index(drop=True)

    n_c = len(cells)
    n_w = len(scored)
    cell_index = {cid: i for i, cid in enumerate(cells["cell_id"])}

    kres, remap = compute_kernel_panel(ev, windows_all, cells)
    alpha = float(kres["alpha"])

    ev_ns = _to_utc_ns(ev["time_utc"])
    ev_cell = np.array([cell_index[c] for c in ev["cell_id"]], dtype=int)
    ev_mag = ev["mag"].to_numpy(dtype=float)
    ev_lon = ev["longitude"].to_numpy(dtype=float)
    ev_lat = ev["latitude"].to_numpy(dtype=float)
    is_m6 = ev_mag >= 6.0

    # Neighbor cells within 800 km for each M>=6 event.
    clon = cells["lon_center"].to_numpy()
    clat = cells["lat_center"].to_numpy()
    m6_idx = np.where(is_m6)[0]
    m6_neighbors: dict[int, np.ndarray] = {}
    chunk = 250
    for a in range(0, len(m6_idx), chunk):
        b = min(a + chunk, len(m6_idx))
        sl = m6_idx[a:b]
        d = haversine_km(ev_lon[sl, None], ev_lat[sl, None], clon[None, :], clat[None, :])
        for i, ei in enumerate(sl):
            m6_neighbors[int(ei)] = np.where(d[i] <= KERNEL_CUTOFF_KM)[0].astype(np.int32)

    t_start_ns = _to_utc_ns(scored["window_start"])
    lb_ns = {d: d * NS_PER_DAY for d in LOOKBACKS_DAYS}

    n30 = np.zeros((n_w, n_c), dtype=np.int16)
    n90 = np.zeros((n_w, n_c), dtype=np.int16)
    n365 = np.zeros((n_w, n_c), dtype=np.int16)
    n_m6 = np.zeros((n_w, n_c), dtype=np.int16)
    days_since = np.full((n_w, n_c), np.nan, dtype=np.float32)
    no_prior = np.ones((n_w, n_c), dtype=bool)
    y = np.zeros((n_w, n_c), dtype=np.int8)
    diag_n = np.zeros((n_w, n_c), dtype=np.int16)
    kernel_s = np.zeros((n_w, n_c), dtype=np.float32)

    # Fill kernel and in-window counts from the baseline kernel pass (history already < T.start).
    for wi, wid in enumerate(scored["window_id"].astype(int).to_numpy()):
        s = kres["stored_s"][wid]
        cnt = kres["stored_count"][wid]
        kernel_s[wi, remap] = s.astype(np.float32)
        diag_n[wi, remap] = cnt.astype(np.int16)
        y[wi, remap] = (cnt > 0).astype(np.int8)

    # Rolling history with two / four pointers, walking scored windows in time order.
    # scored is already sorted by window_id, which is chronological.
    cnt30 = np.zeros(n_c, dtype=np.int32)
    cnt90 = np.zeros(n_c, dtype=np.int32)
    cnt365 = np.zeros(n_c, dtype=np.int32)
    cnt_m6 = np.zeros(n_c, dtype=np.int32)
    last_ns = np.zeros(n_c, dtype=np.int64)
    seen = np.zeros(n_c, dtype=bool)
    left30 = left90 = left365 = left_m6 = right = 0
    n_e = len(ev)

    for wi in range(n_w):
        t0 = int(t_start_ns[wi])
        # add events with t < T.start
        while right < n_e and ev_ns[right] < t0:
            c = ev_cell[right]
            cnt30[c] += 1
            cnt90[c] += 1
            cnt365[c] += 1
            last_ns[c] = ev_ns[right]
            seen[c] = True
            if is_m6[right]:
                neigh = m6_neighbors[right]
                if neigh.size:
                    cnt_m6[neigh] += 1
            right += 1
        # drop events that have left each lookback
        cut30 = t0 - lb_ns[30]
        while left30 < right and ev_ns[left30] < cut30:
            cnt30[ev_cell[left30]] -= 1
            left30 += 1
        cut90 = t0 - lb_ns[90]
        while left90 < right and ev_ns[left90] < cut90:
            cnt90[ev_cell[left90]] -= 1
            left90 += 1
        cut365 = t0 - lb_ns[365]
        while left365 < right and ev_ns[left365] < cut365:
            cnt365[ev_cell[left365]] -= 1
            left365 += 1
        while left_m6 < right and ev_ns[left_m6] < cut365:
            if is_m6[left_m6]:
                neigh = m6_neighbors[left_m6]
                if neigh.size:
                    cnt_m6[neigh] -= 1
            left_m6 += 1

        n30[wi] = cnt30.astype(np.int16)
        n90[wi] = cnt90.astype(np.int16)
        n365[wi] = cnt365.astype(np.int16)
        n_m6[wi] = cnt_m6.astype(np.int16)
        no_prior[wi] = ~seen
        if seen.any():
            days_since[wi, seen] = (t0 - last_ns[seen]) / NS_PER_DAY

        if cnt30.min() < 0 or cnt90.min() < 0 or cnt365.min() < 0 or cnt_m6.min() < 0:
            raise RuntimeError("negative rolling count: pointer bug")

    dist_km = cell_distance_to_boundary(cells).astype(np.float32)
    lon_w = wrap_lon(cells["lon_center"].to_numpy())
    lon_sin = np.sin(np.radians(lon_w)).astype(np.float32)
    lon_cos = np.cos(np.radians(lon_w)).astype(np.float32)
    lat = cells["lat_center"].to_numpy(dtype=np.float32)
    lon_center = cells["lon_center"].to_numpy(dtype=np.float32)
    in_rect = cells["intersects_rectangle"].to_numpy(dtype=bool)
    in_pac = cells["intersects_pacific"].to_numpy(dtype=bool)
    in_over = in_rect & in_pac
    region_label = np.where(in_over, "overlap", np.where(in_rect, "rectangle_only", "pacific_only"))
    p_emp = cells["p_empirical_train"].to_numpy(dtype=np.float32)
    hist = cells["historically_active_union"].to_numpy(dtype=bool)
    cell_ids = cells["cell_id"].to_numpy()

    kernel_lambda = (alpha * kernel_s).astype(np.float32)

    # Assemble long table (window-major).
    cell_tile = np.tile(np.arange(n_c, dtype=np.int32), n_w)
    win_tile = np.repeat(np.arange(n_w, dtype=np.int32), n_c)

    def take_cell(arr):
        return np.tile(arr, n_w)

    df = pd.DataFrame(
        {
            "cell_id": cell_ids[cell_tile],
            "window_id": scored["window_id"].to_numpy()[win_tile],
            "window_start": scored["window_start"].to_numpy()[win_tile],
            "window_end": scored["window_end"].to_numpy()[win_tile],
            "split": scored["split"].to_numpy()[win_tile],
            "y": y.ravel(),
            "diag_n_events_in_window": diag_n.ravel(),
            "lon_center": take_cell(lon_center),
            "lat_center": take_cell(lat),
            "lon_sin": take_cell(lon_sin),
            "lon_cos": take_cell(lon_cos),
            "in_china_rectangle": take_cell(in_rect),
            "in_pacific": take_cell(in_pac),
            "in_overlap": take_cell(in_over),
            "region_label": take_cell(region_label),
            "p_empirical_train": take_cell(p_emp),
            "historically_active": take_cell(hist),
            "dist_to_plate_boundary_km": take_cell(dist_km),
            "n_m55_cell_30d": n30.ravel(),
            "n_m55_cell_90d": n90.ravel(),
            "n_m55_cell_365d": n365.ravel(),
            "kernel_s": kernel_s.ravel(),
            "kernel_lambda": kernel_lambda.ravel(),
            "days_since_last_m55_cell": days_since.ravel(),
            "no_prior_m55_in_cell": no_prior.ravel(),
            "any_m6_800km_365d": (n_m6.ravel() > 0),
            "n_m6_800km_365d": n_m6.ravel(),
        }
    )
    # dtypes
    df["split"] = df["split"].astype("category")
    df["region_label"] = df["region_label"].astype("category")
    df["cell_id"] = df["cell_id"].astype("category")
    df["window_id"] = df["window_id"].astype(np.int16)
    df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
    df["window_end"] = pd.to_datetime(df["window_end"], utc=True)
    for col in [
        "n_m55_cell_30d",
        "n_m55_cell_90d",
        "n_m55_cell_365d",
        "n_m6_800km_365d",
        "diag_n_events_in_window",
    ]:
        df[col] = df[col].astype(np.int16)
    df["y"] = df["y"].astype(np.int8)
    meta = {
        "alpha": alpha,
        "n_windows": n_w,
        "n_cells": n_c,
        "n_events_union": int(len(ev)),
        "n_m6": int(is_m6.sum()),
        "kernel_tau_days": KERNEL_TAU_DAYS,
        "kernel_sigma_km": KERNEL_SIGMA_KM,
        "kernel_cutoff_km": KERNEL_CUTOFF_KM,
        "pb_boundary_path": str(PB_BOUNDARIES),
        "pb_densify_step_km": 2.0,
    }
    return df, meta, ev, scored, cells, kres


def leakage_checks(df: pd.DataFrame, ev: pd.DataFrame, scored: pd.DataFrame, cells: pd.DataFrame, kres: dict) -> dict:
    """Spot-check that history features use only origin times strictly before T.start."""
    rng = np.random.default_rng(2043)
    checks = []
    ev = ev.sort_values("time_utc")
    sample_wids = []
    for split in ["train", "val", "test", "holdout"]:
        ids = scored.loc[scored["split"] == split, "window_id"].to_numpy()
        # first, mid, last plus a few random
        picks = [ids[0], ids[len(ids) // 2], ids[-1]]
        if len(ids) > 6:
            picks.extend(rng.choice(ids, size=3, replace=False).tolist())
        sample_wids.extend(int(x) for x in picks)

    # Also include a window known to have a near-boundary event if any.
    mismatches = []
    n_checked = 0
    for wid in sample_wids:
        wrow = scored.loc[scored["window_id"] == wid].iloc[0]
        t0 = wrow["window_start"]
        # 8 cells: mix of active and random
        sub = df.loc[df["window_id"] == wid]
        active_ids = sub.loc[sub["historically_active"], "cell_id"].astype(str)
        picks_c = []
        if len(active_ids):
            picks_c.extend(active_ids.sample(n=min(6, len(active_ids)), random_state=int(wid)).tolist())
        picks_c.extend(sub["cell_id"].astype(str).sample(n=4, random_state=int(wid) + 1).tolist())
        picks_c = list(dict.fromkeys(picks_c))
        for cid in picks_c:
            row = sub.loc[sub["cell_id"].astype(str) == cid].iloc[0]
            hist = ev.loc[(ev["time_utc"] < t0)]
            in_cell = hist.loc[hist["cell_id"].astype(str) == cid]
            for days, col in [(30, "n_m55_cell_30d"), (90, "n_m55_cell_90d"), (365, "n_m55_cell_365d")]:
                man = int(((in_cell["time_utc"] >= t0 - pd.Timedelta(days=days))).sum())
                got = int(row[col])
                n_checked += 1
                if man != got:
                    mismatches.append({"window_id": int(wid), "cell_id": cid, "col": col, "manual": man, "table": got})
            # current-window events must not be in the 30-day history
            in_win = ev.loc[(ev["cell_id"].astype(str) == cid) & (ev["window_id"] == wid)]
            if len(in_win) and int(row["n_m55_cell_30d"]) >= 0:
                late = in_win.loc[in_win["time_utc"] >= t0]
                if len(late):
                    # those late events must not be counted; already implied by t < T
                    pass
            # days since last
            if len(in_cell):
                last = in_cell["time_utc"].max()
                if last >= t0:
                    mismatches.append({"window_id": int(wid), "cell_id": cid, "col": "days_since", "error": "last >= T.start"})
                expected = (t0 - last) / pd.Timedelta(days=1)
                if bool(row["no_prior_m55_in_cell"]):
                    mismatches.append({"window_id": int(wid), "cell_id": cid, "col": "no_prior", "error": "flag true but prior exists"})
                elif not np.isclose(float(row["days_since_last_m55_cell"]), float(expected), rtol=1e-6, atol=1e-3):
                    mismatches.append(
                        {
                            "window_id": int(wid),
                            "cell_id": cid,
                            "col": "days_since_last_m55_cell",
                            "manual": float(expected),
                            "table": float(row["days_since_last_m55_cell"]),
                        }
                    )
            else:
                if not bool(row["no_prior_m55_in_cell"]) or pd.notna(row["days_since_last_m55_cell"]):
                    mismatches.append({"window_id": int(wid), "cell_id": cid, "col": "no_prior", "error": "should be missing"})
            # M6 365d 800km
            m6 = hist.loc[(hist["mag"] >= 6.0) & (hist["time_utc"] >= t0 - pd.Timedelta(days=365))]
            if len(m6):
                d = haversine_km(
                    row["lon_center"],
                    row["lat_center"],
                    m6["longitude"].to_numpy(),
                    m6["latitude"].to_numpy(),
                )
                man_m6 = int((d <= KERNEL_CUTOFF_KM).sum())
            else:
                man_m6 = 0
            if man_m6 != int(row["n_m6_800km_365d"]) or (man_m6 > 0) != bool(row["any_m6_800km_365d"]):
                mismatches.append(
                    {
                        "window_id": int(wid),
                        "cell_id": cid,
                        "col": "n_m6_800km_365d",
                        "manual": man_m6,
                        "table": int(row["n_m6_800km_365d"]),
                    }
                )

    # Kernel s: recompute for 3 windows x 5 cells from the definition.
    tau = KERNEL_TAU_DAYS
    sigma2 = KERNEL_SIGMA_KM ** 2
    kernel_mismatch = 0
    kernel_checked = 0
    for wid in sample_wids[:6]:
        wrow = scored.loc[scored["window_id"] == wid].iloc[0]
        t0 = wrow["window_start"]
        hist = ev.loc[ev["time_utc"] < t0]
        sub = df.loc[df["window_id"] == wid]
        cids = sub["cell_id"].astype(str).sample(n=5, random_state=int(wid)).tolist()
        for cid in cids:
            row = sub.loc[sub["cell_id"].astype(str) == cid].iloc[0]
            if len(hist) == 0:
                man = 0.0
            else:
                d = haversine_km(
                    row["lon_center"],
                    row["lat_center"],
                    hist["longitude"].to_numpy(),
                    hist["latitude"].to_numpy(),
                )
                dt = (t0 - hist["time_utc"]).dt.total_seconds() / 86400.0
                wgt = np.exp(-(d ** 2) / (2.0 * sigma2))
                wgt = np.where(d <= KERNEL_CUTOFF_KM, wgt, 0.0)
                man = float(np.sum(np.exp(-dt / tau) * wgt))
            kernel_checked += 1
            if not np.isclose(man, float(row["kernel_s"]), rtol=1e-5, atol=1e-6):
                kernel_mismatch += 1
                mismatches.append(
                    {
                        "window_id": int(wid),
                        "cell_id": cid,
                        "col": "kernel_s",
                        "manual": man,
                        "table": float(row["kernel_s"]),
                    }
                )

    # Events at or after T.start must never increment history: global assertion via pointer already,
    # plus: for every scored window, current-window events have time >= T.start by construction.
    ev_in_scored = ev.merge(scored[["window_id", "window_start"]], on="window_id", how="inner", suffixes=("", "_w"))
    n_leaky_event_times = int((ev_in_scored["time_utc"] < ev_in_scored["window_start"]).sum())

    return {
        "windows_spot_checked": sample_wids,
        "n_feature_value_checks": n_checked,
        "n_mismatches": len(mismatches),
        "kernel_recomputed": kernel_checked,
        "kernel_mismatches": kernel_mismatch,
        "events_in_scored_windows_with_time_before_window_start": n_leaky_event_times,
        "mismatch_examples": mismatches[:20],
        "passed": len(mismatches) == 0 and n_leaky_event_times == 0,
    }


def prevalence_qa(df: pd.DataFrame) -> dict:
    locked = pd.read_csv(ROOT / "prevalence_by_split_region.csv")
    rows = []
    ok = True
    for split in ["train", "val", "test", "holdout"]:
        for evset, mask in [
            ("all_mask_cells", np.ones(len(df), dtype=bool)),
            ("historically_active", df["historically_active"].to_numpy()),
        ]:
            sub = df.loc[(df["split"] == split) & mask]
            n_pos = int(sub["y"].sum())
            n = int(len(sub))
            prev = n_pos / n if n else float("nan")
            lk = locked.loc[(locked["region"] == "union") & (locked["split"] == split)].iloc[0]
            if evset == "all_mask_cells":
                exp_pos, exp_n, exp_p = int(lk.n_positive_cell_windows_all), int(lk.n_cell_windows_all), float(lk.prevalence_all)
            else:
                exp_pos, exp_n, exp_p = int(lk.n_positive_cell_windows_hist_active), int(lk.n_cell_windows_hist_active), float(lk.prevalence_hist_active)
            match = (n_pos == exp_pos) and (n == exp_n) and (abs(prev - exp_p) < 1e-12)
            ok = ok and match
            rows.append(
                {
                    "split": split,
                    "eval_set": evset,
                    "n_rows": n,
                    "n_positive": n_pos,
                    "prevalence": prev,
                    "locked_n_rows": exp_n,
                    "locked_n_positive": exp_pos,
                    "locked_prevalence": exp_p,
                    "match": match,
                }
            )
    return {"passed": ok, "rows": rows}


def missingness_qa(df: pd.DataFrame) -> dict:
    out = {}
    for split, sub in df.groupby("split", observed=True):
        n = len(sub)
        n_miss = int(sub["no_prior_m55_in_cell"].sum())
        # days_since must be NA iff no_prior
        consistent = bool(
            (sub["no_prior_m55_in_cell"] == sub["days_since_last_m55_cell"].isna()).all()
        )
        filled_zero = int((~sub["no_prior_m55_in_cell"] & sub["days_since_last_m55_cell"].eq(0)).sum())
        out[str(split)] = {
            "n_rows": n,
            "n_no_prior_m55_in_cell": n_miss,
            "frac_no_prior": n_miss / n,
            "days_since_na_consistent_with_flag": consistent,
            "n_days_since_exactly_zero_with_prior": filled_zero,
            "days_since_min_among_observed": float(sub.loc[~sub["no_prior_m55_in_cell"], "days_since_last_m55_cell"].min())
            if n_miss < n
            else None,
        }
    # first train window should be almost all missing
    first_wid = int(df.loc[df["split"] == "train", "window_id"].min())
    first = df.loc[df["window_id"] == first_wid]
    out["first_train_window_id"] = first_wid
    out["first_train_window_frac_no_prior"] = float(first["no_prior_m55_in_cell"].mean())
    out["any_other_nulls_in_feature_cols"] = {
        c: int(df[c].isna().sum())
        for c in FEATURE_COLS
        if c != "days_since_last_m55_cell" and df[c].isna().any()
    }
    return out


def feature_dictionary(meta: dict) -> list[dict]:
    return [
        {"column": "cell_id", "role": "identifier", "dtype": "category", "definition": "2-degree cell id from even-degree half-open edges, C{lon_west}_{lat_south}."},
        {"column": "window_id", "role": "identifier", "dtype": "int16", "definition": "Index of the 30-day bin starting 1965-01-01T00:00:00Z."},
        {"column": "window_start", "role": "identifier", "dtype": "datetime64[ns, UTC]", "definition": "Window start (UTC). History features use only origin times strictly earlier than this instant."},
        {"column": "window_end", "role": "identifier", "dtype": "datetime64[ns, UTC]", "definition": "Window end (UTC, exclusive)."},
        {"column": "split", "role": "identifier", "dtype": "category", "definition": "train / val / test / holdout for complete in-split windows only."},
        {"column": "y", "role": "label", "dtype": "int8", "definition": "1 if at least one union-region M>=5.5 earthquake has origin time in [window_start, window_end) and is assigned to this cell. Not a feature."},
        {"column": "diag_n_events_in_window", "role": "diagnostic_not_a_feature", "dtype": "int16", "definition": "Count of union M>=5.5 events in this cell-window. Uses events inside T, so it must not be used as a model feature."},
        {"column": "lon_center", "role": "cell_metadata_not_euclidean_feature", "dtype": "float32", "definition": "Cell-center longitude in [-180, 180). Stored for maps and distance checks. Do not treat raw lon/lat as Euclidean ML features; use lon_sin and lon_cos."},
        {"column": "lat_center", "role": "feature", "dtype": "float32", "definition": "Cell-center latitude in degrees. Time-invariant."},
        {"column": "lon_sin", "role": "feature", "dtype": "float32", "definition": "sin(lon_center in radians), spherical longitude encoding. Time-invariant."},
        {"column": "lon_cos", "role": "feature", "dtype": "float32", "definition": "cos(lon_center in radians), spherical longitude encoding so cells near +/-180 stay close. Time-invariant."},
        {"column": "in_china_rectangle", "role": "feature", "dtype": "bool", "definition": "Cell intersects the closed 70-145E, 10-60N rectangle under the assignment rule."},
        {"column": "in_pacific", "role": "feature", "dtype": "bool", "definition": "Cell half-open box intersects a PB2002 Pacific polygon part."},
        {"column": "in_overlap", "role": "feature", "dtype": "bool", "definition": "in_china_rectangle and in_pacific."},
        {"column": "region_label", "role": "feature", "dtype": "category", "definition": "rectangle_only, pacific_only, or overlap."},
        {"column": "p_empirical_train", "role": "feature", "dtype": "float32", "definition": "Baseline 1 union long-term empirical P(N>=1): fraction of the 535 complete train windows with at least one union event in this cell. Static, train windows only. No 2025-2026 data."},
        {"column": "historically_active", "role": "feature", "dtype": "bool", "definition": "True if at least one union event in this cell has origin time in [1965-01-01, 2009-01-01). Same rule as the baseline historically-active evaluation set."},
        {"column": "dist_to_plate_boundary_km", "role": "feature", "dtype": "float32", "definition": f"Great-circle distance (km, R={EARTH_RADIUS_KM}) from the cell center to the nearest point on PB2002_boundaries.shp, after densifying lines at {meta.get('pb_densify_step_km', 2)} km along the sphere. Time-invariant. Source: {meta.get('pb_boundary_path')}."},
        {"column": "n_m55_cell_30d", "role": "feature", "dtype": "int16", "definition": "Count of union M>=5.5 events assigned to this cell with origin time in [T.start-30d, T.start)."},
        {"column": "n_m55_cell_90d", "role": "feature", "dtype": "int16", "definition": "Same as n_m55_cell_30d with a 90-day lookback."},
        {"column": "n_m55_cell_365d", "role": "feature", "dtype": "int16", "definition": "Same as n_m55_cell_30d with a 365-day lookback."},
        {"column": "kernel_s", "role": "feature", "dtype": "float32", "definition": f"Neighborhood recent-activity kernel at T.start, identical to baseline 2: sum over union events with t_e < T.start of exp(-(T.start-t_e)/tau) * exp(-d_gc^2 / (2 sigma^2)) for d_gc <= cutoff. tau={KERNEL_TAU_DAYS} d, sigma={KERNEL_SIGMA_KM} km, cutoff={KERNEL_CUTOFF_KM} km, haversine with wrapped longitude. Not refit on val/test."},
        {"column": "kernel_lambda", "role": "feature", "dtype": "float32", "definition": f"alpha * kernel_s, with alpha={meta.get('alpha')} estimated by Poisson MLE on complete train windows only (same as the baseline)."},
        {"column": "days_since_last_m55_cell", "role": "feature", "dtype": "float32", "definition": "Days from the most recent union M>=5.5 in this cell with t < T.start, to T.start. Null (not 0) if no such prior event."},
        {"column": "no_prior_m55_in_cell", "role": "feature", "dtype": "bool", "definition": "Censored/missing flag: True when no union M>=5.5 in this cell exists before T.start. Use together with days_since_last_m55_cell; do not silently fill the delay with 0."},
        {"column": "any_m6_800km_365d", "role": "feature", "dtype": "bool", "definition": "True if at least one union event with mag>=6 occurred within 800 km (haversine to the cell center) in [T.start-365d, T.start)."},
        {"column": "n_m6_800km_365d", "role": "feature", "dtype": "int16", "definition": "Count of those mag>=6 union events within 800 km in the previous 365 days."},
    ]


def write_dictionary(meta: dict) -> None:
    rows = feature_dictionary(meta)
    (ROOT / "feature_dictionary.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Feature dictionary (2017-2025 split)",
        "",
        "Locked spatiotemporal rate-forecasting features. Every event-derived feature for window T uses only earthquakes with origin time strictly before `window_start`. Time-invariant cell attributes may use train-period statistics. `y` and `diag_n_events_in_window` are not features. Kernel hyperparameters were not searched on val/test.",
        "",
        "| column | role | dtype | definition |",
        "| --- | --- | --- | --- |",
    ]
    for r in rows:
        defn = r["definition"].replace("|", "\\|")
        lines.append(f"| `{r['column']}` | {r['role']} | {r['dtype']} | {defn} |")
    (ROOT / "feature_dictionary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tables(df: pd.DataFrame) -> dict[str, Path]:
    all_path = ROOT / "features_all_mask.parquet"
    hist_path = ROOT / "features_hist_active.parquet"
    df.to_parquet(all_path, engine="pyarrow", index=False)
    hist = df.loc[df["historically_active"]].copy()
    hist.to_parquet(hist_path, engine="pyarrow", index=False)
    return {"all_mask": all_path, "hist_active": hist_path}


def row_counts(df: pd.DataFrame) -> dict:
    out = {"all_mask": {}, "hist_active": {}}
    for split, sub in df.groupby("split", observed=True):
        out["all_mask"][str(split)] = {
            "n_rows": int(len(sub)),
            "n_cells": int(sub["cell_id"].nunique()),
            "n_windows": int(sub["window_id"].nunique()),
            "n_positive": int(sub["y"].sum()),
            "prevalence": float(sub["y"].mean()),
        }
        h = sub.loc[sub["historically_active"]]
        out["hist_active"][str(split)] = {
            "n_rows": int(len(h)),
            "n_cells": int(h["cell_id"].nunique()),
            "n_windows": int(h["window_id"].nunique()),
            "n_positive": int(h["y"].sum()),
            "prevalence": float(h["y"].mean()),
        }
    out["all_mask"]["total"] = int(len(df))
    out["hist_active"]["total"] = int(df["historically_active"].sum())
    # region flags are cell-level; report unique cells
    out["region_cell_counts"] = {
        "rectangle_only": int(((~df.drop_duplicates("cell_id")["in_pacific"]) & df.drop_duplicates("cell_id")["in_china_rectangle"]).sum()) if False else None
    }
    cells = df.drop_duplicates("cell_id")
    out["region_cell_counts"] = {
        "n_cells_union": int(len(cells)),
        "n_rectangle": int(cells["in_china_rectangle"].sum()),
        "n_pacific": int(cells["in_pacific"].sum()),
        "n_overlap": int(cells["in_overlap"].sum()),
        "n_hist_active": int(cells["historically_active"].sum()),
    }
    return out


def main() -> int:
    inputs = load_inputs()
    df, meta, ev, scored, cells, kres = build_arrays(inputs)
    paths = write_tables(df)
    write_dictionary(meta)
    leak = leakage_checks(df, ev, scored, cells, kres)
    prev = prevalence_qa(df)
    miss = missingness_qa(df)
    counts = row_counts(df)
    qa = {
        "split_dir": str(ROOT),
        "parent_snapshot_untouched": str(PREV_SNAPSHOT),
        "plate_boundary_distance_included": True,
        "plate_boundary_file": str(PB_BOUNDARIES),
        "feature_columns": FEATURE_COLS,
        "identifier_label_diagnostic_columns": ID_COLS,
        "n_feature_columns": len(FEATURE_COLS),
        "row_counts": counts,
        "prevalence_matches_locked_baseline": prev,
        "missingness": miss,
        "leakage_check": leak,
        "kernel": {
            "tau_days": KERNEL_TAU_DAYS,
            "sigma_km": KERNEL_SIGMA_KM,
            "cutoff_km": KERNEL_CUTOFF_KM,
            "alpha_train_only": meta["alpha"],
        },
        "files": {
            name: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for name, path in {**paths, "feature_dictionary_md": ROOT / "feature_dictionary.md", "feature_dictionary_json": ROOT / "feature_dictionary.json"}.items()
        },
        "no_training": True,
    }
    (ROOT / "qa_features.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # short markdown QA
    lines = [
        "# Feature QA (2017-2025 split)",
        "",
        f"- All-mask rows: {counts['all_mask']['total']:,}",
        f"- Historically-active rows: {counts['hist_active']['total']:,}",
        f"- Feature columns ({len(FEATURE_COLS)}): {', '.join(FEATURE_COLS)}",
        f"- Plate-boundary distance: included from `{PB_BOUNDARIES.name}` (great-circle km, 2 km densify).",
        f"- Prevalence match vs locked baseline: {prev['passed']}",
        f"- Leakage check passed: {leak['passed']} (value checks {leak['n_feature_value_checks']}, kernel recomputes {leak['kernel_recomputed']}, mismatches {leak['n_mismatches']})",
        f"- First train window fraction with no prior event in-cell: {miss['first_train_window_frac_no_prior']:.4f}",
        f"- `features_all_mask.parquet` sha256: {qa['files']['all_mask']['sha256']}",
        f"- `features_hist_active.parquet` sha256: {qa['files']['hist_active']['sha256']}",
        "",
        "Event-derived features use only origin times strictly before window_start. No model was trained.",
    ]
    (ROOT / "qa_features.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("all-mask", counts["all_mask"]["total"], "hist", counts["hist_active"]["total"])
    print("prevalence match", prev["passed"])
    print("leakage passed", leak["passed"], "mismatches", leak["n_mismatches"])
    print("wrote", paths["all_mask"], paths["hist_active"])
    if not prev["passed"] or not leak["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
