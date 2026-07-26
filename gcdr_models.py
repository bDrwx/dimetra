"""
gcdr_models.py

Andrey's original UserType / CallType / NumberType / Location / Subscriber / Dvo / Gcdr
classes, carried over as-is (so this is a drop-in replacement wherever those were
imported from), MINUS the parts that only make sense for the binary Kaitai CDR path:

  - Reg (wraps a binary Tetra.Reg struct via bcd_to_str/bcd_to_time -- not applicable,
    the text log's own "Mobility Update - Location Registration" events are plain text
    and don't need BCD decoding; not used by this pipeline)
  - The `utility.get_logger` import (that module isn't available here) -- replaced with
    stdlib `logging`.

Added for the text-log source (see bottom of file):

  - TextSubscriber(Subscriber): overrides get_number() to bypass the BCD/hex-encoded
    number-format parsing in Subscriber.get_number(), which expects DXT's internal
    binary-CDR number encoding ("^([A-Fa-f0-9]{2})(\\d)(\\d+)..."). The text log gives
    plain decimal ISSIs ("5217") and talkgroup labels ("TN-ORG-95") directly, so
    TextSubscriber.get_number() just returns the already-normalized string.
  - TextInterface: a stand-in for Interfacez (which wraps a binary Tetra.Interface --
    ui/pui_type/pui_index -- not present in the text log). Renders as the interconnect
    Route # when known, else "--". See README.md for why if_in/if_out can't be populated
    at the same granularity as the binary CDR path.
  - TextTermination: End Of Call Reason (free text in the log) mapped to numeric codes,
    since we don't have Tetra.Terminations without the Kaitai binary schema. Codes are
    PLACEHOLDERS -- see README.md.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, unique
from typing import DefaultDict, Dict, List, Optional

logger = logging.getLogger(__name__)


@unique
class UserType(Enum):
    """Тип абонента DXT: внутренний/внешний/групповой/тип не определен"""

    inner = 1
    outer = 2
    group = 3
    unknown = 9


@unique
class CallType(Enum):
    outg = 1
    toctcc = 2
    tocoutg = 3
    ing = 4
    ingtcc = 5
    toc = 6
    sms = 7
    tcc = 8
    reg = 9  # synthetic: Mobility Update - Location/Unit Registration, not a real call


@unique
class NumberType(Enum):
    PSTN = 0
    MSYSDN = 1
    NITSI = 2
    FSSN = 3
    UNK6 = 6
    UNK7 = 7
    UNK8 = 8
    PABX = 9


class Location:
    """Пара БС на которых зарегистрирован/был зарегистрирован абонент"""

    def __init__(self, crt=0, prev=0) -> None:
        self.crt, self.prev = crt, prev

    def __repr__(self) -> str:
        return "Location(cur={}. prev={})".format(self.crt, self.prev)

    def __iter__(self):
        yield self.crt
        yield self.prev


@dataclass
class Subscriber(object):
    """
    Абонент сети (радио/всс)
    stype: тип абонента (внешний/внутренний) относительно коммутатора Тетра
    number: телефонный номер абонента
    prefix: Пулл номеров выделенный для абонентов DXT 6883 7x-xx РНУ Нерюнгри
    start_location: номер БС в начале разговора (для внутренних абонентов)
    end_location: номер БС в конце разговора (для внутренних абонентов)
    isExist: Указывает на валидность абонента. При завершении вызова Terminations.bad_number
             устанавливается в False
    """

    stype: UserType
    number: str
    dxt_prefix: Dict[str, int]
    start_location: int
    end_location: int
    isExist: bool = field(default=True)

    NET_CODE = 6
    GROUP_CODE = 0

    def get_number(self) -> str:
        """
        Нормализует номер абонента анализируя тип абонента и состояние групп
        регулярного выражения. Это исходная логика для номеров, приходящих в
        DXT-internal encoded form (hex-length-byte + type-digit + digits) из
        бинарного CDR. Для текстового лога используйте TextSubscriber ниже --
        там номера уже приходят как обычные десятичные ISSI/talkgroup id и эта
        логика не применима.
        """
        user_number: Optional[re.Match[str]] = re.match(
            r"^([A-Fa-f0-9]{2})(\d)(\d+)", self.number)
        if user_number:
            phone_len = int(user_number.group(1), 16) - 1
            user_type = NumberType(int(user_number.group(2)))
            if user_type == NumberType.NITSI:
                phone_len = phone_len - 9
            dialed_digit = user_number.group(3)
        else:
            logger.error("Regexp not matched %s", self.number)
            return self.number

        match user_type:
            case NumberType.PSTN:
                if self.isExist and len(dialed_digit) < 8:
                    logger.warning("PSTN number %s to short", self.number)
                    return self._normalized_nitsi(dialed_digit, phone_len)
                return dialed_digit
            case NumberType.MSYSDN:
                if self.isExist and len(dialed_digit) < 8:
                    logger.warning("MSYSDN number %s to short", self.number)
                    return self._normalized_nitsi(dialed_digit, phone_len)
                return dialed_digit
            case NumberType.NITSI:
                nitsi: Optional[re.Match[str]] = re.match(
                    r"^(025000075)(\d+)", dialed_digit)
                if nitsi:
                    return self._normalized_nitsi(nitsi.group(2), phone_len)
                else:
                    logger.warning(f'Parsing error for NITSI {dialed_digit}')
                    return dialed_digit
            case NumberType.FSSN:
                logger.warning("Not processed FSSN for %s", self.number)
                return dialed_digit
            case NumberType.PABX:
                return dialed_digit
            case _:
                logger.warning("Something went wrong for %s", self.number)
                return dialed_digit
        return 'Unk number'

    def _normalized_nitsi(self, nitsi: str, len: int) -> str:
        match len:
            case 4:
                if self.stype == UserType.group:
                    return f"{self.GROUP_CODE}{nitsi}"
                else:
                    logger.warning("Number to short %s", nitsi)
                    net_prefix = self.dxt_prefix.get(' ')
                    return f"{self.NET_CODE}{net_prefix}{nitsi}"
            case 6:
                num: Optional[re.Match[str]] = re.match(
                    r"^(\d{2})(\d{4})", nitsi)
                if num:
                    net_prefix = self.dxt_prefix.get(num.group(1))
                    user_number = num.group(2)
                    match self.stype:
                        case UserType.group:
                            return f"{self.GROUP_CODE}{user_number}"
                        case _:
                            return f"{self.NET_CODE}{net_prefix}{user_number}"
                else:
                    logger.warning("Regexp erroro for 6 digit NITSI %s", nitsi)
                    return nitsi
            case 7:
                return f'{self.NET_CODE}{nitsi}'
            case _:
                if len != 8:
                    logger.warning("Unexpected phone length %i for %s", len, nitsi)
                return nitsi

    def get_location(self) -> int:
        if self.start_location == 65535:
            return 0
        return self.start_location

    def get_last_location(self, reg_buffer: DefaultDict[str, List], sd: datetime,
                           td: timedelta) -> None:
        if self.stype == UserType.inner:
            if td > timedelta(minutes=1):
                reg_by_abonent = reg_buffer.get(self.get_number())
                if reg_by_abonent:
                    new_list = [
                        reg for reg in reg_by_abonent
                        if reg.reg_at > sd and reg.reg_at <= sd + td
                    ]
                    if new_list:
                        logger.debug(f"""Roaming occured {self.get_number()}""")
                        self.location = new_list[-1].get_location
                    else:
                        self.end_location = self.start_location
                else:
                    self.end_location = self.start_location
            else:
                self.end_location = self.start_location

    def __str__(self):
        return f"{self.get_number()}".format(self)


@dataclass
class Dvo:
    """
    Дополнительные виды обслуживания
    switch: признак наличия дополнительного вида обслуживания
    call_forwarding: номер куда был переадресован вызов
    edge_dxt_id: идентификатор граничного коммутатора
    rouming_dxt_id: идентификатор роумингового партнера
    """

    switch: bool
    call_forvarding: str = "--"
    edge_dxt_id: str = "--"
    rouming_dxt_id: str = "--"


@dataclass
class Gcdr:
    """
    General call data record presentation.
    See original docstring from Andrey -- unchanged. call_termination is typed as
    TextTermination here (not Tetra.Terminations) since the module import is lazy
    (from __future__ import annotations), this only matters for static typing.
    """

    dxt_id: str
    provider_id: int
    date: datetime
    call_duration: timedelta
    abon_a: Subscriber
    abon_b: Subscriber
    if_in: Optional["TextInterface"]
    if_out: Optional["TextInterface"]
    call_termination: "TextTermination"
    dvo: Dvo
    call_type: CallType
    check_summ: int

    @property
    def get_dxt_id(self):
        return "".join([hex(i)[2:] for i in self.dxt_id])

    def _format_time(self):
        """Formating date string for FastCom requirenments: '13:59:53 27.04.2018'"""
        time = self.date.strftime("%H:%M:%S")
        date = self.date.strftime("%d.%m.%Y")
        return " ".join([time, date])

    def _normalized_location(self, location) -> str:
        """Request from OASR for back capability"""
        if location == 65535:
            return "0"
        return location

    def __iter__(self):
        return iter([
            self._format_time(),
            int(self.call_duration.total_seconds()),
            self.call_type.value,
            int(self.dvo.switch),
            self.abon_a.stype.value,
            self.dxt_id,
            self.abon_b.stype.value,
            str(self.if_in),
            str(self.if_out),
            self.dvo.edge_dxt_id,
            self.dvo.rouming_dxt_id,
            "{0:02d}".format(self.call_termination.value),
            self.provider_id,
            self.abon_a.get_number(),
            self._normalized_location(self.abon_a.start_location),
            self._normalized_location(self.abon_a.end_location),
            self.abon_b.get_number(),
            self._normalized_location(self.abon_b.start_location),
            self._normalized_location(self.abon_b.end_location),
            self.dvo.call_forvarding,
        ])

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, Gcdr):
            return False
        return self.check_summ == __o.check_summ

    def __str__(self) -> str:
        return f"{self.date}{self.call_type}{self.abon_a}{self.abon_b}{self.call_termination}"


# ----------------------------------------------------------------------------------------
# Text-log-source adapters (new -- not from Andrey's original code)
# ----------------------------------------------------------------------------------------


class TextSubscriber(Subscriber):
    """
    Subscriber built from text-log fields. The text log's subscriber identifiers are
    already plain decimal ISSIs ("5217") or talkgroup labels ("TN-ORG-95") -- not the
    DXT-internal hex-length-byte encoded numbers that Subscriber.get_number() expects
    from the binary CDR path. Bypass that parsing entirely here.
    """

    def get_number(self) -> str:
        return self.number


class TextInterface:
    """
    Stand-in for Interfacez (which wraps a binary Tetra.Interface: ui/pui_type/pui_index --
    a physical trunk-card interface index). The text zone-controller log has no equivalent
    at that granularity. For interconnect calls we at least know the logical INTERCONNECT
    Route #; for radio-internal calls there's nothing, so this renders as "--".
    See README.md for why this is a known gap, not a guess dressed up as data.
    """

    def __init__(self, label: str = "--") -> None:
        self.label = label or "--"

    def __str__(self) -> str:
        return self.label


@unique
class TextTermination(Enum):
    """
    End Of Call Reason (free text in the log) -> numeric code. These are PLACEHOLDER
    codes assigned in the order the 8 reasons were observed in the sample log -- they
    are NOT confirmed against whatever numeric termination-code table FastCom actually
    expects. Swap in the real table before this touches production billing output.
    """

    normal_call_clearing = 1
    disconnect_complete = 2
    user_requested_disconnect = 3
    land_to_mobile_grant_timer_expired = 4
    expiry_of_timer = 5
    called_party_not_reachable = 6
    user_busy = 7
    cause_not_defined_or_unknown = 8
    registration = 9  # synthetic marker for Registration rows -- not a real End Of Call
                        # Reason string, see call_correlator._on_registration
    other_unmapped = 99

    @classmethod
    def from_reason(cls, reason: str) -> "TextTermination":
        mapping = {
            "Normal call clearing": cls.normal_call_clearing,
            "Disconnect Complete": cls.disconnect_complete,
            "User requested disconnect": cls.user_requested_disconnect,
            "Land to Mobile Call Grant Timer Expired": cls.land_to_mobile_grant_timer_expired,
            "Expiry of timer": cls.expiry_of_timer,
            "Called party not reachable": cls.called_party_not_reachable,
            "User busy": cls.user_busy,
            "Cause not defined or unknown": cls.cause_not_defined_or_unknown,
            "Registration": cls.registration,
        }
        result = mapping.get(reason.strip())
        if result is None:
            logger.warning("Unmapped End Of Call Reason %r -- add it to TextTermination", reason)
            return cls.other_unmapped
        return result
