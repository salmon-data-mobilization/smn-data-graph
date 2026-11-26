# Atlantic salmon reported in British Columbia waters

The English Atlantic Salmon Watch Program file comprises 117 reports. DFO verified 79 reports as Atlantic salmon and recorded 38 as unconfirmed by a “No” flag. The source distinguishes these categories. Pairs of reports can share a date and location. The file ends with 25 empty export records, which are checked separately and omitted from the report count. DFO records voluntary observations and fishery reports. Reporting effort and confirmation can vary over time. Counts of reports cannot establish population size. [DFO catalogue record](https://open.canada.ca/data/en/dataset/f0299fb3-73b9-4977-b96a-c83bd84ebdc4)

| Packaged table | Data records | Source fields | Cells with reconstructed padding |
| --- | ---: | ---: | ---: |
| `reports` | 117 | 7 | 11 |

The graph describes these resources and their fields. The package keeps the original values as text. Tables keyed by `source_record_number` use the one-based record position after the source header, including the original positions for selections within a larger file. In affected rows, `source_cell_padding` contains a JSON object keyed by original field position. Apply its prefix and suffix to recover the exact source whitespace that the SDK trims at the edges of strings.

Contains information licensed under the Open Government Licence – Canada. The [Spec](dfo-atlantic-salmon-watch-bc.yaml) pins the URL and SHA-256 of each selected resource. The source version in this package is derived from the ordered file hashes. The catalogue record checked on 2026-11-26 lists 2026-07-07 as its metadata modification date. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada)

Use the [batch intake runner](../source-intake/README.md) to build the package from the original files named in the Spec and compare it with the source.
