import shutil
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow.parquet as pq

from offna.categories import category_flag_expressions
from offna.config import (
    GRAMS_PER_100G_NUTRIENTS,
    MAX_ENERGY_KCAL_100G,
    MAX_ENERGY_KJ_100G,
    NUTRIENTS,
    OFF_LAUNCH_YEAR,
    RAW_COLUMNS,
    VALID_GRADES,
    Profile,
)
from offna.measure import Stopwatch, frame_memory_mib, peak_rss_mib, timed, write_json

KJ_PER_KCAL = 4.184
SALT_PER_SODIUM = 2.5
MACRO_SUM_TOLERANCE_G = 105.0
VERSION_TAG_PATTERN = r"^en:nutriscore-2021-([a-e])-2023-([a-e])$"
LOW_CARDINALITY_SHARE = 0.5


def iter_raw_batches(path: Path, batch_rows: int) -> Iterator[pl.DataFrame]:
    try:
        parquet = pq.ParquetFile(path)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"raw snapshot {path} is missing; run `make acquire` or use --profile demo") from error
    for batch in parquet.iter_batches(batch_size=batch_rows, columns=RAW_COLUMNS):
        yield pl.from_arrow(batch)


def flatten_nutriments(frame: pl.DataFrame) -> pl.DataFrame:
    indexed = frame.with_row_index("_row")
    long = (
        indexed.select("_row", "nutriments")
        .explode("nutriments")
        .unnest("nutriments")
        .filter(pl.col("name").is_in(list(NUTRIENTS)))
    )
    wide = long.group_by("_row").agg(
        pl.col("100g").filter(pl.col("name") == source).first().cast(pl.Float32).alias(target)
        for source, target in NUTRIENTS.items()
    )
    return indexed.drop("nutriments").join(wide, on="_row", how="left").sort("_row").drop("_row")


def _first_text(column: str) -> pl.Expr:
    texts = pl.col(column)
    main = texts.list.eval(pl.element().filter(pl.element().struct.field("lang") == "main").struct.field("text"))
    fallback = texts.list.eval(pl.element().struct.field("text"))
    return pl.coalesce(main.list.first(), fallback.list.first())


def _strip_prefix(expr: pl.Expr) -> pl.Expr:
    return expr.str.replace(r"^[a-z]{2}:", "")


def _epoch_to_datetime(column: str) -> pl.Expr:
    return pl.from_epoch(pl.col(column), time_unit="s").dt.replace_time_zone("UTC")


def derive_columns(frame: pl.DataFrame) -> pl.DataFrame:
    grade = pl.col("nutriscore_grade")
    ingredients_known = pl.col("ingredients_n").fill_null(0) > 0
    version_tags = pl.col("misc_tags").list.eval(pl.element().filter(pl.element().str.contains(VERSION_TAG_PATTERN)))
    return frame.with_columns(
        _first_text("product_name").alias("product_name"),
        pl.col("ingredients_text").list.eval(pl.element().struct.field("text").str.len_chars() > 0).list.any()
        .fill_null(False)
        .alias("has_ingredients_text"),
        pl.col("brands").str.split(",").list.first().str.strip_chars().alias("brand"),
        _strip_prefix(pl.col("food_groups_tags").list.get(0, null_on_oob=True)).fill_null("unknown").alias("food_group"),
        _strip_prefix(pl.col("food_groups_tags").list.get(1, null_on_oob=True)).alias("food_group_l2"),
        pl.col("countries_tags").list.len().cast(pl.UInt16).alias("n_countries"),
        pl.col("categories_tags").list.len().cast(pl.UInt16).alias("n_categories"),
        pl.when(grade.is_in(VALID_GRADES)).then(grade).alias("nutriscore_grade"),
        pl.when(grade.is_in(VALID_GRADES)).then(pl.lit("graded")).otherwise(grade.fill_null("missing")).alias(
            "nutriscore_status"
        ),
        pl.col("nutriscore_score").cast(pl.Int16),
        pl.col("nova_group").cast(pl.Int8),
        pl.col("additives_n").cast(pl.Int16),
        pl.col("ingredients_n").cast(pl.Int16),
        pl.col("allergens_tags").list.len().cast(pl.Int16).alias("allergens_n"),
        pl.when(ingredients_known).then(pl.col("with_non_nutritive_sweeteners").fill_null(0)).cast(pl.Int8),
        pl.when(ingredients_known).then(pl.col("with_sweeteners").fill_null(0)).cast(pl.Int8),
        _epoch_to_datetime("created_t").alias("created_at"),
        _epoch_to_datetime("last_modified_t").alias("last_modified_at"),
        version_tags.list.first().str.extract(VERSION_TAG_PATTERN, 1).alias("off_grade_2021"),
        version_tags.list.first().str.extract(VERSION_TAG_PATTERN, 2).alias("off_grade_2023"),
        pl.col("completeness").cast(pl.Float32),
        *category_flag_expressions(),
    ).drop(
        "brands",
        "food_groups_tags",
        "misc_tags",
        "allergens_tags",
        "additives_tags",
        "ingredients_text",
        "with_sweeteners",
        "created_t",
        "last_modified_t",
    )


def harmonise_units(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.coalesce(
            "energy_kj_declared_100g", "energy_100g", pl.col("energy_kcal_100g") * KJ_PER_KCAL
        ).cast(pl.Float32).alias("energy_kj_100g"),
        pl.coalesce("salt_100g", pl.col("sodium_100g") * SALT_PER_SODIUM).cast(pl.Float32).alias("salt_100g"),
    ).drop("energy_kj_declared_100g", "energy_100g")


def quality_rules(snapshot_day: datetime) -> dict[str, pl.Expr]:
    rules: dict[str, pl.Expr] = {
        f"{column}_negative": pl.col(column) < 0 for column in [*GRAMS_PER_100G_NUTRIENTS, "energy_kj_100g"]
    }
    rules.update({f"{column}_over_100g": pl.col(column) > 100 for column in GRAMS_PER_100G_NUTRIENTS})
    rules["energy_kj_over_max"] = pl.col("energy_kj_100g") > MAX_ENERGY_KJ_100G
    rules["energy_kcal_over_max"] = pl.col("energy_kcal_100g") > MAX_ENERGY_KCAL_100G
    rules["saturated_fat_above_fat"] = pl.col("saturated_fat_100g") > pl.col("fat_100g") + 0.1
    rules["sugars_above_carbohydrates"] = pl.col("sugars_100g") > pl.col("carbohydrates_100g") + 0.1
    rules["macros_sum_over_105g"] = (
        pl.sum_horizontal(
            pl.col(["fat_100g", "carbohydrates_100g", "proteins_100g", "fiber_100g", "salt_100g"]).fill_null(0)
        )
        > MACRO_SUM_TOLERANCE_G
    )
    rules["created_before_off_launch"] = pl.col("created_at").dt.year() < OFF_LAUNCH_YEAR
    rules["created_after_snapshot"] = pl.col("created_at") > pl.lit(snapshot_day)
    rules["modified_before_created"] = pl.col("last_modified_at") < pl.col("created_at")
    rules["missing_code"] = pl.col("code").is_null() | (pl.col("code").str.len_chars() == 0)
    return rules


def count_violations(frame: pl.DataFrame, rules: dict[str, pl.Expr]) -> Counter:
    counts = frame.select(rule.fill_null(False).sum().alias(name) for name, rule in rules.items()).row(0, named=True)
    return Counter({name: int(value) for name, value in counts.items()})


def _nullify_when(column: str, condition: pl.Expr) -> pl.Expr:
    return pl.when(condition.fill_null(False)).then(None).otherwise(pl.col(column)).alias(column)


def apply_cleaning(frame: pl.DataFrame, rules: dict[str, pl.Expr]) -> pl.DataFrame:
    impossible_value = [
        _nullify_when(column, rules[f"{column}_negative"] | rules[f"{column}_over_100g"])
        for column in GRAMS_PER_100G_NUTRIENTS
    ]
    energy = [
        _nullify_when("energy_kj_100g", rules["energy_kj_100g_negative"] | rules["energy_kj_over_max"]),
        _nullify_when("energy_kcal_100g", rules["energy_kcal_over_max"] | (pl.col("energy_kcal_100g") < 0)),
    ]
    flags = pl.sum_horizontal(
        rules[name].fill_null(False).cast(pl.UInt8)
        for name in ["saturated_fat_above_fat", "sugars_above_carbohydrates", "macros_sum_over_105g"]
    ).alias("n_consistency_flags")
    bad_date = rules["created_before_off_launch"] | rules["created_after_snapshot"]
    dates = [_nullify_when("created_at", bad_date), _nullify_when("last_modified_at", rules["created_after_snapshot"])]
    return frame.with_columns(flags).with_columns(*impossible_value, *energy, *dates).filter(
        ~rules["missing_code"].fill_null(False)
    ).with_columns(pl.col("created_at").dt.year().cast(pl.Int16).alias("created_year"))


def transform_batch(frame: pl.DataFrame, rules: dict[str, pl.Expr]) -> tuple[pl.DataFrame, Counter]:
    flat = harmonise_units(derive_columns(flatten_nutriments(frame)))
    violations = count_violations(flat, rules)
    return apply_cleaning(flat, rules), violations


def default_pandas_frame(frame: pl.DataFrame) -> pd.DataFrame:
    widened = frame.with_columns(pl.col(pl.Float32).cast(pl.Float64), pl.col(pl.Int8, pl.Int16).cast(pl.Int64))
    return widened.to_pandas(use_pyarrow_extension_array=False).astype(
        {name: object for name, dtype in widened.schema.items() if dtype == pl.String}
    )


def optimise_pandas_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    optimised = frame.copy()
    for column in optimised.columns:
        series = optimised[column]
        if pd.api.types.is_float_dtype(series):
            optimised[column] = pd.to_numeric(series, downcast="float")
        elif pd.api.types.is_integer_dtype(series):
            optimised[column] = pd.to_numeric(series, downcast="integer")
        elif _is_low_cardinality_text(series):
            optimised[column] = series.astype("category")
    return optimised


def _is_low_cardinality_text(series: pd.Series) -> bool:
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False
    try:
        distinct = series.nunique(dropna=True)
    except TypeError:
        return False
    return distinct < LOW_CARDINALITY_SHARE * max(len(series), 1)


def measure_dtype_savings(frame: pl.DataFrame) -> dict:
    default = default_pandas_frame(frame)
    optimised = optimise_pandas_dtypes(default)
    return {
        "rows": len(default),
        "columns": default.shape[1],
        "default_mib": round(frame_memory_mib(default), 2),
        "optimised_mib": round(frame_memory_mib(optimised), 2),
        "optimised_dtypes": {column: str(dtype) for column, dtype in optimised.dtypes.items()},
    }


def write_partitions(frame: pl.DataFrame, output_dir: Path, batch_index: int) -> int:
    files = 0
    for (group,), part in frame.partition_by("food_group", as_dict=True).items():
        target = output_dir / f"food_group={group}"
        target.mkdir(parents=True, exist_ok=True)
        part.drop("food_group").write_parquet(target / f"part-{batch_index:05d}.parquet", compression="zstd")
        files += 1
    return files


def run_etl(profile: Profile, batch_rows: int = 250_000) -> dict:
    output_dir = profile.processed_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    rules = quality_rules(datetime.now(UTC))
    watch, violations = Stopwatch(), Counter()
    rows_in = rows_out = files = 0
    dtype_report: dict = {}
    with timed(watch, "etl_total"):
        for index, batch in enumerate(iter_raw_batches(profile.raw_path, batch_rows)):
            cleaned, batch_violations = transform_batch(batch, rules)
            if index == 0:
                dtype_report = measure_dtype_savings(cleaned)
            violations.update(batch_violations)
            rows_in, rows_out = rows_in + batch.height, rows_out + cleaned.height
            files += write_partitions(cleaned, output_dir, index)
    report = {
        "profile": profile.name,
        "raw_path": str(profile.raw_path.name),
        "batch_rows": batch_rows,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "partition_files": files,
        "partition_column": "food_group",
        "seconds": round(watch.seconds, 2),
        "peak_rss_mib": round(peak_rss_mib(), 1),
        "dtype_first_batch": dtype_report,
        "quality_violations_before_cleaning": dict(sorted(violations.items())),
    }
    write_json(profile.reports_dir / "etl_report.json", report)
    return report


def scan_processed(profile: Profile) -> pl.LazyFrame:
    if not profile.processed_dir.exists():
        raise FileNotFoundError(f"{profile.processed_dir} is missing; run the etl stage first")
    return pl.scan_parquet(profile.processed_dir / "**" / "*.parquet", hive_partitioning=True)
