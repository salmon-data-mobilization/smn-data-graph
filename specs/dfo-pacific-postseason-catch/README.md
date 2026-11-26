# Pacific commercial salmon post-season catch estimates by gear

The three English catch tables cover gillnet, seine and troll fisheries from 1996 to 2004. DFO identifies catch in numbers of fish and effort in boat-days. Each file begins with a publisher title record above its field names. The parser checks this title layout and packages the rows below the header. The notes identify 14 records with catch suppressed for privacy. Their empty catch fields remain distinct from reported zeros. Source values retain thousands separators. The file-level keys combine calendar year, licence area and management area. [DFO catalogue record](https://open.canada.ca/data/en/dataset/82c7eaa7-7078-4d38-a880-25d53f00c579)

| Packaged table | Data records | Source fields | Cells with reconstructed padding |
| --- | ---: | ---: | ---: |
| `gillnet` | 149 | 12 | 0 |
| `seine` | 114 | 12 | 0 |
| `troll` | 188 | 12 | 0 |

The graph describes these resources and their fields. The package keeps the original values as text.

Contains information licensed under the Open Government Licence – Canada. The [Spec](dfo-pacific-postseason-catch.yaml) pins the URL and SHA-256 of each selected resource. The source version in this package is derived from the ordered file hashes. The catalogue record checked on 2026-11-26 lists 2026-03-24 as its metadata modification date. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada)

Use the [batch intake runner](../source-intake/README.md) to build the package from the original files named in the Spec and compare it with the source.
