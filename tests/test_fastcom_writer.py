"""Unit tests for fastcom_writer.py: delimiter/encoding sourced from config,
append vs. overwrite mode, and parent-directory creation."""
from datetime import datetime, timedelta
from pathlib import Path

import config
from fastcom_writer import write_gcdr_rows
from gcdr_models import CallType, Dvo, Gcdr, TextInterface, TextSubscriber, TextTermination, UserType


def make_gcdr(number_a="67805418", number_b="5217", check_summ=1) -> Gcdr:
    abon_a = TextSubscriber(
        stype=UserType.outer, number=number_a, dxt_prefix={}, start_location=65535, end_location=65535
    )
    abon_b = TextSubscriber(
        stype=UserType.inner, number=number_b, dxt_prefix={}, start_location=68, end_location=68
    )
    return Gcdr(
        dxt_id="ZS-DXT-ID",
        provider_id=45,
        date=datetime(2026, 7, 16, 14, 0, 47),
        call_duration=timedelta(seconds=30),
        abon_a=abon_a,
        abon_b=abon_b,
        if_in=TextInterface("1"),
        if_out=TextInterface("1"),
        call_termination=TextTermination.normal_call_clearing,
        dvo=Dvo(switch=False),
        call_type=CallType.ingtcc,
        check_summ=check_summ,
    )


class TestWriteGcdrRows:
    def test_returns_count_written(self, tmp_path: Path):
        out = tmp_path / "out.csv"
        n = write_gcdr_rows([make_gcdr(), make_gcdr()], out)
        assert n == 2

    def test_uses_configured_delimiter(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(config, "OUTPUT_DELIMITER", "|")
        out = tmp_path / "out.csv"
        write_gcdr_rows([make_gcdr()], out)
        content = out.read_text(encoding="utf-8")
        assert "14:00:47 16.07.2026|30|5|0|2|ZS-DXT-ID" in content

    def test_uses_configured_encoding(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(config, "OUTPUT_ENCODING", "cp1251")
        monkeypatch.setattr(config, "OUTPUT_DELIMITER", ";")
        out = tmp_path / "out.csv"
        write_gcdr_rows([make_gcdr(number_b="Балык")], out)
        content = out.read_bytes().decode("cp1251")
        assert "Балык" in content

    def test_overwrite_mode_replaces_previous_content(self, tmp_path: Path):
        out = tmp_path / "out.csv"
        write_gcdr_rows([make_gcdr(check_summ=1)], out, append=False)
        write_gcdr_rows([make_gcdr(check_summ=2)], out, append=False)
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_append_mode_adds_to_existing_file(self, tmp_path: Path):
        out = tmp_path / "out.csv"
        write_gcdr_rows([make_gcdr(check_summ=1)], out, append=False)
        write_gcdr_rows([make_gcdr(check_summ=2)], out, append=True)
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_creates_missing_parent_directories(self, tmp_path: Path):
        out = tmp_path / "nested" / "dir" / "out.csv"
        write_gcdr_rows([make_gcdr()], out)
        assert out.exists()

    def test_empty_records_writes_empty_file(self, tmp_path: Path):
        out = tmp_path / "out.csv"
        n = write_gcdr_rows([], out)
        assert n == 0
        assert out.exists()
        assert out.read_text(encoding="utf-8") == ""
