"""
fastcom_writer.py

Writes Gcdr records to a delimited file in FastCom's expected column order (i.e.
exactly the order Gcdr.__iter__ yields -- see gcdr_models.py for the field list).
Delimiter/encoding come from config.py; both are placeholders pending confirmation
of FastCom's actual import spec.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

import config
from gcdr_models import Gcdr


def write_gcdr_rows(records: Iterable[Gcdr], out_path: Path, append: bool = False) -> int:
    mode = "a" if append else "w"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open(mode, newline="", encoding=config.OUTPUT_ENCODING) as f:
        writer = csv.writer(f, delimiter=config.OUTPUT_DELIMITER)
        for gcdr in records:
            writer.writerow(list(gcdr))
            count += 1
    return count
