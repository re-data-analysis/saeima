# saeima

Tools for downloading and analysing Latvian Saeima parliamentary session data from the [Latvian Open Data portal](https://data.gov.lv/dati/lv/dataset/saeimas-sedes).

## Setup

Requires Python 3.10+. Install with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Modules

| Module | Description |
|--------|-------------|
| `saeima.sessions` | Data getter and vote analysis -- see [sessions/README.md](saeima/sessions/README.md) |

## Project structure

```
saeima/sessions/
  config.py       Constants (URLs, paths, defaults)
  getter.py       CKAN API client, registry, download logic, sync/status CLI
  analysis.py     Vote XML parser, presence logic, build-votes CLI
  __main__.py     CLI entry point (wires both command groups together)

data/sessions/
  registry.csv    Parsed resource registry (written by sync)
  xml/            Downloaded XML files
  votes.csv       Flat vote spreadsheet (written by build-votes)
```

## Configuration

Defaults are in `saeima/sessions/config.py`:

```python
CKAN_API_URL = "https://data.gov.lv/dati/api/3/action/package_show"
DATASET_ID = "saeimas-sedes"
XML_DIR = Path("data/sessions/xml")
REGISTRY_PATH = Path("data/sessions/registry.csv")
VOTES_CSV_PATH = Path("data/sessions/votes.csv")
DEFAULT_YEAR_FROM = 2022
DEFAULT_YEAR_TO = 2026
```

Adjust `DEFAULT_YEAR_FROM` / `DEFAULT_YEAR_TO` to change the default range for all commands, or override per-invocation with `--year-from` / `--year-to`.
