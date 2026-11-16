#!/usr/bin/env python3
"""Collect official NBS tables for DS 2043 topic 07.

Scope (confirmed 2026-11-15):
  - China Statistical Yearbook table 地震灾害情况
  - provincial year-end resident population
  - regional GDP (地区生产总值 / 各地区国内生产总值)
Source of record: https://www.stats.gov.cn only. Raw save, no cleaning.
Also collect 环境统计资料 earthquake-disaster tables (official series through 2014).
"""

from __future__ import annotations

import hashlib
import html as htmlmod
import json
import random
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote

import requests

ROOT = Path("/workspace/07_external/nbs")
YEARBOOK_DIR = ROOT / "yearbook"
ENV_DIR = ROOT / "environment_stats"
LOG_PATH = ROOT / "retrieve_log.txt"
MANIFEST_PATH = ROOT / "retrieval_manifest.json"
SOURCES_PATH = ROOT / "SOURCES.md"

BASE = "https://www.stats.gov.cn"
INDEX_NDSJ = f"{BASE}/sj/ndsj/"
ENV_PORTAL = f"{BASE}/zt_18555/ztsj/hjtjzl/"

# Browser UA is required by the yearbook site; academic purpose is recorded in the manifest.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

CST = timezone(timedelta(hours=8))
SLEEP = (0.35, 0.55)
TIMEOUT = 40
RETRIES = 3

session = requests.Session()
session.headers.update(HEADERS)

files: dict[str, dict] = {}
failures: list[dict] = []
notes: list[str] = []
inventory: list[dict] = []  # classified table records


def now_cst() -> datetime:
    return datetime.now(CST)


def log(msg: str) -> None:
    line = f"[{now_cst().strftime('%Y-%m-%d %H:%M:%S %z')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_soft_404(url: str, status: int, data: bytes, content_type: str) -> bool:
    if status != 200:
        return status == 404
    if len(data) <= 600:
        head = data[:800].decode("utf-8", "replace").lower()
        if "404 not found" in head or "<title>404" in head:
            return True
    # Some 404 bodies are exactly 555 bytes nginx page
    if len(data) in {555, 557} and b"404 Not Found" in data:
        return True
    return False


def fetch(url: str, referer: Optional[str] = None) -> tuple[int, bytes, str, str]:
    """Return status, content, content-type, final_url. Raises on hard failure after retries."""
    headers = {}
    if referer:
        headers["Referer"] = referer
    last_err = None
    for attempt in range(1, RETRIES + 1):
        time.sleep(random.uniform(*SLEEP))
        try:
            r = session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            ctype = r.headers.get("Content-Type", "")
            return r.status_code, r.content, ctype, r.url
        except Exception as e:
            last_err = e
            log(f"RETRY {attempt}/{RETRIES} {url} ({e})")
            time.sleep(1.2 * attempt)
    raise RuntimeError(f"fetch failed after retries: {url} ({last_err})")


def decode_html(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8")
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("gb18030", "replace")


def save_bytes(relpath: str, data: bytes, source_url: str, kind: str, extra: Optional[dict] = None) -> Path:
    dest = ROOT / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    rec = {
        "path": str(dest.relative_to(ROOT)),
        "abs_path": str(dest),
        "source_url": source_url,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "kind": kind,
        "retrieved_cst": now_cst().isoformat(timespec="seconds"),
    }
    if extra:
        rec.update(extra)
    files[rec["path"]] = rec
    log(f"SAVED {rec['path']}  {rec['bytes']} B  {rec['sha256'][:12]}  {source_url}")
    return dest


def try_save(url: str, relpath: str, kind: str, referer: Optional[str] = None, extra: Optional[dict] = None) -> Optional[Path]:
    try:
        status, data, ctype, final = fetch(url, referer=referer)
    except Exception as e:
        failures.append({"url": url, "error": str(e), "path": relpath})
        log(f"FAIL {url}  {e}")
        return None
    if is_soft_404(url, status, data, ctype) or status != 200:
        failures.append({"url": url, "status": status, "bytes": len(data), "path": relpath, "note": "not saved"})
        log(f"MISS {status} {len(data)}B  {url}")
        return None
    extra = dict(extra or {})
    extra["http_status"] = status
    extra["content_type"] = ctype
    extra["final_url"] = final
    return save_bytes(relpath, data, final or url, kind, extra)


def iter_links(html: str):
    pattern = re.compile(r'(?is)<a[^>]+href\s*=\s*["\']?([^"\'\s>]+)["\']?[^>]*>(.*?)</a>')
    for href, inner in pattern.findall(html):
        href = htmlmod.unescape(href).strip().replace("\\", "/")
        title = htmlmod.unescape(re.sub(r"(?is)<[^>]+>", "", inner))
        title = title.replace("\xa0", " ").replace("&nbsp;", " ")
        title = re.sub(r"\s+", "", title)
        if href and href.lower() not in {"javascript:void(0)", "javascript:void(0);", "javascript:;", "#"}:
            yield href, title


def classify_title(title: str) -> Optional[str]:
    t = re.sub(r"\s+", "", title or "")
    if not t:
        return None
    # Hard exclusions
    if any(x in t for x in ("地震监测", "地质灾害", "本地生产总值", "本地居民生产总值")):
        return None
    if any(x in t for x in ("香港特别行政区", "澳门特别行政区", "台湾省主要", "台湾主要社会经济")):
        return None
    if t.startswith("附录") or "附录1" in t or "附录2" in t or "附录一" in t or "附录二" in t:
        return None
    if "万元国内生产总值" in t or "万元地区生产总值能耗" in t:
        return None

    if "地震灾害" in t:
        return "earthquake_disaster"

    # Provincial / regional GDP (not national 国内生产总值 accounts)
    if re.search(r"(地区生产总值|各地区国内生产总值|分地区国内生产总值|各地区生产总值)", t):
        if "项目结构" in t:
            return None
        if "支出法" in t:
            return None
        return "regional_gdp"

    # Provincial year-end population
    if any(
        x in t
        for x in (
            "分地区年末人口数",
            "分地区年末常住人口",
            "各地区年末人口数",
            "各地区年末常住人口",
            "分地区常住人口",
        )
    ):
        if "城镇人口比重" in t or "城乡构成" in t:
            return None
        return "provincial_population"
    if "各地区总人口和" in t:  # 和出生率… / 和性别比
        return "provincial_population"
    if "各地区人口数和" in t or "分地区人口数和" in t:
        return "provincial_population"
    # bare 各地区总人口, but not growth / ethnicity / household splits
    if "各地区总人口" in t and not any(
        x in t for x in ("增长", "汉族", "少数民族", "家庭户", "集体户", "城乡人口")
    ):
        return "provincial_population"

    return None


def local_rel_from_url(url: str, prefix: str) -> str:
    """Map an official URL to a path under prefix, preserving official path tail."""
    p = urlparse(url)
    path = unquote(p.path).lstrip("/")
    # keep path after ndsj/ or yearbook... to stay readable
    return str(Path(prefix) / path)


def excel_hrefs_from_html(page_url: str, html: str) -> list[str]:
    out = []
    for href, title in iter_links(html):
        low = href.lower().split("?")[0]
        if low.endswith((".xls", ".xlsx", ".et")):
            out.append(urljoin(page_url, href))
    return list(dict.fromkeys(out))


def companion_candidates(url: str) -> list[str]:
    """Limited official companions: Excel / HTML next to a known table file."""
    base, _, ext = url.rpartition(".")
    ext = ext.lower()
    cands = []
    # Only try Excel companions to limit 404s; HTML pages already expose .xls links in-page.
    if ext in {"jpg", "jpeg", "gif", "png", "htm", "html"}:
        for e in ("xls", "xlsx"):
            cands.append(f"{base}.{e}")
    # unique, exclude self
    out = []
    for u in cands:
        if u.rstrip("/") != url.rstrip("/"):
            out.append(u)
    return list(dict.fromkeys(out))


def record_table(year, source, category, title, url, relpath) -> None:
    inventory.append(
        {
            "year": year,
            "source": source,
            "category": category,
            "title": title,
            "source_url": url,
            "path": relpath,
        }
    )


def collect_table_file(url: str, relpath: str, year, source, category, title, referer, also_companions=True) -> Optional[Path]:
    dest = try_save(
        url,
        relpath,
        kind="table",
        referer=referer,
        extra={"year": year, "source": source, "category": category, "title": title},
    )
    if not dest:
        return None
    record_table(year, source, category, title, url, relpath)
    data = dest.read_bytes()
    ctype_looks_html = dest.suffix.lower() in {".htm", ".html"} or data[:200].lower().lstrip().startswith(b"<!doctype") or data[:80].lower().lstrip().startswith(b"<html")
    if ctype_looks_html:
        page = decode_html(data)
        for xurl in excel_hrefs_from_html(url, page):
            xp = local_rel_from_url(xurl, dest.parent.relative_to(ROOT).as_posix())
            # keep companions beside the html
            xp = str(Path(dest.parent.relative_to(ROOT)) / Path(urlparse(xurl).path).name)
            try_save(
                xurl,
                xp,
                kind="table_excel",
                referer=url,
                extra={"year": year, "source": source, "category": category, "title": title + " [Excel]"},
            )
    if also_companions:
        for curl in companion_candidates(url):
            # skip if already saved
            cpath = str(Path(dest.parent.relative_to(ROOT)) / Path(urlparse(curl).path).name)
            if cpath in files:
                continue
            cdest = try_save(
                curl,
                cpath,
                kind="table_companion",
                referer=url,
                extra={"year": year, "source": source, "category": category, "title": title, "companion_of": url},
            )
            # companions that 404 are already logged as MISS; do not treat as hard failure
            if cdest:
                record_table(year, source, category, title + " [companion]", curl, cpath)
    return dest


def collect_from_toc(year: int, toc_url: str, source: str, extra_toc_pages: Optional[list[str]] = None) -> None:
    log(f"==== Yearbook {year} TOC {toc_url}")
    # save TOC
    toc_rel = local_rel_from_url(toc_url, "yearbook")
    dest = try_save(toc_url, toc_rel, kind="toc", referer=INDEX_NDSJ, extra={"year": year, "source": source})
    if not dest:
        notes.append(f"Yearbook {year}: TOC not available at {toc_url}")
        return
    html = decode_html(dest.read_bytes())
    pages = [(toc_url, html)]
    for extra in extra_toc_pages or []:
        erel = local_rel_from_url(extra, "yearbook")
        ed = try_save(extra, erel, kind="toc_chapter", referer=toc_url, extra={"year": year, "source": source})
        if ed:
            pages.append((extra, decode_html(ed.read_bytes())))

    seen_urls = set()
    found = {k: 0 for k in ("earthquake_disaster", "provincial_population", "regional_gdp")}
    for page_url, page_html in pages:
        for href, title in iter_links(page_html):
            cat = classify_title(title)
            if not cat:
                continue
            full = urljoin(page_url, href)
            # ignore non-stats hosts
            if "stats.gov.cn" not in urlparse(full).netloc:
                continue
            if full in seen_urls:
                continue
            seen_urls.add(full)
            rel = local_rel_from_url(full, "yearbook")
            if collect_table_file(full, rel, year, source, cat, title, referer=page_url):
                found[cat] += 1
    log(f"Yearbook {year} classified counts: {found}")
    for k, n in found.items():
        if n == 0:
            notes.append(f"Yearbook {year}: no table classified as {k} in parsed TOC(s)")


def collect_yearbooks() -> None:
    # Official index
    try_save(
        INDEX_NDSJ,
        "yearbook/index_ndsj.html",
        kind="index",
        extra={"title": "中国统计年鉴 目录页"},
    )

    # 1999 (legacy path from official index)
    collect_from_toc(
        1999,
        f"{BASE}/yearbook/ml/1999_c.htm",
        "yearbook",
        extra_toc_pages=[f"{BASE}/yearbook/indexC.htm"],
    )

    # 2000 chapter TOC
    mulu = f"{BASE}/sj/ndsj/zgnj/mulu.html"
    dest = try_save(mulu, "yearbook/sj/ndsj/zgnj/mulu.html", kind="toc", referer=INDEX_NDSJ, extra={"year": 2000})
    extras = []
    if dest:
        for href, title in iter_links(decode_html(dest.read_bytes())):
            full = urljoin(mulu, href)
            if "stats.gov.cn" in urlparse(full).netloc and Path(urlparse(full).path).suffix.lower() in {".html", ".htm"}:
                extras.append(full)
    collect_from_toc(2000, mulu, "yearbook", extra_toc_pages=extras)

    # 2001 chapter TOC
    mulu = f"{BASE}/sj/ndsj/2001c/mulu.htm"
    dest = try_save(mulu, "yearbook/sj/ndsj/2001c/mulu.htm", kind="toc", referer=INDEX_NDSJ, extra={"year": 2001})
    extras = []
    if dest:
        for href, _title in iter_links(decode_html(dest.read_bytes())):
            full = urljoin(mulu, href)
            if "stats.gov.cn" in urlparse(full).netloc:
                extras.append(full)
    collect_from_toc(2001, mulu, "yearbook", extra_toc_pages=extras)

    # 2002
    collect_from_toc(
        2002,
        f"{BASE}/yearbook2001/ml/2002_c.htm",
        "yearbook",
        extra_toc_pages=[f"{BASE}/yearbook2001/indexC.htm"],
    )

    # 2003 is published as a single official PDF
    log("==== Yearbook 2003 official PDF")
    try_save(
        f"{BASE}/sj/ndsj/yearbook2003_c.pdf",
        "yearbook/sj/ndsj/yearbook2003_c.pdf",
        kind="yearbook_pdf",
        referer=INDEX_NDSJ,
        extra={
            "year": 2003,
            "source": "yearbook",
            "title": "中国统计年鉴2003（官方PDF，未拆表）",
        },
    )
    notes.append(
        "Yearbook 2003: official site publishes a single PDF (yearbook2003_c.pdf), not an HTML table TOC; raw PDF saved, tables not extracted."
    )

    # 2004
    collect_from_toc(
        2004,
        f"{BASE}/sj/ndsj/yb2004-c/left.htm",
        "yearbook",
        extra_toc_pages=[f"{BASE}/sj/ndsj/yb2004-c/indexch.htm"],
    )

    # 2005-2025 standard left.htm
    for year in range(2005, 2026):
        collect_from_toc(
            year,
            f"{BASE}/sj/ndsj/{year}/left.htm",
            "yearbook",
            extra_toc_pages=[f"{BASE}/sj/ndsj/{year}/indexch.htm"],
        )


def env_years_from_portal_html(html: str) -> list[int]:
    years = set()
    for href, title in iter_links(html):
        m = re.search(r"(?:环境统计数据|hjtjzl/)((?:19|20)\d{2})", href + title)
        if m:
            years.add(int(m.group(1)))
        m2 = re.search(r"\.\./((?:19|20)\d{2})/", href)
        if m2:
            years.add(int(m2.group(1)))
    return sorted(years)


def collect_environment() -> None:
    log("==== Environment statistics portal")
    portal = try_save(
        ENV_PORTAL,
        "environment_stats/portal.html",
        kind="index",
        extra={"title": "环境统计资料 入口（会跳转到最近年份）"},
    )
    # The portal JS-redirects to ./2014/; also save that index and discover years.
    y2014 = try_save(
        f"{ENV_PORTAL}2014/",
        "environment_stats/2014/index.html",
        kind="index",
        referer=ENV_PORTAL,
        extra={"year": 2014, "source": "environment_stats"},
    )
    years = list(range(2003, 2015)) + [1999]
    if y2014:
        discovered = env_years_from_portal_html(decode_html(y2014.read_bytes()))
        if discovered:
            years = discovered
            log(f"Environment years listed on 2014 index: {years}")

    for year in years:
        collect_environment_year(year)


def collect_environment_year(year: int) -> None:
    base = f"{ENV_PORTAL}{year}/"
    log(f"==== Environment stats {year} {base}")
    first_rel = f"environment_stats/{year}/index.html"
    first = try_save(base, first_rel, kind="index", referer=ENV_PORTAL, extra={"year": year, "source": "environment_stats"})
    if not first:
        # try index.html explicitly
        first = try_save(
            urljoin(base, "index.html"),
            first_rel,
            kind="index",
            referer=ENV_PORTAL,
            extra={"year": year, "source": "environment_stats"},
        )
        if not first:
            notes.append(f"Environment stats {year}: index not available")
            return

    html0 = decode_html(first.read_bytes())
    # pagination: createPageHTML(N, 0, "index", "html") -> index.html, index_1.html, ..., index_{N-1}.html
    n_pages = 1
    m = re.search(r'createPageHTML\s*\(\s*(\d+)\s*,\s*\d+\s*,\s*"index"\s*,\s*"html"\s*\)', html0)
    if m:
        n_pages = int(m.group(1))
    log(f"Environment {year}: {n_pages} index page(s)")

    pages = [(urljoin(base, "index.html"), html0)]
    for i in range(1, n_pages):
        u = urljoin(base, f"index_{i}.html")
        rel = f"environment_stats/{year}/index_{i}.html"
        dest = try_save(u, rel, kind="index", referer=base, extra={"year": year, "source": "environment_stats"})
        if dest:
            pages.append((u, decode_html(dest.read_bytes())))

    seen = set()
    n_eq = 0
    for page_url, page_html in pages:
        for href, title in iter_links(page_html):
            if "地震灾害" not in (title or "") and "地震灾害" not in href:
                continue
            if "地震监测" in title:
                continue
            full = urljoin(page_url, href)
            if "stats.gov.cn" not in urlparse(full).netloc:
                continue
            if full in seen:
                continue
            seen.add(full)
            rel = local_rel_from_url(full, "environment_stats")
            # keep under environment_stats/{year}/...
            if collect_table_file(
                full,
                rel,
                year,
                "environment_stats",
                "earthquake_disaster",
                title or "地震灾害情况",
                referer=page_url,
            ):
                n_eq += 1
    log(f"Environment {year}: saved {n_eq} earthquake-disaster table page(s)")
    if n_eq == 0:
        notes.append(f"Environment stats {year}: no 地震灾害 table found in paginated index")


def probe_data_stats() -> None:
    url = "https://data.stats.gov.cn/"
    log(f"==== Probe {url}")
    try:
        time.sleep(0.3)
        r = session.get(url, timeout=20, allow_redirects=True)
        notes.append(f"data.stats.gov.cn probe: HTTP {r.status_code}, {len(r.content)} bytes, final={r.url}")
        log(f"data.stats.gov.cn -> {r.status_code} {len(r.content)}B {r.url}")
        # save a small note file if forbidden
        (ROOT / "data_stats_gov_cn_probe.txt").write_text(
            f"url={url}\nstatus={r.status_code}\nfinal={r.url}\nbytes={len(r.content)}\n"
            f"retrieved={now_cst().isoformat(timespec='seconds')}\n"
            f"head={r.content[:500]!r}\n",
            encoding="utf-8",
        )
    except Exception as e:
        notes.append(f"data.stats.gov.cn probe failed: {e}")
        log(f"data.stats.gov.cn probe failed: {e}")


def write_sources(started: datetime, ended: datetime) -> None:
    # inventory summary
    def count(src, cat=None):
        return sum(1 for r in inventory if r["source"] == src and (cat is None or r["category"] == cat))

    years_eq = sorted({r["year"] for r in inventory if r["category"] == "earthquake_disaster" and r["source"] == "yearbook"})
    years_pop = sorted({r["year"] for r in inventory if r["category"] == "provincial_population"})
    years_gdp = sorted({r["year"] for r in inventory if r["category"] == "regional_gdp"})
    years_env = sorted({r["year"] for r in inventory if r["source"] == "environment_stats"})

    lines = []
    a = lines.append
    a("# 国家统计局外部数据说明")
    a("")
    a("本目录是 DS 2043 选题 07 外部数据的补充收集，只保存国家统计局官网的原始文件，不做清洗、不改数、不删行。")
    a("不改动 `07_external` 中已收集的 catalogs / impact / context 文件。")
    a("")
    a("## 收集范围")
    a("")
    a("已确认范围：")
    a("")
    a("1. 《中国统计年鉴》中的「地震灾害情况」表（全国时间序列 + 当年分省损失口径，以各年年鉴实际表名为准）。")
    a("2. 分省年末常住人口（近年多为「分地区年末人口数」；较早年鉴多为「各地区总人口和出生率、死亡率、自然增长率」等同类表）。")
    a("3. 分省地区生产总值（近年多为「地区生产总值（某年）」；较早年鉴多为「各地区国内生产总值」或「各地区生产总值和指数」）。")
    a("")
    a("另外，官网「环境统计资料 / 环境统计数据」中有独立的「地震灾害情况」分省表（以及部分全国序列），作为同一官方口径的补充一并保存。")
    a("未收集：地震监测、地质灾害、各类自然灾害合计损失、香港/澳门/台湾本地生产总值、支出法或项目结构表、全国核算总表。")
    a("")
    a("## 来源与入口")
    a("")
    a(f"- 中国统计年鉴目录：<{INDEX_NDSJ}>")
    a("  - 2005–2025 年：`/sj/ndsj/{year}/left.htm`（frameset 目录在 `indexch.htm`）。")
    a("  - 2004 年：`/sj/ndsj/yb2004-c/left.htm`")
    a("  - 2003 年：官方发布整本 PDF `/sj/ndsj/yearbook2003_c.pdf`，本批未拆表。")
    a("  - 2002 年：`/yearbook2001/ml/2002_c.htm`")
    a("  - 2001 年：`/sj/ndsj/2001c/mulu.htm` 及各章目录")
    a("  - 2000 年：`/sj/ndsj/zgnj/mulu.html` 及各章目录")
    a("  - 1999 年：`/yearbook/ml/1999_c.htm`")
    a(f"- 环境统计资料：<{ENV_PORTAL}>（入口会转到最近年份 2014；目录中列出 1999、2003–2014 年）。")
    a("- 国家数据网站 `https://data.stats.gov.cn/` 本次从收集环境无法作为来源（见探测记录），因此不以该站为准。")
    a("")
    a("## 口径说明")
    a("")
    a("- 「地震灾害次数」只统计造成人员伤亡或直接经济损失的事件，不等于全部 M≥5 地震；有的年份也包括 5.0 级以下成灾地震，以及震中在境外但影响境内的事件（表注中常以 * 标出）。")
    a("- 年鉴表的资料来源：较早年份注明中国地震局，近年年鉴「资源和环境」篇简要说明中注明地震灾害等情况由应急管理部提供。")
    a("- 环境统计资料中的分省地震灾害表，资料来源同样标注为中国地震局。该系列在官网目前更新到 2014 年。")
    a("- 分省人口、地区生产总值为中国部分后续分析的暴露度支撑，不是地震目录本身。")
    a("- 近两年年鉴表多为官方 JPG；较早年份常见 HTML，并可能附带 Excel。均保留官网原始格式，不在本步转录为 CSV。")
    a("")
    a("## 抓取信息")
    a("")
    a(f"- 抓取开始：{started.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    a(f"- 抓取结束：{ended.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    a(f"- User-Agent：`{USER_AGENT}`")
    a("- 目的：BNBU DS 2043 课程项目学术使用。")
    a("- 著作权与使用：文件版权归国家统计局及原资料提供单位；本目录仅保存官网公开页面/文件，用于课程学习。具体转载与使用以国家统计局网站声明为准。")
    a("")
    a("## 本次收集结果（原始文件，未清洗）")
    a("")
    a(f"- 保存文件数：{len(files)}")
    a(f"- 已分类的年鉴「地震灾害情况」表（按年鉴年份）：{years_eq if years_eq else '无'}")
    a(f"- 已分类的分省人口表（按年鉴年份）：{years_pop if years_pop else '无'}")
    a(f"- 已分类的地区生产总值表（按年鉴年份）：{years_gdp if years_gdp else '无'}")
    a(f"- 环境统计资料中的地震灾害表（按资料年份）：{years_env if years_env else '无'}")
    a("")
    if notes:
        a("## 备注与缺口")
        a("")
        for n in notes:
            a(f"- {n}")
        a("")
    a("## 分类清单")
    a("")
    a("| 年份 | 来源 | 类别 | 表名 | 相对路径 |")
    a("| --- | --- | --- | --- | --- |")
    for r in inventory:
        title = r["title"].replace("|", "\\|")
        a(f"| {r['year']} | {r['source']} | {r['category']} | {title} | `{r['path']}` |")
    a("")
    SOURCES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Wrote {SOURCES_PATH}")


def append_main_pointer() -> None:
    main = Path("/workspace/07_external/SOURCES.md")
    marker = "## 补充：国家统计局（nbs/）"
    if not main.exists():
        return
    text = main.read_text(encoding="utf-8")
    if marker in text:
        return
    block = (
        "\n\n"
        f"{marker}\n\n"
        "2026-11-15 起，在本目录下新增 `nbs/`，从国家统计局官网收集《中国统计年鉴》"
        "「地震灾害情况」表，以及分省年末常住人口、地区生产总值；并补充「环境统计资料」中的地震灾害表。\n"
        "只保存官方原始文件，不清洗，也不改动本文件以上已记录的 catalogs / impact / context 数据。\n"
        "详细来源、口径、抓取参数和文件清单见 [`nbs/SOURCES.md`](nbs/SOURCES.md)。\n"
    )
    main.write_text(text.rstrip() + block, encoding="utf-8")
    log("Appended pointer section to /workspace/07_external/SOURCES.md")


def write_manifest(started: datetime, ended: datetime) -> None:
    manifest = {
        "retrieval_utc": ended.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "retrieval_cst": ended.isoformat(timespec="seconds"),
        "started_cst": started.isoformat(timespec="seconds"),
        "user_agent": USER_AGENT,
        "source_sites": [INDEX_NDSJ, ENV_PORTAL],
        "scope": [
            "yearbook:earthquake_disaster",
            "yearbook:provincial_population",
            "yearbook:regional_gdp",
            "environment_stats:earthquake_disaster",
        ],
        "files": files,
        "inventory": inventory,
        "notes": notes,
        "failures": failures,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote {MANIFEST_PATH}")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists():
        LOG_PATH.write_text("", encoding="utf-8")
    started = now_cst()
    log("START NBS official collection")
    probe_data_stats()
    collect_yearbooks()
    collect_environment()
    ended = now_cst()
    write_sources(started, ended)
    write_manifest(started, ended)
    append_main_pointer()
    log(
        f"DONE files={len(files)} inventory={len(inventory)} failures={len(failures)} notes={len(notes)}"
    )


if __name__ == "__main__":
    main()
