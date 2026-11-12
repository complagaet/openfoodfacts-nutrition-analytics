from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from offna.csv_reader import CODE_PATTERN, GRADE_VALUES, ParseStats, iter_csv_chunks, read_header
from offna.etl import optimise_pandas_dtypes
from offna.measure import Stopwatch, frame_memory_mib, peak_rss_mib, timed, write_json

CHUNK_ROWS = 5000
NUMERIC_SUFFIXES: tuple[str, ...] = ("_100g", "_serving", "_n", "_t")


def numeric_columns(header: list[str]) -> list[str]:
    return [name for name in header if name.endswith(NUMERIC_SUFFIXES) or name in {"completeness", "nova_group"}]


def arrow_schema(header: list[str]) -> pa.Schema:
    numeric = set(numeric_columns(header))
    return pa.schema([(name, pa.float32() if name in numeric else pa.string()) for name in header])


def typed_chunk(chunk: pd.DataFrame, numeric: list[str]) -> pd.DataFrame:
    chunk = chunk.replace("", None)
    chunk[numeric] = chunk[numeric].apply(pd.to_numeric, errors="coerce").astype("float32")
    return chunk


def naive_parse(path: Path) -> dict:
    frame = pd.read_csv(path, sep="\t", dtype=str, on_bad_lines="skip", low_memory=False, keep_default_na=False)
    grades = frame["nutriscore_grade"]
    codes = frame["code"]
    return {
        "rows": len(frame),
        "columns": frame.shape[1],
        "rows_with_invalid_grade": int((~grades.isin(GRADE_VALUES)).sum()),
        "rows_with_implausible_code": int((~codes.str.match(CODE_PATTERN)).sum()),
    }


def validated_parse(path: Path, output: Path) -> tuple[dict, pd.DataFrame]:
    header = read_header(path)
    numeric = numeric_columns(header)
    stats = ParseStats()
    frames = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(output, arrow_schema(header), compression="zstd") as writer:
        for chunk in iter_csv_chunks(path, CHUNK_ROWS, stats):
            typed = typed_chunk(chunk, numeric)
            writer.write_table(pa.Table.from_pandas(typed, schema=arrow_schema(header), preserve_index=False))
            frames.append(chunk)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=header)
    return {"columns": len(header), **stats.as_dict()}, raw


def wide_memory(raw: pd.DataFrame) -> dict:
    default = raw.replace("", None).infer_objects()
    numeric = numeric_columns(list(raw.columns))
    default[numeric] = default[numeric].apply(pd.to_numeric, errors="coerce")
    optimised = optimise_pandas_dtypes(default)
    return {
        "rows": len(default),
        "columns": default.shape[1],
        "default_mib": round(frame_memory_mib(default), 2),
        "optimised_mib": round(frame_memory_mib(optimised), 2),
        "category_columns": int((optimised.dtypes == "category").sum()),
    }


def run_csv_audit(path: Path, profile) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `offna acquire --source csv-head` first")
    watch = Stopwatch()
    with timed(watch, "naive"):
        naive = naive_parse(path)
    with timed(watch, "validated"):
        validated, raw = validated_parse(path, profile.data_dir / "csv_validated.parquet")
    with timed(watch, "memory"):
        memory = wide_memory(raw)
    report = {
        "input": path.name,
        "input_mib": round(path.stat().st_size / 2**20, 1),
        "naive_pandas_skip_bad_lines": naive,
        "field_count_validated": validated,
        "wide_table_memory": memory,
        "timings": watch.laps,
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "csv_audit.json", report)
    return report
