"""Within-topic first-author gender counts and BIP! comparison for ELIXIR papers.

Reads results/elixir_works_with_first_author_gender.csv (from
attach_first_author_gender.py) and the top topics from
results/openalex_topic_counts.csv.

Writes:
  results/openalex_topic_gender_counts.csv
  results/openalex_topic_gender_stats.csv
  results/topic_gender_figures/counts_by_topic.png
  results/topic_gender_figures/share_by_topic.png
  results/topic_gender_figures/bars_<statistic>.png
  results/topic_gender_report.md

Usage:
  python scripts/compare_topic_gender_bip.py
  python scripts/compare_topic_gender_bip.py --top 5
"""
from __future__ import annotations

import argparse
import csv
import sys
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from count_topics import (  # noqa: E402
    STATS_HEADER,
    load_rows,
    topic_stats,
    to_float,
)

DEFAULT_INPUT = ROOT / "results" / "elixir_works_with_first_author_gender.csv"
DEFAULT_COUNTS = ROOT / "results" / "openalex_topic_counts.csv"
COUNTS_OUT = ROOT / "results" / "openalex_topic_gender_counts.csv"
STATS_OUT = ROOT / "results" / "openalex_topic_gender_stats.csv"
FIGURES_DIR = ROOT / "results" / "topic_gender_figures"
REPORT_MD = ROOT / "results" / "topic_gender_report.md"

STAT_KEYS = [k for k in STATS_HEADER if k not in {"topic", "n_papers"}]
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

GENDER_PLOT = ("female", "male")
GENDER_COLORS = {"female": "#c0392b", "male": "#1f6feb", "unknown": "#9aa5b1"}


def wrap_topic(name: str, width: int = 28) -> str:
    return "\n".join(textwrap.wrap(name, width=width)) or name


def normalize_gender(value: str) -> str:
    g = (value or "").strip().lower()
    if g in {"female", "male"}:
        return g
    return "unknown"


def read_top_topics(counts_path: Path, top: int) -> list[tuple[str, int]]:
    rows = []
    with counts_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append((row["topic"], int(row["count"])))
    return rows[:top]


def fmt_num(x) -> str:
    if x == "" or x is None:
        return ""
    if isinstance(x, float):
        if abs(x) != 0 and (abs(x) < 1e-3 or abs(x) >= 1e4):
            return f"{x:.6E}".replace("E+", "E").replace("E-0", "E-")
        return f"{x:.6g}"
    return str(x)


def make_count_figures(count_rows: list[dict], topics: list[str], out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    by_topic = {r["topic"]: r for r in count_rows}
    y = np.arange(len(topics))
    height = 0.25
    genders = ["female", "male", "unknown"]

    # Absolute counts
    fig, ax = plt.subplots(figsize=(10, 0.7 * len(topics) + 2.2))
    for i, g in enumerate(genders):
        vals = [int(by_topic[t][f"n_{g}"]) for t in topics]
        offset = (i - 1) * height
        bars = ax.barh(y + offset, vals, height=height, color=GENDER_COLORS[g], label=g.capitalize())
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                        str(val), va="center", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels([wrap_topic(t) for t in topics], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Number of ELIXIR papers")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, fontsize=8, frameon=True)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    fig.tight_layout()
    path = out_dir / "counts_by_topic.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    # Percentage share
    fig, ax = plt.subplots(figsize=(10, 0.7 * len(topics) + 2.2))
    left = np.zeros(len(topics))
    for g in genders:
        vals = np.array([float(by_topic[t][f"pct_{g}"]) for t in topics])
        ax.barh(y, vals, left=left, color=GENDER_COLORS[g], label=g.capitalize(), height=0.6)
        for i, (v, l) in enumerate(zip(vals, left)):
            if v >= 8:
                ax.text(l + v / 2, i, f"{v:.0f}%", ha="center", va="center", fontsize=8, color="white")
        left = left + vals
    ax.set_yticks(y)
    ax.set_yticklabels([wrap_topic(t) for t in topics], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of ELIXIR papers (%)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, fontsize=8, frameon=True)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    fig.tight_layout()
    path = out_dir / "share_by_topic.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)
    return paths


def format_stat_annotation(stat: str, value: float, n: int) -> str:
    """Value on the axis scale, plus paper count in parentheses (not on the axis)."""
    if stat.startswith("pct_"):
        val_s = f"{value:.0f}%" if float(value).is_integer() else f"{value:.1f}%"
    elif stat.startswith("median_") and stat in {"median_impulse", "median_cc"}:
        val_s = f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"
    else:
        val_s = f"{value:.3g}"
    return f"{val_s} (n={n})"


def make_indicator_bar_figures(stat_rows: list[dict], topics: list[str], out_dir: Path) -> list[Path]:
    """Grouped bars: x = BIP! statistic; annotation = value + paper count n."""
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    # Drop old dumbbell forests if present
    for old in out_dir.glob("forest_*.png"):
        old.unlink()

    paths: list[Path] = []
    by_key = {(r["topic"], r["gender"]): r for r in stat_rows}
    height = 0.32

    for stat in PLOT_STAT_KEYS:
        label = STAT_LABELS.get(stat, stat)
        fig, ax = plt.subplots(figsize=(11, 0.85 * len(topics) + 2.4))
        y = np.arange(len(topics))
        for i, g in enumerate(GENDER_PLOT):
            vals = []
            ns = []
            for topic in topics:
                row = by_key.get((topic, g))
                v = to_float(row.get(stat)) if row else None
                n = int(row["n_papers"]) if row else 0
                vals.append(0.0 if v is None else v)
                ns.append(n)
            offset = (i - 0.5) * height
            bars = ax.barh(
                y + offset, vals, height=height,
                color=GENDER_COLORS[g], label=f"{g.capitalize()} first author",
            )
            for bar, v, n in zip(bars, vals, ns):
                if n <= 0:
                    continue
                ax.text(
                    bar.get_width() + max(vals) * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    format_stat_annotation(stat, v, n),
                    va="center", fontsize=7, color=GENDER_COLORS[g],
                )
        ax.set_yticks(y)
        ax.set_yticklabels([wrap_topic(t) for t in topics], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel(label)
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, fontsize=8, frameon=True)
        # room for "value (n=…)" annotations to the right of bars
        data_max = max(
            (to_float(by_key[(t, g)].get(stat)) or 0.0)
            for t in topics for g in GENDER_PLOT
            if (t, g) in by_key
        )
        if stat.startswith("pct_"):
            ax.set_xlim(0, max(100, data_max) * 1.28)
        else:
            ax.set_xlim(0, (data_max * 1.28) if data_max > 0 else 1)
        fig.tight_layout()
        path = out_dir / f"bars_{stat}.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def write_report(
    path: Path,
    topics: list[tuple[str, int]],
    count_rows: list[dict],
    stat_rows: list[dict],
    figure_paths: list[Path],
    coverage: dict,
) -> None:
    lines = [
        "# ELIXIR topic BIP! by first-author gender",
        "",
        "## Process",
        "",
        "First-author gender was attached from "
        "`data/elixir_unique_authors_dedup_countries_gender.tsv` to "
        "`data/elixir_works_metadata_openalex_bip.csv` "
        "(`scripts/attach_first_author_gender.py`). Within each of the top "
        f"{len(topics)} OpenAlex primary topics, we count papers by inferred "
        "first-author gender and recompute the same BIP! statistics as "
        "`count_topics.py` for female and male subsets.",
        "",
        "### Join coverage (all papers)",
        "",
        f"- Papers: **{coverage['n_papers']}**",
        f"- Male / female / unknown: "
        f"**{coverage['n_male']}** / **{coverage['n_female']}** / **{coverage['n_unknown']}**",
        f"- Match methods: `{coverage['methods']}`",
        "",
        "### Topics",
        "",
        "| Topic | ELIXIR n | Female | Male | Unknown |",
        "|---|---:|---:|---:|---:|",
    ]
    by_topic = {r["topic"]: r for r in count_rows}
    for name, n in topics:
        r = by_topic[name]
        lines.append(
            f"| {name} | {n} | {r['n_female']} | {r['n_male']} | {r['n_unknown']} |"
        )

    count_figs = [p for p in figure_paths if p.name.startswith(("counts_", "share_"))]
    bar_figs = [p for p in figure_paths if p.name.startswith("bars_")]

    lines += [
        "",
        "## Count and composition figures",
        "",
        "Paper counts and percentage shares by first-author gender within each "
        "topic (unknown includes unmatched consortia and non-retrievable names).",
        "",
    ]
    for p in count_figs:
        label = "Paper counts by first-author gender" if p.name.startswith("counts_") \
            else "Share of papers by first-author gender"
        lines += [
            f"### {label}",
            "",
            f"![{label}](topic_gender_figures/{p.name})",
            "",
        ]

    lines += [
        "## BIP! indicator figures",
        "",
        "Grouped bars compare female vs male first-author subsets within each "
        "topic. The **bar length / x-axis** is the BIP! statistic. The label "
        "next to each bar shows that same value plus **n = number of papers** "
        "in that gender×topic subset (sample size used to compute the "
        "statistic — not an x-axis quantity). Unknown-gender papers are "
        "excluded from these plots.",
        "",
    ]
    for p in bar_figs:
        key = p.stem.removeprefix("bars_")
        label = STAT_LABELS.get(key, key)
        lines += [
            f"### {label}",
            "",
            f"![{label}](topic_gender_figures/{p.name})",
            "",
        ]

    lines += [
        "## Per-topic gender BIP! stats",
        "",
        "| Topic | Gender | n | median impulse | median cc | "
        "pct pop top10 | pct inf top10 | pct imp top10 | pct cc top10 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, _ in topics:
        for g in GENDER_PLOT:
            row = next((r for r in stat_rows if r["topic"] == name and r["gender"] == g), None)
            if not row:
                continue
            lines.append(
                f"| {name} | {g} | {row['n_papers']} | {row['median_impulse']} | "
                f"{row['median_cc']} | {row['pct_pop_top10']} | {row['pct_inf_top10']} | "
                f"{row['pct_imp_top10']} | {row['pct_cc_top10']} |"
            )
    lines += [
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--counts", type=Path, default=DEFAULT_COUNTS)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Not found: {args.input}: run scripts/attach_first_author_gender.py first")
    if not args.counts.exists():
        sys.exit(f"Not found: {args.counts}: run scripts/count_topics.py first")

    papers = load_rows(args.input)
    if "first_author_gender" not in (papers[0] if papers else {}):
        sys.exit(f"Column first_author_gender missing in {args.input}")

    top_topics = read_top_topics(args.counts, args.top)
    topic_names = [t for t, _ in top_topics]
    print("Top topics:")
    for name, n in top_topics:
        print(f"  {name}: {n}")

    # Coverage over all papers
    all_gender = Counter(normalize_gender(p.get("first_author_gender") or "") for p in papers)
    methods = Counter((p.get("gender_match_method") or "") for p in papers)
    coverage = {
        "n_papers": len(papers),
        "n_female": all_gender["female"],
        "n_male": all_gender["male"],
        "n_unknown": all_gender["unknown"],
        "methods": dict(methods),
    }

    # Counts per top topic
    count_rows = []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in papers:
        topic = (p.get("topic") or "").strip()
        if topic not in topic_names:
            continue
        g = normalize_gender(p.get("first_author_gender") or "")
        groups[(topic, g)].append(p)

    for topic, n_all in top_topics:
        n_f = len(groups[(topic, "female")])
        n_m = len(groups[(topic, "male")])
        n_u = len(groups[(topic, "unknown")])
        total = n_f + n_m + n_u
        count_rows.append({
            "topic": topic,
            "n_papers": total,
            "n_female": n_f,
            "n_male": n_m,
            "n_unknown": n_u,
            "pct_female": round(100.0 * n_f / total, 1) if total else 0.0,
            "pct_male": round(100.0 * n_m / total, 1) if total else 0.0,
            "pct_unknown": round(100.0 * n_u / total, 1) if total else 0.0,
        })

    COUNTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    with COUNTS_OUT.open("w", newline="", encoding="utf-8") as fh:
        fields = ["topic", "n_papers", "n_female", "n_male", "n_unknown",
                  "pct_female", "pct_male", "pct_unknown"]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(count_rows)
    print(f"-> {COUNTS_OUT}")

    # BIP stats for female/male only
    stat_rows = []
    for topic, _ in top_topics:
        for g in GENDER_PLOT:
            subset = groups[(topic, g)]
            st = topic_stats(subset)
            row = {"topic": topic, "gender": g, **{k: st[k] for k in STATS_HEADER if k != "topic"}}
            # ensure stringy values for CSV
            for k, v in list(row.items()):
                if k not in {"topic", "gender"}:
                    row[k] = v if isinstance(v, str) else ("" if v is None else str(v))
            # n_papers already int-like from topic_stats
            row["n_papers"] = st["n_papers"]
            for k in STAT_KEYS:
                row[k] = st[k]
            stat_rows.append(row)

    with STATS_OUT.open("w", newline="", encoding="utf-8") as fh:
        fields = ["topic", "gender", "n_papers", *STAT_KEYS]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(stat_rows)
    print(f"-> {STATS_OUT}")

    figure_paths: list[Path] = []
    if not args.skip_plots:
        figure_paths.extend(make_count_figures(count_rows, topic_names, FIGURES_DIR))
        figure_paths.extend(make_indicator_bar_figures(stat_rows, topic_names, FIGURES_DIR))
        for p in figure_paths:
            print(f"-> {p}")
    elif FIGURES_DIR.exists():
        figure_paths = (
            sorted(FIGURES_DIR.glob("counts_*.png"))
            + sorted(FIGURES_DIR.glob("share_*.png"))
            + sorted(FIGURES_DIR.glob("bars_*.png"))
        )

    write_report(REPORT_MD, top_topics, count_rows, stat_rows, figure_paths, coverage)
    print(f"-> {REPORT_MD}")
    print("Done.")


if __name__ == "__main__":
    main()
