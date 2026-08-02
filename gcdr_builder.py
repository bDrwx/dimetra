"""
gcdr_builder.py

Maps a completed RawCall (from call_correlator.py) onto a Gcdr instance, using
Andrey's Subscriber/Dvo/CallType/Gcdr classes (gcdr_models.py) plus the text-log
adapters (TextSubscriber, TextInterface, TextTermination).

Every non-obvious mapping decision is called out in a comment with what it's based on
and where it's a guess vs. read straight off the record. See README.md for the full
list of open questions this still needs answered.
"""
from __future__ import annotations

import logging
import zlib
from datetime import timedelta

import config
from call_correlator import RawCall
from gcdr_models import (
    CallType,
    Dvo,
    Gcdr,
    TextInterface,
    TextSubscriber,
    TextTermination,
    UserType,
)
from text_log_parser import parse_composite_id

logger = logging.getLogger(__name__)

LOCATION_UNKNOWN = 65535  # DXT's own "no location" sentinel; Gcdr._normalized_location
                           # turns this into "0" on output.


class IncompleteCallError(Exception):
    """Raised when a RawCall doesn't have enough data to become a Gcdr (routed to the
    exceptions file by pipeline.py instead of the main output)."""


def _site_to_location(value: str | None) -> int:
    if value is None or value in ("n/a", ""):
        return LOCATION_UNKNOWN
    try:
        return int(value)
    except ValueError:
        return LOCATION_UNKNOWN


def _infer_call_type(call: RawCall) -> CallType:
    """
    Best-effort mapping onto Andrey's CallType enum (outg/toctcc/tocoutg/ing/ingtcc/
    toc/sms/tcc), which encodes trunk-routing paths (e.g. IN_G -> TCC) through the
    switch's physical interfaces. The text log doesn't expose interface-level routing
    (that's the same gap as if_in/if_out -- see README.md), so this only distinguishes
    what the log *can* tell us: whether a call ever touched the PSTN, and which
    direction. 'sms' is never produced -- no SDS/short-data events were observed in the
    sample log at all.
    """
    if not call.is_interconnect:
        return CallType.tcc  # pure radio-to-radio, stays inside TCC, no gateway leg
    if call.billing_direction == "Land to Mobile":
        return CallType.ingtcc  # PSTN in -> TCC
    if call.billing_direction == "Mobile to Land":
        return CallType.tocoutg  # TCC out -> PSTN
    logger.warning("Interconnect call %s has no known direction, defaulting to toc",
                    call.call_id)
    return CallType.toc


def _build_radio_subscriber(raw_field: dict, stype: UserType, location: int) -> TextSubscriber:
    """
    raw_field is a REQUESTER or TARGET block dict from Start of Call. Radio identities
    show up under 'Primary ID' (REQUESTER) or 'Secondary ID' (TARGET) as a composite
    'NNNN(0xHEX) "label" [Security Id=N]' value; group calls' TARGET may use a
    different key entirely (talkgroup field name wasn't confirmed against a full
    sample record) -- fall back to scanning all values for a composite id if the
    known keys aren't present. Always emits the decimal id, not the label -- for
    individual radios the two are identical in every sample seen, but for group calls
    the label is the talkgroup's name (e.g. "Y-Balyk-ORG37"), not a number.
    """
    for key in ("Primary ID", "Secondary ID", "Group ID", "Target ID"):
        if key in raw_field:
            parsed = parse_composite_id(raw_field[key])
            if parsed:
                return TextSubscriber(
                    stype=stype,
                    number=parsed.decimal,
                    dxt_prefix={},
                    start_location=location,
                    end_location=location,
                )
    for value in raw_field.values():
        parsed = parse_composite_id(value)
        if parsed:
            return TextSubscriber(
                stype=stype,
                number=parsed.decimal,
                dxt_prefix={},
                start_location=location,
                end_location=location,
            )
    logger.warning("Could not find a subscriber id in block %r", raw_field)
    return TextSubscriber(
        stype=UserType.unknown,
        number="UNKNOWN",
        dxt_prefix={},
        start_location=LOCATION_UNKNOWN,
        end_location=LOCATION_UNKNOWN,
    )


def _build_interconnect_parties(call: RawCall) -> tuple[TextSubscriber, TextSubscriber]:
    """
    For interconnect calls, abon_a/abon_b are taken from the Interconnect Call Billing
    Info Packet directly (authoritative), not the Start of Call REQUESTER/TARGET --
    those describe call-setup *roles*, not necessarily "who dialed whom" for a PSTN
    leg, and the actual phone number only appears in the billing packet anyway.
    'Type' on the billing packet ("Land to Mobile" / "Mobile to Land") tells us the
    direction directly.
    """
    radio_label = call.billing_subscriber.get("label") or call.billing_subscriber.get("decimal", "UNKNOWN")
    radio_location = _site_to_location(call.requester.get("Affiliated Site"))
    radio = TextSubscriber(
        stype=UserType.inner,
        number=radio_label,
        dxt_prefix={},
        start_location=radio_location,
        end_location=radio_location,
    )
    phone = TextSubscriber(
        stype=UserType.outer,
        number=call.phone_number or "UNKNOWN",
        dxt_prefix={},
        start_location=LOCATION_UNKNOWN,
        end_location=LOCATION_UNKNOWN,
    )
    if call.billing_direction == "Land to Mobile":
        return phone, radio  # abon_a=caller(phone), abon_b=callee(radio)
    return radio, phone  # "Mobile to Land" (or unknown, defaulted): radio called out


def build_gcdr(call: RawCall) -> Gcdr:
    if not call.complete or call.end_ts is None:
        raise IncompleteCallError(f"call {call.call_id} has no End of Call")

    duration_seconds = call.duration()
    if duration_seconds is None:
        # Call was already open when this file started and we never saw its Start of
        # Call (true cross-file gap, not just cross-file *continuation* -- the
        # correlator's checkpointing handles the normal rotation case). Route to
        # exceptions instead of guessing a duration.
        raise IncompleteCallError(
            f"call {call.call_id} has no start_ts/connect_ts to anchor duration")

    anchor_ts = call.connect_ts or call.start_ts
    if anchor_ts is None:
        raise IncompleteCallError(f"call {call.call_id} has no usable timestamp")

    if call.is_interconnect:
        abon_a, abon_b = _build_interconnect_parties(call)
        if_in = TextInterface(call.route_number or "--")
        if_out = TextInterface(call.route_number or "--")
    else:
        caller_location = _site_to_location(call.requester.get("Affiliated Site"))
        callee_location = _site_to_location(call.target.get("Affiliated Site"))
        abon_a = _build_radio_subscriber(call.requester, UserType.inner, caller_location)
        callee_stype = UserType.group if call.type_raw == "Group Call" else UserType.inner
        abon_b = _build_radio_subscriber(call.target, callee_stype, callee_location)
        if_in = TextInterface("--")
        if_out = TextInterface("--")

    if (config.ROAMING_BY_ZONE_MISMATCH and call.local_zone_id != "n/a"
            and call.controlling_zone_id != "n/a"
            and call.local_zone_id != call.controlling_zone_id):
        dvo = Dvo(switch=False, rouming_dxt_id=call.controlling_zone_id)
    else:
        dvo = Dvo(switch=False)

    gcdr = Gcdr(
        dxt_id=config.DXT_ID,
        provider_id=config.PROVIDER_ID,
        date=anchor_ts,
        call_duration=timedelta(seconds=duration_seconds),
        abon_a=abon_a,
        abon_b=abon_b,
        if_in=if_in,
        if_out=if_out,
        call_termination=TextTermination.from_reason(call.end_reason),
        dvo=dvo,
        call_type=_infer_call_type(call),
        check_summ=0,
    )
    if config.SELF_COMPUTE_CHECKSUM:
        gcdr.check_summ = zlib.crc32("|".join(str(v) for v in gcdr).encode("utf-8"))
    return gcdr
