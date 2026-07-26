"""Unit tests for text_log_parser.py: header/block grammar, banner/blank skipping,
UTF-16/UTF-8 file decoding, and the composite-id sub-parser."""
from datetime import datetime
from pathlib import Path

import pytest

import text_log_parser as tlp
from fixtures.sample_lines import (
    BANNER_LINE,
    END_OF_CALL,
    INTERCONNECT_BILLING,
    NON_BILLING_CONTROL_CHANNEL_UPDATE,
    START_OF_CALL_GROUP,
    START_OF_CALL_INDIVIDUAL,
)


class TestParseLine:
    def test_parses_header_fields(self):
        ev = tlp.parse_line(1, END_OF_CALL)
        assert ev is not None
        assert ev.timestamp == datetime(2026, 7, 16, 14, 0, 47)
        assert ev.category == "End of Call"
        assert ev.subtype == "End of Call"
        assert ev.kind == "End of Call - End of Call"

    def test_parses_nested_blocks(self):
        ev = tlp.parse_line(1, END_OF_CALL)
        assert ev.get("CALL", "Universal Call # (lower comp)") == "83317"
        assert ev.get("CALL", "End Of Call Reason") == "Normal call clearing"

    def test_multiple_blocks_on_one_line(self):
        ev = tlp.parse_line(1, INTERCONNECT_BILLING)
        assert set(ev.blocks.keys()) == {"CALL", "INTERCONNECT", "PHONE NUMBER"}
        assert ev.get("INTERCONNECT", "Route #") == "1"
        assert ev.get("PHONE NUMBER", "Phone #") == "67805418"

    def test_missing_key_returns_default(self):
        ev = tlp.parse_line(1, END_OF_CALL)
        assert ev.get("CALL", "Nonexistent Key") == "n/a"
        assert ev.get("NO SUCH BLOCK", "x", default="fallback") == "fallback"

    @pytest.mark.parametrize("line", ["", "   ", "\n", "\r\n"])
    def test_blank_lines_return_none(self, line):
        assert tlp.parse_line(1, line) is None

    def test_banner_line_returns_none(self):
        assert tlp.parse_line(1, BANNER_LINE) is None

    def test_line_not_matching_grammar_returns_none(self):
        assert tlp.parse_line(1, "log.2026_07_16_09_00_00.txt") is None

    def test_line_no_is_preserved(self):
        ev = tlp.parse_line(42, END_OF_CALL)
        assert ev.line_no == 42

    def test_raw_is_preserved(self):
        ev = tlp.parse_line(1, END_OF_CALL)
        assert ev.raw == END_OF_CALL


class TestParseCompositeId:
    def test_full_composite_id(self):
        parsed = tlp.parse_composite_id('5217(0x1461) "5217" [Security Id=1]')
        assert parsed.decimal == "5217"
        assert parsed.hex == "0x1461"
        assert parsed.label == "5217"
        assert parsed.security_id == "1"

    def test_talkgroup_label_differs_from_decimal(self):
        parsed = tlp.parse_composite_id('100(0x64) "TN-ORG-95" [Security Id=1]')
        assert parsed.decimal == "100"
        assert parsed.label == "TN-ORG-95"

    def test_security_id_optional(self):
        parsed = tlp.parse_composite_id('100(0x64) "TN-ORG-95"')
        assert parsed is not None
        assert parsed.security_id is None

    def test_non_matching_value_returns_none(self):
        assert tlp.parse_composite_id("n/a") is None
        assert tlp.parse_composite_id("") is None


class TestIterEvents:
    def test_reads_utf16_with_bom(self, tmp_path: Path):
        content = END_OF_CALL + "\n" + START_OF_CALL_INDIVIDUAL + "\n"
        path = tmp_path / "utf16.txt"
        path.write_bytes(content.encode("utf-16"))
        events = list(tlp.iter_events(path))
        assert len(events) == 2
        assert events[0].kind == "End of Call - End of Call"
        assert events[1].kind == "Call Activity Update - Start of Call"

    def test_falls_back_to_utf8(self, tmp_path: Path):
        path = tmp_path / "utf8.txt"
        path.write_bytes(END_OF_CALL.encode("utf-8"))
        events = list(tlp.iter_events(path))
        assert len(events) == 1
        assert events[0].kind == "End of Call - End of Call"

    def test_skips_banners_and_blanks(self, tmp_path: Path):
        content = "\n".join([BANNER_LINE, "", END_OF_CALL, "   ", BANNER_LINE])
        path = tmp_path / "mixed.txt"
        path.write_bytes(content.encode("utf-8"))
        events = list(tlp.iter_events(path))
        assert len(events) == 1

    def test_group_call_and_non_billing_line_both_parse(self, tmp_path: Path):
        content = "\n".join([NON_BILLING_CONTROL_CHANNEL_UPDATE, START_OF_CALL_GROUP])
        path = tmp_path / "group.txt"
        path.write_bytes(content.encode("utf-8"))
        events = list(tlp.iter_events(path))
        assert len(events) == 2
        assert events[0].kind == "Control Channel Update - Site Info"
        assert events[1].get("CALL", "Type") == "Group Call"
