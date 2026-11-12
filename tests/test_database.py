from datetime import UTC, datetime

import polars as pl

from offna.database import deduplicate

EARLY = datetime(2020, 1, 1, tzinfo=UTC)
LATE = datetime(2024, 1, 1, tzinfo=UTC)


def frame(rows: list[tuple[str, datetime | None, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={"code": pl.String, "last_modified_at": pl.Datetime("us", "UTC"), "name": pl.String},
        orient="row",
    )


def duplicates_of(*frames: pl.DataFrame) -> pl.DataFrame:
    combined = pl.concat(frames)
    return (
        combined.group_by("code")
        .agg(pl.len().alias("n"), pl.col("last_modified_at").max().alias("latest"))
        .filter(pl.col("n") > 1)
        .select("code", "latest")
    )


def load_all(*frames: pl.DataFrame) -> pl.DataFrame:
    duplicates, seen = duplicates_of(*frames), set()
    return pl.concat([deduplicate(part, duplicates, seen) for part in frames])


def test_duplicate_code_with_null_timestamps_is_kept_once_across_partitions() -> None:
    kept = load_all(frame([("1", None, "first")]), frame([("1", None, "second")]))
    assert kept["code"].to_list() == ["1"]


def test_latest_version_wins_even_if_seen_later() -> None:
    kept = load_all(frame([("2", EARLY, "old")]), frame([("2", LATE, "new")]))
    assert kept["name"].to_list() == ["new"]


def test_unique_codes_pass_untouched() -> None:
    kept = load_all(frame([("3", EARLY, "a"), ("4", None, "b")]))
    assert sorted(kept["code"].to_list()) == ["3", "4"]
