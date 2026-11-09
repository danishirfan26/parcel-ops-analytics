"""Generate, load and query synthetic parcel scan events."""

import argparse
import csv
import json
import random
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


FIELDS = ("event_id", "parcel_id", "event_type", "occurred_at", "hub")
EVENT_TYPES = ("ACCEPTED", "IN_TRANSIT", "EXCEPTION", "DELIVERED")
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SQL = Path(__file__).with_name("sql")
IDENTIFIER = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,39}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY NOT NULL,
    parcel_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'ACCEPTED', 'IN_TRANSIT', 'EXCEPTION', 'DELIVERED'
    )),
    occurred_at TEXT NOT NULL,
    hub TEXT NOT NULL
);
"""


def utc_timestamp(value):
    try:
        parsed = datetime.strptime(value, UTC_FORMAT)
    except (ValueError, TypeError):
        raise ValueError("Expected UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format") from None
    if parsed.strftime(UTC_FORMAT) != value:
        raise ValueError("Expected UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format")
    return value


def generate_demo(destination):
    """Write a deterministic feed including one exact repeated row."""
    rng = random.Random(42)
    first_day = datetime(2025, 3, 3, 8, tzinfo=timezone.utc)
    hubs = ("BANGI", "JOHOR_BAHRU", "SHAH_ALAM")
    rows = []
    for index in range(120):
        accepted_at = first_day + timedelta(days=index // 10, minutes=45 * (index % 10))
        origin = rng.choice(hubs)
        destination_hub = rng.choice(hubs)
        scans = [("ACCEPTED", 0, origin), ("IN_TRANSIT", 8, destination_hub)]
        if rng.random() < 0.24:
            scans.append(("EXCEPTION", 15, destination_hub))
            if rng.random() < 0.3:
                scans.append(("EXCEPTION", 19, destination_hub))
        if rng.random() < 0.86:
            scans.append(("DELIVERED", rng.randint(20, 83), destination_hub))
        for event_type, hours, hub in scans:
            occurred_at = accepted_at + timedelta(hours=hours)
            rows.append((f"E{len(rows) + 1:04}", f"P{index + 1:04}", event_type,
                         occurred_at.strftime(UTC_FORMAT), hub))

    rows.append(rows[0])
    rng.shuffle(rows)
    with Path(destination).open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    return len(rows)


def load_events(source, database):
    """Load a file as one transaction and skip exact replays."""
    counts = {"inserted": 0, "duplicates": 0}
    with Path(source).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, strict=True)
        if reader.fieldnames != list(FIELDS):
            raise ValueError(f"Expected CSV header {', '.join(FIELDS)}")

        with closing(sqlite3.connect(database)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(SCHEMA)
            for row in reader:
                try:
                    if None in row or any(row[field] is None for field in FIELDS):
                        raise ValueError("Expected five fields")
                    event = tuple(row[field] for field in FIELDS)
                    event_id, parcel_id, event_type, occurred_at, hub = event
                    if any(not IDENTIFIER.fullmatch(value) for value in (event_id, parcel_id, hub)):
                        raise ValueError("Invalid event ID, parcel ID or hub")
                    if event_type not in EVENT_TYPES:
                        raise ValueError(f"Unknown event type {event_type!r}")
                    utc_timestamp(occurred_at)
                    existing = db.execute(
                        "SELECT event_id, parcel_id, event_type, occurred_at, hub "
                        "FROM events WHERE event_id = ?", (event_id,)
                    ).fetchone()
                    if existing == event:
                        counts["duplicates"] += 1
                        continue
                    if existing is not None:
                        raise ValueError(f"Conflicting payload for event ID {event_id}")
                    db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", event)
                    counts["inserted"] += 1
                except ValueError as error:
                    raise ValueError(f"CSV line {reader.line_num}: {error}") from error
    return counts


def build_report(database, as_of, sla_hours=48):
    """Query one consistent snapshot of the event store."""
    utc_timestamp(as_of)
    if sla_hours <= 0:
        raise ValueError("SLA hours must be positive")
    if not Path(database).is_file():
        raise ValueError("Database does not exist. Load a feed first.")

    params = {"as_of": as_of, "sla_hours": sla_hours}
    report = params.copy()
    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        for name in ("origin_performance", "weekly_exceptions"):
            query = (SQL / f"{name}.sql").read_text(encoding="utf-8")
            report[name] = [dict(row) for row in db.execute(query, params)]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Write the synthetic CSV")
    generate.add_argument("csv", type=Path)
    load = commands.add_parser("load", help="Load an event CSV into SQLite")
    load.add_argument("csv", type=Path)
    load.add_argument("database", type=Path)
    report = commands.add_parser("report", help="Print the warehouse snapshot as JSON")
    report.add_argument("database", type=Path)
    report.add_argument("--as-of", required=True, help="UTC cutoff (YYYY-MM-DDTHH:MM:SSZ)")
    report.add_argument("--sla-hours", type=int, default=48)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            result = {"rows_written": generate_demo(args.csv)}
        elif args.command == "load":
            result = load_events(args.csv, args.database)
        else:
            result = build_report(args.database, args.as_of, args.sla_hours)
    except (OSError, ValueError, csv.Error, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
