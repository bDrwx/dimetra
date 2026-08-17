"""
call_correlator.py

Groups the billing-relevant events emitted by text_log_parser into complete per-call
records, keyed by "Universal Call # (lower comp)" -- the id that appears on every event
belonging to the same call, from Start of Call through End of Call.

Only four event kinds carry billing information; everything else (Control Channel
Update, Site Monitor Update, Location Registration, Radio Status ACKs, ...) is ignored
here -- roughly 95%+ of a DXT log by line count.

    Call Activity Update - Start of Call            call setup: type, caller, callee, site
    Call Activity Update - Call State Change         "...Connected" marks true talk start
    Interconnect Call Billing Info Packet - MBX Info Type
                                                      authoritative duration + phone number
                                                      for PSTN-interconnected calls only
    End of Call - End of Call                        teardown timestamp + reason

Radio-to-radio calls (Individual/Group, no interconnect leg) never get a billing info
packet, so their duration is computed from timestamps instead (connect-to-end if a
Connected state change was seen, else start-to-end).

Calls can span a log-rotation boundary (files run ~50 min in the sample). This module
does not read files itself -- see pipeline.py for that -- but it exposes dump_state /
load_state so open calls survive a restart or a file-rotation edge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from text_log_parser import LogEvent, parse_composite_id

# --------------------------------------------------------------------------------------

START_OF_CALL = "Call Activity Update - Start of Call"
CALL_STATE_CHANGE = "Call Activity Update - Call State Change"
INTERCONNECT_BILLING = "Interconnect Call Billing Info Packet - MBX Info Type"
END_OF_CALL = "End of Call - End of Call"

BILLING_RELEVANT_KINDS = {START_OF_CALL, CALL_STATE_CHANGE, INTERCONNECT_BILLING, END_OF_CALL}

# Substring that marks the state-change event where a call actually becomes active
# (as opposed to ringing/setup). Observed values include "INT Ring to Active",
# "INT Connected" -- any transition mentioning Connected or Active is treated as connect.
_CONNECT_MARKERS = ("Connected", "Active")


@dataclass
class RawCall:
    """
    Everything gathered about one call, in source-format terms (not yet mapped onto
    Gcdr/Subscriber/CallType). gcdr_builder.py turns this into a Gcdr instance.
    """

    call_id: str
    type_raw: str = ""  # "Individual Call" / "Group Call"
    radio_type_qualifier: str = ""  # e.g. "(Interconnect,Interconnect ring state,Astro call)"
    start_ts: datetime | None = None
    connect_ts: datetime | None = None
    end_ts: datetime | None = None
    end_reason: str = ""
    local_zone_id: str = "n/a"
    controlling_zone_id: str = "n/a"
    source_zone_id: str = "n/a"
    source_site_id: str = "n/a"
    requester: dict[str, str] = field(default_factory=dict)  # raw REQUESTER block
    target: dict[str, str] = field(default_factory=dict)  # raw TARGET block
    is_interconnect: bool = False
    billing_duration_seconds: int | None = None
    billing_subscriber: dict[str, str] = field(default_factory=dict)  # composite id fields
    billing_direction: str = ""  # "Land to Mobile" / "Mobile to Land"
    phone_number: str = ""
    route_number: str = ""
    complete: bool = False  # True once an End of Call closed it
    start_seen: bool = True  # False if this call was already open when the file began

    def duration(self) -> float | None:
        """Best billing duration in seconds: authoritative packet, else timestamps."""
        if self.billing_duration_seconds is not None:
            return float(self.billing_duration_seconds)
        if self.end_ts is None:
            return None
        anchor = self.connect_ts or self.start_ts
        if anchor is None:
            return None
        return max(0.0, (self.end_ts - anchor).total_seconds())

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        for k in ("start_ts", "connect_ts", "end_ts"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_json(cls, d: dict) -> RawCall:
        d = dict(d)
        for k in ("start_ts", "connect_ts", "end_ts"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        return cls(**d)


class CallCorrelator:
    def __init__(self) -> None:
        self._open: dict[str, RawCall] = {}

    # -- persistence, for calls spanning a log-file rotation ---------------------------

    def dump_state(self) -> str:
        return json.dumps({cid: c.to_json() for cid, c in self._open.items()})

    def load_state(self, blob: str) -> None:
        if not blob:
            return
        data = json.loads(blob)
        for cid, cdict in data.items():
            call = RawCall.from_json(cdict)
            call.start_seen = False
            self._open[cid] = call

    @property
    def open_calls(self) -> dict[str, RawCall]:
        return self._open

    # -- main entry point ---------------------------------------------------------------

    def feed(self, event: LogEvent) -> RawCall | None:
        """
        Feed one parsed LogEvent in. Returns a finalized RawCall when this event closes
        a call (End of Call), else None. Non-billing-relevant events are ignored
        immediately (cheap check on event.kind).
        """
        if event.kind not in BILLING_RELEVANT_KINDS:
            return None

        call_block = event.blocks.get("CALL", {})
        call_id = call_block.get("Universal Call # (lower comp)")
        if not call_id:
            return None

        if event.kind == START_OF_CALL:
            self._on_start(event, call_id, call_block)
            return None
        if event.kind == CALL_STATE_CHANGE:
            self._on_state_change(event, call_id, call_block)
            return None
        if event.kind == INTERCONNECT_BILLING:
            self._on_billing(event, call_id, call_block)
            return None
        if event.kind == END_OF_CALL:
            return self._on_end(event, call_id, call_block)

        return None  # pragma: no cover

    # -- handlers -------------------------------------------------------------------

    def _get_or_open(self, call_id: str) -> RawCall:
        call = self._open.get(call_id)
        if call is None:
            call = RawCall(call_id=call_id, start_seen=False)
            self._open[call_id] = call
        return call

    def _on_start(self, event: LogEvent, call_id: str, call_block: dict[str, str]) -> None:
        call = self._get_or_open(call_id)
        call.start_ts = event.timestamp
        call.start_seen = True
        call.type_raw = call_block.get("Type", "")
        call.radio_type_qualifier = call_block.get("Radio Type Qualifier", "")
        call.local_zone_id = call_block.get("Local Zone ID", "n/a")
        call.controlling_zone_id = call_block.get("Controlling Zone ID", "n/a")
        call.source_zone_id = call_block.get("Source Zone ID", "n/a")
        call.source_site_id = call_block.get("Source Site ID", "n/a")
        call.requester = event.blocks.get("REQUESTER", {})
        call.target = event.blocks.get("TARGET", {})
        if "Interconnect" in call.radio_type_qualifier:
            call.is_interconnect = True

    def _on_state_change(self, event: LogEvent, call_id: str, call_block: dict[str, str]) -> None:
        call = self._get_or_open(call_id)
        transition = call_block.get("State Transition Field", "")
        if call.connect_ts is None and any(marker in transition for marker in _CONNECT_MARKERS):
            call.connect_ts = event.timestamp

    def _on_billing(self, event: LogEvent, call_id: str, call_block: dict[str, str]) -> None:
        call = self._get_or_open(call_id)
        call.is_interconnect = True
        dur = call_block.get("Duration in Seconds")
        if dur is not None:
            try:
                call.billing_duration_seconds = int(dur)
            except ValueError:
                pass
        sub_id = call_block.get("Subscriber ID", "")
        parsed = parse_composite_id(sub_id)
        if parsed:
            call.billing_subscriber = {
                "decimal": parsed.decimal,
                "hex": parsed.hex,
                "label": parsed.label,
                "security_id": parsed.security_id or "",
            }
        call.billing_direction = call_block.get("Type", "")
        call.route_number = event.blocks.get("INTERCONNECT", {}).get("Route #", "")
        call.phone_number = event.blocks.get("PHONE NUMBER", {}).get("Phone #", "")

    def _on_end(self, event: LogEvent, call_id: str, call_block: dict[str, str]) -> RawCall:
        call = self._get_or_open(call_id)
        call.end_ts = event.timestamp
        call.end_reason = call_block.get("End Of Call Reason", "n/a")
        call.complete = True
        self._open.pop(call_id, None)
        return call
