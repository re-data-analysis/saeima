from pathlib import Path

CKAN_API_URL = "https://data.gov.lv/dati/api/3/action/package_show"
DATASET_ID = "saeimas-sedes"

DATA_DIR = Path("data/sessions")
XML_DIR = DATA_DIR / "xml"
REGISTRY_PATH = DATA_DIR / "registry.csv"

VOTES_CSV_PATH = DATA_DIR / "votes.csv"

DEFAULT_YEAR_FROM = 2022
DEFAULT_YEAR_TO = 2026
