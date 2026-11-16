#!/usr/bin/env python3
"""Retrieve official public external datasets for BNBU DS 2043 option 07.

Writes only under /workspace/07_external/. Does not modify ProjectData,
acquired archives, or /workspace/07_fine_clean/. Does not clean or analyze.

Re-run:
  python3 /workspace/07_external/retrieve_07_external.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path("/workspace/07_external")
CATALOGS = ROOT / "catalogs"
IMPACT = ROOT / "impact"
CONTEXT = ROOT / "context"
TMP = ROOT / "_tmp_download"
LOG_PATH = ROOT / "retrieve_log.txt"

LOCAL_USGS_2022 = Path("/workspace/dpw1_acquired/07_usgs_quakes_m5_2022_2023.csv")
EXPECTED_USGS_2022_SHA256 = (
    "2bbb2c6bd07817bdc8343db5089f9d6b26e1629f68e7a9b9a365c0626ff9b57f"
)

USER_AGENT = (
    "BNBU-DS2043-earthquake-external-collection/1.0 "
    "(academic course project; educational use)"
)
USGS_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USGS_COUNT = "https://earthquake.usgs.gov/fdsnws/event/1/count"
NCEI_BASE = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1"
NCEI_PAGE_SIZE = 200

CST = timezone(timedelta(hours=8), name="CST")

# Captured at process start so every file in this run shares one retrieval clock.
RETRIEVAL_UTC = datetime.now(timezone.utc).replace(microsecond=0)
RETRIEVAL_CST = RETRIEVAL_UTC.astimezone(CST)
USGS_NOW_ENDTIME = RETRIEVAL_UTC.strftime("%Y-%m-%dT%H:%M:%S")

STATS: dict[str, Any] = {
    "retrieval_utc": RETRIEVAL_UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "retrieval_cst": RETRIEVAL_CST.strftime("%Y-%m-%d %H:%M:%S CST (UTC+8)"),
    "usgs_now_endtime_utc": USGS_NOW_ENDTIME,
    "files": {},
    "notes": [],
    "failures": [],
}


def log(msg: str) -> None:
    line = f"[{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S CST')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def make_session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=8,
        connect=8,
        read=8,
        status=8,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    sess.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return sess


SESSION = make_session()


def http_get(
    url: str,
    *,
    params: dict | None = None,
    timeout: int = 180,
    sleep_after: float = 0.0,
    expect_ok: bool = True,
) -> requests.Response:
    last_err: Exception | None = None
    for attempt in range(1, 9):
        try:
            resp = SESSION.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = min(60, 3 * attempt)
                log(f"HTTP 429 rate limit on {resp.url} — sleep {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            if expect_ok and resp.status_code >= 400:
                wait = min(40, 2 * attempt)
                log(
                    f"HTTP {resp.status_code} on {resp.url} — sleep {wait}s "
                    f"(attempt {attempt}, {len(resp.content)} bytes)"
                )
                time.sleep(wait)
                last_err = RuntimeError(f"HTTP {resp.status_code} for {resp.url}")
                continue
            if sleep_after:
                time.sleep(sleep_after)
            return resp
        except requests.RequestException as e:
            last_err = e
            wait = min(40, 2 * attempt)
            log(f"Request error {e} for {url} — sleep {wait}s (attempt {attempt})")
            time.sleep(wait)
    raise RuntimeError(f"Failed GET {url} params={params}: {last_err}")


def download_to(
    url: str,
    dest: Path,
    *,
    params: dict | None = None,
    timeout: int = 300,
    sleep_after: float = 0.4,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    resp = http_get(url, params=params, timeout=timeout, sleep_after=sleep_after)
    tmp.write_bytes(resp.content)
    if tmp.stat().st_size == 0:
        raise RuntimeError(f"Empty download: {url}")
    tmp.replace(dest)
    return dest


def record_file(
    rel: str,
    path: Path,
    *,
    extra: dict | None = None,
) -> dict:
    info = {
        "path": str(path),
        "relpath": rel,
        "bytes": file_size(path),
        "sha256": sha256_file(path),
    }
    if extra:
        info.update(extra)
    STATS["files"][rel] = info
    return info


# ---------------------------------------------------------------------------
# 1. USGS catalogs
# ---------------------------------------------------------------------------

def usgs_count(minmagnitude: float, starttime: str, endtime: str) -> int:
    params = {
        "format": "geojson",
        "minmagnitude": minmagnitude,
        "starttime": starttime,
        "endtime": endtime,
    }
    resp = http_get(USGS_COUNT, params=params, timeout=60, sleep_after=0.6)
    data = resp.json()
    count = int(data["count"] if isinstance(data, dict) else data)
    log(f"USGS count minmag={minmagnitude} {starttime} .. {endtime} -> {count} (raw={data})")
    return count


def _split_needed(count: int) -> bool:
    return count >= 20000


def fetch_usgs_csv_window(
    minmagnitude: float, starttime: str, endtime: str, dest: Path
) -> Path:
    params = {
        "format": "csv",
        "minmagnitude": minmagnitude,
        "starttime": starttime,
        "endtime": endtime,
    }
    log(f"USGS CSV {params}")
    download_to(dest=dest, url=USGS_QUERY, params=params, timeout=300, sleep_after=1.0)
    # Sanity: not an HTML error page
    head = dest.read_bytes()[:200].lstrip()
    if head.startswith(b"<") or b"Error" in head[:80] and b"time," not in head:
        raise RuntimeError(f"USGS returned non-CSV for {params}: {head[:200]!r}")
    return dest


def read_usgs_csv(path: Path) -> pd.DataFrame:
    # Keep all data rows; pandas already consumes a single header per file.
    df = pd.read_csv(path, dtype="string", keep_default_na=False)
    return df


def write_usgs_period(
    dest: Path,
    frames: list[pd.DataFrame],
    *,
    expected_count: int | None,
    label: str,
) -> dict:
    if not frames:
        raise RuntimeError(f"No frames for {label}")
    df = pd.concat(frames, ignore_index=True)
    # Drop only exact duplicate header lines if a chunk accidentally included
    # the header as a data row (time value literally equal to 'time').
    if "time" in df.columns:
        df = df[df["time"].str.lower() != "time"].copy()
        df = df.sort_values("time", kind="mergesort").reset_index(drop=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    extra = validate_usgs_csv(dest, expected_count=expected_count, label=label)
    record_file(f"catalogs/{dest.name}", dest, extra=extra)
    return extra


def validate_usgs_csv(
    path: Path, *, expected_count: int | None, label: str
) -> dict:
    df = pd.read_csv(path)
    cols = list(df.columns)
    required_prefix = [
        "time",
        "latitude",
        "longitude",
        "depth",
        "mag",
        "magType",
        "nst",
        "gap",
        "dmin",
        "rms",
        "net",
        "id",
    ]
    if cols[: len(required_prefix)] != required_prefix:
        raise RuntimeError(f"{label}: unexpected USGS columns: {cols}")
    if len(df) == 0:
        raise RuntimeError(f"{label}: empty catalog {path}")
    tmin, tmax = str(df["time"].min()), str(df["time"].max())
    mag_min, mag_max = float(df["mag"].min()), float(df["mag"].max())
    n = int(len(df))
    note = ""
    if expected_count is not None and n != expected_count:
        note = (
            f"row count {n} != USGS count endpoint {expected_count} "
            "(catalog may have been updated between count and download)"
        )
        STATS["notes"].append(f"{label}: {note}")
        log(f"WARNING {note}")
    # The 20,000-event cap applies to a single FDSN query, not to a
    # concatenated multi-window catalog (e.g. 1965-2016 M>=5.5).
    extra = {
        "rows": n,
        "columns": cols,
        "ncol": len(cols),
        "time_min": tmin,
        "time_max": tmax,
        "mag_min": mag_min,
        "mag_max": mag_max,
        "expected_count": expected_count,
        "types": sorted(df["type"].dropna().astype(str).unique().tolist())
        if "type" in df.columns
        else [],
    }
    log(
        f"Validated {label}: rows={n} time={tmin} .. {tmax} "
        f"mag={mag_min}..{mag_max} types={extra['types']}"
    )
    return extra


def month_windows(start_year: int, start_month: int, end_year: int, end_month: int):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        if m == 12:
            ny, nm = y + 1, 1
        else:
            ny, nm = y, m + 1
        start = f"{y:04d}-{m:02d}-01"
        end = f"{ny:04d}-{nm:02d}-01"
        yield start, end
        y, m = ny, nm


def fetch_usgs_adaptive(
    minmagnitude: float,
    starttime: str,
    endtime: str,
    tmp_dir: Path,
    prefix: str,
) -> tuple[list[pd.DataFrame], int]:
    """Download a window, splitting by year then month if the 20k cap is hit."""
    count = usgs_count(minmagnitude, starttime, endtime)
    if not _split_needed(count):
        path = tmp_dir / f"{prefix}.csv"
        fetch_usgs_csv_window(minmagnitude, starttime, endtime, path)
        return [read_usgs_csv(path)], count

    log(f"{prefix}: count {count} exceeds 20,000 — splitting")
    start_dt = datetime.fromisoformat(starttime.replace("Z", "")).replace(tzinfo=None)
    end_dt = datetime.fromisoformat(endtime.replace("Z", "")).replace(tzinfo=None)
    frames: list[pd.DataFrame] = []
    total = 0
    year = start_dt.year
    end_year_exclusive = end_dt.year if (end_dt.month, end_dt.day, end_dt.hour) == (1, 1, 0) and end_dt.minute == 0 and end_dt.second == 0 else end_dt.year
    # Walk calendar years overlapping [starttime, endtime)
    y = start_dt.year
    last_year = end_dt.year if end_dt > datetime(end_dt.year, 1, 1) else end_dt.year - 1
    if end_dt == datetime(end_dt.year, 1, 1):
        last_year = end_dt.year - 1
    else:
        last_year = end_dt.year
    for y in range(start_dt.year, last_year + 1):
        ys = max(starttime, f"{y:04d}-01-01")
        ye = min(endtime, f"{y+1:04d}-01-01")
        if ye <= ys:
            continue
        yc = usgs_count(minmagnitude, ys, ye)
        total += yc  # informational; final expected is the parent count
        if not _split_needed(yc):
            path = tmp_dir / f"{prefix}_{y}.csv"
            fetch_usgs_csv_window(minmagnitude, ys, ye, path)
            frames.append(read_usgs_csv(path))
            continue
        log(f"{prefix} year {y}: count {yc} still >= 20000 — monthly split")
        for ms, me in month_windows(y, 1, y, 12):
            if me <= ys or ms >= ye:
                continue
            ws, we = max(ms, ys), min(me, ye)
            mc = usgs_count(minmagnitude, ws, we)
            if _split_needed(mc):
                raise RuntimeError(
                    f"Monthly window {ws}..{we} still has {mc} events (>=20000)"
                )
            path = tmp_dir / f"{prefix}_{ws[:7]}.csv"
            fetch_usgs_csv_window(minmagnitude, ws, we, path)
            frames.append(read_usgs_csv(path))
    return frames, count


def collect_catalogs() -> None:
    log("=== Layer 1: USGS catalogs ===")
    CATALOGS.mkdir(parents=True, exist_ok=True)
    tmp_dir = TMP / "usgs"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Copy existing 2022-2023 file; do not re-download.
    dest_2022 = CATALOGS / "07_usgs_quakes_m5_2022_2023.csv"
    if not LOCAL_USGS_2022.is_file():
        raise FileNotFoundError(f"Missing local USGS 2022-2023 file: {LOCAL_USGS_2022}")
    shutil.copy2(LOCAL_USGS_2022, dest_2022)
    digest = sha256_file(dest_2022)
    if digest != EXPECTED_USGS_2022_SHA256:
        raise RuntimeError(
            f"Copied 2022-2023 SHA256 mismatch: got {digest}, "
            f"expected {EXPECTED_USGS_2022_SHA256}"
        )
    extra = validate_usgs_csv(dest_2022, expected_count=None, label="usgs_2022_2023_copy")
    extra["copied_from"] = str(LOCAL_USGS_2022)
    extra["note"] = (
        "Copied from local acquired file; not re-downloaded from ComCat "
        "to avoid revision drift."
    )
    record_file("catalogs/07_usgs_quakes_m5_2022_2023.csv", dest_2022, extra=extra)
    log(f"Copied 2022-2023 catalog sha256={digest}")

    # 2017-01-01 through 2021-12-31 (endtime exclusive 2022-01-01)
    frames, count = fetch_usgs_adaptive(
        5.0, "2017-01-01", "2022-01-01", tmp_dir, "m5_2017_2021"
    )
    write_usgs_period(
        CATALOGS / "07_usgs_quakes_m5_2017_2021.csv",
        frames,
        expected_count=count,
        label="usgs_m5_2017_2021",
    )

    # 2024-01-01 through retrieval moment (UTC)
    frames, count = fetch_usgs_adaptive(
        5.0, "2024-01-01", USGS_NOW_ENDTIME, tmp_dir, "m5_2024_now"
    )
    extra = write_usgs_period(
        CATALOGS / "07_usgs_quakes_m5_2024_now.csv",
        frames,
        expected_count=count,
        label="usgs_m5_2024_now",
    )
    STATS["files"]["catalogs/07_usgs_quakes_m5_2024_now.csv"]["endtime_utc"] = (
        USGS_NOW_ENDTIME
    )

    # M>=5.5, 1965-01-01 through 2016-12-31 (endtime exclusive 2017-01-01)
    frames, count = fetch_usgs_adaptive(
        5.5, "1965-01-01", "2017-01-01", tmp_dir, "m55_1965_2016"
    )
    write_usgs_period(
        CATALOGS / "07_usgs_quakes_m55_1965_2016.csv",
        frames,
        expected_count=count,
        label="usgs_m55_1965_2016",
    )


# ---------------------------------------------------------------------------
# 2. NCEI / Hazel impact catalogs
# ---------------------------------------------------------------------------

def ncei_fetch_all(endpoint: str) -> tuple[list[dict], dict]:
    url = f"{NCEI_BASE}/{endpoint}"
    items: list[dict] = []
    page = 1
    meta: dict = {}
    while True:
        params = {"page": page, "itemsPerPage": NCEI_PAGE_SIZE}
        resp = http_get(url, params=params, timeout=120, sleep_after=0.25)
        data = resp.json()
        if not isinstance(data, dict) or "items" not in data:
            raise RuntimeError(f"Unexpected NCEI payload for {url} page={page}: {data!r:.500}")
        batch = data.get("items") or []
        meta = {
            "endpoint": url,
            "totalItems": data.get("totalItems"),
            "totalPages": data.get("totalPages"),
            "itemsPerPage": data.get("itemsPerPage"),
        }
        log(
            f"NCEI {endpoint} page {page}/{meta['totalPages']} "
            f"got {len(batch)} running={len(items)+len(batch)}/{meta['totalItems']}"
        )
        items.extend(batch)
        if not batch:
            break
        if meta["totalPages"] is not None and page >= int(meta["totalPages"]):
            break
        page += 1
        if page > 5000:
            raise RuntimeError(f"Pagination safety stop on {endpoint}")
    if meta.get("totalItems") is not None and len(items) != int(meta["totalItems"]):
        raise RuntimeError(
            f"NCEI {endpoint}: collected {len(items)} != totalItems {meta['totalItems']}"
        )
    # Stable unique by id if present, but do not drop rows if ids collide — only warn.
    if items and "id" in items[0]:
        ids = [r.get("id") for r in items]
        if len(ids) != len(set(ids)):
            STATS["notes"].append(
                f"NCEI {endpoint}: duplicate ids present ({len(ids)-len(set(ids))} extras); all rows kept"
            )
    return items, meta


def ncei_to_csv(items: list[dict], dest: Path) -> list[str]:
    # Flatten any nested values as JSON; preserve first-seen field order.
    columns: list[str] = []
    seen = set()
    flat_rows: list[dict] = []
    for rec in items:
        row = {}
        for k, v in rec.items():
            if k not in seen:
                seen.add(k)
                columns.append(k)
            if isinstance(v, (dict, list)):
                row[k] = json.dumps(v, ensure_ascii=False)
            else:
                row[k] = v
        flat_rows.append(row)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(flat_rows, columns=columns)
    df.to_csv(dest, index=False, encoding="utf-8")
    return columns


def _ncei_year_span(df: pd.DataFrame) -> tuple[Any, Any]:
    if "year" not in df.columns or df.empty:
        return None, None
    years = pd.to_numeric(df["year"], errors="coerce")
    return (int(years.min()) if years.notna().any() else None,
            int(years.max()) if years.notna().any() else None)


def collect_impact() -> None:
    log("=== Layer 2: NCEI / Hazel impact catalogs ===")
    IMPACT.mkdir(parents=True, exist_ok=True)
    targets = [
        (
            "earthquakes",
            IMPACT / "ncei_significant_earthquakes.csv",
            "NCEI/WDS Global Significant Earthquake Database",
        ),
        (
            "tsunamis/events",
            IMPACT / "ncei_significant_tsunamis.csv",
            "NCEI/WDS Global Historical Tsunami Database — events",
        ),
        (
            "tsunamis/runups",
            IMPACT / "ncei_tsunami_runups.csv",
            "NCEI/WDS Global Historical Tsunami Database — runups",
        ),
        (
            "tsunamis/deposits",
            IMPACT / "ncei_tsunami_deposits.csv",
            "NCEI/WDS Global Historical Tsunami Database — deposits",
        ),
        (
            "tsunamis/marigrams",
            IMPACT / "ncei_tsunami_marigrams.csv",
            "NCEI/WDS Global Historical Tsunami Database — marigrams",
        ),
    ]
    for endpoint, dest, title in targets:
        items, meta = ncei_fetch_all(endpoint)
        columns = ncei_to_csv(items, dest)
        df = pd.read_csv(dest, low_memory=False)
        if len(df) != len(items):
            raise RuntimeError(f"{dest.name}: CSV rows {len(df)} != JSON items {len(items)}")
        ymin, ymax = _ncei_year_span(df)
        extra = {
            "rows": int(len(df)),
            "ncol": int(df.shape[1]),
            "columns": columns,
            "year_min": ymin,
            "year_max": ymax,
            "api_meta": meta,
            "dataset": title,
        }
        record_file(f"impact/{dest.name}", dest, extra=extra)
        log(f"Wrote {dest.name}: rows={len(df)} cols={df.shape[1]} years={ymin}..{ymax}")


# ---------------------------------------------------------------------------
# 3. Tectonic / mechanism context
# ---------------------------------------------------------------------------

def geojson_counts(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} is not a GeoJSON object")
    gtype = data.get("type")
    feats = data.get("features")
    if gtype == "FeatureCollection" and isinstance(feats, list):
        geom_types: dict[str, int] = {}
        for ft in feats:
            gt = (ft.get("geometry") or {}).get("type") or "null"
            geom_types[gt] = geom_types.get(gt, 0) + 1
        return {
            "geojson_type": gtype,
            "feature_count": len(feats),
            "geometry_types": geom_types,
        }
    raise RuntimeError(f"{path}: unexpected GeoJSON type {gtype}")


def shapefile_record_count(shp: Path) -> int:
    # ESRI shapefile main header: byte 24, big-endian int32 file length in 16-bit words.
    # Record count is not in the header; count records by walking the .shx index:
    # shx header 100 bytes + 8 bytes per record.
    shx = shp.with_suffix(".shx")
    if shx.is_file():
        return (shx.stat().st_size - 100) // 8
    # Fallback: parse shp record headers.
    with shp.open("rb") as f:
        header = f.read(100)
        if len(header) < 100 or header[:4] != b"\x00\x00\x27\x0a":
            raise RuntimeError(f"Not a shapefile: {shp}")
        file_len_words = int.from_bytes(header[24:28], "big")
        # walk records
        n = 0
        while f.tell() < file_len_words * 2:
            rec = f.read(8)
            if len(rec) < 8:
                break
            content_words = int.from_bytes(rec[4:8], "big")
            f.seek(content_words * 2, os.SEEK_CUR)
            n += 1
        return n


def collect_tectonicplates() -> None:
    log("=== Layer 3a: Bird 2003 PB2002 plate boundaries (fraxen/tectonicplates) ===")
    dest_dir = CONTEXT / "tectonicplates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_url = "https://github.com/fraxen/tectonicplates/archive/refs/heads/master.zip"
    zip_path = TMP / "tectonicplates-master.zip"
    download_to(zip_url, zip_path, timeout=300, sleep_after=0.2)
    shutil.copy2(zip_path, dest_dir / "tectonicplates-master.zip")
    record_file(
        "context/tectonicplates/tectonicplates-master.zip",
        dest_dir / "tectonicplates-master.zip",
        extra={
            "source_url": zip_url,
            "github_commit": "339b0c56563c118307b1f4542703047f5f698fae",
            "github_commit_date": "2014-10-06T08:19:01Z",
        },
    )
    with zipfile.ZipFile(zip_path) as zf:
        # Extract into dest_dir, flattening the tectonicplates-master/ prefix
        for info in zf.infolist():
            if info.is_dir():
                continue
            # paths like tectonicplates-master/GeoJSON/PB2002_boundaries.json
            parts = Path(info.filename).parts
            if not parts:
                continue
            rel = Path(*parts[1:]) if parts[0].startswith("tectonicplates-master") else Path(*parts)
            out = dest_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    # Validate GeoJSON
    geojson_files = [
        dest_dir / "GeoJSON" / "PB2002_boundaries.json",
        dest_dir / "GeoJSON" / "PB2002_plates.json",
        dest_dir / "GeoJSON" / "PB2002_orogens.json",
        dest_dir / "GeoJSON" / "PB2002_steps.json",
    ]
    for p in geojson_files:
        if not p.is_file():
            raise RuntimeError(f"Missing tectonicplates GeoJSON: {p}")
        counts = geojson_counts(p)
        rel = str(p.relative_to(ROOT))
        record_file(rel, p, extra=counts)
        log(f"GeoJSON {p.name}: {counts}")

    for shp_name in [
        "PB2002_boundaries.shp",
        "PB2002_plates.shp",
        "PB2002_orogens.shp",
        "PB2002_steps.shp",
    ]:
        shp = dest_dir / shp_name
        if not shp.is_file():
            raise RuntimeError(f"Missing shapefile {shp}")
        n = shapefile_record_count(shp)
        rel = str(shp.relative_to(ROOT))
        record_file(rel, shp, extra={"shapefile_records": n})
        log(f"Shapefile {shp.name}: records={n}")

    for extra_name in ["LICENSE.md", "README.md"]:
        p = dest_dir / extra_name
        if p.is_file():
            record_file(str(p.relative_to(ROOT)), p)


def collect_gem() -> None:
    log("=== Layer 3b: GEM Global Active Faults ===")
    dest_dir = CONTEXT / "gem_global_active_faults"
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master"
    commit = "56816508ad92fd6846dad1163b1c8c01376a2cd1"
    files = {
        "geojson/gem_active_faults.geojson": "gem_active_faults.geojson",
        "geojson/gem_active_faults_harmonized.geojson": "gem_active_faults_harmonized.geojson",
        "LICENSE.txt": "LICENSE.txt",
        "README.md": "README.md",
    }
    for remote, local in files.items():
        url = f"{base}/{remote}"
        dest = dest_dir / local
        log(f"GEM GET {url}")
        download_to(url, dest, timeout=300, sleep_after=0.3)
        extra: dict[str, Any] = {
            "source_url": url,
            "github_commit": commit,
            "github_ref": "master",
        }
        if dest.suffix in {".geojson", ".json"}:
            extra.update(geojson_counts(dest))
            log(f"GEM {dest.name}: {extra.get('feature_count')} features")
        record_file(str(dest.relative_to(ROOT)), dest, extra=extra)


def ndk_event_count(path: Path) -> int:
    # Official NDK records are 5 lines each. Count non-empty lines.
    n_lines = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip() != "" or line:  # count all physical lines including format
                n_lines += 1
    # Use exact line count (NDK should have no blanks between records)
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    n = len(raw_lines)
    if n % 5 != 0:
        STATS["notes"].append(f"{path.name}: line count {n} is not divisible by 5")
        log(f"WARNING {path.name}: {n} lines not divisible by 5")
    return n // 5, n


def collect_gcmt() -> None:
    log("=== Layer 3c: Global CMT NDK catalog ===")
    dest_dir = CONTEXT / "gcmt"
    monthly_dir = dest_dir / "monthly_2026"
    pre_dir = dest_dir / "pre1976"
    quick_dir = dest_dir / "quick"
    for d in (dest_dir, monthly_dir, pre_dir, quick_dir):
        d.mkdir(parents=True, exist_ok=True)

    files_html = dest_dir / "CMTfiles.html"
    download_to("https://www.globalcmt.org/CMTfiles.html", files_html, timeout=60)
    record_file(str(files_html.relative_to(ROOT)), files_html, extra={"source_url": "https://www.globalcmt.org/CMTfiles.html"})

    cite_html = dest_dir / "CMTcite.html"
    download_to("https://www.globalcmt.org/CMTcite.html", cite_html, timeout=60)
    record_file(str(cite_html.relative_to(ROOT)), cite_html, extra={"source_url": "https://www.globalcmt.org/CMTcite.html"})

    explained = dest_dir / "allorder.ndk_explained"
    exp_url = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/allorder.ndk_explained"
    download_to(exp_url, explained, timeout=60)
    record_file(str(explained.relative_to(ROOT)), explained, extra={"source_url": exp_url})

    hist_url = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/jan76_dec25.ndk"
    hist = dest_dir / "jan76_dec25.ndk"
    log(f"Downloading official historical NDK {hist_url}")
    download_to(hist_url, hist, timeout=600, sleep_after=0.5)
    ev, lines = ndk_event_count(hist)
    record_file(
        str(hist.relative_to(ROOT)),
        hist,
        extra={"source_url": hist_url, "ndk_events": ev, "ndk_lines": lines, "coverage": "1976-01 through 2025-12 (official combined file)"},
    )
    log(f"jan76_dec25.ndk events={ev} lines={lines}")

    # Official 2026 monthly files (complete months listed on the server)
    monthly_index_url = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/NEW_MONTHLY/2026/"
    idx = http_get(monthly_index_url, timeout=60, sleep_after=0.2)
    (dest_dir / "NEW_MONTHLY_2026_index.html").write_bytes(idx.content)
    record_file(
        "context/gcmt/NEW_MONTHLY_2026_index.html",
        dest_dir / "NEW_MONTHLY_2026_index.html",
        extra={"source_url": monthly_index_url},
    )
    # Known / listed months; parse hrefs ending in .ndk
    import re

    names = sorted(set(re.findall(r"href=['\"]([^'\"]+\.ndk)['\"]", idx.text, flags=re.I)))
    # Sort in calendar order rather than alphabetical month abbreviations
    month_order = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def month_key(name: str) -> tuple[int, str]:
        stem = Path(name).stem.lower()  # e.g. jan26
        mon = stem[:3]
        year = stem[3:]
        return (int(year) if year.isdigit() else 99, month_order.get(mon, 99), name)

    names = sorted(names, key=month_key)
    log(f"2026 monthly NDK files listed: {names}")
    monthly_paths: list[Path] = []
    for name in names:
        url = monthly_index_url + name
        dest = monthly_dir / Path(name).name
        download_to(url, dest, timeout=180, sleep_after=0.4)
        ev_m, lines_m = ndk_event_count(dest)
        record_file(
            str(dest.relative_to(ROOT)),
            dest,
            extra={"source_url": url, "ndk_events": ev_m, "ndk_lines": lines_m},
        )
        log(f"{dest.name}: events={ev_m} lines={lines_m}")
        monthly_paths.append(dest)

    # Concatenate official historical + subsequent official monthly files (no conversion)
    concat_path = dest_dir / "gcmt_1976_latest.ndk"
    parts = [hist, *monthly_paths]
    with concat_path.open("wb") as out:
        for p in parts:
            out.write(p.read_bytes())
            # Ensure files join on a newline if the previous file lacks a trailing newline
            if not p.read_bytes().endswith(b"\n"):
                out.write(b"\n")
    ev_c, lines_c = ndk_event_count(concat_path)
    expected_ev = ev + sum(STATS["files"][str(p.relative_to(ROOT))]["ndk_events"] for p in monthly_paths)
    extra = {
        "ndk_events": ev_c,
        "ndk_lines": lines_c,
        "concatenated_from": [str(p.relative_to(ROOT)) for p in parts],
        "expected_events_sum": expected_ev,
        "note": "Byte-concatenation of official NDK files only; no format conversion.",
    }
    record_file(str(concat_path.relative_to(ROOT)), concat_path, extra=extra)
    log(f"gcmt_1976_latest.ndk events={ev_c} (sum of parts={expected_ev}) lines={lines_c}")

    # Official pre-1976 supplementary catalogs (not merged into 1976-latest)
    pre_files = {
        "deep_1962-1976.ndk": "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/PRE1976/deep_1962-1976.ndk",
        "intdep_1962-1975.ndk": "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/PRE1976/intdep_1962-1975.ndk",
    }
    for name, url in pre_files.items():
        dest = pre_dir / name
        try:
            download_to(url, dest, timeout=180, sleep_after=0.4)
            ev_p, lines_p = ndk_event_count(dest)
            record_file(
                str(dest.relative_to(ROOT)),
                dest,
                extra={"source_url": url, "ndk_events": ev_p, "ndk_lines": lines_p},
            )
            log(f"{name}: events={ev_p} lines={lines_p}")
        except Exception as e:
            STATS["failures"].append(f"GCMT PRE1976 {name}: {e}")
            log(f"FAILURE PRE1976 {name}: {e}")

    # Quick CMT preliminary file (not merged into the complete catalog)
    qcmt_url = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/NEW_QUICK/qcmt.ndk"
    qcmt = quick_dir / "qcmt.ndk"
    try:
        download_to(qcmt_url, qcmt, timeout=180, sleep_after=0.4)
        ev_q, lines_q = ndk_event_count(qcmt)
        record_file(
            str(qcmt.relative_to(ROOT)),
            qcmt,
            extra={
                "source_url": qcmt_url,
                "ndk_events": ev_q,
                "ndk_lines": lines_q,
                "note": "Preliminary Quick CMT solutions; not merged into gcmt_1976_latest.ndk.",
            },
        )
        log(f"qcmt.ndk events={ev_q} lines={lines_q}")
    except Exception as e:
        STATS["failures"].append(f"GCMT Quick CMT qcmt.ndk: {e}")
        log(f"FAILURE qcmt.ndk: {e}")


def collect_context() -> None:
    log("=== Layer 3: tectonic / mechanism context ===")
    CONTEXT.mkdir(parents=True, exist_ok=True)
    collect_tectonicplates()
    collect_gem()
    collect_gcmt()


# ---------------------------------------------------------------------------
# Manifest + cleanup
# ---------------------------------------------------------------------------

def write_manifest() -> None:
    manifest = ROOT / "retrieval_manifest.json"
    payload = {
        "retrieval_utc": STATS["retrieval_utc"],
        "retrieval_cst": STATS["retrieval_cst"],
        "usgs_now_endtime_utc": STATS["usgs_now_endtime_utc"],
        "user_agent": USER_AGENT,
        "files": STATS["files"],
        "notes": STATS["notes"],
        "failures": STATS["failures"],
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Wrote {manifest}")


def cleanup_tmp() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
        log(f"Removed {TMP}")


def main() -> int:
    LOG_PATH.write_text("", encoding="utf-8")
    log(f"Start retrieval at {STATS['retrieval_cst']}")
    log(f"USGS 2024-now endtime UTC = {USGS_NOW_ENDTIME}")
    ROOT.mkdir(parents=True, exist_ok=True)
    for d in (CATALOGS, IMPACT, CONTEXT, TMP):
        d.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    for name, fn in [
        ("catalogs", collect_catalogs),
        ("impact", collect_impact),
        ("context", collect_context),
    ]:
        try:
            fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
            STATS["failures"].append(f"{name}: {e}")
            log(f"FAILURE in {name}: {e}")
            import traceback

            traceback.print_exc()

    write_manifest()
    cleanup_tmp()
    if errors:
        log("Completed with failures: " + " | ".join(errors))
        return 1
    log("All layers completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
