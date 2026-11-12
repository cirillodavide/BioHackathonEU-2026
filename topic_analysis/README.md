# ELIXIR vs OpenAlex topic BIP! comparison

Compare BIP! impact indicators for ELIXIR publications against year-matched
random samples from the same OpenAlex primary topics.

Run the commands below from this folder (`topic_analysis/`).

## Process

1. **Start from ELIXIR + OpenAlex + BIP!**  
   Use `data/elixir_works_metadata_openalex_bip.csv` (OpenAlex primary `topic`,
   publication year, and BIP! popularity / influence / impulse / citation count
   and their classes).

2. **Count topics and summarise ELIXIR impact**  
   ```bash
   python scripts/count_topics.py
   ```
   Writes:
   - `results/openalex_topic_counts.csv` — primary topics ranked by frequency
   - `results/openalex_topic_stats.csv` — per-topic medians and share of papers
     in the BIP! top 10% (classes C1–C4)

3. **Keep the top 5 topics** (by ELIXIR paper count):

   | Topic | ELIXIR n | OpenAlex topic id |
   |---|---:|---|
   | Research Data Management Practices | 154 | `T11937` |
   | Genomics and Phylogenetic Studies | 113 | `T10015` |
   | Scientific Computing and Data Management | 95 | `T11986` |
   | Bioinformatics and Genomic Networks | 73 | `T10887` |
   | Protein Structure and Dynamics | 69 | `T10044` |

4. **Build an OpenAlex reference for each topic**  
   For a topic with *n* ELIXIR papers, draw **100** random OpenAlex samples of
   size *n* that:
   - share the same primary topic
   - match ELIXIR’s publication-year mix (year-stratified)
   - require a DOI
   - exclude ELIXIR DOIs
   - have BIP! coverage (DOIs without scores are redrawn from the year pool when possible)

   Candidate pools are built with the OpenAlex `sample` API, then locally
   resampled for each replicate. Sample membership is saved under
   `results/topic_comparison_samples/` (see `manifest.json`). Seed `42`.

5. **Score samples and place ELIXIR in the null**  
   ```bash
   python scripts/compare_topic_bip_openalex.py --top 5 --replicates 100 --seed 42
   ```
   Recomputes the same statistics as step 2 on every sample. Across the 100
   draws, reports the OpenAlex mean, the central 95% range (2.5th–97.5th
   percentiles), and whether the ELIXIR value falls outside that band.

   To recompute stats/plots from saved samples without re-querying APIs:
   ```bash
   python scripts/compare_topic_bip_openalex.py --reuse-samples
   ```

## Outputs

| Path | What |
|---|---|
| `results/openalex_topic_comparison.csv` | ELIXIR vs OpenAlex summary per topic × statistic |
| `results/openalex_topic_comparison_replicates.csv` | Per-replicate sample statistics |
| `results/topic_comparison_figures/` | Forest plots (95% band + ELIXIR point) and null histograms |
| `results/topic_comparison_report.md` | Written-up findings |
| `results/cache/bip_scores.jsonl` | Cached BIP! API scores used during sampling |

**Forest plots:** grey bar = OpenAlex 95% range, tick = OpenAlex-sample mean,
coloured point = ELIXIR.  
**Histograms:** cloud of the 100 OpenAlex-sample values per topic, red line at
ELIXIR. Raw popularity/influence score plots are omitted; top-10% class shares
are kept instead.

## First-author gender (within ELIXIR)

Compare paper **counts** and BIP! indicators by inferred first-author gender
within each top topic. Uses
`data/elixir_unique_authors_dedup_countries_gender.tsv` (does not gender
OpenAlex random samples).

```bash
python scripts/attach_first_author_gender.py
python scripts/compare_topic_gender_bip.py --top 5
```

| Path | What |
|---|---|
| `results/elixir_works_with_first_author_gender.csv` | BIP papers + first-author gender join |
| `results/openalex_topic_gender_counts.csv` | Per-topic male / female / unknown counts and shares |
| `results/openalex_topic_gender_stats.csv` | Per-topic × gender BIP! stats |
| `results/topic_gender_figures/` | Count/share bars and female/male BIP! indicator bars |
| `results/topic_gender_report.md` | Coverage, figures, and stats table |

Unknown = unmatched consortia, missing authors, or `not retrievable` names.
BIP! indicator bars use female vs male only (bar length = statistic).
