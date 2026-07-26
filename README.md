# DXT text-log → FastCom Gcdr pipeline

## Files

- `text_log_parser.py` — decodes the UTF-16 DXT zone-controller log and tokenizes each
  line into a `LogEvent` (timestamp, category, subtype, nested `{block: {field: value}}`).
- `call_correlator.py` — state machine keyed by `Universal Call # (lower comp)`. Six
  event kinds are billing-relevant (everything else — Control Channel Update, Site
  Monitor Update, Radio Status ACKs, ... — is ignored). Emits a `RawCall` when an
  `End of Call` closes it. Persists still-open calls across log-file rotation via
  `dump_state`/`load_state`. `Mobility Update - Location/Unit Registration` events are
  handled separately: each is a complete single-line record (no Universal Call #, no
  Start/End pair), so `_on_registration` builds and returns an already-complete
  `RawCall` immediately instead of tracking it as open state.
- `gcdr_models.py` — your `UserType`/`CallType`/`NumberType`/`Subscriber`/`Dvo`/`Gcdr`
  classes, unchanged, plus three new adapters for the text-log source:
  `TextSubscriber` (bypasses the BCD/hex number decoding, since text-log IDs are
  already plain), `TextInterface` (stand-in for `Interfacez`), `TextTermination`
  (maps `End Of Call Reason` strings to numeric codes).
- `gcdr_builder.py` — maps a closed `RawCall` onto a `Gcdr`. Every non-obvious
  decision has a comment explaining what it's based on.
- `fastcom_writer.py` — writes `Gcdr` rows via `Gcdr.__iter__` to a delimited file.
- `pipeline.py` — orchestration + checkpointing. Two modes:
  - `python pipeline.py path/to/log.txt` — one-off smoke test, prints a summary and
    sample rows, no output file written.
  - `python pipeline.py --watch-dir DIR --out billing_export.csv` — batch mode: picks
    up new/rotated files, appends to the output CSV, tracks a JSON checkpoint so
    files aren't reprocessed and in-flight calls survive a rotation boundary.

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
  via a registration buffer, which would consume the Registration events described
  below — not wired up that way here, they're emitted as their own rows instead).
- Registration events (`Mobility Update - Location Registration` / `Unit
  Registration`) are modeled as a pseudo-call: `abon_a` is the registering radio
  (`UNIT.Operating Unit ID`), `abon_b` is a synthetic "site" number built by
  concatenating `config.DXT_ID` with `REQUESTER.Registered Site` directly (e.g.
  `"ZS-DXT-ID54"` for site 54), `call_duration` is always 0, and `call_type` uses a
  new `CallType.reg = 9` member added for this (none of the existing 8 values mean
  "registration"). `abon_b.stype` is `UserType.outer`. **None of this — the `reg`
  call type value, the `DXT_ID`+site concatenation format, or the `outer` stype — is
  confirmed against anything FastCom or OASR actually expects for registration rows.**
  Confirm before this touches production billing output. See
  `gcdr_builder._build_registration_parties`.
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
