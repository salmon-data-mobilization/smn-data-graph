# Salish Sea juvenile salmon and pelagic trawl surveys

The three selected v2026a resources describe survey trips, fishing events and catch. DFO records event depths, effort and gear alongside catch counts, volumes, weights and verification descriptions. These surveys follow juvenile Pacific salmon alongside other pelagic species. The detailed individual biological measurements file is outside this intake. Trip, event and catch identifiers remain local to the publisher files. Catch units and verification fields remain attached to the values, and blanks stay distinct from zeros. [DFO catalogue record](https://open.canada.ca/data/en/dataset/711c33d3-32eb-4729-9a39-681fe6f6bca2)

| Packaged table | Data records | Source fields | Cells with reconstructed padding |
| --- | ---: | ---: | ---: |
| `trips` | 43 | 7 | 1 |
| `events` | 803 | 13 | 0 |
| `catches` | 3,142 | 10 | 0 |

The graph describes these resources and their fields. The package keeps the original values as text. In affected rows, `source_cell_padding` contains a JSON object keyed by original field position. Apply its prefix and suffix to recover the exact source whitespace that the SDK trims at the edges of strings.

Contains information licensed under the Open Government Licence – Canada. The [Spec](dfo-salish-sea-juvenile-trawl.yaml) pins the URL and SHA-256 of each selected resource. The source version in this package is derived from the ordered file hashes. The catalogue record checked on 2026-11-26 lists 2026-08-28 as its metadata modification date. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada)

Use the [batch intake runner](../source-intake/README.md) to build the package from the original files named in the Spec and compare it with the source.
