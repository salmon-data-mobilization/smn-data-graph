# Northeast Pacific coho brood tables

Two published brood tables give recruits by total age and by freshwater/sea age. The same brood years can occur in both tables. Separate lookup tables identify stocks and contributing sources. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1ZP44BP)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| total_age | 822 | 14 | source_record_number |
| freshwater_sea_age | 70 | 18 | Stock.ID, BroodYear |
| stocks | 13 | 10 | Stock.ID |
| sources | 5 | 4 | Source.ID |

The total-age file contains 27 duplicate rows when all source fields are compared. A one-based source record number keeps their separate positions. The freshwater/sea-age table has a unique stock and brood-year pair for each record. The use flag and literal NA tokens are retained.

The sources table has 1 source cells with surrounding whitespace. The derived `source_cell_padding` column records the one-based column position and the exact leading and trailing whitespace. The verifier restores these around each packaged value.

## Source and replay

The [specification](sasap-ne-pacific-coho-broods.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1ZP44BP)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 12,918 source cells in record order. It also checks restored headers, source ordinals where used and exact whitespace.
