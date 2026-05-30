"""Fetches Saeima session XML files from the Latvian Open Data portal (CKAN API)."""

from __future__ import annotations

import csv
import logging
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import click
import httpx

from saeima.sessions.config import (
    CKAN_API_URL,
    DATASET_ID,
    DEFAULT_YEAR_FROM,
    DEFAULT_YEAR_TO,
    REGISTRY_PATH,
    XML_DIR,
)

logger = logging.getLogger(__name__)

REGISTRY_FIELDS = [
    "resource_id",
    "saeima_no",
    "year",
    "session",
    "session_no",
    "doc_type",
    "download_url",
    "filename",
    "raw_name",
]

_RE_REGULAR = re.compile(
    r"(\d+)\.Saeimas\s+(\d{4})\.gada?\s+"
    r"(pavasara|rudens|ziemas)\s+sesija-(\d+)-(\w+)"
)
_RE_ARKARTAS = re.compile(
    r"(\d+)\.Saeimas\s+(\d{4})\.gada?\s+"
    r".+?ārk[āa]rtas\s+sesij[a]?-(\d+)-(\w+)"
)
_RE_TAIL = re.compile(r"sesij[a]?-(\d+)-(\w+)")


def fetch_registry() -> list[dict]:
    """Fetch all resources for the saeimas-sedes dataset from the CKAN API."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(CKAN_API_URL, params={"id": DATASET_ID})
        resp.raise_for_status()
        data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"CKAN API returned success=false: {data}")
    return data["result"]["resources"]


def parse_resource_name(name: str) -> dict:
    """Parse a resource name into structured fields.

    Args:
        name: Resource name, e.g. "12.Saeimas 2017.gada pavasara sesija-15-dkp".

    Returns:
        Dict with keys: saeima_no, year, session, session_no, doc_type.
        Missing fields are set to None.
    """
    m = _RE_REGULAR.match(name)
    if m:
        return {
            "saeima_no": int(m.group(1)),
            "year": int(m.group(2)),
            "session": m.group(3),
            "session_no": int(m.group(4)),
            "doc_type": m.group(5),
        }

    m = _RE_ARKARTAS.match(name)
    if m:
        return {
            "saeima_no": int(m.group(1)),
            "year": int(m.group(2)),
            "session": "ārkārtas",
            "session_no": int(m.group(3)),
            "doc_type": m.group(4),
        }

    # Fallback: extract what we can from the tail
    tail = _RE_TAIL.search(name)
    result: dict = {
        "saeima_no": None,
        "year": None,
        "session": None,
        "session_no": int(tail.group(1)) if tail else None,
        "doc_type": tail.group(2) if tail else None,
    }
    logger.warning("Could not fully parse resource name: %s", name)
    return result


def _filename_from_url(url: str) -> str:
    return unquote(url.rsplit("/", 1)[-1])


def build_registry(resources: list[dict]) -> list[dict]:
    """Convert raw CKAN resources into structured registry rows."""
    rows = []
    for r in resources:
        parsed = parse_resource_name(r["name"])
        rows.append(
            {
                "resource_id": r["id"],
                "saeima_no": parsed["saeima_no"] or "",
                "year": parsed["year"] or "",
                "session": parsed["session"] or "",
                "session_no": parsed["session_no"] or "",
                "doc_type": parsed["doc_type"] or "",
                "download_url": r["url"],
                "filename": _filename_from_url(r["url"]),
                "raw_name": r["name"],
            }
        )
    return rows


def save_registry(rows: list[dict], path: Path = REGISTRY_PATH) -> None:
    """Write registry rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    """Load registry rows from CSV."""
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_downloaded_files(xml_dir: Path = XML_DIR) -> set[str]:
    """Return set of filenames already present in the download directory."""
    if not xml_dir.exists():
        return set()
    return {p.name for p in xml_dir.iterdir() if p.is_file()}


def filter_rows(
    rows: list[dict],
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    saeima: int | None = None,
    doc_type: str | None = None,
) -> list[dict]:
    """Filter registry rows by the given criteria."""
    filtered = rows
    if year_from is not None:
        filtered = [r for r in filtered if r["year"] and int(r["year"]) >= year_from]
    if year_to is not None:
        filtered = [r for r in filtered if r["year"] and int(r["year"]) <= year_to]
    if saeima is not None:
        filtered = [
            r for r in filtered if r["saeima_no"] and int(r["saeima_no"]) == saeima
        ]
    if doc_type is not None:
        filtered = [r for r in filtered if r["doc_type"] == doc_type]
    return filtered


def download_files(
    rows: list[dict],
    xml_dir: Path = XML_DIR,
    dry_run: bool = False,
) -> int:
    """Download XML files that are not yet present locally.

    Args:
        rows: Registry rows to consider for download.
        xml_dir: Target directory for XML files.
        dry_run: If True, only log what would be downloaded.

    Returns:
        Number of files downloaded (or that would be downloaded in dry-run mode).
    """
    xml_dir.mkdir(parents=True, exist_ok=True)
    existing = get_downloaded_files(xml_dir)
    to_download = [r for r in rows if r["filename"] not in existing]

    if not to_download:
        click.echo("All files already downloaded.")
        return 0

    click.echo(
        f"{'Would download' if dry_run else 'Downloading'} "
        f"{len(to_download)} file(s)..."
    )

    if dry_run:
        for r in to_download:
            click.echo(f"  {r['filename']}")
        return len(to_download)

    downloaded = 0
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i, r in enumerate(to_download, 1):
            dest = xml_dir / r["filename"]
            try:
                resp = client.get(r["download_url"])
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                downloaded += 1
                if i % 50 == 0 or i == len(to_download):
                    click.echo(f"  [{i}/{len(to_download)}] downloaded")
            except httpx.HTTPError:
                logger.exception("Failed to download %s", r["filename"])
                time.sleep(1)

    click.echo(f"Done. {downloaded}/{len(to_download)} files downloaded.")
    return downloaded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """Saeima session data getter."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


@cli.command()
@click.option(
    "--year-from",
    type=int,
    default=DEFAULT_YEAR_FROM,
    show_default=True,
    help="Start year (inclusive).",
)
@click.option(
    "--year-to",
    type=int,
    default=DEFAULT_YEAR_TO,
    show_default=True,
    help="End year (inclusive).",
)
@click.option("--saeima", type=int, default=None, help="Saeima number (e.g. 14).")
@click.option(
    "--doc-type",
    type=click.Choice(["dkp", "vote", "deb"], case_sensitive=False),
    default=None,
    help="Document type to download.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded.")
def sync(
    year_from: int | None,
    year_to: int | None,
    saeima: int | None,
    doc_type: str | None,
    dry_run: bool,
) -> None:
    """Fetch the registry from CKAN and download new XML files."""
    click.echo("Fetching resource list from CKAN API...")
    resources = fetch_registry()
    click.echo(f"Found {len(resources)} resources.")

    rows = build_registry(resources)
    save_registry(rows)
    click.echo(f"Registry saved to {REGISTRY_PATH}")

    filtered = filter_rows(
        rows,
        year_from=year_from,
        year_to=year_to,
        saeima=saeima,
        doc_type=doc_type,
    )
    click.echo(f"{len(filtered)} resources match filters.")

    download_files(filtered, dry_run=dry_run)


@cli.command()
def status() -> None:
    """Show counts of available vs downloaded files."""
    rows = load_registry()
    if not rows:
        click.echo("No registry found. Run 'sync' first.")
        return

    existing = get_downloaded_files()
    downloaded = sum(1 for r in rows if r["filename"] in existing)

    click.echo(f"Registry:   {len(rows)} resources")
    click.echo(f"Downloaded: {downloaded}")
    click.echo(f"Missing:    {len(rows) - downloaded}")

    type_counts = Counter(r["doc_type"] for r in rows)
    type_downloaded = Counter(r["doc_type"] for r in rows if r["filename"] in existing)
    click.echo("\nBy document type:")
    for dt in sorted(type_counts):
        click.echo(
            f"  {dt:6s}  {type_downloaded.get(dt, 0):>4d} / {type_counts[dt]:>4d}"
        )


if __name__ == "__main__":
    cli()
