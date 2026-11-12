"""Attach inferred first-author gender to ELIXIR BIP! papers.

Joins data/elixir_works_metadata_openalex_bip.csv to
data/elixir_unique_authors_dedup_countries_gender.tsv using the first author
in the semicolon-separated `authors` column.

Match order:
  1. exact full_name
  2. normalized full_name
  3. normalized full_name with middle initials stripped
  4. exact first_name|last_name
  5. normalized first_name|last_name

Writes results/elixir_works_with_first_author_gender.csv with the original
columns plus first_author, first_author_gender, gender_match_method,
gender_llm_confidence, gender_oa_author_id.

Usage:
  python scripts/attach_first_author_gender.py
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPERS = ROOT / "data" / "elixir_works_metadata_openalex_bip.csv"
DEFAULT_GENDER = ROOT / "data" / "elixir_unique_authors_dedup_countries_gender.tsv"
DEFAULT_OUT = ROOT / "results" / "elixir_works_with_first_author_gender.csv"

csv.field_size_limit(sys.maxsize)


def norm(text: str) -> str:
    s = (text or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("‐", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_middle_initials(full: str) -> str:
    parts = full.split()
    if len(parts) <= 2:
        return full
    keep = [parts[0]]
    for mid in parts[1:-1]:
        if not re.fullmatch(r"[A-Za-z]\.?", mid):
            keep.append(mid)
    keep.append(parts[-1])
    return " ".join(keep)


def first_author(authors: str) -> str:
    text = (authors or "").strip()
    if not text:
        return ""
    return text.split(";")[0].strip()


def first_last(name: str) -> tuple[str, str]:
    parts = name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def load_gender_index(path: Path) -> dict[str, dict[str, list[dict]]]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))

    by_full: dict[str, list[dict]] = defaultdict(list)
    by_full_n: dict[str, list[dict]] = defaultdict(list)
    by_fl: dict[str, list[dict]] = defaultdict(list)
    by_fl_n: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        full = (row.get("full_name") or "").strip()
        fn = (row.get("first_name") or row.get("firstname") or "").strip()
        ln = (row.get("last_name") or row.get("lastname") or "").strip()
        if full:
            by_full[full].append(row)
            by_full_n[norm(full)].append(row)
            by_full_n[norm(strip_middle_initials(full))].append(row)
        if fn and ln:
            by_fl[f"{fn}|{ln}"].append(row)
            by_fl_n[f"{norm(fn)}|{norm(ln)}"].append(row)

    return {
        "full": by_full,
        "full_n": by_full_n,
        "fl": by_fl,
        "fl_n": by_fl_n,
    }


def pick(rows: list[dict]) -> dict:
    """Prefer higher llm_confidence when several roster rows share a key."""
    def conf(r: dict) -> float:
        try:
            return float(r.get("llm_confidence") or 0)
        except ValueError:
            return 0.0
    return max(rows, key=conf)


def match_author(name: str, index: dict[str, dict[str, list[dict]]]) -> tuple[dict | None, str]:
    if not name:
        return None, "no_author"
    fn, ln = first_last(name)
    if name in index["full"]:
        return pick(index["full"][name]), "exact_full"
    key = norm(name)
    if key in index["full_n"]:
        return pick(index["full_n"][key]), "norm_full"
    key2 = norm(strip_middle_initials(name))
    if key2 in index["full_n"]:
        return pick(index["full_n"][key2]), "norm_full_strip_middle"
    fl = f"{fn}|{ln}"
    if fl in index["fl"]:
        return pick(index["fl"][fl]), "exact_fl"
    fln = f"{norm(fn)}|{norm(ln)}"
    if fln in index["fl_n"]:
        return pick(index["fl_n"][fln]), "norm_fl"
    return None, "unmatched"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--papers", type=Path, default=DEFAULT_PAPERS)
    parser.add_argument("--gender", type=Path, default=DEFAULT_GENDER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.papers.exists():
        sys.exit(f"Not found: {args.papers}")
    if not args.gender.exists():
        sys.exit(f"Not found: {args.gender}")

    index = load_gender_index(args.gender)
    with args.papers.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            sys.exit(f"No header in {args.papers}")
        fieldnames = list(reader.fieldnames)
        papers = list(reader)

    extra = [
        "first_author",
        "first_author_gender",
        "gender_match_method",
        "gender_llm_confidence",
        "gender_oa_author_id",
    ]
    out_fields = fieldnames + [c for c in extra if c not in fieldnames]

    method_counts: dict[str, int] = defaultdict(int)
    gender_counts: dict[str, int] = defaultdict(int)
    out_rows = []
    for paper in papers:
        author = first_author(paper.get("authors") or "")
        hit, method = match_author(author, index)
        if hit is None:
            gender = "unmatched" if author else "no_author"
        else:
            gender = (hit.get("gender") or "").strip() or "missing"
        method_counts[method] += 1
        gender_counts[gender] += 1
        row = dict(paper)
        row["first_author"] = author
        row["first_author_gender"] = gender
        row["gender_match_method"] = method
        row["gender_llm_confidence"] = (hit.get("llm_confidence") if hit else "") or ""
        row["gender_oa_author_id"] = (hit.get("oa_author_id") if hit else "") or ""
        out_rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"{len(out_rows)} papers -> {args.output}")
    print("match methods:", dict(sorted(method_counts.items(), key=lambda x: -x[1])))
    print("genders:", dict(sorted(gender_counts.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
