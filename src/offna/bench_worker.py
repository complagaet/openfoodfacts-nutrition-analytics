import json
import sys
import time
from pathlib import Path

import polars as pl

from offna.engines import ENGINES
from offna.measure import peak_rss_mib


def run(engine: str, source: Path, output_dir: Path) -> dict:
    start = time.perf_counter()
    country, group = ENGINES[engine](source)
    seconds = time.perf_counter() - start
    output_dir.mkdir(parents=True, exist_ok=True)
    country.to_parquet(output_dir / f"{engine}_country.parquet")
    group.to_parquet(output_dir / f"{engine}_food_group.parquet")
    return {
        "engine": engine,
        "seconds": round(seconds, 3),
        "peak_rss_mib": round(peak_rss_mib(), 1),
        "polars_threads": pl.thread_pool_size(),
        "country_rows": len(country),
        "food_group_rows": len(group),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m offna.bench_worker <engine> <source> <output_dir>", file=sys.stderr)
        return 2
    engine, source, output_dir = argv
    if engine not in ENGINES:
        print(f"unknown engine {engine!r}; expected {sorted(ENGINES)}", file=sys.stderr)
        return 2
    print(json.dumps(run(engine, Path(source), Path(output_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
