"""Unit tests for gcdr_builder.py: RawCall -> Gcdr mapping, including the
inference/fallback logic the README flags as judgment calls (call_type, roaming,
subscriber-id lookup) and the IncompleteCallError branches in build_gcdr."""
from datetime import datetime

import pytest

import config
import text_log_parser as tlp
from call_correlator import CallCorrelator, RawCall
from gcdr_builder import (
    IncompleteCallError,
    _build_interconnect_parties,
    _build_radio_subscriber,
    _build_registration_parties,
    _infer_call_type,
    _site_to_location,
    build_gcdr,
)
from gcdr_models import CallType, TextSubscriber, UserType
from fixtures.sample_lines import (
    CALL_STATE_CHANGE_CONNECTED,
    END_OF_CALL,
    INTERCONNECT_BILLING,
    LOCATION_REGISTRATION,
    START_OF_CALL_GROUP,
    START_OF_CALL_INDIVIDUAL,
)

_CALL_ID = "83317"
_START = tlp.parse_line(1, START_OF_CALL_INDIVIDUAL.replace("83316", _CALL_ID))
_CONNECTED = tlp.parse_line(2, CALL_STATE_CHANGE_CONNECTED.replace("83316", _CALL_ID))
_BILLING = tlp.parse_line(3, INTERCONNECT_BILLING)
_END = tlp.parse_line(4, END_OF_CALL)


def build_full_interconnect_call() -> RawCall:
    correlator = CallCorrelator()
    correlator.feed(_START)
    correlator.feed(_CONNECTED)
    correlator.feed(_BILLING)
    return correlator.feed(_END)


def build_full_group_call() -> RawCall:
    correlator = CallCorrelator()
    correlator.feed(tlp.parse_line(1, START_OF_CALL_GROUP))
    group_id = tlp.parse_line(1, START_OF_CALL_GROUP).get("CALL", "Universal Call # (lower comp)")
    end = tlp.parse_line(
        2, END_OF_CALL.replace("83317", group_id).replace("Normal call clearing", "User busy")
    )
    return correlator.feed(end)


class TestInferCallType:
    def test_registration_is_reg(self):
        call = RawCall(call_id="1", is_registration=True)
        assert _infer_call_type(call) is CallType.reg

    def test_non_interconnect_is_tcc(self):
        call = RawCall(call_id="1", is_interconnect=False)
        assert _infer_call_type(call) is CallType.tcc

    def test_land_to_mobile_is_ingtcc(self):
        call = RawCall(call_id="1", is_interconnect=True, billing_direction="Land to Mobile")
        assert _infer_call_type(call) is CallType.ingtcc

    def test_mobile_to_land_is_tocoutg(self):
        call = RawCall(call_id="1", is_interconnect=True, billing_direction="Mobile to Land")
        assert _infer_call_type(call) is CallType.tocoutg

    def test_interconnect_with_unknown_direction_defaults_to_toc(self):
        call = RawCall(call_id="1", is_interconnect=True, billing_direction="")
        assert _infer_call_type(call) is CallType.toc


class TestSiteToLocation:
    @pytest.mark.parametrize("value", [None, "n/a", ""])
    def test_missing_values_are_unknown(self, value):
        assert _site_to_location(value) == 65535

    def test_numeric_string_converts_to_int(self):
        assert _site_to_location("68") == 68

    def test_non_numeric_string_is_unknown(self):
        assert _site_to_location("not-a-number") == 65535


class TestBuildRadioSubscriber:
    def test_known_key_primary_id_from_real_requester_block(self):
        sub = _build_radio_subscriber(_START.blocks["REQUESTER"], UserType.inner, 68)
        assert sub.number == "1335"
        assert sub.stype == UserType.inner
        assert sub.start_location == 68
        assert sub.end_location == 68

    def test_known_key_secondary_id_from_real_group_target_block(self):
        group_start = tlp.parse_line(1, START_OF_CALL_GROUP)
        sub = _build_radio_subscriber(group_start.blocks["TARGET"], UserType.group, 68)
        assert sub.number == "Y-Balyk-ORG37"
        assert sub.stype == UserType.group

    def test_falls_back_to_scanning_all_values_when_known_keys_absent(self):
        raw_field = {"Some Unexpected Key": '100(0x64) "TN-ORG-95" [Security Id=1]'}
        sub = _build_radio_subscriber(raw_field, UserType.group, 68)
        assert sub.number == "TN-ORG-95"

    def test_totally_unknown_block_returns_unknown_placeholder(self):
        sub = _build_radio_subscriber({"Affiliated Zone": "n/a"}, UserType.inner, 68)
        assert sub.stype == UserType.unknown
        assert sub.number == "UNKNOWN"
        assert sub.start_location == 65535
        assert sub.end_location == 65535


class TestBuildInterconnectParties:
    def test_land_to_mobile_puts_phone_as_caller(self):
        call = RawCall(
            call_id="1",
            billing_direction="Land to Mobile",
            billing_subscriber={"label": "5217", "decimal": "5217"},
            phone_number="67805418",
            requester={"Affiliated Site": "68"},
        )
        abon_a, abon_b = _build_interconnect_parties(call)
        assert abon_a.number == "67805418"
        assert abon_a.stype == UserType.outer
        assert abon_b.number == "5217"
        assert abon_b.stype == UserType.inner
        assert abon_b.start_location == 68

    def test_mobile_to_land_puts_radio_as_caller(self):
        call = RawCall(
            call_id="1",
            billing_direction="Mobile to Land",
            billing_subscriber={"label": "5217", "decimal": "5217"},
            phone_number="67805418",
            requester={"Affiliated Site": "68"},
        )
        abon_a, abon_b = _build_interconnect_parties(call)
        assert abon_a.number == "5217"
        assert abon_b.number == "67805418"


class TestBuildRegistrationParties:
    def test_composite_site_number_and_radio_id(self):
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        call = CallCorrelator().feed(ev)
        abon_a, abon_b = _build_registration_parties(call)
        assert abon_a.number == "NUR UMN 5451"
        assert abon_a.stype == UserType.inner
        assert abon_a.start_location == 54
        assert abon_b.number == f"{config.DXT_ID}54"
        assert abon_b.stype == UserType.outer
        assert abon_b.start_location == 54

    def test_unparseable_unit_id_falls_back_to_unknown(self):
        call = RawCall(call_id="1", registered_unit={"Operating Unit ID": "n/a"}, registered_site="7")
        abon_a, _ = _build_registration_parties(call)
        assert abon_a.number == "UNKNOWN"


class TestBuildGcdrErrors:
    def test_incomplete_call_raises(self):
        call = RawCall(call_id="1", complete=False)
        with pytest.raises(IncompleteCallError):
            build_gcdr(call)

    def test_complete_but_no_end_ts_raises(self):
        call = RawCall(call_id="1", complete=True, end_ts=None)
        with pytest.raises(IncompleteCallError):
            build_gcdr(call)

    def test_end_of_call_with_no_start_seen_and_no_billing_duration_raises(self):
        """Simulates an End of Call whose Start of Call was in an earlier,
        unprocessed file: no billing packet either, so duration() itself is None."""
        correlator = CallCorrelator()
        closed = correlator.feed(_END)
        with pytest.raises(IncompleteCallError, match="no start_ts/connect_ts"):
            build_gcdr(closed)

    def test_billing_duration_present_but_no_anchor_timestamp_raises(self):
        """Distinct from the case above: a billing packet arrived (so duration()
        returns a value), but Start of Call was still never seen, so there's no
        connect_ts/start_ts to anchor the record's date on."""
        correlator = CallCorrelator()
        correlator.feed(_BILLING)
        closed = correlator.feed(_END)
        assert closed.billing_duration_seconds == 30
        assert closed.start_ts is None
        with pytest.raises(IncompleteCallError, match="no usable timestamp"):
            build_gcdr(closed)


class TestBuildGcdrSuccess:
    def test_interconnect_call_end_to_end(self):
        call = build_full_interconnect_call()
        gcdr = build_gcdr(call)
        assert gcdr.call_type is CallType.ingtcc
        assert gcdr.abon_a.number == "67805418"
        assert gcdr.abon_b.number == "5217"
        assert str(gcdr.if_in) == "1"
        assert str(gcdr.if_out) == "1"
        assert gcdr.date == datetime(2026, 7, 16, 14, 0, 16)  # anchored on connect_ts
        assert int(gcdr.call_duration.total_seconds()) == 30  # from billing packet
        assert gcdr.check_summ != 0  # SELF_COMPUTE_CHECKSUM defaults True

    def test_group_call_end_to_end(self):
        call = build_full_group_call()
        gcdr = build_gcdr(call)
        assert gcdr.call_type is CallType.tcc
        assert gcdr.abon_a.stype == UserType.inner
        assert gcdr.abon_b.stype == UserType.group
        assert gcdr.abon_a.number == "3917"
        assert gcdr.abon_b.number == "Y-Balyk-ORG37"
        assert str(gcdr.if_in) == "--"
        assert str(gcdr.if_out) == "--"

    def test_roaming_detected_on_zone_mismatch(self, monkeypatch):
        monkeypatch.setattr(config, "ROAMING_BY_ZONE_MISMATCH", True)
        call = build_full_interconnect_call()
        call.local_zone_id = "1"
        call.controlling_zone_id = "2"
        gcdr = build_gcdr(call)
        assert gcdr.dvo.rouming_dxt_id == "2"

    def test_no_roaming_when_zones_match(self):
        call = build_full_interconnect_call()
        call.local_zone_id = "1"
        call.controlling_zone_id = "1"
        gcdr = build_gcdr(call)
        assert gcdr.dvo.rouming_dxt_id == "--"

    def test_roaming_heuristic_disabled_via_config(self, monkeypatch):
        monkeypatch.setattr(config, "ROAMING_BY_ZONE_MISMATCH", False)
        call = build_full_interconnect_call()
        call.local_zone_id = "1"
        call.controlling_zone_id = "2"
        gcdr = build_gcdr(call)
        assert gcdr.dvo.rouming_dxt_id == "--"

    def test_checksum_not_computed_when_disabled_via_config(self, monkeypatch):
        monkeypatch.setattr(config, "SELF_COMPUTE_CHECKSUM", False)
        call = build_full_interconnect_call()
        gcdr = build_gcdr(call)
        assert gcdr.check_summ == 0

    def test_registration_end_to_end(self):
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        call = CallCorrelator().feed(ev)
        gcdr = build_gcdr(call)
        assert gcdr.call_type is CallType.reg
        assert gcdr.abon_a.number == "NUR UMN 5451"
        assert gcdr.abon_a.stype == UserType.inner
        assert gcdr.abon_b.number == f"{config.DXT_ID}54"
        assert gcdr.abon_b.stype == UserType.outer
        assert int(gcdr.call_duration.total_seconds()) == 0
        assert str(gcdr.if_in) == "--"
        assert str(gcdr.if_out) == "--"
