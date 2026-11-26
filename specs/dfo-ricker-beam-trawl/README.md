# Ricker beam trawl juvenile salmon set logs

The English set-log table records the 1990–1993 surface beam trawl study off western Vancouver Island. Its 131 fields include tow identifiers, gear, start and end times, surface conditions and catch categories by species. Set ID alone repeats in this file. The complete English set logs are included. The separate archive of individual fish examinations, French file and map services are outside this intake. The original data dictionary documents the many abbreviated catch columns. [DFO catalogue record](https://open.canada.ca/data/en/dataset/b16db0fe-a4ec-4844-819e-630e33137b6d)

| Packaged table | Data records | Source fields | Cells with reconstructed padding |
| --- | ---: | ---: | ---: |
| `set_logs` | 2,032 | 131 | 505 |

The graph describes these resources and their fields. The package keeps the original values as text. Tables keyed by `source_record_number` use the one-based record position after the source header, including the original positions for selections within a larger file. In affected rows, `source_cell_padding` contains a JSON object keyed by original field position. Apply its prefix and suffix to recover the exact source whitespace that the SDK trims at the edges of strings. Legacy CSV text is decoded as Windows-1252 and reserialized in UTF-8.

Contains information licensed under the Open Government Licence – Canada. The [Spec](dfo-ricker-beam-trawl.yaml) pins the URL and SHA-256 of each selected resource. The source version in this package is derived from the ordered file hashes. The catalogue record checked on 2026-11-26 lists 2026-03-24 as its metadata modification date. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada)

Use the [batch intake runner](../source-intake/README.md) to build the package from the original files named in the Spec and compare it with the source.
