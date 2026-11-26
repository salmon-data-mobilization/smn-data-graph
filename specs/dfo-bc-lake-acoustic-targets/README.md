# BC lake acoustic surveys and Great Central Lake target records

The output archive contains a survey inventory and detailed acoustic-target records. This package takes the complete inventory and all detailed records whose original lake code is 1 (Great Central Lk). It keeps the publisher’s lake, transect, depth, target, species-proportion and data-issue fields. The detailed table reports fish-like acoustic targets. DFO describes combining trawl biosampling information with acoustic data to interpret sockeye and stickleback abundance. A target count alone does not identify species. The detailed source table holds 123,818 records across lakes, and selection uses no abundance or date threshold. The input archive and other diagnostic outputs are outside this package. [DFO catalogue record](https://open.canada.ca/data/en/dataset/5b5d3312-12e6-4265-b07b-c69dcc17a566)

| Packaged table | Data records | Source fields | Cells with reconstructed padding |
| --- | ---: | ---: | ---: |
| `survey_inventory` | 1,325 | 15 | 1,325 |
| `great_central_lake_targets` | 5,538 | 29 | 11,050 |

The graph describes these resources and their fields. The package keeps the original values as text. Tables keyed by `source_record_number` use the one-based record position after the source header, including the original positions for selections within a larger file. In affected rows, `source_cell_padding` contains a JSON object keyed by original field position. Apply its prefix and suffix to recover the exact source whitespace that the SDK trims at the edges of strings. Legacy CSV text is decoded as Windows-1252 and reserialized in UTF-8.

Contains information licensed under the Open Government Licence – Canada. The [Spec](dfo-bc-lake-acoustic-targets.yaml) pins the URL and SHA-256 of each selected resource. The source version in this package is derived from the ordered file hashes. The catalogue record checked on 2026-11-26 lists 2026-07-24 as its metadata modification date. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada)

Use the [batch intake runner](../source-intake/README.md) to build the package from the original files named in the Spec and compare it with the source. Selected members of the publisher’s output archive are listed below.

- `output/Target_OUTPUT_data_INVENTORY_(1977_2007).csv` · SHA-256 `76be5af586a78e282e8a0bbc67ddd8055f174f284196740e5c1e2b497c5233bf`

- `output/Target_OUTPUT_data_FINAL_(1977_2007).csv` · SHA-256 `242482aed43c7c6776f1019930017b2363a9ecaa6efbbea9d66e15c41ed427df`
