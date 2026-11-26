# Columbia River chum salmon spawner series

The Northwest Fisheries Science Center compiled this Washington Department of Fish and Wildlife series for the Pacific Northwest salmonid viability assessment. This intake covers the complete `data-raw/CRchum2020.csv` in VRData 2.3. The package is dated April 21, 2022. Its license dedicates the package to the public domain under CC0 1.0. [Pinned source table](https://github.com/nwfsc-math-bio/VRData/blob/1511807c895c5adfd1b146a92023a9f93bffde31/data-raw/CRchum2020.csv) · [Field definitions and citations](https://github.com/nwfsc-math-bio/VRData/blob/1511807c895c5adfd1b146a92023a9f93bffde31/man/Salmon-chum-Columbia-River-ESU-CRchum2020.Rd) · [Package license](https://github.com/nwfsc-math-bio/VRData/blob/1511807c895c5adfd1b146a92023a9f93bffde31/LICENSE)

The table contains 132 rows and 19 columns. Each `NMFS_POPID` and `YEAR` pair occurs once. The four series have different periods of coverage in the CSV.

| Source population name | NMFS_POPID | Years in CSV | Rows |
| --- | --- | --- | ---: |
| Grays/Chinook Fall Chum | 115 | 2001–2018 | 18 |
| Washougal Fall Chum | 124 | 2005–2018 | 14 |
| Lower Gorge (Columbia) Fall Chum | 118 | 2000–2018 | 19 |
| Upper Gorge (Columbia) Fall Chum | 123 | 1938–2018 | 81 |

The field manual describes `NUMBER_OF_SPAWNERS` as total spawners or escapement. The row citations name natural-origin spawner abundance. The citations for Grays/Chinook and Washougal also give different start years from their rows. The build keeps the values and citations together so a reviewer can check these differences before comparing abundance or applying `FRACWILD`.

The parser reads all fields as text. It preserves nine explicit zero spawner values, 90 instances of `-99` in `FRACWILD`, 132 instances of `-99` in `CATCH`, and all 132 empty `LINE_NOTES` fields. The manual defines the fraction sentinel and leaves `CATCH` undocumented. Population codes are local to the source. The Spec declares no measurement or cross-source identity.

For replay, stage the four files in `source.files` under their declared names and verify their SHA-256 values. The [Spec](nwfsc-columbia-chum-2020.yaml) uses the executor's built-in CSV parser. Validate the generated `sdp/data/chum_spawners.csv` against the original header, row order and each of the 2,508 cells. The package version and the CSV digest prefix identify this build.
