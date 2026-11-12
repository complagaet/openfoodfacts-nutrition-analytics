from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pyarrow.parquet as pq

from offna.config import CORE_NUTRIENTS
from offna.etl import empty_list_as_null

NO_COUNTRY = "(no country)"
BENCH_COLUMNS: list[str] = ["code", "countries_tags", "food_group", *CORE_NUTRIENTS]
CHUNK_ROWS = 200_000


def parquet_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    files = sorted(source.glob("**/*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files under {source}")
    return files


def _finalise_country(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame({"country": frame.index, "pairs": frame["pairs"].to_numpy(dtype=np.int64)})
    for column in CORE_NUTRIENTS:
        result[f"{column}_missing_share"] = frame[f"{column}_nulls"].to_numpy(dtype=float) / result["pairs"]
    return result.sort_values("country").reset_index(drop=True)


def _finalise_group(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame({"food_group": frame.index, "products": frame["products"].to_numpy(dtype=np.int64)})
    for column in CORE_NUTRIENTS:
        counts = frame[f"{column}_count"].to_numpy(dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            result[f"{column}_mean"] = frame[f"{column}_sum"].to_numpy(dtype=float) / counts
    return result.sort_values("food_group").reset_index(drop=True)


def _country_partials(frame: pd.DataFrame) -> pd.DataFrame:
    pairs = frame[["countries_tags", *CORE_NUTRIENTS]].explode("countries_tags")
    pairs["countries_tags"] = pairs["countries_tags"].fillna(NO_COUNTRY).astype(str)
    nulls = pairs[CORE_NUTRIENTS].isna().add_suffix("_nulls")
    nulls["pairs"] = 1
    nulls["country"] = pairs["countries_tags"].to_numpy()
    return nulls.groupby("country", observed=True).sum()


def _group_partials(frame: pd.DataFrame) -> pd.DataFrame:
    values = frame[CORE_NUTRIENTS].astype("float64")
    parts = pd.concat([values.add_suffix("_sum"), values.notna().add_suffix("_count")], axis=1)
    parts["products"] = 1
    parts["food_group"] = frame["food_group"].astype(str).to_numpy()
    return parts.groupby("food_group", observed=True).sum(min_count=0)


def _read_with_partition(path: Path, columns: list[str] | None) -> pd.DataFrame:
    frame = pq.read_table(path, columns=[c for c in columns if c != "food_group"] if columns else None).to_pandas()
    if "food_group" not in frame:
        frame["food_group"] = path.parent.name.split("=", 1)[1]
    return frame


def pandas_default(source: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.concat([_read_with_partition(path, None) for path in parquet_files(source)], ignore_index=True)
    return _finalise_country(_country_partials(frame)), _finalise_group(_group_partials(frame))


def _optimise_chunk(frame: pd.DataFrame) -> pd.DataFrame:
    frame["food_group"] = frame["food_group"].astype("category")
    frame[CORE_NUTRIENTS] = frame[CORE_NUTRIENTS].astype("float32")
    return frame


def iter_optimised_chunks(source: Path):
    for path in parquet_files(source):
        parquet = pq.ParquetFile(path)
        wanted = [column for column in BENCH_COLUMNS if column in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=CHUNK_ROWS, columns=wanted):
            frame = batch.to_pandas()
            if "food_group" not in frame:
                frame["food_group"] = path.parent.name.split("=", 1)[1]
            yield _optimise_chunk(frame)


def pandas_chunked(source: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    country_total: pd.DataFrame | None = None
    group_total: pd.DataFrame | None = None
    for chunk in iter_optimised_chunks(source):
        country, group = _country_partials(chunk), _group_partials(chunk)
        country_total = country if country_total is None else country_total.add(country, fill_value=0)
        group_total = group if group_total is None else group_total.add(group, fill_value=0)
    if country_total is None or group_total is None:
        raise ValueError(f"no rows read from {source}")
    return _finalise_country(country_total), _finalise_group(group_total)


def _scan(source: Path) -> pl.LazyFrame:
    if source.is_file():
        return pl.scan_parquet(source)
    return pl.scan_parquet(source / "**" / "*.parquet", hive_partitioning=True)


def polars_lazy(source: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    lazy = _scan(source).select(BENCH_COLUMNS)
    country = (
        lazy.select(empty_list_as_null("countries_tags"), *CORE_NUTRIENTS)
        .explode("countries_tags")
        .group_by(pl.col("countries_tags").fill_null(NO_COUNTRY).alias("country"))
        .agg(
            pl.len().cast(pl.Int64).alias("pairs"),
            *[(pl.col(column).null_count() / pl.len()).alias(f"{column}_missing_share") for column in CORE_NUTRIENTS],
        )
        .sort("country")
    )
    group = (
        lazy.group_by(pl.col("food_group").cast(pl.String))
        .agg(
            pl.len().cast(pl.Int64).alias("products"),
            *[pl.col(column).cast(pl.Float64).mean().alias(f"{column}_mean") for column in CORE_NUTRIENTS],
        )
        .sort("food_group")
    )
    country_frame, group_frame = pl.collect_all([country, group], engine="streaming")
    return country_frame.to_pandas(), group_frame.to_pandas()


ENGINES: dict[str, Callable[[Path], tuple[pd.DataFrame, pd.DataFrame]]] = {
    "pandas_default": pandas_default,
    "pandas_chunked_optimised": pandas_chunked,
    "polars_lazy": polars_lazy,
}


def frames_match(left: pd.DataFrame, right: pd.DataFrame, rtol: float = 1e-4) -> tuple[bool, float]:
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return False, float("inf")
    worst = 0.0
    for column in left.columns:
        a, b = left[column].to_numpy(), right[column].to_numpy()
        if not np.issubdtype(np.asarray(a).dtype, np.number):
            if not np.array_equal(a.astype(str), b.astype(str)):
                return False, float("inf")
            continue
        a, b = a.astype(float), b.astype(float)
        if not np.allclose(a, b, rtol=rtol, atol=1e-9, equal_nan=True):
            return False, float(np.nanmax(np.abs(a - b)))
        both = ~(np.isnan(a) | np.isnan(b))
        worst = max(worst, float(np.max(np.abs(a[both] - b[both]), initial=0.0)))
    return True, worst
