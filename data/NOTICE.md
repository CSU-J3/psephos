# Notice: LegiScan data in this directory

State legislation data from the [LegiScan API](https://legiscan.com/legiscan) by LegiScan LLC, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Filtered to election-related bills and reformatted by psephos.

## Which files

- **`state_bills.json`** is derived from LegiScan. It holds the state bills that pass psephos's election filter (`collectors/state.py::election_match`), each with its actions as a timeline. The records were fetched with `getMasterList` and `getBill`, then filtered, trimmed to the fields psephos renders, and reshaped into per-bill timelines.

  Each action also carries psephos's own Admiralty grade and other annotations, which are not LegiScan's.

No other file in this directory contains LegiScan data. The other snapshots come from Congress.gov, the Federal Register, CourtListener and news feeds, under those sources' own terms.

Two LegiScan-derived working files are gitignored and have never been committed: `masterlist_corpus.json` and `sasts_corpus.json`, the offline corpora the `tools/` scripts build. If either is ever committed, it needs this notice and an accurate statement of what was changed. Neither is filtered to election bills: `masterlist_corpus.json` holds every bill in the polled states' masterlists, cut down to four fields.

## Why this file exists

LegiScan's API data is licensed under CC BY 4.0, and from 2026-11-01 LegiScan audits API keys against those terms. The license needs three things wherever the data is redistributed: credit to the creator, a link to the license, and a statement that the data was changed. This repository is public and the cron commits `state_bills.json` to it four times a day, so the notice travels with the file.
