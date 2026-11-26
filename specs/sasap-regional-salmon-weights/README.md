# Regional weights of commercially harvested salmon

Tobias Schwoerer used commercial landings to derive weight estimates in pounds by year, SASAP region and species. The weight table includes the median and two quantiles. Two lookup tables describe the geographic groupings. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1NC5ZGW)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| weights | 2072 | 6 | Species, SASAP.Region, YEAR |
| district_regions | 97 | 2 | District |
| harvest_regions | 22 | 2 | ADFG_Area |

The estimates apply to commercially harvested fish. The author identifies confidentiality of commercial records as a coverage limitation, particularly for regions with a single processor.

## Source and replay

The [specification](sasap-regional-salmon-weights.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1NC5ZGW)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 12,670 source cells in record order.
