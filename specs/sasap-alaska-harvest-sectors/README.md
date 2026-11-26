# Alaska salmon harvest across four fishery sectors

Jeanette Clark and the Alaska Department of Fish and Game compiled salmon harvest across commercial, subsistence, personal-use and sport fisheries. The published CSV has 6,022 records across 13 SASAP regions and five species. The title and catalogue coverage give 1995–2016. The CSV starts in 1969 and includes 1,926 records from before 1995. The package retains the full CSV. [KNB dataset](https://knb.ecoinformatics.org/view/doi:10.5063/F1HM56Q3)

| Source sector | First year | Last year | Regions represented | Records |
| --- | ---: | ---: | ---: | ---: |
| Commercial | 1975 | 2016 | 12 | 2,288 |
| Subsistence | 1975 | 2016 | 13 | 1,875 |
| Personal Use | 1969 | 2016 | 5 | 670 |
| Sport Fish | 1996 | 2016 | 13 | 1,189 |

A record contains the harvest for one year, SASAP region, species and sector. These four fields uniquely identify each published row. The source describes harvest in numbers of fish. It includes fractional estimates in some subsistence and personal-use records. The package keeps the original strings, including all 661 explicit zero harvests and 9,756 literal `NA` tokens in the two commercial-source fields. [Dataset metadata and field definitions](https://cn.dataone.org/cn/v2/resolve/doi:10.5063/F1HM56Q3)

The authors give management reports priority over direct Commercial Fisheries Entry Commission (CFEC) data when both are available. For direct CFEC data, `p_conf` records the proportion of fisheries meeting the code’s confidentiality criterion. It measures the share of fisheries affected, so the proportion of harvest withheld remains unknown. Ten commercial rows report both zero harvest and `p_conf=1`. The authors also describe region assignments based on permit-holder residence for a subsistence fishery that spans Norton Sound and Kotzebue. [Published processing document](https://cn.dataone.org/cn/v2/resolve/urn:uuid:374bdd99-f438-4f06-8f28-cc567b0247ad)

## Replay

The [Spec](sasap-alaska-harvest-sectors.yaml) lists the original CSV, its EML metadata and the authors’ R Markdown processing document. Stage these three files under their declared names for the batch intake. Its built-in CSV parser reads the published table. The processing document provides source evidence. The SHA-256 pins cover all three files. Each download also matched the repository or EML size and SHA-1 checksum. DataONE identifies the selected DOI as the successor to `10.5063/F1TT4P73`. The selected EML grants Creative Commons Attribution 4.0 International. [DataONE revision record](https://cn.dataone.org/cn/v2/meta/doi:10.5063/F1HM56Q3) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

The local graph describes the dataset, table, fields and sources. The Salmon Data Package contains all seven source columns in their original order. Replay compares the generated `sdp/data/harvest.csv` header and all 42,154 source cells to the original CSV.
