from pathlib import Path

import polars as pl

from offna.config import CORE_NUTRIENTS, VALID_GRADES, Profile
from offna.etl import empty_list_as_null, scan_processed
from offna.measure import Stopwatch, peak_rss_mib, timed, write_json

MIN_PRODUCTS_PER_COUNTRY = {"demo": 20, "full": 500}
DASHBOARD_TABLES: list[str] = ["country_food_group", "grade_counts"]


def country_pairs(products: pl.LazyFrame) -> pl.LazyFrame:
    return (
        products.with_columns(empty_list_as_null("countries_tags"))
        .explode("countries_tags")
        .with_columns(pl.col("countries_tags").str.replace(r"^en:", "").fill_null("(no country)").alias("country"))
    )


def keep_frequent_countries(pairs: pl.LazyFrame, minimum: int) -> pl.LazyFrame:
    frequent = pairs.group_by("country").len().filter(pl.col("len") >= minimum).select("country")
    return pairs.join(frequent, on="country", how="semi")


def complete_nutrition() -> pl.Expr:
    return pl.all_horizontal(pl.col(column).is_not_null() for column in CORE_NUTRIENTS)


def country_food_group_table(pairs: pl.LazyFrame) -> pl.DataFrame:
    return (
        pairs.group_by("country", "food_group")
        .agg(
            pl.len().alias("products"),
            pl.col("nutriscore_grade").is_not_null().sum().alias("graded"),
            complete_nutrition().mean().alias("complete_nutrition_share"),
            pl.col("has_ingredients_text").mean().alias("ingredients_text_share"),
            (pl.col("allergens_n").fill_null(0) > 0).mean().alias("allergens_listed_share"),
            pl.col("additives_n").mean().alias("additives_mean"),
            *[pl.col(column).mean().alias(f"{column}_mean") for column in CORE_NUTRIENTS],
            *[pl.col(column).count().alias(f"{column}_count") for column in CORE_NUTRIENTS],
        )
        .sort("country", "food_group")
        .collect(engine="streaming")
    )


def grade_counts_table(pairs: pl.LazyFrame) -> pl.DataFrame:
    return (
        pairs.filter(pl.col("nutriscore_grade").is_in(VALID_GRADES))
        .group_by("country", "food_group", "nutriscore_grade")
        .len()
        .rename({"len": "products"})
        .sort("country", "food_group", "nutriscore_grade")
        .collect(engine="streaming")
    )


def write_aggregate(frame: pl.DataFrame, directory: Path, name: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(directory / f"{name}.parquet")
    return {"rows": frame.height, "columns": frame.width}


def build_aggregates(profile: Profile) -> dict:
    watch = Stopwatch()
    pairs = keep_frequent_countries(country_pairs(scan_processed(profile)), MIN_PRODUCTS_PER_COUNTRY[profile.name])
    written = {}
    with timed(watch, "country_food_group"):
        written["country_food_group"] = write_aggregate(
            country_food_group_table(pairs), profile.aggregates_dir, "country_food_group"
        )
    with timed(watch, "grade_counts"):
        written["grade_counts"] = write_aggregate(grade_counts_table(pairs), profile.aggregates_dir, "grade_counts")
    report = {
        "profile": profile.name,
        "unit": "product-country pairs (a product sold in k countries counts k times)",
        "min_products_per_country": MIN_PRODUCTS_PER_COUNTRY[profile.name],
        "tables": written,
        "seconds": round(watch.seconds, 2),
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "aggregates_report.json", report)
    return report
