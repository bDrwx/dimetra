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
  radio call → `tcc`, PSTN-in → `ingtcc`, PSTN-out → `tocoutg`. `sms` is never
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
