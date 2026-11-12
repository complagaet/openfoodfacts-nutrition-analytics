import sqlite3
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import polars as pl

from offna.config import CORE_NUTRIENTS, PROJECT_ROOT, Profile
from offna.etl import scan_processed
from offna.measure import Stopwatch, peak_rss_mib, timed, write_json

SQL_DIR = PROJECT_ROOT / "sql"
INSERT_BATCH_ROWS = 500_000
DB_NUTRIENTS: dict[str, str] = {
    **{column: "kcal" if "kcal" in column else "g" for column in CORE_NUTRIENTS},
    "energy_kj_100g": "kJ",
}
PRODUCT_COLUMNS: list[str] = [
    "product_id",
    "code",
    "product_name",
    "brand",
    "food_group_id",
    "nutriscore_status",
    "nutriscore_grade",
    "nutriscore_score",
    "nova_group",
    "created_year",
    "has_ingredients_text",
    "with_non_nutritive_sweeteners",
    "additives_n",
]


class TagLookup:
    def __init__(self, table: str, id_name: str, value_name: str) -> None:
        self.table, self.id_name, self.value_name = table, id_name, value_name
        self.ids: dict[str, int] = {}

    def register(self, connection: sqlite3.Connection, values: pl.Series) -> pl.DataFrame:
        fresh = [value for value in values.drop_nulls().unique().to_list() if value not in self.ids]
        start = len(self.ids) + 1
        for offset, value in enumerate(fresh):
            self.ids[value] = start + offset
        connection.executemany(
            f"INSERT INTO {self.table} ({self.id_name}, {self.value_name}) VALUES (?, ?)",
            [(self.ids[value], value) for value in fresh],
        )
        return pl.DataFrame(
            {"tag": list(self.ids), self.id_name: list(self.ids.values())},
            schema={"tag": pl.String, self.id_name: pl.Int64},
        )


def latest_versions(profile: Profile) -> pl.DataFrame:
    return (
        scan_processed(profile)
        .group_by("code")
        .agg(pl.len().alias("n"), pl.col("last_modified_at").max().alias("latest"))
        .filter(pl.col("n") > 1)
        .select("code", "latest")
        .collect(engine="streaming")
    )


def deduplicate(frame: pl.DataFrame, duplicates: pl.DataFrame, seen: set[str]) -> pl.DataFrame:
    flagged = frame.join(duplicates.with_columns(pl.lit(True).alias("duplicated")), on="code", how="left")
    is_duplicated = pl.col("duplicated").fill_null(False)
    is_latest = pl.col("latest").is_null() | (pl.col("last_modified_at") == pl.col("latest"))
    keep = flagged.filter(~is_duplicated | is_latest)
    keep = keep.unique(subset="code", keep="first", maintain_order=True)
    keep = keep.filter(~pl.col("code").is_in(list(seen)) if seen else pl.lit(True))
    seen.update(keep.filter(is_duplicated)["code"].to_list())
    return keep.drop("latest", "duplicated")


def link_table(products: pl.DataFrame, list_column: str, lookup: pl.DataFrame, id_name: str) -> pl.DataFrame:
    return (
        products.select("product_id", pl.col(list_column).alias("tag"))
        .explode("tag")
        .drop_nulls("tag")
        .unique()
        .join(lookup, on="tag", how="inner")
        .select("product_id", id_name)
    )


def nutrient_long(products: pl.DataFrame, nutrients: pl.DataFrame) -> pl.DataFrame:
    return (
        products.select("product_id", *DB_NUTRIENTS)
        .unpivot(index="product_id", variable_name="name", value_name="value_100g")
        .drop_nulls("value_100g")
        .filter(pl.col("value_100g") >= 0)
        .join(nutrients.select("nutrient_id", "name"), on="name")
        .select("product_id", "nutrient_id", pl.col("value_100g").cast(pl.Float64))
    )


def iter_rows(frame: pl.DataFrame) -> Iterator[list[tuple]]:
    for start in range(0, frame.height, INSERT_BATCH_ROWS):
        yield frame.slice(start, INSERT_BATCH_ROWS).rows()


def insert(connection: sqlite3.Connection, table: str, frame: pl.DataFrame) -> int:
    placeholders = ", ".join("?" for _ in frame.columns)
    statement = f"INSERT INTO {table} ({', '.join(frame.columns)}) VALUES ({placeholders})"
    for batch in iter_rows(frame):
        connection.executemany(statement, batch)
    return frame.height


def nutrient_dimension() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "nutrient_id": list(range(1, len(DB_NUTRIENTS) + 1)),
            "name": list(DB_NUTRIENTS),
            "unit": list(DB_NUTRIENTS.values()),
        }
    )


def iter_partitions(profile: Profile) -> Iterator[pl.DataFrame]:
    files = sorted(profile.processed_dir.glob("food_group=*/*.parquet"))
    if not files:
        raise FileNotFoundError(f"{profile.processed_dir} is empty; run the etl stage first")
    for path in files:
        group = path.parent.name.split("=", 1)[1]
        yield pl.read_parquet(path).with_columns(pl.lit(group).alias("food_group"))


class Loader:
    def __init__(self, connection: sqlite3.Connection, duplicates: pl.DataFrame) -> None:
        self.connection = connection
        self.duplicates = duplicates
        self.seen: set[str] = set()
        self.next_id = 1
        self.counts: Counter = Counter()
        self.food_groups = TagLookup("food_group", "food_group_id", "name")
        self.countries = TagLookup("country", "country_id", "tag")
        self.categories = TagLookup("category", "category_id", "tag")
        self.nutrients = nutrient_dimension()
        self.counts["nutrient"] = insert(connection, "nutrient", self.nutrients)

    def load(self, frame: pl.DataFrame) -> None:
        products = deduplicate(frame, self.duplicates, self.seen).with_columns(
            pl.int_range(self.next_id, self.next_id + pl.len(), dtype=pl.Int64).alias("product_id"),
            pl.col("has_ingredients_text").cast(pl.Int8),
        )
        self.next_id += products.height
        groups = self.food_groups.register(self.connection, products["food_group"])
        countries = self.countries.register(self.connection, products["countries_tags"].explode())
        categories = self.categories.register(self.connection, products["categories_tags"].explode())
        product_rows = products.join(groups.rename({"tag": "food_group"}), on="food_group").select(PRODUCT_COLUMNS)
        self.counts["product"] += insert(self.connection, "product", product_rows)
        links = link_table(products, "countries_tags", countries, "country_id")
        self.counts["product_country"] += insert(self.connection, "product_country", links)
        links = link_table(products, "categories_tags", categories, "category_id")
        self.counts["product_category"] += insert(self.connection, "product_category", links)
        self.counts["product_nutrient"] += insert(
            self.connection, "product_nutrient", nutrient_long(products, self.nutrients)
        )

    def table_counts(self) -> dict[str, int]:
        dimensions = {
            "food_group": len(self.food_groups.ids),
            "country": len(self.countries.ids),
            "category": len(self.categories.ids),
        }
        return {**dimensions, **self.counts}


def create_database(profile: Profile) -> dict[str, int]:
    path = profile.sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        loader = Loader(connection, latest_versions(profile))
        for frame in iter_partitions(profile):
            loader.load(frame)
        connection.commit()
        connection.executescript((SQL_DIR / "indexes.sql").read_text(encoding="utf-8"))
    return loader.table_counts()


def query_files() -> list[Path]:
    files = sorted(SQL_DIR.glob("q*.sql"))
    if not files:
        raise FileNotFoundError(f"no query files in {SQL_DIR}")
    return files


def run_queries(path: Path, output_dir: Path) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run the sql stage to build it")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    watch = Stopwatch()
    with sqlite3.connect(path) as connection:
        for query_path in query_files():
            with timed(watch, query_path.stem):
                frame = pd.read_sql_query(query_path.read_text(encoding="utf-8"), connection)
            frame.to_csv(output_dir / f"{query_path.stem}.csv", index=False)
            results[query_path.stem] = {"rows": len(frame), "seconds": watch.laps[query_path.stem]}
    return results


def run_sql_stage(profile: Profile) -> dict:
    watch = Stopwatch()
    with timed(watch, "load_sqlite"):
        counts = create_database(profile)
    queries = run_queries(profile.sqlite_path, profile.output_dir / "sql")
    report = {
        "profile": profile.name,
        "database": profile.sqlite_path.name,
        "database_mib": round(profile.sqlite_path.stat().st_size / 2**20, 1),
        "table_rows": counts,
        "queries": queries,
        "timings": watch.laps,
        "peak_rss_mib": round(peak_rss_mib(), 1),
    }
    write_json(profile.reports_dir / "sql_report.json", report)
    return report
