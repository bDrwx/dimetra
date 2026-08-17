"""Unit/integration tests for pipeline.py: single-file processing, checkpoint
persistence, and --watch-dir batch mode (including a call spanning two rotated
files and the "don't reprocess" guarantee)."""
import csv
import json
import sqlite3
from pathlib import Path

from fixtures.sample_lines import (
    CALL_STATE_CHANGE_CONNECTED,
    END_OF_CALL,
    INTERCONNECT_BILLING,
    LOCATION_REGISTRATION,
    NON_BILLING_CONTROL_CHANNEL_UPDATE,
    START_OF_CALL_INDIVIDUAL,
)

import registration_store
from call_correlator import CallCorrelator
from pipeline import (
    load_checkpoint,
    process_file,
    run_batch,
    run_single_file_smoke_test,
    save_checkpoint,
)

_CALL_ID = "83317"
_START = START_OF_CALL_INDIVIDUAL.replace("83316", _CALL_ID)
_CONNECTED = CALL_STATE_CHANGE_CONNECTED.replace("83316", _CALL_ID)
_BILLING = INTERCONNECT_BILLING
_END = END_OF_CALL
_UNMATCHED_END = END_OF_CALL.replace("83317", "999999")  # closes a call never started


def write_log(path: Path, *lines: str) -> None:
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


class TestProcessFile:
    def test_full_call_produces_one_record(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, NON_BILLING_CONTROL_CHANNEL_UPDATE, _START, _CONNECTED, _BILLING, _END)
        correlator = CallCorrelator()
        records, exceptions = process_file(log, correlator)
        assert len(records) == 1
        assert exceptions == []
        assert correlator.open_calls == {}

    def test_end_of_call_with_no_start_becomes_an_exception(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, _UNMATCHED_END)
        correlator = CallCorrelator()
        records, exceptions = process_file(log, correlator)
        assert records == []
        assert len(exceptions) == 1
        assert exceptions[0][0].call_id == "999999"

    def test_call_still_open_at_eof_is_not_a_record_or_exception(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, _START, _CONNECTED)  # never closed
        correlator = CallCorrelator()
        records, exceptions = process_file(log, correlator)
        assert records == []
        assert exceptions == []
        assert _CALL_ID in correlator.open_calls

    def test_registration_event_never_reaches_the_correlator(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, LOCATION_REGISTRATION)
        correlator = CallCorrelator()
        records, exceptions = process_file(log, correlator)
        assert records == []
        assert exceptions == []
        assert correlator.open_calls == {}  # not tracked as an open call either

    def test_registration_event_is_skipped_without_a_reg_conn(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, LOCATION_REGISTRATION)
        process_file(log, CallCorrelator())  # reg_conn omitted -- must not raise

    def test_registration_event_is_recorded_when_reg_conn_given(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, LOCATION_REGISTRATION)
        conn = registration_store.connect(tmp_path / "regs.sqlite3")
        process_file(log, CallCorrelator(), conn)
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 1


class TestCheckpoint:
    def test_load_missing_checkpoint_returns_defaults(self, tmp_path: Path):
        cp = load_checkpoint(tmp_path / "does_not_exist.json")
        assert cp == {"processed_files": [], "open_calls": ""}

    def test_save_then_load_round_trips(self, tmp_path: Path):
        path = tmp_path / "checkpoint.json"
        save_checkpoint(path, {"processed_files": ["a.txt"], "open_calls": '{"1": {}}'})
        loaded = load_checkpoint(path)
        assert loaded["processed_files"] == ["a.txt"]
        assert loaded["open_calls"] == '{"1": {}}'


class TestRunBatch:
    def test_writes_output_and_checkpoint(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        write_log(watch_dir / "log1.txt", _START, _CONNECTED, _BILLING, _END)

        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"

        run_batch(watch_dir, out, checkpoint, exceptions)

        assert out.exists()
        with out.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter=";"))
        assert len(rows) == 1

        cp = load_checkpoint(checkpoint)
        assert cp["processed_files"] == ["log1.txt"]
        assert not exceptions.exists()

    def test_second_run_does_not_reprocess_same_file(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        write_log(watch_dir / "log1.txt", _START, _CONNECTED, _BILLING, _END)

        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"

        run_batch(watch_dir, out, checkpoint, exceptions)
        run_batch(watch_dir, out, checkpoint, exceptions)  # no new files this time

        with out.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter=";"))
        assert len(rows) == 1  # not doubled

    def test_exceptions_file_records_incomplete_calls(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        write_log(watch_dir / "log1.txt", _UNMATCHED_END)

        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"

        run_batch(watch_dir, out, checkpoint, exceptions)

        assert exceptions.exists()
        lines = exceptions.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["call_id"] == "999999"

    def test_call_spanning_two_rotated_files_is_billed_once(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"

        # First run: only log1.txt exists, containing just the Start of Call.
        write_log(watch_dir / "log1.txt", _START)
        run_batch(watch_dir, out, checkpoint, exceptions)
        cp = load_checkpoint(checkpoint)
        assert cp["processed_files"] == ["log1.txt"]
        assert not out.exists() or out.read_text(encoding="utf-8") == ""

        # Second run: log2.txt "arrives" with the rest of the same call.
        write_log(watch_dir / "log2.txt", _CONNECTED, _BILLING, _END)
        run_batch(watch_dir, out, checkpoint, exceptions)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter=";"))
        assert len(rows) == 1

    def test_no_new_files_is_a_noop(self, tmp_path: Path, caplog):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"

        run_batch(watch_dir, out, checkpoint, exceptions)

        assert not out.exists()

    def test_registrations_written_to_db_alongside_billing_output(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        write_log(watch_dir / "log1.txt", _START, _CONNECTED, _BILLING, _END, LOCATION_REGISTRATION)

        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"
        regs_db = tmp_path / "regs.sqlite3"

        run_batch(watch_dir, out, checkpoint, exceptions, regs_db)

        assert regs_db.exists()
        conn = sqlite3.connect(regs_db)
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 1
        with out.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter=";"))
        assert len(rows) == 1  # the call, not the registration

    def test_second_batch_run_does_not_reinsert_same_registration(self, tmp_path: Path):
        watch_dir = tmp_path / "logs"
        watch_dir.mkdir()
        write_log(watch_dir / "log1.txt", LOCATION_REGISTRATION)

        out = tmp_path / "billing_export.csv"
        checkpoint = tmp_path / "checkpoint.json"
        exceptions = tmp_path / "exceptions.jsonl"
        regs_db = tmp_path / "regs.sqlite3"

        run_batch(watch_dir, out, checkpoint, exceptions, regs_db)
        run_batch(watch_dir, out, checkpoint, exceptions, regs_db)  # no new files

        conn = sqlite3.connect(regs_db)
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 1


class TestSingleFileSmokeTest:
    def test_runs_without_a_registrations_db(self, tmp_path: Path, capsys):
        log = tmp_path / "log1.txt"
        write_log(log, _START, _CONNECTED, _BILLING, _END, LOCATION_REGISTRATION)
        run_single_file_smoke_test(log)  # must not raise
        assert "1 Gcdr records built" in capsys.readouterr().out

    def test_runs_with_a_registrations_db(self, tmp_path: Path):
        log = tmp_path / "log1.txt"
        write_log(log, LOCATION_REGISTRATION)
        regs_db = tmp_path / "regs.sqlite3"
        run_single_file_smoke_test(log, regs_db)
        conn = sqlite3.connect(regs_db)
        count = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        assert count == 1
