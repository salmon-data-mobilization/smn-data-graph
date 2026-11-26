# Alaska salmon fishery disaster determinations

One table records individual fishery-disaster requests and their outcomes. A second summarizes declarations by SASAP region. The underlying events can affect several regions. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1R78CF3)

| Package table | Records | Original fields | Local record key |
| --- | ---: | ---: | --- |
| determinations | 8 | 11 | ShortName |
| areas | 13 | 3 | SASAP_Region |

The source preserves lists within cells, including multiple request dates and years. The amount column records appropriations in unadjusted US dollars for declared disasters. The separate regional counts must be interpreted within their geographic scope.

The determinations table has 28 source cells with surrounding whitespace. The derived `source_cell_padding` column records the one-based column position and the exact leading and trailing whitespace. The verifier restores these around each packaged value.

## Source and replay

The [specification](sasap-alaska-fishery-disasters.yaml) identifies the published metadata and each selected file by URL, local filename and SHA-256. The DataONE object checksum was checked independently for each file. The EML grants [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). [Source metadata](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1R78CF3)

Stage these files under their declared names and use the [batch replay](../source-intake/README.md). The package comparison checks all 127 source cells in record order. It also checks restored headers, source ordinals where used and exact whitespace.
