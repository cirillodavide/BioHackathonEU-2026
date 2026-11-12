"""Corpus-wide academic age (R1–R4) × gender counts and BIP! comparison.

Reads results/elixir_works_with_{first|last}_author_gender_age.csv (from
attach_author_academic_age.py --role …). Aggregates across all ELIXIR papers
(not per topic).

Writes (role=first keeps short paths; role=last uses last_author_*):
  results/openalex[_last_author]_age_gender_counts.csv
  results/openalex[_last_author]_age_gender_stats.csv
  results/figures/[first_|last_]author_age_gender_figures/…  (first uses age_gender_figures)
  results/reports/[first_|last_]author_age_gender_report.md

Usage:
  python scripts/compare_topic_age_gender_bip.py --role first
  python scripts/compare_topic_age_gender_bip.py --role last
"""
from __future__ import annotations

import argparse
import csv
import sys
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

STAGES = ("R1", "R2", "R3", "R4")
GENDER_PLOT = ("female", "male")
GENDER_COLORS = {"female": "#c0392b", "male": "#1f6feb"}
STAGE_COLORS = {
    "R1": "#7f8c8d",
    "R2": "#27ae60",
    "R3": "#f39c12",
    "R4": "#8e44ad",
}
STAGE_LABELS = {
    "R1": "First Stage Researcher",
    "R2": "Recognised Researcher",
    "R3": "Established Researcher",
    "R4": "Leading Researcher",
}


def role_paths(role: str) -> dict[str, Path]:
    if role == "first":
        return {
            "input": ROOT / "results" / "elixir_works_with_first_author_gender_age.csv",
            "counts": ROOT / "results" / "openalex_age_gender_counts.csv",
            "stats": ROOT / "results" / "openalex_age_gender_stats.csv",
            "figures": ROOT / "results" / "figures" / "age_gender_figures",
            "report": ROOT / "results" / "reports" / "first_author_age_gender_report.md",
            "figures_rel": "../figures/age_gender_figures",
        }
    return {
        "input": ROOT / "results" / "elixir_works_with_last_author_gender_age.csv",
        "counts": ROOT / "results" / "openalex_last_author_age_gender_counts.csv",
        "stats": ROOT / "results" / "openalex_last_author_age_gender_stats.csv",
        "figures": ROOT / "results" / "figures" / "last_author_age_gender_figures",
        "report": ROOT / "results" / "reports" / "last_author_age_gender_report.md",
        "figures_rel": "../figures/last_author_age_gender_figures",
    }


def role_phrase(role: str) -> str:
    return "first-author" if role == "first" else "last-author"


def normalize_gender(value: str) -> str:
    g = (value or "").strip().lower()
    if g in {"female", "male"}:
        return g
    return "unknown"


def format_stat_annotation(stat: str, value: float) -> str:
    if stat.startswith("pct_"):
        return f"{value:.0f}%" if float(value).is_integer() else f"{value:.1f}%"
    if stat.startswith("median_") and stat in {"median_impulse", "median_cc"}:
        return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"
    return f"{value:.3g}"


def make_count_figures(
    count_lookup: dict[tuple[str, str], int],
    out_dir: Path,
) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    y = np.arange(len(STAGES))
    height = 0.35

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for gi, g in enumerate(GENDER_PLOT):
        vals = [count_lookup.get((stage, g), 0) for stage in STAGES]
        offset = (gi - 0.5) * height
        bars = ax.barh(
            y + offset, vals, height=height,
            color=GENDER_COLORS[g], label=g.capitalize(),
        )
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(
                    bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", fontsize=8, color=GENDER_COLORS[g],
                )
    ax.set_yticks(y)
    ax.set_yticklabels([STAGE_LABELS[s] for s in STAGES], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Number of ELIXIR papers")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, fontsize=8, frameon=True)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    fig.tight_layout()
    path = out_dir / "counts_by_stage.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, g in zip(axes, GENDER_PLOT):
        total = sum(count_lookup.get((s, g), 0) for s in STAGES)
        left = 0.0
        for stage in STAGES:
            n = count_lookup.get((stage, g), 0)
            pct = 100.0 * n / total if total else 0.0
            ax.barh(0, pct, left=left, color=STAGE_COLORS[stage],
                    label=STAGE_LABELS[stage], height=0.5)
            if pct >= 8:
                ax.text(left + pct / 2, 0, f"{pct:.0f}%", ha="center", va="center",
                        fontsize=8, color="white")
            left += pct
        ax.set_xlim(0, 100)
        ax.set_yticks([])
        ax.set_xlabel(f"Share within {g} (%)")
        ax.set_title(g.capitalize(), fontsize=10)
        ax.grid(axis="x", linestyle=":", alpha=0.5)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 1.0),
               ncol=4, fontsize=8, frameon=True)
    fig.tight_layout()
    path = out_dir / "share_by_gender.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)
    return paths


def make_indicator_bar_figures(
    stat_rows: list[dict],
    out_dir: Path,
    role: str,
) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("bars_*.png"):
        old.unlink()

    paths: list[Path] = []
    by_key = {(r["stage"], r["gender"]): r for r in stat_rows}
    height = 0.32
    author_word = "first author" if role == "first" else "last author"
    y = np.arange(len(STAGES))

    for stat in PLOT_STAT_KEYS:
        label = STAT_LABELS.get(stat, stat)
        fig, ax = plt.subplots(figsize=(9, 4.8))
        data_vals: list[float] = []
        for gi, g in enumerate(GENDER_PLOT):
            vals = []
            for stage in STAGES:
                row = by_key.get((stage, g))
                v = to_float(row.get(stat)) if row and int(row["n_papers"]) > 0 else None
                vals.append(0.0 if v is None else v)
                if v is not None:
                    data_vals.append(v)
            offset = (gi - 0.5) * height
            bars = ax.barh(
                y + offset, vals, height=height,
                color=GENDER_COLORS[g],
                label=f"{g.capitalize()} {author_word}",
            )
            for j, (bar, v) in enumerate(zip(bars, vals)):
                row = by_key.get((STAGES[j], g))
                if not row or int(row["n_papers"]) <= 0:
                    continue
                ax.text(
                    bar.get_width() + max((data_vals or [1])) * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    format_stat_annotation(stat, v),
                    va="center", fontsize=8, color=GENDER_COLORS[g],
                )
        ax.set_yticks(y)
        ax.set_yticklabels([STAGE_LABELS[s] for s in STAGES], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlabel(label)
        ax.grid(axis="x", linestyle=":", alpha=0.5)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, fontsize=8, frameon=True)
        data_max = max(data_vals) if data_vals else 0.0
        if stat.startswith("pct_"):
            ax.set_xlim(0, max(100, data_max) * 1.18)
        else:
            ax.set_xlim(0, (data_max * 1.18) if data_max > 0 else 1)
        fig.tight_layout()
        path = out_dir / f"bars_{stat}.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def write_report(
    path: Path,
    count_rows: list[dict],
    stat_rows: list[dict],
    figure_paths: list[Path],
    coverage: dict,
    role: str,
    figures_rel: str,
) -> None:
    phrase = role_phrase(role)
    lines = [
        f"# ELIXIR BIP! by {phrase} academic age and gender",
        "",
        "## Process",
        "",
        f"{phrase.capitalize()} gender (from "
        "`data/elixir_unique_authors_dedup_countries_gender.tsv`) was joined to "
        f"academic age from `data/elixir_authors_academic_age.csv` "
        f"(`scripts/attach_author_academic_age.py --role {role}`). "
        "Academic age at paper = publication year − OpenAlex first publication year. "
        "Stages: **R1** 0–4y, **R2** 5–10y, **R3** 11–20y, **R4** ≥21y "
        "(ages missing/negative → unknown; >60 → implausible). "
        f"Across the full ELIXIR corpus we count papers by {phrase} stage × gender "
        "and recompute BIP! statistics for female and male subsets within each R stage "
        "(not stratified by topic).",
        "",
        "### Join coverage (all papers)",
        "",
        f"- Papers: **{coverage['n_papers']}**",
        f"- Male / female / unknown gender: "
        f"**{coverage['n_male']}** / **{coverage['n_female']}** / **{coverage['n_unknown']}**",
        f"- Researcher stages: `{coverage['stages']}`",
        f"- Age-at-paper matched: **{coverage['n_age_matched']}**",
        "",
        "### Counts by stage × gender",
        "",
        "| Stage | Female | Male | Total |",
        "|---|---:|---:|---:|",
    ]
    by_sg = {(r["stage"], r["gender"]): int(r["n_papers"]) for r in count_rows}
    for stage in STAGES:
        nf = by_sg.get((stage, "female"), 0)
        nm = by_sg.get((stage, "male"), 0)
        lines.append(f"| {STAGE_LABELS[stage]} | {nf} | {nm} | {nf + nm} |")

    count_figs = [p for p in figure_paths if p.name.startswith(("counts_", "share_"))]
    bar_figs = [p for p in figure_paths if p.name.startswith("bars_")]

    lines += [
        "",
        "## Count and composition figures",
        "",
        f"Paper counts by {phrase} R stage with female vs male side-by-side, "
        "and within-gender percentage shares of R1–R4. "
        "Unknown / implausible ages and unknown gender are excluded from these plots.",
        "",
    ]
    for p in count_figs:
        label = (
            f"Paper counts by {phrase} stage × gender"
            if p.name.startswith("counts_")
            else f"Share of R stages within each {phrase} gender"
        )
        lines += [
            f"### {label}",
            "",
            f"![{label}]({figures_rel}/{p.name})",
            "",
        ]

    lines += [
        "## BIP! indicator figures",
        "",
        f"Grouped bars compare female vs male {phrase} subsets within each R stage. "
        "The **bar length / x-axis** is the BIP! statistic. "
        "Unknown gender and unknown/implausible ages are excluded.",
        "",
    ]
    for p in bar_figs:
        key = p.stem.removeprefix("bars_")
        label = STAT_LABELS.get(key, key)
        lines += [
            f"### {label}",
            "",
            f"![{label}]({figures_rel}/{p.name})",
            "",
        ]

    lines += [
        "## Stage × gender BIP! stats",
        "",
        "| Stage | Gender | n | median impulse | median cc | "
        "pct pop top10 | pct inf top10 | pct imp top10 | pct cc top10 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stage in STAGES:
        for g in GENDER_PLOT:
            row = next(
                (r for r in stat_rows if r["stage"] == stage and r["gender"] == g),
                None,
            )
            if not row or int(row["n_papers"]) <= 0:
                continue
            lines.append(
                f"| {stage} | {g} | {row['n_papers']} | "
                f"{row['median_impulse']} | {row['median_cc']} | "
                f"{row['pct_pop_top10']} | {row['pct_inf_top10']} | "
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
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--role", choices=("first", "last"), default="first")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()

    paths = role_paths(args.role)
    input_path = args.input or paths["input"]
    gender_col = f"{args.role}_author_gender"

    if not input_path.exists():
        sys.exit(
            f"Not found: {input_path}: run "
            f"scripts/attach_author_academic_age.py --role {args.role} first"
        )

    papers = load_rows(input_path)
    if not papers:
        sys.exit(f"No rows in {input_path}")
    for col in (gender_col, "researcher_stage"):
        if col not in papers[0]:
            sys.exit(f"Column {col} missing in {input_path}")

    print(f"role={args.role}: {len(papers)} papers (full corpus)")

    all_gender = Counter(normalize_gender(p.get(gender_col) or "") for p in papers)
    all_stages = Counter((p.get("researcher_stage") or "").strip() for p in papers)
    n_age_matched = sum(
        1 for p in papers if (p.get("academic_age_at_paper") or "").strip() != ""
    )
    coverage = {
        "n_papers": len(papers),
        "n_female": all_gender["female"],
        "n_male": all_gender["male"],
        "n_unknown": all_gender["unknown"],
        "stages": dict(sorted(all_stages.items())),
        "n_age_matched": n_age_matched,
    }

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    count_lookup: dict[tuple[str, str], int] = defaultdict(int)
    for p in papers:
        g = normalize_gender(p.get(gender_col) or "")
        stage = (p.get("researcher_stage") or "").strip()
        if stage not in STAGES or g not in GENDER_PLOT:
            continue
        groups[(stage, g)].append(p)
        count_lookup[(stage, g)] += 1

    count_rows = []
    for stage in STAGES:
        for g in GENDER_PLOT:
            n = count_lookup.get((stage, g), 0)
            count_rows.append({"stage": stage, "gender": g, "n_papers": n})

    paths["counts"].parent.mkdir(parents=True, exist_ok=True)
    with paths["counts"].open("w", newline="", encoding="utf-8") as fh:
        fields = ["stage", "gender", "n_papers"]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(count_rows)
    print(f"-> {paths['counts']}")

    # topic_stats only needs BIP columns on the paper rows; topic unused.
    stat_rows = []
    for stage in STAGES:
        for g in GENDER_PLOT:
            subset = groups.get((stage, g), [])
            st = topic_stats(subset)
            row = {"stage": stage, "gender": g, "n_papers": st["n_papers"]}
            for k in STAT_KEYS:
                row[k] = st[k]
            stat_rows.append(row)

    with paths["stats"].open("w", newline="", encoding="utf-8") as fh:
        fields = ["stage", "gender", "n_papers", *STAT_KEYS]
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(stat_rows)
    print(f"-> {paths['stats']}")

    figure_paths: list[Path] = []
    if not args.skip_plots:
        figure_paths.extend(make_count_figures(dict(count_lookup), paths["figures"]))
        figure_paths.extend(
            make_indicator_bar_figures(stat_rows, paths["figures"], args.role)
        )
        for p in figure_paths:
            print(f"-> {p}")
    elif paths["figures"].exists():
        figure_paths = (
            sorted(paths["figures"].glob("counts_*.png"))
            + sorted(paths["figures"].glob("share_*.png"))
            + sorted(paths["figures"].glob("bars_*.png"))
        )

    write_report(
        paths["report"], count_rows, stat_rows, figure_paths, coverage,
        role=args.role, figures_rel=paths["figures_rel"],
    )
    print(f"-> {paths['report']}")
    print("Done.")


if __name__ == "__main__":
    main()
