# saeima.sessions

Data getter and vote analysis for Saeima session XML files.

## Data source

The portal runs CKAN, so we use its JSON API (`package_show`) instead of scraping HTML. A single API call returns all ~2,600 resources (XML files) with their metadata and download URLs.

Three document types are available per session sitting:

| Type   | Content                        |
|--------|--------------------------------|
| `dkp`  | Agenda / proceedings           |
| `vote` | Roll-call votes (per-MP)       |
| `deb`  | Debate transcripts             |

Data covers Saeimas 12, 13, and 14 (years 2016--2026).

## Usage

All commands are run via:

```bash
python -m saeima.sessions <command> [options]
```

## Commands

### `sync` -- Download XML files

Fetches the resource registry from the CKAN API, saves it as a local CSV, then downloads any XML files not yet present in `data/sessions/xml/`.

```bash
# Download everything (within default year range)
python -m saeima.sessions sync

# Download only 14th Saeima vote files from 2024 onwards
python -m saeima.sessions sync --saeima 14 --doc-type vote --year-from 2024

# Preview what would be downloaded without actually downloading
python -m saeima.sessions sync --dry-run

# Download all document types for a single year
python -m saeima.sessions sync --year-from 2023 --year-to 2023
```

**Parameters:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--year-from` | int | 2022 | Start year, inclusive |
| `--year-to` | int | 2026 | End year, inclusive |
| `--saeima` | int | all | Saeima number (12, 13, or 14) |
| `--doc-type` | choice | all | `dkp`, `vote`, or `deb` |
| `--dry-run` | flag | off | List files that would be downloaded, without downloading |

**Behaviour:**

1. Calls the CKAN API to get the full resource list.
2. Parses each resource name into structured fields (saeima number, year, session, session number, document type).
3. Writes/overwrites `data/sessions/registry.csv` with the full parsed registry.
4. Filters the registry by the provided flags.
5. Compares against files already in `data/sessions/xml/`.
6. Downloads missing files. Progress is logged every 50 files.
7. Resources with unparseable names (~14, mostly typos in the source data) are logged as warnings but still included.

### `status` -- Show download progress

Shows how many files are in the registry vs how many have been downloaded, broken down by document type.

```bash
python -m saeima.sessions status
```

Example output:

```
Registry:   2649 resources
Downloaded: 1740
Missing:    909

By document type:
  deb       580 /  883
  dkp       580 /  882
  vote      580 /  884
```

No parameters.

### `build-votes` -- Build the votes spreadsheet

Parses all `*-vote.xml` files for a given Saeima into a single flat CSV where each row is one MP's participation in one vote.

```bash
# Build the full spreadsheet for the 14th Saeima
python -m saeima.sessions build-votes

# Only process 2024 data
python -m saeima.sessions build-votes --year-from 2024 --year-to 2024

# Write to a custom path
python -m saeima.sessions build-votes --output my_analysis.csv

# Process the 13th Saeima instead
python -m saeima.sessions build-votes --saeima 13
```

**Parameters:**

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--saeima` | int | 14 | Saeima number |
| `--year-from` | int | 2022 | Start year, inclusive |
| `--year-to` | int | 2026 | End year, inclusive |
| `--output` | path | `data/sessions/votes.csv` | Output CSV file path |

**Behaviour:**

1. Finds all `{saeima}.saeimas-*-vote.xml` files in `data/sessions/xml/`.
2. Filters by year range.
3. For each file, parses all `<VOTES>` blocks and sorts them by `VOTE_NUMBER` (XML element order is unreliable).
4. Skips candidate election votes (`VOTEISCANDIDATE=1`) and empty files.
5. For each regular vote, expands the `#`-delimited parallel arrays (`NAME`, `SURNAME`, `FRACTION`, `RESULT`) into one row per MP.
6. Determines `was_present` for each MP by cross-referencing with the nearest "Deputatu klatbutnes registracija" presence check (prefers the latest preceding one; falls back to the first following one).
7. Adds extra rows for MPs who were registered as present but don't appear in the vote's MP list (present but didn't participate). These rows have an empty `result`.
8. Writes all rows to the output CSV. Progress is logged every 50 files.

**Output columns:**

| Column | Description |
|--------|-------------|
| `source_file` | XML filename this row came from |
| `vote_number` | Vote number within the session sitting |
| `vote_timestamp` | Date and time of the vote |
| `vote_motive` | The proposition / subject being voted on |
| `dkp_id` | Agenda item ID (links to DKP files) |
| `voting_id` | Unique vote identifier |
| `vote_result_for` | Total "Par" (for) votes |
| `vote_result_against` | Total "Pret" (against) votes |
| `vote_result_abstain` | Total "Atturas" (abstain) votes |
| `vote_result_registered` | Total registered/present for this vote |
| `name` | MP first name |
| `surname` | MP surname |
| `fraction` | Parliamentary faction (e.g. JV, NA, ZZS) |
| `result` | `Par`, `Pret`, `Atturas`, `Nebalsoja`, or empty |
| `was_present` | `True` / `False` / empty (based on nearest presence registration) |

**Result values:**

| Value | Meaning |
|-------|---------|
| `Par` | Voted for |
| `Pret` | Voted against |
| `Atturas` | Abstained |
| `Nebalsoja` | In the vote list but did not vote |
| *(empty)* | Not in the vote list; row added because MP was registered as present |

### Global options

| Flag | Description |
|------|-------------|
| `-v` / `--verbose` | Enable debug-level logging |
