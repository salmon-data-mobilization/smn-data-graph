# DFO Pacific salmon unit lookup

Fisheries and Oceans Canada identifies this Open Government Portal attachment as the crosswalk used by Salmon Space. It records Stock Management Unit (SMU), Conservation Unit (CU) and Designatable Unit (DU) names and indexes for Canadian Pacific salmon. The intake covers the complete bilingual lookup CSV, a single resource within the larger *Pacific Salmon Conservation Units, Sites & Status* collection. [DFO Salmon Space](https://www.pac.dfo-mpo.gc.ca/science/smon-space-espace/index-eng.html) · [DFO lookup attachment record](https://open.canada.ca/data/en/dataset/1ac00a39-4770-443d-8a6b-9656c06df6a3/resource/ce7ba1d7-ca4f-4510-9958-3fb7618cd6c5)

The source contains 484 rows and 13 fields. The full CU index is present and unique in every row of this snapshot. The rows cover sockeye (266), Chinook (91), coho (48), chum (46) and pink salmon (33). The CU type field includes current, bin, deprecated, extirpated and verification labels. Each retains its original spelling and punctuation. The package preserves the four accented or typographic characters in the bilingual headings by reading the original as Latin-1 and writing UTF-8. Those four source bytes decode identically in Windows-1252.

## Lookup limits

The SMU index is blank in 84 rows, and the DU index is blank in 182. These cells provide no value. Treating them as explicit statements that a unit is unassigned would add information. Eight DU index cells contain semicolon-separated values. Readers can retrieve the complete source string from the packaged table. The graph describes the field and the source attachment. Biological identity, stock equivalence, membership edges and validity periods would require a separate interpretation.

## Source, rights and replay

The source checked on 2026-11-26 was `SMU_CU_DU_Lookup_Table_7172025.csv` in portal record `1ac00a39-4770-443d-8a6b-9656c06df6a3`. The parent record gives 2026-10-23 as its data modification date and 2026-10-26 as its metadata modification date. The attachment has no separate modification date or named release version in that record. The package version uses the first 12 hex characters of the original file’s SHA-256. The Spec pins the entire digest and publisher URL. Other distributions or versions of the crosswalk need their own source checks. [Parent catalogue record](https://open.canada.ca/data/api/3/action/package_show?id=1ac00a39-4770-443d-8a6b-9656c06df6a3)

Contains information licensed under the Open Government Licence – Canada. The DFO portal record assigns this licence to the selected resource’s dataset. [Licence and attribution](https://open.canada.ca/en/open-government-licence-canada/)

For the batch replay, stage the file declared in [the Spec](dfo-smu-cu-du-lookup.yaml) under its original filename. Place the [source parser](../dfo_smu_cu_du_lookup_parser.py) under the executor’s `specs/` directory. After the build, the following check compares all 6,292 cells, headers and row order with the publisher file and checks the lookup codes, blank index fields and multi-value cells.

```sh
python specs/dfo-smu-cu-du-lookup/verify_source.py --raw-dir "$LOOKUP_RAW_DIR" --build-dir "$LOOKUP_BUILD_DIR"
```
