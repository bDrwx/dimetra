"""
pipeline.py

Orchestrates the full run: discover log files -> parse -> correlate calls -> build
Gcdr records -> write FastCom output. Also handles checkpointing so calls that span a
log-rotation boundary aren't lost, and files aren't reprocessed on the next run.

Usage:
    # one-off, against a single file (e.g. the sample log), prints a summary:
    python pipeline.py path/to/log.2026_07_16_09_00_00.txt

    # batch mode: process every *.txt in a directory not yet in the checkpoint,
    # write/append normalized output, advance the checkpoint:
    python pipeline.py --watch-dir /path/to/dxt/logs --out /path/to/billing_export.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

from call_correlator import CallCorrelator, RawCall
from gcdr_builder import IncompleteCallError, build_gcdr
from gcdr_models import Gcdr
from fastcom_writer import write_gcdr_rows
from text_log_parser import iter_events

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pipeline")


def process_file(path: Path, correlator: CallCorrelator) -> Tuple[List[Gcdr], List[Tuple[RawCall, str]]]:
    """
    Run one log file through the correlator. Returns (gcdr_records, exceptions), where
    exceptions is [(raw_call, reason), ...] for calls that closed but couldn't be
    turned into a Gcdr (e.g. no usable start timestamp because Start of Call was in an
    earlier, unprocessed file).
    """
    records: List[Gcdr] = []
    exceptions: List[Tuple[RawCall, str]] = []
    n_events = 0
    for event in iter_events(path):
        n_events += 1
        closed_call = correlator.feed(event)
        if closed_call is None:
            continue
        try:
            records.append(build_gcdr(closed_call))
        except IncompleteCallError as e:
            exceptions.append((closed_call, str(e)))
    logger.info("%s: %d events, %d calls closed, %d incomplete, %d still open",
                path.name, n_events, len(records) + len(exceptions), len(exceptions),
                len(correlator.open_calls))
    return records, exceptions


# --------------------------------------------------------------------------------------
# Checkpoint (processed files + in-flight call state, for cross-rotation continuity)
# --------------------------------------------------------------------------------------


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"processed_files": [], "open_calls": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def run_batch(watch_dir: Path, out_path: Path, checkpoint_path: Path,
              exceptions_path: Path) -> None:
    checkpoint = load_checkpoint(checkpoint_path)
    processed = set(checkpoint["processed_files"])

    correlator = CallCorrelator()
    correlator.load_state(checkpoint.get("open_calls", ""))

    new_files = sorted(
        p for p in watch_dir.glob("*.txt") if p.name not in processed
    )
    if not new_files:
        logger.info("No new log files in %s", watch_dir)
        return

    all_records: List[Gcdr] = []
    all_exceptions: List[Tuple[RawCall, str]] = []
    for path in new_files:
        records, exceptions = process_file(path, correlator)
        all_records.extend(records)
        all_exceptions.extend(exceptions)
        processed.add(path.name)

    written = write_gcdr_rows(all_records, out_path, append=out_path.exists())
    logger.info("Wrote %d Gcdr rows to %s", written, out_path)

    if all_exceptions:
        with exceptions_path.open("a", encoding="utf-8") as f:
            for call, reason in all_exceptions:
                f.write(json.dumps({"call_id": call.call_id, "reason": reason,
                                     "raw": call.to_json()}, ensure_ascii=False) + "\n")
        logger.warning("%d calls routed to exceptions file %s", len(all_exceptions),
                        exceptions_path)

    checkpoint["processed_files"] = sorted(processed)
    checkpoint["open_calls"] = correlator.dump_state()
    save_checkpoint(checkpoint_path, checkpoint)
    logger.info("%d calls still open, carried into next run", len(correlator.open_calls))


def run_single_file_smoke_test(path: Path) -> None:
    """No checkpoint, no output file -- just parse+correlate+build and print a summary,
    for sanity-checking the pipeline against a sample log."""
    correlator = CallCorrelator()
    records, exceptions = process_file(path, correlator)

    print(f"\n{len(records)} Gcdr records built, {len(exceptions)} exceptions, "
          f"{len(correlator.open_calls)} calls still open at end of file.\n")

    print("-- sample Gcdr rows --")
    for gcdr in records[:10]:
        print(list(gcdr))

    if exceptions:
        print("\n-- sample exceptions --")
        for call, reason in exceptions[:5]:
            print(call.call_id, reason)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="single log file to smoke-test")
    parser.add_argument("--watch-dir", type=Path, help="directory of rotated log files")
    parser.add_argument("--out", type=Path, default=Path("billing_export.csv"))
    parser.add_argument("--checkpoint", type=Path, default=Path("pipeline_checkpoint.json"))
    parser.add_argument("--exceptions", type=Path, default=Path("exceptions.jsonl"))
    args = parser.parse_args()

    if args.watch_dir:
        run_batch(args.watch_dir, args.out, args.checkpoint, args.exceptions)
    elif args.file:
        run_single_file_smoke_test(Path(args.file))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
