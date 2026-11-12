from pathlib import Path

import polars as pl

from offna.config import CORE_NUTRIENTS, Profile
from offna.etl import empty_list_as_null, scan_processed
from offna.measure import Stopwatch, peak_rss_mib, read_json, timed, write_json

KEY_FIELDS: list[str] = [*CORE_NUTRIENTS, "nutriscore_grade", "product_name", "brand", "created_at"]
TOP_COUNTRIES = 20
OUTLIER_IQR_FACTOR = 3.0


def missing_share_exprs(fields: list[str]) -> list[pl.Expr]:
    return [pl.col(field).is_null().mean().round(4).alias(field) for field in fields]


def overall_missingness(products: pl.LazyFrame) -> pl.DataFrame:
    extra = [
        (pl.col("categories_tags").list.len() == 0).mean().round(4).alias("categories_tags"),
        (pl.col("countries_tags").list.len() == 0).mean().round(4).alias("countries_tags"),
        (~pl.col("has_ingredients_text")).mean().round(4).alias("ingredients_text"),
        (pl.col("food_group") == "unknown").mean().round(4).alias("food_group"),
    ]
    wide = products.select(*missing_share_exprs(KEY_FIELDS), *extra).collect(engine="streaming")
    return wide.unpivot(variable_name="field", value_name="missing_share").sort("missing_share", descending=True)


def missingness_by_country(products: pl.LazyFrame) -> pl.DataFrame:
    pairs = products.select("code", empty_list_as_null("countries_tags"), *CORE_NUTRIENTS, "nutriscore_grade").explode(
        "countries_tags"
    )
    table = (
        pairs.group_by(pl.col("countries_tags").fill_null("(no country)").alias("country"))
        .agg(
            pl.len().alias("product_country_pairs"),
            *missing_share_exprs([*CORE_NUTRIENTS, "nutriscore_grade"]),
        )
        .sort("product_country_pairs", descending=True)
        .collect(engine="streaming")
    )
    return table.head(TOP_COUNTRIES)


def missingness_by_food_group(products: pl.LazyFrame) -> pl.DataFrame:
    return (
        products.group_by("food_group")
        .agg(pl.len().alias("products"), *missing_share_exprs([*CORE_NUTRIENTS, "nutriscore_grade"]))
        .sort("products", descending=True)
        .collect(engine="streaming")
    )


def duplicate_summary(products: pl.LazyFrame) -> dict:
    by_code = products.group_by("code").agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    name_key = pl.concat_str(
        pl.col("brand").str.to_lowercase().str.strip_chars(),
        pl.col("product_name").str.to_lowercase().str.strip_chars(),
        separator="|",
    )
    by_name = (
        products.filter(pl.col("brand").is_not_null() & pl.col("product_name").is_not_null())
        .group_by(name_key.alias("key"))
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
    )
    codes = by_code.select(pl.len().alias("codes"), pl.col("n").sum().alias("rows")).collect().row(0, named=True)
    names = by_name.select(pl.len().alias("keys"), pl.col("n").sum().alias("rows")).collect().row(0, named=True)
    return {
        "duplicate_codes": codes["codes"],
        "rows_with_duplicate_code": codes["rows"],
        "brand_name_keys_repeated": names["keys"],
        "rows_with_repeated_brand_name": names["rows"],
    }


def outlier_counts(products: pl.LazyFrame) -> pl.DataFrame:
    rows = []
    for column in CORE_NUTRIENTS:
        stats = (
            products.select(
                pl.col(column).quantile(0.25).alias("q1"),
                pl.col(column).quantile(0.75).alias("q3"),
                pl.col(column).max().alias("max"),
            )
            .collect(engine="streaming")
            .row(0, named=True)
        )
        if stats["q1"] is None:
            continue
        upper = stats["q3"] + OUTLIER_IQR_FACTOR * (stats["q3"] - stats["q1"])
        count = products.select((pl.col(column) > upper).sum()).collect(engine="streaming").item()
        rows.append({"nutrient": column, **stats, "upper_fence": upper, "above_fence": count})
    return pl.DataFrame(rows)


def date_summary(products: pl.LazyFrame) -> pl.DataFrame:
    return (
        products.group_by("created_year")
        .agg(
            pl.len().alias("products"),
            pl.col("nutriscore_grade").is_not_null().mean().round(4).alias("graded_share"),
        )
        .sort("created_year")
        .collect(engine="streaming")
    )


def overview(products: pl.LazyFrame) -> dict:
    row = products.select(
        pl.len().alias("rows"),
        pl.col("code").n_unique().alias("unique_codes"),
        pl.col("nutriscore_grade").is_not_null().sum().alias("graded_rows"),
        (pl.col("countries_tags").list.len() > 1).sum().alias("multi_country_rows"),
        pl.col("created_at").min().alias("created_min"),
        pl.col("created_at").max().alias("created_max"),
    ).collect(engine="streaming")
    return row.row(0, named=True)


def grade_distribution(products: pl.LazyFrame) -> pl.DataFrame:
    return (
        products.group_by("nutriscore_status", "nutriscore_grade")
        .len()
        .sort("nutriscore_status", "nutriscore_grade")
        .collect(engine="streaming")
    )


def nutrient_inventory(raw_path: Path) -> pl.DataFrame:
    names = pl.col("nutriments").list.eval(pl.element().struct.field("name")).alias("nutrient")
    per_100g = pl.col("nutriments").list.eval(
        pl.element().filter(pl.element().struct.field("100g").is_not_null()).struct.field("name")
    )
    lazy = pl.scan_parquet(raw_path)
    listed = lazy.select(names).explode("nutrient").group_by("nutrient").agg(pl.len().alias("products_listing"))
    valued = (
        lazy.select(per_100g.alias("nutrient"))
        .explode("nutrient")
        .group_by("nutrient")
        .agg(pl.len().alias("products_with_100g"))
    )
    return (
        listed.join(valued, on="nutrient", how="left")
        .sort("products_listing", descending=True)
        .collect(engine="streaming")
    )


def schema_width(raw_path: Path, inventory: pl.DataFrame) -> dict:
    schema = pl.scan_parquet(raw_path).collect_schema()
    struct_fields = len(schema["nutriments"].inner.fields)
    distinct = inventory.filter(pl.col("nutrient").is_not_null()).height
    return {
        "raw_top_level_columns": len(schema),
        "distinct_nutrient_names": distinct,
        "nutriment_value_fields": struct_fields - 1,
        "fully_flattened_columns": len(schema) - 1 + distinct * (struct_fields - 1),
    }


def write_table(frame: pl.DataFrame, directory: Path, name: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.csv"
    frame.write_csv(path)
    return path.name


def run_audit(profile: Profile) -> dict:
    products = scan_processed(profile)
    audit_dir = profile.output_dir / "audit"
    watch = Stopwatch()
    tables = {
        "missing_overall": overall_missingness,
        "missing_by_country": missingness_by_country,
        "missing_by_food_group": missingness_by_food_group,
        "outliers_iqr": outlier_counts,
        "created_by_year": date_summary,
        "grade_distribution": grade_distribution,
    }
    written = {}
    for name, builder in tables.items():
        with timed(watch, name):
            written[name] = write_table(builder(products), audit_dir, name)
    etl_report = read_json(profile.reports_dir / "etl_report.json")
    with timed(watch, "nutrient_inventory"):
        inventory = nutrient_inventory(profile.raw_path)
        written["nutrient_inventory"] = write_table(inventory, audit_dir, "nutrient_inventory")
    summary = {
        "profile": profile.name,
        "schema_width": schema_width(profile.raw_path, inventory),
        "overview": overview(products),
        "duplicates": duplicate_summary(products),
        "invalid_values_before_cleaning": etl_report["quality_violations_before_cleaning"],
        "tables": written,
        "seconds": round(watch.seconds, 2),
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "audit_summary.json", summary)
    return summary
