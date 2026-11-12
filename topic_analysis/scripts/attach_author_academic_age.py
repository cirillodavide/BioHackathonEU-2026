"""Attach academic age / R1–R4 stage to gender-enriched ELIXIR BIP! papers.

Joins results/elixir_works_with_{first|last}_author_gender.csv to
data/elixir_authors_academic_age.csv on gender_oa_author_id ↔ openalex_author_id.

Computes academic_age_at_paper = publication_year − first_pub_year and maps to
researcher stages (bibliometric proxies of EU R1–R4):

  R1: 0–4 years
  R2: 5–10
  R3: 11–20
  R4: ≥21

Missing / negative ages → unknown; ages >60 → implausible (OpenAlex first-pub noise).

Writes results/elixir_works_with_{first|last}_author_gender_age.csv with added
columns: author_first_pub_year, author_academic_age_span, academic_age_at_paper,
researcher_stage.

Usage:
  python scripts/attach_author_academic_age.py --role first
  python scripts/attach_author_academic_age.py --role last
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGE = ROOT / "data" / "elixir_authors_academic_age.csv"

csv.field_size_limit(sys.maxsize)

MAX_PLAUSIBLE_AGE = 60


def default_input(role: str) -> Path:
    return ROOT / "results" / f"elixir_works_with_{role}_author_gender.csv"


def default_output(role: str) -> Path:
    return ROOT / "results" / f"elixir_works_with_{role}_author_gender_age.csv"


def to_int(value) -> int | None:
    text = (str(value) if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def stage_for_age(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 0 or age > MAX_PLAUSIBLE_AGE:
        return "implausible"
    if age <= 4:
        return "R1"
    if age <= 10:
        return "R2"
    if age <= 20:
        return "R3"
    return "R4"


def load_age_index(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    index: dict[str, dict] = {}
    for row in rows:
        oa = (row.get("openalex_author_id") or "").strip()
        if oa:
            index[oa] = row
    return index


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--role", choices=("first", "last"), default="first",
        help="Author role already present on the gender-enriched works CSV",
    )
    parser.add_argument("--papers", type=Path, default=None)
    parser.add_argument("--age", type=Path, default=DEFAULT_AGE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    papers_path = args.papers or default_input(args.role)
    out = args.output or default_output(args.role)

    if not papers_path.exists():
        sys.exit(
            f"Not found: {papers_path}: run "
            f"scripts/attach_first_author_gender.py --role {args.role} first"
        )
    if not args.age.exists():
        sys.exit(f"Not found: {args.age}")

    age_index = load_age_index(args.age)
    with papers_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            sys.exit(f"No header in {papers_path}")
        fieldnames = list(reader.fieldnames)
        papers = list(reader)

    if "gender_oa_author_id" not in fieldnames:
        sys.exit(f"Column gender_oa_author_id missing in {papers_path}")

    extra = [
        "author_first_pub_year",
        "author_academic_age_span",
        "academic_age_at_paper",
        "researcher_stage",
    ]
    out_fields = fieldnames + [c for c in extra if c not in fieldnames]

    stage_counts: Counter[str] = Counter()
    matched = 0
    out_rows = []
    for paper in papers:
        oa = (paper.get("gender_oa_author_id") or "").strip()
        hit = age_index.get(oa) if oa else None
        first_pub = to_int(hit.get("first_pub_year")) if hit else None
        span = to_int(hit.get("academic_age")) if hit else None
        pub_year = to_int(paper.get("publication_year"))
        age_at = None
        if first_pub is not None and pub_year is not None:
            age_at = pub_year - first_pub
            matched += 1
        stage = stage_for_age(age_at)
        stage_counts[stage] += 1
        row = dict(paper)
        row["author_first_pub_year"] = "" if first_pub is None else str(first_pub)
        row["author_academic_age_span"] = "" if span is None else str(span)
        row["academic_age_at_paper"] = "" if age_at is None else str(age_at)
        row["researcher_stage"] = stage
        out_rows.append(row)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=out_fields, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"role={args.role}: {len(out_rows)} papers -> {out}")
    print(f"matched age-at-paper: {matched}")
    print("stages:", dict(sorted(stage_counts.items())))


if __name__ == "__main__":
    main()
