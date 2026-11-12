import json
import resource
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

MIB = 2**20


def peak_rss_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = MIB if sys.platform == "darwin" else 1024
    return peak / divisor


def frame_memory_mib(frame: pd.DataFrame) -> float:
    return float(frame.memory_usage(deep=True).sum()) / MIB


@dataclass
class Stopwatch:
    seconds: float = 0.0
    laps: dict[str, float] = field(default_factory=dict)


@contextmanager
def timed(watch: Stopwatch, label: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    watch.laps[label] = round(elapsed, 3)
    watch.seconds += elapsed


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"{path} not found; run the stage that produces it first") from error
