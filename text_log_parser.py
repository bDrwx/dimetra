"""
text_log_parser.py

Tokenizer for Dimetra DXT zone-controller text logs (e.g. log.2026_07_16_09_00_00.txt).

Log line grammar (one event per line):

    [MM/DD/YY HH:MM:SS] <Category> - <Subtype> : <BLOCK> {k = v ; k = v ; ...} <BLOCK2> {...} ...

Example:

    [07/16/26 14:00:47] Interconnect Call Billing Info Packet - MBX Info Type : CALL {Universal
    Call # (lower comp) = 83317 ; Controlling Zone ID = 1 ; Duration in Seconds = 0 ; Subscriber
    ID = 5217(0x1461) "5217" [Security Id=1] ; Type = Land to Mobile} INTERCONNECT {Route # = 1}
    PHONE NUMBER {Phone Encoding = n/a ; Phone # = 67805418}

Files are UTF-16 encoded (observed with a BOM). Most lines are operational noise (Control
Channel Update, Security Class Update, Site Monitor Update, Location Registration, Radio
Status ACKs, ...) that this module still parses generically -- filtering to billing-relevant
event types happens one layer up, in call_correlator.py.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------------------
# Line grammar
# --------------------------------------------------------------------------------------

_HEADER_RE = re.compile(
    r"^\[(?P<ts>\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})\]\s*"
    r"(?P<category>.+?)\s*-\s*(?P<subtype>.+?)\s*:\s*(?P<body>.*)$"
)

# Block name: a run of upper-case words (with spaces/'/'/#/' allowed), followed by {..}.
# Block bodies never nest braces in this log format, so a non-greedy [^{}]* is safe.
_BLOCK_RE = re.compile(r"([A-Z][A-Z0-9 /#']*?)\s*\{([^{}]*)\}")

_TIMESTAMP_FMT = "%m/%d/%y %H:%M:%S"


@dataclass
class LogEvent:
    """One parsed line from the DXT text log."""

    line_no: int
    timestamp: datetime
    category: str
    subtype: str
    blocks: dict[str, dict[str, str]] = field(default_factory=dict)
    raw: str = ""

    @property
    def kind(self) -> str:
        """'Category - Subtype', the key used to whitelist billing-relevant events."""
        return f"{self.category} - {self.subtype}"

    def get(self, block: str, key: str, default: str = "n/a") -> str:
        return self.blocks.get(block, {}).get(key, default)


def _parse_block_body(body: str) -> dict[str, str]:
    """Split a block's ' k = v ; k = v ' content into a dict. Tolerant of stray fields."""
    fields: dict[str, str] = {}
    for chunk in body.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, _, val = chunk.partition("=")
            fields[key.strip()] = val.strip()
        else:
            # Rare stray token with no '=' -- keep it under its own key so nothing is lost.
            fields[chunk] = ""
    return fields


def parse_line(line_no: int, line: str) -> LogEvent | None:
    """Parse a single decoded log line. Returns None for separator/banner/blank lines."""
    line = line.rstrip("\n\r")
    if not line.strip():
        return None
    m = _HEADER_RE.match(line)
    if not m:
        # Banner lines ("====...", "log.2026_07_16_...") and any line that doesn't match
        # the event grammar are skipped rather than raising -- the log intersperses
        # rotation banners with real events.
        return None

    ts = datetime.strptime(m.group("ts"), _TIMESTAMP_FMT)
    blocks: dict[str, dict[str, str]] = {}
    for block_name, block_body in _BLOCK_RE.findall(m.group("body")):
        blocks[block_name.strip()] = _parse_block_body(block_body)

    return LogEvent(
        line_no=line_no,
        timestamp=ts,
        category=m.group("category").strip(),
        subtype=m.group("subtype").strip(),
        blocks=blocks,
        raw=line,
    )


# --------------------------------------------------------------------------------------
# File-level iteration
# --------------------------------------------------------------------------------------


def _read_decoded_lines(path: Path) -> Iterator[str]:
    """
    Yield decoded text lines from a DXT log file, handling the UTF-16 encoding
    (with BOM) that the sample file used, and falling back to UTF-8 if a given
    file isn't UTF-16 (some DXT configurations emit plain ASCII/UTF-8 logs).
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") or b"\x00" in raw[:4000]:
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        yield line


def iter_events(path: Path) -> Iterator[LogEvent]:
    """Iterate parsed LogEvents from one log file, in file order."""
    for line_no, line in enumerate(_read_decoded_lines(path), start=1):
        event = parse_line(line_no, line)
        if event is not None:
            yield event


# --------------------------------------------------------------------------------------
# Composite field helper
# --------------------------------------------------------------------------------------

# Matches values like:  5217(0x1461) "5217" [Security Id=1]
#                        1335(0x537) "1335" [Security Id=1]
_COMPOSITE_ID_RE = re.compile(
    r"^(?P<dec>\d+)\((?P<hex>0x[0-9A-Fa-f]+)\)\s*\"(?P<label>[^\"]*)\"\s*(?:\[Security Id=(?P<sec>[^\]]*)\])?$"
)


@dataclass
class CompositeId:
    decimal: str
    hex: str
    label: str
    security_id: str | None


def parse_composite_id(value: str) -> CompositeId | None:
    """
    Decompose a 'NNNN(0xHEX) "label" [Security Id=N]' style field value, used for
    subscriber/talkgroup identifiers throughout the log (Subscriber ID, Primary ID,
    Individual, Affiliated ID, ...). Returns None if value doesn't match (e.g. 'n/a').
    """
    m = _COMPOSITE_ID_RE.match(value.strip())
    if not m:
        return None
    return CompositeId(
        decimal=m.group("dec"),
        hex=m.group("hex"),
        label=m.group("label"),
        security_id=m.group("sec"),
    )


if __name__ == "__main__":
    import sys

    p = Path(sys.argv[1])
    count = 0
    kinds: dict[str, int] = {}
    for ev in iter_events(p):
        count += 1
        kinds[ev.kind] = kinds.get(ev.kind, 0) + 1
    print(f"{count} events parsed from {p}")
    for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {n:6d}  {kind}")
