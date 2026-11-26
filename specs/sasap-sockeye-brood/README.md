# SASAP sockeye brood tables

Rich Brenner, Greg Ruggerone, Brendan Connors, Jeanette Clark and Stephanie Freund compiled brood tables for sockeye salmon across Alaska, British Columbia and Washington. The publisher’s title gives 1922–2016. The CSV also contains ten records for brood year 2017, each with `UseFlag=0` and `TotalRecruits=NA`. The intake retains all years and both values of the source flag. [KNB dataset record](https://knb.ecoinformatics.org/view/doi:10.5063/CR5RR9)

| Source table | Rows | Columns | Local record key |
| --- | ---: | ---: | --- |
| BroodTables.csv | 2,985 | 34 | Stock.ID, BroodYear, UseFlag |
| StockInfo.csv | 120 | 13 | Stock.ID |
| SourceInfo.csv | 12 | 2 | Source.ID |

The brood table contains 51 source stock identifiers across 12 regions. For Gates sockeye, the file has two records for each brood year from 1981 through 2008, distinguished by the use flag. The three-column key preserves both records. The EML abstract defines European age notation. For example, the source defines `R0.1` as recruits with zero freshwater winters and one sea winter. Its attribute list documents each of the 21 age-class fields individually. The EML also explains that some escapement estimates are indices and warns against direct comparisons of productivity across stocks. The specification keeps all fields as source strings. The graph describes the dataset, its fields and provenance. The package holds the source rows. Stock identity links and observation-level interpretations need separate evidence.

## Source and replay

The selected KNB metadata object is DOI `10.5063/CR5RR9`. DataONE identifies it as the successor to `10.5063/F1891459`; the EML still carries the predecessor in its internal `packageId`. The EML calls the brood table `BroodTables.csv` and gives its physical object name as `raw_brood_table_2019_07_16.csv`. The specification uses the EML entity name and pins the bytes returned by the entity’s DataONE identifier. [Selected system metadata](https://cn.dataone.org/cn/v2/meta/doi:10.5063/CR5RR9) · [EML](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/CR5RR9)

The EML states “no restrictions” and supplies no licence identifier. Spec v1 requires a licence IRI to confirm redistribution, so the specification records a null licence and unconfirmed redistribution. The source citation retains the rights text. [DataCite record](https://api.datacite.org/dois/10.5063/cr5rr9)

For a replay, stage the five URLs under the names in [the specification](sasap-sockeye-brood.yaml) and use the executor’s built-in CSV parser. Each file has a SHA-256 pin. On 26 November 2026 the EML matched the size and checksum in DataONE system metadata. All three CSVs and the supporting R Markdown document matched their EML sizes and SHA-1 checksums. The processing document describes how the authors built the published compilation. Replay reads the published CSVs directly.
