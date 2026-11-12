import pandas as pd
import polars as pl

from offna.aggregates import build_aggregates
from offna.config import Profile
from offna.dashboard import AggregatesMissingError, filter_aggregates, load_aggregates
from offna.database import run_sql_stage
from offna.engines import ENGINES, frames_match
from offna.etl import scan_processed
from offna.model import FEATURES, check_allowlist, product_groups


def test_etl_keeps_rows_and_partitions_by_food_group(demo_profile: Profile) -> None:
    products = scan_processed(demo_profile)
    assert products.select(pl.len()).collect().item() == 10_000
    assert "food_group" in products.collect_schema()
    assert products.filter(pl.col("sugars_100g") > 100).select(pl.len()).collect().item() == 0


def test_all_engines_produce_equal_aggregates(demo_profile: Profile) -> None:
    results = {name: engine(demo_profile.processed_dir) for name, engine in ENGINES.items()}
    reference = results.pop("polars_lazy")
    for country, group in results.values():
        assert frames_match(reference[0], country)[0]
        assert frames_match(reference[1], group)[0]


def test_sql_queries_run_and_return_rows(demo_profile: Profile) -> None:
    report = run_sql_stage(demo_profile)
    assert len(report["queries"]) >= 8
    assert all(query["rows"] > 0 for query in report["queries"].values())
    assert report["table_rows"]["product"] == 9_999


def test_dashboard_reads_aggregates(demo_profile: Profile) -> None:
    build_aggregates(demo_profile)
    tables = load_aggregates(demo_profile)
    selected, grades = filter_aggregates(tables, "france", "(all)")
    assert not selected.empty
    assert set(grades["nutriscore_grade"]) <= set("abcde")


def test_missing_aggregates_raise_friendly_error(tmp_path) -> None:
    empty = Profile("demo", tmp_path / "raw.parquet", tmp_path / "data", tmp_path / "outputs")
    try:
        load_aggregates(empty)
    except AggregatesMissingError as error:
        assert "Run the pipeline first" in str(error)
    else:
        raise AssertionError("expected AggregatesMissingError")


def test_feature_allowlist_has_no_target_leakage() -> None:
    check_allowlist(FEATURES)
    assert not any("grade" in name or "score" in name for name in FEATURES)


def test_groups_join_same_code_and_same_brand_name() -> None:
    frame = pd.DataFrame(
        {
            "code": ["0001", "1", "2", "3"],
            "brand": ["A", "B", "C", "C"],
            "product_name": ["x", "y", "Soup", "soup "],
        }
    )
    groups = product_groups(frame)
    assert groups[0] == groups[1]
    assert groups[2] == groups[3]
    assert groups[0] != groups[2]
