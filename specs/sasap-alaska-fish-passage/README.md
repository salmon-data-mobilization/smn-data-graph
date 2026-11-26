# Regional fish passage in Alaska

The published regional table counts assessed culverts by passage classification. It gives one row for each of 13 SASAP regions. The classification describes how suitable a crossing is likely to be for fish passage. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1QZ287T)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| passage | 13 | 7 | region_id |

The EML defines black as unknown, green as likely adequate, gray as possibly inadequate and red as likely inadequate. The regional counts use assessed crossings as the unit of analysis. The DOI resource map identifies RegFishPass_2010-2017.csv as urn:uuid:4e78b33e-0b24-4d9d-9e30-8cc0c26e4eb9.

## Source and replay

The [specification](sasap-alaska-fish-passage.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1QZ287T)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 91 source cells in record order.
