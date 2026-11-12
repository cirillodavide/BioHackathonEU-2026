"""Compare Elixir topic BIP! stats to year-matched OpenAlex Monte Carlo samples.

For each of the top-N Elixir primary topics:
  1. Draw B year-stratified random OpenAlex samples of size n_t (excluding Elixir DOIs)
  2. Score them with BIP!
  3. Recompute the same topic stats as count_topics.py
  4. Place Elixir values in the null (mean, p2.5–p97.5, percentile, two-sided p)

Persists sample membership for reuse, writes comparison CSVs, figures, and a short report.

Requires: Python 3.9+, matplotlib

Usage:
  python scripts/compare_topic_bip_openalex.py
  python scripts/compare_topic_bip_openalex.py --top 5 --replicates 500 --seed 42
  python scripts/compare_topic_bip_openalex.py --reuse-samples
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from count_topics import (  # noqa: E402
    CLASS_COLS,
    SCORE_COLS,
    STATS_HEADER,
    group_by_topic,
    load_rows,
    topic_stats,
    to_float,
)

DEFAULT_INPUT = ROOT / "data" / "elixir_works_metadata_openalex_bip.csv"
DEFAULT_COUNTS = ROOT / "results" / "openalex_topic_counts.csv"
SAMPLES_DIR = ROOT / "results" / "topic_comparison_samples"
AUTHORS_CSV = SAMPLES_DIR / "samples_authors.csv"
CACHE_DIR = ROOT / "results" / "cache"
BIP_CACHE = CACHE_DIR / "bip_scores.jsonl"
COMPARISON_CSV = ROOT / "results" / "openalex_topic_comparison.csv"
REPLICATES_CSV = ROOT / "results" / "openalex_topic_comparison_replicates.csv"
FIGURES_DIR = ROOT / "results" / "topic_comparison_figures"
REPORT_MD = ROOT / "results" / "topic_comparison_report.md"

OPENALEX = "https://api.openalex.org"
BIP = "https://bip-api.imsi.athenarc.gr"
MAILTO = "biohackathon-eu-2026"
USER_AGENT = f"BHEU26-topic-compare (mailto:{MAILTO})"

STAT_KEYS = [k for k in STATS_HEADER if k not in {"topic", "n_papers"}]
# Absolute AttRank/PageRank scores are hard to read in plots; keep class shares instead.
PLOT_STAT_KEYS = [k for k in STAT_KEYS if k not in {"median_popularity", "median_influence"}]
STAT_LABELS = {
    "median_popularity": "Median BIP! popularity (AttRank)",
    "median_influence": "Median BIP! influence (PageRank)",
    "median_impulse": "Median BIP! impulse (3-year citation count)",
    "median_cc": "Median BIP! citation count",
    "pct_pop_top10": "Share of papers in BIP! popularity top 10%",
    "pct_inf_top10": "Share of papers in BIP! influence top 10%",
    "pct_imp_top10": "Share of papers in BIP! impulse top 10%",
    "pct_cc_top10": "Share of papers in BIP! citation-count top 10%",
}
csv.field_size_limit(sys.maxsize)


# ------------------------------------------------------------------ HTTP / cache


def http_json(url: str, retries: int = 4, sleep: float = 0.15):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(sleep)
            return data
        except urllib.error.HTTPError as exc:
            last = exc
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503, 504}:
                time.sleep(min(30, 2 ** attempt))
                continue
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:300]}") from exc
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Failed {url}: {last}")


def load_bip_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            doi = (row.get("doi") or "").strip().lower()
            if doi:
                cache[doi] = row
    return cache


def append_bip_cache(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_doi(value: str) -> str:
    doi = (value or "").strip()
    if not doi:
        return ""
    doi = urllib.parse.unquote(doi)
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    doi = doi.removeprefix("https://dx.doi.org/").removeprefix("http://dx.doi.org/")
    return doi.strip().rstrip(".,;").lower()


def bip_batch(dois: list[str], cache: dict[str, dict]) -> dict[str, dict]:
    """Return {doi: bip_row} for requested DOIs, filling cache via BIP! batch API."""
    out: dict[str, dict] = {}
    missing = []
    for doi in dois:
        key = normalize_doi(doi)
        if not key:
            continue
        if key in cache:
            out[key] = cache[key]
        else:
            missing.append(key)

    new_rows = []
    for i in range(0, len(missing), 50):
        chunk = missing[i:i + 50]
        encoded = urllib.parse.quote(",".join(chunk), safe=",")
        url = f"{BIP}/paper/scores/batch/{encoded}"
        try:
            data = http_json(url, sleep=0.05)
        except Exception as exc:  # noqa: BLE001
            print(f"  BIP batch failed ({exc}); falling back to single lookups", flush=True)
            data = []
            for doi in chunk:
                try:
                    one = http_json(f"{BIP}/paper/scores/{urllib.parse.quote(doi, safe='')}", sleep=0.05)
                    if isinstance(one, dict) and one.get("doi"):
                        data.append(one)
                except Exception:
                    continue
        if not isinstance(data, list):
            continue
        for item in data:
            doi = normalize_doi(item.get("doi") or "")
            if not doi:
                continue
            row = {
                "doi": doi,
                "popularity": item.get("attrank", ""),
                "pop_class": item.get("pop_class", ""),
                "influence": item.get("pagerank", ""),
                "inf_class": item.get("inf_class", ""),
                "impulse": item.get("3_year_cc", ""),
                "imp_class": item.get("imp_class", ""),
                "cc": item.get("cc", ""),
                "cc_class": item.get("cc_class", ""),
            }
            # mark missing BIP coverage
            if row["cc"] == "" and row["pop_class"] == "":
                row["bip_found"] = False
            else:
                row["bip_found"] = True
            cache[doi] = row
            out[doi] = row
            new_rows.append(row)
        # DOIs in chunk with no response
        found = {normalize_doi(x.get("doi") or "") for x in data if isinstance(x, dict)}
        for doi in chunk:
            if doi not in found and doi not in cache:
                empty = {"doi": doi, "bip_found": False,
                         "popularity": "", "pop_class": "", "influence": "", "inf_class": "",
                         "impulse": "", "imp_class": "", "cc": "", "cc_class": ""}
                cache[doi] = empty
                out[doi] = empty
                new_rows.append(empty)
    if new_rows:
        append_bip_cache(BIP_CACHE, new_rows)
    return out


def seed_bip_cache_from_elixir(rows: list[dict], cache: dict[str, dict]) -> int:
    added = []
    for r in rows:
        doi = normalize_doi(r.get("doi") or r.get("doi_final") or "")
        if not doi or doi in cache:
            continue
        if not (r.get("cc") or r.get("popularity") or r.get("pop_class")):
            continue
        row = {
            "doi": doi,
            "popularity": r.get("popularity", ""),
            "pop_class": r.get("pop_class", ""),
            "influence": r.get("influence", ""),
            "inf_class": r.get("inf_class", ""),
            "impulse": r.get("impulse", ""),
            "imp_class": r.get("imp_class", ""),
            "cc": r.get("cc", ""),
            "cc_class": r.get("cc_class", ""),
            "bip_found": True,
        }
        cache[doi] = row
        added.append(row)
    if added:
        append_bip_cache(BIP_CACHE, added)
    return len(added)


# ------------------------------------------------------------------ OpenAlex


def resolve_topic_id(name: str) -> tuple[str, str, int]:
    """Return (topic_id, display_name, works_count) with exact name preferred."""
    url = f"{OPENALEX}/topics?search={urllib.parse.quote(name)}&per_page=25"
    data = http_json(url)
    results = data.get("results") or []
    exact = [t for t in results if (t.get("display_name") or "") == name]
    pick = exact[0] if exact else (results[0] if results else None)
    if not pick:
        sys.exit(f"OpenAlex topic not found: {name!r}")
    tid = (pick.get("id") or "").rsplit("/", 1)[-1]
    return tid, pick.get("display_name") or name, int(pick.get("works_count") or 0)


def openalex_sample(topic_id: str, year: int, n: int, seed: int) -> list[dict]:
    n = max(1, min(n, 200))
    filt = f"primary_topic.id:{topic_id},publication_year:{year},has_doi:true"
    url = (
        f"{OPENALEX}/works?filter={urllib.parse.quote(filt, safe=':,')}"
        f"&sample={n}&seed={seed}&per-page={n}"
        f"&select=id,doi,publication_year,title"
    )
    data = http_json(url)
    works = []
    for w in data.get("results") or []:
        doi = normalize_doi(w.get("doi") or "")
        wid = (w.get("id") or "").rsplit("/", 1)[-1]
        if not doi or not wid:
            continue
        works.append({
            "openalex_work_id": wid,
            "doi": doi,
            "year": int(w.get("publication_year") or year),
            "title": w.get("title") or "",
        })
    return works


def split_person_name(full: str) -> tuple[str, str]:
    """Best-effort first/last from OpenAlex display/raw name; empty if unclear."""
    text = (full or "").strip()
    if not text:
        return "", ""
    lower = text.lower()
    if any(tok in lower for tok in (
        "consortium", "community", "collaboration", "network", " group", "team",
        "members", "committee",
    )):
        return "", ""
    # Prefer "Last, First Middle" when a single comma is present
    if text.count(",") == 1:
        last, first = [p.strip() for p in text.split(",", 1)]
        first_tok = first.split()[0] if first.split() else ""
        last_tok = last.split()[-1] if last.split() else ""
        if first_tok and last_tok:
            return first_tok, last_tok
        return "", ""
    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[-1]


def authorships_from_work(work: dict) -> list[dict]:
    """Parse OpenAlex work authorships into rows with best-effort first/last."""
    wid = (work.get("id") or "").rsplit("/", 1)[-1]
    doi = normalize_doi(work.get("doi") or "")
    rows = []
    for i, a in enumerate(work.get("authorships") or [], start=1):
        author = a.get("author") or {}
        raw = (a.get("raw_author_name") or "").strip()
        display = (author.get("display_name") or "").strip()
        full = display or raw
        first, last = split_person_name(full) if full else ("", "")
        oa_id = (author.get("id") or "").rsplit("/", 1)[-1]
        rows.append({
            "openalex_work_id": wid,
            "doi": doi,
            "author_order": i,
            "author_position": (a.get("author_position") or "").strip(),
            "full_name": full,
            "first_name": first,
            "last_name": last,
            "raw_author_name": raw,
            "oa_author_id": oa_id,
        })
    return rows


def fetch_works_authorships(work_ids: list[str]) -> dict[str, list[dict]]:
    """Return {openalex_work_id: [author rows]} via OpenAlex batched works lookups."""
    out: dict[str, list[dict]] = {}
    ids = [w for w in work_ids if w]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        # OpenAlex accepts pipe-separated openalex IDs
        filt = "|".join(chunk)
        url = (
            f"{OPENALEX}/works?filter=openalex_id:{urllib.parse.quote(filt, safe='|')}"
            f"&per-page={len(chunk)}"
            f"&select=id,doi,authorships"
        )
        try:
            data = http_json(url, sleep=0.12)
        except Exception as exc:  # noqa: BLE001
            print(f"  authorship batch failed ({exc}); falling back to singles", flush=True)
            data = {"results": []}
            for wid in chunk:
                try:
                    one = http_json(
                        f"{OPENALEX}/works/{wid}?select=id,doi,authorships", sleep=0.12)
                    if isinstance(one, dict) and one.get("id"):
                        data["results"].append(one)
                except Exception:
                    continue
        for work in data.get("results") or []:
            wid = (work.get("id") or "").rsplit("/", 1)[-1]
            if wid:
                out[wid] = authorships_from_work(work)
        if (i // 50 + 1) % 20 == 0 or i + 50 >= len(ids):
            print(f"  authorships: {min(i + 50, len(ids))}/{len(ids)} works", flush=True)
    return out


def attach_authors_to_samples(sample_rows: list[dict]) -> list[dict]:
    """Fetch authorships for unique sample works; set authors on samples; return author rows."""
    work_ids = sorted({(r.get("openalex_work_id") or "").strip() for r in sample_rows
                       if (r.get("openalex_work_id") or "").strip()})
    print(f"Fetching authorships for {len(work_ids)} unique OpenAlex works…", flush=True)
    by_work = fetch_works_authorships(work_ids)
    for r in sample_rows:
        wid = (r.get("openalex_work_id") or "").strip()
        authors = by_work.get(wid) or []
        names = [a["full_name"] for a in authors if a.get("full_name")]
        r["authors"] = "; ".join(names)
        r["n_authors"] = len(authors)
    # one row per work×author (deduped by work)
    author_rows: list[dict] = []
    for wid in work_ids:
        author_rows.extend(by_work.get(wid) or [])
    return author_rows


def write_authors_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "openalex_work_id", "doi", "author_order", "author_position",
        "full_name", "first_name", "last_name", "raw_author_name", "oa_author_id",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_year_pool(
    topic_id: str,
    year: int,
    need: int,
    exclude: set[str],
    cache: dict[str, dict],
    base_seed: int,
) -> list[dict]:
    """Collect unique DOI works with BIP coverage for topic-year."""
    # Enough headroom for large B local draws without huge API cost on sparse years.
    target = min(2000, max(need * 15, need + 100, 150))
    by_doi: dict[str, dict] = {}
    seed = base_seed + year * 1009
    rounds = 0
    stagnant = 0
    while len(by_doi) < target and rounds < 25 and stagnant < 5:
        rounds += 1
        before = len(by_doi)
        batch = openalex_sample(topic_id, year, 200, seed + rounds)
        candidates = []
        for w in batch:
            if w["doi"] in exclude or w["doi"] in by_doi:
                continue
            candidates.append(w)
        if candidates:
            bip_batch([w["doi"] for w in candidates], cache)
            for w in candidates:
                row = cache.get(w["doi"]) or {}
                if row.get("bip_found"):
                    by_doi[w["doi"]] = {**w, **{k: row.get(k, "") for k in
                        ["popularity", "pop_class", "influence", "inf_class",
                         "impulse", "imp_class", "cc", "cc_class"]}}
        if len(by_doi) == before:
            stagnant += 1
        else:
            stagnant = 0
        print(f"    year {year}: pool {len(by_doi)}/{target} (round {rounds})", flush=True)
        if len(batch) < 10:
            break
    return list(by_doi.values())


# ------------------------------------------------------------------ sampling / stats


def year_counts(papers: list[dict]) -> Counter:
    c: Counter = Counter()
    for p in papers:
        y = (p.get("publication_year") or "").strip()
        if y.isdigit():
            c[int(y)] += 1
    return c


def draw_stratified_sample(
    pools: dict[int, list[dict]],
    years: Counter,
    rng: random.Random,
) -> list[dict]:
    sample = []
    for year, n in sorted(years.items()):
        pool = pools.get(year) or []
        if len(pool) < n:
            # with replacement if pool too small
            if not pool:
                continue
            picked = [dict(rng.choice(pool)) for _ in range(n)]
        else:
            picked = [dict(x) for x in rng.sample(pool, n)]
        for p in picked:
            p["year"] = year
        sample.extend(picked)
    return sample


def stats_as_floats(stats: dict) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in STAT_KEYS:
        val = stats.get(key, "")
        out[key] = to_float(str(val)) if val != "" and val is not None else None
    return out


def summarize_null(values: list[float], elixir: float | None) -> dict:
    if not values:
        return {
            "null_mean": "", "null_p2_5": "", "null_p97_5": "",
            "elixir_percentile": "", "p_two_sided": "", "outside_95": "",
            "direction": "",
        }
    values_sorted = sorted(values)
    mean = statistics.mean(values)
    p2 = percentile(values_sorted, 2.5)
    p97 = percentile(values_sorted, 97.5)
    if elixir is None:
        return {
            "null_mean": mean, "null_p2_5": p2, "null_p97_5": p97,
            "elixir_percentile": "", "p_two_sided": "", "outside_95": "",
            "direction": "",
        }
    # empirical percentile: fraction of null values <= elixir
    le = sum(1 for v in values if v <= elixir)
    percentile_elixir = 100.0 * le / len(values)
    # two-sided p: extremity vs null mean
    extreme = abs(elixir - mean)
    as_extreme = sum(1 for v in values if abs(v - mean) >= extreme - 1e-15)
    p = as_extreme / len(values)
    outside = elixir < p2 or elixir > p97
    if elixir > mean:
        direction = "higher"
    elif elixir < mean:
        direction = "lower"
    else:
        direction = "equal"
    return {
        "null_mean": mean,
        "null_p2_5": p2,
        "null_p97_5": p97,
        "elixir_percentile": round(percentile_elixir, 1),
        "p_two_sided": round(p, 4),
        "outside_95": outside,
        "direction": direction if outside else "inside",
    }


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (q / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - pos) + sorted_vals[hi] * (pos - lo)


def fmt_num(x) -> str:
    if x == "" or x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        if abs(x) != 0 and (abs(x) < 1e-3 or abs(x) >= 1e4):
            return f"{x:.6E}".replace("E+", "E").replace("E-0", "E-")
        return f"{x:.6g}"
    return str(x)


# ------------------------------------------------------------------ I/O


def read_top_topics(counts_path: Path, top: int) -> list[tuple[str, int]]:
    rows = []
    with counts_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append((row["topic"], int(row["count"])))
    return rows[:top]


def write_samples_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "topic", "topic_id", "replicate", "year", "openalex_work_id", "doi", "seed_used",
        "n_authors", "authors",
        "popularity", "pop_class", "influence", "inf_class", "impulse", "imp_class", "cc", "cc_class",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_samples_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------ plots / report


def make_figures(comparison_rows: list[dict], replicate_rows: list[dict], out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    topics = []
    for r in comparison_rows:
        if r["topic"] not in topics:
            topics.append(r["topic"])

    band_color = "#9aa5b1"
    forest_legend = [
        Patch(facecolor=band_color, edgecolor="none", alpha=0.85,
              label="OpenAlex central 95% range"),
        Line2D([0], [0], marker="o", linestyle="None", markersize=8,
               markerfacecolor="none", markeredgecolor=band_color, markeredgewidth=1.5,
               label="OpenAlex sample mean"),
        Line2D([0], [0], marker="o", color="#c0392b", linestyle="None",
               markersize=8, label="ELIXIR value"),
    ]

    # 1) Forest plots per statistic (skip raw popularity/influence scores)
    for stat in PLOT_STAT_KEYS:
        subset = [r for r in comparison_rows if r["statistic"] == stat]
        if not subset:
            continue
        label = STAT_LABELS.get(stat, stat)
        fig, ax = plt.subplots(figsize=(10, 0.7 * len(subset) + 2.4))
        y = np.arange(len(subset))
        for i, r in enumerate(subset):
            p2 = to_float(r["null_p2_5"])
            p97 = to_float(r["null_p97_5"])
            mean = to_float(r["null_mean"])
            elx = to_float(r["elixir_value"])
            if p2 is not None and p97 is not None:
                ax.hlines(i, p2, p97, color=band_color, linewidth=6, alpha=0.85, zorder=1)
            if mean is not None:
                ax.plot(mean, i, "o", markersize=8, markerfacecolor="none",
                        markeredgecolor=band_color, markeredgewidth=1.5, zorder=2)
            if elx is not None:
                ax.plot(elx, i, "o", color="#c0392b", markersize=8, zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels([wrap_topic(r["topic"]) for r in subset], fontsize=9)
        ax.set_xlabel(label)
        ax.invert_yaxis()
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.legend(handles=forest_legend, loc="lower center", bbox_to_anchor=(0.5, 1.02),
                  ncol=3, fontsize=8, frameon=True)
        fig.tight_layout()
        path = out_dir / f"forest_{stat}.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    # 2) Null histograms (skip raw popularity/influence scores)
    for stat in PLOT_STAT_KEYS:
        label = STAT_LABELS.get(stat, stat)
        n_rep = len({r["replicate"] for r in replicate_rows}) or "B"
        fig, axes = plt.subplots(1, len(topics), figsize=(3.4 * len(topics), 3.8), sharey=False)
        if len(topics) == 1:
            axes = [axes]
        for i, (ax, topic) in enumerate(zip(axes, topics)):
            vals = [to_float(r[stat]) for r in replicate_rows
                    if r["topic"] == topic and to_float(r.get(stat)) is not None]
            vals = [v for v in vals if v is not None]
            elx_row = next((r for r in comparison_rows
                            if r["topic"] == topic and r["statistic"] == stat), None)
            elx = to_float(elx_row["elixir_value"]) if elx_row else None
            if vals:
                ax.hist(vals, bins=min(15, max(5, len(set(vals)))), color="#cbd5e1",
                        edgecolor="white", label="OpenAlex samples")
            if elx is not None:
                ax.axvline(elx, color="#c0392b", linewidth=2, label="ELIXIR value")
            ax.set_title(wrap_topic(topic, width=22), fontsize=9)
            ax.set_xlabel(label, fontsize=8)
            if topic == topics[0]:
                ax.set_ylabel("Number of OpenAlex samples")
            ax.tick_params(labelsize=8)
            if i == 0:
                ax.legend(fontsize=7, loc="best", frameon=True)
        fig.suptitle(
            f"{label}\nacross {n_rep} year-matched OpenAlex samples",
            fontsize=11,
        )
        fig.tight_layout()
        path = out_dir / f"null_hist_{stat}.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    return paths


def short_topic(name: str, n: int = 34) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def wrap_topic(name: str, width: int = 28) -> str:
    import textwrap
    return "\n".join(textwrap.wrap(name, width=width)) or name


def write_report(
    path: Path,
    topics: list[tuple[str, int, str, int]],
    comparison_rows: list[dict],
    figure_paths: list[Path],
    replicates: int,
    seed: int,
) -> None:
    outside = [r for r in comparison_rows if str(r["outside_95"]).lower() == "true"]
    lines = [
        "# Elixir vs OpenAlex topic BIP! comparison",
        "",
        "## Process",
        "",
        f"Starting from `data/elixir_works_metadata_openalex_bip.csv`, we counted how often each "
        f"OpenAlex **primary topic** appears among ELIXIR papers and ranked topics by that "
        f"frequency (`results/openalex_topic_counts.csv`). We then kept the **top {len(topics)}** "
        f"topics and, for each, summarised BIP! impact on the ELIXIR papers in that topic "
        f"(medians of impulse and citation count; share of papers in the BIP! top 10% for "
        f"popularity, influence, impulse, and citations—see `results/openalex_topic_stats.csv`). "
        f"To ask whether those ELIXIR values are unusual for the topic, we built a reference from "
        f"the wider OpenAlex graph: for a topic with n ELIXIR papers we drew **{replicates}** random "
        f"OpenAlex samples of size n, matching ELIXIR’s publication-year mix, restricted to the "
        f"same primary topic, requiring a DOI, excluding ELIXIR DOIs, and scoring each paper with "
        f"BIP!. The same statistics were recomputed on every sample. Across the {replicates} draws "
        f"we report the mean and the central 95% range (2.5th–97.5th percentiles) and place the "
        f"ELIXIR value in that range (including whether it falls outside). Plots are in "
        f"[`topic_comparison_figures/`](topic_comparison_figures/). Raw popularity/influence score "
        f"plots are omitted; we keep the top-10% class shares instead. Seed `{seed}`. "
        f"OpenAlex n is the topic’s `works_count` from the OpenAlex topics API "
        f"(all works with that primary topic). Sample papers include OpenAlex author "
        f"lists in `topic_comparison_samples/samples.csv` (`authors`) and "
        f"`samples_authors.csv` (one row per author, with best-effort "
        f"`first_name`/`last_name` when the name string can be split).",
        "",
        "### Topics",
        "",
        "| Topic | ELIXIR n | OpenAlex n | OpenAlex topic id |",
        "|---|---:|---:|---|",
    ]
    for name, n, tid, oa_n in topics:
        oa_s = f"{oa_n:,}" if oa_n else ""
        lines.append(f"| {name} | {n} | {oa_s} | `{tid}` |")

    forest_files = [p for p in figure_paths if p.name.startswith("forest_")]
    hist_files = [p for p in figure_paths if p.name.startswith("null_hist_")]

    lines += [
        "",
        "## Forest plots",
        "",
        "One panel per BIP! statistic. Each row is a topic. The grey bar is the central 95% "
        f"range of that statistic across the {replicates} year-matched OpenAlex samples; the "
        "open grey circle is the mean of those samples; the red point is the ELIXIR value for the topic. "
        "Use these to see, at a glance, whether ELIXIR sits inside or outside the OpenAlex "
        "reference band for every topic.",
        "",
    ]
    if forest_files:
        for p in forest_files:
            key = p.stem.removeprefix("forest_")
            label = STAT_LABELS.get(key, key)
            lines += [
                f"### {label}",
                "",
                f"![{label}](topic_comparison_figures/{p.name})",
                "",
            ]
    else:
        lines += ["_No forest plots generated._", ""]

    lines += [
        "## Null histograms",
        "",
        "One figure per BIP! statistic, with a small histogram for each topic. Bars show the "
        f"distribution of the {replicates} OpenAlex-sample values; the red vertical line is the "
        "ELIXIR value. Use these to see the shape of the OpenAlex null and how far ELIXIR lies "
        "from that cloud.",
        "",
    ]
    if hist_files:
        for p in hist_files:
            key = p.stem.removeprefix("null_hist_")
            label = STAT_LABELS.get(key, key)
            lines += [
                f"### {label}",
                "",
                f"![{label}](topic_comparison_figures/{p.name})",
                "",
            ]
    else:
        lines += ["_No null histograms generated._", ""]

    lines += [
        "## Main findings",
        "",
        f"**{len(outside)}** topic×statistic pairs fall **outside** the 95% OpenAlex reference band "
        f"(of {len(comparison_rows)} comparisons).",
        "",
    ]
    if outside:
        lines += [
            "| Topic | Statistic | Elixir | OpenAlex mean | 95% band | Direction | p |",
            "|---|---|---:|---:|---|---|---:|",
        ]
        for r in outside:
            band = f"[{fmt_num(to_float(r['null_p2_5']))}, {fmt_num(to_float(r['null_p97_5']))}]"
            lines.append(
                f"| {short_topic(r['topic'], 40)} | `{r['statistic']}` | {fmt_num(to_float(r['elixir_value']))} "
                f"| {fmt_num(to_float(r['null_mean']))} | {band} | {r['direction']} | {r['p_two_sided']} |"
            )
        lines.append("")
    else:
        lines += ["No pairs outside the 95% band.", ""]

    lines += [
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--counts", type=Path, default=DEFAULT_COUNTS)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--replicates", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reuse-samples", action="store_true",
                        help="Reload saved sample membership instead of re-sampling")
    parser.add_argument("--enrich-authors", action="store_true",
                        help="With --reuse-samples, (re)fetch OpenAlex authorships for sample works")
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Not found: {args.input}")
    if not args.counts.exists():
        sys.exit(f"Not found: {args.counts}: run scripts/count_topics.py first")

    elixir_rows = load_rows(args.input)
    groups = group_by_topic(elixir_rows)
    top = read_top_topics(args.counts, args.top)
    print(f"Top {len(top)} topics:", flush=True)
    for name, n in top:
        print(f"  {name}: {n}", flush=True)

    exclude = {normalize_doi(r.get("doi") or "") for r in elixir_rows}
    exclude.discard("")

    bip_cache = load_bip_cache(BIP_CACHE)
    n_seeded = seed_bip_cache_from_elixir(elixir_rows, bip_cache)
    print(f"BIP cache: {len(bip_cache)} DOIs ({n_seeded} seeded from Elixir file)", flush=True)

    samples_path = SAMPLES_DIR / "samples.csv"
    manifest_path = SAMPLES_DIR / "manifest.json"
    sample_rows: list[dict] = []
    # (name, n_elixir, topic_id, openalex_n)
    topic_meta: list[tuple[str, int, str, int]] = []

    if args.reuse_samples:
        if not samples_path.exists():
            sys.exit(f"--reuse-samples set but missing {samples_path}")
        sample_rows = load_samples_csv(samples_path)
        print(f"Reusing {len(sample_rows)} sample rows from {samples_path}", flush=True)
        # enrich any missing BIP fields
        dois = sorted({normalize_doi(r["doi"]) for r in sample_rows})
        bip_batch(dois, bip_cache)
        for r in sample_rows:
            doi = normalize_doi(r["doi"])
            row = bip_cache.get(doi) or {}
            for k in ["popularity", "pop_class", "influence", "inf_class",
                      "impulse", "imp_class", "cc", "cc_class"]:
                if not (r.get(k) or "").strip() and row.get(k) not in (None, ""):
                    r[k] = row.get(k, "")
        # topic meta from manifest or samples; fill OpenAlex works_count from API/manifest
        raw_topics: list[tuple[str, int, str, int]] = []
        if manifest_path.exists():
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            for t in man.get("topics", []):
                raw_topics.append((
                    t["name"], int(t["n_elixir"]), t["topic_id"],
                    int(t.get("openalex_n") or t.get("works_count") or 0),
                ))
        if not raw_topics:
            seen = []
            for r in sample_rows:
                if r["topic"] not in seen:
                    seen.append(r["topic"])
                    n = next(c for name, c in top if name == r["topic"])
                    raw_topics.append((r["topic"], n, r.get("topic_id", ""), 0))
        for name, n, tid, oa_n in raw_topics:
            if not oa_n:
                try:
                    _, _, oa_n = resolve_topic_id(name)
                except Exception as exc:  # noqa: BLE001
                    print(f"  warning: could not fetch OpenAlex n for {name}: {exc}", flush=True)
                    oa_n = 0
            topic_meta.append((name, n, tid, oa_n))
        # persist OpenAlex n into the samples manifest for later reuse
        if manifest_path.exists():
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
            by_name = {name: oa_n for name, _n, _tid, oa_n in topic_meta}
            for t in man.get("topics", []):
                if t.get("name") in by_name:
                    t["openalex_n"] = by_name[t["name"]]
            manifest_path.write_text(json.dumps(man, indent=2), encoding="utf-8")
        if args.enrich_authors or any(not (r.get("authors") or "").strip() for r in sample_rows[:20]):
            author_rows = attach_authors_to_samples(sample_rows)
            write_authors_csv(AUTHORS_CSV, author_rows)
            write_samples_csv(samples_path, sample_rows)
            if manifest_path.exists():
                man = json.loads(manifest_path.read_text(encoding="utf-8"))
                man["n_unique_works_with_authors"] = len({r.get("openalex_work_id") for r in author_rows})
                man["n_author_rows"] = len(author_rows)
                manifest_path.write_text(json.dumps(man, indent=2), encoding="utf-8")
            print(f"Wrote authorships -> {AUTHORS_CSV}", flush=True)
    else:
        for name, n in top:
            tid, display, works_count = resolve_topic_id(name)
            print(f"\n=== {display} ({tid}, OpenAlex works≈{works_count}) ===", flush=True)
            papers = groups.get(name) or []
            years = year_counts(papers)
            if sum(years.values()) != len(papers):
                # drop papers without year from stratification target; keep n from counts file
                print(f"  warning: {len(papers) - sum(years.values())} papers missing year", flush=True)
            topic_meta.append((name, n, tid, works_count))

            pools: dict[int, list[dict]] = {}
            for year, n_y in sorted(years.items()):
                print(f"  building pool for {year} (need {n_y})", flush=True)
                pools[year] = build_year_pool(tid, year, n_y, exclude, bip_cache, args.seed)
                if len(pools[year]) < n_y:
                    print(f"  WARNING: pool for {year} has only {len(pools[year])} < {n_y}", flush=True)

            for rep in range(args.replicates):
                topic_salt = sum(ord(ch) for ch in name) % 10_000
                rng = random.Random(args.seed + 17 * topic_salt + rep)
                sample = draw_stratified_sample(pools, years, rng)
                for paper in sample:
                    sample_rows.append({
                        "topic": name,
                        "topic_id": tid,
                        "replicate": rep,
                        "year": paper.get("year", ""),
                        "openalex_work_id": paper.get("openalex_work_id", ""),
                        "doi": paper.get("doi", ""),
                        "seed_used": args.seed,
                        "popularity": paper.get("popularity", ""),
                        "pop_class": paper.get("pop_class", ""),
                        "influence": paper.get("influence", ""),
                        "inf_class": paper.get("inf_class", ""),
                        "impulse": paper.get("impulse", ""),
                        "imp_class": paper.get("imp_class", ""),
                        "cc": paper.get("cc", ""),
                        "cc_class": paper.get("cc_class", ""),
                    })
                if (rep + 1) % 20 == 0 or (rep + 1) == args.replicates:
                    print(f"  drawn replicate {rep + 1}/{args.replicates}", flush=True)

        SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        author_rows = attach_authors_to_samples(sample_rows)
        write_authors_csv(AUTHORS_CSV, author_rows)
        write_samples_csv(samples_path, sample_rows)
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "input": str(args.input),
            "top": args.top,
            "replicates": args.replicates,
            "seed": args.seed,
            "excluded_elixir_dois": len(exclude),
            "n_sample_rows": len(sample_rows),
            "n_unique_works_with_authors": len({r.get("openalex_work_id") for r in author_rows}),
            "n_author_rows": len(author_rows),
            "sampling_note": (
                "Year-stratified samples: OpenAlex sample+seed builds per-year candidate pools "
                "with BIP coverage; each replicate is a local RNG draw matching the Elixir year histogram. "
                "Author lists come from OpenAlex authorships; first_name/last_name are best-effort "
                "splits of display_name/raw_author_name (empty when unclear)."
            ),
            "topics": [
                {"name": name, "n_elixir": n, "topic_id": tid, "openalex_n": oa_n}
                for name, n, tid, oa_n in topic_meta
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\nWrote {samples_path}, {AUTHORS_CSV}, and {manifest_path}", flush=True)

    # ---- compute replicate stats + comparison
    elixir_stats = {name: stats_as_floats(topic_stats(groups[name])) for name, _, _, _ in topic_meta}

    # group samples
    by_topic_rep: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in sample_rows:
        by_topic_rep[(r["topic"], int(r["replicate"]))].append(r)

    replicate_out = []
    null_values: dict[tuple[str, str], list[float]] = defaultdict(list)

    for name, n, tid, _oa_n in topic_meta:
        reps = sorted({int(r["replicate"]) for r in sample_rows if r["topic"] == name})
        for rep in reps:
            papers = by_topic_rep[(name, rep)]
            # map to count_topics field names
            mapped = []
            for p in papers:
                mapped.append({
                    "popularity": p.get("popularity", ""),
                    "influence": p.get("influence", ""),
                    "impulse": p.get("impulse", ""),
                    "cc": p.get("cc", ""),
                    "pop_class": p.get("pop_class", ""),
                    "inf_class": p.get("inf_class", ""),
                    "imp_class": p.get("imp_class", ""),
                    "cc_class": p.get("cc_class", ""),
                })
            st = topic_stats(mapped)
            st_f = stats_as_floats(st)
            row = {"topic": name, "topic_id": tid, "replicate": rep, "n_papers": len(papers)}
            for k in STAT_KEYS:
                row[k] = st.get(k, "")
                if st_f[k] is not None:
                    null_values[(name, k)].append(st_f[k])
            replicate_out.append(row)

    comparison_out = []
    for name, n, tid, _oa_n in topic_meta:
        for stat in STAT_KEYS:
            elx = elixir_stats[name].get(stat)
            summary = summarize_null(null_values[(name, stat)], elx)
            comparison_out.append({
                "topic": name,
                "topic_id": tid,
                "n_papers": n,
                "statistic": stat,
                "elixir_value": fmt_num(elx) if elx is not None else "",
                "null_mean": fmt_num(summary["null_mean"]),
                "null_p2_5": fmt_num(summary["null_p2_5"]),
                "null_p97_5": fmt_num(summary["null_p97_5"]),
                "elixir_percentile": summary["elixir_percentile"],
                "p_two_sided": summary["p_two_sided"],
                "outside_95": fmt_num(summary["outside_95"]),
                "direction": summary["direction"],
            })

    REPLICATES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPLICATES_CSV.open("w", newline="", encoding="utf-8") as fh:
        fields = ["topic", "topic_id", "replicate", "n_papers", *STAT_KEYS]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(replicate_out)

    with COMPARISON_CSV.open("w", newline="", encoding="utf-8") as fh:
        fields = ["topic", "topic_id", "n_papers", "statistic", "elixir_value",
                  "null_mean", "null_p2_5", "null_p97_5", "elixir_percentile",
                  "p_two_sided", "outside_95", "direction"]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(comparison_out)

    print(f"-> {COMPARISON_CSV}", flush=True)
    print(f"-> {REPLICATES_CSV}", flush=True)

    figure_paths: list[Path] = []
    if not args.skip_plots:
        figure_paths = make_figures(comparison_out, replicate_out, FIGURES_DIR)
        for p in figure_paths:
            print(f"-> {p}", flush=True)
    elif FIGURES_DIR.exists():
        figure_paths = sorted(FIGURES_DIR.glob("forest_*.png")) + sorted(
            FIGURES_DIR.glob("null_hist_*.png"))

    write_report(REPORT_MD, topic_meta, comparison_out, figure_paths,
                 replicates=args.replicates if not args.reuse_samples else (
                     json.loads(manifest_path.read_text()).get("replicates", args.replicates)
                     if manifest_path.exists() else args.replicates
                 ),
                 seed=args.seed)
    print(f"-> {REPORT_MD}", flush=True)

    n_out = sum(1 for r in comparison_out if str(r["outside_95"]).lower() == "true")
    print(f"Done: {n_out}/{len(comparison_out)} comparisons outside 95% null band", flush=True)


if __name__ == "__main__":
    main()
