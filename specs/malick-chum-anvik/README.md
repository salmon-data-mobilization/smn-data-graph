# Malick Anvik phase 1: native source discovery

This is a current-format, lexical source-discovery build for native `stock.id=349` in **pink-chum-database v1.1**, [Zenodo 6478751](https://zenodo.org/records/6478751), published 2022-04-22. It preserves all 22 native data rows and 16 fields, the one information row (10 fields), and linked source rows 16/18 (two fields). The source README defines `stock.id` as its file-linking key. No cross-dataset biological identity is assigned.

The source entry pins the **original complete ZIP** and its actual publisher download URL. `specs.malick_anvik_parser:parse` reads named original CSV members in memory, checks their hashes, and selects only the native stock and its source links. The generated table files are explicitly derived subsets, never represented as the original public CSV download. The parser lives at the ordinary, legal project-root module path `specs/malick_anvik_parser.py`; no parser resolver, ROOT, symlink or guard workaround is used.

All fields are unmarked string attributes. Values, row order, `age`, `use`, and blank cells remain native. There is no filtering on year, age, use or value and no imputation. The 44 blank `recruits.2`/`recruits.7` cells remain blank. The information-row `comment` is also blank, for 45 blank cells among 366 native cells. Source provider/publication names remain source text, not claims of independent lineage.

**This is not a completed measured intake.** It admits zero observations, no identity declarations, no code/ontology mappings, no formal age notation, and no human or agent acceptance. README source descriptions support brood-year counts of salmon and total spawners/recruits, but native `age` is an assumption flag (`data`/`avg`/`age4`). The source does not identify a formal fresh/salt/total-age convention. The current Spec name screen requires an `age_notation` when this native field leaves the whole lexical boundary. Its schema accepts an IRI; a generic `AgeNotation` would technically appease that screen without establishing a truthful convention. It is deliberately absent. Later numerical intake needs a reviewed source-supported interpretation and a deliberate contract decision, without renaming or dropping native fields.

The deposit metadata identifies `cc-zero`, and the original ZIP contains CC0 1.0 Universal. The Spec therefore truthfully uses the CC0 URI and `redistribution: confirmed`. This grant applies to this deposited source, not other datasets or scientific correctness. `source.public` reflects redistribution evidence; the executor's `publication_ready` remains false. The build stays in local ignored cache pending the owner's fidelity/privacy and transfer decision. No private AK/DFO/NOAA or Agent OS material is an input. No person was contacted, no terms were accepted, and nothing was uploaded.

The Spec version `v1.1` identifies the frozen publisher source. The explicit executor `build_date` is the derived execution date, not the source publication, observation or retrieval date. `source-evidence.json` records the original archive/member/license pins. The saved Spec, parser bytes, vocabularies, runtime and all output hashes are recorded by the genuine executor.

Use an already installed environment synchronized to this checkout's `uv.lock`; the replayer never installs or fetches. From the repository root:

```sh
<locked-python> -B specs/malick-chum-anvik/reproduce.py \
  --raw-dir <directory-containing-original-ZIP> \
  --vocab-dir <existing-offline-smn-gcdfo-psc-Turtle-directory> \
  --out-dir .cache/malick-anvik-intake/lexical-build-1 \
  --build-date 2026-10-24 \
  --receipt .cache/malick-anvik-intake/lexical-build-1-receipt.json
```

The replayer uses the public executor and the **unchanged current-format** `combine.load_dataset_build`, verifies all 366 source/derived CSV cells and all nonblank SDK strings, preserves blanks, reloads idempotently, and checks original archive/Spec/parser hashes. It counts ten outer Python DNS/socket hooks before SDK imports, with a final zero-attempt assertion. This is an in-process check, not a network sandbox. A fresh receipt path preserves earlier evidence. Existing build outputs are replaced only through the executor's existing verified-output contract.
