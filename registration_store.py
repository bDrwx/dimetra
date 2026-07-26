"""
registration_store.py

Persists "Mobility Update - Location Registration" / "Unit Registration" events to a
local SQLite database, for whatever downstream processing needs them later (roaming
history, last-known-site lookups, ...) -- not decided yet, so this only captures the
raw fields rather than shaping them into anything.

Distinct from call_correlator.py/gcdr_builder.py: these events are never turned into
Gcdr billing rows here, just recorded as-is. See pipeline.py for where this is wired
into the log-file scan.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from text_log_parser import LogEvent, parse_composite_id

LOCATION_REGISTRATION = "Mobility Update - Location Registration"
UNIT_REGISTRATION = "Mobility Update - Unit Registration"
REGISTRATION_KINDS = {LOCATION_REGISTRATION, UNIT_REGISTRATION}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    event_ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    unit_id_decimal TEXT,
    unit_id_hex TEXT,
    unit_label TEXT,
    registered_zone TEXT,
    registered_site TEXT,
    previous_registered_site TEXT,
    registered_type TEXT,
    mobility_request_result TEXT,
    UNIQUE (source_file, line_no)
);
CREATE INDEX IF NOT EXISTS idx_registrations_unit ON registrations (unit_id_decimal);
CREATE INDEX IF NOT EXISTS idx_registrations_ts ON registrations (event_ts);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def is_registration(event: LogEvent) -> bool:
    return event.kind in REGISTRATION_KINDS


def record(conn: sqlite3.Connection, source_file: str, event: LogEvent) -> bool:
    """
    Insert one registration event. Returns False if a row for this (source_file,
    line_no) already existed (e.g. pipeline.py re-run against an already-processed
    file), True if newly inserted. Does not commit -- caller controls transaction
    boundaries (pipeline.py commits once per file).
    """
    unit = event.blocks.get("UNIT", {})
    requester = event.blocks.get("REQUESTER", {})
    status = event.blocks.get("STATUS", {})
    parsed_unit = parse_composite_id(unit.get("Operating Unit ID", ""))

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO registrations (
            source_file, line_no, event_ts, kind,
            unit_id_decimal, unit_id_hex, unit_label,
            registered_zone, registered_site, previous_registered_site,
            registered_type, mobility_request_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_file,
            event.line_no,
            event.timestamp.isoformat(),
            event.subtype,
            parsed_unit.decimal if parsed_unit else None,
            parsed_unit.hex if parsed_unit else None,
            parsed_unit.label if parsed_unit else None,
            requester.get("Registered Zone", "n/a"),
            requester.get("Registered Site", "n/a"),
            requester.get("Previous Registered Site", "n/a"),
            requester.get("Registered Type", "n/a"),
            status.get("Mobility Request Result", "n/a"),
        ),
    )
    return cur.rowcount > 0
