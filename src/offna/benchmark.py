import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path

import pandas as pd
import polars as pl
import psutil
import pyarrow as pa

import offna
from offna.config import CORE_NUTRIENTS, SEED, Profile
from offna.engines import BENCH_COLUMNS, ENGINES, frames_match
from offna.etl import scan_processed
from offna.measure import frame_memory_mib, peak_rss_mib, write_json

REFERENCE_ENGINE = "polars_lazy"
FULL_DATA_ENGINES: list[str] = ["pandas_chunked_optimised", "polars_lazy"]
WORKER_TIMEOUT_SECONDS = 1800


def write_subset(profile: Profile, rows: int) -> dict:
    products = (
        scan_processed(profile)
        .select(BENCH_COLUMNS)
        .with_columns(pl.col(CORE_NUTRIENTS).cast(pl.Float64), pl.col("food_group").cast(pl.String))
        .collect(engine="streaming")
    )
    subset = products.sample(n=min(rows, products.height), seed=SEED)
    del products
    profile.bench_subset_path.parent.mkdir(parents=True, exist_ok=True)
    subset.write_parquet(profile.bench_subset_path, compression="zstd")
    return {
        "rows": subset.height,
        "sampling": f"uniform random sample without replacement, seed {SEED}",
        "file_mib": round(profile.bench_subset_path.stat().st_size / 2**20, 2),
    }


def worker_command(engine: str, source: Path, output_dir: Path) -> list[str]:
    source_root = str(Path(offna.__file__).resolve().parents[1])
    bootstrap = (
        f"import sys; sys.path.insert(0, {source_root!r}); "
        "from offna.bench_worker import main; raise SystemExit(main(sys.argv[1:]))"
    )
    return [sys.executable, "-I", "-c", bootstrap, engine, str(source), str(output_dir)]


def run_worker(engine: str, source: Path, output_dir: Path) -> dict:
    command = worker_command(engine, source, output_dir)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=WORKER_TIMEOUT_SECONDS, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{engine} failed: {completed.stderr.strip()[-2000:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def summarise_runs(runs: list[dict]) -> dict:
    times = [run["seconds"] for run in runs]
    return {
        "engine": runs[0]["engine"],
        "runs": len(runs),
        "first_run_s": times[0],
        "median_s": round(statistics.median(times), 3),
        "min_s": round(min(times), 3),
        "peak_rss_mib_max": max(run["peak_rss_mib"] for run in runs),
        "polars_threads": runs[0]["polars_threads"],
    }


def compare_outputs(output_dir: Path, engines: list[str]) -> dict:
    checks = {}
    for table in ["country", "food_group"]:
        reference = pd.read_parquet(output_dir / f"{REFERENCE_ENGINE}_{table}.parquet")
        for engine in engines:
            if engine == REFERENCE_ENGINE:
                continue
            other = pd.read_parquet(output_dir / f"{engine}_{table}.parquet")
            equal, max_abs_diff = frames_match(reference, other)
            checks[f"{engine}_vs_{REFERENCE_ENGINE}_{table}"] = {"equal": equal, "max_abs_diff": max_abs_diff}
    return checks


def benchmark_source(source: Path, engines: list[str], repeats: int, output_dir: Path) -> dict:
    summaries = []
    for engine in engines:
        runs = [run_worker(engine, source, output_dir) for _ in range(repeats)]
        summaries.append(summarise_runs(runs))
    return {"engines": summaries, "equality": compare_outputs(output_dir, engines)}


def dataframe_size_comparison(source: Path) -> dict:
    default = pd.read_parquet(source)
    optimised = default.assign(
        food_group=default["food_group"].astype("category"),
        **{column: default[column].astype("float32") for column in default.select_dtypes("float64")},
    )
    return {
        "rows": len(default),
        "default_mib": round(frame_memory_mib(default), 1),
        "optimised_mib": round(frame_memory_mib(optimised), 1),
    }


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_gib": round(psutil.virtual_memory().total / 2**30, 1),
        "pandas": pd.__version__,
        "polars": pl.__version__,
        "pyarrow": pa.__version__,
        "file_cache": "warm after first run; first_run_s reported separately",
    }


def markdown_table(results: dict) -> str:
    lines = [
        "| input | engine | rows | median s | min s | first run s | peak RSS MiB |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, block in results.items():
        for row in block["engines"]:
            lines.append(
                f"| {label} | {row['engine']} | {block['rows']:,} | {row['median_s']} | {row['min_s']} "
                f"| {row['first_run_s']} | {row['peak_rss_mib_max']} |"
            )
    return "\n".join(lines) + "\n"


def run_benchmark(profile: Profile, subset_rows: int, repeats: int, include_full: bool) -> dict:
    subset = write_subset(profile, subset_rows)
    bench_dir = profile.output_dir / "benchmark"
    results = {
        "subset": {
            "rows": subset["rows"],
            **benchmark_source(profile.bench_subset_path, list(ENGINES), repeats, bench_dir / "subset"),
        }
    }
    if include_full:
        rows = scan_processed(profile).select(pl.len()).collect().item()
        results["full"] = {
            "rows": rows,
            **benchmark_source(profile.processed_dir, FULL_DATA_ENGINES, repeats, bench_dir / "full"),
        }
    report = {
        "profile": profile.name,
        "tasks": [
            "T1: product-country pairs and missing share of 8 core nutrients per sales country",
            "T2: products and mean of 8 core nutrients per food group (nulls ignored)",
        ],
        "subset_file": subset,
        "dataframe_size": dataframe_size_comparison(profile.bench_subset_path),
        "environment": environment(),
        "results": results,
        "orchestrator_peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "benchmark.json", report)
    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "benchmark_table.md").write_text(markdown_table(results), encoding="utf-8")
    return report
