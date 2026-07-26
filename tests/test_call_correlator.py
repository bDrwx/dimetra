"""Unit tests for call_correlator.py: event filtering, per-call state accumulation,
duration() fallback logic, and dump_state/load_state round-tripping across a
simulated log-rotation boundary."""
from datetime import datetime

import pytest

import text_log_parser as tlp
from call_correlator import CallCorrelator, RawCall
from fixtures.sample_lines import (
    CALL_STATE_CHANGE_CONNECTED,
    END_OF_CALL,
    INTERCONNECT_BILLING,
    LOCATION_REGISTRATION,
    NON_BILLING_CONTROL_CHANNEL_UPDATE,
    START_OF_CALL_GROUP,
    START_OF_CALL_INDIVIDUAL,
    UNIT_REGISTRATION,
)

# The sampled Start-of-Call/Connected pair (call 83316) and the sampled billing/End
# pair (call 83317) come from different calls in the source log. Unify them under one
# id so tests can exercise a single call's full lifecycle end to end.
_CALL_ID = "83317"
_START = tlp.parse_line(1, START_OF_CALL_INDIVIDUAL.replace("83316", _CALL_ID))
_CONNECTED = tlp.parse_line(2, CALL_STATE_CHANGE_CONNECTED.replace("83316", _CALL_ID))
_BILLING = tlp.parse_line(3, INTERCONNECT_BILLING)
_END = tlp.parse_line(4, END_OF_CALL)


def test_non_billing_event_is_ignored():
    correlator = CallCorrelator()
    ev = tlp.parse_line(1, NON_BILLING_CONTROL_CHANNEL_UPDATE)
    assert correlator.feed(ev) is None
    assert correlator.open_calls == {}


def test_start_of_call_opens_a_call_but_returns_none():
    correlator = CallCorrelator()
    assert correlator.feed(_START) is None
    assert _CALL_ID in correlator.open_calls
    call = correlator.open_calls[_CALL_ID]
    assert call.start_ts == datetime(2026, 7, 16, 14, 0, 15)
    assert call.type_raw == "Individual Call"
    assert call.is_interconnect is True  # "Interconnect" substring in Radio Type Qualifier
    assert call.requester["Primary ID"] == '1335(0x537) "1335" [Security Id=1]'


def test_group_call_start_sets_type_and_not_interconnect():
    correlator = CallCorrelator()
    ev = tlp.parse_line(1, START_OF_CALL_GROUP)
    correlator.feed(ev)
    call_id = ev.get("CALL", "Universal Call # (lower comp)")
    call = correlator.open_calls[call_id]
    assert call.type_raw == "Group Call"
    assert call.is_interconnect is False


def test_state_change_sets_connect_ts_only_on_connect_marker():
    correlator = CallCorrelator()
    correlator.feed(_START)
    assert correlator.open_calls[_CALL_ID].connect_ts is None
    correlator.feed(_CONNECTED)
    assert correlator.open_calls[_CALL_ID].connect_ts == datetime(2026, 7, 16, 14, 0, 16)


def test_state_change_without_connect_marker_leaves_connect_ts_none():
    correlator = CallCorrelator()
    correlator.feed(_START)
    non_connect = tlp.parse_line(
        2,
        CALL_STATE_CHANGE_CONNECTED.replace("83316", _CALL_ID).replace(
            "INT Ring to Active", "INT Ringing"
        ),
    )
    correlator.feed(non_connect)
    assert correlator.open_calls[_CALL_ID].connect_ts is None


def test_connect_ts_is_not_overwritten_by_a_later_connect_event():
    correlator = CallCorrelator()
    correlator.feed(_START)
    correlator.feed(_CONNECTED)
    first_connect = correlator.open_calls[_CALL_ID].connect_ts
    later = tlp.parse_line(
        3, CALL_STATE_CHANGE_CONNECTED.replace("83316", _CALL_ID).replace(
            "14:00:16", "14:05:00"
        )
    )
    correlator.feed(later)
    assert correlator.open_calls[_CALL_ID].connect_ts == first_connect


def test_billing_packet_sets_duration_subscriber_and_phone():
    correlator = CallCorrelator()
    correlator.feed(_START)
    correlator.feed(_BILLING)
    call = correlator.open_calls[_CALL_ID]
    assert call.is_interconnect is True
    assert call.billing_duration_seconds == 30
    assert call.billing_subscriber["label"] == "5217"
    assert call.billing_direction == "Land to Mobile"
    assert call.route_number == "1"
    assert call.phone_number == "67805418"


def test_end_of_call_closes_and_returns_the_call():
    correlator = CallCorrelator()
    correlator.feed(_START)
    correlator.feed(_CONNECTED)
    correlator.feed(_BILLING)
    closed = correlator.feed(_END)
    assert isinstance(closed, RawCall)
    assert closed.complete is True
    assert closed.end_reason == "Normal call clearing"
    assert closed.call_id not in correlator.open_calls


def test_end_of_call_for_unseen_call_still_closes_with_defaults():
    """An End of Call whose Start was in an earlier, unprocessed file should still
    close cleanly (with start_seen=False), not raise."""
    correlator = CallCorrelator()
    closed = correlator.feed(_END)
    assert closed.complete is True
    assert closed.start_seen is False
    assert closed.start_ts is None


class TestRegistration:
    def test_location_registration_returns_a_complete_call_immediately(self):
        correlator = CallCorrelator()
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        closed = correlator.feed(ev)
        assert isinstance(closed, RawCall)
        assert closed.complete is True
        assert closed.is_registration is True
        assert correlator.open_calls == {}  # never touches _open

    def test_unit_registration_also_handled(self):
        correlator = CallCorrelator()
        ev = tlp.parse_line(1, UNIT_REGISTRATION)
        closed = correlator.feed(ev)
        assert closed.is_registration is True
        assert closed.registered_site == "8"
        assert closed.registered_unit["Operating Unit ID"] == '3741010(0x391552) "3741010" [Security Id=1]'

    def test_registration_timestamps_all_equal_event_timestamp(self):
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        closed = CallCorrelator().feed(ev)
        assert closed.start_ts == closed.connect_ts == closed.end_ts == ev.timestamp
        assert closed.duration() == 0.0

    def test_registration_site_extracted_from_requester_block(self):
        ev = tlp.parse_line(1, LOCATION_REGISTRATION)
        closed = CallCorrelator().feed(ev)
        assert closed.registered_site == "54"

    def test_registration_call_id_is_unique_per_line(self):
        ev1 = tlp.parse_line(10, LOCATION_REGISTRATION)
        ev2 = tlp.parse_line(11, LOCATION_REGISTRATION)
        closed1 = CallCorrelator().feed(ev1)
        closed2 = CallCorrelator().feed(ev2)
        assert closed1.call_id != closed2.call_id


class TestDuration:
    def test_prefers_billing_duration_over_timestamps(self):
        call = RawCall(
            call_id="1",
            start_ts=datetime(2026, 1, 1, 0, 0, 0),
            end_ts=datetime(2026, 1, 1, 0, 10, 0),
            billing_duration_seconds=5,
        )
        assert call.duration() == 5.0

    def test_falls_back_to_connect_to_end(self):
        call = RawCall(
            call_id="1",
            start_ts=datetime(2026, 1, 1, 0, 0, 0),
            connect_ts=datetime(2026, 1, 1, 0, 0, 10),
            end_ts=datetime(2026, 1, 1, 0, 0, 40),
        )
        assert call.duration() == 30.0

    def test_falls_back_to_start_to_end_when_never_connected(self):
        call = RawCall(
            call_id="1",
            start_ts=datetime(2026, 1, 1, 0, 0, 0),
            end_ts=datetime(2026, 1, 1, 0, 0, 40),
        )
        assert call.duration() == 40.0

    def test_none_when_no_end_ts(self):
        call = RawCall(call_id="1", start_ts=datetime(2026, 1, 1, 0, 0, 0))
        assert call.duration() is None

    def test_none_when_no_anchor_ts_either(self):
        call = RawCall(call_id="1", end_ts=datetime(2026, 1, 1, 0, 0, 0))
        assert call.duration() is None

    def test_clamped_to_zero_on_negative_span(self):
        call = RawCall(
            call_id="1",
            start_ts=datetime(2026, 1, 1, 0, 0, 40),
            end_ts=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert call.duration() == 0.0


class TestStatePersistence:
    def test_dump_and_load_round_trip(self):
        correlator = CallCorrelator()
        correlator.feed(_START)
        correlator.feed(_CONNECTED)
        blob = correlator.dump_state()

        restored = CallCorrelator()
        restored.load_state(blob)
        assert _CALL_ID in restored.open_calls
        restored_call = restored.open_calls[_CALL_ID]
        original_call = correlator.open_calls[_CALL_ID]
        assert restored_call.start_ts == original_call.start_ts
        assert restored_call.connect_ts == original_call.connect_ts
        assert restored_call.requester == original_call.requester

    def test_loaded_calls_have_start_seen_false(self):
        correlator = CallCorrelator()
        correlator.feed(_START)
        blob = correlator.dump_state()

        restored = CallCorrelator()
        restored.load_state(blob)
        assert restored.open_calls[_CALL_ID].start_seen is False

    def test_load_empty_blob_is_a_noop(self):
        correlator = CallCorrelator()
        correlator.load_state("")
        assert correlator.open_calls == {}

    def test_call_surviving_rotation_can_still_be_closed(self):
        """Simulates a call whose Start of Call was in file A; only Connected +
        Billing + End arrive in file B, after state is restored from A's checkpoint."""
        correlator_a = CallCorrelator()
        correlator_a.feed(_START)
        blob = correlator_a.dump_state()

        correlator_b = CallCorrelator()
        correlator_b.load_state(blob)
        correlator_b.feed(_CONNECTED)
        correlator_b.feed(_BILLING)
        closed = correlator_b.feed(_END)

        assert closed.complete is True
        assert closed.start_ts == datetime(2026, 7, 16, 14, 0, 15)
        assert closed.billing_duration_seconds == 30
