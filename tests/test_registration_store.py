"""Unit tests for registration_store.py: schema creation, field extraction from
Location/Unit Registration events, and dedup on (source_file, line_no)."""
from pathlib import Path

import text_log_parser as tlp
from fixtures.sample_lines import (
    LOCATION_REGISTRATION,
    NON_BILLING_CONTROL_CHANNEL_UPDATE,
    START_OF_CALL_INDIVIDUAL,
    UNIT_REGISTRATION,
)
from registration_store import connect, is_registration, record


class TestIsRegistration:
    def test_location_registration_is_true(self):
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        assert is_registration(ev) is True

    def test_unit_registration_is_true(self):
        ev = tlp.parse_line(1, UNIT_REGISTRATION)
        assert is_registration(ev) is True

    def test_non_registration_is_false(self):
        ev = tlp.parse_line(1, START_OF_CALL_INDIVIDUAL)
        assert is_registration(ev) is False

    def test_non_billing_event_is_false(self):
        ev = tlp.parse_line(1, NON_BILLING_CONTROL_CHANNEL_UPDATE)
        assert is_registration(ev) is False


class TestConnect:
    def test_creates_schema_on_a_fresh_file(self, tmp_path: Path):
        conn = connect(tmp_path / "regs.sqlite3")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        )
        assert {row[0] for row in cur.fetchall()} == {"registrations"}
        conn.close()

    def test_reopening_an_existing_db_is_idempotent(self, tmp_path: Path):
        path = tmp_path / "regs.sqlite3"
        connect(path).close()
        conn = connect(path)  # CREATE TABLE IF NOT EXISTS shouldn't raise
        conn.close()


class TestRecord:
    def test_extracts_fields_from_location_registration(self, tmp_path: Path):
        conn = connect(tmp_path / "regs.sqlite3")
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        inserted = record(conn, "log1.txt", ev)
        conn.commit()
        assert inserted is True

        row = conn.execute(
            "SELECT source_file, line_no, event_ts, kind, unit_id_decimal, unit_id_hex, "
            "unit_label, registered_zone, registered_site, previous_registered_site, "
            "registered_type, mobility_request_result FROM registrations"
        ).fetchone()
        assert row == (
            "log1.txt", 1, "2026-07-16T14:00:42", "Location Registration",
            "5451", "0x154B", "NUR UMN 5451",
            "1", "54", "n/a", "Talkgroup Affiliation", "Accepted",
        )

    def test_extracts_fields_from_unit_registration(self, tmp_path: Path):
        conn = connect(tmp_path / "regs.sqlite3")
        ev = tlp.parse_line(1, UNIT_REGISTRATION)
        record(conn, "log1.txt", ev)
        conn.commit()

        row = conn.execute(
            "SELECT unit_id_decimal, registered_site, registered_type FROM registrations"
        ).fetchone()
        assert row == ("3741010", "8", "Regd Not Affiliated")

    def test_duplicate_source_file_and_line_no_is_ignored(self, tmp_path: Path):
        conn = connect(tmp_path / "regs.sqlite3")
        ev = tlp.parse_line(5, LOCATION_REGISTRATION)
        first = record(conn, "log1.txt", ev)
        second = record(conn, "log1.txt", ev)
        conn.commit()
        assert first is True
        assert second is False
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 1

    def test_same_line_no_in_a_different_file_is_a_separate_row(self, tmp_path: Path):
        conn = connect(tmp_path / "regs.sqlite3")
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        record(conn, "log1.txt", ev)
        record(conn, "log2.txt", ev)
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 2
