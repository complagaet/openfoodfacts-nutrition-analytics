import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from offna.config import VALID_GRADES

CODE_PATTERN = re.compile(r"^[0-9A-Za-z_.-]{1,64}$")
MAX_STITCH_PIECES = 64
GRADE_VALUES = {*VALID_GRADES, "unknown", "not-applicable", ""}


@dataclass
class ParseStats:
    physical_lines: int = 0
    empty_lines: int = 0
    records: int = 0
    stitched_records: int = 0
    rejected_fragments: int = 0
    implausible_records: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class _Pending:
    fields: list[str]
    pieces: int


def _merge(pending: _Pending, line: str) -> _Pending:
    parts = line.split("\t")
    merged = [*pending.fields[:-1], pending.fields[-1] + "\n" + parts[0], *parts[1:]]
    return _Pending(merged, pending.pieces + 1)


def _start(line: str) -> _Pending:
    return _Pending(line.split("\t"), 1)


def _accept(pending: _Pending, stats: ParseStats) -> list[str]:
    stats.records += 1
    if pending.pieces > 1:
        stats.stitched_records += 1
    return pending.fields


def iter_validated_records(
    lines: Iterable[str], expected_fields: int, stats: ParseStats
) -> Iterator[list[str]]:
    pending: _Pending | None = None
    for raw in lines:
        stats.physical_lines += 1
        line = raw.rstrip("\r\n")
        if pending is None and line == "":
            stats.empty_lines += 1
            continue
        candidate = _start(line) if pending is None else _merge(pending, line)
        width = len(candidate.fields)
        if width == expected_fields:
            pending = None
            yield _accept(candidate, stats)
            continue
        if width < expected_fields and candidate.pieces < MAX_STITCH_PIECES:
            pending = candidate
            continue
        stats.rejected_fragments += 1
        if pending is None:
            continue
        pending = None
        restart = _start(line)
        if len(restart.fields) == expected_fields:
            yield _accept(restart, stats)
        elif len(restart.fields) < expected_fields:
            pending = restart
        else:
            stats.rejected_fragments += 1
    if pending is not None:
        stats.rejected_fragments += 1


def is_plausible(code: str, grade: str) -> bool:
    return bool(CODE_PATTERN.match(code)) and grade in GRADE_VALUES


def iter_lines(path: Path) -> Iterator[str]:
    with path.open("rb") as handle:
        for raw in handle:
            yield raw.decode("utf-8", errors="replace")


def read_header(path: Path) -> list[str]:
    return next(iter_lines(path)).rstrip("\r\n").split("\t")


def iter_csv_chunks(path: Path, chunk_rows: int, stats: ParseStats) -> Iterator[pd.DataFrame]:
    header = read_header(path)
    code_at, grade_at = header.index("code"), header.index("nutriscore_grade")
    buffer: list[list[str]] = []
    lines = iter_lines(path)
    next(lines)
    for fields in iter_validated_records(lines, len(header), stats):
        if not is_plausible(fields[code_at], fields[grade_at]):
            stats.implausible_records += 1
            continue
        buffer.append(fields)
        if len(buffer) >= chunk_rows:
            yield pd.DataFrame(buffer, columns=header)
            buffer = []
    if buffer:
        yield pd.DataFrame(buffer, columns=header)
