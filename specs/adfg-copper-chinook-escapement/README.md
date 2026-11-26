# Copper River Chinook escapement

The standardized CSV gives annual spawning escapement estimates for 1999–2016. The detailed calculation CSV covers 1975–2016 and includes harvest, in-river abundance, uncertainty and total escapement. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F14F1P0T)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| escapement | 18 | 5 | sampleYear |
| calculation | 42 | 30 | Year |

The package includes both published CSV tables. The archive also contains the source workbook. Years present in the detailed file can have missing escapement estimates.

## Source and replay

The [specification](adfg-copper-chinook-escapement.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F14F1P0T)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 1,350 source cells in record order.
