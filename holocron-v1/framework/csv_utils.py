"""Shared CSV helpers for Holocron."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Iterable


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _set_max_csv_field_size() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_set_max_csv_field_size()


def count_csv_rows(path: Path) -> int:
    with open(path, encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))
