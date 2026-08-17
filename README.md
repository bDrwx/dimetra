# DXT text-log → FastCom Gcdr pipeline

## Files

- `text_log_parser.py` — decodes the UTF-16 DXT zone-controller log and tokenizes each
  line into a `LogEvent` (timestamp, category, subtype, nested `{block: {field: value}}`).
- `call_correlator.py` — state machine keyed by `Universal Call # (lower comp)`. Only
  four event kinds are billing-relevant (everything else — Control Channel Update,
  Site Monitor Update, Location Registration, Radio Status ACKs, ~95%+ of the log — is
  ignored). Emits a `RawCall` when an `End of Call` closes it. Persists still-open
  calls across log-file rotation via `dump_state`/`load_state`.
- `gcdr_models.py` — your `UserType`/`CallType`/`NumberType`/`Subscriber`/`Dvo`/`Gcdr`
  classes, unchanged, plus three new adapters for the text-log source:
  `TextSubscriber` (bypasses the BCD/hex number decoding, since text-log IDs are
  already plain), `TextInterface` (stand-in for `Interfacez`), `TextTermination`
  (maps `End Of Call Reason` strings to numeric codes).
- `gcdr_builder.py` — maps a closed `RawCall` onto a `Gcdr`. Every non-obvious
  decision has a comment explaining what it's based on.
- `fastcom_writer.py` — writes `Gcdr` rows via `Gcdr.__iter__` to a delimited file.
- `registration_store.py` — `Mobility Update - Location/Unit Registration` events
  aren't calls (no `Universal Call #`, no Start/End pair, one line is the whole
  record), so they never touch `call_correlator.py`/`gcdr_builder.py` at all. Instead,
  if `--registrations-db` is passed to `pipeline.py`, each one is recorded as-is (unit
  id, registered zone/site, registration type, mobility result) into a local SQLite
  `registrations` table, deduped on `(source_file, line_no)` so re-running against an
  already-processed file doesn't double-insert. What downstream processing actually
  needs from this isn't decided yet — see README below.
- `pipeline.py` — orchestration + checkpointing. Two modes:
  - `python pipeline.py path/to/log.txt [--registrations-db regs.sqlite3]` — one-off
    smoke test, prints a summary and sample rows, no CSV written.
  - `python pipeline.py --watch-dir DIR --out billing_export.csv [--registrations-db
    regs.sqlite3]` — batch mode: picks up new/rotated files, appends to the output
    CSV, tracks a JSON checkpoint so files aren't reprocessed and in-flight calls
    survive a rotation boundary. `--registrations-db` is independent of that
    checkpoint (registration rows are deduped by their own unique constraint instead)
    but still only written from files this run actually scans.

## Output row format (`Gcdr.__iter__`)

`fastcom_writer.write_gcdr_rows` writes each `Gcdr` as one CSV row via
`writer.writerow(list(gcdr))` -- so the row is exactly what `Gcdr.__iter__` yields, in
this order. Delimiter is `config.OUTPUT_DELIMITER` (`;`, placeholder), encoding is
`config.OUTPUT_ENCODING` (`utf-8`, placeholder) -- see "Still open" below.

| # | Field | Type | Format / example | Source |
|---|-------|------|-------------------|--------|
| 1 | Date/time | `str` | `"13:59:53 27.04.2018"` (`HH:MM:SS DD.MM.YYYY`) | `Gcdr.date` (connect time if known, else start time) |
| 2 | Call duration | `int` | seconds, e.g. `42` | `int(call_duration.total_seconds())` |
| 3 | Call type | `int` | `CallType` enum value, `1`-`8` | see table below |
| 4 | DVO switch | `int` | `0` / `1` | `Dvo.switch` -- always `0` here, no ДВО signal found in the text log |
| 5 | Abon A type | `int` | `UserType` enum value | type of the calling party (`abon_a.stype`) |
| 6 | DXT id | `str` | e.g. `"ZS-DXT-ID"` | `config.DXT_ID`, used verbatim (not the hex-joined `get_dxt_id` property, which isn't called here) |
| 7 | Abon B type | `int` | `UserType` enum value | type of the called party (`abon_b.stype`) |
| 8 | Interface in | `str` | interconnect `Route #`, else `"--"` | `str(if_in)` |
| 9 | Interface out | `str` | same as #8 for this pipeline | `str(if_out)` |
| 10 | Edge DXT id | `str` | `"--"` | `Dvo.edge_dxt_id` -- always the placeholder, not populated |
| 11 | Roaming DXT id | `str` | roaming partner id, else `"--"` | `Dvo.rouming_dxt_id`, set on `Local Zone ID` vs `Controlling Zone ID` mismatch when `config.ROAMING_BY_ZONE_MISMATCH` is on |
| 12 | Call termination | `str` | zero-padded 2-digit code, e.g. `"01"` | `f"{call_termination.value:02d}"` -- see `TextTermination` table below |
| 13 | Provider id | `int` | e.g. `45` | `config.PROVIDER_ID` |
| 14 | Abon A number | `str` | decimal ISSI/talkgroup id, or `"UNKNOWN"` | `abon_a.get_number()` |
| 15 | Abon A start location | `int` or `"0"` | site id, `"0"` if unknown | `_normalized_location(abon_a.start_location)` |
| 16 | Abon A end location | `int` or `"0"` | same value as #15 in this pipeline | no mid-call roaming tracking (see "Inferred" below) |
| 17 | Abon B number | `str` | same shape as #14 | `abon_b.get_number()` |
| 18 | Abon B start location | `int` or `"0"` | same shape as #15 | |
| 19 | Abon B end location | `int` or `"0"` | same value as #18 in this pipeline | |
| 20 | Call forwarding | `str` | `"--"` | `Dvo.call_forvarding` -- always the placeholder, not populated |

`CallType` values (column 3):

| Value | Name | Meaning |
|---|---|---|
| 1 | `outg` | not produced by this pipeline |
| 2 | `toctcc` | pure radio-to-radio, stays inside TCC (non-interconnect calls) |
| 3 | `tocoutg` | TCC out -> PSTN (`Mobile to Land`) |
| 4 | `ing` | not produced by this pipeline |
| 5 | `ingtcc` | PSTN in -> TCC (`Land to Mobile`) |
| 6 | `toc` | interconnect call with no recognized direction (fallback) |
| 7 | `sms` | never produced -- no SDS/short-data events in the sample log |
| 8 | `tcc` | not produced by this pipeline (see `_infer_call_type`) |

`UserType` values (columns 5 and 7): `1` = `inner` (radio), `2` = `outer` (PSTN/phone),
`3` = `group` (talkgroup), `9` = `unknown` (subscriber id couldn't be parsed).

`TextTermination` values (column 12, zero-padded): `01` normal call clearing, `02`
disconnect complete, `03` user requested disconnect, `04` Land to Mobile call grant
timer expired, `05` expiry of timer, `06` called party not reachable, `07` user busy,
`08` cause not defined/unknown, `99` unmapped reason (logged as a warning). These are
placeholders, not FastCom's real termination-code table -- see "Still open" below.

## I could not run this

The sandboxed shell in this session failed to start (VHDX error) for the whole
conversation, so none of this has actually been executed — only traced by hand against
the real sample lines pulled from your log via grep. Please run:

```
cd dxt_cdr
python pipeline.py log.2026_07_16_09_00_00.txt
```

and send me anything that errors or looks wrong in the printed sample rows. Things
most likely to need a fix on first real run: the `_BLOCK_RE` regex on a block body I
didn't personally see in full (some `TARGET` blocks for Group Calls, `SITE DETAILS` /
`GROUP DETAILS` blocks), and off-by-one issues in the header regex on lines I didn't
sample.

## What's derived vs. assumed vs. still unknown

**Derived directly from the log** (high confidence): `date`, `call_duration` (from the
Interconnect Billing packet when present, else End − Connect/Start timestamps),
`call_termination` reason text, `abon_a`/`abon_b` identifiers, interconnect direction
and phone number.

**Inferred, flagged in code comments as judgment calls**:
- `call_type` — the log has no equivalent to your `CallType` enum's trunk-routing
  semantics (`outg`/`toctcc`/`tocoutg`/`ing`/`ingtcc`/`toc`/`sms`/`tcc`), since those
  encode which physical interface (`IN_G`/`TCC`/`TOC`/`Out_G`) a call passed through.
  `gcdr_builder._infer_call_type` only distinguishes what the log *can* tell us: pure
  radio call → `toctcc`, PSTN-in → `ingtcc`, PSTN-out → `tocoutg`. `sms` is never
  produced — no SDS/short-data events appear in the sample at all.
- `if_in`/`if_out` — same gap. `TextInterface` renders the interconnect `Route #` when
  known, `"--"` otherwise. This is **not** the physical trunk-card interface index
  your `Interfacez`/`Tetra.Interface` binary path captures — there is nothing at that
  granularity in this log.
- Radio site → `start_location`/`end_location` — taken from `Affiliated Site` on the
  `REQUESTER`/`TARGET` blocks. Only the site at call *start* is available from this
  event; `end_location` is set equal to `start_location` rather than tracking
  mid-call roaming (your original `Subscriber.get_last_location` does this properly
  via a registration buffer, which needs "Mobility Update - Location Registration"
  events wired in — not done here).
- Roaming (`Dvo.rouming_dxt_id`) — set from `Local Zone ID` vs `Controlling Zone ID`
  mismatch on the call record, since that pattern showed up in the sample. Not
  confirmed against how FastCom actually wants roaming represented.
- Interconnect `abon_a`/`abon_b` assignment — for interconnect calls, built from the
  billing packet's `Subscriber ID` + `Phone #` + `Type` (Land to Mobile / Mobile to
  Land) directly, rather than the Start-of-Call `REQUESTER`/`TARGET` roles, since the
  actual dialed phone number only appears in the billing packet and the direction
  field states unambiguously who called whom.

**Still open / config placeholders (`config.py`)**:
- `dxt_id`, `provider_id` — deployment constants, not derivable from any log.
- `check_summ` — no CRC/checksum field exists anywhere in the sample log (searched the
  full file). Self-computed via `zlib.crc32` over the row for now. Need to know if
  FastCom expects a specific algorithm, or if this actually needs to come from a
  different DXT export.
- Output delimiter/encoding — guessed `;` / UTF-8, not confirmed against FastCom's
  import spec.
- Whether plain radio-to-radio calls should be billed at all, vs. interconnect-only
  (`config.BILL_RADIO_CALLS`, currently on).
- `TextTermination` codes — assigned 1–8 in the order the 8 reasons appeared in the
  sample (`Normal call clearing`, `Disconnect Complete`, `User requested disconnect`,
  `Land to Mobile Call Grant Timer Expired`, `Expiry of timer`, `Called party not
  reachable`, `User busy`, `Cause not defined or unknown`). These are **placeholders**,
  not FastCom's real termination-code table.
- `Dvo.switch` / `call_forvarding` / `edge_dxt_id` — no ДВО (supplementary service)
  signal was found in the sample log at all; left at defaults (`False`/`"--"`).
- `registration_store.py`'s schema — captures the fields visible in the sample
  Registration lines (unit id, registered zone/site, previous site, registration
  type, mobility result), but nothing has been decided yet about what "processing it
  later" actually needs (roaming history? last-known-site lookups? something else?),
  so treat the column list as a starting point, not a spec.
