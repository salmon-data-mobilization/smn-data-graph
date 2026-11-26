# Koyukuk River chum salmon mortality field samples

The complete 2019 field table records date, location, live/dead status, sex fields, length and age. The 861 published rows include 68 dead fish from the Koyukuk mainstem and 793 live fish across the other two locations. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1BG2MB2)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| mortality | 861 | 7 | source_record_number |

The paper describes a larger count of carcasses on the surveyed reach. This table records sampled fish, so its dead-fish rows alone cannot estimate total mortality. A source record number preserves repeated records. The source header `Sex ` ends in a space and is represented as `Sex` in the package.

## Source and replay

The [specification](koyukuk-chum-en-route-mortality.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1BG2MB2)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 6,027 source cells in record order. It also checks restored headers, source ordinals where used and exact whitespace.
