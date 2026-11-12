"""Count OpenAlex primary topics and summarise BIP! indicators per topic.

Reads elixir_works_metadata_openalex_bip.csv and writes:
  results/openalex_topic_counts.csv   topic, count (desc)
  results/openalex_topic_stats.csv    per-topic BIP! stats (desc by n_papers)

Per-topic stats (papers with that primary `topic`):
  n_papers
  median popularity / influence / impulse / cc
  pct_pop_top10 / pct_inf_top10 / pct_imp_top10 / pct_cc_top10
      share of papers in BIP! classes C1–C4 (top 10%)

Usage:
  python scripts/count_topics.py
  python scripts/count_topics.py --input data/elixir_works_metadata_openalex_bip.csv
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "elixir_works_metadata_openalex_bip.csv"
DEFAULT_COUNTS = ROOT / "results" / "openalex_topic_counts.csv"
DEFAULT_STATS = ROOT / "results" / "openalex_topic_stats.csv"

csv.field_size_limit(sys.maxsize)

TOP10_CLASSES = {"C1", "C2", "C3", "C4"}
SCORE_COLS = ("popularity", "influence", "impulse", "cc")
CLASS_COLS = {
    "pop_class": "pct_pop_top10",
    "inf_class": "pct_inf_top10",
    "imp_class": "pct_imp_top10",
    "cc_class": "pct_cc_top10",
}
STATS_HEADER = [
    "topic",
    "n_papers",
    "median_popularity",
    "median_influence",
    "median_impulse",
    "median_cc",
    "pct_pop_top10",
    "pct_inf_top10",
    "pct_imp_top10",
    "pct_cc_top10",
]


def to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_number(value: float, kind: str) -> str:
    if kind in {"popularity", "influence"}:
        return f"{value:.6E}".replace("E+", "E").replace("E-0", "E-")
    if kind in {"impulse", "cc"}:
        return f"{value:.1f}" if not float(value).is_integer() else str(int(value))
    return str(value)


def median_of(values: list[float], kind: str):
    if not values:
        return ""
    return format_number(statistics.median(values), kind)


def pct_top10(classes: list[str]):
    if not classes:
        return ""
    n = sum(1 for c in classes if c in TOP10_CLASSES)
    return round(100.0 * n / len(classes), 1)


def load_rows(input_path: Path) -> list[dict]:
    with input_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "topic" not in reader.fieldnames:
            sys.exit(f"Column 'topic' not found in {input_path}")
        return list(reader)


def group_by_topic(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        topic = (row.get("topic") or "").strip()
        if topic:
            groups[topic].append(row)
    return groups


def topic_stats(papers: list[dict]) -> dict:
    scores = {col: [v for r in papers if (v := to_float(r.get(col))) is not None]
              for col in SCORE_COLS}
    classes = {col: [(r.get(col) or "").strip() for r in papers if (r.get(col) or "").strip()]
               for col in CLASS_COLS}
    return {
        "n_papers": len(papers),
        "median_popularity": median_of(scores["popularity"], "popularity"),
        "median_influence": median_of(scores["influence"], "influence"),
        "median_impulse": median_of(scores["impulse"], "impulse"),
        "median_cc": median_of(scores["cc"], "cc"),
        "pct_pop_top10": pct_top10(classes["pop_class"]),
        "pct_inf_top10": pct_top10(classes["inf_class"]),
        "pct_imp_top10": pct_top10(classes["imp_class"]),
        "pct_cc_top10": pct_top10(classes["cc_class"]),
    }


def write_counts(groups: dict[str, list[dict]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["topic", "count"])
        for topic, papers in ordered:
            writer.writerow([topic, len(papers)])


def write_stats(groups: dict[str, list[dict]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STATS_HEADER, lineterminator="\n")
        writer.writeheader()
        for topic, papers in ordered:
            row = {"topic": topic, **topic_stats(papers)}
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count topics and summarise BIP! indicators per topic.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input BIP CSV")
    parser.add_argument("--counts", type=Path, default=DEFAULT_COUNTS, help="Output counts CSV")
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS, help="Output stats CSV")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Not found: {args.input}")

    rows = load_rows(args.input)
    groups = group_by_topic(rows)
    write_counts(groups, args.counts)
    write_stats(groups, args.stats)

    n_with_topic = sum(len(v) for v in groups.values())
    print(f"{args.input.name}: {n_with_topic} papers with a topic, "
          f"{len(groups)} distinct topics")
    print(f"-> {args.counts}")
    print(f"-> {args.stats}")


if __name__ == "__main__":
    main()
