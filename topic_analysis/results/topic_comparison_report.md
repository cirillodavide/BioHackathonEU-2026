# Elixir vs OpenAlex topic BIP! comparison

## Process

Starting from `data/elixir_works_metadata_openalex_bip.csv`, we counted how often each OpenAlex **primary topic** appears among ELIXIR papers and ranked topics by that frequency (`results/openalex_topic_counts.csv`). We then kept the **top 5** topics and, for each, summarised BIP! impact on the ELIXIR papers in that topic (medians of impulse and citation count; share of papers in the BIP! top 10% for popularity, influence, impulse, and citations—see `results/openalex_topic_stats.csv`). To ask whether those ELIXIR values are unusual for the topic, we built a reference from the wider OpenAlex graph: for a topic with n ELIXIR papers we drew **100** random OpenAlex samples of size n, matching ELIXIR’s publication-year mix, restricted to the same primary topic, requiring a DOI, excluding ELIXIR DOIs, and scoring each paper with BIP!. The same statistics were recomputed on every sample. Across the 100 draws we report the mean and the central 95% range (2.5th–97.5th percentiles) and place the ELIXIR value in that range (including whether it falls outside). Plots are in [`topic_comparison_figures/`](topic_comparison_figures/). Raw popularity/influence score plots are omitted; we keep the top-10% class shares instead. Seed `42`.

### Topics

| Topic | ELIXIR n | OpenAlex topic id |
|---|---:|---|
| Research Data Management Practices | 154 | `T11937` |
| Genomics and Phylogenetic Studies | 113 | `T10015` |
| Scientific Computing and Data Management | 95 | `T11986` |
| Bioinformatics and Genomic Networks | 73 | `T10887` |
| Protein Structure and Dynamics | 69 | `T10044` |

## Forest plots

One panel per BIP! statistic. Each row is a topic. The grey bar is the central 95% range of that statistic across the 100 year-matched OpenAlex samples; the tick is the mean of those samples; the red point is the ELIXIR value for the topic. Use these to see, at a glance, whether ELIXIR sits inside or outside the OpenAlex reference band for every topic.

- [Median BIP! citation count](topic_comparison_figures/forest_median_cc.png)
- [Median BIP! impulse (3-year citation count)](topic_comparison_figures/forest_median_impulse.png)
- [Share of papers in BIP! citation-count top 10%](topic_comparison_figures/forest_pct_cc_top10.png)
- [Share of papers in BIP! impulse top 10%](topic_comparison_figures/forest_pct_imp_top10.png)
- [Share of papers in BIP! influence top 10%](topic_comparison_figures/forest_pct_inf_top10.png)
- [Share of papers in BIP! popularity top 10%](topic_comparison_figures/forest_pct_pop_top10.png)

## Null histograms

One figure per BIP! statistic, with a small histogram for each topic. Bars show the distribution of the 100 OpenAlex-sample values; the red vertical line is the ELIXIR value. Use these to see the shape of the OpenAlex null and how far ELIXIR lies from that cloud.

- [Median BIP! citation count](topic_comparison_figures/null_hist_median_cc.png)
- [Median BIP! impulse (3-year citation count)](topic_comparison_figures/null_hist_median_impulse.png)
- [Share of papers in BIP! citation-count top 10%](topic_comparison_figures/null_hist_pct_cc_top10.png)
- [Share of papers in BIP! impulse top 10%](topic_comparison_figures/null_hist_pct_imp_top10.png)
- [Share of papers in BIP! influence top 10%](topic_comparison_figures/null_hist_pct_inf_top10.png)
- [Share of papers in BIP! popularity top 10%](topic_comparison_figures/null_hist_pct_pop_top10.png)

## Main findings

**40** topic×statistic pairs fall **outside** the 95% OpenAlex reference band (of 40 comparisons).

| Topic | Statistic | Elixir | OpenAlex mean | 95% band | Direction | p |
|---|---|---:|---:|---|---|---:|
| Research Data Management Practices | `median_popularity` | 9.009341E-9 | 1.736451E-9 | [1.683513E-9, 1.944044E-9] | higher | 0.0 |
| Research Data Management Practices | `median_influence` | 2.907353E-9 | 2.174628E-9 | [2.174628E-9, 2.174628E-9] | higher | 0.0 |
| Research Data Management Practices | `median_impulse` | 9 | 0 | [0, 0] | higher | 0.0 |
| Research Data Management Practices | `median_cc` | 11 | 0 | [0, 0] | higher | 0.0 |
| Research Data Management Practices | `pct_pop_top10` | 76 | 16.015 | [11.7, 21.115] | higher | 0.0 |
| Research Data Management Practices | `pct_inf_top10` | 55.8 | 8.821 | [5.485, 12.3] | higher | 0.0 |
| Research Data Management Practices | `pct_imp_top10` | 63 | 12.564 | [8.4, 16.9] | higher | 0.0 |
| Research Data Management Practices | `pct_cc_top10` | 52.6 | 7.998 | [4.5, 11.7] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `median_popularity` | 1.022127E-8 | 2.005508E-9 | [1.944044E-9, 2.249780E-9] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `median_influence` | 2.600728E-9 | 2.176250E-9 | [2.174628E-9, 2.192877E-9] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `median_impulse` | 10 | 0.05 | [0, 1] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `median_cc` | 16 | 0.11 | [0, 1] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `pct_pop_top10` | 85.8 | 30.847 | [23.9, 37.2] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `pct_inf_top10` | 46.9 | 9.211 | [5.3, 14.62] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `pct_imp_top10` | 69.9 | 23.614 | [17.7, 30.1] | higher | 0.0 |
| Genomics and Phylogenetic Studies | `pct_cc_top10` | 60.2 | 16.651 | [11.5, 23] | higher | 0.0 |
| Scientific Computing and Data Management | `median_popularity` | 6.552419E-9 | 1.940628E-9 | [1.683513E-9, 2.249780E-9] | higher | 0.0 |
| Scientific Computing and Data Management | `median_influence` | 2.530405E-9 | 2.174628E-9 | [2.174628E-9, 2.174628E-9] | higher | 0.0 |
| Scientific Computing and Data Management | `median_impulse` | 5 | 0 | [0, 0] | higher | 0.0 |
| Scientific Computing and Data Management | `median_cc` | 7 | 0 | [0, 0] | higher | 0.0 |
| Scientific Computing and Data Management | `pct_pop_top10` | 62.8 | 20.454 | [13.1225, 28.4] | higher | 0.0 |
| Scientific Computing and Data Management | `pct_inf_top10` | 43.6 | 12.036 | [6.8225, 17.9025] | higher | 0.0 |
| Scientific Computing and Data Management | `pct_imp_top10` | 56.4 | 17.058 | [10.5, 23.2] | higher | 0.0 |
| Scientific Computing and Data Management | `pct_cc_top10` | 46.8 | 10.565 | [4.2, 17.3775] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `median_popularity` | 1.415299E-8 | 2.351098E-9 | [1.767854E-9, 3.354280E-9] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `median_influence` | 2.754036E-9 | 2.220624E-9 | [2.182757E-9, 2.279054E-9] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `median_impulse` | 14 | 1.23 | [0, 3] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `median_cc` | 22 | 1.75 | [1, 4] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `pct_pop_top10` | 89 | 42.562 | [32.9, 52.7825] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `pct_inf_top10` | 53.4 | 15.096 | [8.2, 22.635] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `pct_imp_top10` | 83.6 | 36.409 | [26, 45.935] | higher | 0.0 |
| Bioinformatics and Genomic Networks | `pct_cc_top10` | 71.2 | 26.886 | [17.8, 35.6] | higher | 0.0 |
| Protein Structure and Dynamics | `median_popularity` | 1.436090E-8 | 2.784054E-9 | [1.952398E-9, 4.365342E-9] | higher | 0.0 |
| Protein Structure and Dynamics | `median_influence` | 2.808135E-9 | 2.226782E-9 | [2.174628E-9, 2.307318E-9] | higher | 0.0 |
| Protein Structure and Dynamics | `median_impulse` | 15 | 1.65 | [0, 4] | higher | 0.0 |
| Protein Structure and Dynamics | `median_cc` | 26 | 2.23 | [0, 5] | higher | 0.0 |
| Protein Structure and Dynamics | `pct_pop_top10` | 88.4 | 45.912 | [33.3, 59.4] | higher | 0.0 |
| Protein Structure and Dynamics | `pct_inf_top10` | 56.5 | 12.883 | [5.8, 21.035] | higher | 0.0 |
| Protein Structure and Dynamics | `pct_imp_top10` | 78.3 | 39.095 | [27.5, 52.2] | higher | 0.0 |
| Protein Structure and Dynamics | `pct_cc_top10` | 71 | 27.451 | [17.4, 39.1] | higher | 0.0 |

_Generated 2026-11-11 16:49 UTC_
