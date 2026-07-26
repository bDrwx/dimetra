"""Unit tests for gcdr_models.py.

Covers the original binary-CDR Subscriber.get_number() decoding (kept for parity/
documentation of existing behavior), the TextSubscriber bypass that exists precisely
because plain decimal ISSIs can accidentally match that binary decoding, and the
Gcdr/TextTermination adapters used by the text-log pipeline.
"""
from datetime import datetime, timedelta

import pytest

from gcdr_models import (
    Dvo,
    Gcdr,
    NumberType,
    Subscriber,
    TextInterface,
    TextSubscriber,
    TextTermination,
    UserType,
)


def make_subscriber(number: str, stype=UserType.inner, dxt_prefix=None, is_exist=True) -> Subscriber:
    return Subscriber(
        stype=stype,
        number=number,
        dxt_prefix=dxt_prefix or {},
        start_location=1,
        end_location=1,
        isExist=is_exist,
    )


class TestSubscriberGetNumberPSTN:
    def test_long_dialed_digit_returned_as_is(self):
        # "0A" -> hex 10, phone_len=9 ; "0" -> PSTN ; 8-digit dialed number (>=8, no rewrite)
        sub = make_subscriber("0A012345678")
        assert sub.get_number() == "12345678"

    def test_short_dialed_digit_routes_through_normalized_nitsi_case4(self):
        # "05" -> hex 5, phone_len=4 ; "0" -> PSTN ; 7 digits (<8) -> _normalized_nitsi(.., 4)
        sub = make_subscriber("0501234567", dxt_prefix={" ": 77})
        assert sub.get_number() == "6771234567"

    def test_short_dialed_digit_group_type_uses_group_code(self):
        sub = make_subscriber("0501234567", stype=UserType.group)
        assert sub.get_number() == "01234567"


class TestSubscriberGetNumberMSYSDN:
    def test_behaves_like_pstn_branch(self):
        # "05" -> phone_len=4 ; "1" -> MSYSDN ; 7 digits (<8)
        sub = make_subscriber("0511234567", stype=UserType.group)
        assert sub.get_number() == "01234567"


class TestSubscriberGetNumberNITSI:
    def test_matching_prefix_strips_and_normalizes(self):
        # "11" -> hex 17, phone_len=16, then -9 for NITSI = 7 ; "2" -> NITSI
        # dialed_digit must start with the fixed "025000075" prefix.
        sub = make_subscriber("1120250000751234567")
        assert sub.get_number() == "61234567"

    def test_non_matching_prefix_returns_dialed_digit_unchanged(self):
        sub = make_subscriber("112" + "999999")
        assert sub.get_number() == "999999"


class TestSubscriberGetNumberOtherTypes:
    def test_fssn_returns_dialed_digit_unchanged(self):
        # "0A" -> phone_len=9 ; "3" -> FSSN
        sub = make_subscriber("0A312345")
        assert sub.get_number() == "12345"

    def test_pabx_returns_dialed_digit_unchanged(self):
        # "0A" -> phone_len=9 ; "9" -> PABX
        sub = make_subscriber("0A912345")
        assert sub.get_number() == "12345"

    def test_unmapped_number_type_falls_to_catch_all_branch(self):
        # "0A" -> phone_len=9 ; "6" -> UNK6, not one of the explicitly-handled cases
        sub = make_subscriber("0A612345")
        assert sub.get_number() == "12345"

    def test_group_digit_outside_numbertype_enum_raises(self):
        """NumberType only defines 0,1,2,3,6,7,8,9. Digits 4/5 in that position are
        unmapped and NumberType(4) raises ValueError uncaught -- documenting current
        behavior, not asserting it's desirable."""
        sub = make_subscriber("0A412345")
        with pytest.raises(ValueError):
            sub.get_number()


class TestSubscriberGetNumberFallback:
    def test_non_hex_leading_chars_fail_regex_and_return_number_unchanged(self):
        # "TN" isn't valid hex, so the header regex never matches at all.
        sub = make_subscriber("TN-ORG-95")
        assert sub.get_number() == "TN-ORG-95"

    def test_plain_decimal_issi_is_silently_mangled_by_binary_decoding(self):
        """This is exactly why TextSubscriber exists: a plain text-log ISSI like
        "5217" incidentally matches the binary-CDR grammar ("52" as hex, "1" as
        MSYSDN, "7" as the dialed digit) and comes out wrong on the base class."""
        sub = make_subscriber("5217")
        assert sub.get_number() == "7"


class TestTextSubscriber:
    def test_bypasses_binary_decoding_for_plain_issi(self):
        sub = TextSubscriber(
            stype=UserType.inner, number="5217", dxt_prefix={}, start_location=1, end_location=1
        )
        assert sub.get_number() == "5217"

    def test_bypasses_binary_decoding_for_talkgroup_label(self):
        sub = TextSubscriber(
            stype=UserType.group, number="TN-ORG-95", dxt_prefix={}, start_location=1, end_location=1
        )
        assert sub.get_number() == "TN-ORG-95"


class TestTextInterface:
    def test_renders_given_label(self):
        assert str(TextInterface("1")) == "1"

    def test_defaults_to_dashes(self):
        assert str(TextInterface()) == "--"
        assert str(TextInterface("")) == "--"
        assert str(TextInterface(None)) == "--"


class TestTextTermination:
    @pytest.mark.parametrize(
        "reason,expected",
        [
            ("Normal call clearing", TextTermination.normal_call_clearing),
            ("Disconnect Complete", TextTermination.disconnect_complete),
            ("User requested disconnect", TextTermination.user_requested_disconnect),
            ("Land to Mobile Call Grant Timer Expired",
             TextTermination.land_to_mobile_grant_timer_expired),
            ("Expiry of timer", TextTermination.expiry_of_timer),
            ("Called party not reachable", TextTermination.called_party_not_reachable),
            ("User busy", TextTermination.user_busy),
            ("Cause not defined or unknown", TextTermination.cause_not_defined_or_unknown),
            ("Registration", TextTermination.registration),
        ],
    )
    def test_known_reasons_map_correctly(self, reason, expected):
        assert TextTermination.from_reason(reason) is expected

    def test_unknown_reason_maps_to_other_unmapped(self):
        assert TextTermination.from_reason("Some new reason never seen before") is (
            TextTermination.other_unmapped
        )

    def test_reason_is_stripped_before_lookup(self):
        assert TextTermination.from_reason("  Normal call clearing  ") is (
            TextTermination.normal_call_clearing
        )


def make_gcdr(**overrides) -> Gcdr:
    abon_a = TextSubscriber(
        stype=UserType.outer, number="67805418", dxt_prefix={}, start_location=65535, end_location=65535
    )
    abon_b = TextSubscriber(
        stype=UserType.inner, number="5217", dxt_prefix={}, start_location=68, end_location=68
    )
    defaults = dict(
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
        call_type=__import__("gcdr_models").CallType.ingtcc,
        check_summ=12345,
    )
    defaults.update(overrides)
    return Gcdr(**defaults)


class TestGcdrIter:
    def test_field_order_and_values(self):
        gcdr = make_gcdr()
        row = list(gcdr)
        assert row == [
            "14:00:47 16.07.2026",
            30,
            5,  # CallType.ingtcc.value
            0,  # int(dvo.switch)
            2,  # abon_a.stype (outer)
            "ZS-DXT-ID",
            1,  # abon_b.stype (inner)
            "1",  # if_in
            "1",  # if_out
            "--",  # dvo.edge_dxt_id
            "--",  # dvo.rouming_dxt_id
            "01",  # call_termination, zero-padded
            45,
            "67805418",
            "0",  # 65535 normalized to "0"
            "0",
            "5217",
            68,
            68,
            "--",  # dvo.call_forvarding
        ]

    def test_normalized_location_passes_through_non_sentinel_values_as_int(self):
        gcdr = make_gcdr()
        assert gcdr._normalized_location(68) == 68
        assert gcdr._normalized_location(65535) == "0"


class TestGcdrEquality:
    def test_equal_when_checksums_match_even_if_other_fields_differ(self):
        a = make_gcdr(check_summ=999, provider_id=1)
        b = make_gcdr(check_summ=999, provider_id=2)
        assert a == b

    def test_not_equal_when_checksums_differ(self):
        a = make_gcdr(check_summ=1)
        b = make_gcdr(check_summ=2)
        assert a != b

    def test_not_equal_to_non_gcdr_object(self):
        assert make_gcdr() != "not a gcdr"
