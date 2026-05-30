"""Parses Saeima vote XML files into a flat CSV spreadsheet."""

from __future__ import annotations

import csv
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import click

from saeima.sessions.config import (
    DEFAULT_YEAR_FROM,
    DEFAULT_YEAR_TO,
    VOTES_CSV_PATH,
    XML_DIR,
)

logger = logging.getLogger(__name__)

PRESENCE_MOTIVE = "Deputātu klātbūtnes reģistrācija"

OUTPUT_FIELDS = [
    "source_file",
    "vote_number",
    "vote_timestamp",
    "vote_motive",
    "dkp_id",
    "voting_id",
    "vote_result_for",
    "vote_result_against",
    "vote_result_abstain",
    "vote_result_registered",
    "name",
    "surname",
    "fraction",
    "result",
    "was_present",
]


def parse_vote_file(path: Path) -> list[dict]:
    """Parse a vote XML file into a list of VOTES block dicts, sorted by VOTE_NUMBER.

    Args:
        path: Path to the XML file.

    Returns:
        List of dicts, each representing one VOTES block with split parallel arrays.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    blocks = []
    for v in root.findall("VOTES"):
        vote_number_text = v.findtext("VOTE_NUMBER")
        if not vote_number_text:
            continue
        block = {
            "vote_number": int(vote_number_text),
            "vote_timestamp": v.findtext("VOTETIMESTAMP") or "",
            "vote_motive": (v.findtext("VOTEMOTIVE") or "").strip(),
            "dkp_id": v.findtext("dkp_id") or "",
            "voting_id": v.findtext("VOTING_ID") or "",
            "vote_result_for": v.findtext("VOTERESULT_FOR") or "",
            "vote_result_against": v.findtext("VOTERESULT_AGAINST") or "",
            "vote_result_abstain": v.findtext("VOTERESULT_ABSTAIN") or "",
            "vote_result_registered": v.findtext("VOTERESULT_REGISTERED") or "",
            "is_candidate": v.findtext("VOTEISCANDIDATE") == "1",
            "names": _split(v.findtext("NAME")),
            "surnames": _split(v.findtext("SURNAME")),
            "fractions": _split(v.findtext("FRACTION")),
            "results": _split(v.findtext("RESULT")),
        }
        blocks.append(block)
    blocks.sort(key=lambda b: b["vote_number"])
    return blocks


def _split(text: str | None) -> list[str]:
    if not text:
        return []
    return text.split("#")


def build_presence_map(
    blocks: list[dict],
) -> dict[int, dict[tuple[str, str], bool]]:
    """Index all "Deputatu klatbutnes registracija" blocks by their vote number.

    Each session has multiple presence-registration events interspersed
    among regular votes.  This function extracts them and builds a lookup
    so that, given any vote number, we can later find the nearest
    registration and check whether a specific MP was present.

    Args:
        blocks: Sorted list of VOTES block dicts from one session file
            (output of parse_vote_file).

    Returns:
        Dict keyed by vote_number of each presence registration.
        Each value is a dict mapping (name, surname) -> True/False
        (True = "Reģistrējies", False = "Nereģistrējies").

    Example:
        {
            13: {("Ilze", "Indriksone"): True, ("Mārtiņš", "Daģis"): False, ...},
            27: {("Ilze", "Indriksone"): True, ...},
        }
    """
    pmap: dict[int, dict[tuple[str, str], bool]] = {}
    for b in blocks:
        if b["vote_motive"] != PRESENCE_MOTIVE:
            continue
        mp_presence: dict[tuple[str, str], bool] = {}
        for name, surname, result in zip(
            b["names"], b["surnames"], b["results"], strict=True
        ):
            mp_presence[(name, surname)] = result == "Reģistrējies"
        pmap[b["vote_number"]] = mp_presence
    return pmap


def resolve_presence(
    vote_number: int,
    presence_map: dict[int, dict[tuple[str, str], bool]],
) -> dict[tuple[str, str], bool]:
    """Find the nearest presence registration for a given vote.

    Prefers the latest preceding registration. Falls back to the earliest
    following one if none precedes.

    Args:
        vote_number: The VOTE_NUMBER to resolve presence for.
        presence_map: Output of build_presence_map.

    Returns:
        Dict mapping (name, surname) -> was_registered, or empty dict.
    """
    if not presence_map:
        return {}
    pres_numbers = sorted(presence_map)
    preceding = [n for n in pres_numbers if n <= vote_number]
    if preceding:
        return presence_map[preceding[-1]]
    return presence_map[pres_numbers[0]]


def _build_fraction_lookup(blocks: list[dict]) -> dict[tuple[str, str], str]:
    """Build a (name, surname) -> fraction lookup from all blocks in a session.

    Uses the last non-empty fraction seen for each MP, which handles cases
    where some votes have blank fractions but others (especially presence
    registrations) have them populated.
    """
    lookup: dict[tuple[str, str], str] = {}
    for b in blocks:
        for name, surname, fraction in zip(
            b["names"], b["surnames"], b["fractions"], strict=False
        ):
            if fraction.strip():
                lookup[(name, surname)] = fraction
    return lookup


def explode_votes(path: Path) -> list[dict]:
    """Parse one vote XML file and expand into flat per-MP rows.

    Skips candidate votes and presence registrations. For each regular vote,
    adds rows for every MP in the vote list, plus rows for MPs who were
    registered as present but absent from the vote.

    Args:
        path: Path to the vote XML file.

    Returns:
        List of row dicts matching OUTPUT_FIELDS.
    """
    blocks = parse_vote_file(path)
    if not blocks:
        return []

    presence_map = build_presence_map(blocks)
    fraction_lookup = _build_fraction_lookup(blocks)
    source_file = path.name
    rows: list[dict] = []

    for b in blocks:
        if b["is_candidate"] or b["vote_motive"] == PRESENCE_MOTIVE:
            continue
        if not b["names"]:
            continue

        presence = resolve_presence(b["vote_number"], presence_map)

        vote_meta = {
            "source_file": source_file,
            "vote_number": b["vote_number"],
            "vote_timestamp": b["vote_timestamp"],
            "vote_motive": b["vote_motive"],
            "dkp_id": b["dkp_id"],
            "voting_id": b["voting_id"],
            "vote_result_for": b["vote_result_for"],
            "vote_result_against": b["vote_result_against"],
            "vote_result_abstain": b["vote_result_abstain"],
            "vote_result_registered": b["vote_result_registered"],
        }

        mps_in_vote: set[tuple[str, str]] = set()
        for name, surname, fraction, result in zip(
            b["names"],
            b["surnames"],
            b["fractions"],
            b["results"],
            strict=True,
        ):
            key = (name, surname)
            mps_in_vote.add(key)
            rows.append(
                {
                    **vote_meta,
                    "name": name,
                    "surname": surname,
                    "fraction": fraction.strip() or fraction_lookup.get(key, ""),
                    "result": result,
                    "was_present": presence.get(key, ""),
                }
            )

        for mp_key, was_registered in presence.items():
            if mp_key not in mps_in_vote and was_registered:
                rows.append(
                    {
                        **vote_meta,
                        "name": mp_key[0],
                        "surname": mp_key[1],
                        "fraction": fraction_lookup.get(mp_key, ""),
                        "result": "",
                        "was_present": True,
                    }
                )

    return rows


def build_all(
    xml_dir: Path = XML_DIR,
    output_path: Path = VOTES_CSV_PATH,
    saeima: int = 14,
    year_from: int | None = None,
    year_to: int | None = None,
) -> int:
    """Process all vote XML files for a saeima and write a combined CSV.

    Args:
        xml_dir: Directory containing the XML files.
        output_path: Path for the output CSV.
        saeima: Saeima number to filter files by.
        year_from: Optional start year filter (inclusive).
        year_to: Optional end year filter (inclusive).

    Returns:
        Total number of rows written.
    """
    pattern = f"{saeima}.saeimas-*-vote.xml"
    files = sorted(xml_dir.glob(pattern))

    if year_from is not None or year_to is not None:
        filtered = []
        for f in files:
            m = re.search(r"-(\d{4})\.", f.name)
            if not m:
                filtered.append(f)
                continue
            year = int(m.group(1))
            if year_from and year < year_from:
                continue
            if year_to and year > year_to:
                continue
            filtered.append(f)
        files = filtered

    if not files:
        click.echo("No vote files found matching filters.")
        return 0

    click.echo(f"Processing {len(files)} vote file(s)...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for i, path in enumerate(files, 1):
            rows = explode_votes(path)
            writer.writerows(rows)
            total_rows += len(rows)
            if i % 50 == 0 or i == len(files):
                click.echo(f"  [{i}/{len(files)}] {total_rows:,} rows so far")

    click.echo(f"Done. {total_rows:,} rows written to {output_path}")
    return total_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("build-votes")
@click.option(
    "--saeima", type=int, default=14, show_default=True, help="Saeima number."
)
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
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Output CSV path (default: data/sessions/votes.csv).",
)
def build_votes_cmd(
    saeima: int,
    year_from: int,
    year_to: int,
    output: str | None,
) -> None:
    """Parse vote XMLs into a flat per-MP CSV spreadsheet."""
    out = Path(output) if output else VOTES_CSV_PATH
    build_all(
        saeima=saeima,
        year_from=year_from,
        year_to=year_to,
        output_path=out,
    )
